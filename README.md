# Wind Turbine Monitor

A Python implementation of the Mita-Teknik M-net protocol for monitoring WP3000/IC1000/IC1100 wind turbine controllers.

## Features

- **Real-time Monitoring**: Wind speed, rotor/generator RPM, grid power, voltage (3-phase)
- **Web Dashboard**: Modern responsive interface with live updates via WebSocket
- **MQTT Publishing**: Publish turbine data to any MQTT broker for integration with home automation, logging systems, etc.
- **Remote Display**: Mirror the controller's physical LCD display
- **Event History**: View the last 100 turbine events with timestamps
- **Alarm History**: Track when each alarm type last occurred
- **Turbine Control**: Start, stop, reset, and manual start commands
- **Network Support**: Connect via serial port or remotely via ser2net

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd turbine

# Install dependencies
pip install -r requirements.txt
```

## Configuration

Create a `.env` file in the project root:

```bash
# Serial connection (direct)
TURBINE_CONNECTION=/dev/ttyUSB0

# Or network connection (via ser2net)
TURBINE_CONNECTION=192.168.1.100:3001
# Or with tcp:// prefix
TURBINE_CONNECTION=tcp://192.168.1.100:3001

# MQTT broker
MQTT_HOST=localhost

# Web interface port (optional, default 5000)
WEB_PORT=5000
```

## Usage

### Running the Monitor

```bash
python turbine_monitor.py
```

The web interface will be available at `http://localhost:5000`.

### Using as a Library

```python
import serial
from mnet import Mnet

# Connect via serial
device = serial.Serial('/dev/ttyUSB0', baudrate=38400, timeout=2)
client = Mnet(device)

# Or connect via network (ser2net)
from mnet import NetworkSerial
device = NetworkSerial('192.168.1.100', 3001)
device.connect()
client = Mnet(device)

# Get turbine serial number
serial_num, serial_bytes = client.get_serial_number(b'\x02')
print(f"Turbine serial: {serial_num}")

# Login for authenticated operations
client.login(b'\x02')

# Request wind speed
wind = client.request_data(b'\x02', Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_CURRENT)
print(f"Wind speed: {wind} m/s")

# Request multiple values at once (more efficient)
requests = [
    (Mnet.DATA_ID_WIND_SPEED, Mnet.DATA_AVERAGING_CURRENT),
    (Mnet.DATA_ID_ROTOR_REVS, Mnet.DATA_AVERAGING_CURRENT),
    (Mnet.DATA_ID_GRID_POWER, Mnet.DATA_AVERAGING_CURRENT),
]
results = client.request_multiple_data(b'\x02', requests)

# Get event history
events = client.get_events_batch(b'\x02', limit=10)
for event in events:
    print(f"{event.timestamp}: [{event.code}] {event.text}")

# Get alarm history
alarms = client.get_alarm_history_batch(b'\x02', only_occurred=True)
for alarm in alarms:
    print(f"[{alarm.sub_id}] {alarm.description}: {alarm.last_occurred}")

# Get LCD display content
lines = client.get_remote_display_text(b'\x02')
for line in lines:
    print(line)
```

## Web Dashboard

The web interface provides:

- **Live Data Panel**: Wind speed, RPM, power, and voltage readings
- **Status Display**: Current turbine status and latest event
- **LCD Display**: Real-time mirror of the controller's physical display
- **Control Buttons**: Start, stop, reset, manual start
- **Event History**: Expandable panel showing recent events
- **Alarm History**: View alarm types and when they last occurred
- **Activity Logs**: Serial traffic and MQTT message logs

## MQTT Integration

Data is published as JSON to the topic `turbine/{serial_number}`:

```json
{
  "wind_speed_mps": 7.2,
  "rotor_rpm": 18.5,
  "generator_rpm": 1512,
  "power_W": 245000,
  "l1v": 398.2,
  "l2v": 399.1,
  "l3v": 397.8,
  "status_message": "Generator running",
  "controller_time": "2024-01-15 14:30:45 UTC",
  "current_status_code_0": 651,
  "current_status_code_1": 0
}
```

Commands can be sent to `turbine/{serial_number}/command`:
- `start` - Start turbine
- `stop` - Stop turbine
- `reset` - Reset turbine
- `manual_start` - Manual start

## Network Setup (ser2net)

To access a turbine remotely, use ser2net on a device connected to the serial port:

```bash
# /etc/ser2net.conf
3001:raw:0:/dev/ttyUSB0:38400 NONE 1STOPBIT 8DATABITS
```

Then connect using `tcp://hostname:3001` or `hostname:3001`.

## Protocol Documentation

Comprehensive protocol documentation is available in the `docs/` directory:

- `docs/MNET.md` - Full protocol specification
- `docs/PROTOCOL_ANALYSIS.md` - Reverse engineering notes
- `docs/HARDWARE_PROTECTION.md` - Licensing system details
- `docs/SET_TIME_COMMAND.md` - Time synchronization protocol

## Development

### Running Tests

```bash
# Run all tests
make test

# Run with coverage report
make test-coverage

# Run specific test file
python -m pytest tests/test_mnet.py -v
```

### Project Structure

```
turbine/
├── mnet.py              # Protocol implementation
├── turbine_monitor.py   # Main monitoring application
├── templates/
│   └── index.html       # Web dashboard
├── docs/
│   ├── MNET.md          # Protocol specification
│   └── ...
├── tests/
│   ├── test_mnet.py     # Protocol tests
│   ├── test_crc_*.py    # CRC regression tests
│   └── ...
├── requirements.txt     # Runtime dependencies
└── requirements-test.txt # Test dependencies
```

## Disclaimer

This is an unofficial implementation based on reverse-engineered protocol analysis. Use at your own risk. The authors are not responsible for any damage to your turbine or controller.

## License

See LICENSE file for details.
