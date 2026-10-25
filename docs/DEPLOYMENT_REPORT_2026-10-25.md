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
