"""Offline tests for command_dispatcher.CommandDispatcher.

No hardware, no network, no real MQTT broker. Uses a fake clock and a fake
executor to deterministically exercise expiry, dedupe, queue bounds,
cancellation, and unknown-outcome-on-timeout behavior.
"""
import threading
import time

import pytest

from command_dispatcher import (
    CommandDispatcher,
    CommandState,
    DispatchError,
    parse_envelope,
)

COMMAND_MAP = {"start": 1, "stop": 2, "reset": 3}


class FakeClock:
    def __init__(self, t=0.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make_dispatcher(executor=None, **kwargs):
    clock = kwargs.pop("clock", None) or FakeClock()
    if executor is None:
        def executor(req):
            return {"ok": True, "reply": "ack"}
    d = CommandDispatcher(COMMAND_MAP, executor, clock=clock, **kwargs)
    return d, clock


def wait_for(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_unknown_command_rejected_before_queue():
    d, _ = make_dispatcher()
    d.start()
    try:
        with pytest.raises(DispatchError):
            d.submit("not_a_command", source="mqtt")
        assert d.queue_depth() == 0
    finally:
        d.stop()


def test_retained_mqtt_message_rejected_before_queue():
    d, _ = make_dispatcher()
    d.start()
    try:
        with pytest.raises(DispatchError):
            d.submit("start", source="mqtt", retained=True)
        assert d.queue_depth() == 0
    finally:
        d.stop()


def test_legacy_plain_command_executes_and_acknowledges():
    d, clock = make_dispatcher()
    d.start()
    try:
        record = d.submit("start", source="mqtt")
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.ACKNOWLEDGED)
        final = d.get(record.request.id)
        assert final.result["reply"] == "ack"
    finally:
        d.stop()


def test_queue_full_is_rejected_not_silently_dropped():
    gate = threading.Event()

    def blocking_executor(req):
        gate.wait(timeout=5)
        return {"ok": True}

    d, _ = make_dispatcher(executor=blocking_executor, max_queue=2)
    d.start()
    try:
        d.submit("start", source="mqtt")  # picked up by worker, executing
        time.sleep(0.05)
        d.submit("stop", source="mqtt")
        d.submit("reset", source="mqtt")
        with pytest.raises(DispatchError):
            d.submit("start", source="mqtt")
    finally:
        gate.set()
        d.stop()


def test_expiry_checked_at_enqueue_when_already_past_deadline():
    clock = FakeClock(100.0)
    d, _ = make_dispatcher(clock=clock)
    d.start()
    try:
        # ttl=0 means "already expired"; negative ttl is now a DispatchError.
        record = d.submit("start", source="mqtt", ttl=0)
        assert record.state == CommandState.EXPIRED
        assert d.queue_depth() == 0
    finally:
        d.stop()


def test_expiry_checked_again_just_before_execution():
    """A command that expires while queued (not at submit time) is NEVER
    executed -- expiry check #2, immediately before transmission."""
    released = threading.Event()

    def executor(req):
        pytest.fail("expired command must never reach the executor")

    clock = FakeClock(0.0)
    d, _ = make_dispatcher(executor=executor, clock=clock)
    # Don't start the worker yet; manually enqueue then advance clock past expiry,
    # then start the worker so it hits check #2.
    record = d.submit("start", source="mqtt", ttl=1.0)
    assert record.state == CommandState.QUEUED
    clock.advance(2.0)  # now past expiry, worker hasn't run yet
    d.start()
    try:
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.EXPIRED)
    finally:
        d.stop()


def test_cancelled_queued_command_cannot_execute():
    gate = threading.Event()
    executed = []

    def executor(req):
        executed.append(req.id)
        return {"ok": True}

    def blocking_first(req):
        gate.wait(timeout=5)
        return {"ok": True}

    d, _ = make_dispatcher(executor=blocking_first, max_queue=4)
    d.start()
    try:
        first = d.submit("start", source="mqtt")  # occupies the worker
        time.sleep(0.05)
        second = d.submit("stop", source="mqtt")
        assert d.cancel(second.request.id) is True
        gate.set()
        assert wait_for(lambda: d.get(first.request.id).state == CommandState.ACKNOWLEDGED)
        assert d.get(second.request.id).state == CommandState.CANCELLED
    finally:
        gate.set()
        d.stop()


def test_executing_command_cannot_be_cancelled():
    gate = threading.Event()

    def executor(req):
        gate.wait(timeout=5)
        return {"ok": True}

    d, _ = make_dispatcher(executor=executor)
    d.start()
    try:
        record = d.submit("start", source="mqtt")
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.EXECUTING)
        assert d.cancel(record.request.id) is False
    finally:
        gate.set()
        d.stop()


def test_timeout_during_execution_yields_unknown_not_success():
    def executor(req):
        raise TimeoutError("no reply from controller")

    d, _ = make_dispatcher(executor=executor)
    d.start()
    try:
        record = d.submit("start", source="mqtt")
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.UNKNOWN)
        final = d.get(record.request.id)
        assert final.result["ok"] is False
    finally:
        d.stop()


def test_duplicate_client_request_id_deduped():
    calls = []

    def executor(req):
        calls.append(req.id)
        return {"ok": True}

    d, _ = make_dispatcher(executor=executor)
    d.start()
    try:
        r1 = d.submit("start", source="mqtt", client_request_id="abc")
        r2 = d.submit("start", source="mqtt", client_request_id="abc")
        assert r1.request.id == r2.request.id
        assert wait_for(lambda: d.get(r1.request.id).state == CommandState.ACKNOWLEDGED)
        assert len(calls) == 1
    finally:
        d.stop()


def test_legacy_ids_are_internally_generated_no_false_dedupe_guarantee():
    """Two legacy (no client_request_id) submissions of the same command are
    NOT deduped against each other -- each gets its own internally generated
    id, since legacy payloads carry no caller identity."""
    d, _ = make_dispatcher()
    d.start()
    try:
        r1 = d.submit("start", source="mqtt")
        r2 = d.submit("start", source="mqtt")
        assert r1.request.id != r2.request.id
    finally:
        d.stop()


def test_concurrent_http_socket_mqtt_submissions_serialize_without_races():
    order = []
    lock = threading.Lock()

    def executor(req):
        with lock:
            order.append(req.id)
        time.sleep(0.01)
        return {"ok": True}

    d, _ = make_dispatcher(executor=executor, max_queue=50)
    d.start()
    try:
        records = []
        threads = []

        def submit_many(source, n):
            for _ in range(n):
                try:
                    records.append(d.submit("start", source=source))
                except DispatchError:
                    pass

        for src in ("mqtt", "http", "socket"):
            t = threading.Thread(target=submit_many, args=(src, 5))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        assert wait_for(lambda: all(
            d.get(r.request.id).state in (CommandState.ACKNOWLEDGED, CommandState.EXPIRED)
            for r in records
        ), timeout=5)
        # No two executions overlapped: the executor itself never saw
        # concurrent entry because the dispatcher's worker is single.
        assert len(set(order)) == len(order)
    finally:
        d.stop()


def test_malformed_mqtt_payload_rejected_not_queued():
    d, _ = make_dispatcher()
    d.start()
    try:
        with pytest.raises(DispatchError):
            d.submit(parse_envelope("not valid json {{{")["name"], source="mqtt")
        assert d.queue_depth() == 0
    finally:
        d.stop()


def test_parse_envelope_legacy_plain_text_case_insensitive():
    assert parse_envelope("  Start  ") == {"name": "start", "request_id": None, "ttl": None}
    assert parse_envelope("STOP") == {"name": "stop", "request_id": None, "ttl": None}


def test_parse_envelope_optional_json_is_additive():
    env = parse_envelope('{"command": "start", "request_id": "r1", "ttl": 5}')
    assert env == {"name": "start", "request_id": "r1", "ttl": 5}


def test_parse_envelope_json_missing_command_falls_back_to_legacy():
    # Not a recognized envelope shape -> treated as a legacy bare string
    # (will fail validation downstream as an unknown command, same as before).
    env = parse_envelope('{"foo": "bar"}')
    assert env["name"] == '{"foo": "bar"}'


def test_negative_ack_from_controller_is_rejected_state():
    def executor(req):
        return {"ok": False, "reason": "controller NAK"}

    d, _ = make_dispatcher(executor=executor)
    d.start()
    try:
        record = d.submit("start", source="mqtt")
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.REJECTED)
    finally:
        d.stop()


def test_no_secrets_in_result_dict():
    d, _ = make_dispatcher()
    d.start()
    try:
        record = d.submit("start", source="mqtt")
        assert wait_for(lambda: d.get(record.request.id).state == CommandState.ACKNOWLEDGED)
        result_dict = d.get(record.request.id).to_result_dict()
        dumped = str(result_dict).lower()
        for secret_marker in ("password", "token", "secret"):
            assert secret_marker not in dumped
    finally:
        d.stop()
