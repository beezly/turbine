"""
Simulated M-net Controller

A serial-like device that answers M-net requests the way a WP3000/IC1000
controller does, backed by a simple Gaia-Wind 133 simulation. Passing it to
mnet.Mnet in place of a serial port lets the whole monitor run without
hardware (see `turbine_monitor.py --demo`).

Everything it reports is SIMULATED, not telemetry from a turbine.
"""

import datetime
import math
import random
import struct
import time
from typing import Callable, List, Optional, Tuple

from crc import Calculator, Crc16

from mnet import Mnet

EPOCH = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)

# Turbine model (Gaia-Wind 133: 11 kW, fixed speed, stall regulated)
RATED_POWER_W = 11000.0
CUT_IN_MPS = 3.5
RATED_WIND_MPS = 9.5
CUT_OUT_MPS = 25.0
ROTOR_SYNC_RPM = 56.0
GEAR_RATIO = 18.0
ROTOR_TIME_CONSTANT = 4.0   # seconds for rotor speed to follow its target
POWER_TIME_CONSTANT = 3.0
ALARM_MTBF = 3600.0         # mean seconds between random faults while generating

# Operating states: (status code, status/event text)
RUN = (651, 'Cut in 0_>G1')
AWAITING_WIND = (240, 'Awaiting wind')
HIGH_WIND = (250, 'Wind > max.')
STOPPED = (11, 'Stop via communica.')
FAULTS = [(521, '(G) hot'), (601, 'Current asymmetry'), (102, 'Phase drop'),
          (227, 'Anemometer defect')]

# Events logged for commands. These codes/texts are simulator inventions;
# the codes above come from Mnet.ALARM_SUB_IDS.
EVENT_START = (12, 'Start via communica.')
EVENT_MANUAL_START = (15, 'Manual start')
EVENT_RESET = (14, 'Reset via communica.')
EVENT_AUTO = (16, 'Automatic operation')
EVENT_ACK = (17, 'Alarm acknowledged')

STATUS_TEXTS = {**Mnet.ALARM_SUB_IDS,
                **dict([EVENT_START, EVENT_MANUAL_START, EVENT_RESET, EVENT_AUTO, EVENT_ACK])}

DISPLAY_LINE_LEN = 18
DISPLAY_LEN = 138

# Element encodings: (data_type, conversion_type, conversion_value)
INT16_TENTHS = (3, 1, 1)
INT16 = (3, 0, 0)
INT32 = (5, 0, 0)
UINT16 = (4, 0, 0)
UINT32 = (6, 0, 0)
UINT32_HUNDREDTHS = (6, 1, 2)
STRING = 9


def _id(data_id: bytes) -> int:
    return int.from_bytes(data_id, 'big')


def _to_controller_seconds(when: datetime.datetime) -> int:
    return int((when - EPOCH).total_seconds())


class SimulatedController:
    """Serial-like device (write/read/reset_*/close) that plays an M-net controller."""

    ADDRESS = b'\x02'
    SERIAL_NUMBER = 1330999
    FIRMWARE = 'Rev.1:P00515/090219'

    def __init__(self, seed: Optional[int] = None,
                 clock: Callable[[], float] = time.time):
        self._rng = random.Random(seed)
        self._clock = clock
        self._rx = bytearray()
        self.encoded_serial = Mnet(None).encode_serial(struct.pack('!L', self.SERIAL_NUMBER))
        self._crc = Calculator(Crc16.XMODEM)

        now = self._clock()
        self._last_step = now
        self.clock_offset = 47.0  # controller clock drift; corrected by time sync

        self.wind_base = 7.0
        self.wind_gust = 0.0
        self.wind = 7.0
        self.rotor_rpm = ROTOR_SYNC_RPM
        self.power_w = self._aero_power(self.wind)
        self.voltages = [230.0, 229.0, 231.0]
        self.wind_30s = self.wind
        self.averages = {}  # (quantity, time constant) -> EMA
        self.runtime_total = 112_345_678
        self.runtime_generating = 61_234_567
        self.state = RUN

        self.events: List[Tuple[int, int, str]] = []  # (code, controller seconds, text), newest first
        self.last_occurred = {}  # code -> controller seconds
        self._seed_history(now)

    # ---- serial-like interface -------------------------------------------

    def write(self, data: bytes) -> int:
        reply = self._handle(bytes(data))
        if reply is not None:
            self._rx += reply
        return len(data)

    def read(self, size: int) -> bytes:
        """Return up to size bytes; empty when nothing is pending (like a serial timeout)."""
        chunk = bytes(self._rx[:size])
        del self._rx[:size]
        return chunk

    def reset_input_buffer(self) -> None:
        self._rx.clear()

    def reset_output_buffer(self) -> None:
        pass

    def reconnect(self) -> None:
        self._rx.clear()

    def close(self) -> None:
        self._rx.clear()

    # ---- framing -----------------------------------------------------------

    def _handle(self, packet: bytes) -> Optional[bytes]:
        if len(packet) < 9 or packet[0] != Mnet.SOH[0] or packet[-1] != Mnet.EOT[0]:
            return None
        destination, source = packet[1:2], packet[2:3]
        packet_type, length = packet[3:5], packet[5]
        wire_data = packet[6:6 + length]
        crc, = struct.unpack('!H', packet[6 + length:8 + length])
        if destination != self.ADDRESS or crc != self._crc.checksum(packet[1:6 + length]):
            return None
        data = wire_data.replace(b'\xff\xff', b'\xff')

        self._advance()
        reply_type, reply_data = self._dispatch(packet_type, data)
        return self._frame(source, reply_type, reply_data)

    def _frame(self, destination: bytes, packet_type: bytes, data: bytes) -> bytes:
        # Replies are not 0xFF-escaped: Mnet.read_packet reads data_len raw bytes.
        if len(data) > 255:
            raise ValueError(f"simulated reply of {len(data)} bytes exceeds the "
                             f"255-byte M-net frame limit")
        body = destination + self.ADDRESS + packet_type + bytes([len(data)]) + data
        return Mnet.SOH + body + self._crc.checksum(body).to_bytes(2, 'big') + Mnet.EOT

    def _dispatch(self, packet_type: bytes, data: bytes) -> Tuple[bytes, bytes]:
        if packet_type == Mnet.REQ_SERIAL_NUMBER:
            return b'\x0c\x2f', struct.pack('!L', self.SERIAL_NUMBER)
        if packet_type in (Mnet.REQ_LOGIN, Mnet.REQ_LOGIN_STANDARD):
            # Real hardware acks logins with the generic 0x0001 (see Mnet.REPLY_ACK)
            return Mnet.REPLY_ACK, b''
        if packet_type == Mnet.REQ_COMMAND:
            self._command(data[:2])
            return Mnet.REPLY_ACK, b''
        if packet_type == Mnet.REQ_DATA:
            data_id, sub_id = struct.unpack('!HH', data[:4])
            return b'\x0c\x29', self._encode(self._element(data_id, sub_id))
        if packet_type == Mnet.REQ_MULTIPLE_DATA:
            count = data[0]
            reply = bytes([count])
            for i in range(count):
                data_id, sub_id = struct.unpack_from('!HH', data, 1 + i * 4)
                reply += struct.pack('!HH', data_id, sub_id) + self._element(data_id, sub_id)
            return b'\x0c\x2b', self._encode(reply)
        if packet_type == Mnet.REQ_WRITE_DATA:
            data_id, sub_id, value = struct.unpack('!HHI', data[:8])
            if data_id == _id(Mnet.DATA_ID_CONTROLLER_TIME):
                self.clock_offset = (EPOCH.timestamp() + value) - self._clock()
            return b'\x0c\x2d', b''
        if packet_type == Mnet.REQ_DISPLAY_INFO:
            return b'\x0c\x06', self._encode(self.FIRMWARE.encode('ascii'))
        if packet_type == Mnet.REQ_DISPLAY_SCREEN:
            return b'\x0c\x07', self._encode(self._display())
        return packet_type, b''

    def _encode(self, data: bytes) -> bytes:
        return Mnet(None).encode(data, self.encoded_serial)

    # ---- data elements -----------------------------------------------------

    @staticmethod
    def _value(encoding: Tuple[int, int, int], raw: int) -> bytes:
        data_type, conversion, conversion_value = encoding
        payload = struct.pack({3: '!h', 4: '!H', 5: '!l', 6: '!L'}[data_type], raw)
        return struct.pack('!BBHB', data_type, conversion, conversion_value, len(payload)) + payload

    @staticmethod
    def _string(text: str) -> bytes:
        payload = text.encode('ascii')
        return struct.pack('!BBHB', STRING, 0, 0, len(payload)) + payload

    @staticmethod
    def _none() -> bytes:
        return struct.pack('!BBHB', 0, 0, 0, 0)

    def _element(self, data_id: int, sub_id: int) -> bytes:
        """Type/conversion header + value for one (data_id, sub_id)."""
        measured = self._measurement(data_id, sub_id)
        if measured is not None:
            encoding, value = measured
            scale = 10 ** encoding[2] if encoding[1] == 1 else 1
            return self._value(encoding, round(value * scale))

        if data_id == _id(Mnet.DATA_ID_CONTROLLER_TIME):
            return self._string(self._controller_time().strftime('%y%m%d%H%M%S'))
        if data_id == _id(Mnet.DATA_ID_CURRENT_STATUS_CODE) and sub_id in (0, 1):
            return self._value(UINT16, self.state[0] if sub_id == 0 else 0)
        if data_id == _id(Mnet.DATA_ID_EVENT_STACK_STATUS_CODE):
            index, field = divmod(sub_id, Mnet.EVENT_STACK_INDEX_MULTIPLIER)
            if index >= len(self.events) or field > Mnet.EVENT_STACK_SUBID_TEXT:
                return self._none()
            code, seconds, text = self.events[index]
            if field == Mnet.EVENT_STACK_SUBID_CODE:
                return self._value(UINT16, code)
            if field == Mnet.EVENT_STACK_SUBID_TIMESTAMP:
                return self._value(UINT32, seconds)
            return self._string(text)
        if data_id == _id(Mnet.DATA_ID_ALARM_LAST_OCCURRED) and sub_id in Mnet.ALARM_SUB_IDS:
            never = _to_controller_seconds(Mnet.ALARM_NEVER_OCCURRED_DATE)
            return self._value(UINT32, self.last_occurred.get(sub_id, never))
        if data_id in (_id(Mnet.DATA_ID_STATUS_TEXT), _id(Mnet.DATA_ID_STATUS_CODE_LOOKUP)) \
                and sub_id in STATUS_TEXTS:
            return self._string(STATUS_TEXTS[sub_id])
        if data_id == _id(Mnet.DATA_ID_RUNTIME_1):
            return self._value(UINT32, int(self.runtime_total))
        if data_id == _id(Mnet.DATA_ID_RUNTIME_2):
            return self._value(UINT32, int(self.runtime_generating))
        if data_id == _id(Mnet.DATA_ID_CONTROLLER_INFO) and sub_id in (1, 2):
            return self._string('P00515' if sub_id == 1 else '090219')
        return self._none()

    def _measurement(self, data_id: int, sub_id: int):
        """(encoding, value) for averaged real-time measurements, else None."""
        quantities = {
            _id(Mnet.DATA_ID_WIND_SPEED): (INT16_TENTHS, 'wind'),
            _id(Mnet.DATA_ID_ROTOR_REVS): (INT16_TENTHS, 'rotor'),
            _id(Mnet.DATA_ID_GEN_REVS): (INT16, 'generator'),
            _id(Mnet.DATA_ID_GRID_POWER): (INT32, 'power'),
            _id(Mnet.DATA_ID_L1V): (INT16_TENTHS, 'l1v'),
            _id(Mnet.DATA_ID_L2V): (INT16_TENTHS, 'l2v'),
            _id(Mnet.DATA_ID_L3V): (INT16_TENTHS, 'l3v'),
            _id(Mnet.DATA_ID_L1A): (INT16_TENTHS, 'l1a'),
            _id(Mnet.DATA_ID_L2A): (INT16_TENTHS, 'l2a'),
            _id(Mnet.DATA_ID_L3A): (INT16_TENTHS, 'l3a'),
            0x9cae: (UINT32_HUNDREDTHS, 'frequency'),
        }
        if data_id not in quantities:
            return None
        encoding, name = quantities[data_id]
        if sub_id >= Mnet.DATA_AVERAGING_10MIN:
            tau = 600.0
        elif sub_id >= Mnet.DATA_AVERAGING_30SEC:
            tau = 60.0
        else:
            tau = None
        current = self._quantities()[name]
        return encoding, current if tau is None else self.averages.get((name, tau), current)

    def _quantities(self) -> dict:
        phase_current = max(self.power_w, 0.0) / (3 * 230.0)
        return {
            'wind': self.wind,
            'rotor': self.rotor_rpm,
            'generator': self.rotor_rpm * GEAR_RATIO,
            'power': self.power_w,
            'l1v': self.voltages[0], 'l2v': self.voltages[1], 'l3v': self.voltages[2],
            'l1a': phase_current, 'l2a': phase_current * 1.01, 'l3a': phase_current * 0.99,
            'frequency': 50.0 + 0.03 * math.sin(self._clock() / 37.0),
        }

    def _controller_time(self) -> datetime.datetime:
        return datetime.datetime.fromtimestamp(self._clock() + self.clock_offset,
                                               datetime.timezone.utc)

    def _display(self) -> bytes:
        quantities = self._quantities()
        mode = 'ALARM' if self.state in FAULTS else 'STOP' if self.state == STOPPED else 'AUTO'
        lines = [
            self._controller_time().strftime('%d-%m-%y %H:%M:%S'),
            f"Wind {quantities['wind']:6.1f} m/s",
            f"Power {quantities['power'] / 1000:6.2f} kW",
            f"Rotor {quantities['rotor']:5.1f} rpm",
            f"Gen {quantities['generator']:7.0f} rpm",
            self.state[1],
            f"Mode: {mode}",
        ]
        text = ''.join(line[:DISPLAY_LINE_LEN].ljust(DISPLAY_LINE_LEN) for line in lines)
        return text.ljust(DISPLAY_LEN).encode('ascii')

    # ---- commands and events -----------------------------------------------

    def _command(self, command: bytes) -> None:
        if command == Mnet.DATA_COMMAND_STOP:
            if self.state != STOPPED:
                self._set_state(STOPPED)
        elif command in (Mnet.DATA_COMMAND_START, Mnet.DATA_COMMAND_MANUAL_START):
            if self.state == STOPPED:
                self._push_event(EVENT_START if command == Mnet.DATA_COMMAND_START
                                 else EVENT_MANUAL_START)
                self._resume()
        elif command == Mnet.DATA_COMMAND_AUTO:
            if self.state == STOPPED:
                self._push_event(EVENT_AUTO)
                self._resume()
        elif command == Mnet.DATA_COMMAND_RESET:
            if self.state in FAULTS:
                self._push_event(EVENT_RESET)
                self._resume()
        elif command == Mnet.DATA_COMMAND_ACK_ALARM:
            if self.state in FAULTS:
                self._push_event(EVENT_ACK)

    def _resume(self) -> None:
        self._set_state(RUN if self.wind_30s >= CUT_IN_MPS else AWAITING_WIND)

    def _set_state(self, state: Tuple[int, str]) -> None:
        self.state = state
        self._push_event(state)

    def _push_event(self, event: Tuple[int, str], when: Optional[float] = None) -> None:
        code, text = event
        seconds = _to_controller_seconds(
            datetime.datetime.fromtimestamp(when, datetime.timezone.utc)
            if when is not None else self._controller_time())
        self.events.insert(0, (code, seconds, text))
        del self.events[Mnet.EVENT_STACK_MAX_EVENTS:]
        if code in Mnet.ALARM_SUB_IDS:
            self.last_occurred[code] = seconds

    def _seed_history(self, now: float) -> None:
        """A plausible few days of past events, oldest first."""
        when = now - 5 * 86400
        history = []
        state = AWAITING_WIND
        while when < now - 600:
            state = RUN if state != RUN else AWAITING_WIND
            history.append((state, when))
            if self._rng.random() < 0.08:
                history.append((self._rng.choice(FAULTS), when + 60))
                history.append((EVENT_RESET, when + 1800))
            when += self._rng.uniform(1800, 4 * 3600)
        history.append((RUN, now - 300))
        for event, at in history:
            self._push_event(event, when=at + self.clock_offset)
        for code in (18, 42, 9, 13):  # older one-offs: emergency stop, battery low, ...
            self.last_occurred.setdefault(
                code, _to_controller_seconds(datetime.datetime.fromtimestamp(
                    now - self._rng.uniform(30, 400) * 86400, datetime.timezone.utc)))

    # ---- simulation --------------------------------------------------------

    @staticmethod
    def _aero_power(wind: float) -> float:
        if wind < CUT_IN_MPS or wind >= CUT_OUT_MPS:
            return 0.0
        if wind >= RATED_WIND_MPS:
            return RATED_POWER_W
        return RATED_POWER_W * (wind ** 3 - CUT_IN_MPS ** 3) / (RATED_WIND_MPS ** 3 - CUT_IN_MPS ** 3)

    def _advance(self) -> None:
        """Run the simulation up to now in steps of at most one second."""
        now = self._clock()
        elapsed = min(now - self._last_step, 300.0)  # don't replay long pauses
        self._last_step = now
        while elapsed > 0:
            dt = min(elapsed, 1.0)
            self._step(dt)
            elapsed -= dt

    def _step(self, dt: float) -> None:
        rng = self._rng
        # Wind: slow Ornstein-Uhlenbeck drift around 7 m/s plus fast gusts
        self.wind_base += (7.0 - self.wind_base) * dt / 120.0 + 0.32 * math.sqrt(dt) * rng.gauss(0, 1)
        self.wind_gust += -self.wind_gust * dt / 5.0 + 0.5 * math.sqrt(dt) * rng.gauss(0, 1)
        self.wind = max(0.0, self.wind_base + self.wind_gust)
        self.wind_30s += (self.wind - self.wind_30s) * min(1.0, dt / 30.0)

        # Automatic state changes
        if self.state == RUN:
            if self.wind > CUT_OUT_MPS:
                self._set_state(HIGH_WIND)
            elif self.wind_30s < 3.0:
                self._set_state(AWAITING_WIND)
            elif rng.random() < dt / ALARM_MTBF:
                self._set_state(rng.choice(FAULTS))
        elif self.state == AWAITING_WIND and self.wind_30s > 4.0:
            self._set_state(RUN)
        elif self.state == HIGH_WIND and self.wind_30s < 20.0:
            self._set_state(RUN)

        # Rotor and power follow the state with first-order lags
        if self.state == RUN:
            target_rpm = ROTOR_SYNC_RPM * (1 + 0.03 * self.power_w / RATED_POWER_W)
        elif self.state == AWAITING_WIND:
            target_rpm = min(self.wind * 4.0, 30.0)  # freewheeling
        else:
            target_rpm = 0.0  # braked
        self.rotor_rpm += (target_rpm - self.rotor_rpm) * min(1.0, dt / ROTOR_TIME_CONSTANT)

        generating = self.state == RUN and self.rotor_rpm > 0.9 * ROTOR_SYNC_RPM
        target_power = self._aero_power(self.wind) if generating else 0.0
        self.power_w += (target_power - self.power_w) * min(1.0, dt / POWER_TIME_CONSTANT)

        rise = 2.0 * self.power_w / RATED_POWER_W
        for i, nominal in enumerate((230.0, 229.0, 231.0)):
            self.voltages[i] = nominal + rise + rng.gauss(0, 0.4)

        for name, value in self._quantities().items():
            for tau in (60.0, 600.0):
                ema = self.averages.get((name, tau), value)
                self.averages[(name, tau)] = ema + (value - ema) * min(1.0, dt / tau)

        self.runtime_total += dt
        if generating:
            self.runtime_generating += dt
