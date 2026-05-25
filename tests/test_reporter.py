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
        {"event": "place_real", "ts": _ts(f"{today} 14:00") - 86400 * 2,
         "draft": {"platform": "1736", "kcname": "其他", "requester_wxid": "wxid_c"},
         "result": {"code": 1}},
    ])
    r = reporter.aggregate(account="main", window="today")
    assert r["order_count"] == 2
    assert r["success_count"] == 2
    assert r["fail_count"] == 0
    assert r["unique_users"] == 2
    assert r["total_amount"] == 20.0


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
        {"event": "place_real", "ts": _ts(f"{today} 10:00") - 86400 * 5,
         "draft": {"platform": "1736", "kcname": "形势与政策", "requester_wxid": "u1"},
         "result": {"code": 1}},
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
