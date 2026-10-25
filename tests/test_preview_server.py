"""Offline tests for tools/preview_server.py (fixture server for visual QA).

Checks that the preview tool never touches hardware code and that each scenario
emits the data the dashboard needs to show an honest state.
"""
import ast
import importlib.util
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PREVIEW = ROOT / 'tools' / 'preview_server.py'

spec = importlib.util.spec_from_file_location('preview_server', PREVIEW)
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
NUMERIC = ['wind_speed_mps', 'rotor_rpm', 'generator_rpm', 'power_W', 'l1v', 'l2v', 'l3v',
           'power_W_10min', 'l1v_1min', 'l2v_1min', 'l3v_1min', 'runtime_1_sec', 'runtime_2_sec']


def test_preview_imports_no_hardware_code():
    tree = ast.parse(PREVIEW.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split('.')[0])
    assert not imported & {'turbine_monitor', 'mnet', 'serial', 'paho', 'crc'}, imported


@pytest.mark.parametrize('name', sorted(ps.SCENARIOS))
def test_every_scenario_builds(name):
    status, data = ps.build_fixture(name, NOW)
    assert set(status) == {'connected', 'last_update', 'server_time'}
    assert isinstance(data, dict)


def test_unknown_scenario_raises():
    with pytest.raises(KeyError):
        ps.build_fixture('nope', NOW)


def test_zero_scenario_has_genuine_zeros_and_fresh_timestamp():
    status, data = ps.build_fixture('zero', NOW)
    assert all(data[k] == 0 and data[k] is not None for k in NUMERIC)
    assert data['current_status_code_0'] == 0
    assert status['connected'] is True and status['last_update'] == status['server_time']


def test_live_scenario_is_nonzero_and_fresh():
    status, data = ps.build_fixture('live', NOW)
    assert all(data[k] > 0 for k in NUMERIC)
    assert status['last_update'] == status['server_time']


def test_missing_scenario_has_null_fields():
    _, data = ps.build_fixture('missing', NOW)
    assert data['wind_speed_mps'] is None and data['power_W'] is None
    assert data['rotor_rpm'] is not None


def test_stale_scenario_is_old_but_server_says_connected():
    status, _ = ps.build_fixture('stale', NOW)
    age = datetime.fromisoformat(status['server_time']) - datetime.fromisoformat(status['last_update'])
    assert status['connected'] is True and age == timedelta(minutes=5)


def test_turbine_down_scenario():
    status, _ = ps.build_fixture('turbine_down', NOW)
    assert status['connected'] is False and status['last_update'] is not None


def test_waiting_scenario_has_no_data_or_timestamp():
    status, data = ps.build_fixture('waiting', NOW)
    assert status['connected'] is True and status['last_update'] is None and data == {}


@pytest.fixture
def served():
    app, socketio = ps.create_app()
    return app, socketio


def test_pages_serve_templates_unchanged(served):
    app, _ = served
    client = app.test_client()
    for url, template in (('/scenario/live', 'index.html'), ('/v2/scenario/stale', 'index_v2.html')):
        resp = client.get(url)
        assert resp.status_code == 200
        # Jinja drops one trailing newline; otherwise the template is served byte-for-byte
        assert resp.get_data(as_text=True) == (ROOT / 'templates' / template).read_text().removesuffix('\n')
        assert resp.headers['X-Preview-Fixture'] == url.rsplit('/', 1)[1]
    assert client.get('/scenario/bogus').status_code == 404
    assert 'FIXTURE DATA' in client.get('/').get_data(as_text=True)


def test_fixture_endpoint_returns_json(served):
    body = served[0].test_client().get('/fixture/zero').get_json()
    assert body['scenario'] == 'zero' and body['data']['power_W'] == 0


def _received(client):
    return {m['name']: m['args'][0] for m in client.get_received()}


@pytest.mark.parametrize('name', ['live', 'zero', 'stale', 'turbine_down', 'waiting', 'missing'])
def test_socket_emits_scenario_on_connect(served, name):
    app, socketio = served
    client = socketio.test_client(app, headers={'Referer': f'http://127.0.0.1:1/scenario/{name}'})
    try:
        got = _received(client)
        expected_status, expected_data = ps.build_fixture(name)
        assert got['status']['connected'] == expected_status['connected']
        assert (got['status']['last_update'] is None) == (expected_status['last_update'] is None)
        assert set(got['data']) == set(expected_data)
        assert got['login_state']['control_available'] is False
    finally:
        client.disconnect()


def test_scenario_falls_back_to_cookie_then_live(served):
    app, socketio = served
    http = app.test_client()
    http.get('/scenario/zero')   # sets the cookie
    client = socketio.test_client(app, flask_test_client=http)
    try:
        assert _received(client)['data']['power_W'] == 0
    finally:
        client.disconnect()
    bare = socketio.test_client(app)
    try:
        assert _received(bare)['data']['power_W'] > 0
    finally:
        bare.disconnect()


def test_commands_are_never_executed(served):
    app, socketio = served
    client = socketio.test_client(app)
    try:
        client.get_received()
        client.emit('command', 'stop')
        result = _received(client)['command_result']
        assert result['ok'] is False and result['command'] == 'stop'
    finally:
        client.disconnect()


def test_disconnected_scenario_drops_then_refuses_reconnect(served, monkeypatch):
    monkeypatch.setattr(ps, 'DISCONNECT_AFTER_SECONDS', 0.05)
    app, socketio = served
    app.test_client().get('/scenario/disconnected')   # resets the refusal counter
    headers = {'Referer': 'http://127.0.0.1:1/scenario/disconnected'}
    first = socketio.test_client(app, headers=headers)
    assert first.is_connected()
    assert 'status' in _received(first)
    deadline = time.time() + 2
    while first.is_connected() and time.time() < deadline:
        time.sleep(0.02)
    assert not first.is_connected()
    assert not socketio.test_client(app, headers=headers).is_connected()
