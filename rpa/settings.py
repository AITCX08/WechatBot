from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class RpaSettings:
    enabled: bool
    host: str
    port: int
    api_key: str
    allowed_recipients: frozenset[str]
    max_text_length: int
    idempotency_ttl_sec: int
    weixin_exe: Path
    decrypted_db_path: Path


def _positive_int(raw: Mapping[str, Any], name: str, default: int, maximum: int) -> int:
    value = raw.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"rpa.{name} must be an integer between 1 and {maximum}")
    return value


def _allowed_recipients(raw: Mapping[str, Any]) -> frozenset[str]:
    recipients = raw.get("allowed_recipients", ["filehelper"])
    if (
        not isinstance(recipients, list)
        or not recipients
        or not all(isinstance(item, str) and item.strip() for item in recipients)
    ):
        raise ValueError("rpa.allowed_recipients must be a non-empty string list")
    return frozenset(item.strip() for item in recipients)


def load_rpa_settings(
    raw: Mapping[str, Any] | None,
    weixin: Mapping[str, Any] | None,
    env: Mapping[str, str],
) -> RpaSettings:
    """Validate local RPA settings without creating or controlling WeChat."""
    raw = raw if isinstance(raw, Mapping) else {}
    weixin = weixin if isinstance(weixin, Mapping) else {}

    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("rpa.enabled must be a boolean")

    host = raw.get("host", "127.0.0.1")
    if host != "127.0.0.1":
        raise ValueError("RPA host must be exactly 127.0.0.1")

    key_name = raw.get("api_key_env", "WECHAT_RPA_API_KEY")
    if not isinstance(key_name, str) or not key_name.strip():
        raise ValueError("rpa.api_key_env must be a non-empty environment variable name")
    api_key = str(env.get(key_name, "")).strip()
    if enabled and not api_key:
        raise ValueError(f"{key_name} must be set when rpa.enabled is true")

    return RpaSettings(
        enabled=enabled,
        host=host,
        port=_positive_int(raw, "port", 9922, 65535),
        api_key=api_key,
        allowed_recipients=_allowed_recipients(raw),
        max_text_length=_positive_int(raw, "max_text_length", 2000, 10000),
        idempotency_ttl_sec=_positive_int(raw, "idempotency_ttl_sec", 300, 86400),
        weixin_exe=Path(str(weixin.get("exe", ""))),
        decrypted_db_path=Path(
            str(weixin.get("decrypted_db_path", "./wx/decrypted/contact.db"))
        ),
    )
