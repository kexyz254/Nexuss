"""Bounded, session-scoped live progress. Durable receipts remain in interaction storage."""
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import RLock
import time

ProgressSink = Callable[[str, str, str], None]

_sink: ContextVar[ProgressSink | None] = ContextVar(
    "nexuss_progress_sink",
    default=None,
)
_recorder: ContextVar[ProgressSink | None] = ContextVar(
    "nexuss_progress_recorder",
    default=None,
)


def emit(event_type: str, state: str, detail: str) -> None:
    sink = _sink.get()
    if sink:
        sink(event_type, state, detail)
    recorder = _recorder.get()
    if recorder:
        recorder(event_type, state, detail)


@contextmanager
def recording(recorder: ProgressSink) -> Iterator[None]:
    token = _recorder.set(recorder)
    try:
        yield
    finally:
        _recorder.reset(token)


@contextmanager
def reporting(sink: ProgressSink) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


class ProgressHub:
    def __init__(self, capacity=256, ttl=1800):
        self.capacity, self.ttl = capacity, ttl
        self._runs = {}
        self._lock = RLock()

    def start(self, request_id, owner, conversation_id):
        with self._lock:
            now = time.monotonic()
            for key in list(self._runs):
                row = self._runs[key]
                if row["state"] != "running" and now - row["updated"] > self.ttl:
                    del self._runs[key]
            old = self._runs.get(request_id)
            if old:
                if old["owner"] != owner or old["conversation_id"] != conversation_id:
                    raise PermissionError("Progress belongs to another conversation")
                if old["state"] == "running":
                    raise RuntimeError("Request is already running")
            elif len(self._runs) >= self.capacity:
                finished = [(row["updated"], key) for key, row in self._runs.items() if row["state"] != "running"]
                if not finished:
                    raise RuntimeError("Progress capacity reached")
                del self._runs[min(finished)[1]]
            self._runs[request_id] = {"owner": owner, "conversation_id": conversation_id,
                "state": "running", "events": [], "sequence": 0, "updated": now}

    def append(self, request_id, event_type, state, detail):
        with self._lock:
            row = self._runs[request_id]
            row["sequence"] += 1
            row["events"].append({"sequence": row["sequence"], "event_type": event_type,
                "state": state, "detail": detail[:2000],
                "occurred_at": datetime.now(timezone.utc).isoformat()})
            row["events"] = row["events"][-200:]
            row["updated"] = time.monotonic()

    def finish(self, request_id, state):
        with self._lock:
            self._runs[request_id]["state"] = state
            self._runs[request_id]["updated"] = time.monotonic()

    def get(self, request_id, owner):
        with self._lock:
            row = self._runs.get(request_id)
            if row is None or row["owner"] != owner:
                raise LookupError("Progress not found")
            return {"request_id": str(request_id), "conversation_id": str(row["conversation_id"]),
                    "state": row["state"], "events": [dict(item) for item in row["events"]]}
