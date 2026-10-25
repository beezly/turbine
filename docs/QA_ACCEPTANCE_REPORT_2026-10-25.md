# Turbine local acceptance QA — 2026-10-25

Host: deb (node, verified via `hostname`). Branch: `fix/protocol-reliability` at
commit `bb12e0f` (HEAD, unchanged — no corrective edits were needed; see
"Findings" below). Working tree clean except untracked `.qa-artifacts/`
(now gitignored).

## 1. Backend protocol review

Reviewed `mnet.py` / `turbine_monitor.py` against `docs/PROTOCOL_ANALYSIS.md`
and the prior (untracked) `backend_validation_plan.md` gap analysis, which
had flagged three "HIGH PRIORITY" gaps as not yet addressed:

- **Gap A** (response source/destination validation in `send_packet`):
  **already implemented** — `mnet.py:300-337` validates
  `response.source == destination`, `response.destination == self.id`, and
  `response.packet_type == packet_type`, raising `MnetDecodeError` on
  mismatch.
- **Gap B** (`logged_in` flag not gating requests): **already implemented**
  — `turbine_monitor.py:656` and `:788` gate request paths on
  `self.logged_in`.
- **Gap C** (unstandardized transaction identity validation): **already
  implemented** — `send_command`, `request_data`, `request_multiple_data`,
  and the remote-display getters all route through `send_packet`, which
  performs the Gap A validation uniformly.

Conclusion: the gap-analysis document in the repo was stale relative to the
current `HEAD` (bb12e0f); no further backend code changes were needed. No
edits made to `mnet.py` / `turbine_monitor.py`.

## 2. UI contrast review

`templates/index.html:28` already carries the corrected `--text-muted`
value `#7c8a9e` with an inline comment noting it replaced `#64748b`
(~4.1:1) to reach ≥4.5:1 contrast on `--bg-primary`. `git diff` against
HEAD showed **no uncommitted contrast changes** — the fix is already
committed (part of `bb12e0f`/`c4a7e17`). No edit needed.

## 3. Backend offline test suite

Interpreter: `/home/andy/projects/turbine/venv/bin/python` (3.11.14).
Module resolved from repo (`mnet.__file__` = `.../turbine/mnet.py`, not a
stray install).

```
$ /home/andy/projects/turbine/venv/bin/python -m pytest -q --no-header
...
======================= 152 passed, 33 skipped in 0.44s ========================
```

Exit code 0. Matches prior coordinator evidence (152 passed / 33 skipped);
confirmed fresh, not reused.

## 4. Browser acceptance QA (finite harness, no background processes)

Process reconciliation before testing: no `preview_server.py` process, no
listener on port 5055, and no PID 397194 were found running on deb — nothing
to disturb. No long-lived user tmux session was touched.

Harness: `.qa-artifacts/qa_acceptance.py`, run with
`/home/andy/.pyenv/versions/3.14.2/envs/unifi-openapi-spec-generator/bin/python3`
(Playwright + cached Chromium), single `exec` call, `timeout 115`
wall-clock. The script starts `tools/preview_server.py` (turbine venv, port
5056, fixture data only — no hardware/broker imports) as a `subprocess`,
runs all checks, then terminates the server and closes the browser in a
`finally` block inside the same process before exiting. No `nohup`, no
`background:true`, no detached shell.

```
$ timeout 115 <pyenv-python3> .qa-artifacts/qa_acceptance.py
PASS server_started preview server on http://127.0.0.1:5056
PASS live_status_text_present statusText='Live'
PASS zero_status_text_present statusText='Live'
PASS zero_shows_0_not_dash wind='0.0' power='0 W'
PASS missing_status_text_present statusText='Live'
PASS missing_shows_dash_somewhere expected some '--' placeholders for null fields
PASS stale_status_text_present statusText='Stale data'
PASS stale_mentions_stale statusText='Stale data'
PASS turbine_down_status_text_present statusText='Turbine link down'
PASS turbine_down_message statusText='Turbine link down'
PASS disconnected_status_text_present statusText='Server unreachable'
PASS disconnected_message statusText='Server unreachable'
PASS desktop_1280_no_overflow scrollWidth=1280 innerWidth=1280
PASS desktop_control_buttons_present count=8
PASS history_tab_switch_alarms_active active_count=1
PASS log_tab_switch_mqtt_active active_count=1
PASS keyboard_activation_events_tab active_count=1
PASS reduced_motion_media_query_matches matches=True
PASS reduced_motion_no_active_animations any_active_animation=False
PASS mobile_320_no_overflow scrollWidth=320 innerWidth=320
PASS mobile_390_no_overflow scrollWidth=390 innerWidth=390

=== SUMMARY ===
total=21 failed=0
```

Exit code 0 (21/21 checks passed). Checks covered:

- Six fixture scenarios at desktop 1280×900 (`live`, `zero`, `missing`,
  `stale`, `turbine_down`, `disconnected`) with honest status-text
  assertions pulled from the live DOM (`#statusText`): zero genuinely shows
  `0.0`/`0 W` (not `--`); missing shows `--` placeholders; stale/turbine
  down/disconnected show their distinct, honest messages (no silent
  "connected" fallback).
- Desktop 1280 width: zero horizontal overflow (`scrollWidth == innerWidth`
  == 1280); 8 control buttons present (Start/Stop/Reset/Manual/Auto/Ack +
  history/log tab buttons counted separately).
- Tab controls: clicking the "Alarm History" and "MQTT" tabs correctly
  toggles the `.active` class on the corresponding panel.
- Keyboard: focusing the "Event Stack" tab button and pressing `Enter`
  (native `<button>` activation) correctly switches the active panel —
  DOM-asserted, not just visual.
- `prefers-reduced-motion: reduce` emulation: media query matches, and (after
  correcting the harness's own initial over-strict assertion, which wrongly
  required literal `0s` instead of the CSS's `0.01ms !important` reduced
  value) no element has an active animation with duration >1ms.
- Mobile 320px and 390px viewports: zero horizontal overflow at both widths.

Screenshots saved under `/home/andy/projects/turbine/.qa-artifacts/`
(now gitignored, left on disk for inspection):
`acc_live_desktop1280.png`, `acc_zero_desktop1280.png`,
`acc_missing_desktop1280.png`, `acc_stale_desktop1280.png`,
`acc_turbine_down_desktop1280.png`, `acc_disconnected_desktop1280.png`,
`acc_desktop1280_controls.png`, `acc_reduced_motion.png`,
`acc_mobile_320.png`, `acc_mobile_390.png`. Raw results also in
`acceptance_results.json`.

Process check after the run confirmed no leftover `preview_server.py` or
Chromium process and nothing on port 5056 — the finite harness cleaned up
fully.

## 5. Outcome

No real acceptance regression was found: the previously-flagged backend
gaps and the UI contrast fix were already present and correct in commit
`bb12e0f`. No source edits were made; Claude CLI was not invoked because
there was nothing to fix. This report plus the gitignore update for
`.qa-artifacts/` are the only changes.

No turbinepi operations, push, deploy, or merge were performed.
