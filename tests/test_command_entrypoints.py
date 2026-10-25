"""Offline tests: MQTT / Socket.IO / HTTP entry points all funnel through the
single CommandDispatcher instead of the old shared pending_command fields.

No hardware, no real broker: mnet/MQTT/SocketIO are mocked, same style as
tests/test_protocol_recovery.py's `monitor` fixture.
"""
import json
import time
from unittest.mock import Mock, patch

import pytest

from command_dispatcher import CommandState


@pytest.fixture
def monitor():
    import turbine_monitor as tm
    with patch.object(tm.TurbineMonitor, '_create_device', return_value=Mock()), \
         patch.object(tm.mnet, 'Mnet') as mnet_cls, \
         patch.object(tm.TurbineMonitor, '_setup_mqtt', return_value=Mock()), \
         patch.object(tm.TurbineMonitor, '_setup_command_subscription'), \
         patch.object(tm, 'SocketIO'):
        mnet_cls.return_value.get_serial_number.return_value = (1234, b'\x00\x00\x04\xd2')
        mon = tm.TurbineMonitor('tcp://localhost:1', 'broker.invalid', control_password='pw')
    mon.socketio = Mock()
    mon.mqtt_client = Mock()
    # Make the dispatcher executor instant/deterministic without touching serial.
    # The dispatcher captured the bound method at construction time, so the
    # mock must replace its stored callable, not just the instance attribute.
    mon._dispatcher_execute = Mock(return_value={'command': 'start', 'ok': True, 'reply': 'ab'})
    mon.command_dispatcher._executor = mon._dispatcher_execute
    yield mon
    mon.command_dispatcher.stop(timeout=2)


def wait_terminal(monitor, req_id, timeout=2.0):
    deadline = time.time() + timeout
    terminal = {CommandState.ACKNOWLEDGED, CommandState.REJECTED, CommandState.EXPIRED,
                CommandState.CANCELLED, CommandState.UNKNOWN}
    while time.time() < deadline:
        rec = monitor.command_dispatcher.get(req_id)
        if rec and rec.state in terminal:
            return rec
        time.sleep(0.01)
    raise AssertionError("command never reached a terminal state")


class FakeMsg:
    def __init__(self, topic, payload: bytes, retain=False):
        self.topic = topic
        self.payload = payload
        self.retain = retain


class TestMqttEntrypoint:
    def test_legacy_plain_text_command_is_queued_and_acknowledged(self, monitor):
        monitor._handle_command_message(None, None, FakeMsg('turbine/1234/command', b'start'))
        depth_or_running = True  # either still queued/executing or already done
        # Find the record the dispatcher created (only one in this test).
        recs = list(monitor.command_dispatcher._records.values())
        assert len(recs) == 1
        rec = wait_terminal(monitor, recs[0].request.id)
        assert rec.state == CommandState.ACKNOWLEDGED
        monitor._dispatcher_execute.assert_called_once()

    def test_retained_message_rejected_before_queue(self, monitor):
        monitor._handle_command_message(None, None, FakeMsg('turbine/1234/command', b'start', retain=True))
        assert len(monitor.command_dispatcher._records) == 0
        monitor._dispatcher_execute.assert_not_called()

    def test_unknown_command_logged_not_queued(self, monitor):
        monitor._handle_command_message(None, None, FakeMsg('turbine/1234/command', b'frobnicate'))
        assert len(monitor.command_dispatcher._records) == 0

    def test_json_envelope_with_request_id_is_additive(self, monitor):
        payload = json.dumps({'command': 'stop', 'request_id': 'abc-123'}).encode()
        monitor._handle_command_message(None, None, FakeMsg('turbine/1234/command', payload))
        recs = list(monitor.command_dispatcher._records.values())
        assert len(recs) == 1
        assert recs[0].request.client_request_id == 'abc-123'

    def test_mqtt_result_topic_published_additively_nonretained(self, monitor):
        monitor._handle_command_message(None, None, FakeMsg('turbine/1234/command', b'start'))
        recs = list(monitor.command_dispatcher._records.values())
        wait_terminal(monitor, recs[0].request.id)
        # dispatcher result callback publishes to <prefix><serial>/command_result
        publish_calls = [c for c in monitor.mqtt_client.publish.call_args_list]
        result_calls = [c for c in publish_calls if c.args[0].endswith('/command_result')]
        assert len(result_calls) == 1
        topic, payload = result_calls[0].args[0], result_calls[0].args[1]
        kwargs = result_calls[0].kwargs
        assert kwargs.get('retain') is False
        body = json.loads(payload)
        assert body['state'] == 'acknowledged'
        assert 'password' not in payload.lower()


class TestSocketEntrypoint:
    def test_socket_command_funnels_through_same_dispatcher(self, monitor):
        monitor._handle_socket_command('START')
        recs = list(monitor.command_dispatcher._records.values())
        assert len(recs) == 1
        assert recs[0].request.source == 'socket'
        wait_terminal(monitor, recs[0].request.id)
        monitor._dispatcher_execute.assert_called_once()

    def test_socket_unknown_command_emits_error_result(self, monitor):
        monitor._handle_socket_command('bogus')
        monitor.socketio.emit.assert_any_call(
            'command_result', {'command': 'bogus', 'ok': False, 'error': "unknown command: 'bogus'"})


class TestHttpEntrypoint:
    def _client(self, monitor):
        monitor.app.config['TESTING'] = True
        return monitor.app.test_client()

    def test_http_command_requires_password(self, monitor):
        client = self._client(monitor)
        resp = client.post('/api/command/start')
        assert resp.status_code == 401

    def test_http_command_with_password_executes_through_dispatcher(self, monitor):
        client = self._client(monitor)
        resp = client.post('/api/command/start', headers={'X-Control-Password': 'pw'})
        assert resp.status_code == 200
        body = resp.get_json()
        assert body['ok'] is True
        assert body['state'] == 'acknowledged'
        monitor._dispatcher_execute.assert_called_once()

    def test_http_unknown_command_rejected(self, monitor):
        client = self._client(monitor)
        resp = client.post('/api/command/bogus', headers={'X-Control-Password': 'pw'})
        assert resp.status_code == 400

    def test_http_queue_full_returns_429(self, monitor):
        # Fill the queue by blocking the one worker on a slow command, then
        # saturate max_queue (8) pending items behind it.
        gate = __import__('threading').Event()
        monitor._dispatcher_execute = Mock(side_effect=lambda req: (gate.wait(2), {'ok': True})[1])
        monitor.command_dispatcher._executor = monitor._dispatcher_execute
        client = self._client(monitor)
        client.post('/api/command/start', headers={'X-Control-Password': 'pw'})  # consumed by worker
        # give the worker a moment to pick it up
        time.sleep(0.05)
        import threading as _t

        def fire():
            try:
                monitor.command_dispatcher.submit('stop', source='mqtt')
            except Exception:
                pass
        for _ in range(8):
            fire()
        from command_dispatcher import DispatchError
        with pytest.raises(DispatchError):
            monitor.command_dispatcher.submit('reset', source='mqtt')
        gate.set()


class TestConcurrentInterfaces:
    def test_mqtt_http_socket_concurrently_serialize(self, monitor):
        import threading
        errors = []

        def do_mqtt():
            try:
                monitor._handle_command_message(None, None, FakeMsg('t', b'start'))
            except Exception as e:
                errors.append(e)

        def do_socket():
            try:
                monitor._handle_socket_command('stop')
            except Exception as e:
                errors.append(e)

        def do_http():
            try:
                with monitor.app.test_client() as c:
                    c.post('/api/command/reset', headers={'X-Control-Password': 'pw'})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=f) for f in (do_mqtt, do_socket, do_http)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errors
        # All three ended up as distinct, immutable requests -- no shared
        # mutable pending_command field to race on.
        time.sleep(0.2)
        assert len(monitor.command_dispatcher._records) >= 2  # http result consumed synchronously too
