"""
Integration tests against a real turbine controller.

These tests require a turbine connection configured in .env:
    TURBINE_HOST=turbinepi.local
    TURBINE_PORT=2217

Tests are skipped if the environment is not configured.
"""

import datetime
import pytest

from mnet import Mnet, NetworkSerial


@pytest.mark.integration
class TestTurbineConnection:
    """Integration tests for turbine connectivity."""

    def test_connect_to_turbine(self, require_turbine):
        """Test basic TCP connection to turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            assert device.is_connected

    def test_get_serial_number(self, require_turbine):
        """Test retrieving turbine serial number."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            serial, serial_bytes = mnet.get_serial_number(b'\x02')

            assert serial > 0
            assert len(serial_bytes) == 4
            print(f"\nTurbine serial number: {serial}")

    def test_login(self, require_turbine):
        """Test login to turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            response = mnet.login(b'\x02')

            assert response is not None
            print(f"\nLogin response: {response}")


@pytest.mark.integration
class TestTurbineData:
    """Integration tests for reading turbine data."""

    def test_read_wind_speed(self, require_turbine):
        """Test reading wind speed from turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            wind_speed = mnet.request_data(b'\x02', Mnet.DATA_ID_WIND_SPEED)

            assert wind_speed is not None
            assert isinstance(wind_speed, (int, float))
            print(f"\nWind speed: {wind_speed} m/s")

    def test_read_generator_rpm(self, require_turbine):
        """Test reading generator RPM from turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            gen_rpm = mnet.request_data(b'\x02', Mnet.DATA_ID_GEN_REVS)

            assert gen_rpm is not None
            print(f"\nGenerator RPM: {gen_rpm}")

    def test_read_rotor_rpm(self, require_turbine):
        """Test reading rotor RPM from turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            rotor_rpm = mnet.request_data(b'\x02', Mnet.DATA_ID_ROTOR_REVS)

            assert rotor_rpm is not None
            print(f"\nRotor RPM: {rotor_rpm}")

    def test_read_grid_power(self, require_turbine):
        """Test reading grid power from turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            power = mnet.request_data(b'\x02', Mnet.DATA_ID_GRID_POWER)

            assert power is not None
            print(f"\nGrid power: {power} kW")

    def test_read_status_code(self, require_turbine):
        """Test reading current status code from turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            status = mnet.request_data(b'\x02', Mnet.DATA_ID_CURRENT_STATUS_CODE)

            assert status is not None
            print(f"\nStatus code: {status}")

    def test_read_multiple_data(self, require_turbine):
        """Test reading multiple data points in one request."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            data_points = [
                (Mnet.DATA_ID_WIND_SPEED, 0),
                (Mnet.DATA_ID_GEN_REVS, 0),
                (Mnet.DATA_ID_ROTOR_REVS, 0),
                (Mnet.DATA_ID_GRID_POWER, 0),
            ]

            results = mnet.request_multiple_data(b'\x02', data_points)

            assert len(results) == 4
            print(f"\nMultiple data: wind={results[0]}, gen_rpm={results[1]}, "
                  f"rotor_rpm={results[2]}, power={results[3]}")


@pytest.mark.integration
class TestTurbineTime:
    """Integration tests for turbine time operations."""

    def test_get_controller_time(self, require_turbine):
        """Test reading controller time."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            controller_time = mnet.get_controller_time(b'\x02')

            assert controller_time is not None
            assert isinstance(controller_time, datetime.datetime)
            print(f"\nController time: {controller_time}")

    def test_set_controller_time(self, require_turbine):
        """Test setting controller time to current UTC."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            mnet.login(b'\x02')

            # Get time before
            time_before = mnet.get_controller_time(b'\x02', adjust=False)
            print(f"\nController time before: {time_before}")

            # Set to current time
            response = mnet.set_controller_time(b'\x02')
            assert response is not None

            # Get time after
            time_after = mnet.get_controller_time(b'\x02', adjust=False)
            print(f"Controller time after: {time_after}")

            # Verify time is close to current UTC
            now = datetime.datetime.now(datetime.timezone.utc)
            diff = abs((time_after - now).total_seconds())
            print(f"Difference from UTC: {diff} seconds")

            # Allow up to 5 seconds difference for network latency
            assert diff < 5, f"Time difference too large: {diff} seconds"
