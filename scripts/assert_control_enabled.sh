#!/bin/bash
# Post-deploy assertion: the turbine service MUST have started with control
# enabled (TURBINE_CONTROL_PASSWORD set). A deploy that silently degrades
# the control path to read-only is a FAILED deploy, not a success -- this
# script exists so that failure is loud, automatic, and checked every time,
# instead of relying on someone noticing greyed-out buttons in the UI.
#
# This checks the startup log line turbine_monitor.py already prints
# ("Control: ENABLED (password set)" vs "Control: disabled (read-only...)"),
# never the secret value itself, and never exercises a live control (no
# Start/Stop/Reset/Manual request is sent).
#
# Usage: assert_control_enabled.sh [service_name] [max_wait_seconds]
# Exit 0 = control confirmed enabled. Exit 1 = assertion failed (abort the
# deploy / trigger rollback). Exit 2 = could not determine in time.
set -uo pipefail

SERVICE="${1:-turbine.service}"
MAX_WAIT="${2:-20}"

echo "Asserting '${SERVICE}' started with control enabled (max ${MAX_WAIT}s)..."

elapsed=0
while [ "${elapsed}" -lt "${MAX_WAIT}" ]; do
    # Only look at log lines emitted after the current MainPID's start, so a
    # stale "ENABLED" line from a PREVIOUS run can't false-pass this check.
    since_ts="$(systemctl show "${SERVICE}" -p ExecMainStartTimestamp --value 2>/dev/null)"
    if [ -n "${since_ts}" ]; then
        log_tail="$(journalctl -u "${SERVICE}" --no-pager --since "${since_ts}" 2>/dev/null | grep -E '^.*Control: (ENABLED|disabled)' | tail -1)"
    else
        log_tail=""
    fi

    if echo "${log_tail}" | grep -q 'Control: ENABLED (password set)'; then
        echo "PASS: ${log_tail}"
        exit 0
    fi

    if echo "${log_tail}" | grep -q 'Control: disabled'; then
        echo "FAIL: service started but control is DISABLED (read-only)." >&2
        echo "      Log line: ${log_tail}" >&2
        echo "      This means TURBINE_CONTROL_PASSWORD was not set in the" >&2
        echo "      process environment at startup -- check the systemd" >&2
        echo "      drop-in's EnvironmentFile= path and permissions." >&2
        exit 1
    fi

    sleep 1
    elapsed=$((elapsed + 1))
done

echo "FAIL: no 'Control: ENABLED/disabled' log line seen within ${MAX_WAIT}s; cannot confirm control state." >&2
exit 2
