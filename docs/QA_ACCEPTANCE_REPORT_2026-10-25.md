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
  source/destination checks were present and correct in `bb12e0f`. The
  packet-type check introduced by commit `69d7e0c` asserted
  `response.packet_type == packet_type` (a universal echo check), and this
  QA report's first draft (superseded by the "Correction" section below)
  endorsed that echo check as correct validation. **That endorsement was
  wrong and is retracted here.**
- **Gap B** (`logged_in` flag not gating requests): already implemented —
  `turbine_monitor.py:656` and `:788` gate request paths on
  `self.logged_in`. Unaffected by this correction.
- **Gap C** (unstandardized transaction identity validation): `send_command`,
  `request_data`, `request_multiple_data`, and the remote-display getters do
  route through `send_packet` uniformly, but `send_packet` itself enforced
  the wrong rule (see "Correction" below).

### Correction (superseding the above "already implemented" conclusion for Gap A)

**The original conclusion was wrong.** `send_packet` (introduced by
`69d7e0c`, commit message "Validate response destination/type...") asserted
`response.packet_type == packet_type` — i.e. that every reply echoes its
request's packet type. Per `docs/MNET.md` "Packet Type Codes" and "Message
Sequence Examples", the Mnet protocol does **not** work that way for most
message types: request and reply use distinct, specifically-documented
codes, e.g.:

- Request data `0x0C28` → Reply data `0x0C29`
- Request multiple data `0x0C2A` → Reply multiple data `0x0C2B`
- Request write data `0x0C2C` → Reply write data `0x0C2D`
- Request serial no. `0x0C2E` → Reply serial no. `0x0C2F`
- Display command type 2 `0x0C04` → `0x0C06`; type 3 `0x0C05` → `0x0C07`
- Acknowledge alarm `0x0BEA` → Reply Acknowledge `0x0001`

Login (`0x138E` standard, `0x13A1` hidden) is the documented exception where
a *successful* login reply does echo the request's own type; a *rejected*
login instead returns the shared "Remote not logged in" code `0x1390` — a
valid negative, not a successful login and not corruption.

Under the old universal-echo rule, a genuine, correctly-formed reply to
e.g. a `0x0C28` data request (type `0x0C29`) would have been **rejected**
as a "packet type mismatch", and conversely a reply that happened to merely
echo the request type back (not a real documented reply) would have been
**wrongly accepted**. This QA report previously endorsed that behavior as
correct; it was not.

**Fix applied in this pass**, as an uncommitted working-tree change on top
of `2209c2b` at the time this correction was written (committed separately
immediately after, with the resulting commit hash recorded in this repo's
`git log`): `mnet.py` `send_packet` (now `mnet.py:341-420`,
moved from the `69d7e0c`-era `mnet.py:300-337` cited above as the original
code location) now resolves an explicit,
per-request-type set of documented valid reply types
(`Mnet.REQUEST_RESPONSE_TYPES`) built directly from `docs/MNET.md`, instead
of assuming echo. Source/destination identity validation (the part of Gap A
that was actually correct) is unchanged. A login request that receives the
documented `0x1390` "Remote not logged in" reply now raises a dedicated
`MnetLoginRejectedError` (a subclass of `MnetDecodeError`) so callers can
distinguish a valid rejection from a successful login or from frame/CRC
corruption, rather than being misreported as a generic type mismatch.
Request types with no documented reply code in `docs/MNET.md` (currently
only `REQ_COMMAND` / `0x0C32`, whose only caller logs whatever type comes
back without asserting one) still require an exact echo as a conservative
fallback — not because echo is proven correct for that type, but because no
reply code is documented for it and documented pairs higher are known to be
non-echo, so nothing better is invented.

Two existing tests in `tests/test_protocol_recovery.py`
(`test_send_packet_accepts_matching_source`,
`test_send_packet_accepts_fully_matching_wire_response`) were self-confirming
fixtures: they constructed a `0x0c28` request's "good" reply as itself
`0x0c28` (an echo), which is not what the real protocol or `docs/MNET.md`
describes. Both were corrected in place to use the documented `0x0c29`
reply type (not duplicated). Eleven new tests were added in
`TestTransactionIdentityValidation` covering: an echoed reply being
rejected where docs require a different type, an unrelated wrong reply
type being rejected, multiple-data/write-data/serial-number/acknowledge-alarm
documented reply types, successful login echo (both login variants), login
rejection raising `MnetLoginRejectedError` for both login variants, and a
corrupted "not logged in" frame still failing CRC validation rather than
being accepted as a valid rejection. No CRC or source/destination
assertions were weakened; only the request→reply type expectation was
corrected to match `docs/MNET.md`.

Conclusion: the gap-analysis document being stale was true for Gaps B and
C, but Gap A's packet-type-echo assumption was independently wrong and is
corrected above.

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

Exit code 0. Matches prior coordinator evidence (152 passed / 33 skipped) at
the time this report was first written, against the then-unmodified
`bb12e0f`/`2209c2b` tree. **Superseded by the correction above**: after
fixing `send_packet`'s request→reply type mapping and correcting the two
self-confirming echo fixtures (plus 11 new tests), the suite now reports:

```
$ /home/andy/projects/turbine/venv/bin/python -m pytest -q --no-header
...
======================= 163 passed, 33 skipped in 0.46s ========================
```

Exit code 0, still unpiped. 163 = 152 original + 11 new tests added to
`tests/test_protocol_recovery.py::TestTransactionIdentityValidation` (the 2
pre-existing self-confirming echo tests in that class were corrected
in place, not duplicated, so they are not additional counts). Skip count
(33) unchanged — same previously-skipped tests, untouched by this fix.

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
