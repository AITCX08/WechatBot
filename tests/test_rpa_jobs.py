from __future__ import annotations

import threading

from rpa.jobs import JobStatus, SendQueue, SendRequest


class FakeSender:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def send_text(self, recipient: str, text: str) -> None:
        with self._lock:
            self.calls.append((recipient, text))


def test_duplicate_id_runs_once():
    sender = FakeSender()
    queue = SendQueue(sender, ttl_sec=300)
    try:
        request = SendRequest("r1", "filehelper", "private message")

        accepted, _ = queue.submit(request)
        duplicated, snapshot = queue.submit(request)
        queue.drain_for_test()

        assert accepted is True
        assert duplicated is False
        assert snapshot.request_id == "r1"
        assert sender.calls == [("filehelper", "private message")]
        assert queue.get("r1").status is JobStatus.SUCCEEDED
    finally:
        queue.stop()


def test_audit_excludes_message_body():
    sender = FakeSender()
    queue = SendQueue(sender, ttl_sec=300)
    try:
        queue.submit(SendRequest("r2", "filehelper", "must not be logged"))
        queue.drain_for_test()

        audit = queue.audit_events()
        snapshot = queue.get("r2")

        assert "must not be logged" not in repr(audit)
        assert snapshot.status is JobStatus.SUCCEEDED
        assert set(audit[0]) == {"ts", "request_id", "recipient", "status", "error_code"}
    finally:
        queue.stop()


def test_sender_failure_is_recorded_without_retry():
    class FailingSender:
        def __init__(self):
            self.calls = 0

        def send_text(self, recipient: str, text: str) -> None:
            self.calls += 1
            raise RuntimeError("window unavailable")

    sender = FailingSender()
    queue = SendQueue(sender, ttl_sec=300)
    try:
        queue.submit(SendRequest("r3", "filehelper", "private message"))
        queue.drain_for_test()

        snapshot = queue.get("r3")
        assert sender.calls == 1
        assert snapshot.status is JobStatus.FAILED
        assert snapshot.error_code == "send_failed"
    finally:
        queue.stop()


def test_health_does_not_expose_message_content():
    sender = FakeSender()
    queue = SendQueue(sender, ttl_sec=300)
    try:
        queue.submit(SendRequest("r4", "filehelper", "not visible in health"))
        assert "not visible in health" not in repr(queue.health())
    finally:
        queue.stop()
