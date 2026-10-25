"""Bounded, serialized command dispatcher for turbine control commands.

Single submission path for all callers (MQTT, HTTP, Socket.IO). Replaces the
old shared `pending_command` / `pending_command_name` fields with an
immutable CommandRequest flowing through one FIFO queue, protected by a
single lock, with a bounded dedupe cache and explicit expiry handling.

Design notes / honest limitations:
- Expiry for legacy callers (plain MQTT payload, bare socket command) is
  measured from RECEIVE time, not original send time, because legacy
  payloads carry no timestamp. This is a real limitation, not a full
  "don't execute stale intents" guarantee -- see docs/command-dispatcher.md.
- A command transitions to UNKNOWN (never "cancelled" and never assumed
  successful) once it has been dispatched to the serial/mnet executor and a
  client-side timeout fires before a result is observed. We do not resend.
- No new required fields: legacy plain-text payloads/commands keep working
  with internally generated request ids. An optional JSON envelope lets a
  caller supply its own request_id/expiry for dedup purposes only; it never
  changes required behavior for legacy callers.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional


class CommandState(str, Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class DispatchError(Exception):
    """Raised for synchronous rejection at submit time (not queued)."""

    def __init__(self, reason: str, http_status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.http_status = http_status


@dataclass(frozen=True)
class CommandRequest:
    """Immutable description of one requested control command."""

    id: str
    source: str  # 'mqtt' | 'http' | 'socket'
    name: str
    received_at: float  # time.monotonic() at receipt
    expiry: Optional[float]  # absolute time.monotonic() deadline, or None
    client_request_id: Optional[str] = None  # caller-supplied id, if any (dedupe only)

    def is_expired(self, now: Optional[float] = None) -> bool:
        if self.expiry is None:
            return False
        return (now if now is not None else time.monotonic()) >= self.expiry


@dataclass
class CommandRecord:
    """Mutable bookkeeping the dispatcher owns for one request's lifecycle."""

    request: CommandRequest
    state: CommandState = CommandState.QUEUED
    result: Optional[Dict[str, Any]] = None
    queued_at: float = field(default_factory=time.monotonic)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_result_dict(self) -> Dict[str, Any]:
        return {
            "id": self.request.id,
            "source": self.request.source,
            "command": self.request.name,
            "state": self.state.value,
            "received_at": self.request.received_at,
            "queued_at": self.queued_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            **({"reason": self.result.get("reason")} if self.result and "reason" in self.result else {}),
            **({"reply": self.result.get("reply")} if self.result and "reply" in self.result else {}),
        }


class CommandDispatcher:
    """Single serialized entry point for all control-command submissions.

    Owns one FIFO queue plus a worker that drains it one command at a time
    (the mnet serial link is inherently single-command-at-a-time anyway).
    Callers from MQTT/HTTP/Socket.IO all call `submit()`; nothing else is
    allowed to touch the queue or set a "pending command" directly.
    """

    def __init__(
        self,
        command_map: Dict[str, Any],
        executor: Callable[[CommandRequest], Dict[str, Any]],
        *,
        max_queue: int = 8,
        default_ttl: float = 30.0,
        dedupe_cache_size: int = 256,
        on_result: Optional[Callable[[CommandRecord], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._command_map = command_map
        self._executor = executor
        self._max_queue = max_queue
        self._default_ttl = default_ttl
        self._on_result = on_result
        self._clock = clock

        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._queue: "deque[CommandRecord]" = deque()
        self._records: "OrderedDict[str, CommandRecord]" = OrderedDict()
        self._dedupe_cache_size = dedupe_cache_size
        # client_request_id -> our internal id, bounded FIFO
        self._dedupe: "OrderedDict[str, str]" = OrderedDict()

        self._shutdown = False
        self._worker: Optional[threading.Thread] = None

    # ---- lifecycle -----------------------------------------------------
    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._shutdown = False
        self._worker = threading.Thread(target=self._run, name="command-dispatcher", daemon=True)
        self._worker.start()

    def stop(self, timeout: float = 5.0):
        with self._lock:
            self._shutdown = True
            self._not_empty.notify_all()
        if self._worker:
            self._worker.join(timeout=timeout)

    # ---- submission (the ONE path for every interface) ------------------
    def submit(
        self,
        name: str,
        source: str,
        *,
        client_request_id: Optional[str] = None,
        ttl: Optional[float] = None,
        retained: bool = False,
    ) -> CommandRecord:
        """Validate, dedupe, and enqueue one command request.

        Raises DispatchError for synchronous rejects (unknown command,
        retained message, queue full). Returns the CommandRecord otherwise
        (state QUEUED, or REJECTED/EXPIRED if dedupe/expiry fired inline).
        """
        name = (name or "").strip().lower()
        if retained:
            raise DispatchError(
                "retained command messages are refused before queueing "
                "(a retained message is a stale historical intent, not a live request)",
                http_status=400,
            )
        if name not in self._command_map:
            raise DispatchError(f"unknown command: {name!r}", http_status=400)

        now = self._clock()
        with self._lock:
            if self._shutdown:
                raise DispatchError("dispatcher is shutting down", http_status=503)

            if client_request_id is not None:
                existing_id = self._dedupe.get(client_request_id)
                if existing_id is not None and existing_id in self._records:
                    return self._records[existing_id]

            if len(self._queue) >= self._max_queue:
                raise DispatchError(
                    f"command queue full ({self._max_queue} pending); try again shortly",
                    http_status=429,
                )

            req_id = str(uuid.uuid4())
            expiry = now + ttl if ttl else (now + self._default_ttl if self._default_ttl else None)
            request = CommandRequest(
                id=req_id,
                source=source,
                name=name,
                received_at=now,
                expiry=expiry,
                client_request_id=client_request_id,
            )
            record = CommandRecord(request=request)

            # Expiry check #1: at enqueue time (covers e.g. a caller-supplied
            # ttl of 0, or a clock already past an explicit deadline).
            if request.is_expired(now):
                record.state = CommandState.EXPIRED
                record.finished_at = now
                self._records[req_id] = record
                self._trim_records()
                return record

            self._records[req_id] = record
            self._queue.append(record)
            if client_request_id is not None:
                self._dedupe[client_request_id] = req_id
                while len(self._dedupe) > self._dedupe_cache_size:
                    self._dedupe.popitem(last=False)
            self._trim_records()
            self._not_empty.notify_all()
            return record

    def cancel(self, request_id: str) -> bool:
        """Cancel a QUEUED (not yet started) command. Returns True if cancelled.

        A command already EXECUTING cannot be cancelled -- we never claim to
        stop something already sent to the controller.
        """
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.state != CommandState.QUEUED:
                return False
            try:
                self._queue.remove(record)
            except ValueError:
                return False
            record.state = CommandState.CANCELLED
            record.finished_at = self._clock()
            return True

    def get(self, request_id: str) -> Optional[CommandRecord]:
        with self._lock:
            return self._records.get(request_id)

    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    def _trim_records(self, keep: int = 512):
        while len(self._records) > keep:
            self._records.popitem(last=False)

    # ---- worker ----------------------------------------------------------
    def _run(self):
        while True:
            with self._lock:
                while not self._queue and not self._shutdown:
                    self._not_empty.wait(timeout=1.0)
                if self._shutdown and not self._queue:
                    return
                if not self._queue:
                    continue
                record = self._queue.popleft()

                now = self._clock()
                # Expiry check #2: immediately before transmission. A command
                # that sat in the queue past its deadline is NEVER executed.
                if record.request.is_expired(now):
                    record.state = CommandState.EXPIRED
                    record.finished_at = now
                    self._emit_result(record)
                    continue

                if record.state == CommandState.CANCELLED:
                    continue  # cancelled while sitting in the deque snapshot

                record.state = CommandState.EXECUTING
                record.started_at = now

            # Executor runs OUTSIDE the dispatcher lock (it holds the serial
            # lock itself) so a slow/hung serial exchange cannot block new
            # submissions or expiry bookkeeping for unrelated commands.
            try:
                result = self._executor(record.request)
                with self._lock:
                    record.result = result
                    record.state = (
                        CommandState.ACKNOWLEDGED if result.get("ok") else CommandState.REJECTED
                    )
                    record.finished_at = self._clock()
            except TimeoutError as exc:
                # Sent (or ambiguous whether sent) + no confirmed reply before
                # our own timeout: outcome is UNKNOWN, never "success" and
                # never auto-retried/resent.
                with self._lock:
                    record.result = {"ok": False, "reason": f"timeout: {exc}"}
                    record.state = CommandState.UNKNOWN
                    record.finished_at = self._clock()
            except Exception as exc:  # pragma: no cover - defensive
                with self._lock:
                    record.result = {"ok": False, "reason": f"error: {exc}"}
                    record.state = CommandState.REJECTED
                    record.finished_at = self._clock()

            self._emit_result(record)

    def _emit_result(self, record: CommandRecord):
        if self._on_result:
            try:
                self._on_result(record)
            except Exception:
                pass


def parse_envelope(raw: str) -> Dict[str, Optional[str]]:
    """Parse a legacy plain-text or optional-JSON command payload.

    Legacy behavior is preserved exactly: a bare string like "start" or
    "STOP" (any case/whitespace) is the command name, no envelope required.
    Optionally, a JSON object may be sent instead:
        {"command": "start", "request_id": "...", "ttl": 30}
    This is purely additive -- callers that never send JSON are unaffected.
    """
    text = raw.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "command" in data:
                return {
                    "name": str(data.get("command", "")).strip().lower(),
                    "request_id": data.get("request_id"),
                    "ttl": data.get("ttl"),
                }
        except (json.JSONDecodeError, TypeError):
            pass
    # Fallback: legacy bare command string.
    return {"name": text.strip().lower(), "request_id": None, "ttl": None}
