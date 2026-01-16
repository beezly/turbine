"""
Pytest configuration and shared fixtures for mnet tests.
"""

import os
from pathlib import Path

import pytest
from unittest.mock import Mock
import struct


def load_dotenv():
    """Load environment variables from .env file if it exists."""
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())


# Load .env at module import time
load_dotenv()


def parse_connection(connection: str):
    """Parse connection string into (host, port) tuple.

    Args:
        connection: 'host:port' or 'tcp://host:port'

    Returns:
        Tuple of (host, port)
    """
    if connection.startswith('tcp://'):
        connection = connection[6:]
    host, port = connection.rsplit(':', 1)
    return (host, int(port))


@pytest.fixture
def turbine_connection():
    """Provide turbine connection parameters from environment.

    Returns tuple of (host, port) or None if not configured.
    """
    connection = os.environ.get('TURBINE_CONNECTION')
    if connection:
        return parse_connection(connection)
    return None


@pytest.fixture
def require_turbine(turbine_connection):
    """Skip test if turbine connection is not configured."""
    if turbine_connection is None:
        pytest.skip("TURBINE_CONNECTION not configured in .env")
    return turbine_connection


@pytest.fixture
def mock_serial():
    """Create a mock serial device for testing."""
    mock = Mock()
    mock.read.return_value = b''
    mock.write.return_value = None
    return mock


@pytest.fixture
def sample_packet_data():
    """Provide sample packet data for testing."""
    return {
        'destination': b'\x02',
        'source': b'\x01', 
        'packet_type': b'\x0c\x28',
        'data': b'\x9c\x43',
        'serial_number': 12345678,
        'encoded_serial': bytearray([0x01, 0x02, 0x03, 0x04, 0x05])
    }


@pytest.fixture
def sample_decoded_data():
    """Provide sample decoded data structures for testing."""
    return [
        (0x9c43, 0x0000, (0x4, 15.5)),  # Wind speed
        (0x9c47, 0x0000, (0x4, 1800)),  # Generator RPM
        (0x9c46, 0x0000, (0x4, 25.2))   # Rotor RPM
    ]


@pytest.fixture
def mock_serial_responses():
    """Provide mock serial response data."""
    return {
        'serial_header': struct.pack('!BBBHB', 0x01, 0x01, 0x02, 0x0c2e, 4),
        'serial_data': struct.pack('!L', 12345678),
        'serial_tail': struct.pack('!HB', 0x1234, 0x04),
        'data_header': struct.pack('!BBBHB', 0x01, 0x01, 0x02, 0x0c28, 7),
        'data_payload': b'encoded',
        'data_tail': struct.pack('!HB', 0x5678, 0x04)
    }