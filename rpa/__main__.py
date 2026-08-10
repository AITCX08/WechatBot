from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import uvicorn

from configuration import Config
from rpa.jobs import SendQueue
from rpa.sender import UiAutomationTextSender
from rpa.server import create_app
from rpa.settings import RpaSettings, load_rpa_settings


def build_runtime(
    rpa_raw: Mapping[str, Any] | None,
    weixin_raw: Mapping[str, Any] | None,
) -> tuple[RpaSettings, SendQueue, object]:
    """Build the service without launching, stopping, or restarting Weixin."""
    settings = load_rpa_settings(rpa_raw, weixin_raw, os.environ)
    if not settings.enabled:
        raise RuntimeError("rpa.enabled must be true before starting the local RPA service")

    sender = UiAutomationTextSender(settings.weixin_exe, settings.decrypted_db_path)
    queue = SendQueue(sender, settings.idempotency_ttl_sec)
    return settings, queue, create_app(settings, queue)


def main() -> None:
    config = Config()
    settings, queue, app = build_runtime(config.RPA, config.WEIXIN)
    try:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
    finally:
        queue.stop()


if __name__ == "__main__":
    main()
