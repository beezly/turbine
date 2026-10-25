"""Tests for the simulated controller behind `turbine_monitor.py --demo`.

The simulator is driven through the real mnet.Mnet client, so these also
check that its replies are valid M-net frames the client accepts.
"""

import pytest

import mnet
from demo_controller import SimulatedController, RUN, STOPPED, FAULTS

DEST = b'\x02'


class FakeClock:
    def __init__(self, now=1_790_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def controller(clock):
    return SimulatedController(seed=42, clock=clock)


@pytest.fixture
def client(controller):
    client = mnet.Mnet(controller)
    client.login(DEST)
    return client


def test_serial_number(client):
    serial, _ = client.get_serial_number(DEST)
    assert serial == SimulatedController.SERIAL_NUMBER


def test_monitor_batch_decodes(client):
    """The 17-item batch TurbineMonitor polls fits one frame and decodes sanely."""
    M = mnet.Mnet
    requests = [
        (M.DATA_ID_WIND_SPEED, 0), (M.DATA_ID_ROTOR_REVS, 0), (M.DATA_ID_GEN_REVS, 0),
        (M.DATA_ID_GRID_POWER, 0), (M.DATA_ID_L1V, 0), (M.DATA_ID_L2V, 0), (M.DATA_ID_L3V, 0),
        (M.DATA_ID_EVENT_STACK_STATUS_CODE, M.EVENT_STACK_SUBID_TEXT),
        (M.DATA_ID_CONTROLLER_TIME, 0),
        (M.DATA_ID_CURRENT_STATUS_CODE, 0), (M.DATA_ID_CURRENT_STATUS_CODE, 1),
        (M.DATA_ID_GRID_POWER, M.DATA_AVERAGING_10MIN),
        (M.DATA_ID_L1V, M.DATA_AVERAGING_1MIN), (M.DATA_ID_L2V, M.DATA_AVERAGING_1MIN),
        (M.DATA_ID_L3V, M.DATA_AVERAGING_1MIN),
        (M.DATA_ID_RUNTIME_1, 0), (M.DATA_ID_RUNTIME_2, 0),
    ]
    results = client.request_multiple_data(DEST, requests)

    assert len(results) == 17
    assert 0 <= results[0] < 40
    assert results[2] == pytest.approx(results[1] * 18, abs=1)
    assert all(220 < v < 240 for v in results[4:7])
    assert results[7] == RUN[1]
    assert len(results[8]) == 12  # YYMMDDHHMMSS
    assert results[9] == RUN[0]
    assert isinstance(results[15], int) and isinstance(results[16], int)


def test_unknown_data_id_is_none(client):
    assert client.request_data(DEST, b'\x12\x34', 0) is None


def test_set_controller_time(client, clock):
    import datetime
    target = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
    client.set_controller_time(DEST, target)
    assert client.get_controller_time(DEST) == target


def test_stop_and_start_commands(client, controller, clock):
    client.login_standard(DEST, 'anything')
    reply = client.send_command(DEST, mnet.Mnet.DATA_ID_STOP)
    assert reply.packet_type == mnet.Mnet.REPLY_ACK
    assert controller.state == STOPPED

    clock.now += 30
    assert client.request_data(DEST, mnet.Mnet.DATA_ID_ROTOR_REVS) < 1.0
    assert client.request_data(DEST, mnet.Mnet.DATA_ID_GRID_POWER) == 0
    assert client.get_events_batch(DEST, limit=1)[0].text == STOPPED[1]

    client.send_command(DEST, mnet.Mnet.DATA_ID_START)
    assert controller.state != STOPPED
    assert client.get_events_batch(DEST, limit=2)[1].text == 'Start via communica.'


def test_reset_clears_fault(client, controller):
    controller._set_state(FAULTS[0])
    client.send_command(DEST, mnet.Mnet.DATA_ID_STOP)
    assert controller.state == STOPPED  # a stop still works during a fault
    controller._set_state(FAULTS[0])
    client.send_command(DEST, mnet.Mnet.DATA_ID_START)
    assert controller.state == FAULTS[0]  # start can't override a fault
    client.send_command(DEST, mnet.Mnet.DATA_ID_RESET)
    assert controller.state not in FAULTS


def test_event_stack(client):
    events = client.get_events_batch(DEST, limit=10)
    assert [e.index for e in events] == list(range(10))
    assert events[0].text == RUN[1]
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps, reverse=True)


def test_remote_display(client):
    display = client.get_remote_display(DEST)
    assert len(display) == 138
    assert b'Wind' in display and b'Mode: AUTO' in display


def test_reply_over_frame_limit_raises(client):
    """The simulator refuses to build a frame the 1-byte length can't describe."""
    too_many = [(mnet.Mnet.DATA_ID_STATUS_TEXT, 314)] * 9
    with pytest.raises(ValueError, match='255-byte'):
        client.request_multiple_data(DEST, too_many)


def test_simulation_is_deterministic_for_a_seed(clock):
    a = SimulatedController(seed=7, clock=clock)
    b = SimulatedController(seed=7, clock=FakeClock(clock.now))
    assert a.events == b.events
