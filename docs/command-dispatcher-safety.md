# MQTT-compatible command safety: dispatcher implementation report

Branch: `feat/command-dispatcher-safety`
Base: `master` @ `7635e0f` (local checkout; also matches deployed `0214f17` lineage per `git log`)
Host: node `deb` (checkout at `/home/andy/projects/turbine`)
Status: **local branch only. No push, no PR, no merge, no deploy in this pass.**

## 0. What was NOT done / explicit blockers

- **Live turbinepi device**: could not locate `/home/andy/turbine-new-0214f17`
  or a running `turbine_monitor.py`/PID 28480 process on this host (`deb`).
  Nothing on the live device was read, modified, restarted, or sent a
  control command — this pass only touched the git checkout on `deb`.
  If the live box is a different physical host ("turbinepi"), it was not
  reachable from this execution context and was not touched, per the
  explicit instruction not to.
- **HA / domesticgoddess MQTT automation audit**: not performed. No
  `/mnt/ha` path was accessible from this host and no cooperating HA agent
  was available in this pass. This is a real gap in the "no breaking
  callers" guarantee below — any Home Assistant automation subscribing to
  `turbine/<serial>/command_result` or depending on retained-command replay
  was not inventoried. Flag for follow-up before deploy.
- **Broker ACL/auth change**: none made. See Section 3 (Security gap) —
  this is deliberately read-only/documentary this pass.
- **Deployment**: none. This is a reviewed, offline-tested local branch,
  not a deploy artifact.

## 1. Compatibility table (audited from the pre-change code, `turbine_monitor.py`)

| Interface | Accepted input (legacy, verified in code) | Case/whitespace | Response contract |
|---|---|---|---|
| MQTT `turbine/<serial>/command` | bare plain-text payload, one of `start, stop, reset, manual_start, auto, ack` (`COMMAND_MAP` keys) | `.strip().lower()` applied; any case/leading-trailing whitespace accepted | none (fire-and-forget; no MQTT reply topic existed before this change) |
| Socket.IO `command` event | same bare string, same `COMMAND_MAP` | `.strip().lower()` | `command_result` socket event: `{'command', 'ok', ['reply'|'error']}` |
| HTTP `POST /api/command/<name>` | `<name>` path segment, same `COMMAND_MAP`; password via `X-Control-Password` header or JSON body `{"password": ...}` | `.strip().lower()` | synchronous JSON: `{'command','ok', 'reply'|'error'}`; 401 unauthorized, 400 unknown command, 504 on 20s timeout |

All three interfaces previously wrote into **the same two shared mutable
instance fields** (`self.pending_command`, `self.pending_command_name`) with
no locking at the point of write (only the HTTP path used `command_lock`,
and only around its own 20s wait — not around the write itself), no queue,
no expiry, no request identity, and no defense against retained MQTT
messages being replayed as a live command on every broker reconnect.

This compatibility table was validated against the actual pre-change code
in `_handle_command_message`, `_handle_socket_command`, and the
`/api/command/<name>` route (see git history on this branch for the exact
removed code), not assumed from documentation.

## 2. Behavioral changes (this branch)

**Unchanged (verified by tests):**
- All current MQTT command topic names and all legacy plain-text command
  payloads (`start/stop/reset/manual_start/auto/ack`, any case/whitespace)
  are still accepted — no new required field, no password field, no new
  message format required.
- Telemetry topics/JSON fields: untouched. No telemetry-publishing code
  path was modified.
- Legacy Socket.IO and HTTP `/api/command/<name>` contracts: response
  shapes are preserved (`command`, `ok`, `reply`/`error`); additive fields
  (`state`, `id`) were added alongside, not instead of, the legacy keys.

**New / changed:**
- A single `CommandDispatcher` (`command_dispatcher.py`) now owns every
  command submission from all three interfaces. There is exactly one
  `submit()` path; nothing sets a "pending command" directly anymore.
- Retained MQTT command messages are rejected **before** queueing
  (`message.retain` checked in `_handle_command_message`), closing the gap
  where a stale retained command could be replayed as live intent on every
  broker reconnect.
- Bounded queue (`max_queue=8` by default): a caller that floods the queue
  gets an explicit rejection (HTTP 429 / logged warning), not silent
  dropping or unbounded memory growth.
- Expiry is checked twice: once at enqueue, and again immediately before
  the command is handed to the serial executor. A command that goes stale
  while queued is marked `EXPIRED` and is **never executed** — this closes
  the original "resume this stale intent after we recover" risk.
  - **Honest limitation**: for legacy callers (plain MQTT payload, bare
    socket command, bare HTTP path) there is no original send-time in the
    payload, so expiry is measured from **receive time**, not true
    end-to-end intent age. This is disclosed, not hidden.
- An optional additive JSON envelope (`{"command": "...", "request_id":
  "...", "ttl": ...}`) lets a caller supply its own `request_id` for
  bounded dedup and/or a custom `ttl`. Legacy bare-string payloads are
  completely unaffected and get internally generated ids — so there is
  **no end-to-end dedupe guarantee** for legacy callers (two identical
  legacy submissions are two distinct commands, by design, since we cannot
  tell them apart).
- Terminal states are now explicit and truthful:
  `queued → executing → {acknowledged | rejected | expired | cancelled |
  unknown}`. A client-timeout on the already-`EXECUTING` HTTP wait (or on
  the dispatcher's own executor call) produces `UNKNOWN`, never a false
  "success" and never an automatic resend/replay of the physical command.
  A `QUEUED` command can be cancelled; an `EXECUTING` one cannot (we never
  claim to stop something already sent to the controller).
- Additive, non-retained MQTT result topic:
  `turbine/<serial>/command_result`, QoS 0, **not retained** (so a stale
  result is never replayed to a new subscriber), payload
  `{id, source, command, state, received_at, started_at, finished_at,
  reason}` — no password/secret fields. Publish failures are caught and
  logged, never blocking command execution (a down broker cannot wedge the
  worker).
- No "operator priority stop" / emergency semantics were introduced. `stop`
  behaves exactly as before: one more command in the same serialized queue,
  same priority as everything else. This was a deliberate choice to avoid
  inventing safety semantics the hardware/protocol doesn't actually have.

## 3. MQTT broker authentication — read-only inventory + security gap

**Read-only finding (config key names only, no values read or printed):**
the only broker-related configuration key in this codebase is `MQTT_HOST`
(env var, default `mqtt.lan`). The paho client is constructed as:

```python
mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id='turbine_mqtt', userdata=self)
...
client.connect_async(self.mqtt_host)
```

There is **no call to `client.username_pw_set()`, no TLS context, and no
client-certificate configuration anywhere in this repository.** No
credential env vars (`MQTT_USER`, `MQTT_PASS`, etc.) exist in this code.

**SECURITY GAP (explicit, not silently bypassed):** this client connects
anonymously. Whether the broker itself enforces authentication/ACLs at the
network layer is **unknown from this codebase alone** — that is broker-side
configuration this repo does not control or ship, and auditing the actual
running broker's ACL/auth state was out of scope for this pass (no broker
access was attempted or authorized here). This change does **not** make any
claim that MQTT transport is authenticated, and does not change broker
policy.

**Concrete migration proposal (not implemented here):**
1. Add `MQTT_USERNAME`/`MQTT_PASSWORD` (or a TLS client-cert pair) env vars,
   call `client.username_pw_set()` / `client.tls_set()` before connect.
2. Configure the broker with per-topic ACLs scoping each client to
   `turbine/<serial>/#` publish/subscribe only.
3. Roll out broker auth and client credentials together, with a bounded
   dual-run window, and confirm every subscriber (including any HA
   automation — see Section 0) has been migrated before enforcing auth.
   This is a deliberate, separate authorization step, not bundled into this
   change.

## 4. Web (HTTP/Socket.IO) auth boundary

Unchanged in this pass: `TURBINE_CONTROL_PASSWORD`-gated
`/api/command/<name>` (header or JSON body password), same as before. This
branch does not introduce, remove, or bypass that check — it only moved
*what happens after* the check passes (dispatcher submission instead of a
raw shared field). No new unauthenticated path was added. A deliberate
future web-auth migration (e.g. session/CSRF hardening) is out of scope
here and was not silently assumed "already protected" anywhere in this
change.

## 5. Tests (offline only; exact invocation + evidence)

Host: node `deb`, checkout `/home/andy/projects/turbine`,
venv: `venv/bin/python3` (Python 3.11.14, pytest 9.1.1).

Baseline (pre-change, same checkout, `master`):
```
$ venv/bin/python3 -m pytest -q
172 passed, 33 skipped in 0.52s
```

This branch, full suite:
```
$ venv/bin/python3 -m pytest -q
202 passed, 33 skipped in 3.34s
```
(172 baseline + 30 new: `tests/test_command_dispatcher.py` [18] +
`tests/test_command_entrypoints.py` [12]. The 33 skipped hardware-only /
quirk-ack tests are untouched and remain skipped — same count as baseline.)

New test modules:
- `tests/test_command_dispatcher.py` — unit tests on `CommandDispatcher`
  directly with a fake clock and fake executor: unknown command rejected
  pre-queue, retained-flag rejected pre-queue, queue-full rejection,
  expiry-at-enqueue, expiry-just-before-execution (never reaches executor),
  cancel-while-queued vs cannot-cancel-while-executing, timeout → `UNKNOWN`
  (never resent/never "success"), request-id dedupe vs. legacy
  non-dedupe, concurrent multi-source submission ordering (no overlapping
  executor calls), malformed/non-JSON payload handling, negative-ACK →
  `REJECTED`, and a no-secrets-in-result assertion.
- `tests/test_command_entrypoints.py` — integration-style tests against
  `TurbineMonitor` (mnet/MQTT/SocketIO mocked, no hardware/network) proving
  MQTT, Socket.IO, and HTTP all funnel into the same dispatcher instance;
  retained-message rejection at the MQTT boundary; additive JSON envelope
  request-id plumbing; the new non-retained `command_result` MQTT
  publication and its payload shape; HTTP password gate, unknown-command
  400, queue-full 429; and one concurrent MQTT+Socket.IO+HTTP submission
  test asserting no shared-state races.

No real MQTT broker, serial device, or network socket was opened by any
test. No test imports or executes any live-hardware path; the pytest
hardware-skip markers are unaffected (33 skipped, matching baseline).

**Independent review**: not performed as a separate actual-Claude
plan-mode pass in this run (no second reviewing agent was spawned for this
diff). Flag as a remaining step before merge if an independent review gate
is required by policy.

**Browser/UI QA**: no UI/template files were modified in this change (the
WebUI's existing `command_result` socket-event consumption is unchanged in
shape), so no browser QA harness was started.

## 6. Remaining deployment decision

This branch is **not deployed and not proposed for immediate deploy.**
Recommended before any deploy decision:
1. Resolve the HA-automation-audit gap in Section 0.
2. Decide on the MQTT broker auth migration in Section 3 as a separate,
   explicitly authorized change.
3. Get an independent review pass on this diff.
4. Validate against the actual live turbinepi device's current release
   once the above are resolved, under a separate explicit deploy
   authorization — this pass intentionally did not touch that device.
