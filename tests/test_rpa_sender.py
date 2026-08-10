from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from rpa.sender import UiAutomationTextSender


def test_sender_attaches_once_then_delegates():
    contacts = MagicMock()
    backend = MagicMock()
    backend.send_text.return_value = True
    sender = UiAutomationTextSender(
        Path("C:/Weixin.exe"), Path("C:/contact.db"), contacts, backend
    )

    sender.send_text("filehelper", "hello")
    sender.send_text("filehelper", "second message")

    contacts.refresh.assert_called_once_with()
    backend.attach.assert_called_once_with()
    assert backend.send_text.call_args_list[0].args == ("filehelper", "hello")
    assert backend.send_text.call_args_list[1].args == ("filehelper", "second message")


def test_sender_raises_on_backend_false():
    contacts = MagicMock()
    backend = MagicMock()
    backend.send_text.return_value = False
    sender = UiAutomationTextSender(
        Path("C:/Weixin.exe"), Path("C:/contact.db"), contacts, backend
    )

    with pytest.raises(RuntimeError, match="UIA send failed"):
        sender.send_text("filehelper", "hello")


def test_failed_initial_attach_is_retried_on_next_send():
    contacts = MagicMock()
    backend = MagicMock()
    backend.attach.side_effect = [RuntimeError("not logged in"), None]
    backend.send_text.return_value = True
    sender = UiAutomationTextSender(
        Path("C:/Weixin.exe"), Path("C:/contact.db"), contacts, backend
    )

    with pytest.raises(RuntimeError, match="not logged in"):
        sender.send_text("filehelper", "hello")
    sender.send_text("filehelper", "hello")

    assert contacts.refresh.call_count == 2
    assert backend.attach.call_count == 2
