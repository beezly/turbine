"""
Mnet Protocol Implementation

Provides communication interface for wind turbine controllers using the Mnet protocol.
"""

import socket
import struct
import datetime
from typing import Tuple, List, Union, Optional
from crc import Calculator, Crc16


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
    
    def decode_data(self, data_in: bytes) -> Tuple[int, Union[float, str, None]]:
        """Decode data value from response."""
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
        
        if data_type == 6:
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
            decoded = self.decode_data(next_data)
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
        _, value = self.decode_data(decoded_data)
        
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