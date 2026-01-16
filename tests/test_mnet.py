import unittest
from unittest.mock import Mock, patch, MagicMock
import struct
import datetime
from crc import Calculator, Crc16
import pytest

from mnet import Mnet


class TestMnetPacket(unittest.TestCase):
    """Test cases for the MnetPacket inner class."""
    
    def setUp(self):
        self.destination = b'\x02'
        self.source = b'\x01'
        self.packet_type = b'\x0c\x28'
        self.data = b'\x9c\x43'
        
    def test_packet_creation(self):
        """Test basic packet creation."""
        packet = Mnet.MnetPacket(
            self.destination, self.source, self.packet_type, 
            len(self.data), self.data
        )
        
        self.assertEqual(packet.destination, self.destination)
        self.assertEqual(packet.source, self.source)
        self.assertEqual(packet.packet_type, self.packet_type)
        self.assertEqual(packet.data_len, len(self.data))
        self.assertEqual(packet.data, self.data)
        
    def test_packet_with_custom_crc(self):
        """Test packet creation with custom CRC."""
        custom_crc = 0x1234
        packet = Mnet.MnetPacket(
            self.destination, self.source, self.packet_type,
            len(self.data), self.data, custom_crc
        )
        
        self.assertEqual(packet.crc, custom_crc)
        self.assertNotEqual(packet.crc, packet.calculated_crc)
        
    def test_packet_data_escaping(self):
        """Test that 0xFF bytes are properly escaped in packet data."""
        data_with_ff = b'\x9c\xff\x43'
        packet = Mnet.MnetPacket(
            self.destination, self.source, self.packet_type,
            len(data_with_ff), data_with_ff
        )
        
        self.assertIn(b'\xff\xff', packet.real_data)
        
    def test_packet_str_representation(self):
        """Test string representation of packet."""
        packet = Mnet.MnetPacket(
            self.destination, self.source, self.packet_type,
            len(self.data), self.data
        )
        
        str_repr = str(packet)
        self.assertIn('sot:01', str_repr)
        self.assertIn('dst:0x02', str_repr)
        self.assertIn('src:0x01', str_repr)
        self.assertIn('eot:04', str_repr)
        
    def test_packet_bytes_representation(self):
        """Test bytes representation of packet."""
        packet = Mnet.MnetPacket(
            self.destination, self.source, self.packet_type,
            len(self.data), self.data
        )
        
        packet_bytes = bytes(packet)
        self.assertTrue(packet_bytes.startswith(Mnet.MnetPacket.SOH))
        self.assertTrue(packet_bytes.endswith(Mnet.MnetPacket.EOT))


class TestMnet(unittest.TestCase):
    """Test cases for the main Mnet class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_serial = Mock()
        self.device_path = '/dev/ttyUSB0'
        self.test_id = b'\x01'
        
    def test_mnet_initialization(self):
        """Test Mnet class initialization."""
        mnet_instance = Mnet(self.mock_serial, self.test_id)
        
        self.assertEqual(mnet_instance.id, self.test_id)
        self.assertEqual(mnet_instance.device, self.mock_serial)
        self.assertIsNone(mnet_instance.serial)
        self.assertIsNone(mnet_instance.encoded_serial)
        
    def test_create_packet(self):
        """Test packet creation method."""
        mnet_instance = Mnet(self.mock_serial, self.test_id)
        
        destination = b'\x02'
        packet_type = b'\x0c\x28'
        data = b'\x9c\x43'
        
        packet = mnet_instance.create_packet(destination, packet_type, data)
        
        self.assertIsInstance(packet, Mnet.MnetPacket)
        self.assertEqual(packet.destination, destination)
        self.assertEqual(packet.source, self.test_id)
        self.assertEqual(packet.packet_type, packet_type)
        
    def test_read_packet(self):
        """Test reading packet from serial device."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock serial read responses
        header_data = struct.pack('!BBBHB', 0x01, 0x02, 0x01, 0x0c28, 2)
        data = b'\x9c\x43'
        tail_data = struct.pack('!HB', 0x1234, 0x04)
        
        self.mock_serial.read.side_effect = [header_data, data, tail_data]
        
        packet = mnet_instance.read_packet()
        
        self.assertIsInstance(packet, Mnet.MnetPacket)
        self.assertEqual(packet.data, data)
        self.assertEqual(packet.crc, 0x1234)
        
    def test_read_packet_no_data(self):
        """Test reading packet with no data payload."""
        mnet_instance = Mnet(self.mock_serial)
        
        header_data = struct.pack('!BBBHB', 0x01, 0x02, 0x01, 0x0c28, 0)
        tail_data = struct.pack('!HB', 0x1234, 0x04)
        
        self.mock_serial.read.side_effect = [header_data, tail_data]
        
        packet = mnet_instance.read_packet()
        
        self.assertEqual(packet.data, b'')
        
    def test_get_serial_number(self):
        """Test getting serial number from device."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock the response packet
        serial_data = struct.pack('!L', 12345678)
        mock_packet = Mock()
        mock_packet.data = serial_data
        
        with patch.object(mnet_instance, 'send_packet', return_value=mock_packet):
            serial, serial_bytes = mnet_instance.get_serial_number(b'\x02')
            
            self.assertEqual(serial, 12345678)
            self.assertEqual(serial_bytes, serial_data)
            
    def test_encode_serial(self):
        """Test serial number encoding algorithm."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Test with known values
        serial_bytes = b'\x01\x02\x03\x04'
        encoded = mnet_instance.encode_serial(serial_bytes)
        
        self.assertEqual(len(encoded), 5)
        self.assertIsInstance(encoded, bytearray)
            
    def test_encode_decode_data(self):
        """Test data encoding and decoding."""
        mnet_instance = Mnet(self.mock_serial)
        
        original_data = b'Hello, World!'
        enc_serial = bytearray([0x01, 0x02, 0x03, 0x04, 0x05])
        
        encoded = mnet_instance.encode(original_data, enc_serial)
        decoded = mnet_instance.decode(encoded, enc_serial)
        
        self.assertEqual(decoded, original_data)
            
    def test_decode_data_types(self):
        """Test decoding different data types."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Test type 0x1 (signed byte) - now works correctly
        data = struct.pack('!BBHB', 0x1, 0x0, 0x0, 0x1) + struct.pack('!b', -5)
        data_type, value = mnet_instance.decode_data(data)
        self.assertEqual(data_type, 0x1)
        self.assertEqual(value, -5)
        
        # Test type 0x4 (unsigned short) with conversion - this works
        data = struct.pack('!BBHB', 0x4, 0x1, 0x2, 0x2) + struct.pack('!H', 1234)
        data_type, value = mnet_instance.decode_data(data)
        self.assertEqual(data_type, 0x4)
        self.assertEqual(value, 12.34)  # 1234 / 10^2
            
    def test_decode_multiple_data(self):
        """Test decoding multiple data elements."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Test decoding multiple data elements - now works correctly
        # Create test data with 2 elements
        num_elements = 2
        element1_header = struct.pack("!HHBBHB", 0x9c43, 0x0000, 0x1, 0x0, 0x0, 0x1)
        element1_data = struct.pack('!b', 10)
        element2_header = struct.pack("!HHBBHB", 0x9c47, 0x0000, 0x4, 0x1, 0x1, 0x2)
        element2_data = struct.pack('!H', 1500)
        
        test_data = (bytes([num_elements]) + 
                    element1_header + element1_data +
                    element2_header + element2_data)
        
        # This now works correctly
        result = mnet_instance.decode_multiple_data(test_data)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0][0], 0x9c43)  # mainid
        self.assertEqual(result[0][2][1], 10)   # decoded value
        self.assertEqual(result[1][0], 0x9c47)  # mainid
        self.assertEqual(result[1][2][1], 150.0) # decoded value (1500 / 10^1)
            
    def test_create_login_packet_data(self):
        """Test login packet data creation."""
        mnet_instance = Mnet(self.mock_serial)
        
        login_data = mnet_instance.create_login_packet_data()
        
        self.assertEqual(len(login_data), 32)  # 20 + 12 bytes
        self.assertTrue(login_data.startswith(Mnet.LOGIN_131_GAIA_WIND))
        
    def test_send_command(self):
        """Test sending command to device."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock serial number retrieval
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        mock_response = Mock()
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response):
            result = mnet_instance.send_command(b'\x02', Mnet.DATA_COMMAND_START)
            
            self.assertEqual(result, mock_response)
            
    def test_request_data(self):
        """Test requesting single data value."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock dependencies
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        # Mock response
        mock_response = Mock()
        encoded_data = b'\x04\x01\x00\x02\x02\x04\xd2'  # Example encoded data
        mock_response.data = encoded_data
        
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response):
            with patch.object(mnet_instance, 'decode', return_value=b'\x04\x01\x00\x02\x02\x04\xd2'):
                with patch.object(mnet_instance, 'decode_data', return_value=(0x4, 12.34)):
                    result = mnet_instance.request_data(b'\x02', Mnet.DATA_ID_WIND_SPEED)
                    
                    self.assertEqual(result, 12.34)
                    
    def test_request_multiple_data(self):
        """Test requesting multiple data values."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock dependencies
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        mock_response = Mock()
        mock_response.data = b'encoded_data'
        
        datasubids = [(Mnet.DATA_ID_WIND_SPEED, 0), (Mnet.DATA_ID_GEN_REVS, 0)]
        
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response):
            with patch.object(mnet_instance, 'decode', return_value=b'decoded_data'):
                with patch.object(mnet_instance, 'decode_multiple_data', 
                                return_value=[(0x9c43, 0, (0x4, 15.5)), (0x9c47, 0, (0x4, 1800))]):
                    result = mnet_instance.request_multiple_data(b'\x02', datasubids)
                    
                    self.assertEqual(len(result), 2)
                    self.assertEqual(result[0], 15.5)
                    self.assertEqual(result[1], 1800)
                    
    def test_request_multiple_data_with_ids(self):
        """Test requesting multiple data values with IDs included."""
        mnet_instance = Mnet(self.mock_serial)
        
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        mock_response = Mock()
        mock_response.data = b'encoded_data'
        
        datasubids = [(Mnet.DATA_ID_WIND_SPEED, 0)]
        
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response):
            with patch.object(mnet_instance, 'decode', return_value=b'decoded_data'):
                with patch.object(mnet_instance, 'decode_multiple_data', 
                                return_value=[(0x9c43, 0, (0x4, 15.5))]):
                    result = mnet_instance.request_multiple_data(b'\x02', datasubids, include_ids=True)
                    
                    self.assertEqual(len(result), 1)
                    self.assertEqual(result[0][0], Mnet.DATA_ID_WIND_SPEED)
                    self.assertEqual(result[0][1], 0)
                    self.assertEqual(result[0][2], 15.5)
                    
    def test_timestamp_to_datetime(self):
        """Test timestamp conversion to datetime."""
        mnet_instance = Mnet(self.mock_serial)

        # Test with known timestamp
        seconds = 86400  # 1 day after epoch
        result = mnet_instance.timestamp_to_datetime(seconds)

        expected = datetime.datetime(1980, 1, 2, tzinfo=datetime.timezone.utc)  # 1 day after 1980-01-01
        self.assertEqual(result, expected)

    def test_set_controller_time(self):
        """Test setting controller time."""
        mnet_instance = Mnet(self.mock_serial)

        # Mock serial number retrieval
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])

        mock_response = Mock()
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response) as mock_send:
            # Test with specific datetime
            test_time = datetime.datetime(2026, 1, 16, 18, 20, 13, tzinfo=datetime.timezone.utc)
            result = mnet_instance.set_controller_time(b'\x02', test_time)

            self.assertEqual(result, mock_response)

            # Verify send_packet was called with correct parameters
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            self.assertEqual(call_args[0][0], b'\x02')  # destination
            self.assertEqual(call_args[0][1], Mnet.REQ_WRITE_DATA)  # packet type

            # Verify payload structure: data_id (2) + sub_id (2) + timestamp (4)
            payload = call_args[0][2]
            self.assertEqual(len(payload), 8)
            self.assertEqual(payload[:2], Mnet.DATA_ID_CONTROLLER_TIME)
            self.assertEqual(payload[2:4], b'\x00\x01')  # sub_id = 0x0001

            # Verify timestamp calculation (seconds since 1980-01-01)
            epoch = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
            expected_timestamp = int((test_time - epoch).total_seconds())
            actual_timestamp = struct.unpack('!I', payload[4:8])[0]
            self.assertEqual(actual_timestamp, expected_timestamp)

    def test_set_controller_time_default(self):
        """Test setting controller time with default (current) time."""
        mnet_instance = Mnet(self.mock_serial)

        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])

        mock_response = Mock()
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response) as mock_send:
            # Test with no time argument (should use current time)
            before_call = datetime.datetime.now(datetime.timezone.utc)
            result = mnet_instance.set_controller_time(b'\x02')
            after_call = datetime.datetime.now(datetime.timezone.utc)

            self.assertEqual(result, mock_response)

            # Verify the timestamp is reasonable (within the call window)
            payload = mock_send.call_args[0][2]
            actual_timestamp = struct.unpack('!I', payload[4:8])[0]

            epoch = datetime.datetime(1980, 1, 1, tzinfo=datetime.timezone.utc)
            min_expected = int((before_call - epoch).total_seconds())
            max_expected = int((after_call - epoch).total_seconds())
            self.assertGreaterEqual(actual_timestamp, min_expected)
            self.assertLessEqual(actual_timestamp, max_expected)

    def test_constants(self):
        """Test that all required constants are defined."""
        constants = [
            'SOH', 'EOT', 'MAX_PACKET_SIZE', 'REQ_MULTIPLE_DATA', 'REQ_DATA',
            'REQ_WRITE_DATA', 'REQ_COMMAND', 'REQ_SERIAL_NUMBER', 'LOGIN_131_GAIA_WIND', 'LOGIN_PACKET_ID',
            'DATA_ID_WIND_SPEED', 'DATA_ID_GEN_REVS', 'DATA_ID_ROTOR_REVS',
            'DATA_ID_L1V', 'DATA_ID_L2V', 'DATA_ID_L3V', 'DATA_ID_L1A', 'DATA_ID_L2A', 'DATA_ID_L3A',
            'DATA_ID_SYSTEM_PRODUCTION', 'DATA_ID_G1_PRODUCTION', 'DATA_ID_CONTROLLER_TIME',
            'DATA_ID_GRID_POWER', 'DATA_ID_GRID_CURRENT', 'DATA_ID_GRID_VOLTAGE', 'DATA_ID_GRID_VAR',
            'DATA_ID_CURRENT_STATUS_CODE', 'DATA_ID_EVENT_STACK_STATUS_CODE',
            'DATA_COMMAND_EMPTY', 'DATA_COMMAND_START', 'DATA_COMMAND_STOP', 'DATA_COMMAND_RESET', 'DATA_COMMAND_MANUAL_START'
        ]
        
        for constant in constants:
            self.assertTrue(hasattr(Mnet, constant), f"Missing constant: {constant}")


class TestMnetIntegration(unittest.TestCase):
    """Integration tests for Mnet functionality."""
    
    def test_full_workflow(self):
        """Test a complete workflow from initialization to data request."""
        mock_serial = Mock()

        mnet_instance = Mnet(mock_serial)
        mnet_instance._log_callback = Mock()

        # Mock the get_serial_number to avoid complex mocking
        with patch.object(mnet_instance, 'get_serial_number', return_value=(12345678, struct.pack('!L', 12345678))):
            # Mock the send_packet for the data request
            mock_response = Mock()
            mock_response.data = b'encoded_response'

            with patch.object(mnet_instance, 'send_packet', return_value=mock_response):
                with patch.object(mnet_instance, 'decode_data', return_value=(0x4, 15.5)):
                    result = mnet_instance.request_data(b'\x02', Mnet.DATA_ID_WIND_SPEED)

                    self.assertEqual(result, 15.5)
                    self.assertEqual(mnet_instance.serial, 12345678)
                    self.assertIsNotNone(mnet_instance.encoded_serial)


class TestMnetErrorHandling(unittest.TestCase):
    """Test error handling in Mnet class."""
    
    def test_serial_connection_error(self):
        """Test handling of serial connection errors."""
        mock_device = Mock()
        mock_device.read.side_effect = Exception("Serial port not found")
        
        mnet_instance = Mnet(mock_device)
        with self.assertRaises(Exception):
            mnet_instance.read_packet()
            
    def test_decode_data_invalid_type(self):
        """Test handling of invalid data types in decode_data."""
        mnet_instance = Mnet(Mock())
        
        # Test with unsupported data type
        invalid_data = struct.pack('!BBHB', 0xFF, 0x0, 0x0, 0x1) + b'\x00'
        
        # Should raise ValueError for unsupported types (improved error handling)
        with self.assertRaises(ValueError):
            mnet_instance.decode_data(invalid_data)


if __name__ == '__main__':
    unittest.main()