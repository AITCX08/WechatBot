# Filehelper v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Turn filehelper into a full bi-directional ops channel: add proactive event notifications (online/offline/order outcomes/errors), daily statistical report (manual + scheduled 22:00), and pricing-based revenue aggregation. Each account's notifications go to its own filehelper.

**Architecture:** Three new self-contained modules + small wire-up. `router/pricing.py` (config-driven lookup), `router/reporter.py` (audit-log aggregator + text renderer), `router/notifier.py` (event dispatcher with per-account cooldown + quiet hours). Wire `notifier.emit(...)` from `OrderHandler._audit` and `AccountManager.start/stop` background threads. Add 3 new command handlers (`/report`, `/pending`, `/pricing`). Schedule daily push via the existing `schedule` library — no new deps.

**Tech Stack:** Python 3.10+, existing `schedule` lib, stdlib `json`/`time`/`pathlib`/`threading`. Per-account `logs/audit/orders-{name}.jsonl` is the source of truth.

**Spec source:** Standard version B from `/req` on 2026-05-23 (filehelper command MVP), v2 features.

---

## File Structure

**New files:**
- `router/pricing.py` — `PricingTable` class, `resolve(platform, kcname) -> float | None`
- `router/reporter.py` — `Reporter` class with `aggregate(account, window)` + `render_text(report) -> str`
- `router/notifier.py` — `Notifier` class with per-account `emit(event_type, payload)`, cooldown + quiet-hours
- `tests/test_pricing.py`, `tests/test_reporter.py`, `tests/test_notifier.py`

**Modified files:**
- `router/commands.py` — register `/report`, `/pending`, `/pricing` handlers + Chinese aliases
- `router/order.py` — `OrderHandler._audit` and `place_order` invoke `notifier.emit(...)`
- `main.py` — construct shared `Notifier` + `Reporter`; pass into bot factory; start scheduler thread
- `dashboard/accounts.py` — `AccountManager.start/stop` background threads emit online/offline (via optional callback set by main.py)
- `configuration.py` + `config.yaml.template` — `pricing` block + `notifier`/`report` sub-blocks under `filehelper`
- `tests/test_commands.py`, `tests/test_order_handler.py`, `tests/test_accounts.py` — verify new wiring

---

## Task V2-1: Pricing table with tests

**Files:** Create `router/pricing.py`, `tests/test_pricing.py`

- [ ] **Step 1: Write failing tests**

`tests/test_pricing.py`:

```python
from router.pricing import PricingTable


def _table():
    return PricingTable({
        "default": 5.0,
        "1736": {
            "default": 8.0,
            "形势与政策": 12.0,
            "马克思主义基本原理": 10.0,
        },
        "1800": {
            "default": 5.0,
        },
    })


def test_resolve_exact_match():
    t = _table()
    assert t.resolve("1736", "形势与政策") == 12.0


def test_resolve_falls_back_to_platform_default():
    t = _table()
    assert t.resolve("1736", "未列出的课") == 8.0


def test_resolve_falls_back_to_global_default():
    t = _table()
    assert t.resolve("9999", "anything") == 5.0


def test_resolve_with_empty_table():
    t = PricingTable({})
    assert t.resolve("any", "any") == 0.0


def test_resolve_with_only_global_default():
    t = PricingTable({"default": 7.5})
    assert t.resolve("any", "any") == 7.5


def test_resolve_handles_none_inputs():
    t = _table()
    assert t.resolve(None, None) == 5.0


def test_estimate_total_sums_resolved_prices():
    t = _table()
    orders = [
        {"platform": "1736", "kcname": "形势与政策"},   # 12
        {"platform": "1736", "kcname": "其他"},          # 8 (platform default)
        {"platform": "9999", "kcname": "no plat"},       # 5 (global default)
    ]
    assert t.estimate_total(orders) == 25.0
```

- [ ] **Step 2: Run → expect ImportError**

```bash
pytest tests/test_pricing.py -v
```

- [ ] **Step 3: Implement `router/pricing.py`**

```python
"""Lookup unit price per (platform, course-name)."""
from __future__ import annotations
from typing import Iterable


class PricingTable:
    """Two-level lookup: platform -> (course-name -> price | 'default').

    Schema in config.yaml:
        pricing:
          default: 5.0              # global fallback when platform missing
          1736:
            default: 8.0            # platform-level fallback
            "形势与政策": 12.0      # exact course override
          1800:
            default: 5.0
    """

    def __init__(self, table: dict):
        self._table = table or {}

    def resolve(self, platform, kcname) -> float:
        platform = str(platform) if platform is not None else ""
        kcname = str(kcname) if kcname is not None else ""
        plat = self._table.get(platform)
        if isinstance(plat, dict):
            if kcname in plat:
                return float(plat[kcname])
            if "default" in plat:
                return float(plat["default"])
        # Fall back to global default; 0.0 if missing
        return float(self._table.get("default", 0.0))

    def estimate_total(self, orders: Iterable[dict]) -> float:
        return round(sum(self.resolve(o.get("platform"), o.get("kcname")) for o in orders), 2)
```

- [ ] **Step 4: Run → 7 pass**

- [ ] **Step 5: Commit**

```bash
git add router/pricing.py tests/test_pricing.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): add PricingTable two-level lookup"
```

---

## Task V2-2: Reporter with tests

**Files:** Create `router/reporter.py`, `tests/test_reporter.py`

Reads from `logs/audit/orders-{name}.jsonl` (one JSON per line, written by OrderHandler). Aggregates per time-window into a `Report` dict, then renders to text.

- [ ] **Step 1: Write failing tests**

`tests/test_reporter.py`:

```python
import json
import time
from pathlib import Path
import pytest

from router.reporter import Reporter
from router.pricing import PricingTable


def _write_audit(tmp_path: Path, account: str, events: list[dict]) -> Path:
    p = tmp_path / f"orders-{account}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    return p


@pytest.fixture
def pricing():
    return PricingTable({"default": 5.0, "1736": {"default": 8.0, "形势与政策": 12.0}})


@pytest.fixture
def reporter(tmp_path, pricing):
    return Reporter(audit_dir=tmp_path, pricing=pricing)


def _ts(date_str: str) -> int:
    # date_str: YYYY-MM-DD HH:MM
    return int(time.mktime(time.strptime(date_str, "%Y-%m-%d %H:%M")))


def test_today_counts_only_today(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        {"event": "place_real", "ts": _ts(f"{today} 10:00"),
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "wxid_a"},
         "result": {"code": 1}},
        {"event": "place_real", "ts": _ts(f"{today} 14:00"),
         "draft": {"platform": "1736", "kcname": "其他", "requester_wxid": "wxid_b"},
         "result": {"code": 1}},
        # Yesterday – should NOT be counted
        {"event": "place_real", "ts": _ts(f"{today} 14:00") - 86400 * 2,
         "draft": {"platform": "1736", "kcname": "其他", "requester_wxid": "wxid_c"},
         "result": {"code": 1}},
    ])
    r = reporter.aggregate(account="main", window="today")
    assert r["order_count"] == 2
    assert r["success_count"] == 2
    assert r["fail_count"] == 0
    assert r["unique_users"] == 2
    assert r["total_amount"] == 20.0    # 12 + 8


def test_failures_counted_separately(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        {"event": "place_real", "ts": _ts(f"{today} 10:00"),
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "wxid_a"},
         "result": {"code": 1}},
        {"event": "place_error", "ts": _ts(f"{today} 11:00"),
         "draft": {"platform": "1736", "kcname": "其他", "requester_wxid": "wxid_b"},
         "error": "timeout"},
    ])
    r = reporter.aggregate(account="main", window="today")
    assert r["success_count"] == 1
    assert r["fail_count"] == 1
    # Failed orders do NOT add to total_amount
    assert r["total_amount"] == 12.0


def test_dry_run_in_today_counts_as_success(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        {"event": "place_dry_run", "ts": _ts(f"{today} 10:00"),
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "wxid_a"}},
    ])
    r = reporter.aggregate(account="main", window="today")
    assert r["success_count"] == 1
    assert r["total_amount"] == 12.0


def test_yesterday_window(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        {"event": "place_real", "ts": _ts(f"{today} 10:00") - 86400,
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "wxid_a"},
         "result": {"code": 1}},
        {"event": "place_real", "ts": _ts(f"{today} 14:00"),
         "draft": {"platform": "1736", "kcname": "其他", "requester_wxid": "wxid_b"},
         "result": {"code": 1}},
    ])
    r = reporter.aggregate(account="main", window="yesterday")
    assert r["order_count"] == 1


def test_window_7d_uses_seven_days(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        # within 7d
        {"event": "place_real", "ts": _ts(f"{today} 10:00") - 86400 * 5,
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "u1"},
         "result": {"code": 1}},
        # outside 7d
        {"event": "place_real", "ts": _ts(f"{today} 10:00") - 86400 * 10,
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "u2"},
         "result": {"code": 1}},
    ])
    r = reporter.aggregate(account="main", window="7d")
    assert r["order_count"] == 1


def test_missing_audit_file_returns_zero_report(tmp_path, reporter):
    r = reporter.aggregate(account="nonexistent", window="today")
    assert r["order_count"] == 0
    assert r["total_amount"] == 0.0


def test_render_text_includes_key_fields(reporter):
    rep = {
        "account": "main",
        "window_label": "今日",
        "date_range": "2026-05-25",
        "order_count": 5, "success_count": 4, "fail_count": 1,
        "total_amount": 48.0, "unique_users": 3,
        "top_courses": [("形势与政策", 3), ("其他", 1)],
    }
    text = reporter.render_text(rep)
    assert "今日" in text
    assert "main" in text or "[main]" in text or "账号" in text
    assert "5" in text
    assert "¥48" in text or "48.0" in text or "48" in text
    assert "形势与政策" in text


def test_top_courses_sorted_desc(tmp_path, reporter):
    today = time.strftime("%Y-%m-%d")
    _write_audit(tmp_path, "main", [
        {"event": "place_real", "ts": _ts(f"{today} 10:00"),
         "draft": {"platform": "1736", "kcname": "A", "requester_wxid": "u1"},
         "result": {"code": 1}},
        {"event": "place_real", "ts": _ts(f"{today} 11:00"),
         "draft": {"platform": "1736", "kcname": "B", "requester_wxid": "u2"},
         "result": {"code": 1}},
        {"event": "place_real", "ts": _ts(f"{today} 12:00"),
         "draft": {"platform": "1736", "kcname": "B", "requester_wxid": "u3"},
         "result": {"code": 1}},
        {"event": "place_real", "ts": _ts(f"{today} 13:00"),
         "draft": {"platform": "1736", "kcname": "B", "requester_wxid": "u4"},
         "result": {"code": 1}},
    ])
    r = reporter.aggregate(account="main", window="today")
    assert r["top_courses"][0] == ("B", 3)
    assert r["top_courses"][1] == ("A", 1)
```

- [ ] **Step 2: Run → expect ImportError**

- [ ] **Step 3: Implement `router/reporter.py`**

```python
"""Aggregate order audit logs into time-windowed reports + render text."""
from __future__ import annotations
import json
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from router.pricing import PricingTable

SUCCESS_EVENTS = ("place_real", "place_dry_run")
FAIL_EVENTS = ("place_error", "daily_limit_hit")


class Reporter:
    def __init__(self, audit_dir: Path, pricing: Optional[PricingTable] = None):
        self.audit_dir = Path(audit_dir)
        self.pricing = pricing or PricingTable({})

    # ---- public ----
    def aggregate(self, account: str, window: str) -> dict:
        start_ts, end_ts, label, date_range = self._resolve_window(window)
        rows = self._read_events(account)
        in_window = [r for r in rows if start_ts <= r.get("ts", 0) < end_ts]

        successes = [r for r in in_window if r.get("event") in SUCCESS_EVENTS]
        failures = [r for r in in_window if r.get("event") in FAIL_EVENTS]

        unique_users = {self._wxid(r) for r in successes if self._wxid(r)}
        course_counter = Counter(self._kcname(r) for r in successes if self._kcname(r))
        success_orders = [r.get("draft") or {} for r in successes]

        return {
            "account": account,
            "window": window,
            "window_label": label,
            "date_range": date_range,
            "order_count": len(in_window),
            "success_count": len(successes),
            "fail_count": len(failures),
            "unique_users": len(unique_users),
            "total_amount": self.pricing.estimate_total(success_orders),
            "top_courses": course_counter.most_common(5),
        }

    def render_text(self, rep: dict) -> str:
        lines = [
            f"📊 {rep['window_label']}报告 [{rep['account']}]",
            f"📅 {rep['date_range']}",
            "─" * 18,
            f"下单 {rep['order_count']} 笔  (成功 {rep['success_count']} / 失败 {rep['fail_count']})",
            f"服务用户 {rep['unique_users']} 人",
            f"累计金额 ¥{rep['total_amount']:.2f}",
        ]
        top = rep.get("top_courses") or []
        if top:
            lines.append("── 热门课程 ──")
            for name, count in top[:5]:
                lines.append(f"  {name}  ×{count}")
        return "\n".join(lines)

    # ---- internals ----
    def _read_events(self, account: str) -> list[dict]:
        p = self.audit_dir / f"orders-{account}.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out

    @staticmethod
    def _wxid(row: dict) -> str:
        d = row.get("draft") or {}
        return d.get("requester_wxid") or row.get("wxid") or ""

    @staticmethod
    def _kcname(row: dict) -> str:
        d = row.get("draft") or {}
        return d.get("kcname") or ""

    @staticmethod
    def _resolve_window(window: str) -> tuple[int, int, str, str]:
        """Return (start_ts, end_ts, human_label, date_range_str)."""
        now = time.time()
        day_sec = 86400
        today_struct = time.localtime(now)
        midnight = int(time.mktime(time.struct_time((
            today_struct.tm_year, today_struct.tm_mon, today_struct.tm_mday,
            0, 0, 0, 0, 0, today_struct.tm_isdst,
        ))))
        today_str = time.strftime("%Y-%m-%d", today_struct)

        if window in ("today", ""):
            return midnight, midnight + day_sec, "今日", today_str
        if window == "yesterday":
            y = midnight - day_sec
            yesterday_str = time.strftime("%Y-%m-%d", time.localtime(y))
            return y, midnight, "昨日", yesterday_str
        if window.endswith("d") and window[:-1].isdigit():
            n = int(window[:-1])
            start = midnight - day_sec * (n - 1)   # include today
            start_str = time.strftime("%Y-%m-%d", time.localtime(start))
            return start, midnight + day_sec, f"{n}日", f"{start_str} → {today_str}"
        # Unknown window → today
        return midnight, midnight + day_sec, "今日", today_str
```

- [ ] **Step 4: Run → 8 pass**

- [ ] **Step 5: Commit**

```bash
git add router/reporter.py tests/test_reporter.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): add Reporter audit-log aggregator + text rendering"
```

---

## Task V2-3: Notifier with cooldown + quiet hours

**Files:** Create `router/notifier.py`, `tests/test_notifier.py`

Central event dispatcher. Each event is `(account, event_type, payload)`. Notifier looks up target filehelper (via account context), checks subscription / cooldown / quiet hours, formats text, sends via `wx_adapter.send_text(text, "filehelper")`.

- [ ] **Step 1: Write failing tests**

`tests/test_notifier.py`:

```python
import time
from unittest.mock import MagicMock

import pytest

from router.notifier import Notifier


@pytest.fixture
def wx():
    return MagicMock()


@pytest.fixture
def adapters(wx):
    """Map of account_name -> wx_adapter. Notifier uses this to send."""
    return {"main": wx, "support": MagicMock()}


@pytest.fixture
def notifier(adapters):
    return Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        cooldown_sec=300,
        quiet_hours=(),
        enabled_events=None,  # all enabled by default
    )


def test_emit_unknown_account_does_not_raise(notifier):
    notifier.emit("nobody", "online", {})   # should not raise


def test_emit_online_sends_to_filehelper(notifier, adapters):
    notifier.emit("main", "online", {})
    adapters["main"].send_text.assert_called_once()
    text, receiver = adapters["main"].send_text.call_args[0][:2]
    assert receiver == "filehelper"
    assert "上线" in text or "online" in text.lower()


def test_emit_offline_sends(notifier, adapters):
    notifier.emit("main", "offline", {})
    adapters["main"].send_text.assert_called_once()
    assert "下线" in adapters["main"].send_text.call_args[0][0]


def test_emit_order_success_with_payload(notifier, adapters):
    notifier.emit("main", "order_success", {"kcname": "形势与政策", "wxid": "wxid_x"})
    text = adapters["main"].send_text.call_args[0][0]
    assert "形势与政策" in text
    assert "wxid_x" in text


def test_cooldown_suppresses_repeat(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("main", "order_success", {"kcname": "B"})    # same type within cooldown
    adapters["main"].send_text.assert_not_called()


def test_cooldown_per_account_independent(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("support", "order_success", {"kcname": "B"})
    adapters["support"].send_text.assert_called_once()


def test_cooldown_per_event_type_independent(adapters):
    n = Notifier(adapter_lookup=lambda name: adapters.get(name), cooldown_sec=300)
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.reset_mock()
    n.emit("main", "order_failure", {"kcname": "A", "msg": "bad"})
    adapters["main"].send_text.assert_called_once()


def test_disabled_event_type_not_sent(adapters):
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        enabled_events={"online", "offline"},
    )
    n.emit("main", "order_success", {"kcname": "A"})
    adapters["main"].send_text.assert_not_called()


def test_critical_bypasses_quiet_hours(adapters, monkeypatch):
    """error events have priority=CRITICAL and ignore quiet_hours."""
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        quiet_hours=(0, 23),       # quiet ALL hours
    )
    # Force "now" to fall inside quiet hours
    monkeypatch.setattr("router.notifier.time.localtime",
                        lambda *_: time.struct_time((2026, 5, 25, 3, 0, 0, 0, 0, 0)))
    n.emit("main", "error", {"msg": "boom"})
    adapters["main"].send_text.assert_called_once()


def test_info_suppressed_in_quiet_hours(adapters, monkeypatch):
    n = Notifier(
        adapter_lookup=lambda name: adapters.get(name),
        quiet_hours=(0, 7),
    )
    monkeypatch.setattr("router.notifier.time.localtime",
                        lambda *_: time.struct_time((2026, 5, 25, 3, 0, 0, 0, 0, 0)))
    n.emit("main", "online", {})
    adapters["main"].send_text.assert_not_called()


def test_send_failure_swallowed(adapters):
    adapters["main"].send_text.side_effect = RuntimeError("send broken")
    n = Notifier(adapter_lookup=lambda name: adapters.get(name))
    n.emit("main", "online", {})   # must not raise
```

- [ ] **Step 2: Run → expect ImportError**

- [ ] **Step 3: Implement `router/notifier.py`**

```python
"""Event-driven notifications to per-account filehelper."""
from __future__ import annotations
import logging
import threading
import time
from typing import Callable, Optional

LOG = logging.getLogger(__name__)

# Priority: CRITICAL bypasses quiet_hours; INFO is suppressed during quiet_hours.
CRITICAL_EVENTS = frozenset({"error", "sidecar_down", "order_failure"})

FORMATTERS = {
    "online":         lambda p: "🟢 [{account}] 已上线",
    "offline":        lambda p: "🔴 [{account}] 已下线",
    "order_success":  lambda p: "✅ [{account}] 下单成功 / {wxid} / {kcname}",
    "order_failure":  lambda p: "❌ [{account}] 下单失败 / {wxid} / {kcname} / {msg}",
    "order_dry_run":  lambda p: "🟡 [{account}] dry_run 下单 / {wxid} / {kcname}",
    "error":          lambda p: "❗ [{account}] 错误：{msg}",
    "sidecar_down":   lambda p: "❗ [{account}] sidecar 心跳超时",
}


class Notifier:
    """Send filehelper notifications per account, with cooldown + quiet hours."""

    def __init__(
        self,
        adapter_lookup: Callable[[str], object],
        cooldown_sec: int = 300,
        quiet_hours: tuple = (),
        enabled_events: Optional[set[str]] = None,
    ):
        self._lookup = adapter_lookup
        self._cooldown_sec = int(cooldown_sec)
        self._quiet_hours = tuple(quiet_hours) if quiet_hours else ()
        self._enabled = enabled_events  # None == all
        self._last_emit: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def emit(self, account: str, event_type: str, payload: dict) -> None:
        try:
            self._emit(account, event_type, payload)
        except Exception as e:
            LOG.warning("notifier.emit failed: %s", e)

    def _emit(self, account: str, event_type: str, payload: dict) -> None:
        if self._enabled is not None and event_type not in self._enabled:
            return

        is_critical = event_type in CRITICAL_EVENTS
        if not is_critical and self._in_quiet_hours():
            return

        key = (account, event_type)
        now = time.time()
        with self._lock:
            last = self._last_emit.get(key, 0.0)
            if not is_critical and (now - last) < self._cooldown_sec:
                return
            self._last_emit[key] = now

        adapter = self._lookup(account)
        if adapter is None:
            LOG.debug("no adapter for account %s; dropping notification", account)
            return

        text = self._format(account, event_type, payload)
        try:
            adapter.send_text(text, "filehelper")
        except Exception as e:
            LOG.warning("notifier send_text failed: %s", e)

    def _format(self, account: str, event_type: str, payload: dict) -> str:
        fmt = FORMATTERS.get(event_type)
        ctx = {"account": account, "wxid": "", "kcname": "", "msg": ""}
        ctx.update(payload or {})
        if fmt is None:
            return f"ℹ️ [{account}] {event_type}: {payload}"
        try:
            return fmt(ctx).format(**ctx)
        except Exception:
            return f"ℹ️ [{account}] {event_type}"

    def _in_quiet_hours(self) -> bool:
        if not self._quiet_hours or len(self._quiet_hours) != 2:
            return False
        start, end = self._quiet_hours
        hour = time.localtime().tm_hour
        if start <= end:
            return start <= hour < end
        # wraps midnight (e.g. 22..7)
        return hour >= start or hour < end
```

- [ ] **Step 4: Run → 11 pass**

- [ ] **Step 5: Commit**

```bash
git add router/notifier.py tests/test_notifier.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): add Notifier with cooldown + quiet_hours + per-account routing"
```

---

## Task V2-4: New /report /pending /pricing commands

**Files:** Modify `router/commands.py`, `tests/test_commands.py`

The commands need a Reporter + Pricing to do their work. Pass them via `CommandContext` (add fields).

- [ ] **Step 1: Extend `CommandContext` in `router/commands.py`**

Add two optional fields:
```python
@dataclass
class CommandContext:
    wx_adapter: object
    state: object
    account_state: object | None = None
    reporter: object | None = None        # Reporter instance
    pricing: object | None = None         # PricingTable instance
```

- [ ] **Step 2: Add 3 new handler functions** in `router/commands.py`:

```python
def cmd_report(ctx, args: str) -> str:
    if ctx.reporter is None:
        return "⚠ 报告引擎未就绪"
    account = ctx.account_state.config.name if ctx.account_state else "default"
    window = (args or "today").strip()
    rep = ctx.reporter.aggregate(account=account, window=window)
    return ctx.reporter.render_text(rep)


def cmd_pending(ctx, args: str) -> str:
    oh = getattr(ctx.account_state, "order_handler", None) if ctx.account_state else None
    if oh is None and ctx.state is not None:
        oh = getattr(ctx.state, "order_handler", None)
    if oh is None:
        return "⚠ OrderHandler 未就绪"
    pending = list(oh._pending.values()) if hasattr(oh, "_pending") else []
    if not pending:
        return "✅ 当前无待确认订单"
    lines = [f"📋 待确认订单 ({len(pending)} 笔):"]
    for d in pending:
        lines.append(f"  {d.requester_wxid}: {d.kcname or '?'} ({d.kcid or '?'}) · 第 {d.extract_rounds} 轮")
    return "\n".join(lines)


def cmd_pricing(ctx, args: str) -> str:
    if ctx.pricing is None:
        return "⚠ 价格表未配置"
    table = ctx.pricing._table
    lines = ["💰 当前价格表："]
    default = table.get("default")
    if default is not None:
        lines.append(f"  全局默认: ¥{float(default):.2f}")
    for k, v in table.items():
        if k == "default" or not isinstance(v, dict):
            continue
        lines.append(f"  [{k}] 默认 ¥{float(v.get('default', 0)):.2f}")
        for course, price in v.items():
            if course == "default":
                continue
            lines.append(f"    · {course}  ¥{float(price):.2f}")
    return "\n".join(lines)
```

- [ ] **Step 3: Wire into `build_default_registry()`**:

```python
def build_default_registry() -> CommandRegistry:
    reg = CommandRegistry()
    reg.register("/status", cmd_status, aliases=["状态"])
    reg.register("/pause",  cmd_pause,  aliases=["暂停"])
    reg.register("/resume", cmd_resume, aliases=["恢复"])
    reg.register("/help",   cmd_help,   aliases=["帮助"])
    reg.register("/report", cmd_report, aliases=["日报", "今日", "报告"])
    reg.register("/pending", cmd_pending, aliases=["待确认", "待办"])
    reg.register("/pricing", cmd_pricing, aliases=["价格", "价目"])
    return reg
```

- [ ] **Step 4: Update `cmd_help` text** to include new commands:

```python
def cmd_help(ctx: CommandContext, args: str) -> str:
    return (
        "📋 可用命令：\n"
        "/status   或 「状态」    — 查看运行状态\n"
        "/pause    或 「暂停」    — 暂停响应\n"
        "/resume   或 「恢复」    — 取消暂停\n"
        "/report   或 「日报/今日」— 今日报告 (/report yesterday|7d|30d)\n"
        "/pending  或 「待确认」  — 待确认订单列表\n"
        "/pricing  或 「价格」    — 当前价格表\n"
        "/help     或 「帮助」    — 此说明"
    )
```

- [ ] **Step 5: Add tests in `tests/test_commands.py`**

```python
# ============ v2 command tests ============

from router.reporter import Reporter
from router.pricing import PricingTable


@pytest.fixture
def ctx_with_v2_deps(ctx, tmp_path):
    """Augment ctx with reporter + pricing for v2 tests."""
    pricing = PricingTable({"default": 5.0, "1736": {"default": 8.0, "形势与政策": 12.0}})
    reporter = Reporter(audit_dir=tmp_path, pricing=pricing)
    ctx.reporter = reporter
    ctx.pricing = pricing
    # Fake account_state with config.name="main"
    ctx.account_state = MagicMock()
    ctx.account_state.config.name = "main"
    ctx.account_state.order_handler = None
    return ctx


def test_cmd_report_today_empty(ctx_with_v2_deps):
    out = cmd_report(ctx_with_v2_deps, "today")
    assert "今日" in out
    assert "0" in out


def test_cmd_report_default_window_is_today(ctx_with_v2_deps):
    out = cmd_report(ctx_with_v2_deps, "")
    assert "今日" in out


def test_cmd_report_no_reporter_returns_warning():
    from router.commands import CommandContext
    c = CommandContext(wx_adapter=MagicMock(), state=MagicMock(), account_state=None,
                       reporter=None, pricing=None)
    out = cmd_report(c, "today")
    assert "未就绪" in out


def test_cmd_pending_empty(ctx_with_v2_deps):
    oh = MagicMock()
    oh._pending = {}
    ctx_with_v2_deps.account_state.order_handler = oh
    out = cmd_pending(ctx_with_v2_deps, "")
    assert "无待确认" in out


def test_cmd_pending_lists_drafts(ctx_with_v2_deps):
    oh = MagicMock()
    draft = MagicMock()
    draft.requester_wxid = "wxid_a"
    draft.kcname = "形势与政策"
    draft.kcid = "40"
    draft.extract_rounds = 1
    oh._pending = {"wxid_a": draft}
    ctx_with_v2_deps.account_state.order_handler = oh
    out = cmd_pending(ctx_with_v2_deps, "")
    assert "wxid_a" in out
    assert "形势与政策" in out


def test_cmd_pricing_renders_table(ctx_with_v2_deps):
    out = cmd_pricing(ctx_with_v2_deps, "")
    assert "1736" in out
    assert "形势与政策" in out
    assert "¥12" in out or "12.00" in out


def test_help_includes_new_commands(ctx_with_v2_deps):
    out = cmd_help(ctx_with_v2_deps, "")
    assert "/report" in out
    assert "/pending" in out
    assert "/pricing" in out


def test_registry_has_new_commands():
    reg = build_default_registry()
    assert reg.lookup("/report") is not None
    assert reg.lookup("/pending") is not None
    assert reg.lookup("/pricing") is not None
    assert reg.lookup("日报") is not None
    assert reg.lookup("待确认") is not None
    assert reg.lookup("价格") is not None
```

- [ ] **Step 6: Run command tests → all pass**

```bash
pytest tests/test_commands.py -v
```

- [ ] **Step 7: Commit**

```bash
git add router/commands.py tests/test_commands.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(router): add /report /pending /pricing commands + Chinese aliases"
```

---

## Task V2-5: Wire Notifier into OrderHandler + Account lifecycle

**Files:** Modify `router/order.py`, `dashboard/accounts.py`, `tests/test_order_handler.py`, `tests/test_accounts.py`

- [ ] **Step 1: `OrderHandler` accepts a notifier; emits on each `_audit`**

In `router/order.py`, modify `__init__` to accept optional `notifier` + `account_name`:

```python
    def __init__(
        self,
        lexue_creds: dict,
        llm,
        wx,
        safety: dict,
        audit_log_path: Path,
        intent_prompt: str,
        extract_prompt: str,
        notifier=None,
        account_name: str = "default",
    ):
        ...existing assignments...
        self.notifier = notifier
        self.account_name = account_name
```

In `_audit`, after writing JSONL + RingBuffer, emit via notifier with appropriate event type mapping:

```python
    def _audit(self, event: dict) -> None:
        event["ts"] = int(time.time())
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        try:
            from dashboard.state import get_state
            get_state().audit.append(event)
        except Exception:
            pass
        # v2: notify filehelper
        if self.notifier is not None:
            ev = event.get("event", "")
            payload = {
                "wxid": (event.get("draft") or {}).get("requester_wxid", ""),
                "kcname": (event.get("draft") or {}).get("kcname", ""),
                "msg": event.get("error") or event.get("msg") or "",
            }
            mapping = {
                "place_real": "order_success",
                "place_dry_run": "order_dry_run",
                "place_error": "order_failure",
                "daily_limit_hit": "error",
            }
            evt = mapping.get(ev)
            if evt:
                self.notifier.emit(self.account_name, evt, payload)
```

- [ ] **Step 2: AccountManager fires hooks on state transitions**

In `dashboard/accounts.py`, add a callback param to `AccountManager`:

```python
    def __init__(self):
        ...existing...
        self._on_status_change: Optional[Callable[[str, AccountStatus], None]] = None

    def set_on_status_change(self, cb):
        self._on_status_change = cb
```

In the background thread of `start()`, after `state.status = AccountStatus.RUNNING`, invoke the callback:
```python
                state.status = AccountStatus.RUNNING
                state.paused = False
                LOG.info("account %s: running", name)
                if self._on_status_change is not None:
                    try:
                        self._on_status_change(name, AccountStatus.RUNNING)
                    except Exception:
                        LOG.warning("on_status_change(RUNNING) failed", exc_info=True)
```

Similarly in `stop()`, after `state.status = AccountStatus.STOPPED`:
```python
                state.status = AccountStatus.STOPPED
                LOG.info("account %s: stopped", name)
                if self._on_status_change is not None:
                    try:
                        self._on_status_change(name, AccountStatus.STOPPED)
                    except Exception:
                        LOG.warning("on_status_change(STOPPED) failed", exc_info=True)
```

- [ ] **Step 3: main.py wires it all together**

In `main.py`, after creating the AccountManager + factory:

```python
from router.notifier import Notifier
from router.pricing import PricingTable
from router.reporter import Reporter
from dashboard.accounts import AccountStatus

# Build shared notifier + reporter + pricing
pricing = PricingTable(getattr(config, "PRICING", {}) or yaml_get(config, "pricing", {}))
reporter = Reporter(audit_dir=Path("logs/audit"), pricing=pricing)
notifier_cfg = (config.LLM.get("filehelper") if isinstance(config.LLM, dict) else {}) or {}
quiet = tuple(notifier_cfg.get("quiet_hours", ())) if notifier_cfg else ()

def _adapter_for(account_name: str):
    s = state.accounts.get(account_name)
    return s.wx_adapter if s else None

notifier = Notifier(
    adapter_lookup=_adapter_for,
    cooldown_sec=int(notifier_cfg.get("cooldown_sec", 300)),
    quiet_hours=quiet,
)

def _on_status_change(name: str, status):
    if status == AccountStatus.RUNNING:
        notifier.emit(name, "online", {})
    elif status == AccountStatus.STOPPED:
        notifier.emit(name, "offline", {})

state.accounts.set_on_status_change(_on_status_change)
```

And in `_make_bot_factory`, pass notifier into OrderHandler:

```python
        # Use a per-account audit log so multi-account orders don't collide
        try:
            audit_path = Path(f"logs/audit/orders-{acc_cfg.name}.jsonl")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            oh = getattr(robot.dispatcher, "order", None)
            if oh is not None:
                oh.audit_log_path = audit_path
                oh.notifier = notifier
                oh.account_name = acc_cfg.name
        ...
```

And expose `reporter` + `pricing` to commands by injecting CommandContext at dispatcher level — modify `router/dispatch.py` to take reporter+pricing in __init__ and put them in the CommandContext it builds:

```python
class Dispatcher:
    def __init__(self, ..., reporter=None, pricing=None):
        ...
        self.reporter = reporter
        self.pricing = pricing

    def _handle(self, msg):
        ctx = CommandContext(
            wx_adapter=self.wx, state=get_state(),
            account_state=None,
            reporter=self.reporter, pricing=self.pricing,
        )
        ...
```

Robot must pass them through; update `robot.py` to pull from config:

```python
from router.pricing import PricingTable
from router.reporter import Reporter
# inside __init__ after self.template_matcher:
pricing = PricingTable(getattr(self.config, "PRICING", {}) or {})
reporter = Reporter(audit_dir=Path("logs/audit"), pricing=pricing)
self.dispatcher = Dispatcher(
    wx=self.wcf,
    template_matcher=self.template_matcher,
    order_handler=order_handler,
    llm=self.chat,
    groups_allowed=set(self.config.GROUPS or []),
    reporter=reporter,
    pricing=pricing,
)
```

And add `PRICING` to `configuration.py`:

```python
self.PRICING = yconfig.get("pricing", {})
```

- [ ] **Step 4: Add tests**

In `tests/test_order_handler.py`, add:

```python
def test_audit_calls_notifier_on_place_real(handler, llm, wx):
    notif = MagicMock()
    handler.notifier = notif
    handler.account_name = "main"
    llm.get_answer.return_value = json.dumps({
        "school": "x", "user": "u", "password": "p",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.safety["dry_run"] = False
    # Mock Lexxue_api.xd
    import sys, types
    fake = types.ModuleType("Lexxue_api")
    fake.xd = lambda *a, **kw: {"code": 1, "msg": "ok"}
    sys.modules["Lexxue_api"] = fake
    handler.handle_new_order_message(make_msg("下单"))
    handler.on_user_reply(make_msg("确认"))
    # Among notifier calls, one should be order_success
    assert any(c[0][1] == "order_success" for c in notif.emit.call_args_list)
```

In `tests/test_accounts.py`, add:

```python
def test_on_status_change_fires_on_start(adapters_dict=None):
    import time as _t
    m = AccountManager()
    state = m.register(_cfg("a"))
    seen = []
    m.set_on_status_change(lambda name, status: seen.append((name, status.value)))

    def fac(cfg, st): return (MagicMock(), MagicMock(), MagicMock())
    m.set_factory(fac)
    m.start("a")
    for _ in range(20):
        if seen: break
        _t.sleep(0.05)
    assert ("a", "running") in seen


def test_on_status_change_fires_on_stop():
    import time as _t
    m = AccountManager()
    state = m.register(_cfg("a"))
    state.status = AccountStatus.RUNNING
    state.wx_adapter = MagicMock()
    seen = []
    m.set_on_status_change(lambda name, status: seen.append((name, status.value)))
    m.stop("a")
    for _ in range(20):
        if seen: break
        _t.sleep(0.05)
    assert ("a", "stopped") in seen
```

- [ ] **Step 5: Run all related tests → green**

```bash
pytest tests/test_order_handler.py tests/test_accounts.py -v
```

- [ ] **Step 6: Commit**

```bash
git add router/order.py dashboard/accounts.py main.py robot.py router/dispatch.py configuration.py tests/
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat: wire Notifier into OrderHandler + AccountManager lifecycle"
```

---

## Task V2-6: Daily report scheduler

**Files:** Modify `main.py`

Use existing `schedule` library (already a dep via Robot.runPendingJobs). Add a per-account daily report job at configured time (default `22:00`).

- [ ] **Step 1: In main.py, after notifier/reporter setup:**

```python
def _schedule_daily_reports():
    """Push daily report to each account's filehelper at configured time."""
    import schedule
    report_time = (notifier_cfg.get("daily_report_time")
                   if isinstance(notifier_cfg, dict) else None) or "22:00"

    def _push_for_all():
        for acc in state.accounts.all():
            if acc.status.value != "running":
                continue
            try:
                rep = reporter.aggregate(account=acc.name, window="today")
                text = reporter.render_text(rep)
                adapter = acc.wx_adapter
                if adapter is not None:
                    adapter.send_text(text, "filehelper")
                    LOG.info("daily report pushed to %s", acc.name)
            except Exception as e:
                LOG.warning("daily report for %s failed: %s", acc.name, e)

    schedule.every().day.at(report_time).do(_push_for_all)

    def _runner():
        while True:
            try:
                schedule.run_pending()
            except Exception as e:
                LOG.warning("schedule.run_pending crashed: %s", e)
            time.sleep(30)

    t = threading.Thread(target=_runner, name="DailyReportScheduler", daemon=True)
    t.start()
    LOG.info("daily report scheduled at %s", report_time)


# Call after setting up notifier:
_schedule_daily_reports()
```

(Note: `import threading` at top of main.py.)

- [ ] **Step 2: Verify main.py still imports**

```bash
python -c "import main; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add main.py
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "feat(main): schedule daily filehelper report at configurable time"
```

---

## Task V2-7: Full suite + config.yaml.template + commit + push

- [ ] **Step 1: Update `config.yaml.template` with new sections**

Append:

```yaml
pricing:
  default: 5.0
  # 1736:
  #   default: 8.0
  #   "形势与政策": 12.0

# Filehelper notifier + report tuning. All optional; defaults shown.
# Nest under llm.filehelper or top-level — main.py reads via config.LLM.get("filehelper", {})
# llm:
#   filehelper:
#     quiet_hours: [0, 7]          # no INFO notifications in 0:00-6:59
#     cooldown_sec: 300            # same event same account
#     daily_report_time: "22:00"   # cron-style HH:MM
```

- [ ] **Step 2: Run full suite**

```bash
pytest tests/ -q
```

- [ ] **Step 3: Push to GitHub**

```bash
git add config.yaml.template
git -c user.email="flashw008@gmail.com" -c user.name="WeChatRobot Dev" commit -m "docs(config): document pricing + filehelper notifier knobs in template"
git push github master:main
```

---

## Self-Review

| Spec line | Task | Status |
|---|---|---|
| 上线/下线主动通知 | V2-5 (on_status_change hook → notifier) | ✓ |
| 下单成功/失败/dry_run 通知 | V2-5 (OrderHandler._audit emit) | ✓ |
| 错误事件通知 | V2-5 (`daily_limit_hit` → error event) | ✓ |
| /report today/yesterday/Nd | V2-4 + V2-2 | ✓ |
| 22:00 自动报告 | V2-6 | ✓ |
| Pricing 表 | V2-1 + config.yaml.template | ✓ |
| 多账号 filehelper 隔离 | V2-3 (adapter_lookup per account) | ✓ |
| 每事件 cooldown | V2-3 (per (account, event) key) | ✓ |
| 静默时段 | V2-3 (quiet_hours config) | ✓ |
| CRITICAL bypass | V2-3 (CRITICAL_EVENTS list) | ✓ |

Placeholder scan: clean. No TBDs.

Type consistency: `Notifier.emit(account, event_type, payload)` consistent across V2-3 tests, V2-5 wire-up, V2-6 scheduler. `Reporter.aggregate(account, window)` consistent. `PricingTable.resolve(platform, kcname)` consistent.
