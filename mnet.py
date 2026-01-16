"""
Mnet Protocol Implementation

Provides communication interface for wind turbine controllers using the Mnet protocol.
"""

import socket
import struct
import datetime
from typing import Tuple, List, Union, Optional, Iterator, NamedTuple
from crc import Calculator, Crc16


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
    REQ_LOGIN = b'\x13\xa1'
    
    # Login constants
    LOGIN_131_GAIA_WIND = b'\x31\x33\x31\x20\x66\x6b\x59\x75\x29\x29\x31\x32\x32\x32\x31\x51\x51\x61\x61\x00'
    LOGIN_PACKET_ID = 0x7b
    
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

    # Sub-IDs for EVENT_STACK_STATUS_CODE (0x000B)
    # Event history is at sub_id = (event_index * 100) + offset
    # event_index 0 = most recent, up to 99 (100 events total)
    EVENT_STACK_SUBID_CODE = 0       # Status code number (0 is valid, e.g., "COMPENSATOR 1 IN")
    EVENT_STACK_SUBID_TIMESTAMP = 1  # When event occurred
    EVENT_STACK_SUBID_TEXT = 2       # Human-readable event description (use this, not lookup)
    EVENT_STACK_INDEX_MULTIPLIER = 100  # sub_id = event_index * 100 + offset
    EVENT_STACK_MAX_EVENTS = 100     # Stack holds 100 events (indices 0-99)

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
    
    # Command aliases for backward compatibility
    DATA_ID_START = DATA_COMMAND_START
    DATA_ID_STOP = DATA_COMMAND_STOP
    DATA_ID_RESET = DATA_COMMAND_RESET
    DATA_ID_MANUAL_START = DATA_COMMAND_MANUAL_START

    # Data IDs that use data_type 6 (uint32) but should NOT be converted to datetime
    # These return numeric values even though the protocol marks them as "timestamp" type
    DATA_IDS_NOT_TIMESTAMP = {
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
    
    def create_packet(self, destination: bytes, packet_type: bytes, data: bytes) -> MnetPacket:
        """Create an Mnet packet."""
        return MnetPacket(destination, self.id, packet_type, len(data), data)
    
    def send_packet(self, destination: bytes, packet_type: bytes, data: bytes) -> MnetPacket:
        """Send packet and return response."""
        packet = self.create_packet(destination, packet_type, data)
        packet_bytes = bytes(packet)
        
        # Log outgoing packet
        if self._log_callback:
            self._log_callback('TX', packet_bytes.hex(), str(packet))
        
        self.device.write(packet_bytes)
        response = self.read_packet()
        
        # Log incoming response
        if self._log_callback:
            response_bytes = bytes(response)
            self._log_callback('RX', response_bytes.hex(), str(response))
        
        return response
    
    def read_packet(self) -> MnetPacket:
        """Read packet from device."""
        header = self.device.read(6)
        soh, destination, source, packet_type, data_len = struct.unpack('!BBBHB', header)
        
        data = self.device.read(data_len) if data_len > 0 else b''
        
        tail = self.device.read(3)
        crc, eot = struct.unpack('!HB', tail)
        
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
    
    def decode_multiple_data(self, data_in: bytes) -> List[Tuple[int, int, Tuple[int, Union[float, str, None]]]]:
        """Decode multiple data elements from response."""
        if not data_in:
            return []

        num_elements = data_in[0]
        pos = 1
        results = []

        for _ in range(num_elements):
            if pos + 9 > len(data_in):
                break

            header = data_in[pos:pos+9]
            mainid, subid, _, _, _, length = struct.unpack("!HHBBHB", header)

            next_data = data_in[pos+4:pos+9+length]
            # Pass mainid to decode_data for proper type handling
            decoded = self.decode_data(next_data, data_id=mainid)
            results.append((mainid, subid, decoded))

            pos += 9 + length

        return results
    
    def create_login_packet_data(self) -> bytes:
        """Create login packet data."""
        return struct.pack('=20sBBBBBBBBBBBB',
                          self.LOGIN_131_GAIA_WIND,
                          0xff, 0xff,
                          self.LOGIN_PACKET_ID >> 0x18,
                          self.LOGIN_PACKET_ID >> 0x10,
                          self.LOGIN_PACKET_ID >> 8,
                          self.LOGIN_PACKET_ID,
                          5, 0, 0, 0, 0, 0)
    
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
        
        results = self.decode_multiple_data(decoded_data)
        
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
        """Perform login to device."""
        self._ensure_serial_available(destination)
        login_data = self.encode(self.create_login_packet_data(), self.encoded_serial)
        return self.send_packet(destination, self.REQ_LOGIN, login_data)
    
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
        """Fetch multiple events from the event stack in a single batch request.

        This is more efficient than calling get_event() repeatedly, as it
        combines all event data (code, timestamp, text) for multiple events
        into a single request_multiple_data() call.

        Args:
            destination: Target device address
            limit: Number of events to fetch (default: 10, max: 33 due to packet size)

        Returns:
            List of Event namedtuples, most recent first (index 0)
        """
        # Limit batch size due to packet size constraints (3 items per event)
        # Max ~33 events per batch (99 data items + overhead)
        max_batch = min(limit, 33)

        # Build request list: for each event, request code, timestamp, and text
        requests = []
        for index in range(max_batch):
            base = index * self.EVENT_STACK_INDEX_MULTIPLIER
            requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                           base + self.EVENT_STACK_SUBID_CODE))
            requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                           base + self.EVENT_STACK_SUBID_TIMESTAMP))
            requests.append((self.DATA_ID_EVENT_STACK_STATUS_CODE,
                           base + self.EVENT_STACK_SUBID_TEXT))

        # Execute batch request
        results = self.request_multiple_data(destination, requests)

        # Parse results into Event objects (3 results per event)
        events = []
        for i in range(max_batch):
            base_idx = i * 3
            if base_idx + 2 >= len(results):
                break

            code = results[base_idx]
            timestamp = results[base_idx + 1]
            text = results[base_idx + 2]

            if code is None:
                continue

            events.append(Event(
                index=i,
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
        """Fetch alarm history in a single batch request.

        This is more efficient than calling get_alarm_record() repeatedly, as it
        combines all alarm data (timestamp and description) for all known alarm
        types into a single request_multiple_data() call.

        Args:
            destination: Target device address
            only_occurred: If True, only return alarms that have actually occurred

        Returns:
            List of AlarmRecord namedtuples, sorted by sub_id
        """
        sub_ids = sorted(self.ALARM_SUB_IDS.keys())

        # Build request list: for each alarm, request timestamp and description
        requests = []
        for sub_id in sub_ids:
            requests.append((self.DATA_ID_ALARM_LAST_OCCURRED, sub_id))
            requests.append((self.DATA_ID_STATUS_TEXT, sub_id))

        # Execute batch request
        results = self.request_multiple_data(destination, requests)

        # Parse results into AlarmRecord objects (2 results per alarm)
        alarms = []
        for i, sub_id in enumerate(sub_ids):
            base_idx = i * 2
            if base_idx + 1 >= len(results):
                break

            timestamp = results[base_idx]
            description = results[base_idx + 1]

            if timestamp is None:
                continue

            # Check if alarm has actually occurred (not the "never" sentinel date)
            has_occurred = True
            if hasattr(timestamp, 'year') and timestamp.year == 2032:
                has_occurred = False

            if only_occurred and not has_occurred:
                continue

            alarms.append(AlarmRecord(
                sub_id=sub_id,
                last_occurred=timestamp,
                description=description.strip() if isinstance(description, str) else str(description),
                has_occurred=has_occurred
            ))

        return alarms