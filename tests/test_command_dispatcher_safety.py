"""Offline concurrency/safety tests for the command dispatcher hardening.

No hardware, no broker, no network. Real threads, fakes for mnet/MQTT/SocketIO.
"""
import json
import math
import threading
import time
from unittest.mock import Mock, patch

import pytest

from command_dispatcher import (
    CommandDispatcher,
    CommandState,
    DispatchError,
)

COMMAND_MAP = {"start": 1, "stop": 2, "reset": 3}
SECRET = "S3cretPw!"
WRONG = "WrongPw!!"

TERMINAL = {CommandState.ACKNOWLEDGED, CommandState.REJECTED, CommandState.EXPIRED,
            CommandState.CANCELLED, CommandState.UNKNOWN}


def wait_for(predicate, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class ResultSink:
    """Thread-safe on_result collector."""

    def __init__(self):
        self.lock = threading.Lock()
        self.records = []

    def __call__(self, record):
        with self.lock:
            self.records.append((record.request.id, record.request.name, record.state))

    def states_for(self, req_id):
        with self.lock:
            return [s for (i, _, s) in self.records if i == req_id]

    def all(self):
        with self.lock:
            return list(self.records)


def make(executor=None, sink=None, **kw):
    sink = sink if sink is not None else ResultSink()
    if executor is None:
        executor = lambda req: {"ok": True, "reply": "ack"}
    d = CommandDispatcher(COMMAND_MAP, executor, on_result=sink, **kw)
    return d, sink


# --------------------------------------------------------------------------
# ttl / request-id validation, dedupe
# --------------------------------------------------------------------------
class TestValidation:
    @pytest.mark.parametrize("bad", [-1, -0.5, math.nan, math.inf, -math.inf, True, False,
                                     301, 1e9, "5", [1], {"a": 1}, 10 ** 400, -(10 ** 400)])
    def test_invalid_ttl_rejected(self, bad):
        calls = []
        d, sink = make(executor=lambda r: calls.append(r) or {"ok": True})
        d.start()
        try:
            with pytest.raises(DispatchError) as ei:
                d.submit("start", "mqtt", ttl=bad)
            assert ei.value.http_status == 400
            assert d.queue_depth() == 0
            assert not calls
        finally:
            d.stop()

    def test_ttl_zero_expires_immediately_and_never_executes(self):
        calls = []
        d, sink = make(executor=lambda r: calls.append(r) or {"ok": True})
        d.start()
        try:
            rec = d.submit("start", "http", ttl=0)
            assert rec.state == CommandState.EXPIRED
            time.sleep(0.1)
            assert not calls
            assert sink.states_for(rec.request.id) == [CommandState.EXPIRED]
        finally:
            d.stop()

    def test_ttl_none_uses_default_and_valid_ttl_accepted(self):
        d, _ = make(default_ttl=30.0)
        try:
            a = d.submit("start", "mqtt")
            b = d.submit("stop", "mqtt", ttl=300)
            assert a.state == CommandState.QUEUED and b.state == CommandState.QUEUED
            assert a.request.expiry is not None
        finally:
            d.stop()

    @pytest.mark.parametrize("bad", [123, "", "x" * 201, ["a"], True])
    def test_invalid_client_request_id_rejected(self, bad):
        d, _ = make()
        with pytest.raises(DispatchError):
            d.submit("start", "mqtt", client_request_id=bad)
        assert d.queue_depth() == 0

    def test_dedupe_same_name_returns_existing(self):
        d, _ = make()
        a = d.submit("start", "mqtt", client_request_id="rid-1")
        b = d.submit("start", "mqtt", client_request_id="rid-1")
        assert a is b
        assert d.queue_depth() == 1

    def test_dedupe_different_name_conflicts_409(self):
        d, _ = make()
        d.submit("start", "mqtt", client_request_id="rid-1")
        with pytest.raises(DispatchError) as ei:
            d.submit("stop", "mqtt", client_request_id="rid-1")
        assert ei.value.http_status == 409
        assert "conflict" in ei.value.reason
        assert d.queue_depth() == 1


# --------------------------------------------------------------------------
# sync rejects emit a result additively
# --------------------------------------------------------------------------
class TestSyncRejectReporting:
    def test_reject_paths_emit_rejected_and_do_not_touch_state(self):
        d, sink = make()
        d.submit("start", "mqtt", client_request_id="dup")
        before_depth, before_records = d.queue_depth(), len(d._records)
        attempts = [
            dict(name="start", kw=dict(retained=True)),
            dict(name="nonsense", kw={}),
            dict(name="start", kw=dict(ttl=-1)),
            dict(name="stop", kw=dict(client_request_id="dup")),
        ]
        for a in attempts:
            with pytest.raises(DispatchError):
                d.submit(a["name"], "mqtt", **a["kw"])
        rejected = [r for r in sink.all() if r[2] == CommandState.REJECTED]
        assert len(rejected) == len(attempts)
        assert d.queue_depth() == before_depth
        assert len(d._records) == before_records

    def test_queue_full_and_shutdown_rejects_emit(self):
        d, sink = make(max_queue=1)
        d.submit("start", "mqtt")
        with pytest.raises(DispatchError):
            d.submit("stop", "mqtt")
        d.stop()
        with pytest.raises(DispatchError):
            d.submit("stop", "mqtt")
        rejected = [r for r in sink.all() if r[2] == CommandState.REJECTED]
        assert len(rejected) == 2


# --------------------------------------------------------------------------
# result mapping + exactly-once emission
# --------------------------------------------------------------------------
class TestTerminalStates:
    @pytest.mark.parametrize("outcome,expected", [
        ({"ok": True, "reply": "x"}, CommandState.ACKNOWLEDGED),
        ({"ok": False, "reason": "no"}, CommandState.REJECTED),
        ({"ok": False, "expired_before_send": True}, CommandState.EXPIRED),
        (TimeoutError("t"), CommandState.UNKNOWN),
        (RuntimeError("r"), CommandState.REJECTED),
    ])
    def test_executor_outcome_mapping_emits_once(self, outcome, expected):
        def ex(req):
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        d, sink = make(executor=ex)
        d.start()
        try:
            rec = d.submit("start", "mqtt")
            assert wait_for(lambda: len(sink.states_for(rec.request.id)) >= 1)
            time.sleep(0.05)
            assert sink.states_for(rec.request.id) == [expected]
            assert d.get(rec.request.id).state == expected
        finally:
            d.stop()

    def test_expired_in_queue_and_cancel_emit_once(self):
        gate = threading.Event()
        calls = []

        def ex(req):
            calls.append(req.name)
            gate.wait(3)
            return {"ok": True}

        class Clock:
            t = 0.0
            def __call__(self):
                return self.t
        clock = Clock()
        sink = ResultSink()
        d = CommandDispatcher(COMMAND_MAP, ex, on_result=sink, clock=clock)
        d.start()
        try:
            first = d.submit("start", "mqtt")
            assert wait_for(lambda: d.get(first.request.id).state == CommandState.EXECUTING)
            stale = d.submit("stop", "mqtt", ttl=5)
            cancelled = d.submit("reset", "mqtt")
            assert d.cancel(cancelled.request.id) is True
            assert d.cancel(cancelled.request.id) is False
            clock.t += 10
            gate.set()
            assert wait_for(lambda: d.get(stale.request.id).state == CommandState.EXPIRED)
            assert wait_for(lambda: d.get(first.request.id).state == CommandState.ACKNOWLEDGED)
            time.sleep(0.05)
            assert calls == ["start"]
            assert sink.states_for(stale.request.id) == [CommandState.EXPIRED]
            assert sink.states_for(cancelled.request.id) == [CommandState.CANCELLED]
        finally:
            gate.set()
            d.stop()


# --------------------------------------------------------------------------
# callback re-entrancy: lock not held during on_result
# --------------------------------------------------------------------------
class TestCallbackOutsideLock:
    def test_reentrant_callback_does_not_deadlock(self):
        seen = {}
        done = threading.Event()
        holder = {}

        def cb(record):
            if seen.get("first"):
                return
            seen["first"] = True
            d = holder["d"]
            seen["get"] = d.get(record.request.id)
            seen["cancel"] = d.cancel("does-not-exist")
            seen["submit"] = d.submit("stop", "mqtt")
            done.set()

        d = CommandDispatcher(COMMAND_MAP, lambda r: {"ok": True}, on_result=cb)
        holder["d"] = d
        d.start()
        try:
            d.submit("start", "mqtt")
            assert done.wait(3), "callback deadlocked re-entering the dispatcher"
            assert seen["get"] is not None and seen["cancel"] is False
        finally:
            d.stop()

    def test_slow_callback_does_not_block_unrelated_submit(self):
        entered, release = threading.Event(), threading.Event()

        def cb(record):
            if record.request.name == "start":
                entered.set()
                release.wait(3)

        d = CommandDispatcher(COMMAND_MAP, lambda r: {"ok": True}, on_result=cb)
        d.start()
        try:
            d.submit("start", "mqtt")
            assert entered.wait(3)
            out = {}

            def other():
                out["rec"] = d.submit("stop", "http")
                out["depth"] = d.queue_depth()

            t = threading.Thread(target=other)
            t.start()
            t.join(1.0)
            assert not t.is_alive(), "submit blocked while on_result held the lock"
            assert out["rec"].request.name == "stop"
        finally:
            release.set()
            d.stop()

    def test_callback_invoked_without_lock_for_cancel_and_expiry(self):
        flags = []

        def cb(record):
            # lock must be free: a non-blocking acquire proves it
            got = holder["d"]._lock.acquire(blocking=False)
            flags.append(got)
            if got:
                holder["d"]._lock.release()

        holder = {}
        d = CommandDispatcher(COMMAND_MAP, lambda r: {"ok": True}, on_result=cb)
        holder["d"] = d
        rec = d.submit("start", "mqtt")
        d.cancel(rec.request.id)
        d.submit("stop", "mqtt", ttl=0)
        with pytest.raises(DispatchError):
            d.submit("nope", "mqtt")
        d.submit("start", "mqtt")
        d.stop()
        assert flags and all(flags)


# --------------------------------------------------------------------------
# shutdown semantics
# --------------------------------------------------------------------------
class TestShutdown:
    def test_stop_cancels_queued_and_never_sends_them(self):
        gate = threading.Event()
        sent = []

        def ex(req):
            sent.append(req.name)
            gate.wait(3)
            return {"ok": True}

        d, sink = make(executor=ex)
        d.start()
        try:
            running = d.submit("start", "mqtt")
            assert wait_for(lambda: d.get(running.request.id).state == CommandState.EXECUTING)
            queued = [d.submit("stop", "mqtt"), d.submit("reset", "mqtt"), d.submit("stop", "http")]
            stopped = d.stop(timeout=0.1)  # worker still busy with the in-flight one
            assert stopped is False
            for q in queued:
                assert d.get(q.request.id).state == CommandState.CANCELLED
                assert sink.states_for(q.request.id) == [CommandState.CANCELLED]
                assert d.get(q.request.id).result["reason"] == "dispatcher shutting down"
            gate.set()
            assert wait_for(lambda: d.get(running.request.id).state == CommandState.ACKNOWLEDGED)
            assert wait_for(lambda: not d._worker.is_alive())
            assert sent == ["start"]  # queued commands never reached the executor
            for q in queued:
                assert sink.states_for(q.request.id) == [CommandState.CANCELLED]  # still once
        finally:
            gate.set()

    def test_submit_after_stop_rejected_503(self):
        d, _ = make()
        d.start()
        d.stop()
        with pytest.raises(DispatchError) as ei:
            d.submit("start", "mqtt")
        assert ei.value.http_status == 503


# --------------------------------------------------------------------------
# records bound never evicts live commands
# --------------------------------------------------------------------------
class TestTrim:
    def test_burst_of_terminal_records_never_evicts_queued_or_executing(self):
        gate = threading.Event()

        def ex(req):
            gate.wait(5)
            return {"ok": True}

        d, _ = make(executor=ex)
        d.start()
        try:
            executing = d.submit("start", "mqtt")
            assert wait_for(lambda: d.get(executing.request.id).state == CommandState.EXECUTING)
            queued = d.submit("stop", "mqtt")
            for _ in range(700):  # each stored as EXPIRED
                d.submit("reset", "mqtt", ttl=0)
            assert d.get(executing.request.id) is not None
            assert d.get(queued.request.id) is not None
            assert d.get(queued.request.id).state == CommandState.QUEUED
            assert len(d._records) <= 513
        finally:
            gate.set()
            d.stop()

    def test_trim_keeps_live_even_if_over_bound(self):
        d, _ = make(max_queue=1000)
        live = [d.submit("start", "mqtt") for _ in range(600)]
        assert all(d.get(r.request.id) is not None for r in live)


# --------------------------------------------------------------------------
# monitor-level tests (HTTP race, serial_lock expiry, phases, socket auth)
# --------------------------------------------------------------------------
def build_monitor(password=SECRET, on_subscribe=None):
    import turbine_monitor as tm

    def fake_subscribe(self):
        if on_subscribe:
            on_subscribe(self)

    with patch.object(tm.TurbineMonitor, '_create_device', return_value=Mock()), \
         patch.object(tm.mnet, 'Mnet') as mnet_cls, \
         patch.object(tm.TurbineMonitor, '_setup_mqtt', return_value=Mock()), \
         patch.object(tm.TurbineMonitor, '_setup_command_subscription', fake_subscribe), \
         patch.object(tm, 'SocketIO'):
        mnet_cls.return_value.get_serial_number.return_value = (1234, b'\x00\x00\x04\xd2')
        mon = tm.TurbineMonitor('tcp://localhost:1', 'broker.invalid', control_password=password)
    mon.socketio = Mock()
    mon.mqtt_client = Mock()
    mon.mnet_client = Mock()
    mon.INTER_REQUEST_DELAY = 0.0
    mon.logger = Mock()
    return mon


@pytest.fixture
def monitor():
    mon = build_monitor()
    yield mon
    mon.command_dispatcher.stop(timeout=2)


def use_real_executor(mon):
    import turbine_monitor as tm
    mon.command_dispatcher._executor = lambda req: tm.TurbineMonitor._dispatcher_execute(mon, req)


def wait_terminal(mon, req_id, timeout=3.0):
    assert wait_for(lambda: mon.command_dispatcher.get(req_id).state in TERMINAL, timeout)
    return mon.command_dispatcher.get(req_id)


def only_record(mon):
    recs = list(mon.command_dispatcher._records.values())
    assert len(recs) == 1
    return recs[0]


def good_reply():
    return Mock(packet_type=b'\x0c\x32')


class TestStartupAndClose:
    def test_dispatcher_started_only_after_init_complete(self):
        seen = {}

        def on_sub(self):
            seen['worker_at_subscribe'] = self.command_dispatcher._worker
            seen['mnet_ready'] = hasattr(self, 'mnet_client') and hasattr(self, 'mqtt_client')

        mon = build_monitor(on_subscribe=on_sub)
        try:
            assert seen['worker_at_subscribe'] is None
            assert seen['mnet_ready'] is True
            assert mon.command_dispatcher._worker.is_alive()
        finally:
            mon.command_dispatcher.stop(timeout=2)

    def test_close_stops_dispatcher_before_closing_resources(self, monitor):
        order = []
        real_stop = monitor.command_dispatcher.stop
        monitor.command_dispatcher.stop = lambda *a, **k: (order.append('stop'), real_stop(*a, **k))[1]
        monitor.mqtt_client.disconnect.side_effect = lambda *a, **k: order.append('mqtt')
        monitor.serial_device.close.side_effect = lambda *a, **k: order.append('serial')
        monitor.close()
        assert order == ['stop', 'mqtt', 'serial']


class TestExecutorPhases:
    def _run(self, mon, name='start', **kw):
        use_real_executor(mon)
        rec = mon.command_dispatcher.submit(name, 'mqtt', **kw)
        return wait_terminal(mon, rec.request.id)

    def test_success_is_acknowledged_with_reply(self, monitor):
        monitor.mnet_client.send_command.return_value = good_reply()
        rec = self._run(monitor)
        assert rec.state == CommandState.ACKNOWLEDGED
        assert rec.result['reply'] == '0c32'

    def test_observed_0001_ack_is_acknowledged_not_unknown(self, monitor):
        """Two live RESET attempts on 2026-10-25 (22:39:26 and 22:41:32 UTC)
        showed this controller replying 0x0001 (Reply Acknowledge) to
        REQ_COMMAND instead of echoing 0x0C32 -- the same quirk already
        fixed for both logins. This mirrors the pre-hardening behaviour
        where ANY syntactically valid command reply counted as success,
        restored narrowly for this one additional reply type rather than
        reverted to accepting anything."""
        monitor.mnet_client.send_command.return_value = Mock(packet_type=b'\x00\x01')
        rec = self._run(monitor)
        assert rec.state == CommandState.ACKNOWLEDGED
        assert rec.result['reply'] == '0001'

    def test_login_failure_before_send_is_rejected_never_sent(self, monitor):
        monitor.mnet_client.login_standard.side_effect = RuntimeError('bad password')
        rec = self._run(monitor)
        assert rec.state == CommandState.REJECTED
        monitor.mnet_client.send_command.assert_not_called()
        monitor.mnet_client.login.assert_called()  # reverted to hidden login

    @pytest.mark.parametrize("exc", [TimeoutError('read timeout'), OSError('io'), ValueError('x')])
    def test_failure_after_send_is_unknown(self, monitor, exc):
        monitor.mnet_client.send_command.side_effect = exc
        rec = self._run(monitor)
        assert rec.state == CommandState.UNKNOWN
        assert rec.state not in (CommandState.REJECTED, CommandState.ACKNOWLEDGED)

    @pytest.mark.parametrize("reply", [Mock(packet_type=b'\x13\x90'), Mock(packet_type=None),
                                       Mock(packet_type='0c32'), None])
    def test_wrongly_typed_reply_is_unknown_not_acknowledged(self, monitor, reply):
        monitor.mnet_client.send_command.return_value = reply
        rec = self._run(monitor)
        assert rec.state == CommandState.UNKNOWN

    def test_failed_revert_marks_login_state_unknown(self, monitor):
        monitor.logged_in = True
        monitor.mnet_client.send_command.return_value = good_reply()
        monitor.mnet_client.login.side_effect = RuntimeError('line dropped')
        rec = self._run(monitor)
        assert rec.state == CommandState.ACKNOWLEDGED
        assert monitor.logged_in is False

    def test_held_serial_lock_past_ttl_means_no_send_and_expired(self, monitor):
        use_real_executor(monitor)
        monitor.mnet_client.send_command.return_value = good_reply()
        monitor.serial_lock.acquire()
        try:
            rec = monitor.command_dispatcher.submit('start', 'mqtt', ttl=0.3)
            assert wait_for(lambda: monitor.command_dispatcher.get(rec.request.id).state
                            == CommandState.EXECUTING)
            time.sleep(0.5)  # deadline passes while blocked on serial_lock
        finally:
            monitor.serial_lock.release()
        final = wait_terminal(monitor, rec.request.id)
        assert final.state == CommandState.EXPIRED
        monitor.mnet_client.send_command.assert_not_called()
        monitor.mnet_client.login.assert_called()  # reverted to hidden

    def test_shutdown_while_waiting_for_lock_prevents_send(self, monitor):
        use_real_executor(monitor)
        monitor.mnet_client.send_command.return_value = good_reply()
        monitor.serial_lock.acquire()
        try:
            rec = monitor.command_dispatcher.submit('start', 'mqtt')
            assert wait_for(lambda: monitor.command_dispatcher.get(rec.request.id).state
                            == CommandState.EXECUTING)
            monitor.command_dispatcher.stop(timeout=0.1)
        finally:
            monitor.serial_lock.release()
        final = wait_terminal(monitor, rec.request.id)
        assert final.state == CommandState.CANCELLED
        monitor.mnet_client.send_command.assert_not_called()


class TestHttpTimeoutRace:
    def _client(self, mon):
        mon.app.config['TESTING'] = True
        mon.http_command_wait = 0.3
        return mon.app.test_client()

    def test_timeout_while_queued_cancels_and_reports_cancelled(self, monitor):
        gate = threading.Event()
        sent = []

        def ex(req):
            sent.append(req.name)
            gate.wait(5)
            return {'ok': True}

        monitor.command_dispatcher._executor = ex
        blocker = monitor.command_dispatcher.submit('stop', 'mqtt')
        assert wait_for(lambda: monitor.command_dispatcher.get(blocker.request.id).state
                        == CommandState.EXECUTING)
        resp = self._client(monitor).post('/api/command/start')
        body = resp.get_json()
        assert resp.status_code == 504
        assert body['state'] == 'cancelled' and body['ok'] is False
        gate.set()
        wait_terminal(monitor, blocker.request.id)
        time.sleep(0.1)
        assert sent == ['stop']  # the cancelled command never executed

    def test_timeout_while_executing_reports_executing_and_not_cancelled(self, monitor):
        gate = threading.Event()
        monitor.command_dispatcher._executor = lambda req: (gate.wait(5), {'ok': True})[1]
        resp = self._client(monitor).post('/api/command/start')
        body = resp.get_json()
        assert resp.status_code == 504
        assert body['state'] == 'executing' and body['ok'] is False
        assert 'may still take effect' in body['error']
        gate.set()
        assert wait_terminal(monitor, body['id']).state == CommandState.ACKNOWLEDGED

    def test_command_finishing_in_race_window_reports_real_result(self, monitor):
        gate = threading.Event()
        monitor.command_dispatcher._executor = lambda req: (gate.wait(5), {'ok': True, 'reply': 'r'})[1]
        real_cancel = monitor.command_dispatcher.cancel

        def racing_cancel(rid):
            gate.set()  # command completes between timeout and cancel
            assert wait_for(lambda: monitor.command_dispatcher.get(rid).state in TERMINAL)
            return real_cancel(rid)

        monitor.command_dispatcher.cancel = racing_cancel
        resp = self._client(monitor).post('/api/command/start')
        body = resp.get_json()
        assert resp.status_code == 200
        assert body['state'] == 'acknowledged' and body['ok'] is True


class TestSocketAuthAndLegacy:
    def test_dict_without_password_executes(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        monitor._handle_socket_command({'command': 'start'})
        rec = only_record(monitor)
        assert wait_terminal(monitor, rec.request.id).state == CommandState.ACKNOWLEDGED
        assert SECRET not in repr(monitor.socketio.emit.call_args_list)
        assert SECRET not in repr(monitor.logger.method_calls)

    def test_caller_supplied_password_is_ignored_and_never_leaks(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        monitor._handle_socket_command({'command': 'start', 'password': WRONG})
        rec = only_record(monitor)
        assert wait_terminal(monitor, rec.request.id).state == CommandState.ACKNOWLEDGED
        time.sleep(0.1)
        blob = repr(monitor.socketio.emit.call_args_list) + repr(monitor.logger.method_calls) \
            + repr(monitor.mqtt_client.publish.call_args_list) + repr(rec.to_result_dict()) \
            + repr(rec.result)
        assert WRONG not in blob
        assert SECRET not in blob

    def test_bare_string_accepted(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        monitor._handle_socket_command('START')
        rec = only_record(monitor)
        assert rec.request.name == 'start' and rec.request.source == 'socket'
        assert wait_terminal(monitor, rec.request.id).state == CommandState.ACKNOWLEDGED

    def test_envelope_request_id_and_ttl_honoured(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True})
        monitor._handle_socket_command({'command': 'start', 'request_id': 'rid-1', 'ttl': 30})
        rec = only_record(monitor)
        assert wait_terminal(monitor, rec.request.id).state == CommandState.ACKNOWLEDGED

    def test_missing_server_password_disables_controls(self):
        mon = build_monitor(password=None)
        try:
            mon._handle_socket_command({'command': 'start', 'password': WRONG})
            rec = only_record(mon)
            wait_terminal(mon, rec.request.id)
            assert mon.mnet_client.login_standard.call_count == 0
            assert WRONG not in repr(mon.socketio.emit.call_args_list) + repr(mon.logger.method_calls)
            assert rec.state != CommandState.ACKNOWLEDGED
        finally:
            mon.command_dispatcher.stop(timeout=2)

    def test_legacy_socket_result_shapes(self, monitor):
        # MQTT keeps its unauthenticated plain-text legacy shape (tested
        # separately below); socket results keep their legacy shape too.
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        monitor._handle_socket_command({'command': 'start'})
        wait_terminal(monitor, only_record(monitor).request.id)
        monitor.socketio.emit.assert_any_call('command_result',
                                              {'command': 'start', 'ok': True, 'reply': 'ab'})
        monitor._handle_socket_command({'command': 'bogus'})
        calls = [c for c in monitor.socketio.emit.call_args_list
                 if c.args[1].get('command') == 'bogus']
        assert len(calls) == 1  # exactly one rejection event, not duplicated
        assert calls[0].args[1] == {'command': 'bogus', 'ok': False,
                                    'error': "unknown command: 'bogus'"}


class TestMqttAndHttpLegacy:
    class Msg:
        def __init__(self, payload, retain=False):
            self.topic = 'turbine/1234/command'
            self.payload = payload
            self.retain = retain

    def test_plain_text_mqtt_unchanged(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        monitor._handle_command_message(None, None, self.Msg(b'  Start \n'))
        rec = only_record(monitor)
        assert rec.request.name == 'start' and rec.request.source == 'mqtt'
        assert wait_terminal(monitor, rec.request.id).state == CommandState.ACKNOWLEDGED

    def test_retained_message_additively_reports_and_leaves_queue_alone(self, monitor):
        ex = Mock(return_value={'ok': True})
        monitor.command_dispatcher._executor = ex
        monitor._handle_command_message(None, None, self.Msg(b'start', retain=True))
        assert monitor.command_dispatcher.queue_depth() == 0
        assert not monitor.command_dispatcher._records
        ex.assert_not_called()
        monitor.socketio.emit.assert_any_call(
            'command_result',
            {'command': 'start', 'ok': False,
             'error': monitor.last_command_result['error']})
        assert 'retained' in monitor.last_command_result['error']
        pubs = [c for c in monitor.mqtt_client.publish.call_args_list
                if c.args[0].endswith('/command_result')]
        assert len(pubs) == 1
        body = json.loads(pubs[0].args[1])
        assert body['state'] == 'rejected'
        assert pubs[0].kwargs.get('retain') is False

    def test_http_response_shape_unchanged(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'command': 'start', 'ok': True,
                                                                   'reply': 'ab'})
        monitor.app.config['TESTING'] = True
        resp = monitor.app.test_client().post('/api/command/start')
        body = resp.get_json()
        assert resp.status_code == 200
        assert {'command', 'ok', 'reply', 'state', 'id'} <= set(body)
        assert body['ok'] is True and body['state'] == 'acknowledged'

    def test_no_secret_in_any_output_across_paths(self, monitor):
        monitor.command_dispatcher._executor = Mock(return_value={'ok': True, 'reply': 'ab'})
        client = monitor.app.test_client()
        monitor.app.config['TESTING'] = True
        responses = [
            client.post('/api/command/start'),
            client.post('/api/command/start', headers={'X-Control-Password': WRONG}),
            client.post('/api/command/start', json={'password': WRONG}),
            client.post('/api/command/bogus', headers={'X-Control-Password': WRONG}),
        ]
        monitor._handle_socket_command({'command': 'stop'})
        monitor._handle_socket_command({'command': 'stop', 'password': WRONG})
        monitor._handle_command_message(None, None, self.Msg(b'start', retain=True))
        time.sleep(0.2)
        blob = repr(monitor.socketio.emit.call_args_list) + repr(monitor.mqtt_client.publish.call_args_list) \
            + repr(monitor.logger.method_calls) + repr([r.get_data(as_text=True) for r in responses])
        for rec in monitor.command_dispatcher._records.values():
            blob += repr(rec.to_result_dict()) + repr(rec.result)
        assert SECRET not in blob
        assert WRONG not in blob



class TestSocketRealTransportTargeting:
    """Real flask_socketio test clients (no mocked SocketIO), proving the
    unauthorized/invalid-payload reply goes only to the requesting
    connection and is never broadcast to an unrelated bystander socket.
    No hardware, no broker, no real network: flask_socketio's in-process
    test client."""

    @pytest.fixture
    def real_monitor(self):
        import turbine_monitor as tm
        with patch.object(tm.TurbineMonitor, '_create_device', return_value=Mock()), \
             patch.object(tm.mnet, 'Mnet') as mnet_cls, \
             patch.object(tm.TurbineMonitor, '_setup_mqtt', return_value=Mock()), \
             patch.object(tm.TurbineMonitor, '_setup_command_subscription'):
            mnet_cls.return_value.get_serial_number.return_value = (1234, b'\x00\x00\x04\xd2')
            mon = tm.TurbineMonitor('tcp://localhost:1', 'broker.invalid', control_password=SECRET)
        mon.mqtt_client = Mock()
        mon._dispatcher_execute = Mock(return_value={'ok': True, 'reply': 'ab'})
        mon.command_dispatcher._executor = mon._dispatcher_execute
        yield mon
        mon.command_dispatcher.stop(timeout=2)

    def _received(self, client):
        return [m for m in client.get_received() if m['name'] == 'command_result']

    def test_invalid_payload_reply_not_broadcast_to_bystander(self, real_monitor):
        bystander = real_monitor.socketio.test_client(real_monitor.app)
        actor = real_monitor.socketio.test_client(real_monitor.app)
        try:
            bystander.get_received()  # drain connect-time emits
            actor.get_received()

            actor.emit('command', 12345)

            actor_results = self._received(actor)
            bystander_results = self._received(bystander)

            assert len(actor_results) == 1
            assert actor_results[0]['args'][0]['ok'] is False
            # The rejection must reach only the requester, never the
            # bystander connection.
            assert bystander_results == []
            assert not real_monitor.command_dispatcher._records
            real_monitor._dispatcher_execute.assert_not_called()
        finally:
            actor.disconnect()
            bystander.disconnect()

    def test_bare_string_executes_over_real_transport(self, real_monitor):
        actor = real_monitor.socketio.test_client(real_monitor.app)
        try:
            actor.get_received()
            actor.emit('command', 'start')
            deadline = time.time() + 2.0
            results = []
            while time.time() < deadline and not results:
                time.sleep(0.02)
                results = self._received(actor)
            assert results and results[0]['args'][0]['ok'] is True
        finally:
            actor.disconnect()

    def test_command_executes_over_real_transport_ignoring_caller_password(self, real_monitor):
        actor = real_monitor.socketio.test_client(real_monitor.app)
        try:
            actor.get_received()
            actor.emit('command', {'command': 'start', 'password': WRONG})
            deadline = time.time() + 2.0
            results = []
            while time.time() < deadline and not results:
                time.sleep(0.02)
                results = self._received(actor)
            assert results and results[0]['args'][0]['ok'] is True
            assert SECRET not in repr(results)
        finally:
            actor.disconnect()
