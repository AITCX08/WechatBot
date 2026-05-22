from __future__ import annotations
import logging
import time

from dashboard.state import get_state


class RingBufferHandler(logging.Handler):
    """logging.Handler that pushes formatted records into BotState.logs."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            state = get_state()
            entry = {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
            }
            state.logs.append(entry)
        except Exception:
            # Never let logging crash the bot
            pass


def install(root_level: int = logging.INFO) -> None:
    """Idempotently install the ring buffer handler on the root logger."""
    root = logging.getLogger()
    if any(isinstance(h, RingBufferHandler) for h in root.handlers):
        return
    h = RingBufferHandler()
    h.setLevel(root_level)
    h.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(h)
    if root.level > root_level or root.level == 0:
        root.setLevel(root_level)
