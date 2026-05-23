from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from dashboard.state import BotState, reset_state, get_state
from dashboard.server import create_app


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    yield
    reset_state()


@pytest.fixture
def client():
    return TestClient(create_app(get_state()))


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "WeChatRobot Dashboard" in r.text
    assert "text/html" in r.headers["content-type"]


def test_status_endpoint(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    data = r.json()
    assert "uptime_sec" in data
    assert data["paused"] is False
    assert data["queue_depth"] == 0


def test_pause_resume_cycle(client):
    r = client.post("/api/pause", json={"reason": "smoke"})
    assert r.status_code == 200
    assert r.json()["paused"] is True

    r = client.get("/api/status")
    assert r.json()["paused"] is True
    assert r.json()["pause_reason"] == "smoke"

    r = client.post("/api/resume")
    assert r.json()["paused"] is False

    r = client.get("/api/status")
    assert r.json()["paused"] is False


def test_pause_without_body(client):
    r = client.post("/api/pause")
    assert r.status_code == 200
    assert r.json()["reason"] == "manual"


def test_logs_endpoint_empty(client):
    r = client.get("/api/logs")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_logs_with_seeded_entries(client):
    s = get_state()
    s.logs.append({"ts": 1, "level": "INFO", "logger": "x", "message": "hello"})
    s.logs.append({"ts": 2, "level": "ERROR", "logger": "x", "message": "boom"})
    s.logs.append({"ts": 3, "level": "INFO", "logger": "y", "message": "world"})

    r = client.get("/api/logs?level=ERROR")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["message"] == "boom"

    r = client.get("/api/logs?q=hello")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["message"] == "hello"

    r = client.get("/api/logs?n=2")
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["message"] == "boom"
    assert items[1]["message"] == "world"


def test_logs_since_seq(client):
    s = get_state()
    s.logs.append({"ts": 1, "level": "INFO", "logger": "x", "message": "first"})
    seq1 = s.logs.last_seq
    s.logs.append({"ts": 2, "level": "INFO", "logger": "x", "message": "second"})

    r = client.get(f"/api/logs?since_seq={seq1}")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["message"] == "second"


def test_messages_endpoint(client):
    s = get_state()
    s.messages.append({"ts": 1, "type": 1, "sender": "wxid_a", "roomid": "", "content": "hi"})
    s.messages.append({"ts": 2, "type": 1, "sender": "wxid_b", "roomid": "", "content": "下单"})

    r = client.get("/api/messages?q=下单")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["sender"] == "wxid_b"


def test_audit_endpoint(client):
    s = get_state()
    s.audit.append({"event": "place_dry_run", "wxid": "a", "ts": 1})
    s.audit.append({"event": "cancel", "wxid": "b", "ts": 2})

    r = client.get("/api/audit?event=cancel")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["wxid"] == "b"


def test_contacts_endpoint_no_adapter(client):
    r = client.get("/api/contacts")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_contacts_endpoint_with_adapter(client):
    s = get_state()
    s.wx_adapter = MagicMock()
    s.wx_adapter._contacts.all_contacts.return_value = {
        "wxid_alice": "Alice",
        "wxid_bob": "Bob",
        "wxid_charlie": "Charlie",
    }

    r = client.get("/api/contacts?q=ali")
    data = r.json()
    assert data["total"] == 1
    assert data["items"][0]["wxid"] == "wxid_alice"

    r = client.get("/api/contacts")
    data = r.json()
    assert data["total"] == 3


def test_pending_orders_empty(client):
    r = client.get("/api/orders/pending")
    assert r.json()["items"] == []


def test_pending_orders_with_handler(client):
    s = get_state()
    s.order_handler = MagicMock()
    draft = MagicMock()
    draft.to_dict.return_value = {
        "school": "X", "user": "u", "password": None,
        "platform": None, "kcid": None, "kcname": None,
        "requester_wxid": "wxid_a", "created_at": 0,
        "confirmed": False, "extract_rounds": 1,
    }
    s.order_handler._pending = {"wxid_a": draft}

    r = client.get("/api/orders/pending")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["wxid"] == "wxid_a"
    assert items[0]["school"] == "X"


# ----- account endpoints -----

def _register_account(s, name="acc1", label="Account 1"):
    from dashboard.accounts import AccountConfig
    return s.accounts.register(AccountConfig(name=name, label=label))


def test_accounts_endpoint_empty(client):
    r = client.get("/api/accounts")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_accounts_endpoint_lists_registered(client):
    s = get_state()
    _register_account(s, "alice", "Alice's bot")
    _register_account(s, "bob", "Bob's bot")

    r = client.get("/api/accounts")
    items = r.json()["items"]
    names = [i["name"] for i in items]
    assert "alice" in names
    assert "bob" in names
    for item in items:
        assert item["status"] == "stopped"
        assert item["paused"] is False


def test_account_start_without_factory_fails(client):
    s = get_state()
    _register_account(s, "x")
    r = client.post("/api/accounts/x/start")
    assert r.status_code == 400
    assert "factory" in r.json()["detail"]


def test_account_start_with_factory(client):
    s = get_state()
    state_ref = _register_account(s, "x")

    def fac(cfg, st):
        return (MagicMock(), MagicMock(), MagicMock())

    s.accounts.set_factory(fac)
    r = client.post("/api/accounts/x/start")
    assert r.status_code == 200
    # background thread; wait a beat
    import time as _t
    _t.sleep(0.2)
    assert state_ref.status.value in ("running", "starting")


def test_account_pause_resume(client):
    s = get_state()
    _register_account(s, "y")
    r = client.post("/api/accounts/y/pause", json={"reason": "test"})
    assert r.status_code == 200
    r = client.get("/api/accounts")
    item = [i for i in r.json()["items"] if i["name"] == "y"][0]
    assert item["paused"] is True
    assert item["pause_reason"] == "test"

    r = client.post("/api/accounts/y/resume")
    assert r.status_code == 200
    r = client.get("/api/accounts")
    item = [i for i in r.json()["items"] if i["name"] == "y"][0]
    assert item["paused"] is False


def test_account_stop_when_not_running(client):
    s = get_state()
    _register_account(s, "z")
    r = client.post("/api/accounts/z/stop")
    assert r.status_code == 200


def test_account_unknown_returns_400(client):
    r = client.post("/api/accounts/nobody/start")
    assert r.status_code == 400


def test_status_includes_account_aggregate(client):
    s = get_state()
    _register_account(s, "a")
    _register_account(s, "b")
    r = client.get("/api/status")
    data = r.json()
    assert data["account_count"] == 2
    assert len(data["accounts"]) == 2


def test_status_reports_factory_registered_false_by_default(client):
    r = client.get("/api/status")
    data = r.json()
    assert data["factory_registered"] is False


def test_status_reports_factory_registered_true_after_set(client):
    s = get_state()
    s.accounts.set_factory(lambda cfg, st: (MagicMock(), MagicMock(), MagicMock()))
    r = client.get("/api/status")
    data = r.json()
    assert data["factory_registered"] is True
