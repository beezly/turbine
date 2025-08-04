#!/usr/bin/env python3
"""
Demo Web Monitor

Simulates turbine data for web interface testing without real hardware.
"""

import json
import logging
import time
import threading
import random
from collections import deque
from datetime import datetime
from typing import Dict, Any

from flask import Flask, render_template
from flask_socketio import SocketIO, emit


class DemoTurbineMonitor:
    """Demo turbine monitor for testing web interface."""
    
    def __init__(self, web_port: int = 5000):
        self.web_port = web_port
        self.logger = self._setup_logging()
        
        # Monitoring data
        self.latest_data = {}
        self.mqtt_log = deque(maxlen=100)
        self.serial_log = deque(maxlen=100)
        self.status = {'connected': True, 'last_update': None}
        
        # Web server
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app, cors_allowed_origins="*")
        self._setup_web_routes()
    
    def _setup_logging(self) -> logging.Logger:
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
    
    def _generate_demo_data(self) -> Dict[str, Any]:
        """Generate realistic demo turbine data."""
        return {
            'wind_speed_mps': random.uniform(3.0, 15.0),
            'rotor_rpm': random.uniform(10.0, 30.0),
            'generator_rpm': random.uniform(800.0, 1800.0),
            'power_W': random.uniform(500.0, 5000.0),
            'l1v': random.uniform(220.0, 240.0),
            'l2v': random.uniform(220.0, 240.0),
            'l3v': random.uniform(220.0, 240.0),
            'status_message': random.choice([
                'Normal Operation',
                'High Wind Speed',
                'Low Wind Speed',
                'Maintenance Mode',
                'Grid Connected'
            ])
        }
    
    def _simulate_data_collection(self):
        """Simulate data collection with logging."""
        # Simulate serial requests
        requests = ['WIND_SPEED', 'ROTOR_RPM', 'GEN_RPM', 'POWER', 'L1V', 'L2V', 'L3V', 'STATUS']
        
        for req in requests:
            self._log_serial('TX', f'REQ: {req}')
            time.sleep(0.1)
            
            # Generate response value
            if req == 'WIND_SPEED':
                value = random.uniform(3.0, 15.0)
            elif req == 'POWER':
                value = random.uniform(500.0, 5000.0)
            elif 'RPM' in req:
                value = random.uniform(800.0, 1800.0)
            elif 'V' in req:
                value = random.uniform(220.0, 240.0)
            else:
                value = 'Normal Operation'
            
            self._log_serial('RX', f'{req}: {value}')
    
    def run(self):
        """Main demo loop."""
        self.logger.info("Starting demo turbine monitor")
        
        # Start web server in separate thread
        web_thread = threading.Thread(
            target=lambda: self.socketio.run(self.app, host='0.0.0.0', port=self.web_port, debug=False)
        )
        web_thread.daemon = True
        web_thread.start()
        self.logger.info(f"Demo web interface started on http://localhost:{self.web_port}")
        
        while True:
            try:
                # Simulate login
                self._log_serial('TX', 'LOGIN: 0x13a1...')
                time.sleep(0.1)
                
                # Simulate data collection
                self._simulate_data_collection()
                
                # Generate demo data
                demo_data = self._generate_demo_data()
                
                # Simulate MQTT publish
                topic = f"turbine/12345"
                payload = json.dumps(demo_data)
                self._log_mqtt('TX', topic, payload)
                
                # Update status and emit data
                self.latest_data = demo_data
                self.status['last_update'] = datetime.now().isoformat()
                self.status['connected'] = True
                
                self.socketio.emit('data', demo_data)
                self.socketio.emit('status', self.status)
                
                self.logger.info(f"Demo data: Wind={demo_data['wind_speed_mps']:.1f}m/s, Power={demo_data['power_W']:.0f}W")
                
                time.sleep(2)  # Update every 2 seconds for demo
                
            except Exception as e:
                self.logger.error(f"Demo error: {e}")
                time.sleep(5)


def main():
    """Main entry point."""
    print("🌪️  Demo Turbine Monitor")
    print("=" * 50)
    print("This demo simulates turbine data for web interface testing.")
    print("Open http://localhost:5000 in your browser to view the interface.")
    print("Press Ctrl+C to stop.")
    print("=" * 50)
    
    monitor = DemoTurbineMonitor(5000)
    
    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nDemo stopped.")


if __name__ == '__main__':
    main()