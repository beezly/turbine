# Turbine deploy/rollback report — 2026-10-25

## PR / merge

- PR: https://github.com/beezly/turbine/pull/1
- Head SHA (branch `fix/protocol-reliability`): `124376fdde88113bd3936556cd4a43fc137006f4`
- Merge commit (on `master`): `aa79bfe5c67479b13852bc20d09ee942c3d815e3`
- Merged: `2026-10-25T09:44:36Z`, state `MERGED` (verified via `gh pr view`)
- No CI configured in this repo (`.github/workflows` absent); merge gated only
  on a fresh local `pytest -q` run: **163 passed, 33 skipped** (matches
  `docs/QA_ACCEPTANCE_REPORT_2026-10-25.md`).
- Diff reviewed for secrets/fabricated artifacts: none found (`.env` only
  added to `.gitignore`, never committed).

## Rollback preparation (before any live change)

- Pre-deploy backup dir on `turbinepi`:
  `/home/andy/turbine-backups/pre-deploy-20261025-094452/`
  - `turbine-new-full.tar.gz` — full tar of the then-live
    `/home/andy/turbine-new` (code + `.env`, perms preserved via
    `--numeric-owner`), sha256
    `3d9b3e6431f9e278495dd64325106347b2c7819175cfb6c9d26bf71fa95074ef`.
  - `turbine.service.orig` — exact copy of the original unit file.
  - `metadata.txt` — PID/HEAD/paths at backup time.
  - `rollback.sh` (mode 700) — removes the drop-in override, restores the
    original unit file, `daemon-reload` + `restart`. Bash-syntax-validated
    (`bash -n`) before any live switch.
- Original release dir `/home/andy/turbine-new` (HEAD
  `fcf0a445885e809629598716a0396d2a94e9b080`, same commit as PR base) was
  **never modified**; the live `turbine-new` Python venv
  (`/home/andy/.pyenv/versions/turbine-new`, Python 3.10.4) was reused
  unchanged — `requirements.txt` is byte-identical between the old and new
  release, so no new dependencies were installed.

## Staged new release

- `/home/andy/turbine-new-aa79bfe5` — fresh clone of
  `https://github.com/beezly/turbine.git`, checked out at merge commit
  `aa79bfe5c67479b13852bc20d09ee942c3d815e3`; `.env` copied in with original
  `600 andy:andy` permissions (not displayed/exfiltrated).
- Offline verification before switch: `py_compile` of `mnet.py` and
  `turbine_monitor.py` succeeded; AST-parse of `turbine_monitor.py` succeeded;
  `import mnet` succeeded standalone (no monitor/hardware instantiation).

## Switch and live verification

- Switch mechanism: systemd drop-in
  `/etc/systemd/system/turbine.service.d/10-release-override.conf`
  overriding only `WorkingDirectory`/`ExecStart` to the new release dir
  (`systemd-analyze verify turbine.service` clean before restart).
  `turbine.service` was restarted (not the controller) — `KillMode=process`,
  no other process signalled.
- Immediately after restart (new PID 27976, single instance confirmed via
  `pgrep`): read-only `/api/read` probes for wind speed (`id=9c43`) and grid
  power (`id=9cac`) returned fresh, varying, plausible values (17.0, 17.0,
  13.0, 18.0 — consistent with pre-deploy baseline 14.0/12.0/17.0) over
  multiple successive timestamped reads; `NRestarts=0`; UI root returned
  HTTP 200.
- **Discovered incompatibility**: within ~10s, the service's periodic
  re-login path (`_login_to_turbine` / `_reconnect_device`, unrelated to the
  manual `/api/read` probe path) began failing repeatedly:
  `MnetDecodeError: response packet type mismatch: expected one of
  {0x1390, 0x13a1}, got 0x0001`. The live controller sometimes replies to a
  login request (`REQ_LOGIN`/`0x13A1`) with packet type `0x0001`, which is
  not in the new strict `REQUEST_RESPONSE_TYPES` allow-list for logins
  (`docs/MNET.md` only documents echo-on-success or `0x1390` on rejection).
  This is a real, hardware-observed protocol behavior not covered by the
  PR's validation map — a concrete, evidence-backed incompatibility, not a
  speculative concern.
- Because this caused a persistent reconnect/login failure loop (risking
  stalled MQTT publishing even though direct serial reads still worked), the
  prepared rollback was invoked immediately per the mandatory safety rule.

## Rollback executed

- Command: `/home/andy/turbine-backups/pre-deploy-20261025-094452/rollback.sh`
  (exact manual command for any future rollback of this deploy).
- Result: drop-in removed, original unit restored
  (`diff` against backup confirms byte-identical), `daemon-reload` +
  `restart` run. New PID 28099, working dir confirmed
  `/home/andy/turbine-new` (original, untouched release/venv).
- Post-rollback live verification: `/api/read` for wind speed returned
  fresh varying values (17.0, 14.0, 21.0) over successive reads; journal
  showed zero errors in the post-rollback window.

## Current state

- **Live `turbinepi` is running the original, pre-merge code**
  (`fcf0a445885e809629598716a0396d2a94e9b080`) — intentionally, due to the
  login-reply incompatibility above. The PR is merged to `master` on GitHub,
  but the live deployment was rolled back and was not left on the new code.
- Original venv, `.env`, and unit file are unchanged.
- Staged new release dir `/home/andy/turbine-new-aa79bfe5` and the
  pre-deploy backup are left on `turbinepi` for forensics/retry.
- No turbine control commands (start/stop/reset/ack/time/manual) were sent
  at any point; only read-only data probes were used for verification.

## Follow-up required before any future deploy of this code

The login packet-type allow-list in `mnet.py`
(`REQUEST_RESPONSE_TYPES[REQ_LOGIN]` / `REQUEST_RESPONSE_TYPES[REQ_LOGIN_STANDARD]`)
needs to account for the observed `0x0001` reply, confirmed against real
hardware logs/behavior (not guessed), before this fix is redeployed live.

## Follow-up fix (same day, separate PR — not pushed directly to master)

Root-cause finding, from offline inspection of the real controller
traceback and `docs/MNET.md` (no live hardware re-tested; no command
API calls made):

- The pre-PR `mnet.py` performed **no reply-type validation at all** in
  `send_packet` — it accepted whatever packet type came back for any
  request, including logins. That is why hidden-login-based monitoring
  had always worked against this controller despite it replying 0x0001
  to login.
- The failing traceback showed the 0x0001 reply passing the new
  `send_packet`'s source/destination identity checks (it was correctly
  addressed from the controller back to the client) and never the
  documented `0x1390` ("Remote not logged in") rejection, across five
  separate reconnect attempts in the 09:45:46–09:46:38 window. That is
  hardware-observed evidence of a controller-specific behavior, not a
  one-off desync/corruption artifact (a desync would also be expected to
  surface as a source/destination mismatch or a frame/CRC error, which
  did not occur) — treated per the mandatory rule as evidence, not
  inference.
- `docs/MNET.md` documents `0x0001` only as the generic "Reply
  Acknowledge" type (e.g. for Acknowledge alarm / `0x0BEA`), not as a
  documented login reply. No raw hex of the actual 0x0001 frame was
  captured (the `_log_callback` in the new `mnet.py` only fires *after*
  the type-validation that raised, so the exception's text summary is
  the only available artifact) — this is acknowledged as a gap, not
  papered over.
- Fix applied: `REQUEST_RESPONSE_TYPES[REQ_LOGIN]` (hidden login, 0x13A1
  only) now also accepts `0x0001` as a valid success reply, in addition
  to the documented 0x13A1 echo and the 0x1390 rejection.
  `REQUEST_RESPONSE_TYPES[REQ_LOGIN_STANDARD]` (control login, 0x138E)
  was deliberately **left unchanged/strict** — there is no hardware
  evidence for how this controller answers a standard/control login, and
  control commands were never exercised live, so widening that mapping
  would be an unverified guess.
- Added `tests/test_login_ack_quirk.py` (9 new offline tests, mocked
  in-memory serial device, no hardware): valid-ACK accepted for hidden
  login, documented echo still accepted, documented negative (0x1390)
  still raises `MnetLoginRejectedError`, an unrelated wrong type still
  raises, a corrupted-CRC frame still raises `MnetFrameError` even when
  the (corrupted) type would otherwise match, the standard login does
  **not** inherit the 0x0001 allowance, and 0x0001 is **not** treated as
  a universal "ignore the request type" success code for non-login
  requests (e.g. `REQ_DATA`).
- Full suite after the change: `172 passed, 33 skipped` (163 prior +
  9 new; 33 skipped matches the pre-existing baseline — no regressions).
- PR: see `docs/DEPLOYMENT_REPORT_2026-10-25.md` update / PR link
  recorded below once opened. Pushed as a feature branch and opened as a
  normal PR — **not** pushed directly to `master` (unlike this file's
  earlier update, which the prior agent pushed directly and should not
  be repeated).

### Live redeploy status

Not attempted as part of this follow-up. Per the mandatory safety rule,
a fix is landed via reviewed PR first; a fresh, independently backed-up
deploy attempt (new backup dir, new rollback script, same bounded
read-only verification protocol as above) is left for a separate,
explicit deploy step after this PR merges. Live `turbinepi` remains on
the original pre-merge code (`fcf0a445885e809629598716a0396d2a94e9b080`,
PID 28099 at report time), unchanged, with zero errors in the journal
since the rollback.

## Live redeploy — successful, after PR #2 merge

- PR: https://github.com/beezly/turbine/pull/2 (merge commit `0214f17`,
  head `782c22e`) — merged normally, no direct push to `master`.
- New backup dir on `turbinepi`:
  `/home/andy/turbine-backups/pre-deploy-20261025-095441/`
  (`turbine-new-full.tar.gz` sha256
  `3d9b3e6431f9e278495dd64325106347b2c7819175cfb6c9d26bf71fa95074ef`,
  identical content to the earlier backup since `/home/andy/turbine-new`
  was never modified; `turbine.service.orig`; `metadata.txt`;
  `rollback.sh`, mode 700, `bash -n` syntax-validated).
  Exact rollback command if ever needed:
  `/home/andy/turbine-backups/pre-deploy-20261025-095441/rollback.sh`
  (removes the drop-in override, `daemon-reload`, `restart` — restores
  original `/home/andy/turbine-new`, unchanged venv/`.env`/unit).
- Staged new release: `/home/andy/turbine-new-0214f17` (fresh clone,
  checked out at merge commit `0214f17`; `.env` copied in at `600`
  perms; `requirements.txt` byte-identical to the old release, so no
  new dependencies installed/reviewed). Offline-verified first:
  `py_compile` of `mnet.py`/`turbine_monitor.py` and `import mnet`
  succeeded using the existing `turbine-new` pyenv (Python 3.10.4) —
  same unchanged venv reused for both releases.
- Switch: same systemd drop-in mechanism as the earlier attempt
  (`/etc/systemd/system/turbine.service.d/10-release-override.conf`,
  overriding only `WorkingDirectory`/`ExecStart`); `systemd-analyze
  verify turbine.service` clean before restart; `turbine.service`
  restarted (not the controller).
- **Live verification (automatic polling, not just one-shot `/api/read`
  success):** polled `/api/read` for wind speed (`id=9c43`) and grid
  power (`id=9cac`) every ~6-7s across 6 cycles over the restart plus a
  continued journal review spanning **~73s** total
  (09:54:49 restart → 09:56:02). Wind speed values were fresh and
  varying across cycles (10.0, 16.0, 11.0, 20.0, 20.0, 18.0); grid power
  read a steady -3.0 across the same cycles (plausible at the observed
  low/variable wind speed — not itself proof of freshness, but
  corroborated by the wind-speed variation and by zero decode/connection
  errors on every read in between). `NRestarts=0` throughout; UI root
  returned HTTP 200; MQTT connected successfully
  (`"MQTT connected"` in the journal) and the command topic was
  subscribed — no control/command API calls were made, this is only the
  startup subscribe.
- **Journal, full window since restart:** zero `MnetDecodeError`, zero
  "Reconnection failed", zero tracebacks — the periodic hidden-login
  path that previously failed within ~10s (see the "Discovered
  incompatibility" section above) completed cleanly on both the initial
  login and the scheduled controller time-sync
  ("Syncing controller time to UTC" / "Controller time synced
  successfully" — a routine clock-sync write the monitor performs on
  every startup, not an operator-issued control command). No
  start/stop/reset/ack/manual-override commands were sent.
- **Outcome: fix confirmed working on real hardware.** Live `turbinepi`
  is now running the merged fix
  (`turbine-new-0214f17`, PID 28480 at verification time) with a fresh,
  validated, immediately-usable rollback path if ever needed.
