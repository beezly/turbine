#!/usr/bin/env python3
"""Offline preview of the dashboard templates with fixture telemetry.

Serves templates/index.html (and templates/index_v2.html) unchanged and feeds
them the same Socket.IO events the real monitor emits ('status', 'data',
'login_state', ...), using canned fixtures. It imports nothing from
turbine_monitor, mnet, serial or MQTT code and never opens a device, so it is
safe to run anywhere. It binds to 127.0.0.1 only.

Everything it shows is FIXTURE DATA, not telemetry from a turbine.

    python3 tools/preview_server.py --port 5055
    open http://127.0.0.1:5055/            # scenario index
    open http://127.0.0.1:5055/scenario/stale

Scenarios (see SCENARIOS): live, zero, missing, waiting, stale, turbine_down,
disconnected. The scenario is taken from the page URL (/scenario/<name>), via
the Referer of the Socket.IO handshake, with a cookie as fallback.
"""
import argparse
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, jsonify, make_response, render_template, request, abort
from flask_socketio import SocketIO, emit

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
STATIC = Path(__file__).resolve().parent.parent / 'static'
HOST = '127.0.0.1'
REFRESH_SECONDS = 1.0
DISCONNECT_AFTER_SECONDS = 4.0

SCENARIOS = {
    'live': 'Fresh data every second, non-zero values: should read "Live".',
    'calm': 'QA fixture: fixed near-zero wind (0.2 m/s), rotor stopped -- for calm-vs-high-wind comparison at an identical camera.',
    'windy': 'QA fixture: fixed high wind (18 m/s), rotor spinning fast -- for calm-vs-high-wind comparison at an identical camera.',
    'zero': 'Fresh data where wind, power, RPM, voltages and runtimes are genuinely 0: must show 0, not "--".',
    'missing': 'Fresh data but some fields are null: those show "--", the rest show values.',
    'waiting': 'Server up, controller status known, no turbine data published yet: "Waiting for data…".',
    'stale': 'Server reports data last updated 5 minutes ago: "Stale data", readings dimmed.',
    'turbine_down': 'Server up but reports the controller link is down: "Turbine link down".',
    'disconnected': 'Live for a few seconds, then the server drops the socket and refuses reconnects: "Server unreachable".',
}

_SCENARIO_RE = re.compile(r'/scenario/([a-z_]+)')


def _iso(dt):
    return dt.isoformat()


def _data(now, *, zero=False, missing=False, fixed=None):
    """A data payload shaped like TurbineMonitor._collect_turbine_data()."""
    t = now.timestamp()
    wave = lambda period, lo, hi: lo + (hi - lo) * (0.5 + 0.5 * math.sin(2 * math.pi * t / period))
    if zero:
        n = lambda _v: 0
        runtime = 0
    else:
        n = lambda v: v
        runtime = 123456
    data = {
        'wind_speed_mps': n(round(wave(40, 4.0, 11.0), 1)),
        'rotor_rpm': n(round(wave(50, 14.0, 24.0), 1)),
        'generator_rpm': n(round(wave(50, 900.0, 1500.0), 0)),
        'power_W': n(round(wave(45, 8000.0, 52000.0), 0)),
        'l1v': n(231.0), 'l2v': n(229.0), 'l3v': n(230.0),
        'status_message': 'AWAITING WIND' if zero else 'POWER GENERATION',
        'event_stack_0': 'AWAITING WIND' if zero else 'POWER GENERATION',
        'controller_time': now.strftime('%Y-%m-%d %H:%M:%S UTC'),
        'current_status_code_0': 0 if zero else 3,
        'current_status_code_1': 0,
        'power_W_10min': n(41000.0),
        'l1v_1min': n(230.5), 'l2v_1min': n(229.5), 'l3v_1min': n(230.1),
        'runtime_1_sec': runtime, 'runtime_2_sec': runtime * 2 if not zero else 0,
        'remote_display': ['FIXTURE  PREVIEW  DATA ', 'NOT A LIVE CONTROLLER ',
                           'wind %-6s power %-6s' % (n(round(wave(40, 4.0, 11.0), 1)), n(round(wave(45, 8000.0, 52000.0), 0))),
                           'status: %s' % ('AWAITING WIND' if zero else 'POWER GENERATION')],
    }
    if missing:
        for key in ('wind_speed_mps', 'power_W', 'l2v', 'power_W_10min', 'runtime_1_sec'):
            data[key] = None
        data['controller_time'] = None
        data['status_message'] = ''
    # `fixed`: QA-only override for a genuinely STABLE (non-randomized)
    # wind_speed_mps/rotor_rpm/generator_rpm/power_W reading, so a
    # calm-vs-high-wind screenshot pair at an identical camera reflects a
    # real steady telemetry state rather than racing the live sine-wave
    # randomizer. Only used by the 'calm'/'windy' QA fixtures below.
    if fixed is not None:
        wind_v, rotor_v, gen_v, power_v = fixed
        data['wind_speed_mps'] = wind_v
        data['rotor_rpm'] = rotor_v
        data['generator_rpm'] = gen_v
        data['power_W'] = power_v
        data['power_W_10min'] = power_v
    return data


def build_fixture(name, now=None):
    """Return (status, data) for a scenario at time `now` (UTC). Pure; no I/O."""
    now = now or datetime.now(timezone.utc)
    server_time = _iso(now)

    def status(connected, last_update):
        return {'connected': connected,
                'last_update': _iso(last_update) if last_update else None,
                'server_time': server_time}

    if name in ('live', 'disconnected'):
        return status(True, now), _data(now)
    if name == 'calm':
        return status(True, now), _data(now, fixed=(0.2, 0, 0, 0))
    if name == 'windy':
        return status(True, now), _data(now, fixed=(18.0, 26.0, 1550.0, 11000.0))
    if name == 'zero':
        return status(True, now), _data(now, zero=True)
    if name == 'missing':
        return status(True, now), _data(now, missing=True)
    if name == 'waiting':
        return status(True, None), {}
    if name == 'stale':
        old = now - timedelta(minutes=5)
        return status(True, old), _data(old)
    if name == 'turbine_down':
        old = now - timedelta(minutes=2)
        return status(False, old), _data(old)
    raise KeyError(name)


def _events(now):
    texts = ['POWER GENERATION', 'COMPENSATOR 1 IN', 'GENERATOR 1 IN', 'AWAITING WIND', 'STOP (FIXTURE)']
    return [{'index': i, 'code': i, 'text': f'[fixture] {t}',
             'timestamp': _iso(now - timedelta(minutes=7 * i))} for i, t in enumerate(texts)]


def _alarms(now):
    return [
        {'sub_id': 5, 'description': '[fixture] Vibration', 'has_occurred': True,
         'last_occurred': _iso(now - timedelta(days=3))},
        {'sub_id': 18, 'description': '[fixture] Emergency stop', 'has_occurred': False, 'last_occurred': None},
    ]


def create_app():
    app = Flask(__name__, template_folder=str(TEMPLATES), static_folder=str(STATIC))
    socketio = SocketIO(app, async_mode='threading', cors_allowed_origins=[])
    active = {}              # sid -> scenario, for the refresh loops
    disconnected_seen = {'n': 0}   # 'disconnected' scenario: refuse reconnects after the first drop

    def scenario_of_request():
        match = _SCENARIO_RE.search(request.headers.get('Referer', ''))
        name = match.group(1) if match else request.cookies.get('preview_scenario', 'live')
        return name if name in SCENARIOS else 'live'

    def page(template, name):
        if name not in SCENARIOS:
            abort(404)
        if name == 'disconnected':
            disconnected_seen['n'] = 0
        response = make_response(render_template(template))
        response.set_cookie('preview_scenario', name, max_age=3600, samesite='Lax')
        response.headers['X-Preview-Fixture'] = name
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/')
    def index():
        rows = ''.join(
            f'<li><a href="/scenario/{n}">/scenario/{n}</a> '
            f'(<a href="/v2/scenario/{n}">v2</a>, <a href="/fixture/{n}">json</a>) &mdash; {d}</li>'
            for n, d in SCENARIOS.items())
        return ('<!doctype html><meta charset="utf-8"><title>Dashboard preview</title>'
                '<h1>Dashboard preview &mdash; FIXTURE DATA, NOT A LIVE TURBINE</h1>'
                f'<ul>{rows}</ul>')

    @app.route('/scenario/<name>')
    def scenario(name):
        return page('index.html', name)

    @app.route('/v2/scenario/<name>')
    def scenario_v2(name):
        return page('index_v2.html', name)

    @app.route('/fixture/<name>')
    def fixture(name):
        if name not in SCENARIOS:
            abort(404)
        status, data = build_fixture(name)
        return jsonify({'scenario': name, 'status': status, 'data': data})

    @app.route('/healthz')
    def healthz():
        return jsonify({'ok': True, 'fixture': True})

    def refresh_loop(sid, name):
        while active.get(sid) == name:
            time.sleep(REFRESH_SECONDS)
            if active.get(sid) != name:
                return
            status, data = build_fixture(name)
            # 'calm'/'windy' are QA fixtures with fixed (non-randomized)
            # data, but still need periodic re-emission: the page's
            # Babylon viz handler is registered asynchronously (after a
            # dynamic import resolves) and can miss the single 'data'
            # event sent on connect, in which case it never receives
            # telemetry at all without a follow-up emit.
            if name in ('live', 'zero', 'missing', 'calm', 'windy'):
                socketio.emit('data', data, to=sid)
            # stale / turbine_down re-send status only, as the real monitor does while it retries
            socketio.emit('status', status, to=sid)

    def drop_later(sid):
        time.sleep(DISCONNECT_AFTER_SECONDS)
        if sid in active:
            disconnected_seen['n'] += 1
            socketio.server.disconnect(sid, namespace='/')

    @socketio.on('connect')
    def on_connect():
        name = scenario_of_request()
        if name == 'disconnected' and disconnected_seen['n'] > 0:
            return False   # refuse: the page keeps retrying and shows "Server unreachable"
        status, data = build_fixture(name)
        emit('status', status)
        emit('data', data)
        emit('login_state', {'mode': 'hidden', 'detail': 'preview fixture (no hardware)',
                             'control_available': False})
        active[request.sid] = name
        if name == 'disconnected':
            socketio.start_background_task(drop_later, request.sid)
        else:
            socketio.start_background_task(refresh_loop, request.sid, name)

    @socketio.on('disconnect')
    def on_disconnect(*_):
        active.pop(request.sid, None)

    @socketio.on('get_events')
    def on_get_events(payload=None):
        emit('events', _events(datetime.now(timezone.utc)))

    @socketio.on('get_alarms')
    def on_get_alarms(payload=None):
        emit('alarms', _alarms(datetime.now(timezone.utc)))

    @socketio.on('command')
    def on_command(command):
        emit('command_result', {'ok': False, 'command': str(command),
                                'error': 'preview server: no hardware, command not sent'})

    app.preview_socketio = socketio
    app.preview_active = active
    return app, socketio


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=0, help='port on 127.0.0.1 (0 = pick a free one)')
    args = parser.parse_args()
    port = args.port
    if port == 0:
        import socket
        with socket.socket() as s:
            s.bind((HOST, 0))
            port = s.getsockname()[1]
    app, socketio = create_app()
    print(f'Preview server (FIXTURE DATA ONLY) on http://{HOST}:{port}/', flush=True)
    for name in SCENARIOS:
        print(f'  http://{HOST}:{port}/scenario/{name}', flush=True)
    socketio.run(app, host=HOST, port=port, allow_unsafe_werkzeug=True)


if __name__ == '__main__':
    main()
