"""Offline tests for protocol framing, multi-data validation and recovery paths.

No serial hardware or MQTT broker is touched: devices are in-memory fakes and
the paho client / Mnet client are replaced with mocks.
"""
import struct
from unittest.mock import Mock, patch, MagicMock

import pytest

import mnet
from mnet import Mnet, MnetPacket, MnetDecodeError, MnetLoginRejectedError


# ---------------------------------------------------------------- helpers

class FakeDevice:
    """In-memory serial device: read(n) returns at most n of the queued bytes."""

    def __init__(self, data: bytes = b''):
        self.buffer = bytearray(data)
        self.written = []

    def read(self, n: int) -> bytes:
        chunk = bytes(self.buffer[:n])
        del self.buffer[:n]
        return chunk

    def write(self, data: bytes) -> None:
        self.written.append(data)


class ChunkedDevice(FakeDevice):
    """Returns at most `chunk` bytes per read call, like a slow TCP/serial link."""

    def __init__(self, data: bytes = b'', chunk: int = 1):
        super().__init__(data)
        self.chunk = chunk
        self.read_calls = 0

    def read(self, n: int) -> bytes:
        self.read_calls += 1
        return super().read(min(n, self.chunk))


def make_frame(data: bytes = b'\x9c\x43', packet_type: bytes = b'\x0c\x28') -> bytes:
    """A valid wire frame (no 0xFF bytes in data, so escaping is a no-op)."""
    return bytes(MnetPacket(b'\x02', b'\x01', packet_type, len(data), data))


def element(mainid, subid, data_type, conv_type, conv_value, payload):
    return struct.pack('!HHBBHB', mainid, subid, data_type, conv_type, conv_value,
                       len(payload)) + payload


def multi(*elements, count=None):
    count = len(elements) if count is None else count
    return bytes([count]) + b''.join(elements)


WIND = (Mnet.DATA_ID_WIND_SPEED, 0)
GEN = (Mnet.DATA_ID_GEN_REVS, 0)
WIND_EL = element(0x9c43, 0, 0x1, 0x0, 0, struct.pack('!b', 10))
GEN_EL = element(0x9c47, 0, 0x4, 0x1, 1, struct.pack('!H', 1500))


# ------------------------------------------------- Bug #1: frame validation

class TestReadPacketValidation:
    def test_valid_frame_is_returned(self):
        m = Mnet(FakeDevice(make_frame(b'\x9c\x43')))
        packet = m.read_packet()
        assert packet.data == b'\x9c\x43'

    def test_bad_soh_raises(self):
        frame = bytearray(make_frame())
        frame[0] = 0x02
        with pytest.raises(mnet.MnetFrameError, match='SOH'):
            Mnet(FakeDevice(bytes(frame))).read_packet()

    def test_bad_eot_raises(self):
        frame = bytearray(make_frame())
        frame[-1] = 0x05
        with pytest.raises(mnet.MnetFrameError, match='EOT'):
            Mnet(FakeDevice(bytes(frame))).read_packet()

    def test_crc_mismatch_raises(self):
        frame = bytearray(make_frame(b'\x9c\x43'))
        frame[6] ^= 0x01  # flip a payload bit, leave CRC alone
        with pytest.raises(mnet.MnetFrameError, match='CRC'):
            Mnet(FakeDevice(bytes(frame))).read_packet()

    @pytest.mark.parametrize('keep', [0, 3, 5])
    def test_short_header_raises(self, keep):
        with pytest.raises(mnet.MnetFrameError, match='short'):
            Mnet(FakeDevice(make_frame()[:keep])).read_packet()

    def test_short_data_raises(self):
        frame = make_frame(b'\x9c\x43\x00\x01')
        with pytest.raises(mnet.MnetFrameError, match='short'):
            Mnet(FakeDevice(frame[:8])).read_packet()

    def test_short_tail_raises(self):
        with pytest.raises(mnet.MnetFrameError, match='short'):
            Mnet(FakeDevice(make_frame()[:-2])).read_packet()

    def test_empty_payload_frame_is_valid(self):
        m = Mnet(FakeDevice(make_frame(b'')))
        assert m.read_packet().data == b''


class TestReadPacketPartialReads:
    @pytest.mark.parametrize('chunk', [1, 2, 3])
    def test_reassembles_frame_from_small_chunks(self, chunk):
        frame = make_frame(b'\x9c\x43\x00\x01\x02')
        device = ChunkedDevice(frame, chunk=chunk)
        packet = Mnet(device).read_packet()
        assert packet.data == b'\x9c\x43\x00\x01\x02'
        assert device.read_calls > 3  # needed more than one read per section
        assert not device.buffer

    def test_empty_payload_from_small_chunks(self):
        assert Mnet(ChunkedDevice(make_frame(b''), chunk=1)).read_packet().data == b''

    def test_eof_mid_header_raises_instead_of_looping(self):
        device = ChunkedDevice(make_frame()[:3], chunk=1)
        with pytest.raises(mnet.MnetFrameError, match='short header read: 3 of 6'):
            Mnet(device).read_packet()
        assert device.read_calls == 4  # three bytes, then the empty read

    def test_eof_mid_data_raises(self):
        frame = make_frame(b'\x9c\x43\x00\x01')
        with pytest.raises(mnet.MnetFrameError, match='short data read: 2 of 4'):
            Mnet(ChunkedDevice(frame[:8], chunk=2)).read_packet()

    def test_eof_mid_tail_raises(self):
        with pytest.raises(mnet.MnetFrameError, match='short tail read: 1 of 3'):
            Mnet(ChunkedDevice(make_frame()[:-2], chunk=1)).read_packet()

    def test_device_returning_empty_immediately_raises(self):
        with pytest.raises(mnet.MnetFrameError, match='connection closed'):
            Mnet(FakeDevice(b'')).read_packet()


# --------------------------------------------- Bug #2: multi-data validation

class TestDecodeMultipleDataValidation:
    def setup_method(self):
        self.m = Mnet(FakeDevice())

    def test_matching_requests_decode(self):
        res = self.m.decode_multiple_data(multi(WIND_EL, GEN_EL), requests=[WIND, GEN])
        assert [(r[0], r[1]) for r in res] == [(0x9c43, 0), (0x9c47, 0)]
        assert res[1][2][1] == 150.0

    def test_truncated_element_list_raises(self):
        # header claims 2 elements, only 1 present
        with pytest.raises(mnet.MnetDecodeError):
            self.m.decode_multiple_data(multi(WIND_EL, count=2), requests=[WIND, GEN])

    def test_truncated_without_requests_still_raises(self):
        with pytest.raises(mnet.MnetDecodeError):
            self.m.decode_multiple_data(multi(WIND_EL, count=2))

    def test_truncated_mid_element_raises(self):
        with pytest.raises(mnet.MnetDecodeError):
            self.m.decode_multiple_data(multi(WIND_EL, GEN_EL)[:-1], requests=[WIND, GEN])

    def test_fewer_elements_than_requested_raises(self):
        # well-formed reply that simply omits the second item: must not shift data
        with pytest.raises(mnet.MnetDecodeError, match='expected 2'):
            self.m.decode_multiple_data(multi(WIND_EL), requests=[WIND, GEN])

    def test_id_mismatch_raises(self):
        with pytest.raises(mnet.MnetDecodeError, match='mismatch'):
            self.m.decode_multiple_data(multi(GEN_EL, WIND_EL), requests=[WIND, GEN])

    def test_subid_mismatch_raises(self):
        with pytest.raises(mnet.MnetDecodeError, match='mismatch'):
            self.m.decode_multiple_data(multi(WIND_EL), requests=[(Mnet.DATA_ID_WIND_SPEED, 5)])

    def test_request_multiple_data_rejects_shifted_reply(self):
        m = Mnet(FakeDevice())
        m.serial = 1
        m.encoded_serial = bytearray([1, 2, 3, 4, 5])
        reply = Mock(data=m.encode(multi(GEN_EL, WIND_EL), m.encoded_serial))
        with patch.object(m, 'send_packet', return_value=reply):
            with pytest.raises(mnet.MnetDecodeError):
                m.request_multiple_data(b'\x02', [WIND, GEN])

    def test_unknown_conversion_type_raises(self):
        data = struct.pack('!BBHB', 0x1, 0x9, 0, 1) + struct.pack('!b', 1)
        with pytest.raises(ValueError, match='conversion'):
            self.m.decode_data(data)


# ------------------------------------------------ Bug #3/#4: monitor recovery

class StopLoop(BaseException):
    """Escapes `except Exception` so tests can break out of run()."""


@pytest.fixture
def monitor():
    import turbine_monitor as tm
    with patch.object(tm.TurbineMonitor, '_create_device', return_value=Mock()), \
         patch.object(tm.mnet, 'Mnet') as mnet_cls, \
         patch.object(tm.TurbineMonitor, '_setup_mqtt', return_value=Mock()), \
         patch.object(tm.TurbineMonitor, '_setup_command_subscription'), \
         patch.object(tm, 'SocketIO'):
        mnet_cls.return_value.get_serial_number.return_value = (1234, b'\x00\x00\x04\xd2')
        mon = tm.TurbineMonitor('tcp://localhost:1', 'broker.invalid')
    mon.socketio = Mock()
    return mon


@pytest.fixture(autouse=True)
def no_sleep():
    with patch('turbine_monitor.time.sleep'):
        yield


class TestRunRecovery:
    @pytest.mark.parametrize('exc', [
        struct.error('short'),
        ValueError('bad'),
        IndexError('oob'),
        UnicodeDecodeError('ascii', b'\xff', 0, 1, 'bad'),
        mnet.MnetFrameError('crc'),
        mnet.MnetDecodeError('shift'),
    ], ids=lambda e: type(e).__name__)
    def test_protocol_errors_trigger_reconnect(self, monitor, exc):
        monitor._login_to_turbine = Mock()
        monitor._execute_pending_command = Mock()
        monitor._sync_controller_time = Mock()
        monitor._collect_turbine_data = Mock(side_effect=[exc, StopLoop()])
        monitor._reconnect_device = Mock()
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        monitor._reconnect_device.assert_called_once()
        assert monitor.status['connected'] is False


class TestNotLoggedInRecovery:
    def _prep(self, monitor, collect_side_effect):
        monitor._login_to_turbine = Mock()
        monitor._execute_pending_command = Mock()
        monitor._sync_controller_time = Mock()
        monitor._reconnect_device = Mock()
        monitor._collect_turbine_data = Mock(side_effect=collect_side_effect)

    def test_not_logged_in_triggers_relogin(self, monitor):
        import turbine_monitor as tm
        self._prep(monitor, [tm.NotLoggedInError("Cannot collect data: not logged in to controller"),
                             StopLoop()])
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        # mocked login never sets logged_in, so: loop-top login, the NotLoggedInError
        # recovery login, then the loop-top login of the next iteration
        assert monitor._login_to_turbine.call_count == 3
        monitor._reconnect_device.assert_not_called()

    def test_relogin_connection_failure_falls_through_to_reconnect(self, monitor):
        import turbine_monitor as tm
        self._prep(monitor, [tm.NotLoggedInError("not logged in"), StopLoop()])
        monitor._login_to_turbine.side_effect = [None, ConnectionError('down'), None]
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        monitor._reconnect_device.assert_called_once()
        assert monitor.status['connected'] is False

    def test_relogin_protocol_failure_falls_through_to_reconnect(self, monitor):
        import turbine_monitor as tm
        self._prep(monitor, [tm.NotLoggedInError("not logged in"), StopLoop()])
        monitor._login_to_turbine.side_effect = [None, mnet.MnetFrameError('crc'), None]
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        monitor._reconnect_device.assert_called_once()

    @pytest.mark.parametrize('exc', [ConnectionError('down'), mnet.MnetFrameError('crc')],
                             ids=lambda e: type(e).__name__)
    def test_startup_login_failure_does_not_crash_run(self, monitor, exc):
        self._prep(monitor, [StopLoop()])
        monitor._login_to_turbine.side_effect = [exc, None]
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        # reached the loop body (collect) after recovering, instead of crashing at startup
        monitor._reconnect_device.assert_called_once()
        monitor._collect_turbine_data.assert_called_once()

    def test_failed_login_does_not_set_logged_in(self, monitor):
        monitor.logged_in = False
        monitor.mnet_client.login.side_effect = mnet.MnetDecodeError('bad reply')
        with pytest.raises(mnet.MnetDecodeError):
            monitor._login_to_turbine()
        assert monitor.logged_in is False
        assert not monitor.serial_lock.locked()


class TestReconnect:
    def test_reconnect_is_atomic_and_tracks_login(self, monitor):
        seen = {}
        client = monitor.mnet_client
        client.get_serial_number.side_effect = lambda d: (
            seen.setdefault('serial_locked', monitor.serial_lock.locked()),
            seen.setdefault('logged_in_during', monitor.logged_in),
            (99, b'\x00\x00\x00\x63'))[2]
        client.login.side_effect = lambda d: seen.setdefault('login_locked', monitor.serial_lock.locked())
        monitor.logged_in = True

        monitor._reconnect_device()

        assert seen == {'serial_locked': True, 'logged_in_during': False, 'login_locked': True}
        assert monitor.logged_in is True
        assert not monitor.serial_lock.locked()

    def test_failed_reconnect_leaves_logged_out_and_unlocked(self, monitor):
        monitor.logged_in = True
        monitor.mnet_client.get_serial_number.side_effect = OSError('down')
        with pytest.raises(OSError):
            monitor._reconnect_device()
        assert monitor.logged_in is False
        assert not monitor.serial_lock.locked()


class TestRemoteDisplayProtocolErrors:
    @pytest.mark.parametrize('exc', [mnet.MnetFrameError('crc'), mnet.MnetDecodeError('src')],
                             ids=lambda e: type(e).__name__)
    def test_protocol_error_is_reraised_not_swallowed(self, monitor, exc):
        monitor.logged_in = True
        monitor.logger = Mock()
        monitor.mnet_client.get_remote_display.side_effect = exc
        with pytest.raises(type(exc)):
            monitor._collect_turbine_data()
        monitor.mnet_client.request_multiple_data.assert_not_called()
        monitor.logger.error.assert_called()

    def test_protocol_error_in_collect_triggers_reconnect_via_run(self, monitor):
        monitor.logged_in = True
        monitor.mnet_client.get_remote_display.side_effect = mnet.MnetFrameError('crc')
        monitor._execute_pending_command = Mock()
        monitor._sync_controller_time = Mock()
        monitor._publish_data = Mock(side_effect=StopLoop())
        monitor._reconnect_device = Mock()
        monitor._login_to_turbine = Mock()
        # second iteration: reconnect "restored" login, display works, publish stops loop
        def reconnect():
            monitor.mnet_client.get_remote_display.side_effect = None
            monitor.mnet_client.get_remote_display.return_value = b''
            monitor.mnet_client.request_multiple_data.return_value = [0] * 17
        monitor._reconnect_device.side_effect = reconnect
        with patch('turbine_monitor.threading.Thread'), pytest.raises(StopLoop):
            monitor.run()
        monitor._reconnect_device.assert_called_once()
        assert monitor.status['connected'] is False

    def test_non_protocol_display_error_still_degrades_to_empty_display(self, monitor):
        monitor.logged_in = True
        monitor.logger = Mock()
        monitor.mnet_client.get_remote_display.side_effect = KeyError('x')
        monitor.mnet_client.request_multiple_data.return_value = [0] * 17
        data = monitor._collect_turbine_data()
        assert data['remote_display'] == []
        monitor.logger.warning.assert_called()


class TestStatusPayload:
    def test_payload_has_utc_aware_timestamps(self, monitor):
        from datetime import datetime
        monitor.serial_number = 1234
        monitor.mqtt_client.publish.return_value = Mock(rc=1)  # not SUCCESS: skip wait
        monitor.logger = Mock()
        monitor._publish_data({'wind_speed_mps': 0.0})
        sent = monitor.socketio.emit.call_args_list[-1].args
        assert sent[0] == 'status'
        payload = sent[1]
        assert payload['connected'] is True
        for key in ('last_update', 'server_time'):
            assert datetime.fromisoformat(payload[key]).utcoffset() is not None
        assert datetime.fromisoformat(payload['server_time']) >= datetime.fromisoformat(payload['last_update'])

    def test_payload_before_first_data_has_no_last_update(self, monitor):
        payload = monitor._status_payload()
        assert payload['last_update'] is None
        assert payload['connected'] is False
        assert 'server_time' in payload

    def test_payload_does_not_mutate_shared_status(self, monitor):
        monitor._status_payload()
        assert 'server_time' not in monitor.status


class TestTimeSyncProtocolErrors:
    @pytest.mark.parametrize('exc', [mnet.MnetFrameError('crc'), mnet.MnetDecodeError('src')],
                             ids=lambda e: type(e).__name__)
    def test_protocol_error_is_caught_and_backs_off(self, monitor, exc):
        monitor.logger = Mock()
        monitor.mnet_client.set_controller_time.side_effect = exc
        monitor._sync_controller_time()  # must not raise
        monitor._sync_controller_time()  # inside backoff window: no second attempt
        assert monitor.mnet_client.set_controller_time.call_count == 1
        monitor.logger.error.assert_called()
        assert monitor.last_time_sync is None


class TestTimeSyncBackoff:
    def test_failure_defers_next_attempt_and_grows(self, monitor):
        monitor.mnet_client.set_controller_time.side_effect = OSError('nope')
        monitor._sync_controller_time()
        monitor._sync_controller_time()  # inside backoff window: no second call
        assert monitor.mnet_client.set_controller_time.call_count == 1
        first_delay = monitor._time_sync_backoff

        monitor._next_time_sync_attempt = 0.0  # window elapsed
        monitor._sync_controller_time()
        assert monitor.mnet_client.set_controller_time.call_count == 2
        assert monitor._time_sync_backoff > first_delay

    def test_success_resets_backoff(self, monitor):
        monitor.mnet_client.set_controller_time.side_effect = [OSError('x'), None]
        monitor._sync_controller_time()
        monitor._next_time_sync_attempt = 0.0
        monitor._sync_controller_time()
        assert monitor.last_time_sync is not None
        assert monitor._time_sync_backoff == monitor.TIME_SYNC_RETRY_INITIAL


class TestMqttRecovery:
    @pytest.fixture
    def mqtt_monitor(self, monitor):
        import turbine_monitor as tm
        monitor.serial_number = 1234
        with patch.object(tm.mqtt, 'Client') as client_cls:
            client = client_cls.return_value
            built = tm.TurbineMonitor._setup_mqtt(monitor)
        assert built is client
        return monitor, client

    def test_uses_async_connect(self, mqtt_monitor):
        _, client = mqtt_monitor
        client.connect_async.assert_called_once()
        client.connect.assert_not_called()
        client.loop_start.assert_called_once()

    def test_on_connect_resubscribes(self, mqtt_monitor):
        mon, client = mqtt_monitor
        client.on_connect(client, mon, {}, Mock(is_failure=False), None)
        client.subscribe.assert_called_once_with('turbine/1234/command')

    def test_on_connect_failure_does_not_subscribe(self, mqtt_monitor):
        mon, client = mqtt_monitor
        client.on_connect(client, mon, {}, Mock(is_failure=True), None)
        client.subscribe.assert_not_called()

    def test_on_connect_before_serial_known_is_safe(self, mqtt_monitor):
        mon, client = mqtt_monitor
        del mon.serial_number
        client.on_connect(client, mon, {}, Mock(is_failure=False), None)
        client.subscribe.assert_not_called()

    def test_on_disconnect_logs(self, mqtt_monitor):
        mon, client = mqtt_monitor
        mon.logger = Mock()
        client.on_disconnect(client, mon, {}, Mock(is_failure=True), None)
        assert mon.logger.warning.called

    def test_publish_failure_rc_is_not_waited_on(self, monitor):
        import paho.mqtt.client as paho
        monitor.serial_number = 1234
        result = Mock(rc=paho.MQTT_ERR_NO_CONN)
        monitor.mqtt_client.publish.return_value = result
        monitor.logger = Mock()
        monitor._publish_data({'wind_speed_mps': 1.0})
        result.wait_for_publish.assert_not_called()
        assert monitor.logger.warning.called or monitor.logger.error.called

    def test_publish_success_waits(self, monitor):
        import paho.mqtt.client as paho
        monitor.serial_number = 1234
        result = Mock(rc=paho.MQTT_ERR_SUCCESS)
        monitor.mqtt_client.publish.return_value = result
        monitor._publish_data({'wind_speed_mps': 1.0})
        result.wait_for_publish.assert_called_once_with(timeout=monitor.MQTT_PUBLISH_TIMEOUT)

    def test_publish_timeout_offline_warns_and_continues(self, monitor):
        import paho.mqtt.client as paho
        monitor.serial_number = 1234
        monitor.logger = Mock()
        result = Mock(rc=paho.MQTT_ERR_SUCCESS)
        result.is_published.return_value = False  # wait returned on timeout
        monitor.mqtt_client.publish.return_value = result
        monitor._log_mqtt = Mock()
        monitor._publish_data({'wind_speed_mps': 1.0})  # must not raise or block
        monitor.logger.warning.assert_called()
        monitor._log_mqtt.assert_not_called()
        assert monitor.status['connected'] is True  # turbine data is still good
        assert monitor.latest_data == {'wind_speed_mps': 1.0}

    @pytest.mark.parametrize('exc', [ValueError('queue full'), RuntimeError('failed')])
    def test_wait_for_publish_errors_do_not_crash(self, monitor, exc):
        import paho.mqtt.client as paho
        monitor.serial_number = 1234
        monitor.logger = Mock()
        result = Mock(rc=paho.MQTT_ERR_SUCCESS)
        result.wait_for_publish.side_effect = exc
        monitor.mqtt_client.publish.return_value = result
        monitor._publish_data({'wind_speed_mps': 1.0})
        monitor.logger.warning.assert_called()

    def test_publish_confirmed_is_logged(self, monitor):
        import paho.mqtt.client as paho
        monitor.serial_number = 1234
        result = Mock(rc=paho.MQTT_ERR_SUCCESS)
        result.is_published.return_value = True
        monitor.mqtt_client.publish.return_value = result
        monitor._log_mqtt = Mock()
        monitor._publish_data({'wind_speed_mps': 1.0})
        monitor._log_mqtt.assert_called_once()


class TestTransactionIdentityValidation:
    """Test transaction identity validation for protocol robustness."""
    
    def test_send_packet_validates_response_source(self):
        """send_packet should reject responses from unexpected source."""
        mock_device = MagicMock()
        mnet = Mnet(mock_device)
        
        # Setup mock to return packet with wrong source
        bad_response = MagicMock()
        bad_response.source = b'\x99'  # Wrong source
        bad_response.data = b''
        
        mnet.read_packet = MagicMock(return_value=bad_response)
        
        # Should raise MnetDecodeError
        with pytest.raises(MnetDecodeError, match="response source mismatch"):
            mnet.send_packet(b'\x02', b'\x0c\x28', b'')
    
    def test_send_packet_accepts_matching_source(self):
        """send_packet should accept responses from expected source."""
        mock_device = MagicMock()
        mnet = Mnet(mock_device)
        
        # Setup mock to return packet with correct source
        good_response = MagicMock()
        good_response.source = b'\x02'  # Expected source (controller)
        good_response.destination = mnet.id  # Addressed back to us
        # Per docs/MNET.md, Request data (0x0c28) replies with Reply data
        # (0x0c29) -- not an echo of the request type.
        good_response.packet_type = b'\x0c\x29'
        good_response.data = b'test'
        
        mnet.read_packet = MagicMock(return_value=good_response)
        
        result = mnet.send_packet(b'\x02', b'\x0c\x28', b'')
        assert result == good_response

    def test_send_packet_validates_response_destination(self):
        """send_packet should reject replies addressed to someone else."""
        mnet = Mnet(MagicMock())
        bad_response = MagicMock()
        bad_response.source = b'\x02'
        bad_response.destination = b'\x77'  # Not our id
        bad_response.packet_type = b'\x0c\x28'
        mnet.read_packet = MagicMock(return_value=bad_response)

        with pytest.raises(MnetDecodeError, match="response destination mismatch"):
            mnet.send_packet(b'\x02', b'\x0c\x28', b'')

    def test_send_packet_validates_response_packet_type(self):
        """send_packet should reject replies that don't echo the request type."""
        mnet = Mnet(MagicMock())
        bad_response = MagicMock()
        bad_response.source = b'\x02'
        bad_response.destination = mnet.id
        bad_response.packet_type = b'\x0c\x2a'  # Request was 0x0c28
        mnet.read_packet = MagicMock(return_value=bad_response)

        with pytest.raises(MnetDecodeError, match="response packet type mismatch"):
            mnet.send_packet(b'\x02', b'\x0c\x28', b'')

    def test_send_packet_accepts_fully_matching_wire_response(self):
        """A real framed reply (dst=our id, src=controller, documented
        reply type 0x0c29 for a 0x0c28 request) passes."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x29', 2, b'\x9c\x43'))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x0c\x28', b'')
        assert result.data == b'\x9c\x43'

    def test_send_packet_rejects_echoed_reply_when_docs_require_different_type(self):
        """A reply that merely echoes the request type (0x0c28) must be
        rejected for request types with a documented, different reply code
        (0x0c28 -> 0x0c29 per docs/MNET.md); echo is not a valid substitute."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x28', 2, b'\x9c\x43'))
        mnet = Mnet(FakeDevice(frame))

        with pytest.raises(MnetDecodeError, match='packet type mismatch'):
            mnet.send_packet(b'\x02', b'\x0c\x28', b'')

    def test_send_packet_rejects_unrelated_wrong_reply_type(self):
        """An entirely unrelated reply type must still be rejected."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x2d', 2, b'\x9c\x43'))
        mnet = Mnet(FakeDevice(frame))

        with pytest.raises(MnetDecodeError, match='packet type mismatch'):
            mnet.send_packet(b'\x02', b'\x0c\x28', b'')

    def test_send_packet_multiple_data_accepts_documented_reply_type(self):
        """Request multiple data (0x0c2a) -> Reply multiple data (0x0c2b)."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x2b', 1, b'\x00'))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x0c\x2a', b'\x00')
        assert result.packet_type == b'\x0c\x2b'

    def test_send_packet_write_data_accepts_documented_reply_type(self):
        """Request write data (0x0c2c) -> Reply write data (0x0c2d)."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x2d', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x0c\x2c', b'')
        assert result.packet_type == b'\x0c\x2d'

    def test_send_packet_serial_number_accepts_documented_reply_type(self):
        """Request serial no. (0x0c2e) -> Reply serial no. (0x0c2f)."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x0c\x2f', 4, b'\x00\x00\x00\x01'))
        mnet = Mnet(FakeDevice(frame))

        serial, data = mnet.get_serial_number(b'\x02')
        assert serial == 1

    def test_send_packet_ack_alarm_accepts_documented_reply_type(self):
        """Acknowledge alarm (0x0bea) -> Reply Acknowledge (0x0001)."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x00\x01', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x0b\xea', b'')
        assert result.packet_type == b'\x00\x01'

    def test_send_packet_login_standard_accepts_success_echo(self):
        """A successful standard login (0x138e) echoes its own request type."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x13\x8e', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x13\x8e', b'')
        assert result.packet_type == b'\x13\x8e'

    def test_send_packet_login_hidden_accepts_success_echo(self):
        """A successful hidden login (0x13a1) echoes its own request type."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x13\xa1', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        result = mnet.send_packet(b'\x02', b'\x13\xa1', b'')
        assert result.packet_type == b'\x13\xa1'

    def test_send_packet_login_rejected_raises_dedicated_error(self):
        """A well-formed "Remote not logged in" (0x1390) reply to a login
        request is a valid negative acknowledgement -- distinct from a
        successful login and from frame/CRC corruption -- and must raise
        the dedicated MnetLoginRejectedError (a subclass of MnetDecodeError),
        with CRC validation still intact on the wire frame."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x13\x90', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        with pytest.raises(MnetLoginRejectedError):
            mnet.send_packet(b'\x02', b'\x13\x8e', b'')

    def test_send_packet_login_rejected_hidden_login_variant(self):
        """Hidden login (0x13a1) rejection also raises MnetLoginRejectedError."""
        frame = bytes(MnetPacket(b'\x01', b'\x02', b'\x13\x90', 0, b''))
        mnet = Mnet(FakeDevice(frame))

        with pytest.raises(MnetLoginRejectedError):
            mnet.send_packet(b'\x02', b'\x13\xa1', b'')

    def test_send_packet_login_rejected_frame_still_crc_checked(self):
        """A corrupted "not logged in" frame must still fail on CRC, not be
        silently accepted as a valid rejection."""
        frame = bytearray(bytes(MnetPacket(b'\x01', b'\x02', b'\x13\x90', 0, b'')))
        frame[-2] ^= 0x01  # flip a CRC byte
        mnet = Mnet(FakeDevice(bytes(frame)))

        import mnet as mnet_module
        with pytest.raises(mnet_module.MnetFrameError):
            mnet.send_packet(b'\x02', b'\x13\x8e', b'')

    def test_collect_turbine_data_checks_logged_in(self):
        """_collect_turbine_data should raise if not logged in."""
        monitor = MagicMock()
        monitor.logged_in = False
        monitor.serial_lock = MagicMock()
        monitor.serial_lock.__enter__ = MagicMock()
        monitor.serial_lock.__exit__ = MagicMock()
        
        # Bind method to monitor
        from turbine_monitor import TurbineMonitor
        method = TurbineMonitor._collect_turbine_data.__get__(monitor, TurbineMonitor)
        
        with pytest.raises(RuntimeError, match="not logged in"):
            method()
    
    def test_collect_turbine_data_proceeds_when_logged_in(self):
        """_collect_turbine_data should proceed when logged in."""
        monitor = MagicMock()
        monitor.logged_in = True
        monitor.serial_lock = MagicMock()
        monitor.serial_lock.__enter__ = MagicMock()
        monitor.serial_lock.__exit__ = MagicMock()
        monitor.mnet_client = MagicMock()
        monitor.mnet_client.get_remote_display.return_value = b''
        monitor.mnet_client.request_multiple_data.return_value = [0] * 17
        monitor.logger = MagicMock()
        monitor.DESTINATION = b'\x02'
        
        # Bind method to monitor
        from turbine_monitor import TurbineMonitor
        method = TurbineMonitor._collect_turbine_data.__get__(monitor, TurbineMonitor)
        
        # Should not raise
        result = method()
        assert result is not None
        assert 'remote_display' in result
