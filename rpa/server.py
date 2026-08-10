from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from rpa.jobs import JobSnapshot, SendQueue, SendRequest
from rpa.settings import RpaSettings


class SendMessageBody(BaseModel):
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    recipient: str = Field(min_length=1, max_length=256)
    text: str


def _safe_snapshot(snapshot: JobSnapshot) -> dict[str, str | None]:
    return {
        "request_id": snapshot.request_id,
        "recipient": snapshot.recipient,
        "status": snapshot.status.value,
        "error_code": snapshot.error_code,
        "updated_at": snapshot.updated_at,
    }


def create_app(settings: RpaSettings, queue: SendQueue) -> FastAPI:
    """Build the HTTP surface for the local-only RPA process."""
    app = FastAPI(title="WeChatRobot Local RPA", version="1.0")

    def require_api_key(
        api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> None:
        if not api_key or not secrets.compare_digest(api_key, settings.api_key):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid API key",
            )

    @app.get("/health")
    def health() -> dict[str, object]:
        return queue.health()

    @app.post(
        "/api/chat/send_message",
        status_code=status.HTTP_202_ACCEPTED,
        dependencies=[],
    )
    def send_message(
        body: SendMessageBody,
        api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> dict[str, str]:
        require_api_key(api_key)
        if body.recipient not in settings.allowed_recipients:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="recipient is not allowlisted",
            )
        if not body.text.strip() or len(body.text) > settings.max_text_length:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="text must be non-blank and within the configured length limit",
            )

        request_id = body.request_id or uuid.uuid4().hex
        _, snapshot = queue.submit(
            SendRequest(request_id=request_id, recipient=body.recipient, text=body.text)
        )
        return {"request_id": snapshot.request_id, "status": snapshot.status.value}

    @app.get("/api/jobs/{request_id}")
    def get_job(
        request_id: str,
        api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> dict[str, str | None]:
        require_api_key(api_key)
        snapshot = queue.get(request_id)
        if snapshot is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
        return _safe_snapshot(snapshot)

    return app
