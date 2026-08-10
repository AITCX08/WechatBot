from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from queue import Queue
from threading import Event, Lock, Thread
from typing import Protocol


class TextSender(Protocol):
    def send_text(self, recipient: str, text: str) -> None: ...


class JobStatus(str, Enum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class SendRequest:
    request_id: str
    recipient: str
    text: str


@dataclass(frozen=True)
class JobSnapshot:
    request_id: str
    recipient: str
    status: JobStatus
    error_code: str | None
    updated_at: str


class SendQueue:
    """A single-worker send queue that deliberately never retains audit bodies."""

    def __init__(self, sender: TextSender, ttl_sec: int) -> None:
        self._sender = sender
        self._ttl_sec = ttl_sec
        self._work: Queue[SendRequest | None] = Queue()
        self._lock = Lock()
        self._stop_event = Event()
        self._snapshots: dict[str, JobSnapshot] = {}
        self._dedupe_expires_at: dict[str, float] = {}
        self._audit: list[dict[str, str | None]] = []
        self._worker = Thread(target=self._run, name="wechat-rpa-send-worker", daemon=True)
        self._worker.start()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def _record(self, snapshot: JobSnapshot) -> None:
        self._snapshots[snapshot.request_id] = snapshot
        self._audit.append(
            {
                "ts": snapshot.updated_at,
                "request_id": snapshot.request_id,
                "recipient": snapshot.recipient,
                "status": snapshot.status.value,
                "error_code": snapshot.error_code,
            }
        )

    def _make_snapshot(
        self, request: SendRequest, status: JobStatus, error_code: str | None = None
    ) -> JobSnapshot:
        return JobSnapshot(
            request_id=request.request_id,
            recipient=request.recipient,
            status=status,
            error_code=error_code,
            updated_at=self._now().isoformat(),
        )

    def _prune_expired_dedupe(self, now_ts: float) -> None:
        expired_ids = [
            request_id
            for request_id, expires_at in self._dedupe_expires_at.items()
            if expires_at <= now_ts
        ]
        for request_id in expired_ids:
            del self._dedupe_expires_at[request_id]

    def submit(self, request: SendRequest) -> tuple[bool, JobSnapshot]:
        if self._stop_event.is_set():
            raise RuntimeError("send queue is stopped")

        now = self._now()
        now_ts = now.timestamp()
        with self._lock:
            self._prune_expired_dedupe(now_ts)
            existing = self._snapshots.get(request.request_id)
            if request.request_id in self._dedupe_expires_at and existing is not None:
                return False, existing

            snapshot = JobSnapshot(
                request_id=request.request_id,
                recipient=request.recipient,
                status=JobStatus.QUEUED,
                error_code=None,
                updated_at=now.isoformat(),
            )
            self._dedupe_expires_at[request.request_id] = now_ts + self._ttl_sec
            self._record(snapshot)
            self._work.put(request)
            return True, snapshot

    def get(self, request_id: str) -> JobSnapshot | None:
        with self._lock:
            return self._snapshots.get(request_id)

    def audit_events(self) -> tuple[dict[str, str | None], ...]:
        with self._lock:
            return tuple(event.copy() for event in self._audit)

    def health(self) -> dict[str, object]:
        with self._lock:
            return {
                "status": "stopped" if self._stop_event.is_set() else "ok",
                "pending_jobs": self._work.unfinished_tasks,
                "known_jobs": len(self._snapshots),
            }

    def _run(self) -> None:
        while True:
            request = self._work.get()
            try:
                if request is None:
                    return
                self._process(request)
            finally:
                self._work.task_done()

    def _process(self, request: SendRequest) -> None:
        try:
            self._sender.send_text(request.recipient, request.text)
        except Exception:
            snapshot = self._make_snapshot(request, JobStatus.FAILED, "send_failed")
        else:
            snapshot = self._make_snapshot(request, JobStatus.SUCCEEDED)
        with self._lock:
            self._record(snapshot)

    def drain_for_test(self) -> None:
        """Wait for all currently submitted work; intended for deterministic tests."""
        self._work.join()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._work.put(None)
        self._worker.join(timeout=5)
