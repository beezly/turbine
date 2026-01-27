#!/usr/bin/env python3
"""
Wind Turbine Monitor

Monitors wind turbine data via Mnet protocol and publishes to MQTT.
"""

import json
import logging
import time
import threading
import traceback
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional

import paho.mqtt.client as mqtt
import serial
from flask import Flask, render_template
from flask_socketio import SocketIO, emit

import mnet


class TurbineMonitor:
    """Wind turbine monitoring and MQTT publishing."""

    TOPIC_PREFIX = 'turbine/'
    DESTINATION = b'\x02'
    POLL_INTERVAL = 1.0
    ERROR_RETRY_DELAY = 10.0
    INTER_REQUEST_DELAY = 0.1  # Delay between serial requests
    TIME_SYNC_INTERVAL = 14400  # Sync controller time every 4 hours (in seconds)

    def __init__(self, connection: str, mqtt_host: str, web_port: int = 5000):
        """Initialize turbine monitor.

        Args:
            connection: Serial port path (e.g., '/dev/ttyUSB0') or
                       network address (e.g., 'host:port' or 'tcp://host:port')
            mqtt_host: MQTT broker hostname
            web_port: Web interface port (default 5000)
        """
        self.connection = connection
        self.mqtt_host = mqtt_host
        self.web_port = web_port
        self.pending_command: Optional[bytes] = None
        self.last_time_sync: Optional[datetime] = None
        self.logger = self._setup_logging()

        # Monitoring data
        self.latest_data = {}
        self.mqtt_log = deque(maxlen=100)
        self.serial_log = deque(maxlen=100)
        self.debug_log = deque(maxlen=100)
        self.status = {'connected': False, 'last_update': None}
        self.serial_lock = threading.Lock()  # Prevent concurrent serial access

        # Web server
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        self._setup_web_routes()

        # Initialize connections
        self.serial_device = self._create_device(connection)
        self.mnet_client = mnet.Mnet(self.serial_device)
        self.mnet_client._log_callback = self._log_serial_hex
        self.mnet_client._debug_callback = self._log_debug_response
        self.mqtt_client = self._setup_mqtt()

        # Get turbine serial number
        self.serial_number, serial_bytes = self.mnet_client.get_serial_number(self.DESTINATION)
        self.encoded_serial = self.mnet_client.encode_serial(serial_bytes)
        self.logger.info(f"Connected to turbine serial: {self.serial_number}")

        # Setup MQTT command subscription
        self._setup_command_subscription()

    def _create_device(self, connection: str):
        """Create serial or network device based on connection string.

        Args:
            connection: '/dev/ttyUSB0' for serial, 'host:port' or 'tcp://host:port' for network

        Returns:
            Serial device or NetworkSerial instance
        """
        # Check for network connection formats
        if connection.startswith('tcp://'):
            # tcp://host:port format
            addr = connection[6:]  # Remove 'tcp://'
            host, port = addr.rsplit(':', 1)
            self.logger.info(f"Using network connection: {host}:{port}")
            device = mnet.NetworkSerial(host, int(port), timeout=5.0)
            device.connect()
            return device
        elif ':' in connection and not connection.startswith('/'):
            # host:port format (no path-like prefix)
            host, port = connection.rsplit(':', 1)
            self.logger.info(f"Using network connection: {host}:{port}")
            device = mnet.NetworkSerial(host, int(port), timeout=5.0)
            device.connect()
            return device
        else:
            # Assume serial port path
            self.logger.info(f"Using serial port: {connection}")
            return serial.Serial(port=connection, baudrate=38400, timeout=2)

    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration."""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def _setup_web_routes(self):
        """Setup Flask routes."""
        @self.app.route('/')
        def index():
            return render_template('index.html')
        
        @self.socketio.on('connect')
        def handle_connect():
            emit('status', self.status)
            emit('data', self.latest_data)
        
        @self.socketio.on('toggle_debug')
        def handle_toggle_debug(enabled):
            # Debug toggle handled on client side
            pass
        
        @self.socketio.on('command')
        def handle_command(command):
            self._handle_socket_command(command)

        @self.socketio.on('get_events')
        def handle_get_events(data):
            """Fetch events from the event stack."""
            limit = data.get('limit', 10) if data else 10
            events = self._fetch_events(limit)
            emit('events', events)

        @self.socketio.on('get_alarms')
        def handle_get_alarms(data):
            """Fetch alarm history."""
            only_occurred = data.get('only_occurred', True) if data else True
            alarms = self._fetch_alarm_history(only_occurred)
            emit('alarms', alarms)
    
    def _log_mqtt(self, direction: str, topic: str, payload: str):
        """Log MQTT activity."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'direction': direction,
            'topic': topic,
            'payload': payload
        }
        self.mqtt_log.append(entry)
        self.socketio.emit('mqtt_log', entry)
    
    def _log_serial(self, direction: str, data: str):
        """Log serial activity."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'direction': direction,
            'data': data
        }
        self.serial_log.append(entry)
        self.socketio.emit('serial_log', entry)
    
    def _log_serial_hex(self, direction: str, hex_data: str, decoded: str):
        """Log serial activity with hex and decoded data."""
        # Abbreviate hex data to max 32 characters
        abbreviated_hex = hex_data[:32] + ('...' if len(hex_data) > 32 else '')
        
        # Abbreviate decoded data
        abbreviated_decoded = decoded[:16] + ('...' if len(decoded) > 16 else '')
        
        entry = {
            'timestamp': datetime.now().isoformat(),
            'direction': direction,
            'data': f'HEX: {abbreviated_hex} | {abbreviated_decoded}'
        }
        self.serial_log.append(entry)
        self.socketio.emit('serial_log', entry)
    
    def _log_debug_response(self, debug_data):
        """Log debug response data."""
        # Convert any datetime objects to strings for JSON serialization
        serializable_data = {}
        for key, value in debug_data.items():
            if isinstance(value, datetime):
                serializable_data[key] = value.isoformat()
            else:
                serializable_data[key] = value
        
        entry = {
            'timestamp': datetime.now().isoformat(),
            **serializable_data
        }
        self.debug_log.append(entry)
        self.socketio.emit('debug_response', entry)
        
        # Log to console
        req_id = serializable_data.get('request_data_id', 'unknown')
        req_sub = serializable_data.get('request_sub_id', 'unknown')
        resp_main = serializable_data.get('response_mainid', 'unknown')
        resp_sub = serializable_data.get('response_subid', 'unknown')
        value = serializable_data.get('value', 'unknown')
        data_type = serializable_data.get('data_type', 'unknown')
        self.logger.debug(f"REQ[{req_id}:{req_sub}] -> RSP[{resp_main}:{resp_sub}] = {value} (type:{data_type})")
    
    def _setup_mqtt(self) -> mqtt.Client:
        """Setup MQTT client."""
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='turbine_mqtt', userdata=self)
        client.on_message = self._handle_command_message
        client.connect(self.mqtt_host)
        client.loop_start()
        return client
    
    def _setup_command_subscription(self):
        """Setup MQTT command topic subscription."""
        command_topic = f"{self.TOPIC_PREFIX}{self.serial_number}/command"
        self.mqtt_client.subscribe(command_topic)
        self.logger.info(f"Subscribed to command topic: {command_topic}")
    
    def _handle_command_message(self, client, userdata, message):
        """Handle incoming MQTT command messages."""
        try:
            command = message.payload.decode('utf-8').strip().lower()
            self._log_mqtt('RX', message.topic, command)
            self.logger.info(f"Received command: {command}")
            
            command_map = {
                'start': mnet.Mnet.DATA_ID_START,
                'stop': mnet.Mnet.DATA_ID_STOP,
                'reset': mnet.Mnet.DATA_ID_RESET,
                'manual_start': mnet.Mnet.DATA_ID_MANUAL_START
            }
            
            if command in command_map:
                self.pending_command = command_map[command]
                self.logger.info(f"Queued command: {command}")
            else:
                self.logger.warning(f"Unknown command: {command}")
                
        except Exception as e:
            self.logger.error(f"Error handling command: {e}")
            self.logger.error(traceback.format_exc())
    
    def _handle_socket_command(self, command: str):
        """Handle incoming socket command from web UI."""
        try:
            command = command.strip().lower()
            self.logger.info(f"Received socket command: {command}")
            
            command_map = {
                'start': mnet.Mnet.DATA_ID_START,
                'stop': mnet.Mnet.DATA_ID_STOP,
                'reset': mnet.Mnet.DATA_ID_RESET,
                'manual_start': mnet.Mnet.DATA_ID_MANUAL_START
            }
            
            if command in command_map:
                self.pending_command = command_map[command]
                self.logger.info(f"Queued socket command: {command}")
            else:
                self.logger.warning(f"Unknown socket command: {command}")
                
        except Exception as e:
            self.logger.error(f"Error handling socket command: {e}")
            self.logger.error(traceback.format_exc())

    def _fetch_events(self, limit: int = 10) -> list:
        """Fetch events from the event stack using batch request.

        Args:
            limit: Maximum number of events to fetch

        Returns:
            List of event dictionaries
        """
        events = []
        with self.serial_lock:
            try:
                self._clear_serial_buffers()
                # Use batch method for efficiency (single request instead of 3*limit)
                for event in self.mnet_client.get_events_batch(self.DESTINATION, limit=limit):
                    events.append({
                        'index': event.index,
                        'code': event.code,
                        'timestamp': event.timestamp.isoformat() if event.timestamp else None,
                        'text': event.text
                    })
            except Exception as e:
                self.logger.error(f"Error fetching events: {e}")
                self.logger.error(traceback.format_exc())
        return events

    def _fetch_alarm_history(self, only_occurred: bool = True) -> list:
        """Fetch alarm history using batch request.

        Args:
            only_occurred: Only return alarms that have occurred

        Returns:
            List of alarm record dictionaries
        """
        alarms = []
        with self.serial_lock:
            try:
                self._clear_serial_buffers()
                # Use batch method for efficiency (single request instead of 2*num_alarms)
                for alarm in self.mnet_client.get_alarm_history_batch(self.DESTINATION, only_occurred=only_occurred):
                    alarms.append({
                        'sub_id': alarm.sub_id,
                        'last_occurred': alarm.last_occurred.isoformat() if alarm.last_occurred else None,
                        'description': alarm.description,
                        'has_occurred': alarm.has_occurred
                    })
            except Exception as e:
                self.logger.error(f"Error fetching alarm history: {e}")
                self.logger.error(traceback.format_exc())
        return alarms

    def _clear_serial_buffers(self):
        """Clear serial input/output buffers to prevent timing issues."""
        # Only applies to real serial devices, not network connections
        if hasattr(self.serial_device, 'reset_input_buffer'):
            try:
                self.serial_device.reset_input_buffer()
                self.serial_device.reset_output_buffer()
            except Exception as e:
                self.logger.warning(f"Buffer clear failed: {e}")
    
    def _login_to_turbine(self):
        """Perform login to turbine."""
        with self.serial_lock:
            self._clear_serial_buffers()
            self._log_serial('TX', 'LOGIN')
            self.mnet_client.login(self.DESTINATION)
            time.sleep(self.INTER_REQUEST_DELAY)
    
    def _execute_pending_command(self):
        """Execute any pending command."""
        if self.pending_command:
            with self.serial_lock:
                try:
                    self._clear_serial_buffers()
                    self.logger.info(f"Executing command: {self.pending_command}")
                    result = self.mnet_client.send_command(self.DESTINATION, self.pending_command)
                    self.logger.info(f"Command result: {result}")
                    time.sleep(self.INTER_REQUEST_DELAY)
                except Exception as e:
                    self.logger.error(f"Command execution failed: {e}")
                    self.logger.error(traceback.format_exc())
                finally:
                    self.pending_command = None

    def _sync_controller_time(self):
        """Sync controller time to current UTC if interval has elapsed."""
        now = datetime.now()
        if (self.last_time_sync is None or
            (now - self.last_time_sync).total_seconds() >= self.TIME_SYNC_INTERVAL):
            with self.serial_lock:
                try:
                    self._clear_serial_buffers()
                    self.logger.info("Syncing controller time to UTC")
                    self.mnet_client.set_controller_time(self.DESTINATION)
                    self.last_time_sync = now
                    self.logger.info("Controller time synced successfully")
                except Exception as e:
                    self.logger.error(f"Failed to sync controller time: {e}")
                    self.logger.error(traceback.format_exc())

    def _collect_turbine_data(self) -> Dict[str, Any]:
        """Collect all turbine data using single multiple request."""
        # Get remote display screen
        with self.serial_lock:
            try:
                remote_display = self.mnet_client.get_remote_display(self.DESTINATION)
                # Convert to ASCII, format as 18-char lines (matches controller LCD)
                display_text = ''.join(chr(b) if 32 <= b < 127 else ' ' for b in remote_display)
                display_lines = [display_text[i:i+18] for i in range(0, len(display_text), 18)]
            except Exception as e:
                self.logger.warning(f"Failed to get remote display: {e}")
                display_lines = []

        # Combined request for all data (max ~17 items to stay within response limits)
        all_requests = [
            (mnet.Mnet.DATA_ID_WIND_SPEED, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_ROTOR_REVS, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_GEN_REVS, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_GRID_POWER, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L1V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L2V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L3V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, mnet.Mnet.EVENT_STACK_SUBID_TEXT),  # Latest event text
            (mnet.Mnet.DATA_ID_CONTROLLER_TIME, 0),
            (mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 0),
            (mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 1),
            (mnet.Mnet.DATA_ID_GRID_POWER, mnet.Mnet.DATA_AVERAGING_10MIN),
            (mnet.Mnet.DATA_ID_L1V, mnet.Mnet.DATA_AVERAGING_1MIN),
            (mnet.Mnet.DATA_ID_L2V, mnet.Mnet.DATA_AVERAGING_1MIN),
            (mnet.Mnet.DATA_ID_L3V, mnet.Mnet.DATA_AVERAGING_1MIN),
            (mnet.Mnet.DATA_ID_RUNTIME_1, 0),  # Runtime counter 1
            (mnet.Mnet.DATA_ID_RUNTIME_2, 0),  # Runtime counter 2
        ]

        with self.serial_lock:
            results = self.mnet_client.request_multiple_data(self.DESTINATION, all_requests)

        # Latest event text for quick display
        event_text = results[7].strip() if isinstance(results[7], str) else str(results[7]).strip()

        data = {
            'wind_speed_mps': results[0],
            'rotor_rpm': results[1],
            'generator_rpm': results[2],
            'power_W': results[3],
            'l1v': results[4],
            'l2v': results[5],
            'l3v': results[6],
            'status_message': event_text,
            'event_stack_0': event_text,
            'controller_time': datetime.strptime(results[8], "%y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S UTC") if results[8] else None,
            'current_status_code_0': results[9],
            'current_status_code_1': results[10],
            # 10-minute and 1-minute averages
            'power_W_10min': results[11],
            'l1v_1min': results[12],
            'l2v_1min': results[13],
            'l3v_1min': results[14],
            # Runtime counters (in seconds)
            'runtime_1_sec': results[15] if len(results) > 15 else None,
            'runtime_2_sec': results[16] if len(results) > 16 else None,
            # Remote display (40x4 LCD)
            'remote_display': display_lines,
        }

        return data
    
    def _publish_data(self, data: Dict[str, Any]):
        """Publish data to MQTT."""
        # Convert datetime objects to strings for JSON serialization
        serializable_data = {}
        for key, value in data.items():
            if isinstance(value, datetime):
                serializable_data[key] = value.isoformat()
            else:
                serializable_data[key] = value
        
        topic = f"{self.TOPIC_PREFIX}{self.serial_number}"
        payload = json.dumps(serializable_data)
        
        result = self.mqtt_client.publish(topic, payload)
        result.wait_for_publish()
        
        self._log_mqtt('TX', topic, payload)
        self.latest_data = serializable_data
        self.status['last_update'] = datetime.now().isoformat()
        self.status['connected'] = True
        
        self.socketio.emit('data', serializable_data)
        self.socketio.emit('status', self.status)
    
    def run(self):
        """Main monitoring loop."""
        self.logger.info("Starting turbine monitor")
        
        # Start web server in separate thread
        web_thread = threading.Thread(
            target=lambda: self.socketio.run(self.app, host='0.0.0.0', port=self.web_port, debug=False, allow_unsafe_werkzeug=True)
        )
        web_thread.daemon = True
        web_thread.start()
        self.logger.info(f"Web interface started on port {self.web_port}")
        
        # Login to turbine
        self._login_to_turbine()

        while True:
            try:
                # Execute any pending commands
                self._execute_pending_command()

                # Sync controller time periodically
                self._sync_controller_time()

                # Collect and publish data
                turbine_data = self._collect_turbine_data()
                self._publish_data(turbine_data)
                
                time.sleep(self.POLL_INTERVAL)
                
            except (BrokenPipeError, ConnectionError, OSError) as e:
                self.logger.error(f"Connection error: {e}")
                self.status['connected'] = False
                self.socketio.emit('status', self.status)
                time.sleep(self.ERROR_RETRY_DELAY)

                # Attempt reconnection
                try:
                    self._reconnect_device()
                except Exception as reconnect_error:
                    self.logger.error(f"Reconnection failed: {reconnect_error}")
                    self.logger.error(traceback.format_exc())

            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
                self.logger.error(traceback.format_exc())
                self.status['connected'] = False
                self.socketio.emit('status', self.status)
                time.sleep(self.ERROR_RETRY_DELAY)
    
    def _reconnect_device(self):
        """Reconnect to the serial/network device after connection loss."""
        self.logger.info("Attempting to reconnect to turbine...")

        # Reconnect if NetworkSerial, otherwise recreate the device
        if hasattr(self.serial_device, 'reconnect'):
            self.serial_device.reconnect()
        else:
            # For serial devices, close and recreate
            try:
                self.serial_device.close()
            except Exception:
                pass
            self.serial_device = self._create_device(self.connection)
            self.mnet_client.device = self.serial_device

        # Reset mnet_client state so serial number is re-fetched
        self.mnet_client.serial = None
        self.mnet_client.encoded_serial = None
        self.mnet_client._alarm_description_cache.clear()

        # Re-fetch serial number and re-login
        self.serial_number, serial_bytes = self.mnet_client.get_serial_number(self.DESTINATION)
        self.encoded_serial = self.mnet_client.encode_serial(serial_bytes)
        self.logger.info(f"Reconnected to turbine serial: {self.serial_number}")

        self._login_to_turbine()
        self.logger.info("Reconnection successful")

    def close(self):
        """Clean shutdown."""
        self.logger.info("Shutting down turbine monitor")
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.serial_device.close()


def main():
    """Main entry point."""
    import os

    # Load .env file if it exists
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

    # Get configuration from environment
    connection = os.environ.get('TURBINE_CONNECTION', '/dev/ttyUSB0')
    mqtt_host = os.environ.get('MQTT_HOST', 'mqtt.lan')
    web_port = int(os.environ.get('WEB_PORT', '5000'))
    time_sync_interval = int(os.environ.get('TIME_SYNC_INTERVAL', '14400'))  # 4 hours default

    print(f"Turbine connection: {connection}")
    print(f"MQTT host: {mqtt_host}")
    print(f"Web port: {web_port}")
    print(f"Time sync interval: {time_sync_interval}s ({time_sync_interval/3600:.1f}h)")

    monitor = TurbineMonitor(connection, mqtt_host, web_port)
    monitor.TIME_SYNC_INTERVAL = time_sync_interval

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        monitor.close()


if __name__ == '__main__':
    main()