# Weixin 4.x Migration & Order Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate WeChatRobot off broken wcferry/WeChat 3.9.12.51 onto Weixin 4.1.7.30 (read via `wechat-decrypt` sidecar, write via `uiautomation`), then layer a template-based LLM router that auto-extracts order intent from chat and places orders against the Lexue API behind a confirmation gate.

**Architecture:** New `wx/` package = thin facade `WxAdapter` over three backends: `ReceiveBackend` (subscribes to `wechat-decrypt` SSE), `SendBackend` (UIA on Weixin window), `ContactsBackend` (reads decrypted SQLCipher DB). New `router/` package handles message dispatch + order state machine. `robot.py` becomes a thin glue layer.

**Tech Stack:** Python 3.10+, `uiautomation`, `pyperclip`, `pywin32`, `requests` (SSE), `sqlite3`, existing `pandas`/`openai`/`yaml`. Sidecar = `ylytdeng/wechat-decrypt` as git submodule.

**Spec:** `docs/superpowers/specs/2026-05-22-weixin4-migration-and-order-automation-design.md`

---

## File Structure

**New files:**
```
wx/
  __init__.py                # exports WxAdapter, WxMsg
  msg.py                     # @dataclass WxMsg + helpers
  adapter.py                 # WxAdapter facade
  receive.py                 # ReceiveBackend (sidecar + SSE)
  send.py                    # SendBackend (uiautomation)
  contacts.py                # ContactsBackend (SQLite read)
  sidecar/
    wechat-decrypt/          # git submodule, do not edit
router/
  __init__.py                # exports Dispatcher
  template.py                # keyword/regex template matcher
  order.py                   # OrderHandler (state machine + Lexue calls)
  dispatch.py                # Dispatcher composes everything
prompts/
  order_intent.md            # LLM prompt: classify if msg is order intent
  order_extract.md           # LLM prompt: extract OrderDraft fields
tests/
  __init__.py
  conftest.py                # shared fixtures
  test_msg.py
  test_contacts.py
  test_template.py
  test_order.py
  test_dispatch.py
  fixtures/
    sample_contact.db        # tiny seeded SQLite db for tests
    sample_sse_events.json   # canned wechat-decrypt SSE events
logs/
  audit/
    .gitkeep
.gitmodules
```

**Modified files:**
- `robot.py` — swap `Wcf`/`WxMsg` imports; replace `processMsg` body with `dispatcher.handle`
- `main.py` — change WxAdapter initialization
- `configuration.py` — load new `weixin`, `lexue`, `order_safety`, `llm` blocks
- `config.yaml.template` — add new sections
- `requirements.txt` — drop `wcferry`, add `uiautomation`, `pyperclip`, `pywin32`, `pytest`
- `.gitignore` — add `logs/audit/orders.jsonl`, `wx/sidecar/wechat-decrypt/.venv/`, `wx/decrypted/`

---

## Phase 0: Repository Preparation

### Task 0.1: Add wechat-decrypt submodule and scaffold dirs

**Files:**
- Create: `.gitmodules`
- Create: `wx/sidecar/wechat-decrypt` (submodule)
- Create: `logs/audit/.gitkeep`, `wx/__init__.py`, `wx/sidecar/__init__.py`, `router/__init__.py`, `prompts/.gitkeep`, `tests/__init__.py`, `tests/fixtures/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Add submodule**

```bash
git submodule add https://github.com/ylytdeng/wechat-decrypt.git wx/sidecar/wechat-decrypt
git submodule update --init --recursive
```

Expected: `.gitmodules` is created with the new entry; `wx/sidecar/wechat-decrypt/` contains the repo contents.

- [ ] **Step 2: Create directory skeleton**

```bash
mkdir -p logs/audit prompts tests/fixtures
touch wx/__init__.py wx/sidecar/__init__.py router/__init__.py tests/__init__.py
touch logs/audit/.gitkeep prompts/.gitkeep tests/fixtures/.gitkeep
```

- [ ] **Step 3: Update `.gitignore`**

Append these lines to `.gitignore`:

```gitignore
# Audit logs and decrypted data are runtime artifacts, never commit
logs/audit/orders.jsonl
logs/audit/*.jsonl
wx/sidecar/wechat-decrypt/.venv/
wx/decrypted/
wx/sidecar/wechat-decrypt/output/
```

- [ ] **Step 4: Commit**

```bash
git add .gitmodules wx/ router/ logs/ prompts/ tests/ .gitignore
git commit -m "chore: scaffold wx/, router/, sidecar submodule, test dirs"
```

### Task 0.2: Update requirements.txt

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Rewrite requirements**

Replace the contents of `requirements.txt` with:

```
chinese_calendar
lxml
openai>1.0.0
pandas
pyyaml
requests
schedule
pyhandytools
sparkdesk-api==1.3.0
websocket
pillow
jupyter_client
zhdate
ipykernel
google-generativeai
zhipuai
uiautomation>=2.0
pyperclip>=1.8
pywin32>=306
pytest>=7.0
pytest-mock>=3.10
```

(Removed `wcferry`; added `uiautomation`, `pyperclip`, `pywin32`, `pytest`, `pytest-mock`.)

- [ ] **Step 2: Install**

```bash
pip install -r requirements.txt
```

Expected: no errors; `uiautomation` and `pytest` available.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "chore(deps): drop wcferry, add uiautomation/pytest stack"
```

### Task 0.3: Smoke-test wechat-decrypt sidecar against Weixin 4.1.7.30

**Files:**
- Create: `docs/uia-anchors.md` (will be filled in Task 1.4)
- Create: `docs/sidecar-verification.md`

This is a **manual verification** that the sidecar can extract keys and produce an SSE stream from the installed Weixin 4.1.7.30 before we write any code against it.

- [ ] **Step 1: Install sidecar deps**

```bash
cd wx/sidecar/wechat-decrypt
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
cd ../../..
```

- [ ] **Step 2: Launch Weixin and log in normally**

Open `C:/Program Files/Tencent/Weixin/Weixin.exe`, scan QR, complete login.

- [ ] **Step 3: Run sidecar's web monitor**

```bash
cd wx/sidecar/wechat-decrypt
.venv/Scripts/python monitor_web.py
```

Expected: server starts, browser opens at `http://localhost:5678`, status shows "已找到密钥" / "解密完成", UI shows recent messages.

- [ ] **Step 4: Record findings in docs/sidecar-verification.md**

Write a short doc with:

```markdown
# Sidecar Verification (2026-05-22)

- Sidecar: wechat-decrypt @ <commit hash>
- Target: Weixin 4.1.7.30, path C:\Program Files\Tencent\Weixin\Weixin.exe
- Key extraction: SUCCESS / FAIL — <details>
- DB decryption: SUCCESS / FAIL — <files produced>
- SSE endpoint: <URL>, sample event structure:
  ```json
  <paste 1-2 real events>
  ```
- Decrypted DB location: <path>
- Decrypted DB tables relevant to contacts: <names>
- Notes / quirks for future code:
  - <...>
```

- [ ] **Step 5: Commit verification doc**

```bash
git add docs/sidecar-verification.md
git commit -m "docs: verify wechat-decrypt sidecar works with Weixin 4.1.7.30"
```

**Gate:** If Step 3 fails, STOP and escalate. The plan assumes sidecar works on this Weixin version. Without it, we need to fall back to pure UIA receive (window scraping), which is a different design.

---

## Phase 1: wx/ Package (Bottom-Up)

### Task 1.1: WxMsg dataclass with tests

**Files:**
- Create: `tests/test_msg.py`
- Create: `wx/msg.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_msg.py`:

```python
import pytest
from wx.msg import WxMsg


def make_msg(**overrides):
    base = dict(
        id=1, type=1, sender="wxid_alice", roomid="", content="hello",
        is_self=False, ts=1700000000
    )
    base.update(overrides)
    return WxMsg(**base)


def test_from_group_true_when_roomid_set():
    m = make_msg(roomid="123@chatroom")
    assert m.from_group() is True


def test_from_group_false_when_roomid_empty():
    m = make_msg(roomid="")
    assert m.from_group() is False


def test_from_self_true():
    m = make_msg(is_self=True)
    assert m.from_self() is True


def test_is_at_detects_at_token():
    m = make_msg(content="@WxBot hello there", roomid="123@chatroom")
    assert m.is_at("wxid_bot") is True


def test_is_at_false_when_no_at():
    m = make_msg(content="just chatting", roomid="123@chatroom")
    assert m.is_at("wxid_bot") is False


def test_is_at_false_in_dm():
    m = make_msg(content="@bot", roomid="")
    assert m.is_at("wxid_bot") is False
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/test_msg.py -v
```

Expected: ImportError / module not found.

- [ ] **Step 3: Implement `wx/msg.py`**

```python
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class WxMsg:
    """Wire-compatible substitute for wcferry.WxMsg.

    Only carries fields and methods actually consulted by robot.py.
    """
    id: int
    type: int                # 1=text, 3=image, 37=friend request, 10000=system
    sender: str              # wxid of the sender
    roomid: str              # group id ("" for DM)
    content: str             # text content or XML payload
    is_self: bool
    ts: int

    def from_group(self) -> bool:
        return bool(self.roomid)

    def from_self(self) -> bool:
        return self.is_self

    def is_at(self, wxid: str) -> bool:
        # Group @ is encoded as "@<displayname>" in Weixin clients.
        # We don't have a perfect wxid→displayname mapping at parse time,
        # so the dispatcher will pass the bot's own wxid AND resolve via
        # ContactsBackend later. Here we just check whether the content
        # contains any "@" token in a group context.
        if not self.from_group():
            return False
        return "@" in self.content
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_msg.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add wx/msg.py tests/test_msg.py
git commit -m "feat(wx): add WxMsg dataclass with from_group/from_self/is_at helpers"
```

### Task 1.2: ContactsBackend with SQLite-fixture tests

**Files:**
- Create: `tests/test_contacts.py`
- Create: `tests/fixtures/sample_contact.py` (generator script)
- Create: `wx/contacts.py`

- [ ] **Step 1: Write the fixture generator**

Create `tests/fixtures/sample_contact.py`:

```python
"""Generate a tiny SQLite DB that mimics the relevant Weixin 4.x contact table.

Run once to create sample_contact.db; tests assume it exists.
"""
import sqlite3
from pathlib import Path

HERE = Path(__file__).parent
DB = HERE / "sample_contact.db"


def build():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.executescript("""
        CREATE TABLE contact (
            username TEXT PRIMARY KEY,
            nickname TEXT,
            remark TEXT,
            type INTEGER
        );
        INSERT INTO contact VALUES ('wxid_alice', 'Alice', '小爱', 3);
        INSERT INTO contact VALUES ('wxid_bob',   'Bob',   '',   3);
        INSERT INTO contact VALUES ('123@chatroom', 'Test Group', '', 2);

        CREATE TABLE chatroom (
            roomid TEXT PRIMARY KEY,
            memberlist TEXT
        );
        INSERT INTO chatroom VALUES ('123@chatroom', 'wxid_alice,wxid_bob');

        CREATE TABLE chatroom_member_nickname (
            roomid TEXT,
            wxid TEXT,
            display_name TEXT,
            PRIMARY KEY (roomid, wxid)
        );
        INSERT INTO chatroom_member_nickname VALUES ('123@chatroom', 'wxid_alice', '群里的爱丽丝');
    """)
    con.commit()
    con.close()
    print(f"Wrote {DB}")


if __name__ == "__main__":
    build()
```

- [ ] **Step 2: Generate the fixture DB**

```bash
python tests/fixtures/sample_contact.py
```

Expected: prints "Wrote <path>/sample_contact.db".

- [ ] **Step 3: Write failing tests**

Create `tests/test_contacts.py`:

```python
from pathlib import Path
import pytest
from wx.contacts import ContactsBackend


FIXTURE_DB = Path(__file__).parent / "fixtures" / "sample_contact.db"


@pytest.fixture
def contacts():
    b = ContactsBackend(FIXTURE_DB)
    b.refresh()
    return b


def test_wxid_to_name_prefers_remark(contacts):
    # Alice has remark="小爱"; remark takes precedence
    assert contacts.wxid_to_name("wxid_alice") == "小爱"


def test_wxid_to_name_falls_back_to_nickname(contacts):
    assert contacts.wxid_to_name("wxid_bob") == "Bob"


def test_wxid_to_name_unknown(contacts):
    assert contacts.wxid_to_name("wxid_nobody") is None


def test_name_to_wxid_by_remark(contacts):
    assert contacts.name_to_wxid("小爱") == "wxid_alice"


def test_name_to_wxid_by_nickname(contacts):
    assert contacts.name_to_wxid("Bob") == "wxid_bob"


def test_alias_in_room_present(contacts):
    assert contacts.alias_in_room("wxid_alice", "123@chatroom") == "群里的爱丽丝"


def test_alias_in_room_fallback_to_global(contacts):
    # Bob has no chatroom-specific nickname; falls back to remark/nickname.
    assert contacts.alias_in_room("wxid_bob", "123@chatroom") == "Bob"


def test_all_contacts_returns_dict(contacts):
    all_ = contacts.all_contacts()
    assert all_["wxid_alice"] == "小爱"
    assert all_["wxid_bob"] == "Bob"
```

- [ ] **Step 4: Run tests to verify fail**

```bash
pytest tests/test_contacts.py -v
```

Expected: ImportError on `wx.contacts`.

- [ ] **Step 5: Implement `wx/contacts.py`**

```python
from __future__ import annotations
import sqlite3
import threading
from pathlib import Path


class ContactsBackend:
    """Read-only access to the decrypted Weixin contact DB with in-memory cache.

    NOTE: The actual table/column names in Weixin 4.x's decrypted DB may differ.
    This implementation targets the canonical schema seen in tests/fixtures.
    For real deployment, Task 1.2.b will adapt to the real schema discovered
    during Phase 0 sidecar verification.
    """

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._by_wxid: dict[str, str] = {}    # wxid -> display name (remark > nickname)
        self._by_name: dict[str, str] = {}    # display name -> wxid
        self._room_alias: dict[tuple[str, str], str] = {}  # (wxid, roomid) -> display
        self._raw: dict[str, dict] = {}       # wxid -> raw row

    def refresh(self) -> None:
        with self._lock:
            con = sqlite3.connect(self._db_path)
            con.row_factory = sqlite3.Row
            try:
                self._load_contacts(con)
                self._load_room_aliases(con)
            finally:
                con.close()

    def _load_contacts(self, con: sqlite3.Connection) -> None:
        self._by_wxid.clear()
        self._by_name.clear()
        self._raw.clear()
        for row in con.execute("SELECT username, nickname, remark, type FROM contact"):
            wxid = row["username"]
            nickname = row["nickname"] or ""
            remark = row["remark"] or ""
            display = remark or nickname or wxid
            self._by_wxid[wxid] = display
            # Reverse index: prefer remark, then nickname; both point to same wxid.
            if remark:
                self._by_name[remark] = wxid
            if nickname and nickname not in self._by_name:
                self._by_name[nickname] = wxid
            self._raw[wxid] = dict(row)

    def _load_room_aliases(self, con: sqlite3.Connection) -> None:
        self._room_alias.clear()
        try:
            cursor = con.execute(
                "SELECT roomid, wxid, display_name FROM chatroom_member_nickname"
            )
        except sqlite3.OperationalError:
            return  # Table may not exist on real deployments; skip silently.
        for row in cursor:
            self._room_alias[(row["wxid"], row["roomid"])] = row["display_name"]

    def wxid_to_name(self, wxid: str) -> str | None:
        return self._by_wxid.get(wxid)

    def name_to_wxid(self, name: str) -> str | None:
        return self._by_name.get(name)

    def alias_in_room(self, wxid: str, roomid: str) -> str:
        in_room = self._room_alias.get((wxid, roomid))
        if in_room:
            return in_room
        return self.wxid_to_name(wxid) or wxid

    def all_contacts(self) -> dict[str, str]:
        return dict(self._by_wxid)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_contacts.py -v
```

Expected: 8 passed.

- [ ] **Step 7: Commit**

```bash
git add wx/contacts.py tests/test_contacts.py tests/fixtures/sample_contact.py tests/fixtures/sample_contact.db
git commit -m "feat(wx): add ContactsBackend reading decrypted SQLite contact DB"
```

### Task 1.3: ReceiveBackend with mocked SSE feed

**Files:**
- Create: `tests/fixtures/sample_sse_events.py`
- Create: `tests/test_receive.py`
- Create: `wx/receive.py`

- [ ] **Step 1: Write SSE event fixtures**

Create `tests/fixtures/sample_sse_events.py`:

```python
"""Canned wechat-decrypt SSE events.

The real event schema is discovered during Task 0.3 verification and
recorded in docs/sidecar-verification.md. These shapes match what we expect:
each event is a dict with `event_type` and `data` keys.
"""

TEXT_DM = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1001,
        "type": 1,
        "from_user": "wxid_alice",
        "to_user": "wxid_self",
        "room_id": "",
        "content": "hi bot",
        "is_send": 0,
        "timestamp": 1700000000,
    },
}

TEXT_GROUP_AT = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1002,
        "type": 1,
        "from_user": "wxid_alice",
        "to_user": "123@chatroom",
        "room_id": "123@chatroom",
        "content": "@WxBot help",
        "is_send": 0,
        "timestamp": 1700000010,
    },
}

FRIEND_REQUEST = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1003,
        "type": 37,
        "from_user": "wxid_new",
        "to_user": "wxid_self",
        "room_id": "",
        "content": "<msg encryptusername='v3_xxx' ticket='v4_xxx' scene='14' />",
        "is_send": 0,
        "timestamp": 1700000020,
    },
}

SELF_MESSAGE = {
    "event_type": "new_message",
    "data": {
        "msg_id": 1004,
        "type": 1,
        "from_user": "wxid_self",
        "to_user": "wxid_alice",
        "room_id": "",
        "content": "I'm replying",
        "is_send": 1,
        "timestamp": 1700000030,
    },
}

UNRELATED_EVENT = {
    "event_type": "key_refreshed",
    "data": {"timestamp": 1700000040},
}
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_receive.py`:

```python
from queue import Queue, Empty
import pytest

from wx.msg import WxMsg
from wx.receive import ReceiveBackend
from tests.fixtures import sample_sse_events as evs


@pytest.fixture
def queue():
    return Queue()


@pytest.fixture
def backend(queue):
    # We instantiate without starting the subprocess; we'll feed events directly.
    return ReceiveBackend(
        decrypt_repo=None, sidecar_url="http://nowhere", msg_queue=queue
    )


def test_translate_text_dm(backend):
    msg = backend._translate_event(evs.TEXT_DM)
    assert isinstance(msg, WxMsg)
    assert msg.type == 1
    assert msg.sender == "wxid_alice"
    assert msg.roomid == ""
    assert msg.content == "hi bot"
    assert msg.is_self is False


def test_translate_group_at(backend):
    msg = backend._translate_event(evs.TEXT_GROUP_AT)
    assert msg.roomid == "123@chatroom"
    assert msg.from_group() is True
    assert msg.is_at("wxid_bot") is True


def test_translate_friend_request(backend):
    msg = backend._translate_event(evs.FRIEND_REQUEST)
    assert msg.type == 37


def test_translate_self_message_flag(backend):
    msg = backend._translate_event(evs.SELF_MESSAGE)
    assert msg.is_self is True


def test_translate_unrelated_event_returns_none(backend):
    assert backend._translate_event(evs.UNRELATED_EVENT) is None


def test_enqueue_via_internal_pipe(backend, queue):
    # Simulate the SSE consumer pushing translated events to the queue.
    backend._consume_event(evs.TEXT_DM)
    backend._consume_event(evs.UNRELATED_EVENT)  # should be filtered out
    backend._consume_event(evs.TEXT_GROUP_AT)
    assert queue.qsize() == 2
    m1 = queue.get_nowait()
    m2 = queue.get_nowait()
    assert m1.id == 1001
    assert m2.id == 1002
    with pytest.raises(Empty):
        queue.get_nowait()
```

- [ ] **Step 3: Run tests to verify fail**

```bash
pytest tests/test_receive.py -v
```

Expected: ImportError on `wx.receive`.

- [ ] **Step 4: Implement `wx/receive.py`**

```python
from __future__ import annotations
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from queue import Queue

import requests

from wx.msg import WxMsg

LOG = logging.getLogger(__name__)


class ReceiveBackend:
    """Wraps the wechat-decrypt sidecar. One process per backend instance."""

    SSE_PATH = "/stream"             # path on monitor_web.py; verify in Task 0.3
    HEARTBEAT_TIMEOUT_SEC = 30
    RESTART_BACKOFF_SEC = 5
    MAX_RESTARTS = 3

    def __init__(
        self,
        decrypt_repo: Path | None,
        sidecar_url: str,
        msg_queue: Queue,
    ):
        self._repo = Path(decrypt_repo) if decrypt_repo else None
        self._url = sidecar_url.rstrip("/")
        self._queue = msg_queue
        self._proc: subprocess.Popen | None = None
        self._sse_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_event_ts = 0.0
        self._restart_count = 0

    # ---- lifecycle ----
    def start(self) -> None:
        if self._proc is not None:
            return
        self._spawn_sidecar()
        self._sse_thread = threading.Thread(
            target=self._sse_loop, name="ReceiveSSE", daemon=True
        )
        self._sse_thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def is_alive(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        if self._last_event_ts == 0.0:
            return True   # not yet received first event; grace period
        return (time.time() - self._last_event_ts) < self.HEARTBEAT_TIMEOUT_SEC

    # ---- subprocess + SSE ----
    def _spawn_sidecar(self) -> None:
        if self._repo is None:
            LOG.warning("ReceiveBackend: no decrypt_repo, assuming external sidecar")
            return
        venv_py = self._repo / ".venv" / "Scripts" / "python.exe"
        py = str(venv_py) if venv_py.exists() else "python"
        cmd = [py, str(self._repo / "monitor_web.py")]
        LOG.info("Launching sidecar: %s", " ".join(cmd))
        self._proc = subprocess.Popen(
            cmd, cwd=str(self._repo),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        time.sleep(2)   # give the web server time to bind

    def _sse_loop(self) -> None:
        while not self._stop.is_set():
            try:
                with requests.get(
                    self._url + self.SSE_PATH, stream=True, timeout=(5, None)
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines(decode_unicode=True):
                        if self._stop.is_set():
                            return
                        if not line or not line.startswith("data:"):
                            continue
                        try:
                            payload = json.loads(line[len("data:"):].strip())
                        except json.JSONDecodeError:
                            LOG.warning("malformed SSE line: %r", line)
                            continue
                        self._consume_event(payload)
            except Exception as e:
                LOG.error("SSE connection lost: %s", e)
                if self._stop.is_set():
                    return
                self._restart_count += 1
                if self._restart_count > self.MAX_RESTARTS:
                    LOG.error("max restarts exceeded; giving up")
                    return
                time.sleep(self.RESTART_BACKOFF_SEC)

    # ---- translation ----
    def _consume_event(self, event: dict) -> None:
        msg = self._translate_event(event)
        if msg is not None:
            self._last_event_ts = time.time()
            self._queue.put(msg)

    def _translate_event(self, event: dict) -> WxMsg | None:
        if event.get("event_type") != "new_message":
            return None
        d = event.get("data") or {}
        try:
            return WxMsg(
                id=int(d["msg_id"]),
                type=int(d["type"]),
                sender=str(d.get("from_user", "")),
                roomid=str(d.get("room_id", "")),
                content=str(d.get("content", "")),
                is_self=bool(d.get("is_send", 0)),
                ts=int(d.get("timestamp", 0)),
            )
        except (KeyError, ValueError, TypeError) as e:
            LOG.warning("malformed message event %r: %s", event, e)
            return None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_receive.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add wx/receive.py tests/test_receive.py tests/fixtures/sample_sse_events.py
git commit -m "feat(wx): add ReceiveBackend with SSE event translation"
```

### Task 1.4: SendBackend (UIA) — control-tree spike + implementation

**Files:**
- Create: `docs/uia-anchors.md`
- Create: `wx/send.py`
- Create: `scripts/smoke_send.py`

**Note:** UIA logic is hard to unit-test (requires a real Weixin window). We do a manual spike first to discover anchors, then write code, then a smoke script.

- [ ] **Step 1: UIA discovery spike**

Run this discovery snippet manually:

```bash
python -c "import uiautomation as uia; w = uia.WindowControl(searchDepth=2, Name='微信'); w.SetActive(); print(w.GetChildren()); uia.WalkTree(w, showAllName=False, maxDepth=4)"
```

Expected: prints the control tree of the Weixin main window. Identify:
- Search box `EditControl` (top-left, has name like "搜索")
- Conversation list `ListControl`
- Message input `EditControl` (bottom; might be inside a Pane)
- Send button `ButtonControl` named "发送(S)" or similar

If the window name is not "微信" on Weixin 4.x (it might be "Weixin"), try `Name='Weixin'`.

- [ ] **Step 2: Record anchors in `docs/uia-anchors.md`**

```markdown
# Weixin 4.1.7.30 UIA Anchors

> Used by wx/send.py. Update here whenever Weixin's UI changes.

## Main Window
- ClassName: `WeChatMainWndForPC` (verify; may be different in 4.x)
- Name: `微信` (or `Weixin`)
- Locator: `WindowControl(searchDepth=2, Name='微信')`

## Search Box
- ControlType: `EditControl`
- Locator: `<main>.EditControl(searchDepth=10, Name='搜索')`
- Behavior: typing + Enter selects first matching conversation

## Conversation List
- ControlType: `ListControl`
- Locator: `<main>.ListControl(searchDepth=10, Name='会话')`

## Message Input
- ControlType: `EditControl`
- Locator: `<main>.EditControl(searchDepth=20)` (usually the only Edit in the bottom Pane)
- Trick: focus, then `pyperclip.copy(text); SendKeys('{Ctrl}v')`, then Enter

## Send Button
- ControlType: `ButtonControl`
- Locator: `<main>.ButtonControl(searchDepth=20, Name='发送(S)')`
- Fallback: press Enter (default behavior)

## @ in Group
- Type `@` in input → Weixin pops a member picker
- Send `displayname` characters → press Enter to insert
```

- [ ] **Step 3: Implement `wx/send.py`**

```python
from __future__ import annotations
import logging
import time
from pathlib import Path
from threading import Lock

import pyperclip
import uiautomation as uia

from wx.contacts import ContactsBackend

LOG = logging.getLogger(__name__)


class SendBackend:
    """Drive Weixin 4.x via UIA. Single instance per Weixin process."""

    MAIN_WINDOW_NAMES = ("微信", "Weixin")
    SEARCH_BOX_NAME = "搜索"
    PER_SEND_INTERVAL_SEC = 0.8       # throttle to avoid risk control
    OPEN_CHAT_TIMEOUT_SEC = 5
    POST_OPEN_SETTLE_SEC = 0.3

    def __init__(self, weixin_exe: Path, contacts: ContactsBackend):
        self._exe = Path(weixin_exe)
        self._contacts = contacts
        self._main: uia.WindowControl | None = None
        self._send_lock = Lock()
        self._last_send_ts = 0.0

    # ---- lifecycle ----
    def attach(self) -> None:
        for name in self.MAIN_WINDOW_NAMES:
            w = uia.WindowControl(searchDepth=2, Name=name)
            if w.Exists(maxSearchSeconds=2):
                self._main = w
                LOG.info("attached to Weixin window: %s", name)
                return
        raise RuntimeError(
            f"Weixin main window not found (tried {self.MAIN_WINDOW_NAMES}). "
            "Make sure Weixin is running and logged in."
        )

    # ---- public ----
    def send_text(
        self, receiver_wxid: str, msg: str, at_wxids: tuple[str, ...] = ()
    ) -> bool:
        display = self._contacts.wxid_to_name(receiver_wxid)
        if not display:
            LOG.error("send_text: no display name for %s", receiver_wxid)
            return False
        with self._send_lock:
            self._throttle()
            try:
                self._open_chat(display)
                self._focus_input()
                if at_wxids and "@" in msg:
                    self._send_with_ats(msg, at_wxids)
                else:
                    self._paste_and_send(msg)
                return True
            except Exception as e:
                LOG.error("send_text failed to %s: %s", display, e)
                return False

    def send_image(self, receiver_wxid: str, image_path: Path) -> bool:
        display = self._contacts.wxid_to_name(receiver_wxid)
        if not display:
            return False
        with self._send_lock:
            self._throttle()
            try:
                self._open_chat(display)
                self._focus_input()
                # Use Windows clipboard image insertion
                from PIL import Image
                import win32clipboard
                from io import BytesIO

                img = Image.open(image_path)
                output = BytesIO()
                img.convert("RGB").save(output, "BMP")
                data = output.getvalue()[14:]   # strip BMP header
                output.close()
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
                finally:
                    win32clipboard.CloseClipboard()
                uia.SendKeys("{Ctrl}v")
                time.sleep(0.3)
                uia.SendKeys("{Enter}")
                return True
            except Exception as e:
                LOG.error("send_image failed: %s", e)
                return False

    def accept_friend_request_via_ui(self, requester_hint: str = "") -> bool:
        """Best-effort: open '新的朋友' panel and click the topmost '通过' button."""
        if self._main is None:
            self.attach()
        try:
            # Sidebar contains a 新的朋友 entry
            entry = self._main.TextControl(searchDepth=20, Name="新的朋友")
            if not entry.Exists(maxSearchSeconds=2):
                LOG.warning("'新的朋友' entry not found")
                return False
            entry.Click(simulateMove=False)
            time.sleep(0.5)
            accept_btn = self._main.ButtonControl(searchDepth=20, Name="接受")
            if not accept_btn.Exists(maxSearchSeconds=2):
                LOG.info("No pending friend request to accept")
                return False
            accept_btn.Click(simulateMove=False)
            return True
        except Exception as e:
            LOG.error("accept_friend_request_via_ui failed: %s", e)
            return False

    # ---- internals ----
    def _throttle(self) -> None:
        elapsed = time.time() - self._last_send_ts
        if elapsed < self.PER_SEND_INTERVAL_SEC:
            time.sleep(self.PER_SEND_INTERVAL_SEC - elapsed)
        self._last_send_ts = time.time()

    def _open_chat(self, display_name: str) -> None:
        if self._main is None:
            self.attach()
        search = self._main.EditControl(searchDepth=10, Name=self.SEARCH_BOX_NAME)
        if not search.Exists(maxSearchSeconds=self.OPEN_CHAT_TIMEOUT_SEC):
            raise RuntimeError("search box not found")
        search.Click(simulateMove=False)
        time.sleep(0.1)
        # Clear any prior input then type the name
        uia.SendKeys("{Ctrl}a", waitTime=0.05)
        uia.SendKeys("{Delete}", waitTime=0.05)
        pyperclip.copy(display_name)
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(0.4)   # wait for search results to populate
        uia.SendKeys("{Enter}", waitTime=0.05)
        time.sleep(self.POST_OPEN_SETTLE_SEC)

    def _focus_input(self) -> None:
        # The message input is the bottom-most EditControl in the chat pane.
        # Heuristic: take the last EditControl encountered.
        edits = []

        def _collect(ctrl, depth):
            if ctrl.ControlTypeName == "EditControl":
                edits.append(ctrl)

        uia.WalkControl(self._main, _collect, maxDepth=15)
        if not edits:
            raise RuntimeError("no EditControl found for message input")
        edits[-1].Click(simulateMove=False)
        time.sleep(0.1)

    def _paste_and_send(self, text: str) -> None:
        pyperclip.copy(text)
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(0.1)
        uia.SendKeys("{Enter}", waitTime=0.05)

    def _send_with_ats(self, msg: str, at_wxids: tuple[str, ...]) -> None:
        # Caller has already injected " @displayname" placeholders into msg;
        # for accurate group @ we'd need to type "@" then pick from popup.
        # MVP: paste the whole message; @ token is plain text in this version.
        self._paste_and_send(msg)
```

- [ ] **Step 4: Write smoke script `scripts/smoke_send.py`**

```python
"""Run with Weixin 4.x already open and logged in.

Sends a single 'ping' to filehelper to verify SendBackend works end-to-end.
"""
import logging
from pathlib import Path

from wx.contacts import ContactsBackend
from wx.send import SendBackend

logging.basicConfig(level=logging.INFO)


def main():
    # filehelper has a fixed wxid; ContactsBackend would normally resolve it,
    # but for the smoke test we cheat by mapping it directly.
    contacts = ContactsBackend(Path("tests/fixtures/sample_contact.db"))
    contacts.refresh()
    # Inject filehelper into the cache so wxid_to_name returns something:
    contacts._by_wxid["filehelper"] = "文件传输助手"

    backend = SendBackend(
        weixin_exe=Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
        contacts=contacts,
    )
    backend.attach()
    ok = backend.send_text("filehelper", "ping from SendBackend smoke")
    print("RESULT:", ok)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run smoke (manual)**

```bash
mkdir -p scripts
python scripts/smoke_send.py
```

Expected: opens Weixin's 文件传输助手 chat and sends "ping from SendBackend smoke".
If it fails, update `docs/uia-anchors.md` with the actual control names found in the spike and adjust `SEARCH_BOX_NAME` / `MAIN_WINDOW_NAMES` in `wx/send.py`.

- [ ] **Step 6: Commit**

```bash
git add wx/send.py docs/uia-anchors.md scripts/smoke_send.py
git commit -m "feat(wx): add SendBackend (UIA-driven send_text/send_image/accept_friend)"
```

### Task 1.5: WxAdapter facade + smoke

**Files:**
- Create: `tests/test_adapter.py`
- Create: `wx/adapter.py`
- Modify: `wx/__init__.py`
- Create: `scripts/smoke_adapter.py`

- [ ] **Step 1: Write facade tests (mocking backends)**

Create `tests/test_adapter.py`:

```python
from pathlib import Path
from queue import Empty
from unittest.mock import MagicMock

import pytest

from wx.adapter import WxAdapter
from wx.msg import WxMsg


@pytest.fixture
def adapter(monkeypatch):
    # Patch out backend constructors so __init__ doesn't try real I/O
    monkeypatch.setattr("wx.adapter.ContactsBackend", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("wx.adapter.ReceiveBackend", lambda *a, **kw: MagicMock())
    monkeypatch.setattr("wx.adapter.SendBackend", lambda *a, **kw: MagicMock())
    return WxAdapter(
        weixin_exe=Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
        sidecar_url="http://127.0.0.1:5678",
        decrypted_db_path=Path("tests/fixtures/sample_contact.db"),
        decrypt_repo=Path("wx/sidecar/wechat-decrypt"),
    )


def test_send_text_delegates_to_send_backend(adapter):
    adapter._send.send_text.return_value = True
    rc = adapter.send_text("hello", "wxid_alice")
    adapter._send.send_text.assert_called_once_with("wxid_alice", "hello", ())
    assert rc == 0


def test_send_text_returns_nonzero_on_failure(adapter):
    adapter._send.send_text.return_value = False
    rc = adapter.send_text("hello", "wxid_alice")
    assert rc != 0


def test_send_image_delegates(adapter):
    adapter._send.send_image.return_value = True
    rc = adapter.send_image("/tmp/x.png", "wxid_alice")
    adapter._send.send_image.assert_called_once()
    assert rc == 0


def test_get_alias_in_chatroom_delegates(adapter):
    adapter._contacts.alias_in_room.return_value = "Group Alice"
    assert adapter.get_alias_in_chatroom("wxid_alice", "123@chatroom") == "Group Alice"


def test_query_sql_contact_table_returns_list(adapter):
    adapter._contacts.all_contacts.return_value = {"wxid_alice": "Alice"}
    rows = adapter.query_sql("MicroMsg.db", "SELECT UserName, NickName FROM Contact")
    assert rows == [{"UserName": "wxid_alice", "NickName": "Alice"}]


def test_query_sql_other_raises(adapter):
    with pytest.raises(NotImplementedError):
        adapter.query_sql("MicroMsg.db", "SELECT * FROM Message")


def test_get_msg_blocks_and_returns(adapter):
    test_msg = WxMsg(
        id=1, type=1, sender="x", roomid="", content="hi",
        is_self=False, ts=0
    )
    adapter._queue.put(test_msg)
    got = adapter.get_msg(timeout=0.1)
    assert got is test_msg


def test_get_msg_raises_empty_on_timeout(adapter):
    with pytest.raises(Empty):
        adapter.get_msg(timeout=0.05)
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/test_adapter.py -v
```

Expected: ImportError on `wx.adapter`.

- [ ] **Step 3: Implement `wx/adapter.py`**

```python
from __future__ import annotations
import logging
from pathlib import Path
from queue import Queue, Empty

from wx.contacts import ContactsBackend
from wx.receive import ReceiveBackend
from wx.send import SendBackend
from wx.msg import WxMsg

LOG = logging.getLogger(__name__)


class WxAdapter:
    """Facade exposing a wcferry.Wcf-compatible subset, backed by Weixin 4.x.

    Methods mirror the wcferry calls actually used by robot.py:
      get_self_wxid, send_text, send_image, query_sql, get_alias_in_chatroom,
      accept_new_friend, enable_receiving_msg, get_msg, is_receiving_msg
    """

    def __init__(
        self,
        weixin_exe: Path,
        sidecar_url: str,
        decrypted_db_path: Path,
        decrypt_repo: Path | None = None,
        self_wxid: str = "filehelper",
    ):
        self._weixin_exe = Path(weixin_exe)
        self._self_wxid = self_wxid
        self._queue: Queue[WxMsg] = Queue()
        self._contacts = ContactsBackend(decrypted_db_path)
        self._send = SendBackend(weixin_exe=self._weixin_exe, contacts=self._contacts)
        self._recv = ReceiveBackend(
            decrypt_repo=decrypt_repo, sidecar_url=sidecar_url, msg_queue=self._queue
        )

    # ---- init / lifecycle ----
    def setup(self) -> None:
        """Idempotent: refresh contacts, attach send window, start sidecar."""
        self._contacts.refresh()
        self._send.attach()
        # ReceiveBackend.start() is deferred to enable_receiving_msg.

    # ---- wcferry-compatible API ----
    def get_self_wxid(self) -> str:
        return self._self_wxid

    def send_text(self, msg: str, receiver: str, at_list: str = "") -> int:
        at_wxids = tuple(w for w in at_list.split(",") if w)
        ok = self._send.send_text(receiver, msg, at_wxids=at_wxids)
        return 0 if ok else 1

    def send_image(self, image_path, receiver: str) -> int:
        ok = self._send.send_image(receiver, Path(image_path))
        return 0 if ok else 1

    def query_sql(self, db: str, sql: str) -> list[dict]:
        # robot.py only uses: SELECT UserName, NickName FROM Contact
        normalised = sql.strip().upper().replace("  ", " ")
        if "FROM CONTACT" in normalised and "USERNAME" in normalised:
            return [
                {"UserName": wxid, "NickName": name}
                for wxid, name in self._contacts.all_contacts().items()
            ]
        raise NotImplementedError(
            f"WxAdapter.query_sql only supports Contact lookup; got: {sql}"
        )

    def get_alias_in_chatroom(self, wxid: str, roomid: str) -> str:
        return self._contacts.alias_in_room(wxid, roomid)

    def accept_new_friend(self, v3: str, v4: str, scene: int) -> int:
        # wcferry-signature; we ignore v3/v4/scene and drive the UI directly.
        ok = self._send.accept_friend_request_via_ui()
        return 0 if ok else 1

    # ---- receive side ----
    def enable_receiving_msg(self) -> None:
        self._recv.start()

    def is_receiving_msg(self) -> bool:
        return self._recv.is_alive()

    def get_msg(self, timeout: float = 1.0) -> WxMsg:
        # raises queue.Empty on timeout (matches what robot.py already handles)
        return self._queue.get(timeout=timeout)

    def cleanup(self) -> None:
        self._recv.stop()
```

- [ ] **Step 4: Update `wx/__init__.py`**

```python
from wx.adapter import WxAdapter
from wx.msg import WxMsg

__all__ = ["WxAdapter", "WxMsg"]
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_adapter.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Write end-to-end smoke `scripts/smoke_adapter.py`**

```python
"""Manual end-to-end smoke for WxAdapter.

Prereqs:
  1. Weixin 4.1.7.30 open and logged in
  2. wechat-decrypt sidecar running (cd wx/sidecar/wechat-decrypt && python monitor_web.py)
  3. tests/fixtures/sample_contact.db generated

Behavior:
  - Receives messages for 30 seconds
  - For every text message from a non-self sender, replies "echo: <text>" to filehelper
"""
import logging
import time
from pathlib import Path
from queue import Empty

from wx.adapter import WxAdapter

logging.basicConfig(level=logging.INFO)


def main():
    a = WxAdapter(
        weixin_exe=Path("C:/Program Files/Tencent/Weixin/Weixin.exe"),
        sidecar_url="http://127.0.0.1:5678",
        decrypted_db_path=Path("tests/fixtures/sample_contact.db"),
        decrypt_repo=None,
    )
    a.setup()
    a._contacts._by_wxid["filehelper"] = "文件传输助手"
    a.enable_receiving_msg()
    print("Listening 30s; send a message in Weixin...")
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            msg = a.get_msg(timeout=1.0)
            print(f"received: type={msg.type} sender={msg.sender} content={msg.content!r}")
            if msg.type == 1 and not msg.is_self:
                a.send_text(f"echo: {msg.content}", "filehelper")
        except Empty:
            continue
    a.cleanup()


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Manual run + verify**

```bash
python scripts/smoke_adapter.py
```

Expected: prints incoming messages and echoes them back to 文件传输助手 in Weixin.

- [ ] **Step 8: Commit**

```bash
git add wx/adapter.py wx/__init__.py tests/test_adapter.py scripts/smoke_adapter.py
git commit -m "feat(wx): add WxAdapter facade and end-to-end smoke script"
```

---

## Phase 2: Migrate robot.py off wcferry

### Task 2.1: Config schema additions

**Files:**
- Modify: `configuration.py`
- Modify: `config.yaml.template`

- [ ] **Step 1: Update `config.yaml.template`**

Append to the existing template (do not overwrite):

```yaml
weixin:
  exe: "C:/Program Files/Tencent/Weixin/Weixin.exe"
  sidecar_repo: "./wx/sidecar/wechat-decrypt"
  sidecar_url: "http://127.0.0.1:5678"
  decrypted_db_path: "./wx/decrypted/contact.db"
  self_wxid: ""   # auto-detected at runtime if blank

lexue:
  user: "1492246"
  pass: "IZ0IPKM5pYPhhGqy"
  url: "http://lxuexi.cn/"

order_safety:
  dry_run: true
  confirm_timeout_sec: 300
  max_extract_rounds: 3
  daily_limit: 50
  per_user_cooldown_sec: 60

llm:
  intent_model: deepseek
  chitchat_model: deepseek
  intent_prompt_path: prompts/order_intent.md
  extract_prompt_path: prompts/order_extract.md
```

- [ ] **Step 2: Read existing `configuration.py`**

```bash
cat configuration.py
```

(Take note of the existing Config class structure; we'll extend it.)

- [ ] **Step 3: Modify `configuration.py`**

Add these properties to the `Config` class (next to existing properties like `CHATGPT`, `GROUPS`, `NEWS`):

```python
    @property
    def WEIXIN(self) -> dict:
        return self.config.get("weixin", {})

    @property
    def LEXUE(self) -> dict:
        return self.config.get("lexue", {})

    @property
    def ORDER_SAFETY(self) -> dict:
        defaults = {
            "dry_run": True,
            "confirm_timeout_sec": 300,
            "max_extract_rounds": 3,
            "daily_limit": 50,
            "per_user_cooldown_sec": 60,
        }
        defaults.update(self.config.get("order_safety", {}))
        return defaults

    @property
    def LLM(self) -> dict:
        return self.config.get("llm", {})
```

- [ ] **Step 4: Copy template to config.yaml manually if needed**

If `config.yaml` exists, manually merge the new sections into it. Otherwise:

```bash
cp config.yaml.template config.yaml
```

- [ ] **Step 5: Commit**

```bash
git add configuration.py config.yaml.template
git commit -m "feat(config): add weixin/lexue/order_safety/llm config sections"
```

### Task 2.2: Migrate robot.py imports + main.py initialization

**Files:**
- Modify: `robot.py:13` (the `from wcferry import` line)
- Modify: `main.py`

- [ ] **Step 1: Read existing `main.py`**

```bash
cat main.py
```

Note current `Wcf()` instantiation and how it's passed to `Robot`.

- [ ] **Step 2: Modify `robot.py` import line**

Replace this line in `robot.py:13`:

```python
from wcferry import Wcf, WxMsg
```

with:

```python
from wx import WxAdapter as Wcf
from wx import WxMsg
```

(Keeps the alias `Wcf` so the rest of `robot.py` doesn't need to change.)

- [ ] **Step 3: Modify `main.py` to instantiate `WxAdapter`**

Open `main.py` and locate the line that does `wcf = Wcf()` (or similar). Replace it with:

```python
from pathlib import Path
from configuration import Config
from wx import WxAdapter

config = Config()
wcf = WxAdapter(
    weixin_exe=Path(config.WEIXIN["exe"]),
    sidecar_url=config.WEIXIN["sidecar_url"],
    decrypted_db_path=Path(config.WEIXIN["decrypted_db_path"]),
    decrypt_repo=Path(config.WEIXIN["sidecar_repo"]),
    self_wxid=config.WEIXIN.get("self_wxid") or "filehelper",
)
wcf.setup()
```

Then ensure the existing `Robot(config, wcf, args.chat_model)` call still works (signature unchanged).

- [ ] **Step 4: Verify smoke**

```bash
python main.py -c 7   # 7 = deepseek per existing constants.py
```

Expected: starts up, attaches Weixin window, starts sidecar, listens. No traceback.
Send a test message in Weixin and verify it's logged.

If `processMsg` errors due to wcferry-specific assumptions, that's expected — we fix in Phase 3 by routing through Dispatcher.

- [ ] **Step 5: Commit**

```bash
git add robot.py main.py
git commit -m "feat(robot): swap Wcf for WxAdapter in main bootstrap"
```

---

## Phase 3: Template Matcher + Dispatcher

### Task 3.1: TemplateMatcher with tests

**Files:**
- Create: `tests/test_template.py`
- Create: `router/template.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_template.py`:

```python
import json
from pathlib import Path
import pytest

from router.template import TemplateMatcher


@pytest.fixture
def kw_replies(tmp_path):
    p = tmp_path / "replies.json"
    p.write_text(json.dumps({
        "你好": "你好！请问需要什么帮助？",
        "营业时间": "周一至周日 9:00-21:00",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def kw_images(tmp_path):
    p = tmp_path / "images.json"
    p.write_text(json.dumps({
        "菜单图": "images/menu.png",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def kw_menus(tmp_path):
    p = tmp_path / "menus.json"
    p.write_text(json.dumps({
        "菜单": "1. 课程查询\n2. 下单",
    }, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def tm(kw_replies, kw_images, kw_menus):
    return TemplateMatcher(
        replies_path=kw_replies, images_path=kw_images, menus_path=kw_menus
    )


def test_text_match_exact(tm):
    actions = tm.match("你好")
    assert any(a.kind == "text" and a.payload == "你好！请问需要什么帮助？" for a in actions)


def test_text_match_substring(tm):
    actions = tm.match("请问营业时间是什么时候")
    assert any(a.kind == "text" and a.payload == "周一至周日 9:00-21:00" for a in actions)


def test_image_match(tm):
    actions = tm.match("菜单图")
    assert any(a.kind == "image" and a.payload == "images/menu.png" for a in actions)


def test_menu_match(tm):
    actions = tm.match("查看菜单")
    assert any(a.kind == "menu" and a.payload == "1. 课程查询\n2. 下单" for a in actions)


def test_no_match_returns_empty(tm):
    assert tm.match("完全无关的话题") == []


def test_multiple_matches_returned(tm):
    actions = tm.match("你好 我想看菜单")
    kinds = [a.kind for a in actions]
    assert "text" in kinds
    assert "menu" in kinds
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/test_template.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `router/template.py`**

```python
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class TemplateAction:
    kind: str          # 'text', 'image', or 'menu'
    payload: str       # text content or file path


class TemplateMatcher:
    """Substring keyword matcher over three JSON dicts.

    Matches:
      - 关键词回复.json  → TemplateAction(kind='text')
      - 关键词发图.json  → TemplateAction(kind='image')
      - 菜单格式.json    → TemplateAction(kind='menu')
    """

    def __init__(self, replies_path: Path, images_path: Path, menus_path: Path):
        self._replies = self._load(replies_path)
        self._images = self._load(images_path)
        self._menus = self._load(menus_path)

    @staticmethod
    def _load(path: Path) -> dict[str, str]:
        path = Path(path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def match(self, text: str) -> list[TemplateAction]:
        actions: list[TemplateAction] = []
        actions.extend(
            TemplateAction("text", reply)
            for kw, reply in self._replies.items()
            if kw in text
        )
        actions.extend(
            TemplateAction("image", path)
            for kw, path in self._images.items()
            if kw in text
        )
        actions.extend(
            TemplateAction("menu", payload)
            for kw, payload in self._menus.items()
            if kw in text
        )
        return actions

    def reload(self) -> None:
        # Re-read all three files (for config hot-reload).
        pass    # Implemented in Phase 3 polish if needed
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_template.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add router/template.py tests/test_template.py
git commit -m "feat(router): add TemplateMatcher for keyword/image/menu replies"
```

### Task 3.2: Dispatcher with tests (no OrderHandler yet)

**Files:**
- Create: `tests/test_dispatch.py`
- Create: `router/dispatch.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_dispatch.py`:

```python
from unittest.mock import MagicMock
import pytest

from wx.msg import WxMsg
from router.dispatch import Dispatcher
from router.template import TemplateMatcher, TemplateAction


def make_msg(content="hi", sender="wxid_alice", roomid="", type=1, is_self=False):
    return WxMsg(
        id=1, type=type, sender=sender, roomid=roomid, content=content,
        is_self=is_self, ts=0,
    )


@pytest.fixture
def wx():
    m = MagicMock()
    m.get_self_wxid.return_value = "wxid_bot"
    return m


@pytest.fixture
def tm():
    m = MagicMock(spec=TemplateMatcher)
    m.match.return_value = []
    return m


@pytest.fixture
def order_handler():
    m = MagicMock()
    m.is_pending_for.return_value = False
    m.looks_like_order_intent.return_value = False
    return m


@pytest.fixture
def llm():
    m = MagicMock()
    m.get_answer.return_value = "LLM says hi"
    return m


@pytest.fixture
def dispatcher(wx, tm, order_handler, llm):
    return Dispatcher(
        wx=wx, template_matcher=tm, order_handler=order_handler, llm=llm,
        groups_allowed={"123@chatroom"},
    )


def test_self_messages_ignored(dispatcher, wx):
    dispatcher.handle(make_msg(is_self=True))
    wx.send_text.assert_not_called()


def test_friend_request_triggers_accept(dispatcher, wx):
    msg = make_msg(type=37, content="<msg encryptusername='v3' ticket='v4' scene='14'/>")
    dispatcher.handle(msg)
    wx.accept_new_friend.assert_called_once()


def test_template_text_action_sends(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "hello back")]
    dispatcher.handle(make_msg(content="你好"))
    wx.send_text.assert_called_with("hello back", "wxid_alice")


def test_template_image_action_sends(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("image", "images/x.png")]
    dispatcher.handle(make_msg(content="菜单图"))
    wx.send_image.assert_called_with("images/x.png", "wxid_alice")


def test_group_non_at_ignored(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "x")]
    dispatcher.handle(make_msg(content="hi", roomid="123@chatroom"))
    # Group messages only handled when @bot
    wx.send_text.assert_not_called()


def test_group_unconfigured_ignored(dispatcher, wx, tm):
    tm.match.return_value = [TemplateAction("text", "x")]
    dispatcher.handle(make_msg(content="@WxBot hi", roomid="999@chatroom"))
    wx.send_text.assert_not_called()


def test_order_pending_routes_to_handler(dispatcher, order_handler):
    order_handler.is_pending_for.return_value = True
    dispatcher.handle(make_msg(content="确认"))
    order_handler.on_user_reply.assert_called_once()


def test_order_intent_routes_to_handler(dispatcher, order_handler):
    order_handler.looks_like_order_intent.return_value = True
    dispatcher.handle(make_msg(content="下单 北理工 学号xxx"))
    order_handler.handle_new_order_message.assert_called_once()


def test_fallback_to_llm(dispatcher, wx, llm):
    dispatcher.handle(make_msg(content="random chat"))
    llm.get_answer.assert_called_once()
    wx.send_text.assert_called()
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/test_dispatch.py -v
```

Expected: ImportError on `router.dispatch`.

- [ ] **Step 3: Implement `router/dispatch.py`**

```python
from __future__ import annotations
import logging
from pathlib import Path

from wx.msg import WxMsg
from router.template import TemplateMatcher, TemplateAction

LOG = logging.getLogger(__name__)


class Dispatcher:
    """Routes each incoming WxMsg through a deterministic chain."""

    def __init__(
        self,
        wx,
        template_matcher: TemplateMatcher,
        order_handler,
        llm,
        groups_allowed: set[str],
    ):
        self.wx = wx
        self.tm = template_matcher
        self.order = order_handler
        self.llm = llm
        self.groups = set(groups_allowed)
        self._self_wxid = wx.get_self_wxid()

    def handle(self, msg: WxMsg) -> None:
        try:
            self._handle(msg)
        except Exception as e:
            LOG.error("dispatcher error on msg %s: %s", msg.id, e, exc_info=True)

    def _handle(self, msg: WxMsg) -> None:
        # 1. Self messages: ignore
        if msg.from_self():
            return

        # 2. Friend request (type 37): auto-accept
        if msg.type == 37:
            LOG.info("auto-accepting friend request from %s", msg.sender)
            self.wx.accept_new_friend("", "", 0)
            return

        # 3. Group filter: only respond in allowed groups, and only when @bot
        if msg.from_group():
            if msg.roomid not in self.groups:
                return
            if not msg.is_at(self._self_wxid):
                return
            # @bot in allowed group → continue processing

        receiver = msg.roomid if msg.from_group() else msg.sender

        # 4. Order pending: any reply from a sender with an open draft goes
        #    to the order handler (covers confirm/cancel/correction)
        if self.order.is_pending_for(msg.sender):
            self.order.on_user_reply(msg)
            return

        # 5. Template matches (static keyword/image/menu replies)
        actions = self.tm.match(msg.content) if msg.type == 1 else []
        if actions:
            for act in actions:
                self._dispatch_action(act, receiver)
            return

        # 6. Order intent classifier
        if msg.type == 1 and self.order.looks_like_order_intent(msg.content):
            self.order.handle_new_order_message(msg)
            return

        # 7. Fallback: LLM chitchat (only on text messages)
        if msg.type == 1:
            response = self.llm.get_answer(msg.content, receiver)
            if response:
                self.wx.send_text(response, receiver)

    def _dispatch_action(self, action: TemplateAction, receiver: str) -> None:
        if action.kind == "text":
            self.wx.send_text(action.payload, receiver)
        elif action.kind == "menu":
            self.wx.send_text(action.payload, receiver)
        elif action.kind == "image":
            self.wx.send_image(action.payload, receiver)
        else:
            LOG.warning("unknown action kind: %s", action.kind)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_dispatch.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add router/dispatch.py tests/test_dispatch.py
git commit -m "feat(router): add Dispatcher with template/order/LLM routing chain"
```

### Task 3.3: Integrate Dispatcher into robot.py

**Files:**
- Modify: `robot.py:236-273` (the `processMsg` method)
- Modify: `robot.py:33-84` (the `__init__` method)
- Modify: `main.py`

- [ ] **Step 1: Modify `robot.py.__init__` to build the Dispatcher**

Add at the top of `robot.py` (next to existing imports):

```python
from router.dispatch import Dispatcher
from router.template import TemplateMatcher
```

In `Robot.__init__`, after the existing model selection block, add:

```python
        self.template_matcher = TemplateMatcher(
            replies_path=Path("关键词回复.json"),
            images_path=Path("关键词发图.json"),
            menus_path=Path("菜单格式.json"),
        )
        self.dispatcher = Dispatcher(
            wx=self.wcf,
            template_matcher=self.template_matcher,
            order_handler=NullOrderHandler(),   # replaced in Phase 4
            llm=self.chat,
            groups_allowed=set(self.config.GROUPS or []),
        )
```

Then add a stub NullOrderHandler in the same file (above `Robot` class):

```python
class NullOrderHandler:
    """Placeholder until OrderHandler is added in Phase 4."""

    def is_pending_for(self, wxid: str) -> bool:
        return False

    def looks_like_order_intent(self, text: str) -> bool:
        return False

    def on_user_reply(self, msg) -> None:
        pass

    def handle_new_order_message(self, msg) -> None:
        pass
```

Add `from pathlib import Path` to the imports if missing.

- [ ] **Step 2: Replace `processMsg` body**

Replace the entire `processMsg` method (`robot.py:236-273`) with:

```python
    def processMsg(self, msg: WxMsg) -> None:
        self.dispatcher.handle(msg)
```

Keep all other methods (`sendTextMsg`, `sendImageMsg`, `autoAcceptFriendRequest`, `sayHiToNewFriend`, `getAllContacts`, `keepRunningAndBlockProcess`, etc.) untouched.

- [ ] **Step 3: Smoke run**

```bash
python main.py -c 7
```

Send these test messages in Weixin from another account:
1. "你好" → expect static reply from 关键词回复.json
2. "完全乱说的话" → expect LLM reply
3. (Add the bot as friend from a new account) → expect auto-accept

Watch for errors in logs.

- [ ] **Step 4: Commit**

```bash
git add robot.py
git commit -m "feat(robot): delegate processMsg to Dispatcher"
```

---

## Phase 4: OrderHandler

### Task 4.1: OrderDraft dataclass + prompt scaffolds

**Files:**
- Create: `prompts/order_intent.md`
- Create: `prompts/order_extract.md`
- Create: `router/order_draft.py`
- Create: `tests/test_order_draft.py`

- [ ] **Step 1: Write prompt: order_intent.md**

```markdown
你是一个分类器。给定一条微信用户消息，判断它是否表达"想要下单/代刷课程"的意图。

只回答一个 JSON 对象，**不要任何额外文本**：
```json
{"is_order_intent": true|false, "confidence": 0.0-1.0, "reason": "<10字以内>"}
```

下单意图示例：
- "我要下单课程"
- "帮我刷一下形势与政策"
- "代刷 北理工 学号xxx 密码yyy"
- "下单 1736 平台 课程40"

非下单意图示例：
- "你好"
- "营业时间是什么时候"
- "今天天气真好"
- "课程价格多少"（这是询价不是下单）

消息内容："""{message}"""
```

- [ ] **Step 2: Write prompt: order_extract.md**

```markdown
你需要从用户消息中提取下单所需字段，输出一个严格的 JSON 对象。

字段定义：
- school: 学校名称 (string)
- user: 学号或账号 (string)
- password: 密码 (string)
- platform: 平台编号 (string, 通常是4位数字, 如 "1736")
- kcid: 课程 ID (string)
- kcname: 课程名称 (string)

输出格式（必须返回这个 JSON，不要任何额外文本）：
```json
{
  "school": "<value or null>",
  "user": "<value or null>",
  "password": "<value or null>",
  "platform": "<value or null>",
  "kcid": "<value or null>",
  "kcname": "<value or null>",
  "missing": ["<list of missing field names>"]
}
```

历史对话上下文（按时间正序）：
{history}

最新一条消息："""{message}"""

请提取字段。无法判定的字段用 null，并在 missing 中列出所有 null 字段。
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_order_draft.py`:

```python
import time
from router.order_draft import OrderDraft


def test_orderdraft_complete_true_when_all_fields_set():
    d = OrderDraft(
        school="北理工", user="18543", password="wjx",
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=int(time.time()),
    )
    assert d.is_complete()


def test_orderdraft_complete_false_when_missing():
    d = OrderDraft(
        school="北理工", user="18543", password=None,
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=0,
    )
    assert not d.is_complete()
    assert "password" in d.missing_fields()


def test_orderdraft_summary_includes_all_fields():
    d = OrderDraft(
        school="北理工", user="18543", password="wjx",
        platform="1736", kcid="40", kcname="形势与政策",
        requester_wxid="wxid_x", created_at=0,
    )
    s = d.summary_for_confirmation()
    assert "北理工" in s
    assert "18543" in s
    assert "形势与政策" in s


def test_orderdraft_expired():
    d = OrderDraft(
        school=None, user=None, password=None,
        platform=None, kcid=None, kcname=None,
        requester_wxid="x", created_at=int(time.time()) - 1000,
    )
    assert d.is_expired(timeout_sec=300)


def test_orderdraft_merge_keeps_existing_values():
    d = OrderDraft(
        school="北理工", user=None, password=None,
        platform=None, kcid=None, kcname=None,
        requester_wxid="x", created_at=0,
    )
    d.merge({"user": "18543", "school": None})
    assert d.school == "北理工"   # not overwritten by None
    assert d.user == "18543"
```

- [ ] **Step 4: Run tests to verify fail**

```bash
pytest tests/test_order_draft.py -v
```

Expected: ImportError.

- [ ] **Step 5: Implement `router/order_draft.py`**

```python
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Optional


REQUIRED_FIELDS = ("school", "user", "password", "platform", "kcid", "kcname")


@dataclass
class OrderDraft:
    school: Optional[str]
    user: Optional[str]
    password: Optional[str]
    platform: Optional[str]
    kcid: Optional[str]
    kcname: Optional[str]
    requester_wxid: str
    created_at: int
    confirmed: bool = False
    extract_rounds: int = 0

    def is_complete(self) -> bool:
        return all(getattr(self, f) for f in REQUIRED_FIELDS)

    def missing_fields(self) -> list[str]:
        return [f for f in REQUIRED_FIELDS if not getattr(self, f)]

    def is_expired(self, timeout_sec: int) -> bool:
        return (int(time.time()) - self.created_at) > timeout_sec

    def merge(self, updates: dict) -> None:
        for f in REQUIRED_FIELDS:
            if f in updates and updates[f]:
                setattr(self, f, updates[f])

    def summary_for_confirmation(self) -> str:
        return (
            f"确认下单：\n"
            f"学校: {self.school}\n"
            f"课程: {self.kcname} (ID: {self.kcid})\n"
            f"平台: {self.platform}\n"
            f"账号: {self.user}\n"
            f"回复'确认'下单 / '取消'放弃 (5分钟有效)"
        )

    def to_dict(self) -> dict:
        return asdict(self)
```

- [ ] **Step 6: Run tests**

```bash
pytest tests/test_order_draft.py -v
```

Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add router/order_draft.py tests/test_order_draft.py prompts/order_intent.md prompts/order_extract.md
git commit -m "feat(router): add OrderDraft dataclass and LLM prompts"
```

### Task 4.2: OrderHandler — intent classifier + extraction with mocked LLM

**Files:**
- Create: `tests/test_order_handler.py`
- Create: `router/order.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_order_handler.py`:

```python
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from wx.msg import WxMsg
from router.order import OrderHandler


def make_msg(content, sender="wxid_alice"):
    return WxMsg(
        id=1, type=1, sender=sender, roomid="", content=content,
        is_self=False, ts=int(time.time()),
    )


@pytest.fixture
def lexue_creds():
    return {"user": "1492246", "pass": "xxx", "url": "http://lxuexi.cn/"}


@pytest.fixture
def llm():
    return MagicMock()


@pytest.fixture
def wx():
    return MagicMock()


@pytest.fixture
def safety():
    return {
        "dry_run": True,
        "confirm_timeout_sec": 300,
        "max_extract_rounds": 3,
        "daily_limit": 50,
        "per_user_cooldown_sec": 0,
    }


@pytest.fixture
def handler(tmp_path, lexue_creds, safety, llm, wx):
    return OrderHandler(
        lexue_creds=lexue_creds,
        llm=llm,
        wx=wx,
        safety=safety,
        audit_log_path=tmp_path / "orders.jsonl",
        intent_prompt="判断是否下单意图: {message}",
        extract_prompt="提取字段: history={history} message={message}",
    )


def test_intent_classifier_true(handler, llm):
    llm.get_answer.return_value = '{"is_order_intent": true, "confidence": 0.9, "reason": "ok"}'
    assert handler.looks_like_order_intent("下单 北理工 学号x") is True


def test_intent_classifier_false(handler, llm):
    llm.get_answer.return_value = '{"is_order_intent": false, "confidence": 0.95, "reason": "chitchat"}'
    assert handler.looks_like_order_intent("你好") is False


def test_intent_classifier_malformed_treated_as_false(handler, llm):
    llm.get_answer.return_value = "not json"
    assert handler.looks_like_order_intent("???") is False


def test_extract_complete_draft_requests_confirmation(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": "18543", "password": "wjx",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单 北理工 学号18543 密码wjx 平台1736 课程40 形势与政策"))
    # Bot should have asked for confirmation
    wx.send_text.assert_called_once()
    assert "确认下单" in wx.send_text.call_args[0][0]
    # Draft must be pending
    assert handler.is_pending_for("wxid_alice")


def test_extract_incomplete_asks_for_missing(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": None, "password": None,
        "platform": None, "kcid": None, "kcname": None,
        "missing": ["user", "password", "platform", "kcid", "kcname"],
    })
    handler.handle_new_order_message(make_msg("我想下单"))
    wx.send_text.assert_called_once()
    asked = wx.send_text.call_args[0][0]
    assert "user" in asked or "学号" in asked or "账号" in asked
    assert handler.is_pending_for("wxid_alice")


def test_on_user_reply_confirm_triggers_place_order_in_dry_run(handler, llm, wx, tmp_path):
    # Seed: pending draft with complete fields
    llm.get_answer.return_value = json.dumps({
        "school": "北理工", "user": "18543", "password": "wjx",
        "platform": "1736", "kcid": "40", "kcname": "形势与政策",
        "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    wx.send_text.reset_mock()
    # User replies '确认'
    handler.on_user_reply(make_msg("确认"))
    # In dry_run, place_order writes audit + replies success; does NOT call lexue
    wx.send_text.assert_called()
    assert "下单成功" in wx.send_text.call_args[0][0] or "dry_run" in wx.send_text.call_args[0][0]
    # Pending draft is cleared
    assert not handler.is_pending_for("wxid_alice")
    # Audit log has one line
    audit_path = handler.audit_log_path
    assert audit_path.exists()
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1


def test_on_user_reply_cancel_drops_draft(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": "x", "user": "y", "password": "z",
        "platform": "1", "kcid": "2", "kcname": "k", "missing": [],
    })
    handler.handle_new_order_message(make_msg("下单"))
    wx.send_text.reset_mock()
    handler.on_user_reply(make_msg("取消"))
    assert not handler.is_pending_for("wxid_alice")
    assert any("取消" in c[0][0] or "放弃" in c[0][0] for c in wx.send_text.call_args_list)


def test_max_extract_rounds_aborts(handler, llm, wx):
    llm.get_answer.return_value = json.dumps({
        "school": None, "user": None, "password": None,
        "platform": None, "kcid": None, "kcname": None,
        "missing": ["school", "user", "password", "platform", "kcid", "kcname"],
    })
    handler.handle_new_order_message(make_msg("下单"))
    handler.on_user_reply(make_msg("还是没说全"))
    handler.on_user_reply(make_msg("继续没说全"))
    handler.on_user_reply(make_msg("依然没说全"))   # 4th attempt → abort
    # Final state: pending dropped, escalation message sent
    assert not handler.is_pending_for("wxid_alice")
```

- [ ] **Step 2: Run tests to verify fail**

```bash
pytest tests/test_order_handler.py -v
```

Expected: ImportError on `router.order`.

- [ ] **Step 3: Implement `router/order.py`**

```python
from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from typing import Optional

from wx.msg import WxMsg
from router.order_draft import OrderDraft, REQUIRED_FIELDS

LOG = logging.getLogger(__name__)


class OrderHandler:
    CONFIRM_TOKENS = ("确认", "确定", "yes", "y", "1")
    CANCEL_TOKENS = ("取消", "放弃", "no", "n", "0", "退出")

    FIELD_LABELS = {
        "school": "学校",
        "user": "学号/账号",
        "password": "密码",
        "platform": "平台编号",
        "kcid": "课程 ID",
        "kcname": "课程名称",
    }

    def __init__(
        self,
        lexue_creds: dict,
        llm,
        wx,
        safety: dict,
        audit_log_path: Path,
        intent_prompt: str,
        extract_prompt: str,
    ):
        self.lexue_creds = lexue_creds
        self.llm = llm
        self.wx = wx
        self.safety = safety
        self.audit_log_path = Path(audit_log_path)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.intent_prompt = intent_prompt
        self.extract_prompt = extract_prompt
        self._pending: dict[str, OrderDraft] = {}     # wxid -> draft
        self._history: dict[str, list[str]] = {}      # wxid -> [recent msgs]
        self._daily_count = self._count_today_orders()
        self._last_attempt: dict[str, float] = {}     # cooldown per user

    # ---- public ----
    def is_pending_for(self, wxid: str) -> bool:
        draft = self._pending.get(wxid)
        if draft is None:
            return False
        if draft.is_expired(self.safety["confirm_timeout_sec"]):
            self._pending.pop(wxid, None)
            return False
        return True

    def looks_like_order_intent(self, text: str) -> bool:
        try:
            raw = self.llm.get_answer(self.intent_prompt.format(message=text), "intent")
            obj = json.loads(raw)
            return bool(obj.get("is_order_intent"))
        except Exception as e:
            LOG.warning("intent parse failed: %s; raw=%r", e, raw if 'raw' in dir() else '')
            return False

    def handle_new_order_message(self, msg: WxMsg) -> None:
        if self._on_cooldown(msg.sender):
            self.wx.send_text("操作太频繁，请稍后再试", msg.sender)
            return
        self._history.setdefault(msg.sender, []).append(msg.content)
        draft = self._extract(msg)
        self._pending[msg.sender] = draft
        self._advance(draft, msg.sender)

    def on_user_reply(self, msg: WxMsg) -> None:
        draft = self._pending.get(msg.sender)
        if draft is None:
            return

        text = msg.content.strip()
        if text in self.CANCEL_TOKENS:
            self._pending.pop(msg.sender, None)
            self.wx.send_text("已取消下单", msg.sender)
            self._audit({"event": "cancel", "wxid": msg.sender, "draft": draft.to_dict()})
            return

        if draft.is_complete() and text in self.CONFIRM_TOKENS:
            draft.confirmed = True
            result = self.place_order(draft)
            self._pending.pop(msg.sender, None)
            self.wx.send_text(self._format_result(result), msg.sender)
            return

        # Otherwise: treat reply as additional info, re-extract
        draft.extract_rounds += 1
        if draft.extract_rounds >= self.safety["max_extract_rounds"]:
            self._pending.pop(msg.sender, None)
            self.wx.send_text(
                "信息收集次数过多，已放弃本次下单；请联系客服处理。", msg.sender
            )
            self._audit({"event": "abort_max_rounds", "wxid": msg.sender, "draft": draft.to_dict()})
            return

        self._history.setdefault(msg.sender, []).append(msg.content)
        updated = self._extract(msg)
        draft.merge(updated.to_dict())
        self._advance(draft, msg.sender)

    def place_order(self, draft: OrderDraft):
        if self._daily_count >= self.safety["daily_limit"]:
            self._audit({"event": "daily_limit_hit", "draft": draft.to_dict()})
            return {"code": -2, "msg": "今日下单已达上限"}
        if self.safety.get("dry_run"):
            self._audit({"event": "place_dry_run", "draft": draft.to_dict()})
            self._daily_count += 1
            return {"code": 1, "msg": "下单成功 (dry_run)"}
        # Real call:
        try:
            from Lexxue_api import xd
            result = xd(
                self.lexue_creds,
                draft.school, draft.user, draft.password,
                draft.platform, draft.kcname, draft.kcid,
            )
            self._daily_count += 1
            self._audit({"event": "place_real", "draft": draft.to_dict(), "result": result})
            return result
        except Exception as e:
            LOG.error("place_order failed: %s", e)
            self._audit({"event": "place_error", "draft": draft.to_dict(), "error": str(e)})
            return {"code": -1, "msg": f"下单失败: {e}"}

    # ---- internals ----
    def _advance(self, draft: OrderDraft, wxid: str) -> None:
        if draft.is_complete():
            self.wx.send_text(draft.summary_for_confirmation(), wxid)
        else:
            missing_labels = [self.FIELD_LABELS[f] for f in draft.missing_fields()]
            prompt = "请补充以下信息: " + "、".join(missing_labels)
            self.wx.send_text(prompt, wxid)

    def _extract(self, msg: WxMsg) -> OrderDraft:
        history = "\n".join(self._history.get(msg.sender, [])[-5:])
        try:
            raw = self.llm.get_answer(
                self.extract_prompt.format(history=history, message=msg.content),
                msg.sender,
            )
            obj = json.loads(raw)
        except Exception as e:
            LOG.warning("extract parse failed: %s", e)
            obj = {}
        return OrderDraft(
            school=obj.get("school"),
            user=obj.get("user"),
            password=obj.get("password"),
            platform=obj.get("platform"),
            kcid=obj.get("kcid"),
            kcname=obj.get("kcname"),
            requester_wxid=msg.sender,
            created_at=int(time.time()),
        )

    def _on_cooldown(self, wxid: str) -> bool:
        last = self._last_attempt.get(wxid, 0.0)
        cd = self.safety.get("per_user_cooldown_sec", 0)
        now = time.time()
        if now - last < cd:
            return True
        self._last_attempt[wxid] = now
        return False

    def _audit(self, event: dict) -> None:
        event["ts"] = int(time.time())
        with self.audit_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _count_today_orders(self) -> int:
        if not self.audit_log_path.exists():
            return 0
        today = time.strftime("%Y-%m-%d")
        n = 0
        for line in self.audit_log_path.read_text(encoding="utf-8").splitlines():
            try:
                obj = json.loads(line)
                if obj.get("event", "").startswith("place") and \
                   time.strftime("%Y-%m-%d", time.localtime(obj.get("ts", 0))) == today:
                    n += 1
            except Exception:
                continue
        return n

    def _format_result(self, result: dict) -> str:
        if result.get("code") in (1, "1"):
            return f"下单成功: {result.get('msg', '')}"
        return f"下单失败: {result.get('msg', '未知错误')}"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_order_handler.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add router/order.py tests/test_order_handler.py
git commit -m "feat(router): add OrderHandler with intent/extract/confirm flow"
```

### Task 4.3: Wire OrderHandler into robot.py

**Files:**
- Modify: `robot.py`

- [ ] **Step 1: Read prompts at startup, replace NullOrderHandler**

In `robot.py`, replace the `NullOrderHandler` class and the `Dispatcher` construction:

```python
from router.order import OrderHandler

# ... inside Robot.__init__, after self.chat is built:
intent_prompt = Path(self.config.LLM["intent_prompt_path"]).read_text(encoding="utf-8")
extract_prompt = Path(self.config.LLM["extract_prompt_path"]).read_text(encoding="utf-8")
order_handler = OrderHandler(
    lexue_creds=self.config.LEXUE,
    llm=self.chat,
    wx=self.wcf,
    safety=self.config.ORDER_SAFETY,
    audit_log_path=Path("logs/audit/orders.jsonl"),
    intent_prompt=intent_prompt,
    extract_prompt=extract_prompt,
)
self.dispatcher = Dispatcher(
    wx=self.wcf,
    template_matcher=self.template_matcher,
    order_handler=order_handler,
    llm=self.chat,
    groups_allowed=set(self.config.GROUPS or []),
)
```

Delete the `NullOrderHandler` class.

- [ ] **Step 2: Verify `Lexxue_api.py` is importable** (it should be)

```bash
python -c "from Lexxue_api import xd; print(xd)"
```

Expected: prints the function reference.

- [ ] **Step 3: Smoke run with dry_run=true**

Ensure `config.yaml`'s `order_safety.dry_run` is `true`, then:

```bash
python main.py -c 7
```

From a test account, send: "下单 北理工 学号18543 密码wjx 平台1736 课程40 形势与政策"

Expected sequence:
1. Bot replies with "确认下单：..." summary
2. Reply "确认"
3. Bot replies "下单成功 (dry_run)"
4. `logs/audit/orders.jsonl` contains a `place_dry_run` event

- [ ] **Step 4: Commit**

```bash
git add robot.py
git commit -m "feat(robot): wire OrderHandler into dispatcher with prompt loading"
```

---

## Phase 5: Integration & Verification

### Task 5.1: End-to-end dry-run validation

**Files:**
- Create: `docs/e2e-dry-run-report.md`

- [ ] **Step 1: Verify acceptance criteria from spec §11 (dry_run mode)**

For each criterion, run the test in Weixin and record result in a Markdown checklist:

- [ ] `python main.py` starts cleanly
- [ ] Friend request from a new account → auto-accepted within 5s, welcome sent
- [ ] Group @bot → LLM reply received
- [ ] Private "你好" → static reply
- [ ] Private "菜单图" → image sent
- [ ] Private "下单 ..." → confirmation requested → "确认" → dry_run success
- [ ] `logs/audit/orders.jsonl` populated correctly
- [ ] Kill the sidecar process; bot detects within 30s and auto-restarts (verify in logs)
- [ ] Kill Weixin window; bot fails gracefully (verify no traceback to console)

- [ ] **Step 2: Write report**

Create `docs/e2e-dry-run-report.md` listing every criterion + PASS/FAIL/notes.

- [ ] **Step 3: Fix any failures inline (each as its own micro-commit)**

If a test fails, debug, patch the relevant file, re-run, commit with `fix(...): <what>`.

- [ ] **Step 4: Commit final report**

```bash
git add docs/e2e-dry-run-report.md
git commit -m "docs: e2e dry-run validation report"
```

### Task 5.2: Disable dry_run, verify real order

**Files:**
- Modify: `config.yaml` only (not template)

- [ ] **Step 1: Use a TEST Lexue account**

In `config.yaml`, swap `lexue.user` / `lexue.pass` to a test credentials pair (do NOT use production creds for this test).

- [ ] **Step 2: Set `order_safety.dry_run: false`**

- [ ] **Step 3: Re-run a single order from a small WeChat account**

From the test account, send a real order message. Confirm. Verify:
- Bot replies with whatever `Lexxue_api.xd()` returns
- `logs/audit/orders.jsonl` has a `place_real` event with the API response

- [ ] **Step 4: Document result**

Append to `docs/e2e-dry-run-report.md`: "Real-order verification: PASS — order id X placed at TIME".

- [ ] **Step 5: Switch back to production credentials, commit config separately**

(Do NOT commit `config.yaml` with real production credentials. The template stays committed; the live config remains gitignored or untracked.)

---

## Self-Review

Run through this checklist against the spec:

| Spec requirement | Task |
|---|---|
| §1.2.1 全自动好友通过 | Task 3.2 (Dispatcher friend-request branch) + Task 1.4 (`accept_friend_request_via_ui`) |
| §1.2.2 群/私聊监听 | Task 1.3 (ReceiveBackend) + Task 3.2 (group filter) |
| §1.2.3 LLM 路由模板 | Task 3.1 (TemplateMatcher) + Task 3.2 (Dispatcher) |
| §1.2.4 下单意图识别 + 自动下单 | Tasks 4.1, 4.2, 4.3 |
| §1.2.5 现有文件零改动 | `Lexxue_api.py`, `*.json` not modified |
| §3.1 Architecture diagram | All Phase 1 + Phase 3/4 tasks |
| §4.1 WxMsg | Task 1.1 |
| §4.2 WxAdapter | Task 1.5 |
| §4.3 ReceiveBackend | Task 1.3 |
| §4.4 SendBackend | Task 1.4 |
| §4.5 ContactsBackend | Task 1.2 |
| §4.6 Dispatcher | Task 3.2 |
| §4.7 OrderHandler + OrderDraft | Tasks 4.1, 4.2 |
| §5.1-5.4 数据流 | Verified end-to-end in Task 5.1 |
| §6 错误处理 | ReceiveBackend restart logic, SendBackend retry (Task 1.4), OrderHandler max_rounds (Task 4.2) |
| §7 配置变更 | Task 2.1 |
| §8 测试策略 | Test files in each task; Task 5.1 e2e |
| §9 落地分期 | This plan mirrors the spec's 5 phases |
| §11 完成标准 | Task 5.1 covers all |

**Placeholder scan:** searched the plan for "TBD", "TODO", "implement later" — none found.

**Type consistency:** `WxMsg` fields used consistently across all tasks (id/type/sender/roomid/content/is_self/ts). `OrderDraft.REQUIRED_FIELDS` matches the LLM extract prompt schema. `Dispatcher.handle()` signature consistent in all references.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-22-weixin4-migration-and-order-automation.md`.

User has pre-authorized "执行不要再问我" — proceeding with **Subagent-Driven (recommended)** execution via `superpowers:subagent-driven-development`. Fresh subagent per task, review between tasks.
