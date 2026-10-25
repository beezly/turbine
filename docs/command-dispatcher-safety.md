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
- **HA / MQTT automation audit (independent, read-only, INCOMPLETE)**: a
  separate read-only inspection of Home Assistant `automations.yaml`,
  `scripts.yaml` and the MQTT config found no `turbine/<serial>/command`
  publishers and no dynamic command topic in the top-level HA
  automations/scripts/helpers/dashboards. One unrelated `mqtt.publish`
  automation exists (an ebusd poll payload). HA's turbine MQTT config is a
  telemetry subscriber only, with unchanged JSON fields. A Shelly
  switch/reboot entity is not an MQTT command path. This audit did **not**
  cover HA packages or `custom_components`, external publishers, Node-RED,
  or broker ACLs. It therefore does **not** show that no command callers
  exist globally, only that none were found in the inspected top-level HA
  config. No HA or broker config was queried or changed by this work.
- **Broker ACL/auth change**: none made. See Section 3 (Security gap) —
  this is deliberately read-only/documentary this pass.
- **Deployment**: none. This is a reviewed, offline-tested local branch,
  not a deploy artifact.

## 1. Compatibility table (audited from the pre-change code, `turbine_monitor.py`)

| Interface | Accepted input (legacy, verified in code) | Case/whitespace | Response contract |
|---|---|---|---|
| MQTT `turbine/<serial>/command` | bare plain-text payload, one of `start, stop, reset, manual_start, auto, ack` (`COMMAND_MAP` keys) | `.strip().lower()` applied; any case/leading-trailing whitespace accepted | none (fire-and-forget; no MQTT reply topic existed before this change) |
| Socket.IO `command` event | same bare string, same `COMMAND_MAP` (still accepted, unauthenticated, logs a warning); NEW optional dict `{"command", "password", ["request_id"], ["ttl"]}` | `.strip().lower()` | `command_result` socket event: `{'command', 'ok', ['reply'|'error']}` (unchanged); dict with bad/missing password -> `{'command','ok':False,'error':'unauthorized'}` |
| HTTP `POST /api/command/<name>` | `<name>` path segment, same `COMMAND_MAP`; password via `X-Control-Password` header or JSON body `{"password": ...}` | `.strip().lower()` | synchronous JSON: `{'command','ok', 'reply'|'error', 'state','id'}`; 401 unauthorized, 400 unknown command, 429 queue full, 504 on 20s wait timeout (now with truthful `state`: `cancelled`, `executing` or `unknown`) |

(The table above describes the legacy contract; the "Socket" and "HTTP"
cells have been updated for this revision's additive changes only. MQTT
topic names, plain-text payloads and broker authentication behaviour are
unchanged.)

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

### 2a. Hardening revision (items 1–7 of the safety follow-up)

1. **HTTP wait timeout is truthful.** After the 20s wait (`http_command_wait`)
   the handler atomically tries `cancel(id)`. Success -> 504 with state
   `cancelled`. If the command is already `executing` -> 504 with state
   `executing` and a message that it may still take effect. If it finished in
   the race window the real terminal result is returned as usual. If it is
   still `queued` but could not be cancelled, state `unknown` is reported.
2. **Authoritative pre-send check.** Inside `_dispatcher_execute`, under
   `serial_lock`, after the standard login and immediately before
   `send_command`, expiry and shutdown are re-checked. If expired the command
   is NOT sent, the login reverts to hidden, and the executor returns
   `expired_before_send` -> `EXPIRED`. If shutting down it returns
   `cancelled_before_send` -> `CANCELLED`.
   `CommandDispatcher.stop()` atomically cancels all still-`QUEUED` commands
   (`CANCELLED`, reason "dispatcher shutting down", result emitted once) and
   the worker never starts a new send after `stop()`; it only finishes a
   command it had already begun.
3. **Pre-send vs send phase.** Pre-send failures (bad password, login error)
   -> `REJECTED` (never sent). Any failure once sending starts (exception,
   `TimeoutError`, or a reply that is not a `bytes` packet type equal to
   `0x0c32`) is re-raised as `TimeoutError` -> `UNKNOWN`; never `REJECTED`,
   never a false `ACKNOWLEDGED`.
4. **Callbacks outside the lock, exactly once.** `on_result` is invoked after
   `self._lock` is released on every terminal path (normal, timeout,
   exception, expired in queue, expired at enqueue, cancel, shutdown cancel).
   Synchronous `DispatchError` rejects still raise, and additionally emit one
   `REJECTED` result through `on_result` (the rejected request is never
   queued or stored, so queue state and controller state are untouched). As a
   consequence the socket handler no longer emits its own rejection (the
   dispatcher callback emits the identical legacy-shaped `command_result`),
   and MQTT/HTTP rejects now also appear as a `command_result` event and on
   the non-retained `command_result` MQTT topic (additive).
5. **Input validation.** `ttl=None` -> default; `ttl=0` -> immediately
   `EXPIRED`; booleans, non-numbers, NaN/Inf, negatives and values over 300s
   -> `DispatchError` 400. `client_request_id` must be a non-empty string of
   <= 200 chars. Reusing a `client_request_id` for a *different* command ->
   409 conflict (same command still dedupes as before).
   `_trim_records()` only evicts terminal records, oldest first; `QUEUED` /
   `EXECUTING` are never evicted. Behaviour change: a negative `ttl` used to
   mean "expired"; it is now a 400.
6. **Lifecycle.** The dispatcher worker starts at the end of
   `TurbineMonitor.__init__`. `close()` stops the dispatcher first (waiting
   up to 5s for `serial_lock`) before disconnecting MQTT and closing the
   device. If reverting to the hidden login fails, `logged_in` is set to
   `False` so `run()` re-logs in.
7. **Socket.IO auth (partial).** A dict payload is checked against
   `control_password`; mismatch -> `error: unauthorized`, password never
   logged or echoed. Bare strings keep working (warning logged).

## 3. MQTT broker authentication — read-only inventory + security gap

### Broker auth / ACL

The current code does not call any broker authentication or ACL API, so it
does **not** prove the broker is anonymous or secured; that is unknown and
unverified from the code alone. The only broker-related setting referenced in
this repo is the `MQTT_HOST` env var (read in `main()`); no username, password
or TLS configuration key exists, so there is no optional auth support to note
as unchanged. This revision adds no MQTT auth and does not change any topic,
payload format or broker authentication behaviour.

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

**SECURITY GAP (explicit, not silently bypassed):** this client presents no
credentials. Whether the broker itself enforces authentication/ACLs at the
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

### 4a. Follow-up revision (closes the Socket.IO bare-string bypass)

The previous revision of this branch (see "Known remaining security gap"
below, kept for the historical record) left an actual, exploitable
unauthenticated path: the Socket.IO `command` handler accepted a bare
string from any connected client and queued it for execution with only a
log warning, while the *served* `templates/index.html` still only ever
sent that bare-string shape. In practice that meant **every web client
connected to the Socket.IO endpoint could execute start/stop/reset/etc.
with no control password at all**, regardless of whether
`TURBINE_CONTROL_PASSWORD` was configured. This follow-up closes that gap:

- `_handle_socket_command` now **rejects every bare string outright** and
  never calls `self.command_dispatcher.submit(...)` for it. The dict shape
  `{"command", "password", ["request_id"], ["ttl"]}` is the only path that
  can reach the dispatcher, same contract as before, just actually
  enforced now.
- The dict-shape password comparison (both Socket.IO and the pre-existing
  `/api/command/<name>` HTTP header/body check) now uses
  `secrets.compare_digest` instead of `!=`, closing the previously
  disclosed non-constant-time-comparison gap for both paths.
- Rejection/error replies (`command_result` for unauthorized or
  invalid-payload cases) are now sent only to the requesting Socket.IO
  client (`socketio.emit(..., to=request.sid)`), not broadcast to every
  connected socket, verified with a real (non-mocked) `flask_socketio`
  test-client pair in `tests/test_command_dispatcher_safety.py::TestSocketRealTransportTargeting`.
  Successful `command_result` events for genuinely queued/executed
  commands keep the existing broadcast behavior (unchanged shape/contract,
  consistent with prior MQTT/HTTP-triggered broadcasts that all connected
  dashboards already relied on to reflect turbine state).
- `templates/index.html`'s `sendCommand()` now prompts for the control
  password (`window.prompt`) and always sends the dict shape; it never
  sends a bare string. Cancelling the prompt (`null`) or submitting it
  empty sends nothing. The password is not persisted (no `localStorage`,
  no logging) — it exists only for the duration of building that one
  `socket.emit(...)` call. This is new, deliberate web-UI behavior; it was
  not silently left as the old unauthenticated UX.
- **MQTT is explicitly unchanged**: `_handle_command_message` (the
  `turbine/<serial>/command` plain-text legacy path) was not touched by
  this follow-up, verified by `TestMqttAndHttpLegacy` continuing to pass
  unmodified. It remains unauthenticated at the application layer by
  design/legacy contract; broker-level trust/ACL is the control boundary
  there (see Section 3), and that boundary was not touched or re-verified
  in this pass.
- **Browser/UI QA**: a finite, offline, no-browser-required harness
  (`tests/frontend_qa_sendcommand.js`, run with plain `node`) extracts
  `sendCommand()`'s source from the actual served `templates/index.html`
  and runs it in a `vm` sandbox with mocked `window.prompt`/`window.confirm`/
  `socket.emit`, asserting: control-disabled short-circuits before any
  prompt; a cancelled confirm or cancelled password prompt never emits;
  an empty password never emits and shows an error; a real password always
  emits the dict shape (never a bare string) with the typed password in
  the `password` field; and the function source contains no
  `localStorage`/`console.log` of the password. This is a static/sandbox
  check of the exact shipped JS, not a live-browser click-through.

### Known remaining limitations (still open, unchanged by this follow-up)

- **Transport/origin trust**: the password still travels as plain
  Socket.IO/HTTP payload. Anyone who can observe the page (compromised
  origin, non-HTTPS deployment, malicious extension, etc.) can observe
  what the user types into the `window.prompt()` dialog or sniff the
  payload on the wire. This UI change does not add encryption or add any
  CSRF/session hardening; deploying this over plain HTTP, or on an
  untrusted origin, is not materially safer than before. HTTPS + a trusted
  origin remain the actual control boundary for this transport, same as
  the pre-existing HTTP header/body password gate.
- **Broker trust is unchanged and still unverified** by this pass (see
  Section 3): MQTT commands remain plain-text, unauthenticated at the
  application layer, same topics/format, trusted entirely to the broker's
  own auth/ACL, which was not (re-)audited here.
- **Dispatcher dedupe cache**: reviewed again in this pass; remains a
  *bounded* FIFO cache (`OrderedDict`, size-capped, evicts oldest), giving
  only a best-effort, bounded-window de-duplication guarantee for
  `client_request_id` — not a global, time-unbounded exactly-once
  guarantee. No undisclosed race was found in the dedupe read/write path
  beyond what Section 2 already documents (it is read/written entirely
  under the dispatcher's single lock); this is a scope/guarantee
  clarification, not a new fix.
- **HTTP-side cancellation window** (unchanged from Section 5's prior
  finding): a command already admitted to the executor (state
  `EXECUTING`) but still blocked on `serial_lock` when the HTTP client's
  wait deadline is hit cannot be cancelled by that HTTP call — cancellation
  only ever applies to still-`QUEUED` commands, by design. It can still
  physically send up to the dispatcher's own TTL window after the HTTP
  response returns. This is reported truthfully via `state` rather than
  claimed cancelled, and there is **no absolute "nothing sends after
  shutdown" guarantee** — only a best-effort check immediately before
  send, which a true in-flight race could still beat. Not re-litigated or
  changed in this follow-up; carried over from Section 5 as still accurate.

### Previously disclosed security gap (closed above; kept for history)

WebSocket control-command auth was **not** fully unified with the HTTP
password gate: legacy bare-string Socket.IO callers (the then-current
WebUI) were accepted without a password; only the dict form with
`password` was checked. **This gap is now closed** — see 4a above.

## 5. Tests (offline only; exact invocation + evidence)

> **Revision note:** the figures below are from the earlier pass. The
> hardening revision added `tests/test_command_dispatcher_safety.py` and
> changed one assertion in `tests/test_command_dispatcher.py` (negative ttl
> -> `ttl=0`). The suite could not be executed in the authoring session
> (command execution was not permitted), so there are **no verified counts
> for this revision**; run `python3 -m pytest` and record real counts before
> relying on it.

Host: node `deb`, checkout `/home/andy/projects/turbine`,
venv: `venv/bin/python3` (Python 3.11.14, pytest 9.1.1).

Baseline (pre-change, same checkout, `master`):
```
$ venv/bin/python3 -m pytest -q
172 passed, 33 skipped in 0.52s
```

This branch, after the hardening revision (1537d96, prior to this
follow-up):
```
$ venv/bin/python3 -m pytest -q
269 passed, 33 skipped in 6.28s
```

This follow-up revision (closing the Socket.IO auth-bypass gap), full
suite, re-run and counted in this session:
```
$ venv/bin/python3 -m pytest -q
272 passed, 33 skipped in 6.27s
```
(269 prior + 3 new: `TestSocketRealTransportTargeting` in
`tests/test_command_dispatcher_safety.py`, using real — not mocked —
`flask_socketio` test clients to prove the unauthorized/bare-string
rejection reaches only the requesting socket and never a bystander, and
that an authenticated command still executes end-to-end over that real
transport. Existing socket tests in `TestSocketAuthAndLegacy` and
`tests/test_command_entrypoints.py::TestSocketEntrypoint` were updated —
not just left passing by accident — because they previously asserted the
bare-string bypass as *correct* behavior; they now assert it is rejected.
The 33 skipped hardware-only/quirk-ack tests are untouched and remain
skipped — same count as baseline. Separately, `node
tests/frontend_qa_sendcommand.js` (offline, no browser, no server) passed
13/13 assertions against the actual shipped `templates/index.html`
`sendCommand()` source — see Section 4a.)

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

**Independent review**: performed as a separate actual-Claude plan-mode
pass (read-only, no edits) against this diff. Verdict: **no blockers**.
Minor/nit findings and their resolution:
- Huge-integer `ttl` (e.g. a 400-digit literal) could raise `OverflowError`
  inside `_validate_ttl` and escape `submit()` with no terminal state ever
  recorded. **Fixed**: `math.isfinite`/comparison now wrapped so any
  out-of-range value, however large, is a clean 400 `DispatchError`; a
  regression case (`10**400` and its negative) was added to
  `test_invalid_ttl_rejected`.
- `close()` closed the serial device even when `serial_lock.acquire(timeout=5)`
  failed (i.e. a command might still be mid-send). **Fixed**: the device is
  now only closed when the lock was actually acquired; otherwise it logs
  loudly and leaves the device open rather than racing an in-flight send.
- A command already marked EXECUTING but still blocked on `serial_lock` when
  an HTTP client's 20s wait expires cannot be cancelled by that endpoint
  call; it can still send up to the dispatcher's own TTL window later. This
  is reported truthfully (`state: executing`/`unknown`) rather than claimed
  cancelled — **documented as a known residual gap**, not fixed in this
  pass (closing it fully needs either passing the HTTP wait window through
  as the request `ttl`, or a separate cooperative-cancel flag checked inside
  the executor; left as a follow-up, not silently claimed done).
- `client_request_id` dedupe hits on a request whose original outcome was
  terminal (CANCELLED/EXPIRED/REJECTED) return that stale terminal record
  without re-emitting a result to the new caller, and a plain duplicate
  across unrelated clients using a weak id collides silently. **Documented**
  as a known limitation of the dedupe cache (not fixed in this pass).
- Socket/HTTP password comparison is a plain `!=`, not constant-time
  (`hmac.compare_digest`); pre-existing behavior, not introduced by this
  change. **Documented**, not fixed in this pass.
- `_set_login_state('command', ...)` (a socketio emit) sits inside the
  send-phase try/except; if that emit itself raised, a pre-send failure
  would be misclassified as UNKNOWN instead of REJECTED. Noted as a
  theoretical edge case (socketio.emit failures are not observed in
  practice here); not fixed in this pass.

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

## 7. Remaining limitations / security blockers

- **Socket auth gap: CLOSED** by the follow-up revision in Section 4a —
  legacy bare-string Socket.IO commands are now always rejected
  (unauthenticated) and never reach the dispatcher; only the
  password-checked dict shape can execute a command.
- **Transport/origin trust (still open)**: the control password is still
  typed into a plain `window.prompt()` and sent as a Socket.IO/HTTP
  payload; this is only as safe as HTTPS + a trusted origin, which this
  change does not add or verify.
- **MQTT broker trust (still open, unchanged)**: MQTT commands remain
  plain-text and unauthenticated at the application layer; broker auth/ACL
  is the only control boundary there and was not (re-)audited in this
  pass.
- **0x0c32 reply semantics are uncertain**: `docs/MNET.md` documents no reply
  code for the command request (`REQ_COMMAND` / `0x0C32`). `mnet.send_packet`
  therefore requires an exact echo of `0x0c32`, and `_dispatcher_execute`
  re-checks that. We have no evidence that an echoed `0x0c32` guarantees the
  controller *acted* on the command (as opposed to merely receiving it), so
  `ACKNOWLEDGED` means "well-formed reply received", not "command effect
  verified". Confirm the effect via telemetry/status.
- **Broker auth unknown**: see "Broker auth / ACL". Not verified either way.
- **Expiry for legacy callers** is measured from receive time.
- **Incomplete HA audit** (Section 0): other publishers may exist.
- **UNKNOWN is final**: no automatic resend; an operator must check status.
- **HTTP-timeout-vs-already-executing race**: if a command is EXECUTING but
  still waiting on `serial_lock` when the HTTP 20s wait gives up, it cannot
  be cancelled from that request and may still send within its TTL window;
  reported truthfully, not fixed (see Section 5 "Independent review").
- **Dedupe cache on a terminal (non-success) prior outcome**: reusing a
  `client_request_id` after a CANCELLED/EXPIRED/REJECTED prior attempt
  returns that stale record with no new result emitted until the id ages
  out of the 256-entry FIFO; not fixed (see Section 5).
- **Password comparisons are not constant-time** (`!=`, not
  `hmac.compare_digest`) on both the HTTP and socket control-password
  checks; pre-existing, not introduced or fixed here.
