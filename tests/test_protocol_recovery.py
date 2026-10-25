"""Offline tests for protocol framing, multi-data validation and recovery paths.

No serial hardware or MQTT broker is touched: devices are in-memory fakes and
the paho client / Mnet client are replaced with mocks.
"""
import struct
from unittest.mock import Mock, patch

import pytest

import mnet
from mnet import Mnet, MnetPacket


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
        result.wait_for_publish.assert_called_once()
