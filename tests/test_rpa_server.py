from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rpa.jobs import SendQueue
from rpa.server import create_app
from rpa.settings import RpaSettings


class FakeSender:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def send_text(self, recipient: str, text: str) -> None:
        self.calls.append((recipient, text))


@pytest.fixture
def app_and_queue():
    settings = RpaSettings(
        enabled=True,
        host="127.0.0.1",
        port=9922,
        api_key="key",
        allowed_recipients=frozenset({"filehelper"}),
        max_text_length=20,
        idempotency_ttl_sec=300,
        weixin_exe=Path("C:/x"),
        decrypted_db_path=Path("C:/db"),
    )
    queue = SendQueue(FakeSender(), 300)
    try:
        yield create_app(settings, queue), queue
    finally:
        queue.stop()


def test_send_requires_api_key(app_and_queue):
    app, _ = app_and_queue
    response = TestClient(app).post(
        "/api/chat/send_message", json={"recipient": "filehelper", "text": "hi"}
    )

    assert response.status_code == 401


def test_send_rejects_non_allowlisted_recipient(app_and_queue):
    app, _ = app_and_queue
    response = TestClient(app).post(
        "/api/chat/send_message",
        headers={"X-API-Key": "key"},
        json={"recipient": "other", "text": "hi"},
    )

    assert response.status_code == 403


def test_accepted_response_does_not_echo_body(app_and_queue):
    app, _ = app_and_queue
    response = TestClient(app).post(
        "/api/chat/send_message",
        headers={"X-API-Key": "key"},
        json={"request_id": "r1", "recipient": "filehelper", "text": "private"},
    )

    assert response.status_code == 202
    assert response.json()["request_id"] == "r1"
    assert "private" not in response.text


def test_blank_or_oversized_text_is_rejected(app_and_queue):
    app, _ = app_and_queue
    client = TestClient(app)
    headers = {"X-API-Key": "key"}

    blank = client.post(
        "/api/chat/send_message",
        headers=headers,
        json={"recipient": "filehelper", "text": "  "},
    )
    oversized = client.post(
        "/api/chat/send_message",
        headers=headers,
        json={"recipient": "filehelper", "text": "x" * 21},
    )

    assert blank.status_code == 422
    assert oversized.status_code == 422


def test_job_lookup_exposes_only_safe_snapshot_fields(app_and_queue):
    app, queue = app_and_queue
    client = TestClient(app)
    client.post(
        "/api/chat/send_message",
        headers={"X-API-Key": "key"},
        json={"request_id": "safe-job", "recipient": "filehelper", "text": "private"},
    )
    queue.drain_for_test()

    response = client.get("/api/jobs/safe-job", headers={"X-API-Key": "key"})

    assert response.status_code == 200
    assert set(response.json()) == {
        "request_id",
        "recipient",
        "status",
        "error_code",
        "updated_at",
    }
    assert "private" not in response.text


def test_health_is_unauthenticated_and_safe(app_and_queue):
    app, _ = app_and_queue
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_disabled_service_refuses_to_build_runtime(monkeypatch):
    from rpa.__main__ import build_runtime

    monkeypatch.setenv("WECHAT_RPA_API_KEY", "key")

    with pytest.raises(RuntimeError, match="rpa.enabled"):
        build_runtime(
            {"enabled": False},
            {"exe": "C:/x", "decrypted_db_path": "C:/db"},
        )


def test_runtime_uses_validated_loopback_settings_without_running_uvicorn(monkeypatch):
    from rpa import __main__ as entrypoint

    class StubSender:
        def __init__(self, weixin_exe, db_path):
            self.weixin_exe = weixin_exe
            self.db_path = db_path

        def send_text(self, recipient, text):
            pass

    monkeypatch.setattr(entrypoint, "UiAutomationTextSender", StubSender)
    monkeypatch.setenv("WECHAT_RPA_API_KEY", "key")

    settings, queue, app = entrypoint.build_runtime(
        {"enabled": True},
        {"exe": "C:/x", "decrypted_db_path": "C:/db"},
    )
    try:
        assert settings.host == "127.0.0.1"
        assert app.title == "WeChatRobot Local RPA"
    finally:
        queue.stop()
