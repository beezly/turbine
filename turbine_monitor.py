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
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import paho.mqtt.client as mqtt
import serial
from flask import Flask, render_template, request, jsonify
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

    # Control commands (require the standard/control login; see _execute_pending_command)
    COMMAND_MAP = {
        'start': mnet.Mnet.DATA_ID_START,
        'stop': mnet.Mnet.DATA_ID_STOP,
        'reset': mnet.Mnet.DATA_ID_RESET,
        'manual_start': mnet.Mnet.DATA_ID_MANUAL_START,
        'ack': mnet.Mnet.DATA_ID_ACK_ALARM,
    }

    def __init__(self, connection: str, mqtt_host: str, web_port: int = 5000,
                 control_password: Optional[str] = None):
        """Initialize turbine monitor.

        Args:
            connection: Serial port path (e.g., '/dev/ttyUSB0') or
                       network address (e.g., 'host:port' or 'tcp://host:port')
            mqtt_host: MQTT broker hostname
            web_port: Web interface port (default 5000)
            control_password: per-turbine Turbine Password. When set, control
                commands elevate to a standard (0x138E) login for the command and
                then drop back to the hidden read-only login. When None, control
                commands are refused (monitor stays read-only).
        """
        self.connection = connection
        self.mqtt_host = mqtt_host
        self.web_port = web_port
        self.control_password = control_password
        self.pending_command: Optional[bytes] = None
        self.pending_command_name: Optional[str] = None
        self.last_command_result: Optional[dict] = None
        self.command_lock = threading.Lock()  # serialize /api/command callers
        # Login state broadcast to the UI: mode in hidden|elevating|control|command|reverting
        self.login_state = {'mode': 'hidden', 'detail': 'monitoring (read-only)',
                            'control_available': bool(control_password), 'ts': None}
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

        @self.app.route('/api/read')
        def api_read():
            """Read-only data-probe: query an arbitrary data ID / read-type packet
            through the live connection (no service restart needed).

            Params:
              id=<hex>    data ID (e.g. 9c43). Required for data reads.
              sub=<int>   sub id (default 0)
              type=<hex>  packet type, default 0c28 (REQ_DATA). Whitelisted read
                          types only: 0c28 data, 0c2a multi, 0c04 menu, 0c05 screen,
                          0c2e serial. Command/login/write types are refused.
            """
            READ_TYPES = {'0c28', '0c2a', '0c04', '0c05', '0c2e'}
            try:
                ptype_hex = request.args.get('type', '0c28').lower().replace('0x', '')
                sub = int(request.args.get('sub', '0'), 0)
                id_hex = request.args.get('id', '').lower().replace('0x', '')
            except Exception as e:
                return jsonify({'error': f'bad params: {e}'}), 400
            if ptype_hex not in READ_TYPES:
                return jsonify({'error': f'type {ptype_hex} not allowed (read-only endpoint)'}), 403
            ptype = bytes.fromhex(ptype_hex)
            needs_id = ptype_hex in ('0c28', '0c2a')
            try:
                did = bytes.fromhex(id_hex.zfill(4)) if id_hex else b''
            except Exception as e:
                return jsonify({'error': f'bad id: {e}'}), 400
            if needs_id and len(did) != 2:
                return jsonify({'error': 'id must be a 2-byte hex data ID (e.g. 9c43)'}), 400
            payload = (did + sub.to_bytes(2, 'big')) if needs_id else b''
            with self.serial_lock:
                try:
                    self._clear_serial_buffers()
                    resp = self.mnet_client.send_packet(self.DESTINATION, ptype, payload)
                    dec = self.mnet_client.decode(resp.data, self.mnet_client.encoded_serial)
                    out = {
                        'request': {'type': ptype_hex, 'id': id_hex, 'sub': sub},
                        'reply_type': resp.packet_type.hex(),
                        'raw': dec.hex(' '),
                        'len': len(dec),
                        'ascii': ''.join(chr(x) if 32 <= x < 127 else '.' for x in dec),
                    }
                    if needs_id:
                        try:
                            _, val = self.mnet_client.decode_data(dec, data_id=int.from_bytes(did, 'big'))
                            out['value'] = val
                        except Exception as e:
                            out['value_error'] = str(e)
                    time.sleep(self.INTER_REQUEST_DELAY)
                    return jsonify(out)
                except Exception as e:
                    return jsonify({'error': str(e)}), 500

        @self.app.route('/api/scan')
        def api_scan():
            """Read-only sweep of a data-ID range via REQ_DATA, returning only IDs
            that reply with non-empty data. Params: start=<hex> end=<hex> sub=<int>.
            Range capped at 512 IDs per call."""
            try:
                start = int(request.args.get('start', ''), 16)
                end = int(request.args.get('end', ''), 16)
                sub = int(request.args.get('sub', '0'), 0)
            except Exception as e:
                return jsonify({'error': f'bad params (need hex start/end): {e}'}), 400
            if not (0 <= start <= end <= 0xffff) or (end - start) > 512:
                return jsonify({'error': 'invalid range (max 512 ids, start<=end)'}), 400
            hits = []
            with self.serial_lock:
                for wid in range(start, end + 1):
                    try:
                        self._clear_serial_buffers()
                        payload = wid.to_bytes(2, 'big') + sub.to_bytes(2, 'big')
                        resp = self.mnet_client.send_packet(self.DESTINATION, b'\x0c\x28', payload)
                        dec = self.mnet_client.decode(resp.data, self.mnet_client.encoded_serial)
                        # empty / "no such point" replies are all-zero 5-byte headers
                        if any(dec[1:]) or (len(dec) > 5 and any(dec[5:])):
                            hits.append({'id': '%04x' % wid, 'raw': dec.hex(' ')})
                    except Exception:
                        pass
            return jsonify({'start': '%04x' % start, 'end': '%04x' % end, 'sub': sub,
                            'hit_count': len(hits), 'hits': hits})

        @self.app.route('/api/multiscan')
        def api_multiscan():
            """Fast read-only sweep using REQ_MULTIPLE_DATA (0x0c2a) batches.
            Params: start=<hex> end=<hex> sub=<int> batch=<int, default 32>.
            Returns IDs that came back with a value. Range capped at 8192/call.
            On a batch error, falls back to single reads so no ID is missed."""
            try:
                start = int(request.args.get('start', ''), 16)
                end = int(request.args.get('end', ''), 16)
                sub = int(request.args.get('sub', '0'), 0)
                batch = max(1, min(int(request.args.get('batch', '32')), 60))
            except Exception as e:
                return jsonify({'error': f'bad params: {e}'}), 400
            if not (0 <= start <= end <= 0xffff) or (end - start) > 8192:
                return jsonify({'error': 'invalid range (max 8192 ids)'}), 400
            hits, fell_back = [], 0
            with self.serial_lock:
                wid = start
                while wid <= end:
                    ids = list(range(wid, min(wid + batch, end + 1)))
                    try:
                        self._clear_serial_buffers()
                        pairs = [(w.to_bytes(2, 'big'), sub) for w in ids]
                        res = self.mnet_client.request_multiple_data(
                            self.DESTINATION, pairs, include_ids=True)
                        for mid, sid, val in res:
                            if val is not None and val != '':
                                hits.append({'id': mid.hex(), 'sub': sid, 'value': val})
                    except Exception:
                        fell_back += 1
                        # A bad multi-data reply (e.g. a string-type register) desyncs the
                        # ser2net stream; the network buffer-clear is a no-op, so reconnect
                        # to resync, then warm up before the single-read fallback.
                        try:
                            if hasattr(self.serial_device, 'reconnect'):
                                self.serial_device.reconnect()
                                time.sleep(0.3)
                                try:
                                    self.mnet_client.send_packet(self.DESTINATION, b'\x0c\x2e', b'')
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        for w in ids:
                            try:
                                payload = w.to_bytes(2, 'big') + sub.to_bytes(2, 'big')
                                resp = self.mnet_client.send_packet(self.DESTINATION, b'\x0c\x28', payload)
                                dec = self.mnet_client.decode(resp.data, self.mnet_client.encoded_serial)
                                if any(dec[1:]):
                                    hits.append({'id': '%04x' % w, 'raw': dec.hex(' ')})
                            except Exception:
                                pass
                    wid += batch
            return jsonify({'start': '%04x' % start, 'end': '%04x' % end, 'sub': sub,
                            'batch': batch, 'batches_fell_back': fell_back,
                            'hit_count': len(hits), 'hits': hits})

        @self.app.route('/api/command/<name>', methods=['POST'])
        def api_command(name):
            """Issue a control command through the monitor (elevate -> command ->
            revert to hidden). Password-gated. Synchronous: waits for execution and
            returns the result. Supply the control password via the
            'X-Control-Password' header or a JSON body {"password": "..."}."""
            name = (name or '').strip().lower()
            if not self.control_password:
                return jsonify({'error': 'control disabled (no TURBINE_CONTROL_PASSWORD set)'}), 403
            supplied = request.headers.get('X-Control-Password')
            if supplied is None and request.is_json:
                supplied = (request.get_json(silent=True) or {}).get('password')
            if supplied != self.control_password:
                return jsonify({'error': 'unauthorized (bad or missing control password)'}), 401
            if name not in self.COMMAND_MAP:
                return jsonify({'error': 'unknown command: %s' % name,
                                'valid': sorted(self.COMMAND_MAP)}), 400
            with self.command_lock:
                self.last_command_result = None
                self.pending_command_name = name
                self.pending_command = self.COMMAND_MAP[name]
                deadline = time.time() + 20
                while self.pending_command is not None and time.time() < deadline:
                    time.sleep(0.1)
                if self.pending_command is not None:
                    return jsonify({'command': name, 'ok': False,
                                    'error': 'timeout waiting for execution'}), 504
                return jsonify(self.last_command_result or {'command': name, 'ok': True})

        @self.socketio.on('connect')
        def handle_connect():
            emit('status', self.status)
            emit('data', self.latest_data)
            emit('login_state', self.login_state)
        
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
            
            if command in self.COMMAND_MAP:
                self.pending_command = self.COMMAND_MAP[command]
                self.pending_command_name = command
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

            if command in self.COMMAND_MAP:
                self.pending_command = self.COMMAND_MAP[command]
                self.pending_command_name = command
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
    
    def _set_login_state(self, mode: str, detail: str = ''):
        """Update and broadcast the current login/control state to the UI."""
        self.login_state = {
            'mode': mode,
            'detail': detail,
            'control_available': bool(self.control_password),
            'ts': datetime.now(timezone.utc).isoformat(),
        }
        self.socketio.emit('login_state', self.login_state)

    def _login_to_turbine(self):
        """Perform the hidden (read-only) login used for monitoring."""
        with self.serial_lock:
            self._clear_serial_buffers()
            self._log_serial('TX', 'LOGIN')
            self.mnet_client.login(self.DESTINATION)
            time.sleep(self.INTER_REQUEST_DELAY)
        self._set_login_state('hidden', 'monitoring (read-only)')

    def _execute_pending_command(self):
        """Execute a pending control command by briefly elevating to a standard
        (control) login for the command, then dropping back to the hidden login."""
        if not self.pending_command:
            return
        cmd = self.pending_command
        name = self.pending_command_name or 'command'
        self.pending_command = None
        self.pending_command_name = None

        if not self.control_password:
            self.logger.warning("Control command '%s' refused: no control password configured", name)
            self.socketio.emit('command_result',
                               {'command': name, 'ok': False, 'error': 'Control disabled (no password set)'})
            self._set_login_state('hidden', 'control disabled (no password set)')
            return

        with self.serial_lock:
            try:
                self._clear_serial_buffers()
                # 1. elevate to the standard (control) login
                self._set_login_state('elevating', 'standard login (control)')
                self.mnet_client.login_standard(self.DESTINATION, self.control_password)
                time.sleep(self.INTER_REQUEST_DELAY)
                self._set_login_state('control', 'control login active')
                # 2. issue the command
                self._set_login_state('command', f'sending {name.upper()}')
                self.logger.info("Executing control command: %s", name)
                result = self.mnet_client.send_command(self.DESTINATION, cmd)
                reply = result.packet_type.hex()
                self.logger.info("Command '%s' reply: %s", name, reply)
                time.sleep(self.INTER_REQUEST_DELAY)
                self.last_command_result = {'command': name, 'ok': True, 'reply': reply}
                self.socketio.emit('command_result', self.last_command_result)
            except Exception as e:
                self.logger.error("Command '%s' failed: %s", name, e)
                self.logger.error(traceback.format_exc())
                self.last_command_result = {'command': name, 'ok': False, 'error': str(e)}
                self.socketio.emit('command_result', self.last_command_result)
            finally:
                # 3. always drop back to the hidden read-only login
                try:
                    self._set_login_state('reverting', 'returning to hidden login')
                    self._clear_serial_buffers()
                    self.mnet_client.login(self.DESTINATION)
                    time.sleep(self.INTER_REQUEST_DELAY)
                except Exception as e:
                    self.logger.error("Failed to revert to hidden login: %s", e)
                self._set_login_state('hidden', 'monitoring (read-only)')

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
    control_password = os.environ.get('TURBINE_CONTROL_PASSWORD') or None

    print(f"Turbine connection: {connection}")
    print(f"MQTT host: {mqtt_host}")
    print(f"Web port: {web_port}")
    print(f"Time sync interval: {time_sync_interval}s ({time_sync_interval/3600:.1f}h)")
    print(f"Control: {'ENABLED (password set)' if control_password else 'disabled (read-only; set TURBINE_CONTROL_PASSWORD to enable)'}")

    monitor = TurbineMonitor(connection, mqtt_host, web_port, control_password=control_password)
    monitor.TIME_SYNC_INTERVAL = time_sync_interval

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        monitor.close()


if __name__ == '__main__':
    main()