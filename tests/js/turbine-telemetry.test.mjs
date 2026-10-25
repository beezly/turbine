// Plain Node test (node --test), no browser/DOM, no Babylon.js, no hardware imports.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  rpmToAngularVelocity,
  stepRotorAngle,
  isStale,
  mapTelemetry,
  deriveRotorState,
  STALE_THRESHOLD_MS,
} from '../../static/js/turbine-telemetry.js';

test('rpmToAngularVelocity: positive RPM', () => {
  assert.ok(Math.abs(rpmToAngularVelocity(60) - 2 * Math.PI) < 1e-9);
  assert.ok(Math.abs(rpmToAngularVelocity(48) - (2 * Math.PI * 48) / 60) < 1e-9);
});

test('rpmToAngularVelocity: zero/missing/negative never spins', () => {
  assert.equal(rpmToAngularVelocity(0), 0);
  assert.equal(rpmToAngularVelocity(null), 0);
  assert.equal(rpmToAngularVelocity(undefined), 0);
  assert.equal(rpmToAngularVelocity(NaN), 0);
  assert.equal(rpmToAngularVelocity(-5), 0);
});

test('stepRotorAngle: frame-independent integration', () => {
  const omega = rpmToAngularVelocity(60);
  const a1 = stepRotorAngle(0, 60, 0.1);
  assert.ok(Math.abs(a1 - omega * 0.1) < 1e-9);
  const a2a = stepRotorAngle(0, 60, 0.05);
  const a2b = stepRotorAngle(a2a, 60, 0.05);
  assert.ok(Math.abs(a2b - a1) < 1e-9);
});

test('stepRotorAngle: 0 RPM freezes angle exactly (no fake wobble)', () => {
  assert.equal(stepRotorAngle(1.2345, 0, 1), 1.2345);
  assert.equal(stepRotorAngle(1.2345, null, 1), 1.2345);
  assert.equal(stepRotorAngle(1.2345, -3, 1), 1.2345);
});

test('stepRotorAngle: clamps huge deltaTime instead of exploding', () => {
  const normal = stepRotorAngle(0, 60, 0.25);
  const huge = stepRotorAngle(0, 60, 9999);
  assert.ok(Math.abs(huge - normal) < 1e-9);
});

test('isStale: missing status => stale', () => {
  assert.equal(isStale(null, Date.now()), true);
  assert.equal(isStale({}, Date.now()), true);
  assert.equal(isStale({ connected: false }, Date.now()), true);
});

test('isStale: fresh status within threshold => not stale', () => {
  const now = Date.parse('2026-01-01T00:00:10.000Z');
  const status = {
    connected: true,
    last_update: '2026-01-01T00:00:09.000Z',
    server_time: '2026-01-01T00:00:09.500Z',
    _receivedAtMs: now - 100,
  };
  assert.equal(isStale(status, now), false);
});

test('isStale: status not refreshed in a while beyond threshold => stale', () => {
  // The client received this status 60s ago and nothing newer has arrived since;
  // the server/last_update gap itself was tiny (normal operation).
  const receivedAt = Date.parse('2026-01-01T00:00:00.000Z');
  const now = receivedAt + 60000;
  const status = {
    connected: true,
    last_update: '2026-01-01T00:00:00.000Z',
    server_time: '2026-01-01T00:00:00.200Z',
    _receivedAtMs: receivedAt,
  };
  assert.equal(isStale(status, now), true);
  assert.ok(STALE_THRESHOLD_MS < 60000);
});

test('mapTelemetry: only maps known deployed fields, never fabricates', () => {
  const mapped = mapTelemetry({
    wind_speed_mps: 7.2,
    rotor_rpm: 42,
    generator_rpm: 1500,
    power_W: 4200,
    status_message: 'Running',
    current_status_code_0: 3,
    current_status_code_1: 0,
    some_unrelated_field: 'ignored',
  });
  assert.equal(mapped.windSpeedMps, 7.2);
  assert.equal(mapped.rotorRpm, 42);
  assert.equal(mapped.powerW, 4200);
  assert.equal(mapped.statusMessage, 'Running');
  assert.equal('some_unrelated_field' in mapped, false);
});

test('mapTelemetry: missing/non-numeric fields map to null, not 0 or fake values', () => {
  const mapped = mapTelemetry({});
  assert.equal(mapped.windSpeedMps, null);
  assert.equal(mapped.rotorRpm, null);
  assert.equal(mapped.statusMessage, null);

  const mapped2 = mapTelemetry({ rotor_rpm: 'not-a-number' });
  assert.equal(mapped2.rotorRpm, null);
});

test('deriveRotorState: stale/disconnected freezes rotor and labels NO DATA', () => {
  const now = Date.now();
  const state = deriveRotorState({ connected: false }, { rotor_rpm: 50 }, now);
  assert.equal(state.spinning, false);
  assert.equal(state.rpm, 0);
  assert.equal(state.label, 'NO DATA');
  assert.equal(state.stale, true);
});

test('deriveRotorState: connected + 0 RPM => STOPPED, no fake spin even with wind', () => {
  const now = Date.parse('2026-01-01T00:00:10.000Z');
  const status = {
    connected: true,
    last_update: '2026-01-01T00:00:09.000Z',
    server_time: '2026-01-01T00:00:09.500Z',
    _receivedAtMs: now,
  };
  const state = deriveRotorState(status, { rotor_rpm: 0, wind_speed_mps: 28 }, now);
  assert.equal(state.spinning, false);
  assert.equal(state.rpm, 0);
  assert.equal(state.label, 'STOPPED');
});

test('deriveRotorState: connected + missing rotor_rpm => STOPPED (not fabricated motion)', () => {
  const now = Date.parse('2026-01-01T00:00:10.000Z');
  const status = {
    connected: true,
    last_update: '2026-01-01T00:00:09.000Z',
    server_time: '2026-01-01T00:00:09.500Z',
    _receivedAtMs: now,
  };
  const state = deriveRotorState(status, {}, now);
  assert.equal(state.spinning, false);
  assert.equal(state.label, 'STOPPED');
});

test('deriveRotorState: connected + positive RPM => RUNNING at that RPM', () => {
  const now = Date.parse('2026-01-01T00:00:10.000Z');
  const status = {
    connected: true,
    last_update: '2026-01-01T00:00:09.000Z',
    server_time: '2026-01-01T00:00:09.500Z',
    _receivedAtMs: now,
  };
  const state = deriveRotorState(status, { rotor_rpm: 46.5 }, now);
  assert.equal(state.spinning, true);
  assert.equal(state.rpm, 46.5);
  assert.equal(state.label, 'RUNNING');
});
