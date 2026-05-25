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
            start = midnight - day_sec * (n - 1)
            start_str = time.strftime("%Y-%m-%d", time.localtime(start))
            return start, midnight + day_sec, f"{n}日", f"{start_str} → {today_str}"
        return midnight, midnight + day_sec, "今日", today_str
