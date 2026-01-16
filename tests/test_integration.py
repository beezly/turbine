"""
Integration tests against a real turbine controller.

These tests require a turbine connection configured in .env:
    TURBINE_CONNECTION=turbinepi.local:2217

Tests are skipped if the environment is not configured.

NOTE: All tests are READ-ONLY and will not modify turbine state.
"""

import datetime
import pytest

from mnet import Mnet, NetworkSerial


DESTINATION = b'\x02'


@pytest.fixture
def turbine_session(require_turbine):
    """Create a logged-in turbine session."""
    host, port = require_turbine
    with NetworkSerial(host, port, timeout=10.0) as device:
        mnet = Mnet(device)
        mnet.login(DESTINATION)
        yield mnet


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
            serial, serial_bytes = mnet.get_serial_number(DESTINATION)

            assert serial > 0
            assert len(serial_bytes) == 4
            print(f"\nTurbine serial number: {serial}")

    def test_login(self, require_turbine):
        """Test login to turbine."""
        host, port = require_turbine

        with NetworkSerial(host, port, timeout=10.0) as device:
            mnet = Mnet(device)
            response = mnet.login(DESTINATION)

            assert response is not None
            print(f"\nLogin response: {response}")


@pytest.mark.integration
class TestWindData:
    """Integration tests for wind-related data."""

    def test_read_wind_speed_current(self, turbine_session):
        """Test reading current wind speed."""
        mnet = turbine_session
        wind_speed = mnet.request_data(DESTINATION, Mnet.DATA_ID_WIND_SPEED,
                                       Mnet.DATA_AVERAGING_CURRENT)

        assert wind_speed is not None
        assert isinstance(wind_speed, (int, float))
        assert 0 <= wind_speed <= 100  # Reasonable range for wind speed m/s
        print(f"\nWind speed (current): {wind_speed} m/s")


@pytest.mark.integration
class TestRotationData:
    """Integration tests for rotation speed data."""

    def test_read_rotor_rpm(self, turbine_session):
        """Test reading rotor RPM."""
        mnet = turbine_session
        rotor_rpm = mnet.request_data(DESTINATION, Mnet.DATA_ID_ROTOR_REVS)

        assert rotor_rpm is not None
        assert isinstance(rotor_rpm, (int, float))
        assert rotor_rpm >= 0
        print(f"\nRotor RPM: {rotor_rpm}")

    def test_read_generator_rpm(self, turbine_session):
        """Test reading generator RPM."""
        mnet = turbine_session
        gen_rpm = mnet.request_data(DESTINATION, Mnet.DATA_ID_GEN_REVS)

        assert gen_rpm is not None
        assert isinstance(gen_rpm, (int, float))
        assert gen_rpm >= 0
        print(f"\nGenerator RPM: {gen_rpm}")

    def test_read_rpm_1min_avg(self, turbine_session):
        """Test reading 1-minute average RPM values."""
        mnet = turbine_session

        rotor_rpm = mnet.request_data(DESTINATION, Mnet.DATA_ID_ROTOR_REVS,
                                      Mnet.DATA_AVERAGING_1MIN)
        gen_rpm = mnet.request_data(DESTINATION, Mnet.DATA_ID_GEN_REVS,
                                    Mnet.DATA_AVERAGING_1MIN)

        assert rotor_rpm is not None
        assert gen_rpm is not None
        print(f"\nRotor RPM (1min avg): {rotor_rpm}")
        print(f"Generator RPM (1min avg): {gen_rpm}")


@pytest.mark.integration
class TestVoltageData:
    """Integration tests for voltage readings."""

    def test_read_phase_voltages_current(self, turbine_session):
        """Test reading current phase voltages."""
        mnet = turbine_session

        l1v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L1V,
                                Mnet.DATA_AVERAGING_CURRENT)
        l2v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L2V,
                                Mnet.DATA_AVERAGING_CURRENT)
        l3v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L3V,
                                Mnet.DATA_AVERAGING_CURRENT)

        assert l1v is not None
        assert l2v is not None
        assert l3v is not None
        print(f"\nPhase voltages (current): L1={l1v}V, L2={l2v}V, L3={l3v}V")

    def test_read_phase_voltages_1min_avg(self, turbine_session):
        """Test reading 1-minute average phase voltages."""
        mnet = turbine_session

        l1v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L1V,
                                Mnet.DATA_AVERAGING_1MIN)
        l2v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L2V,
                                Mnet.DATA_AVERAGING_1MIN)
        l3v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L3V,
                                Mnet.DATA_AVERAGING_1MIN)

        assert l1v is not None
        assert l2v is not None
        assert l3v is not None
        print(f"\nPhase voltages (1min avg): L1={l1v}V, L2={l2v}V, L3={l3v}V")

    def test_read_phase_voltages_10min_avg(self, turbine_session):
        """Test reading 10-minute average phase voltages."""
        mnet = turbine_session

        l1v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L1V,
                                Mnet.DATA_AVERAGING_10MIN)
        l2v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L2V,
                                Mnet.DATA_AVERAGING_10MIN)
        l3v = mnet.request_data(DESTINATION, Mnet.DATA_ID_L3V,
                                Mnet.DATA_AVERAGING_10MIN)

        assert l1v is not None
        assert l2v is not None
        assert l3v is not None
        print(f"\nPhase voltages (10min avg): L1={l1v}V, L2={l2v}V, L3={l3v}V")

    def test_read_grid_voltage(self, turbine_session):
        """Test reading grid voltage."""
        mnet = turbine_session
        grid_voltage = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_VOLTAGE)

        assert grid_voltage is not None
        print(f"\nGrid voltage: {grid_voltage}V")


@pytest.mark.integration
class TestCurrentData:
    """Integration tests for current readings."""

    def test_read_phase_currents(self, turbine_session):
        """Test reading phase currents."""
        mnet = turbine_session

        l1a = mnet.request_data(DESTINATION, Mnet.DATA_ID_L1A)
        l2a = mnet.request_data(DESTINATION, Mnet.DATA_ID_L2A)
        l3a = mnet.request_data(DESTINATION, Mnet.DATA_ID_L3A)

        assert l1a is not None
        assert l2a is not None
        assert l3a is not None
        print(f"\nPhase currents: L1={l1a}A, L2={l2a}A, L3={l3a}A")

    def test_read_grid_current(self, turbine_session):
        """Test reading grid current."""
        mnet = turbine_session
        grid_current = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_CURRENT)

        assert grid_current is not None
        print(f"\nGrid current: {grid_current}A")


@pytest.mark.integration
class TestPowerData:
    """Integration tests for power readings."""

    def test_read_grid_power_current(self, turbine_session):
        """Test reading current grid power."""
        mnet = turbine_session
        power = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_POWER,
                                  Mnet.DATA_AVERAGING_CURRENT)

        assert power is not None
        print(f"\nGrid power (current): {power}W")

    def test_read_grid_power_10min_avg(self, turbine_session):
        """Test reading 10-minute average grid power."""
        mnet = turbine_session
        power = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_POWER,
                                  Mnet.DATA_AVERAGING_10MIN)

        assert power is not None
        print(f"\nGrid power (10min avg): {power}W")

    def test_read_grid_var(self, turbine_session):
        """Test reading grid reactive power (VAR)."""
        mnet = turbine_session
        grid_var = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_VAR)

        assert grid_var is not None
        print(f"\nGrid VAR: {grid_var}")


@pytest.mark.integration
class TestProductionData:
    """Integration tests for production counter readings.

    Note: Production counters may not be available on all controller models.
    """

    @pytest.mark.skip(reason="Production counters not available on test controller")
    def test_read_system_production(self, turbine_session):
        """Test reading total system production."""
        mnet = turbine_session
        production = mnet.request_data(DESTINATION, Mnet.DATA_ID_SYSTEM_PRODUCTION)

        assert production is not None
        assert production >= 0
        print(f"\nSystem production: {production} kWh")

    @pytest.mark.skip(reason="Production counters not available on test controller")
    def test_read_g1_production(self, turbine_session):
        """Test reading G1 production counter."""
        mnet = turbine_session
        production = mnet.request_data(DESTINATION, Mnet.DATA_ID_G1_PRODUCTION)

        assert production is not None
        assert production >= 0
        print(f"\nG1 production: {production} kWh")


@pytest.mark.integration
class TestStatusData:
    """Integration tests for status code readings."""

    def test_read_current_status_code(self, turbine_session):
        """Test reading current status code."""
        mnet = turbine_session
        status = mnet.request_data(DESTINATION, Mnet.DATA_ID_CURRENT_STATUS_CODE, 0)

        assert status is not None
        print(f"\nCurrent status code [0]: {status}")

    def test_read_current_status_code_text(self, turbine_session):
        """Test reading current status code text."""
        mnet = turbine_session
        status_text = mnet.request_data(DESTINATION, Mnet.DATA_ID_CURRENT_STATUS_CODE, 1)

        assert status_text is not None
        print(f"\nCurrent status text: {status_text}")

    def test_read_event_stack(self, turbine_session):
        """Test reading event stack status codes."""
        mnet = turbine_session

        # Read last 3 events from the stack
        event_0 = mnet.request_data(DESTINATION, Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 0)
        event_1 = mnet.request_data(DESTINATION, Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 1)
        event_2 = mnet.request_data(DESTINATION, Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 2)

        assert event_0 is not None
        print(f"\nEvent stack [0]: {event_0}")
        print(f"Event stack [1]: {event_1}")
        print(f"Event stack [2]: {event_2}")


@pytest.mark.integration
class TestTimeData:
    """Integration tests for time reading (READ-ONLY)."""

    def test_get_controller_time(self, turbine_session):
        """Test reading controller time."""
        mnet = turbine_session
        controller_time = mnet.get_controller_time(DESTINATION)

        assert controller_time is not None
        assert isinstance(controller_time, datetime.datetime)
        assert controller_time.tzinfo is not None  # Should be timezone-aware
        print(f"\nController time: {controller_time}")

    def test_controller_time_is_reasonable(self, turbine_session):
        """Test that controller time is within reasonable bounds."""
        mnet = turbine_session
        controller_time = mnet.get_controller_time(DESTINATION)

        # Time should be after 2020 and not too far in the future
        min_time = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
        max_time = datetime.datetime(2100, 1, 1, tzinfo=datetime.timezone.utc)

        assert controller_time > min_time, "Controller time is before 2020"
        assert controller_time < max_time, "Controller time is after 2100"


@pytest.mark.integration
class TestBatchDataRequests:
    """Integration tests for batch data requests."""

    def test_read_multiple_basic_data(self, turbine_session):
        """Test reading multiple basic data points in one request."""
        mnet = turbine_session

        data_points = [
            (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_ROTOR_REVS, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_GEN_REVS, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_CURRENT),
        ]

        results = mnet.request_multiple_data(DESTINATION, data_points)

        assert len(results) == 4
        assert all(r is not None for r in results)
        print(f"\nBatch data: wind={results[0]} m/s, rotor={results[1]} rpm, "
              f"gen={results[2]} rpm, power={results[3]} W")

    def test_read_multiple_voltages(self, turbine_session):
        """Test reading all phase voltages in one request."""
        mnet = turbine_session

        data_points = [
            (Mnet.DATA_ID_L1V, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L2V, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L3V, Mnet.DATA_AVERAGING_CURRENT),
        ]

        results = mnet.request_multiple_data(DESTINATION, data_points)

        assert len(results) == 3
        print(f"\nBatch voltages: L1={results[0]}V, L2={results[1]}V, L3={results[2]}V")

    def test_read_multiple_currents(self, turbine_session):
        """Test reading all phase currents in one request."""
        mnet = turbine_session

        data_points = [
            (Mnet.DATA_ID_L1A, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L2A, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L3A, Mnet.DATA_AVERAGING_CURRENT),
        ]

        results = mnet.request_multiple_data(DESTINATION, data_points)

        assert len(results) == 3
        print(f"\nBatch currents: L1={results[0]}A, L2={results[1]}A, L3={results[2]}A")

    def test_read_mixed_averaging_periods(self, turbine_session):
        """Test reading data with different averaging periods."""
        mnet = turbine_session

        data_points = [
            (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_1MIN),
            (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_10MIN),
            (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_1MIN),
            (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_10MIN),
        ]

        results = mnet.request_multiple_data(DESTINATION, data_points)

        assert len(results) == 6
        print(f"\nWind speed: current={results[0]}, 1min={results[1]}, 10min={results[2]}")
        print(f"Grid power: current={results[3]}, 1min={results[4]}, 10min={results[5]}")

    def test_read_full_turbine_snapshot(self, turbine_session):
        """Test reading a comprehensive turbine data snapshot."""
        mnet = turbine_session

        data_points = [
            # Wind
            (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_CURRENT),
            # Rotation
            (Mnet.DATA_ID_ROTOR_REVS, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_GEN_REVS, Mnet.DATA_AVERAGING_CURRENT),
            # Power
            (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_CURRENT),
            # Voltages
            (Mnet.DATA_ID_L1V, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L2V, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L3V, Mnet.DATA_AVERAGING_CURRENT),
            # Currents
            (Mnet.DATA_ID_L1A, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L2A, Mnet.DATA_AVERAGING_CURRENT),
            (Mnet.DATA_ID_L3A, Mnet.DATA_AVERAGING_CURRENT),
        ]

        results = mnet.request_multiple_data(DESTINATION, data_points)

        assert len(results) == 10
        print(f"\n--- Full Turbine Snapshot ---")
        print(f"Wind speed: {results[0]} m/s")
        print(f"Rotor RPM: {results[1]}")
        print(f"Generator RPM: {results[2]}")
        print(f"Grid power: {results[3]} W")
        print(f"Voltages: L1={results[4]}V, L2={results[5]}V, L3={results[6]}V")
        print(f"Currents: L1={results[7]}A, L2={results[8]}A, L3={results[9]}A")


@pytest.mark.integration
class TestDataAveragingPeriods:
    """Integration tests for different data averaging periods.

    Note: Available averaging periods vary by data type and controller model.
    Voltage supports: current, 1min, 10min
    Grid power supports: current, 10min
    Wind speed supports: current only
    """

    @pytest.mark.parametrize("averaging,name", [
        (Mnet.DATA_AVERAGING_CURRENT, "current"),
        (Mnet.DATA_AVERAGING_1MIN, "1min"),
        (Mnet.DATA_AVERAGING_10MIN, "10min"),
    ])
    def test_voltage_averaging_periods(self, turbine_session, averaging, name):
        """Test reading voltage with different averaging periods."""
        mnet = turbine_session
        voltage = mnet.request_data(DESTINATION, Mnet.DATA_ID_L1V, averaging)

        assert voltage is not None
        print(f"\nL1 Voltage ({name}): {voltage} V")

    @pytest.mark.parametrize("averaging,name", [
        (Mnet.DATA_AVERAGING_CURRENT, "current"),
        (Mnet.DATA_AVERAGING_10MIN, "10min"),
    ])
    def test_grid_power_averaging_periods(self, turbine_session, averaging, name):
        """Test reading grid power with different averaging periods."""
        mnet = turbine_session
        power = mnet.request_data(DESTINATION, Mnet.DATA_ID_GRID_POWER, averaging)

        assert power is not None
        print(f"\nGrid power ({name}): {power} W")
