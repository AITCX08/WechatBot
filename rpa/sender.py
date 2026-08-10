from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Protocol

from wx.contacts import ContactsBackend
from wx.send import SendBackend


class TextSender(Protocol):
    def send_text(self, recipient: str, text: str) -> None: ...


class UiAutomationTextSender:
    """Attach to an existing Weixin window and send one text message via UIA."""

    def __init__(
        self,
        weixin_exe: Path,
        db_path: Path,
        contacts: ContactsBackend | None = None,
        backend: SendBackend | None = None,
    ) -> None:
        self._contacts = contacts if contacts is not None else ContactsBackend(db_path)
        self._backend = (
            backend
            if backend is not None
            else SendBackend(weixin_exe=weixin_exe, contacts=self._contacts)
        )
        self._attached = False
        self._attach_lock = Lock()

    def _attach_once(self) -> None:
        if self._attached:
            return
        with self._attach_lock:
            if self._attached:
                return
            self._contacts.refresh()
            self._backend.attach()
            self._attached = True

    def send_text(self, recipient: str, text: str) -> None:
        self._attach_once()
        if not self._backend.send_text(recipient, text):
            raise RuntimeError("UIA send failed")
