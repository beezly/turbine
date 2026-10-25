"""
Mnet Protocol Implementation

Provides communication interface for wind turbine controllers using the Mnet protocol.
"""

import socket
import struct
import datetime
from typing import Tuple, List, Union, Optional, Iterator, NamedTuple, Dict
from crc import Calculator, Crc16


class MnetFrameError(Exception):
    """A received frame was short, mis-delimited or failed its CRC check."""


class MnetDecodeError(ValueError):
    """A well-framed reply could not be decoded or did not match its request."""


class MnetLoginRejectedError(MnetDecodeError):
    """The controller returned the documented "Remote not logged in" (0x1390)
    reply to a login attempt: a valid, well-formed negative acknowledgement,
    not a successful login and not frame/transport corruption."""


class Event(NamedTuple):
    """A turbine event from the event stack."""
    index: int
    code: int
    timestamp: datetime.datetime
    text: str


class AlarmRecord(NamedTuple):
    """An alarm type's last occurrence record."""
    sub_id: int
    last_occurred: datetime.datetime
    description: str
    has_occurred: bool  # False if timestamp is the "never" sentinel


class NetworkSerial:
    """TCP socket wrapper providing a serial-like interface for ser2net connections."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        """Initialize network serial connection.

        Args:
            host: ser2net server hostname or IP address
            port: ser2net server port
            timeout: Socket timeout in seconds (default 5.0)
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None

    def connect(self) -> None:
        """Establish connection to ser2net server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))

    def reconnect(self) -> None:
        """Close existing connection and establish a new one."""
        self.close()
        self.connect()

    def close(self) -> None:
        """Close the connection."""
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def read(self, size: int) -> bytes:
        """Read exactly size bytes from the connection.

        Args:
            size: Number of bytes to read

        Returns:
            Bytes read from connection

        Raises:
            ConnectionError: If connection is closed or read fails
        """
        if not self._socket:
            raise ConnectionError("Not connected")

        data = b''
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def write(self, data: bytes) -> int:
        """Write data to the connection.

        Args:
            data: Bytes to write

        Returns:
            Number of bytes written

        Raises:
            ConnectionError: If connection is closed or write fails
        """
        if not self._socket:
            raise ConnectionError("Not connected")
        return self._socket.send(data)

    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._socket is not None

    def __enter__(self) -> 'NetworkSerial':
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class MnetPacket:
    """Represents an Mnet protocol packet."""
    
    SOH = b'\x01'
    EOT = b'\x04'
    
    def __init__(self, destination: bytes, source: bytes, packet_type: bytes, 
                 data_len: int, data: bytes, crc: Optional[int] = None):
        self.crc_calculator = Calculator(Crc16.XMODEM)
        self.destination = destination
        self.source = source
        self.packet_type = packet_type
        self.data_len = data_len
        self.data = data
        
        # Escape 0xFF bytes in data
        self.real_data = self._escape_data(self.data)
        
        # Build packet for CRC calculation
        self.packet = (self.destination + self.source + self.packet_type + 
                      len(self.real_data).to_bytes(1, byteorder='big') + self.real_data)
        
        self.calculated_crc = self.crc_calculator.checksum(self.packet)
        self.crc = crc if crc is not None else self.calculated_crc
    
    def _escape_data(self, data: bytes) -> bytes:
        """Escape 0xFF bytes by doubling them."""
        return data.replace(b'\xff', b'\xff\xff')
    
    def __str__(self) -> str:
        return (f'sot:01 dst:0x{self.destination.hex()} src:0x{self.source.hex()} '
                f'type:0x{self.packet_type.hex()} len:{self.data_len} '
                f'data:{self.data.hex()} crc:{self.crc:04x} eot:04')
    
    def __bytes__(self) -> bytes:
        return (self.SOH + self.packet + 
                self.crc.to_bytes(2, byteorder='big') + self.EOT)


class Mnet:
    """Mnet protocol client for wind turbine communication."""
    
    # Protocol constants
    SOH = b'\x01'
    EOT = b'\x04'
    MAX_PACKET_SIZE = 300
    
    # Request types
    REQ_MULTIPLE_DATA = b'\x0c\x2a'
    REQ_DATA = b'\x0c\x28'
    REQ_WRITE_DATA = b'\x0c\x2c'
    REQ_COMMAND = b'\x0c\x32'
    REQ_SERIAL_NUMBER = b'\x0c\x2e'
    REQ_LOGIN = b'\x13\xa1'          # hidden login ("Remote hidden login"); password not validated -> level 0
    REQ_LOGIN_STANDARD = b'\x13\x8e'  # standard login ("Remote login"); carries + validates the Turbine Password

    # "Remote not logged in" (5008 / 0x1390): documented in docs/MNET.md as the
    # controller's reply when a login attempt is rejected. It is a valid,
    # well-formed negative reply, not an echo of the login request type.
    REPLY_NOT_LOGGED_IN = b'\x13\x90'

    # "Reply Acknowledge" (1 / 0x0001): docs/MNET.md documents this as a
    # generic acknowledgment reply type (e.g. for Acknowledge alarm /
    # 0x0BEA), not as a documented login reply. It was added to the hidden
    # login (REQ_LOGIN / 0x13A1) mapping below ONLY after being observed,
    # live, on real turbinepi hardware (2026-10-25 09:45-09:46 deploy
    # attempt, see docs/DEPLOYMENT_REPORT_2026-10-25.md): five separate
    # hidden-login attempts each got a 0x0001 reply that passed the source
    # and destination identity checks below (addressed from the expected
    # controller back to us, not a stray/misrouted frame) and was never
    # followed by the documented rejection code 0x1390. This matches the
    # pre-PR behaviour (send_packet performed no reply-type validation at
    # all) under which hidden-login-based monitoring worked continuously
    # against this same controller. Treat this as a controller-specific
    # quirk: this firmware acknowledges a successful hidden login with the
    # generic 0x0001 ack instead of echoing 0x13A1.
    #
    # Update: a live RESET attempt against this same controller at
    # 2026-10-25 22:22:10 UTC showed REQ_LOGIN_STANDARD (0x138E,
    # control/write login) *also* gets a 0x0001 reply -- the controller-wide
    # generic-ack quirk is not limited to hidden login. This is separately
    # observed evidence for the standard login specifically (not an
    # inference carried over from the hidden-login case): a bounded,
    # redacted journalctl excerpt from that exact timestamp showed a
    # correctly-addressed 0x0001 reply to a login_standard() call, never
    # the documented 0x1390 rejection. REQ_LOGIN_STANDARD now accepts
    # 0x0001 for the same evidence-based reason REQ_LOGIN already does --
    # this is NOT a blanket widening of accepted packet types; it is
    # scoped to this one request type, backed by this one observation.
    REPLY_ACK = b'\x00\x01'

    # Request packet type -> set of documented valid reply packet types.
    #
    # The Mnet protocol does NOT universally echo request.packet_type back on
    # the reply (see docs/MNET.md "Packet Type Codes" and "Message Sequence
    # Examples"): most request/reply pairs use *different* codes (e.g.
    # Request data 0x0C28 -> Reply data 0x0C29). Logins are a documented
    # exception: a successful login reply echoes the login request's own
    # type (0x138E or 0x13A1); a rejected login instead returns the shared
    # "Remote not logged in" code 0x1390.
    #
    # Request types with NO documented reply code in docs/MNET.md and no
    # hardware-observed quirk evidence are intentionally left out of this
    # map; send_packet falls back to requiring an exact echo for those so an
    # unexpected reply type still raises instead of being silently invented.
    # 0x0BEA (Acknowledge alarm) is included below even though no current
    # caller in this file sends that request type, for completeness against
    # docs/MNET.md and so a future caller gets correct validation for free.
    #
    # REQ_COMMAND / 0x0C32 has NO documented reply code in docs/MNET.md at
    # all (it does not appear in the "Packet Type Codes" table, unlike every
    # other request type above). Prior to the identity/type-validation
    # hardening added in this repo's history (see a436d77, 2109a53, 124376f,
    # 782c22e), send_packet performed no reply validation whatsoever and the
    # command dispatcher (then turbine_monitor.py's _execute_pending_command)
    # treated ANY syntactically valid reply to a command as a successful
    # ack -- this was the actual, long-running production behaviour this
    # controller was built against, not an assumption drawn from
    # docs/MNET.md (which does not document a reply code for this request
    # type at all). That hardening's exact-echo fallback (no entry here for
    # REQ_COMMAND) was therefore a real regression once source/destination/
    # CRC checks were added: two separate live RESET attempts against this
    # same controller on 2026-10-25 (22:39:26 and 22:41:32 UTC, each a
    # bounded, redacted journalctl excerpt) show a correctly-addressed,
    # CRC-valid 0x0001 "Reply Acknowledge" in response to REQ_COMMAND, never
    # the literal 0x0C32 echo. This mirrors the identical, already-fixed
    # quirk for both logins above. The fix stays narrow: only REPLY_ACK
    # (0x0001) is added back for REQ_COMMAND specifically, backed by this
    # session's own repeated observation -- not a reversion to accepting
    # any reply type, and the CRC/source/destination checks added by that
    # same hardening are kept exactly as they are, independently valuable
    # regardless of which reply type they are checking.
    REQUEST_RESPONSE_TYPES: Dict[bytes, frozenset] = {
        REQ_DATA: frozenset({b'\x0c\x29'}),             # Request data -> Reply data
        REQ_MULTIPLE_DATA: frozenset({b'\x0c\x2b'}),     # Request multiple data -> Reply multiple data
        REQ_WRITE_DATA: frozenset({b'\x0c\x2d'}),        # Request write data -> Reply write data
        REQ_SERIAL_NUMBER: frozenset({b'\x0c\x2f'}),     # Request serial no. -> Reply serial no.
        b'\x0c\x04': frozenset({b'\x0c\x06'}),          # Display command type 2 -> 0xc06
        b'\x0c\x05': frozenset({b'\x0c\x07'}),          # Display command type 3 -> 0xc07
        b'\x0b\xea': frozenset({b'\x00\x01'}),          # Acknowledge alarm -> Reply Acknowledge (no current caller uses this request type)
        # Remote command: no documented reply code in docs/MNET.md at all,
        # PLUS the hardware-observed 0x0001 generic-ack quirk (see REQ_COMMAND
        # comment above for the 2026-10-25 22:39/22:41 UTC evidence and the
        # pre-hardening history this restores).
        REQ_COMMAND: frozenset({REQ_COMMAND, REPLY_ACK}),
        # Hidden login: echo (0x13A1) or 0x1390 rejection per docs/MNET.md,
        # PLUS the hardware-observed 0x0001 generic-ack quirk above.
        REQ_LOGIN: frozenset({REQ_LOGIN, REPLY_NOT_LOGGED_IN, REPLY_ACK}),
        # Standard (control) login: echo on success, 0x1390 on rejection,
        # PLUS the hardware-observed 0x0001 generic-ack quirk (see REPLY_ACK
        # comment above for the 2026-10-25 22:22 UTC evidence).
        REQ_LOGIN_STANDARD: frozenset({REQ_LOGIN_STANDARD, REPLY_NOT_LOGGED_IN, REPLY_ACK}),
    }

    # Login constants
    LOGIN_131_GAIA_WIND = b'\x31\x33\x31\x20\x66\x6b\x59\x75\x29\x29\x31\x32\x32\x32\x31\x51\x51\x61\x61\x00'
    # Payload offset 0x2a (big-endian dword). WPMS builder 0x59D2 fills this with the HASP
    # dongle serial (sscanf "%lx" of the dongle string) or, with NO dongle, hardcodes 0x7B.
    # So a dongle-less login (ours) must use 0x7B here to byte-match WPMS -- NOT the mfr code.
    LOGIN_PACKET_ID = 0x7b
    # Turbine Password field is a 20-byte, NUL-terminated ASCII slot (max 19 chars).
    LOGIN_PASSWORD_FIELD_LEN = 20
    
    # Data IDs
    DATA_ID_WIND_SPEED = b'\x9c\x43'
    DATA_ID_GEN_REVS = b'\x9c\x47'
    DATA_ID_ROTOR_REVS = b'\x9c\x46'
    DATA_ID_L1V = b'\x9c\xa5'
    DATA_ID_L2V = b'\x9c\xa6'
    DATA_ID_L3V = b'\x9c\xa7'
    DATA_ID_L1A = b'\x9c\xa9'
    DATA_ID_L2A = b'\x9c\xaa'
    DATA_ID_L3A = b'\x9c\xab'
    DATA_ID_SYSTEM_PRODUCTION = b'\x80\xe9'
    DATA_ID_G1_PRODUCTION = b'\x80\xea'
    DATA_ID_CONTROLLER_TIME = b'\xc3\x53'
    DATA_ID_GRID_POWER = b'\x9c\xac'
    DATA_ID_GRID_CURRENT = b'\x9c\xa8'
    DATA_ID_GRID_VOLTAGE = b'\x9c\xa4'
    DATA_ID_GRID_VAR = b'\x9c\xad'
    DATA_ID_CURRENT_STATUS_CODE = b'\x00\x0c'
    DATA_ID_EVENT_STACK_STATUS_CODE = b'\x00\x0b'
    DATA_ID_STATUS_TEXT = b'\xc7\x3c'  # Current status or alarm text by sub_id
    DATA_ID_STATUS_CODE_LOOKUP = b'\xc7\xa0'  # Status code text lookup (sub_id = status code)
    DATA_ID_ALARM_LAST_OCCURRED = b'\xc7\x3b'  # Last occurrence time per alarm type (sub_id = alarm sub_id)

    # Runtime counters (discovered 0x0003, 0x0004)
    DATA_ID_RUNTIME_1 = b'\x00\x03'  # Runtime counter 1 (seconds)
    DATA_ID_RUNTIME_2 = b'\x00\x04'  # Runtime counter 2 (seconds)

    # Sub-IDs for EVENT_STACK_STATUS_CODE (0x000B)
    # Event history is at sub_id = (event_index * 100) + offset
    # event_index 0 = most recent, up to 99 (100 events total)
    EVENT_STACK_SUBID_CODE = 0       # Status code number (0 is valid, e.g., "COMPENSATOR 1 IN")
    EVENT_STACK_SUBID_TIMESTAMP = 1  # When event occurred
    EVENT_STACK_SUBID_TEXT = 2       # Human-readable event description (use this, not lookup)
    EVENT_STACK_INDEX_MULTIPLIER = 100  # sub_id = event_index * 100 + offset
    EVENT_STACK_MAX_EVENTS = 100     # Stack holds 100 events (indices 0-99)

    # Maximum items per batch request (controller limit is ~17-20)
    MAX_BATCH_SIZE = 15

    # Controller info data IDs (discovered)
    DATA_ID_CONTROLLER_INFO = b'\x00\x01'  # sub_id=1: program number, sub_id=2: version
    
    # Real-time measurements averaging - from DATAID.DAT

    DATA_AVERAGING_CURRENT = 0
    DATA_AVERAGING_20MSEC = 1000
    DATA_AVERAGING_100MSEC = 1500
    DATA_AVERAGING_1SEC = 2000
    DATA_AVERAGING_30SEC = 3000
    DATA_AVERAGING_1MIN = 4000
    DATA_AVERAGING_10MIN = 5000
    DATA_AVERAGING_30MIN = 6000
    DATA_AVERAGING_1HR = 7000
    DATA_AVERAGING_24HR = 8000

    # Command IDs
    DATA_COMMAND_EMPTY = b'\x00\x00'
    DATA_COMMAND_START = b'\x00\x01'
    DATA_COMMAND_STOP = b'\x00\x02'
    DATA_COMMAND_RESET = b'\x00\x03'
    DATA_COMMAND_MANUAL_START = b'\x00\x04'
    DATA_COMMAND_ACK_ALARM = b'\x00\x0a'   # acknowledge alarm (value 10)
    DATA_COMMAND_AUTO = b'\x00\x0e'        # return to automatic operation (value 14)

    # Command aliases for backward compatibility
    DATA_ID_START = DATA_COMMAND_START
    DATA_ID_STOP = DATA_COMMAND_STOP
    DATA_ID_RESET = DATA_COMMAND_RESET
    DATA_ID_MANUAL_START = DATA_COMMAND_MANUAL_START
    DATA_ID_ACK_ALARM = DATA_COMMAND_ACK_ALARM
    DATA_ID_AUTO = DATA_COMMAND_AUTO

    # Data IDs that use data_type 6 (uint32) but should NOT be converted to datetime
    # These return numeric values even though the protocol marks them as "timestamp" type
    DATA_IDS_NOT_TIMESTAMP = {
        0x0003,  # RUNTIME_1 - runtime counter in seconds
        0x0004,  # RUNTIME_2 - runtime counter in seconds
        0x9cae,  # GRID_FREQUENCY - returns Hz (e.g., 49.9)
        0xc739,  # ERROR_COUNT - returns count
        0xc73a,  # STOP_DUE_TO_ERROR - returns seconds (duration, not absolute time)
        0xc79c,  # Error status mirror
        0xc79d,  # Error count mirror (same as 0xc739)
        0xc79e,  # Stop due to error mirror (same as 0xc73a)
    }
    
    # Legacy inner class for backward compatibility
    MnetPacket = MnetPacket
    
    def __init__(self, device, id: bytes = b'\x01'):
        """Initialize Mnet client.

        Args:
            device: Serial device object
            id: Client ID bytes
        """
        self.device = device
        self.id = id
        self.serial: Optional[int] = None
        self.encoded_serial: Optional[bytearray] = None
        self._log_callback = None
        self._debug_callback = None
        self._alarm_description_cache: Dict[int, str] = {}  # Cache for alarm descriptions
    
    def create_packet(self, destination: bytes, packet_type: bytes, data: bytes) -> MnetPacket:
        """Create an Mnet packet."""
        return MnetPacket(destination, self.id, packet_type, len(data), data)
    
    def send_packet(self, destination: bytes, packet_type: bytes, data: bytes,
                     expected_types: Optional[frozenset] = None) -> MnetPacket:
        """Send packet and return response.

        Validates the reply's identity: it must come from the device we
        addressed, be addressed back to us, and use a packet type that is a
        documented valid reply to this specific request type.

        Per docs/MNET.md, the Mnet protocol does NOT universally echo the
        request's packet type back on the reply -- most request/reply pairs
        use distinct codes (e.g. Request data 0x0C28 -> Reply data 0x0C29).
        The expected reply type set is resolved as follows:

        1. ``expected_types`` if the caller passes one explicitly (lets a
           caller override/narrow for a transaction-specific case).
        2. ``REQUEST_RESPONSE_TYPES[packet_type]`` if the request type has a
           documented mapping.
        3. Otherwise, exact echo of ``packet_type`` -- this is a conservative
           fallback for request types with no documented reply code (not an
           assumption that echo is correct; any other reply is still
           rejected).

        Raises:
            MnetLoginRejectedError: a login request got the documented
                "Remote not logged in" (0x1390) reply -- a valid, well-formed
                rejection, not a successful login and not corruption.
            MnetDecodeError: the response source, destination, or packet type
                does not match the request / documented mapping.
        """
        packet = self.create_packet(destination, packet_type, data)
        packet_bytes = bytes(packet)
        
        # Log outgoing packet
        if self._log_callback:
            self._log_callback('TX', packet_bytes.hex(), str(packet))
        
        self.device.write(packet_bytes)
        response = self.read_packet()
        
        # Validate response came from expected source (the device we're talking to)
        if response.source != destination:
            raise MnetDecodeError(
                f"response source mismatch: expected 0x{destination.hex()}, "
                f"got 0x{response.source.hex()}")

        # Validate response is addressed back to us
        if response.destination != self.id:
            raise MnetDecodeError(
                f"response destination mismatch: expected 0x{self.id.hex()}, "
                f"got 0x{response.destination.hex()}")

        # Resolve the documented set of valid reply types for this request.
        if expected_types is not None:
            valid_types = expected_types
        else:
            valid_types = self.REQUEST_RESPONSE_TYPES.get(packet_type, frozenset({packet_type}))

        if response.packet_type not in valid_types:
            raise MnetDecodeError(
                f"response packet type mismatch: expected one of "
                f"{{{', '.join('0x' + t.hex() for t in sorted(valid_types))}}}, "
                f"got 0x{response.packet_type.hex()}")

        # A login request that got the documented "not logged in" rejection
        # reply is a valid negative, not a successful login: surface it as a
        # distinct, specific error rather than letting callers mistake the
        # well-formed rejection reply for a successful login response.
        if (packet_type in (self.REQ_LOGIN, self.REQ_LOGIN_STANDARD)
                and response.packet_type == self.REPLY_NOT_LOGGED_IN):
            raise MnetLoginRejectedError(
                f"login rejected: controller replied 0x{self.REPLY_NOT_LOGGED_IN.hex()} "
                f"(Remote not logged in) to request 0x{packet_type.hex()}")

        # Log incoming response
        if self._log_callback:
            response_bytes = bytes(response)
            self._log_callback('RX', response_bytes.hex(), str(response))
        
        return response
    
    def _read_exact(self, size: int, what: str) -> bytes:
        """Read exactly size bytes, looping over partial reads.

        TCP and serial reads may return fewer bytes than requested. An empty read
        means EOF, a closed connection or a serial timeout, so give up rather than spin.

        Raises:
            MnetFrameError: the device returned no data before size bytes arrived.
        """
        buf = b''
        while len(buf) < size:
            chunk = self.device.read(size - len(buf))
            if not chunk:
                raise MnetFrameError(
                    f"short {what} read: {len(buf)} of {size} bytes (connection closed or timed out)")
            buf += chunk
        return buf

    def read_packet(self) -> MnetPacket:
        """Read and validate a packet from the device.

        Raises:
            MnetFrameError: short read, bad SOH/EOT delimiter, or CRC mismatch.
        """
        header = self._read_exact(6, 'header')
        soh, destination, source, packet_type, data_len = struct.unpack('!BBBHB', header)
        if soh != self.SOH[0]:
            raise MnetFrameError(f"bad SOH: 0x{soh:02x}")

        data = self._read_exact(data_len, 'data') if data_len > 0 else b''

        tail = self._read_exact(3, 'tail')
        crc, eot = struct.unpack('!HB', tail)
        if eot != self.EOT[0]:
            raise MnetFrameError(f"bad EOT: 0x{eot:02x}")

        # CRC covers dst..data exactly as received (data is already wire-escaped)
        expected_crc = Calculator(Crc16.XMODEM).checksum(header[1:] + data)
        if crc != expected_crc:
            raise MnetFrameError(f"CRC mismatch: got 0x{crc:04x}, expected 0x{expected_crc:04x}")

        return MnetPacket(
            destination.to_bytes(1, byteorder='big'),
            source.to_bytes(1, byteorder='big'),
            packet_type.to_bytes(2, byteorder='big'),
            data_len, data, crc
        )
    
    def get_serial_number(self, destination: bytes) -> Tuple[int, bytes]:
        """Get device serial number."""
        response = self.send_packet(destination, self.REQ_SERIAL_NUMBER, b'')
        serial, = struct.unpack('!L', response.data)
        return serial, response.data

    # Remote display packet types
    REQ_DISPLAY_INFO = b'\x0c\x04'    # Returns controller version info
    REQ_DISPLAY_SCREEN = b'\x0c\x05'  # Returns current screen content

    def get_remote_display_info(self, destination: bytes) -> str:
        """Get remote display controller info (version/revision).

        Args:
            destination: Target device address

        Returns:
            Controller version string (e.g., "Rev.1:P00515/090219")
        """
        self._ensure_serial_available(destination)
        response = self.send_packet(destination, self.REQ_DISPLAY_INFO, b'')
        decoded = self.decode(response.data, self.encoded_serial)
        try:
            text = decoded.decode('ascii', errors='replace')
            return text.strip().replace('\x00', ' ').strip()
        except Exception:
            return decoded.hex()

    def get_remote_display(self, destination: bytes) -> bytes:
        """Get remote display screen data (raw decrypted bytes).

        Retrieves the screen buffer from the turbine controller.

        Args:
            destination: Target device address

        Returns:
            Decrypted screen buffer bytes
        """
        self._ensure_serial_available(destination)
        response = self.send_packet(destination, self.REQ_DISPLAY_SCREEN, b'')
        return self.decode(response.data, self.encoded_serial)

    def get_remote_display_text(self, destination: bytes) -> List[str]:
        """Get remote display as text lines.

        The display buffer is ~138 bytes with this approximate structure:
        - Bytes 0-19: Timestamp (DD-MM-YY HH:MM:SS)
        - Bytes 20-31: Generator indicator
        - Bytes 32-79: Operational data (power, wind, RPM, status)
        - Bytes 80-111: Padding
        - Bytes 112+: Operating mode

        Args:
            destination: Target device address

        Returns:
            List of non-empty text lines from the display
        """
        data = self.get_remote_display(destination)

        # Decode as ASCII, replacing non-printable chars with spaces
        text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in data)

        # Split into logical sections and clean up
        # The data seems to be ~34-35 char lines based on content analysis
        lines = []
        # Try splitting by detecting natural boundaries in the data
        # Use 34-char lines which aligns reasonably well
        for i in range(0, len(text), 34):
            line = text[i:i + 34].strip()
            if line:
                lines.append(line)

        return lines

    def get_remote_display_parsed(self, destination: bytes) -> dict:
        """Get remote display data parsed into fields.

        Args:
            destination: Target device address

        Returns:
            Dictionary with parsed display fields
        """
        data = self.get_remote_display(destination)
        text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in data)

        return {
            'raw': text,
            'raw_bytes': len(data),
            'timestamp': text[1:20].strip() if len(text) > 20 else '',
            'full_text': ' '.join(text.split()),  # Collapse whitespace
        }

    def encode_serial(self, serial_bytes: bytes) -> bytearray:
        """Encode serial number for encryption."""
        p0, p1, p2, p3 = struct.unpack('!BBBB', serial_bytes)
        result = bytearray(5)
        result[0] = ((p2 & p1) - p2) % 256
        result[1] = (p1 + p0 + p3) % 256
        result[2] = (p3 + p0 ^ p1) % 256
        result[3] = ((p3 & p1) + p2) % 256
        result[4] = ((p3 | p2) - p3) % 256
        return result
    
    def encode(self, data: bytes, enc_serial: bytearray) -> bytes:
        """Encode data using serial-based encryption."""
        CONST = 0x34
        ba = bytearray(data)
        out = [0] * len(data)
        
        previous_byte = 0
        for i, byte in enumerate(ba):
            out[i] = ((enc_serial[i % 5] - previous_byte ^ byte) + CONST) % 256
            previous_byte = byte
        return bytes(out)
    
    def decode(self, data: bytes, enc_serial: bytearray) -> bytes:
        """Decode data using serial-based decryption."""
        CONST = 0x34
        ba = bytearray(data)
        out = [0] * len(data)
        
        tmp = 0
        for i, byte in enumerate(ba):
            tmp = (byte - CONST ^ enc_serial[i % 5] - tmp) % 256
            out[i] = tmp
        return bytes(out)
    
    def decode_data(self, data_in: bytes, data_id: Optional[int] = None) -> Tuple[int, Union[float, str, None]]:
        """Decode data value from response.

        Args:
            data_in: Raw data bytes from response
            data_id: Optional data ID (wire ID as int) to determine type handling.
                     If provided and in DATA_IDS_NOT_TIMESTAMP, skips datetime conversion.
        """
        header = data_in[0:5]
        data_type, conversion_type, conversion_value, length = struct.unpack('!BBHB', header)

        # Original match statement with bugs preserved for compatibility
        match data_type:
            case 0x0:
                raw_data = None
            case 0x1 | 0xa:
                raw_data, = struct.unpack_from('!b', data_in, 5)
            case 0x2:
                raw_data, = struct.unpack_from('!b', data_in, 5)
            case 0x3:
                raw_data, = struct.unpack_from('!h', data_in, 5)
            case 0x4:
                raw_data, = struct.unpack_from('!H', data_in, 5)
            case 0x5:
                raw_data, = struct.unpack_from('!l', data_in, 5)
            case 0x6: # timestamp - fix up later to normalise to datetime
                raw_data, = struct.unpack_from('!L', data_in, 5)
            case 0x7:
                raw_data, = struct.unpack_from('!L', data_in, 5)
            case 0x9:
                raw_data, = struct.unpack_from(f'!{length}s', data_in, 5)
                raw_data = raw_data.decode('ascii').rstrip('\x00')
            case _:
                raise ValueError(f"Unknown data type: {data_type}")

        # Original match statement with bugs preserved
        match conversion_type:
            case 0x0:
                value = raw_data
            case 0x1 | 0x5:
                value = float(raw_data) / pow(10, conversion_value)
            case 0x2:
                value = float(raw_data) / conversion_value if conversion_value != 0 else float(raw_data)
            case 0x3:
                value = float(raw_data) * conversion_value if conversion_value != 0 else float(raw_data)
            case 0x4:
                value = float(raw_data) * pow(10, conversion_value)
            case _:
                raise ValueError(f"Unknown conversion type: {conversion_type}")

        # Convert to datetime only if data_type is 6 AND data_id is not in the exclusion set
        if data_type == 6 and data_id not in self.DATA_IDS_NOT_TIMESTAMP:
            value = self.timestamp_to_datetime(value)

        return data_type, value
    
    def _extract_raw_data(self, data_type: int, data_in: bytes, length: int) -> Union[int, str, None]:
        """Extract raw data based on type."""
        type_map = {
            0x0: lambda: None,
            0x1: lambda: struct.unpack_from('!b', data_in, 5)[0],
            0x2: lambda: struct.unpack_from('!b', data_in, 5)[0],
            0x3: lambda: struct.unpack_from('!h', data_in, 5)[0],
            0x4: lambda: struct.unpack_from('!H', data_in, 5)[0],
            0x5: lambda: struct.unpack_from('!l', data_in, 5)[0],
            0x6: lambda: struct.unpack_from('!L', data_in, 5)[0],
            0x7: lambda: struct.unpack_from('!L', data_in, 5)[0],
            0x9: lambda: struct.unpack_from(f'!{length}s', data_in, 5)[0].decode('ascii').rstrip('\x00'),
            0xa: lambda: struct.unpack_from('!b', data_in, 5)[0],
        }
        
        extractor = type_map.get(data_type)
        if extractor is None:
            raise ValueError(f"Unknown data type: {data_type}")
        
        return extractor()
    
    def _apply_conversion(self, conversion_type: int, conversion_value: int, 
                         raw_data: Union[int, str, None]) -> Union[float, str, None]:
        """Apply conversion to raw data."""
        if raw_data is None:
            return None
        if isinstance(raw_data, str):
            return raw_data
        
        conversion_map = {
            0x0: lambda: raw_data,
            0x1: lambda: float(raw_data) / pow(10, conversion_value),
            0x2: lambda: float(raw_data) / conversion_value if conversion_value != 0 else float(raw_data),
            0x3: lambda: float(raw_data) * conversion_value if conversion_value != 0 else float(raw_data),
            0x4: lambda: float(raw_data) * pow(10, conversion_value),
            0x5: lambda: float(raw_data) / pow(10, conversion_value),
        }
        
        converter = conversion_map.get(conversion_type)
        if converter is None:
            raise ValueError(f"Unknown conversion type: {conversion_type}")
        
        return converter()
    
    def decode_multiple_data(self, data_in: bytes,
                             requests: Optional[List[Tuple[bytes, int]]] = None
                             ) -> List[Tuple[int, int, Tuple[int, Union[float, str, None]]]]:
        """Decode multiple data elements from response.

        Args:
            data_in: Decrypted multi-data reply.
            requests: Optional (data_id bytes, sub_id) list that was sent. When given,
                the reply must contain exactly one element per request, in order, with
                matching (mainid, subid) -- otherwise a truncated/reordered reply would
                silently shift values onto the wrong fields.

        Raises:
            MnetDecodeError: truncated reply, element-count or (mainid, subid) mismatch.
        """
        if not data_in:
            if requests:
                raise MnetDecodeError(f"empty reply, expected {len(requests)} elements")
            return []

        num_elements = data_in[0]
        pos = 1
        results = []

        for i in range(num_elements):
            if pos + 9 > len(data_in):
                raise MnetDecodeError(
                    f"truncated reply: header of element {i} of {num_elements} incomplete")

            header = data_in[pos:pos+9]
            mainid, subid, _, _, _, length = struct.unpack("!HHBBHB", header)
            if pos + 9 + length > len(data_in):
                raise MnetDecodeError(
                    f"truncated reply: element {i} of {num_elements} needs {length} data bytes")

            next_data = data_in[pos+4:pos+9+length]
            # Pass mainid to decode_data for proper type handling
            decoded = self.decode_data(next_data, data_id=mainid)
            results.append((mainid, subid, decoded))

            pos += 9 + length

        if requests is not None:
            if len(results) != len(requests):
                raise MnetDecodeError(
                    f"expected {len(requests)} elements, reply contains {len(results)}")
            for i, ((req_id, req_sub), (mainid, subid, _)) in enumerate(zip(requests, results)):
                if (int.from_bytes(req_id, 'big'), req_sub) != (mainid, subid):
                    raise MnetDecodeError(
                        f"element {i} mismatch: requested {req_id.hex()}:{req_sub}, "
                        f"got {mainid:04x}:{subid}")

        return results
    
    def create_login_packet_data(self) -> bytes:
        """Create hidden-login packet data (32 bytes, no password)."""
        return struct.pack('=20sBBBBBBBBBBBB',
                          self.LOGIN_131_GAIA_WIND,
                          0xff, 0xff,
                          self.LOGIN_PACKET_ID >> 0x18,
                          self.LOGIN_PACKET_ID >> 0x10,
                          self.LOGIN_PACKET_ID >> 8,
                          self.LOGIN_PACKET_ID,
                          5, 0, 0, 0, 0, 0)

    def create_login_packet_data_standard(self, password: str,
                                           login_id: Optional[int] = None) -> bytes:
        """Create standard-login packet data (52 bytes, WITH the Turbine Password).

        Wire layout (verified from PRTCL001.PRO staging routine @0x59d2):
            [0x00] 20 bytes  manufacturer credential (NUL-terminated)
            [0x14] 20 bytes  Turbine Password (ASCII, NUL-terminated, max 19 chars)
            [0x28] 0xFF 0xFF
            [0x2a] 4 bytes   login-type id, big-endian (131 = Gaia Wind)
            [0x2e] 0x05
            [0x2f] 0x00 x5
        The whole 52-byte payload is then serial-XOR encoded and sent as REQ_LOGIN_STANDARD.
        """
        if login_id is None:
            login_id = self.LOGIN_PACKET_ID   # 0x7B, WPMS's no-dongle value for offset 0x2a
        credential = self.LOGIN_131_GAIA_WIND.ljust(20, b'\x00')[:20]
        # Accept str (latin-1, so 'ø' -> 0xF8) or raw bytes (full control over code page).
        if isinstance(password, (bytes, bytearray)):
            pw = bytes(password)[:self.LOGIN_PASSWORD_FIELD_LEN - 1]
        else:
            pw = password.encode('latin-1', errors='replace')[:self.LOGIN_PASSWORD_FIELD_LEN - 1]
        pw_field = pw.ljust(self.LOGIN_PASSWORD_FIELD_LEN, b'\x00')
        payload = (credential                       # [0x00] 20 bytes credential
                   + pw_field                       # [0x14] 20 bytes password
                   + b'\xff\xff'                    # [0x28] FF FF
                   + struct.pack('>I', login_id)    # [0x2a] login id, big-endian
                   + b'\x05\x00\x00\x00\x00\x00')   # [0x2e] 05 00 00 00 00 00
        assert len(payload) == 52, f"login payload must be 52 bytes, got {len(payload)}"
        return payload
    
    def _ensure_serial_available(self, destination: bytes) -> None:
        """Ensure serial number is available for encoding."""
        if self.serial is None:
            self.serial, serial_bytes = self.get_serial_number(destination)
            self.encoded_serial = self.encode_serial(serial_bytes)

    def send_command(self, destination: bytes, command_id: bytes) -> MnetPacket:
        """Send command to device."""
        self._ensure_serial_available(destination)
        return self.send_packet(destination, self.REQ_COMMAND, command_id)
    
    def request_data(self, destination: bytes, data_id: bytes, sub_id: int = 0) -> Union[float, str]:
        """Request single data value."""
        self._ensure_serial_available(destination)

        request_data = data_id + sub_id.to_bytes(2, byteorder='big')
        response = self.send_packet(destination, self.REQ_DATA, request_data)

        decoded_data = self.decode(response.data, self.encoded_serial)
        # Convert data_id bytes to int for type handling lookup
        data_id_int = int.from_bytes(data_id, byteorder='big')
        _, value = self.decode_data(decoded_data, data_id=data_id_int)

        return value
    
    def request_multiple_data(self, destination: bytes, datasubids: List[Tuple[bytes, int]], 
                            include_ids: bool = False) -> List[Union[float, str]]:
        """Request multiple data values."""
        self._ensure_serial_available(destination)
        
        # Build request data
        request_data = bytes([len(datasubids)])
        for data_id, sub_id in datasubids:
            request_data += data_id + sub_id.to_bytes(2, byteorder='big')
        
        response = self.send_packet(destination, self.REQ_MULTIPLE_DATA, request_data)
        decoded_data = self.decode(response.data, self.encoded_serial)
        
        # Log decrypted data (commented out to reduce serial log clutter)
        # if self._log_callback:
        #     ascii_data = decoded_data.decode('ascii', errors='replace')
        #     abbreviated_ascii = ascii_data[:16] + ('...' if len(ascii_data) > 16 else '')
        #     self._log_callback('DECRYPT', decoded_data.hex(), f'Decrypted ASCII: {abbreviated_ascii}')
        
        results = self.decode_multiple_data(decoded_data, requests=datasubids)

        # Log debug responses
        if self._debug_callback:
            for i, (mainid, subid, (data_type, value)) in enumerate(results):
                req_data_id = datasubids[i][0].hex() if i < len(datasubids) else 'unknown'
                req_sub_id = datasubids[i][1] if i < len(datasubids) else 'unknown'
                self._debug_callback({
                    'request_data_id': req_data_id,
                    'request_sub_id': req_sub_id,
                    'response_mainid': mainid,
                    'response_subid': subid,
                    'data_type': data_type,
                    'value': value,
                    'decoded_hex': decoded_data.hex()
                })
        
        if include_ids:
            return [(struct.pack('!H', mainid), subid, value) for mainid, subid, (_, value) in results]
        else:
            return [value for _, _, (_, value) in results]
    
    def login(self, destination: bytes) -> MnetPacket:
        """Perform hidden login to device (no password; grants read-only / level 0)."""
        self._ensure_serial_available(destination)
        login_data = self.encode(self.create_login_packet_data(), self.encoded_serial)
        return self.send_packet(destination, self.REQ_LOGIN, login_data)

    def login_standard(self, destination: bytes, password: str,
                        login_id: Optional[int] = None) -> MnetPacket:
        """Perform standard login WITH the per-turbine Turbine Password.

        The controller assigns the access level from the password (e.g. level 50),
        so use this instead of login() when you need write access. Note the
        controller caches the assigned level for ~2 minutes after the line drops,
        so allow a cooldown between attempts with different passwords.
        """
        self._ensure_serial_available(destination)
        payload = self.create_login_packet_data_standard(password, login_id)
        login_data = self.encode(payload, self.encoded_serial)
        return self.send_packet(destination, self.REQ_LOGIN_STANDARD, login_data)
    
    def get_controller_time(self, destination: bytes) -> datetime.datetime:
        """Get controller time and convert to datetime."""
        timestamp = self.request_data(destination, self.DATA_ID_CONTROLLER_TIME, 0)
        # Parse timestamp string in format YYMMDDHHmmSS as UTC
        return datetime.datetime.strptime(timestamp, "%y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)

    def set_controller_time(self, destination: bytes,
                           time: Optional[datetime.datetime] = None) -> MnetPacket:
        """Set controller time.

        Args:
            destination: Target device address
            time: Datetime to set (defaults to current UTC time if None)

        Returns:
            Response packet from controller
        """
        self._ensure_serial_available(destination)

        if time is None:
            time = datetime.datetime.now(datetime.timezone.utc)

        # Ensure timezone-aware datetime in UTC
        if time.tzinfo is None:
            time = time.replace(tzinfo=datetime.timezone.utc)
        else:
            time = time.astimezone(datetime.timezone.utc)

        # Convert to seconds since 1980-01-01 epoch
        epoch = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
        timestamp = int((time - epoch).total_seconds())

        # Build write data payload: data_id (2 bytes) + sub_id (2 bytes) + value (4 bytes)
        # Sub-ID 0x0001 is used for write operations
        write_data = (self.DATA_ID_CONTROLLER_TIME +
                     struct.pack('!H', 1) +  # sub_id = 0x0001
                     struct.pack('!I', timestamp))

        return self.send_packet(destination, self.REQ_WRITE_DATA, write_data)

    def timestamp_to_datetime(self, timestamp: int) -> datetime.datetime:
        """Convert timestamp to datetime (epoch: 1980-01-01)."""
        epoch = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
        return epoch + datetime.timedelta(seconds=timestamp)

    # Sentinel date indicating alarm has never occurred
    ALARM_NEVER_OCCURRED_DATE = datetime.datetime(2032, 5, 9, 6, 24, 0,
                                                   tzinfo=datetime.timezone.utc)

    def get_event(self, destination: bytes, index: int) -> Optional[Event]:
        """Get a single event from the event stack.

        Args:
            destination: Target device address
            index: Event index (0 = most recent, up to 99)

        Returns:
            Event namedtuple or None if index is empty
        """
        if not 0 <= index < self.EVENT_STACK_MAX_EVENTS:
            raise ValueError(f"Event index must be 0-{self.EVENT_STACK_MAX_EVENTS - 1}")

        base = index * self.EVENT_STACK_INDEX_MULTIPLIER
        code = self.request_data(destination, self.DATA_ID_EVENT_STACK_STATUS_CODE,
                                 base + self.EVENT_STACK_SUBID_CODE)
        if code is None:
            return None

        timestamp = self.request_data(destination, self.DATA_ID_EVENT_STACK_STATUS_CODE,
                                      base + self.EVENT_STACK_SUBID_TIMESTAMP)
        text = self.request_data(destination, self.DATA_ID_EVENT_STACK_STATUS_CODE,
                                 base + self.EVENT_STACK_SUBID_TEXT)

        return Event(
            index=index,
            code=int(code),
            timestamp=timestamp,
            text=text.strip() if isinstance(text, str) else str(text)
        )

    def get_events(self, destination: bytes,
                   limit: Optional[int] = None) -> Iterator[Event]:
        """Iterate over events in the event stack.

        Args:
            destination: Target device address
            limit: Maximum number of events to return (default: all 100)

        Yields:
            Event namedtuples, most recent first
        """
        max_events = min(limit or self.EVENT_STACK_MAX_EVENTS,
                        self.EVENT_STACK_MAX_EVENTS)

        for index in range(max_events):
            event = self.get_event(destination, index)
            if event is not None:
                yield event

    def get_events_batch(self, destination: bytes, limit: int = 10) -> List[Event]:
        """Fetch multiple events from the event stack using chunked batch requests.

        Splits requests into smaller chunks to stay within controller limits.

        Args:
            destination: Target device address
            limit: Number of events to fetch (default: 10)

        Returns:
            List of Event namedtuples, most recent first (index 0)
        """
        # 3 items per event (code, timestamp, text), chunk to stay under limit
        # Event stack has lower batch limit (12 items max), so 4 events per chunk
        items_per_event = 3
        events_per_chunk = 4

        events = []
        for chunk_start in range(0, limit, events_per_chunk):
            chunk_end = min(chunk_start + events_per_chunk, limit)

            # Build request list for this chunk
            requests = []
            for index in range(chunk_start, chunk_end):
                base = index * self.EVENT_STACK_INDEX_MULTIPLIER
                requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                               base + self.EVENT_STACK_SUBID_CODE))
                requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                               base + self.EVENT_STACK_SUBID_TIMESTAMP))
                requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                               base + self.EVENT_STACK_SUBID_TEXT))

            # Execute batch request for this chunk
            results = self.request_multiple_data(destination, requests)

            # Parse results into Event objects (3 results per event)
            for i, index in enumerate(range(chunk_start, chunk_end)):
                base_idx = i * 3
                if base_idx + 2 >= len(results):
                    break

                code = results[base_idx]
                timestamp = results[base_idx + 1]
                text = results[base_idx + 2]

                if code is None:
                    continue

                events.append(Event(
                    index=index,
                    code=int(code) if code is not None else 0,
                    timestamp=timestamp,
                    text=text.strip() if isinstance(text, str) else str(text)
                ))

        return events

    def get_alarm_record(self, destination: bytes, sub_id: int) -> Optional[AlarmRecord]:
        """Get the last occurrence record for a specific alarm type.

        Args:
            destination: Target device address
            sub_id: Alarm sub_id (use known values like 5=Vibration, 18=Emergency stop)

        Returns:
            AlarmRecord namedtuple or None if sub_id is invalid
        """
        try:
            timestamp = self.request_data(destination, self.DATA_ID_ALARM_LAST_OCCURRED, sub_id)
            if timestamp is None:
                return None

            description = self.request_data(destination, self.DATA_ID_STATUS_TEXT, sub_id)
            if description is None:
                return None

            # Check if alarm has actually occurred (not the "never" sentinel date)
            has_occurred = True
            if hasattr(timestamp, 'year') and timestamp.year == 2032:
                has_occurred = False

            return AlarmRecord(
                sub_id=sub_id,
                last_occurred=timestamp,
                description=description.strip() if isinstance(description, str) else str(description),
                has_occurred=has_occurred
            )
        except Exception:
            return None

    # Known alarm sub_ids (discovered via scanning)
    ALARM_SUB_IDS = {
        5: 'Vibration',
        7: 'Turbine is serviced',
        9: 'Remote stop',
        11: 'Stop via communica.',
        13: 'Manual stop',
        18: 'Emergency stop',
        23: 'Repeating error',
        29: 'New program',
        38: 'Alarm call test',
        39: 'Division by zero',
        40: 'Parameter crash',
        42: 'Internal battery low',
        45: 'Main ctrl. Supply',
        51: 'DSP watchdog',
        53: 'Main ctrl. watchdog',
        55: 'Main ctrl.man.reboot',
        99: 'Parkmasterstop',
        100: 'Repeated grid error',
        102: 'Phase drop',
        103: 'Vector surge',
        110: 'Voltage high',
        111: 'Voltage low',
        120: 'Frequency high',
        121: 'Frequency low',
        138: 'Grid param. warning',
        139: 'Grid parameter stop',
        227: 'Anemometer defect',
        240: 'Awaiting wind',
        250: 'Wind > max.',
        300: '(G) tacho defect',
        302: '(R) tacho defect',
        311: 'Rotor overspeed',
        312: '(G) overspeed',
        314: 'Free wheeling oversp',
        415: 'Brake pads worn',
        416: 'Replace brake pads',
        421: 'Brake not released',
        434: 'B200 brake time>max.',
        501: 'Power consumption',
        521: '(G) hot',
        530: '(G) power too high',
        537: '(G) peak power',
        601: 'Current asymmetry',
        607: 'Auto. motorstart',
        609: 'Thyristor block hot',
        651: 'Cut in 0_>G1',
        662: 'WP4060 error',
        722: 'Cable twisted',
    }

    def get_alarm_history(self, destination: bytes,
                          only_occurred: bool = False) -> Iterator[AlarmRecord]:
        """Iterate over alarm types and their last occurrence times.

        Args:
            destination: Target device address
            only_occurred: If True, only yield alarms that have actually occurred

        Yields:
            AlarmRecord namedtuples
        """
        for sub_id in sorted(self.ALARM_SUB_IDS.keys()):
            record = self.get_alarm_record(destination, sub_id)
            if record is not None:
                if only_occurred and not record.has_occurred:
                    continue
                yield record

    def get_alarm_history_batch(self, destination: bytes,
                                only_occurred: bool = False) -> List[AlarmRecord]:
        """Fetch alarm history using chunked batch requests.

        Splits requests into smaller chunks to stay within controller limits.
        Uses cached descriptions when available (populated on first call),
        so subsequent calls only fetch timestamps.

        Args:
            destination: Target device address
            only_occurred: If True, only return alarms that have actually occurred

        Returns:
            List of AlarmRecord namedtuples, sorted by sub_id
        """
        sub_ids = sorted(self.ALARM_SUB_IDS.keys())
        use_cache = len(self._alarm_description_cache) >= len(sub_ids)

        alarms = []

        if use_cache:
            # Only fetch timestamps - can fit more per batch
            for chunk_start in range(0, len(sub_ids), self.MAX_BATCH_SIZE):
                chunk_sub_ids = sub_ids[chunk_start:chunk_start + self.MAX_BATCH_SIZE]
                requests = [(self.DATA_ID_ALARM_LAST_OCCURRED, sub_id) for sub_id in chunk_sub_ids]
                results = self.request_multiple_data(destination, requests)

                for i, sub_id in enumerate(chunk_sub_ids):
                    if i >= len(results):
                        break
                    timestamp = results[i]
                    description = self._alarm_description_cache.get(sub_id, '')

                    if timestamp is None:
                        continue

                    has_occurred = not (hasattr(timestamp, 'year') and timestamp.year == 2032)
                    if only_occurred and not has_occurred:
                        continue

                    alarms.append(AlarmRecord(
                        sub_id=sub_id,
                        last_occurred=timestamp,
                        description=description.strip() if isinstance(description, str) else str(description),
                        has_occurred=has_occurred
                    ))
        else:
            # Fetch timestamps + descriptions (2 items per alarm, smaller chunks)
            items_per_alarm = 2
            alarms_per_chunk = self.MAX_BATCH_SIZE // items_per_alarm

            for chunk_start in range(0, len(sub_ids), alarms_per_chunk):
                chunk_sub_ids = sub_ids[chunk_start:chunk_start + alarms_per_chunk]
                requests = []
                for sub_id in chunk_sub_ids:
                    requests.append((self.DATA_ID_ALARM_LAST_OCCURRED, sub_id))
                    requests.append((self.DATA_ID_STATUS_TEXT, sub_id))

                results = self.request_multiple_data(destination, requests)

                for i, sub_id in enumerate(chunk_sub_ids):
                    base_idx = i * 2
                    if base_idx + 1 >= len(results):
                        break

                    timestamp = results[base_idx]
                    description = results[base_idx + 1]

                    # Cache description for future calls
                    if isinstance(description, str):
                        self._alarm_description_cache[sub_id] = description.strip()

                    if timestamp is None:
                        continue

                    has_occurred = not (hasattr(timestamp, 'year') and timestamp.year == 2032)
                    if only_occurred and not has_occurred:
                        continue

                    alarms.append(AlarmRecord(
                        sub_id=sub_id,
                        last_occurred=timestamp,
                        description=description.strip() if isinstance(description, str) else str(description),
                        has_occurred=has_occurred
                    ))

        return alarms