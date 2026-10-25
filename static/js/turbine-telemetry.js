/**
 * turbine-telemetry.js
 *
 * Pure, DOM-free telemetry/physics helpers for the Gaia-Wind 133 visualization.
 * Kept separate from turbine-scene.js so the math can be unit tested with
 * plain Node (no browser, no Babylon.js) via tests/js/turbine-telemetry.test.mjs.
 *
 * Real deployed Socket.IO fields observed in turbine_monitor.py `_poll_data()`
 * / `_status_payload()` (verified by reading the server source directly, not
 * assumed):
 *   'data' event   -> { wind_speed_mps, rotor_rpm, generator_rpm, power_W,
 *                        l1v, l2v, l3v, status_message, event_stack_0,
 *                        controller_time, current_status_code_0,
 *                        current_status_code_1, power_W_10min, ... }
 *   'status' event -> { connected: bool, last_update: ISO8601|null,
 *                        server_time: ISO8601 }
 *
 * This module never invents fields that are not in that payload.
 */

/** Data considered stale if the server hasn't published an update in this long. */
export const STALE_THRESHOLD_MS = 15000;

/**
 * Convert rotor RPM to angular velocity in radians/sec.
 * omega = 2 * PI * RPM / 60
 * Returns 0 for null/undefined/NaN/negative input (never a fake spin).
 */
export function rpmToAngularVelocity(rpm) {
  const n = Number(rpm);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return (2 * Math.PI * n) / 60;
}

/**
 * Frame-independent integration of rotor angle.
 * @param {number} currentAngleRad current rotor angle (radians, any range)
 * @param {number} rpm current rotor RPM (0/null/missing => no rotation)
 * @param {number} deltaTimeSec elapsed seconds since last frame (clamped to avoid
 *                 huge jumps after a tab was hidden/throttled)
 */
export function stepRotorAngle(currentAngleRad, rpm, deltaTimeSec) {
  const dt = Math.max(0, Math.min(Number(deltaTimeSec) || 0, 0.25));
  const omega = rpmToAngularVelocity(rpm);
  if (omega === 0) return currentAngleRad; // STOP / 0 RPM => freeze, no wobble
  const next = currentAngleRad + omega * dt;
  // Keep the angle bounded to avoid float drift over long sessions.
  const twoPi = 2 * Math.PI;
  return ((next % twoPi) + twoPi) % twoPi;
}

/**
 * Determine whether telemetry should be treated as stale/disconnected.
 * @param {object} status last 'status' payload: {connected, last_update, server_time}
 * @param {number} nowMs client clock ms (Date.now())
 */
export function isStale(status, nowMs) {
  if (!status || status.connected !== true) return true;
  if (!status.last_update) return true;
  const lastUpdateMs = Date.parse(status.last_update);
  if (!Number.isFinite(lastUpdateMs)) return true;
  // Prefer server-relative age (server_time - last_update) when available so a
  // skewed client clock doesn't falsely mark fresh data as stale; otherwise
  // fall back to the client clock.
  let ageMs;
  const serverTimeMs = status.server_time ? Date.parse(status.server_time) : NaN;
  if (Number.isFinite(serverTimeMs)) {
    ageMs = serverTimeMs - lastUpdateMs;
    // Also add how long ago we *received* that status, measured on the client.
    if (Number.isFinite(status._receivedAtMs)) {
      ageMs += Math.max(0, nowMs - status._receivedAtMs);
    }
  } else {
    ageMs = nowMs - lastUpdateMs;
  }
  return !(ageMs >= 0 && ageMs <= STALE_THRESHOLD_MS);
}

/**
 * Map a raw 'data' socket payload into the fields the scene needs, with
 * explicit, honest defaults. Never fabricate a value that wasn't present.
 */
export function mapTelemetry(raw) {
  const r = raw || {};
  const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  return {
    windSpeedMps: num(r.wind_speed_mps),
    rotorRpm: num(r.rotor_rpm),
    generatorRpm: num(r.generator_rpm),
    powerW: num(r.power_W),
    statusMessage: typeof r.status_message === 'string' ? r.status_message : null,
    statusCode0: r.current_status_code_0 ?? null,
    statusCode1: r.current_status_code_1 ?? null,
  };
}

/**
 * Derive the renderable rotor state from telemetry + connection status.
 * This is the single gate that decides "spin, freeze, or alarm" so the
 * scene code never has to re-derive it (and can't drift out of sync with
 * what the badges show).
 *
 * Rules (explicit, per task requirements):
 *  - stale/disconnected  -> frozen, label 'NO DATA'
 *  - connected but rpm<=0 or missing -> frozen, label 'STOPPED' (honest 0, not fake wobble)
 *  - connected and rpm>0 -> spin at that RPM, label 'RUNNING'
 *  - wind speed alone never drives rotation (by construction: rpm comes only from rotorRpm)
 */
export function deriveRotorState(status, rawData, nowMs) {
  const stale = isStale(status, nowMs);
  const telemetry = mapTelemetry(rawData);
  if (stale) {
    return { spinning: false, rpm: 0, telemetry, label: 'NO DATA', stale: true };
  }
  const rpm = telemetry.rotorRpm;
  if (rpm === null || rpm <= 0) {
    return { spinning: false, rpm: 0, telemetry, label: 'STOPPED', stale: false };
  }
  return { spinning: true, rpm, telemetry, label: 'RUNNING', stale: false };
}
