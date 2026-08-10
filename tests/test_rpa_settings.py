from __future__ import annotations

from pathlib import Path

import pytest

from configuration import Config
from rpa.settings import load_rpa_settings


WEIXIN = {
    "exe": "C:/Weixin/Weixin.exe",
    "decrypted_db_path": "C:/tmp/contact.db",
}


def test_enabled_requires_environment_key():
    with pytest.raises(ValueError, match="WECHAT_RPA_API_KEY"):
        load_rpa_settings({"enabled": True}, WEIXIN, {})


def test_defaults_are_loopback_and_filehelper_only():
    settings = load_rpa_settings(
        {"enabled": True}, WEIXIN, {"WECHAT_RPA_API_KEY": "secret"}
    )

    assert settings.host == "127.0.0.1"
    assert settings.allowed_recipients == frozenset({"filehelper"})
    assert settings.api_key == "secret"
    assert settings.weixin_exe == Path("C:/Weixin/Weixin.exe")
    assert settings.decrypted_db_path == Path("C:/tmp/contact.db")


def test_rejects_non_loopback_host():
    with pytest.raises(ValueError, match="127.0.0.1"):
        load_rpa_settings(
            {"host": "0.0.0.0"}, WEIXIN, {"WECHAT_RPA_API_KEY": "secret"}
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"allowed_recipients": []},
        {"allowed_recipients": ["filehelper", ""]},
        {"allowed_recipients": "filehelper"},
    ],
)
def test_rejects_invalid_recipient_allowlist(raw):
    with pytest.raises(ValueError, match="allowed_recipients"):
        load_rpa_settings(raw, WEIXIN, {"WECHAT_RPA_API_KEY": "secret"})


@pytest.mark.parametrize(
    ("field", "value"),
    [("port", 0), ("port", 65536), ("max_text_length", 0), ("idempotency_ttl_sec", 0)],
)
def test_rejects_unsafe_numeric_limits(field, value):
    with pytest.raises(ValueError):
        load_rpa_settings({field: value}, WEIXIN, {"WECHAT_RPA_API_KEY": "secret"})


def test_config_exposes_rpa_section(monkeypatch):
    config = Config.__new__(Config)
    monkeypatch.setattr(
        config,
        "_load_config",
        lambda: {
            "logging": {"version": 1, "handlers": {}, "root": {"handlers": []}},
            "groups": {"enable": []},
            "news": {"receivers": []},
            "report_reminder": {"receivers": []},
            "weixin": {},
            "rpa": {"enabled": False},
        },
    )

    config.reload()

    assert config.RPA == {"enabled": False}
