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
        """Collect all turbine data with timing delays."""
        data = {}
        
        # Core measurements with delays between requests
        self._log_serial('TX', f'REQ: WIND_SPEED')
        data['wind_speed_mps'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_WIND_SPEED)
        self._log_serial('RX', f'WIND_SPEED: {data["wind_speed_mps"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        self._log_serial('TX', f'REQ: ROTOR_RPM')
        data['rotor_rpm'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_ROTOR_REVS)
        self._log_serial('RX', f'ROTOR_RPM: {data["rotor_rpm"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        self._log_serial('TX', f'REQ: GEN_RPM')
        data['generator_rpm'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_GEN_REVS)
        self._log_serial('RX', f'GEN_RPM: {data["generator_rpm"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        self._log_serial('TX', f'REQ: POWER')
        data['power_W'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_GRID_POWER)
        self._log_serial('RX', f'POWER: {data["power_W"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        # Voltage measurements
        self._log_serial('TX', f'REQ: L1V')
        data['l1v'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_L1V)
        self._log_serial('RX', f'L1V: {data["l1v"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        self._log_serial('TX', f'REQ: L2V')
        data['l2v'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_L2V)
        self._log_serial('RX', f'L2V: {data["l2v"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        self._log_serial('TX', f'REQ: L3V')
        data['l3v'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_L3V)
        self._log_serial('RX', f'L3V: {data["l3v"]}')
        time.sleep(self.INTER_REQUEST_DELAY)
        
        # Status message
        self._log_serial('TX', f'REQ: STATUS')
        data['status_message'] = self.mnet_client.request_data(
            self.DESTINATION, mnet.Mnet.DATA_ID_EVENT_STACK_STATUS_CODE, 2).strip()
        self._log_serial('RX', f'STATUS: {data["status_message"]}')
        
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