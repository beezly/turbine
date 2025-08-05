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
    
    def __init__(self, serial_port: str, mqtt_host: str, web_port: int = 5000):
        self.serial_port = serial_port
        self.mqtt_host = mqtt_host
        self.web_port = web_port
        self.pending_command: Optional[bytes] = None
        self.last_time_offset_update: Optional[datetime] = None
        self.logger = self._setup_logging()
        
        # Monitoring data
        self.latest_data = {}
        self.mqtt_log = deque(maxlen=100)
        self.serial_log = deque(maxlen=100)
        self.debug_log = deque(maxlen=100)
        self.status = {'connected': False, 'last_update': None}
        
        # Web server
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        self._setup_web_routes()
        
        # Initialize connections
        self.serial_device = serial.Serial(port=serial_port, baudrate=38400, timeout=2)
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
        self.logger.info(f"DEBUG: REQ[{req_id}:{req_sub}] -> RSP[{resp_main}:{resp_sub}] = {value} (type:{data_type})")
    
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
    
    def _clear_serial_buffers(self):
        """Clear serial input/output buffers to prevent timing issues."""
        try:
            self.serial_device.reset_input_buffer()
            self.serial_device.reset_output_buffer()
        except Exception as e:
            self.logger.warning(f"Buffer clear failed: {e}")
            self.logger.warning(traceback.format_exc())
    
    def _login_to_turbine(self):
        """Perform login to turbine."""
        self._clear_serial_buffers()
        self._log_serial('TX', 'LOGIN')
        self.mnet_client.login(self.DESTINATION)
        time.sleep(self.INTER_REQUEST_DELAY)
    
    def _execute_pending_command(self):
        """Execute any pending command."""
        if self.pending_command:
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
    
    def _collect_turbine_data(self) -> Dict[str, Any]:
        """Collect all turbine data using single multiple request."""
        # Update time offset once per 24 hours
        now = datetime.now()
        if (self.last_time_offset_update is None or 
            (now - self.last_time_offset_update).total_seconds() >= 86400):
            self.mnet_client.update_time_offset(self.DESTINATION)
            self.last_time_offset_update = now
            self.logger.info("Updated time offset")
        
        # Combined request for all data
        all_requests = [
            (mnet.Mnet.DATA_ID_WIND_SPEED, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_ROTOR_REVS, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_GEN_REVS, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_GRID_POWER, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L1V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L2V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_L3V, mnet.Mnet.DATA_AVERAGING_CURRENT),
            (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 2),
            (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 1),
            (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 0),
            (mnet.Mnet.DATA_ID_CONTROLLER_TIME, 0),
            (mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 0),
            (mnet.Mnet.DATA_ID_CURRENT_STATUS_CODE, 1),
            (mnet.Mnet.DATA_ID_GRID_POWER, mnet.Mnet.DATA_AVERAGING_10MIN),
            (mnet.Mnet.DATA_ID_L1V, mnet.Mnet.DATA_AVERAGING_1MIN),
            (mnet.Mnet.DATA_ID_L2V, mnet.Mnet.DATA_AVERAGING_1MIN),
            (mnet.Mnet.DATA_ID_L3V, mnet.Mnet.DATA_AVERAGING_1MIN)
        ]
        
        results = self.mnet_client.request_multiple_data(self.DESTINATION, all_requests)
        
        data = {
            'wind_speed_mps': results[0],
            'rotor_rpm': results[1],
            'generator_rpm': results[2],
            'power_W': results[3],
            'l1v': results[4],
            'l2v': results[5],
            'l3v': results[6],
            'status_message': results[7].strip() if isinstance(results[7], str) else str(results[7]).strip(),
            'event_stack_2': results[7],
            'event_stack_1': results[8],
            'event_stack_0': results[9],
            'controller_time': results[10],
            'time_offset': str(self.mnet_client.time_offset) if self.mnet_client.time_offset else 'None',
            'current_status_code_0': results[11],
            'current_status_code_1': results[12],
            # 1-minute averages
            'power_W_10min': results[13],
            'l1v_1min': results[14],
            'l2v_1min': results[15],
            'l3v_1min': results[16]
        }
        
        # Safe formatting for None values
        def safe_format(val, fmt):
            return f'{val:{fmt}}' if val is not None else 'None'
        

        
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
            target=lambda: self.socketio.run(self.app, host='0.0.0.0', port=self.web_port, debug=False)
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
                
                # Collect and publish data
                turbine_data = self._collect_turbine_data()
                self._publish_data(turbine_data)
                
                time.sleep(self.POLL_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
                self.logger.error(traceback.format_exc())
                self.status['connected'] = False
                self.socketio.emit('status', self.status)
                time.sleep(self.ERROR_RETRY_DELAY)
    
    def close(self):
        """Clean shutdown."""
        self.logger.info("Shutting down turbine monitor")
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.serial_device.close()


def main():
    """Main entry point."""
    monitor = TurbineMonitor('/dev/ttyUSB0', 'mqtt.lan', 5000)
    
    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        monitor.close()


if __name__ == '__main__':
    main()