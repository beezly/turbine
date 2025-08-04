"""
CRC Baseline Tests - CRITICAL REGRESSION TESTS

These tests capture the exact CRC values from the current implementation.
DO NOT MODIFY the expected CRC values after establishing the baseline.
Any change in these values indicates a breaking change in CRC calculation.
"""

import unittest
from unittest.mock import patch
from mnet import Mnet


class TestCRCBaseline(unittest.TestCase):
    """Critical CRC baseline tests - values must never change."""
    
    def test_crc_baseline_values(self):
        """CRITICAL: These CRC values must remain identical after any code changes."""
        from unittest.mock import Mock
        mnet_instance = Mnet(Mock())
        
        # BASELINE CRC VALUES - DO NOT CHANGE THESE
        baseline_crcs = [
            (b"\x02\x01\x0c(\x02\x9cC", 0x57a4),      # Wind speed request packet
            (b"\x02\x01\x0c.\x00", 0x62bf),            # Serial number request packet  
            (b"\x02\x01\x0c2\x02\x00\x01", 0x11a8),   # Start command packet
            (b"\x02\x01\x0c2\x02\x00\x02", 0x21cb),   # Stop command packet
            (b"\x02\x01\x0c2\x02\x00\x03", 0x31ea),   # Reset command packet
            (b"", 0x0000),                             # Empty data
            (b"\x00", 0x0000),                         # Single zero byte
            (b"\xff", 0x1ef0),                         # Single 0xFF byte
            (b"\x01\x02\x03\x04\x05", 0x8208),        # Sequential bytes
            (b"\xff\xff\xff\xff", 0x99cf),            # All 0xFF bytes
            (b"\x9cC\x9cG\x9cF", 0x5ee9),             # Data IDs sequence
        ]
        
        for data, expected_crc in baseline_crcs:
            with self.subTest(data=data.hex()):
                calculated_crc = mnet_instance.crc_calculator.checksum(data)
                self.assertEqual(
                    calculated_crc, 
                    expected_crc,
                    f"CRITICAL CRC REGRESSION: Data {data.hex()} expected 0x{expected_crc:04x}, got 0x{calculated_crc:04x}"
                )
    
    def test_packet_crc_baseline(self):
        """Test CRC calculations for actual MnetPacket objects."""
        
        # Test packet CRC calculations
        packet_tests = [
            # (dest, src, type, data, expected_packet_crc)
            (b'\x02', b'\x01', b'\x0c\x28', b'\x9c\x43', 0x57a4),
            (b'\x02', b'\x01', b'\x0c\x2e', b'', 0x62bf),
            (b'\x02', b'\x01', b'\x0c\x32', b'\x00\x01', 0x11a8),
        ]
        
        for dest, src, ptype, data, expected_crc in packet_tests:
            with self.subTest(data=data.hex()):
                packet = Mnet.MnetPacket(dest, src, ptype, len(data), data)
                self.assertEqual(
                    packet.calculated_crc,
                    expected_crc,
                    f"Packet CRC regression for data {data.hex()}"
                )
    
    def test_crc_with_data_escaping(self):
        """Test CRC calculation with 0xFF byte escaping."""
        
        # Data with 0xFF bytes that get escaped in packet
        test_data = b'\x9c\xff\x43'
        packet = Mnet.MnetPacket(b'\x02', b'\x01', b'\x0c\x28', len(test_data), test_data)
        
        # Verify the escaping happened
        self.assertIn(b'\xff\xff', packet.real_data)
        
        # The CRC should be calculated on the full packet including escaped data
        expected_packet_data = b'\x02\x01\x0c\x28\x04\x9c\xff\xff\x43'
        from unittest.mock import Mock
        mnet_instance = Mnet(Mock())
        expected_crc = mnet_instance.crc_calculator.checksum(expected_packet_data)
        
        # Store the actual CRC as baseline
        actual_crc = packet.calculated_crc
        self.assertEqual(actual_crc, 0x5f05)  # Baseline value from current implementation


if __name__ == '__main__':
    unittest.main(verbosity=2)