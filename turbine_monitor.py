#!/usr/bin/env python3
"""
Wind Turbine Monitor

Monitors wind turbine data via Mnet protocol and publishes to MQTT.
"""

import json
import logging
import time
import threading
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
        self.logger = self._setup_logging()
        
        # Monitoring data
        self.latest_data = {}
        self.mqtt_log = deque(maxlen=100)
        self.serial_log = deque(maxlen=100)
        self.status = {'connected': False, 'last_update': None}
        
        # Web server
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        self._setup_web_routes()
        
        # Initialize connections
        self.serial_device = serial.Serial(port=serial_port, baudrate=38400, timeout=2)
        self.mnet_client = mnet.Mnet(self.serial_device)
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
                'reset': mnet.Mnet.DATA_ID_RESET
            }
            
            if command in command_map:
                self.pending_command = command_map[command]
                self.logger.info(f"Queued command: {command}")
            else:
                self.logger.warning(f"Unknown command: {command}")
                
        except Exception as e:
            self.logger.error(f"Error handling command: {e}")
    
    def _clear_serial_buffers(self):
        """Clear serial input/output buffers to prevent timing issues."""
        try:
            self.serial_device.reset_input_buffer()
            self.serial_device.reset_output_buffer()
        except Exception as e:
            self.logger.warning(f"Buffer clear failed: {e}")
    
    def _login_to_turbine(self):
        """Perform login to turbine."""
        self._clear_serial_buffers()
        login_data = self.mnet_client.encode(
            self.mnet_client.create_login_packet_data(), 
            self.encoded_serial
        )
        self._log_serial('TX', f'LOGIN: {login_data.hex()}')
        self.mnet_client.send_packet(self.DESTINATION, b'\x13\xa1', login_data)
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
            finally:
                self.pending_command = None
    
    def _collect_turbine_data(self) -> Dict[str, Any]:
        """Collect all turbine data using single multiple request."""
        # All data requests in one call
        data_requests = [
            (mnet.Mnet.DATA_ID_WIND_SPEED, 0),
            (mnet.Mnet.DATA_ID_ROTOR_REVS, 0),
            (mnet.Mnet.DATA_ID_GEN_REVS, 0),
            (mnet.Mnet.DATA_ID_GRID_POWER, 0),
            (mnet.Mnet.DATA_ID_L1V, 0),
            (mnet.Mnet.DATA_ID_L2V, 0),
            (mnet.Mnet.DATA_ID_L3V, 0),
            (mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 2)
        ]
        
        self._log_serial('TX', 'REQ: ALL_DATA (multiple)')
        results = self.mnet_client.request_multiple_data(self.DESTINATION, data_requests)
        
        data = {
            'wind_speed_mps': results[0],
            'rotor_rpm': results[1],
            'generator_rpm': results[2],
            'power_W': results[3],
            'l1v': results[4],
            'l2v': results[5],
            'l3v': results[6],
            'status_message': results[7].strip() if isinstance(results[7], str) else str(results[7]).strip()
        }
        
        self._log_serial('RX', f'ALL_DATA: Wind={data["wind_speed_mps"]:.1f}, Power={data["power_W"]:.0f}, RPM={data["rotor_rpm"]:.0f}/{data["generator_rpm"]:.0f}, V={data["l1v"]:.0f}/{data["l2v"]:.0f}/{data["l3v"]:.0f}')
        
        return data
    
    def _publish_data(self, data: Dict[str, Any]):
        """Publish data to MQTT."""
        topic = f"{self.TOPIC_PREFIX}{self.serial_number}"
        payload = json.dumps(data)
        
        result = self.mqtt_client.publish(topic, payload)
        result.wait_for_publish()
        
        self._log_mqtt('TX', topic, payload)
        self.latest_data = data
        self.status['last_update'] = datetime.now().isoformat()
        self.status['connected'] = True
        
        self.socketio.emit('data', data)
        self.socketio.emit('status', self.status)
        
        self.logger.info(f"Published data: {data}")
    
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
        
        while True:
            try:
                # Login to turbine
                self._login_to_turbine()
                
                # Execute any pending commands
                self._execute_pending_command()
                
                # Collect and publish data
                turbine_data = self._collect_turbine_data()
                self._publish_data(turbine_data)
                
                time.sleep(self.POLL_INTERVAL)
                
            except Exception as e:
                self.logger.error(f"Monitor loop error: {e}")
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