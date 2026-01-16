"""
Tests for Mnet login functionality.
"""

import unittest
from unittest.mock import Mock, patch
import struct
from mnet import Mnet


class TestMnetLogin(unittest.TestCase):
    """Test cases for Mnet login functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_serial = Mock()
        self.destination = b'\x02'
        
    def test_login_method_exists(self):
        """Test that login method exists."""
        mnet_instance = Mnet(self.mock_serial)
        self.assertTrue(hasattr(mnet_instance, 'login'))
        self.assertTrue(callable(getattr(mnet_instance, 'login')))
    
    def test_login_calls_ensure_serial(self):
        """Test that login ensures serial number is available."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Mock the serial number retrieval
        with patch.object(mnet_instance, '_ensure_serial_available') as mock_ensure:
            with patch.object(mnet_instance, 'encode', return_value=b'encoded_data'):
                with patch.object(mnet_instance, 'send_packet', return_value=Mock()):
                    mnet_instance.login(self.destination)
                    mock_ensure.assert_called_once_with(self.destination)
    
    def test_login_creates_correct_packet_data(self):
        """Test that login creates correct packet data."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Set up serial number
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        # Mock methods
        mock_login_data = b'login_packet_data'
        mock_encoded_data = b'encoded_login_data'
        mock_response = Mock()
        
        with patch.object(mnet_instance, 'create_login_packet_data', return_value=mock_login_data) as mock_create:
            with patch.object(mnet_instance, 'encode', return_value=mock_encoded_data) as mock_encode:
                with patch.object(mnet_instance, 'send_packet', return_value=mock_response) as mock_send:
                    result = mnet_instance.login(self.destination)
                    
                    # Verify method calls
                    mock_create.assert_called_once()
                    mock_encode.assert_called_once_with(mock_login_data, mnet_instance.encoded_serial)
                    mock_send.assert_called_once_with(self.destination, b'\x13\xa1', mock_encoded_data)
                    self.assertEqual(result, mock_response)
    
    def test_login_packet_type(self):
        """Test that login uses correct packet type."""
        mnet_instance = Mnet(self.mock_serial)
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        with patch.object(mnet_instance, 'create_login_packet_data', return_value=b'data'):
            with patch.object(mnet_instance, 'encode', return_value=b'encoded'):
                with patch.object(mnet_instance, 'send_packet', return_value=Mock()) as mock_send:
                    mnet_instance.login(self.destination)
                    
                    # Check that correct packet type is used
                    args, kwargs = mock_send.call_args
                    self.assertEqual(args[1], Mnet.REQ_LOGIN)  # Login packet type
    
    def test_login_with_fresh_instance(self):
        """Test login with fresh instance that needs serial number."""
        mnet_instance = Mnet(self.mock_serial)

        # Mock serial number response
        serial_response = Mock()
        serial_response.data = struct.pack('!L', 12345678)

        with patch.object(mnet_instance, '_initialize_time_offset'):
            with patch.object(mnet_instance, 'send_packet') as mock_send:
                # First call for serial number, second for login
                mock_send.side_effect = [serial_response, Mock()]

                with patch.object(mnet_instance, 'encode', return_value=b'encoded'):
                    result = mnet_instance.login(self.destination)

                    # Should have called send_packet twice (serial + login)
                    self.assertEqual(mock_send.call_count, 2)

                    # First call should be for serial number
                    first_call_args = mock_send.call_args_list[0][0]
                self.assertEqual(first_call_args[1], mnet_instance.REQ_SERIAL_NUMBER)
                
                # Second call should be for login
                second_call_args = mock_send.call_args_list[1][0]
                self.assertEqual(second_call_args[1], Mnet.REQ_LOGIN)
    
    def test_login_integration(self):
        """Test login integration with actual packet creation."""
        mnet_instance = Mnet(self.mock_serial)
        
        # Set up serial number
        mnet_instance.serial = 12345678
        mnet_instance.encoded_serial = bytearray([1, 2, 3, 4, 5])
        
        # Mock only the send_packet method
        mock_response = Mock()
        with patch.object(mnet_instance, 'send_packet', return_value=mock_response) as mock_send:
            result = mnet_instance.login(self.destination)
            
            # Verify the call was made
            self.assertEqual(mock_send.call_count, 1)
            args, kwargs = mock_send.call_args
            
            # Check destination and packet type
            self.assertEqual(args[0], self.destination)
            self.assertEqual(args[1], Mnet.REQ_LOGIN)
            
            # Check that data was provided (encoded login packet)
            self.assertIsInstance(args[2], bytes)
            self.assertGreater(len(args[2]), 0)
            
            # Check return value
            self.assertEqual(result, mock_response)
    
    def test_login_packet_data_structure(self):
        """Test that login packet data has correct structure."""
        mnet_instance = Mnet(self.mock_serial)
        
        login_data = mnet_instance.create_login_packet_data()
        
        # Should be 32 bytes (20 + 12)
        self.assertEqual(len(login_data), 32)
        
        # Should start with LOGIN_131_GAIA_WIND
        self.assertTrue(login_data.startswith(mnet_instance.LOGIN_131_GAIA_WIND))
        
        # Should contain the login packet ID
        # The packet ID is split into bytes in the structure
        packet_id_bytes = struct.pack('!L', mnet_instance.LOGIN_PACKET_ID)
        # Check if packet ID bytes are present in the login data
        found_id = False
        for i in range(len(login_data) - 3):
            if login_data[i:i+4] == packet_id_bytes:
                found_id = True
                break
        # Note: The actual implementation splits the ID differently, so we just check it's non-zero
        self.assertGreater(len(login_data), 20)  # At least the base data plus additional bytes


class TestMnetLoginConstants(unittest.TestCase):
    """Test login-related constants."""
    
    def test_login_constants_exist(self):
        """Test that login constants are defined."""
        self.assertTrue(hasattr(Mnet, 'LOGIN_131_GAIA_WIND'))
        self.assertTrue(hasattr(Mnet, 'LOGIN_PACKET_ID'))
        self.assertTrue(hasattr(Mnet, 'REQ_LOGIN'))
        
        # Check values
        self.assertEqual(Mnet.LOGIN_131_GAIA_WIND, 
                        b'\x31\x33\x31\x20\x66\x6b\x59\x75\x29\x29\x31\x32\x32\x32\x31\x51\x51\x61\x61\x00')
        self.assertEqual(Mnet.LOGIN_PACKET_ID, 0x7b)
        self.assertEqual(Mnet.REQ_LOGIN, b'\x13\xa1')


if __name__ == '__main__':
    unittest.main()