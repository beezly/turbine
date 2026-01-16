# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository implements a **wind turbine monitoring system** that communicates with Mita-Teknik WP3000/IC1000 wind turbine controllers via the proprietary **M-net protocol** over serial or network connections. It collects real-time turbine data, publishes to MQTT, and provides a web interface for monitoring.

## Core Modules

### mnet.py (Protocol Implementation)

**Data Classes:**
- `Event` - Named tuple for event stack entries (index, code, timestamp, text)
- `AlarmRecord` - Named tuple for alarm history entries (sub_id, last_occurred, description, has_occurred)

**NetworkSerial class:**
- TCP socket wrapper providing serial-like interface for ser2net connections
- Enables remote serial access over network
- Context manager support for automatic connection handling

**MnetPacket class:**
- Encapsulates individual M-net protocol packets with:
  - Source/destination addressing (1 byte each)
  - Packet type identification (2 bytes)
  - CRC-16 XMODEM checksums for data integrity
  - 0xFF byte escaping for protocol reliability
  - SOH (0x01) and EOT (0x04) frame delimiters

**Mnet class (Main protocol client):**
- Serial/network device management and packet I/O
- Request/reply packet handling with response parsing
- Support for multiple data types (scaling, division, power conversions)
- Serial-based XOR encryption/decryption
- Login authentication with encrypted credentials

**Key data types supported:**
- Wind speed, rotor/generator RPM, grid power, voltage, current
- Status codes (current and event stack)
- Controller time (epoch: 1980-01-01 UTC)
- Runtime counters
- Remote display (LCD screen content)
- Multiple averaging levels (current, 20ms, 100ms, 1s, 30s, 1min, 10min, 30min, 1hr, 24hr)

**Key methods:**
- `request_data(destination, data_id)` / `request_multiple_data(destination, data_ids)` - Fetch turbine values
- `send_command(destination, command)` - Start/stop/reset turbine
- `encode(data, key)` / `decode(data, key)` - Serial-based encryption/decryption
- `encode_serial(serial_bytes)` - Convert serial number to encryption key
- `login(destination)` - Authenticate with controller
- `get_controller_time(destination)` / `set_controller_time(destination)` - Time synchronization
- `get_remote_display(destination)` / `get_remote_display_text(destination)` - LCD screen mirroring
- `get_event(destination, index)` / `get_events_batch(destination, limit)` - Event stack access
- `get_alarm_record(destination, sub_id)` / `get_alarm_history_batch(destination)` - Alarm history

### turbine_monitor.py (Main Application)

**TurbineMonitor class:**
- Orchestrates monitoring with:
  - Serial or network connection management (38400 baud for serial)
  - MQTT client publishing to `turbine/{serial_number}` topics
  - Flask web server with SocketIO for real-time updates
  - Background polling thread (1-second intervals)
  - Command queue from MQTT subscriptions and web UI
  - Periodic controller time synchronization (4-hour interval)

**Features:**
- Batch data collection: 17 data points in single request (efficiency optimization)
- JSON publishing to MQTT
- Activity logging: serial traffic (hex), MQTT events, debug responses
- Command support: start, stop, reset, manual_start
- Remote display (LCD) mirroring on web dashboard
- Event stack and alarm history viewing
- Runtime counter display
- Serial buffer clearing for timing reliability
- Error recovery with 10-second retry delay

**Data collected:**
- Wind speed, rotor/generator RPM, grid power
- Voltage (3-phase current + 1-minute averages)
- Status codes (current and event stack)
- Controller time
- Runtime counters
- Remote display content

**Connection types:**
- Serial: `/dev/ttyUSB0` (direct USB-serial adapter)
- Network: `host:port` or `tcp://host:port` (via ser2net)

## Architecture Patterns

| Pattern | Implementation | Purpose |
|---------|-----------------|---------|
| **Dependency Injection** | Serial/network device passed to Mnet constructor | Enables clean testing without framework patching |
| **Callback Logging** | `_log_callback`, `_debug_callback` attributes | Event logging and debugging |
| **Async Publishing** | Background MQTT thread with `.loop_start()` | Non-blocking MQTT communication |
| **Mock Device Pattern** | Tests use direct mock objects | Direct dependency injection for testing |
| **Protocol State Machine** | Login → Serial retrieval → Data requests → Commands | Ensures proper device handshake |
| **CRC Regression Tests** | `tests/test_crc_*.py` prevent calculation drift | Critical: prevents silent protocol breaks |
| **Batch Requests** | Single 17-item query vs 17 individual requests | Reduces latency and improves responsiveness |
| **Chunked Batching** | Event/alarm fetches split into controller-safe chunks | Handles controller batch limits |
| **Periodic Time Sync** | Controller time synchronized every 4 hours | Handles controller clock drift |
| **Real-time Updates** | SocketIO broadcasts to all connected clients | Web UI synchronization |
| **Description Caching** | Alarm descriptions cached after first fetch | Reduces redundant protocol requests |

## Testing Architecture

**Test Organization** (`tests/` directory):
- **test_mnet.py** - 4 test classes covering packet operations, encoding/decoding, data requests, and error handling
- **test_crc_baseline.py** - Ensures CRC-16 XMODEM calculations never change unintentionally
- **test_crc_regression.py** - Comprehensive regression testing for protocol stability
- **test_login.py** - Authentication and login flow testing
- **conftest.py** - Shared pytest fixtures

**Key testing patterns:**
- Direct mock device injection (no `@patch` decorators on class level)
- Realistic packet structures in test data
- 100+ test entries covering normal and edge cases
- Coverage reporting via pytest-cov

**Test configuration** (`pytest.ini`):
- Test discovery in `tests/test_*.py`
- Markers available: `unit`, `integration`, `slow`
- Verbose output with short tracebacks

## Common Development Commands

```bash
# Run tests
make test                    # Quick test run
make test-coverage          # Generate HTML coverage report (htmlcov/)
make test-verbose           # Verbose output

# Test specific components
make test-packet            # TestMnetPacket class only
make test-main              # TestMnet class only
make test-integration       # Integration tests only

# Cleanup
make clean                  # Remove test artifacts and coverage

# Dependencies
make install-test-deps      # Install test requirements

# Protocol verification
python verify_crc.py        # Run CRC baseline comparison (blocks unsafe changes)
```

## Single Test Execution

Run individual tests using pytest directly:

```bash
# Run specific test method
python -m pytest tests/test_mnet.py::TestMnet::test_encode_decode_data -v

# Run specific test class
python -m pytest tests/test_mnet.py::TestMnet -v

# Run test with coverage
python -m pytest tests/test_mnet.py --cov=mnet --cov-report=html -v
```

## Important Implementation Details

### Serial-based Encryption

The Mnet protocol uses XOR encryption where the key is derived from the device's serial number:
- Serial number obtained via `get_serial_number()` request
- `encode_serial(serial_bytes)` creates encryption key
- All sensitive data (login credentials) encrypted with this key
- See `mnet.py:encode()` and `decode()` methods for implementation

### CRC-16 XMODEM Checksums

- Used for all packet integrity verification
- Implementation in `mnet.py:calculate_crc()`
- **Critical:** Regression tests in `tests/test_crc_*.py` prevent accidental changes
- Run `python verify_crc.py` before modifying CRC logic

### Packet Structure

```
[SOH (0x01)][Destination][Source][Type (2B)][Len][Data][CRC (2B)][EOT (0x04)]
```
- Data escaping: 0xFF bytes in data become `0xFF 0xFF`
- Max packet size: 300 bytes
- See `MnetPacket` class in mnet.py for implementation details

### Time Handling

- Controller epoch: 1980-01-01 (not Unix epoch)
- `timestamp_to_datetime()` handles conversion with UTC timezone
- `set_controller_time()` synchronizes controller clock to system time
- Periodic sync every 4 hours in TurbineMonitor

### Event Stack

- Stores last 100 turbine events (index 0 = most recent)
- Each event has: code, timestamp, and description text
- `get_events_batch()` uses chunked requests (4 events per chunk) to stay within controller limits

### Alarm History

- Records last occurrence time for each alarm type
- `ALARM_SUB_IDS` dictionary maps sub_ids to alarm descriptions
- Sentinel date (2032-05-09) indicates alarm has never occurred
- Description caching reduces redundant requests after first fetch

### Remote Display (LCD)

- Mirrors the controller's physical LCD display
- 138-byte buffer formatted as 18-character lines
- `get_remote_display_text()` returns cleaned text lines
- Web dashboard displays in status panel

## Documentation

See `docs/MNET.md` (73KB) for comprehensive protocol specification including:
- Connection management procedures
- Packet types and structures
- Configuration parameters
- Data encoding formats

See `docs/PROTOCOL_ANALYSIS.md` for protocol reverse engineering notes.

See `docs/HARDWARE_PROTECTION.md` for licensing system details.

See `docs/SET_TIME_COMMAND.md` for time synchronization protocol.

See `TEST_README.md` for detailed testing guide and patterns.

## Dependencies

**Runtime** (`requirements.txt`):
- `pySerial` - Serial communication
- `crc>=7.1.0` - CRC-16 XMODEM calculations
- `bitstring` - Bit manipulation utilities
- `flask` - Web server framework
- `flask-socketio` - WebSocket support for real-time updates
- `paho-mqtt` - MQTT client library

**Testing** (`requirements-test.txt`):
- `pytest>=7.0.0` - Test framework
- `pytest-cov>=4.0.0` - Coverage reporting
- `pytest-mock>=3.10.0` - Mocking utilities
- `coverage>=7.0.0` - Coverage analysis

**Python version:** 3.13+ (see `.python-version`)

## Important Notes for Future Work

1. **Protocol Changes**: Always run `python verify_crc.py` before committing CRC logic modifications. The regression tests exist to prevent silent protocol breaks.

2. **New Data IDs**: When adding new turbine data types, follow existing patterns in `mnet.py` - add constant definition, data ID to batch requests, and corresponding tests.

3. **Test Structure**: Maintain the mock device injection pattern (don't use `@patch` decorators on class level). This pattern enables clean, deterministic testing without framework dependencies.

4. **MQTT Publishing**: Data is published as JSON to `turbine/{serial_number}`. Keep topic structure consistent.

5. **Time Synchronization**: The periodic time sync mechanism in `turbine_monitor.py` runs every 4 hours. Avoid disabling this as controller clocks can drift.

6. **Batch Efficiency**: The 17-item batch request in `turbine_monitor.py` is optimized for minimal latency. Avoid changing this pattern without performance testing.

7. **Event Stack Batch Limits**: The controller has a lower batch limit for event stack requests (~12 items). The chunked approach in `get_events_batch()` handles this.

8. **Network Connections**: When using ser2net, ensure the baud rate is configured to 38400 on the server side.
