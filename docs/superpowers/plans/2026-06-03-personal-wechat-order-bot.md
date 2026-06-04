# 个人微信半自动客服下单 Bot 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在个人微信 PC 客户端(Weixin 4.1.9.62)上全程接管刷课客服下单流程——读用 sidecar 协议、发用 pywinauto 键鼠模拟(不改窗口大小)，客户转账后自动收款核对金额，金额对则调 lexue 交单，全程在 dashboard 显示+记录+文件助手通知。

**Architecture:** 复用现有 `WxAdapter` facade 与 `Dispatcher`/`OrderHandler`/`PricingTable` 业务层(零改动其接口契约)。新增三块能力：(1) `PywinautoSender` 替换坏掉的 raw-uiautomation 发送；(2) 转账金额读取(复用 sidecar `decode_transfer`)+ 收款动作 + 金额核对；(3) OCR 读科目截图。**关键纪律：3 个高风险点先做 spike 真机验证，验通才写正式实现；`order_safety.dry_run` 保持 True 直到全链路验通。**

**Tech Stack:** Python 3.x, pywinauto(uia backend), pyperclip, requests, sidecar(wechat-decrypt 已有 decode_transfer), OCR(待 spike 选型：cnocr / ddddocr / paddleocr), pytest, FastAPI dashboard(已有)。

---

## 阶段总览

- **Phase 0 — Spike 闸门(真机)**：3 个高风险点各验一次，产出结论。**任一失败则在此停下找用户重新决策**，不进 Phase 1+。
- **Phase 1 — 发送层**：把 `wx/send.py` 从 raw-uiautomation 改为 pywinauto，不改窗口大小。
- **Phase 2 — 转账收款+金额核对**：读金额、点收款、核对应收。
- **Phase 3 — OCR 科目识别**：截图→课程名。
- **Phase 4 — 下单流程编排**：把报价/收款核对/交单/通知串成状态机(扩 OrderDraft)。
- **Phase 5 — dashboard + 记录 + 文件助手通知**：成交可见+落账+通知。
- **Phase 6 — 全链路 dry_run 验证 + 存档**。

**红线**：Phase 1-5 全程 `order_safety.dry_run=true`。Phase 6 用户在场逐步开真档。

---

## Phase 0 — Spike 闸门(真机，不写正式实现)

> Spike 脚本放 `scripts/spike_*.py`，结论写进 `plan/功能开发/2026-06-03-个人微信下单bot-spike.md`。Spike 代码不要求 TDD/单测，是探针。

### Task 0.1: Spike — sidecar 能否从实时 SSE 读出转账金额+状态

**Files:**
- Create: `scripts/spike_transfer_read.py`

**背景事实(已查证)**：sidecar 已内置转账解析 `wx/sidecar/wechat-decrypt/decode_transfer.py` + `mcp_server._extract_transfer_info`，转账是 appmsg type=2000 `<wcpayinfo>`，paysubtype 标签：`1`=发起/待对方收、`3`=已收款、`7`=待领取、`4`=已退还(见 mcp_server.py:918 `_TRANSFER_PAYSUBTYPE_LABEL`)。**未知点**：实时 SSE `/stream` 推的转账帧里，是否直接带金额/paysubtype，还是只给 "[转账]" 概要、需再查库。

- [ ] **Step 1: 写探针**：连 `http://127.0.0.1:5678/stream`，捕获 N 帧，对每帧打印完整 JSON 的 KEYS + 原文；并对疑似转账帧(content 含"转账"/"¥"/type∈{49,2000})高亮。

```python
"""Spike: 实时 SSE 流里转账帧长什么样、带不带金额。
用法: python -X utf8 scripts/spike_transfer_read.py [URL] [N]
让用户在微信里给本号转一笔(或自己用小号转)，观察帧。
"""
import sys, json, requests
URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5678/stream"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 8
got = 0
with requests.get(URL, stream=True, timeout=(5, None)) as r:
    r.raise_for_status()
    for line in r.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        raw = line[len("data:"):].strip()
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        blob = json.dumps(obj, ensure_ascii=False)
        is_transfer = any(k in blob for k in ("转账", "¥", "wcpay", "2000")) or obj.get("type") in (49, 2000, "转账")
        mark = "  <<< 疑似转账" if is_transfer else ""
        print(f"=== FRAME #{got} KEYS={list(obj.keys())}{mark} ===")
        print(blob[:900])
        got += 1
        if got >= N:
            break
print("done")
```

- [ ] **Step 2: 真机跑**：确保 sidecar 在跑(端口 5678 OPEN)，运行探针，请用户发一笔真转账。

Run: `python -X utf8 scripts/spike_transfer_read.py http://127.0.0.1:5678/stream 8`
Expected: 捕获到转账帧，**记录**：帧里有没有金额数字？有没有 paysubtype/状态？字段名是什么？

- [ ] **Step 3: 若 SSE 帧不带金额 → 验证查库兜底**：用 sidecar 的 `decode_transfer.py` 对该笔 local_id 解一次，确认能解出金额+方向。

Run: `cd wx/sidecar/wechat-decrypt && .venv/Scripts/python.exe decode_transfer.py <chat_name> <local_id>`
Expected: 输出含金额/方向/收款 wxid。

- [ ] **Step 4: 记录结论**：在 spike 存档里写明——金额从哪取(SSE 直出 / 查库)、字段名、状态如何判断"待收款 vs 已收款"。这是 Phase 2 的输入契约。

### Task 0.2: Spike — pywinauto 能否点开转账气泡并确认收款(不放大窗口)

**Files:**
- Create: `scripts/spike_receive_money.py`

**背景**：已实测 pywinauto 能枚举 187 控件、能发文本(`scripts/send_pywinauto.py`)。未知：转账气泡是什么控件、点击后弹的收款确认窗能否被 pywinauto 找到"确认收款"按钮。**硬约束**：全程不调任何 Maximize/ShowWindow 放大/set_focus 之外的尺寸变更。

- [ ] **Step 1: 写探针(只观察+可选点击)**：附着到微信主窗口(`mmui::MainWindow`，**只 attach 不 resize**)，打开与某客户的会话，dump 出聊天区里所有控件的 friendly_class_name + window_text + rectangle，定位转账气泡(文案含"转账"/"待收款"/"¥")。先 `--observe` 只打印不点；`--click` 才尝试点击气泡→等待弹窗→dump 弹窗控件找"收款"/"确认收款"按钮。

```python
"""Spike: 转账气泡能否被 pywinauto 驱动点收款。绝不放大窗口。
用法: python -X utf8 scripts/spike_receive_money.py <客户显示名> [--observe|--click]
"""
import sys, time
from pywinauto import Desktop
from pywinauto.keyboard import send_keys
import pyperclip

TARGET = sys.argv[1] if len(sys.argv) > 1 else ""
MODE = sys.argv[2] if len(sys.argv) > 2 else "--observe"

d = Desktop(backend="uia")
win = d.window(title="微信", class_name="mmui::MainWindow")
win.wait("visible", timeout=8)
# 注意：不调用任何 maximize/move/resize；set_focus 仅置前，不改尺寸
win.set_focus(); time.sleep(0.5)

# 打开会话：顶部 Edit=搜索框
edits = [c for c in win.descendants() if "Edit" in c.friendly_class_name()]
search = sorted(edits, key=lambda e: e.rectangle().top)[0]
search.click_input(); time.sleep(0.3)
send_keys("^a"); send_keys("{DEL}"); time.sleep(0.15)
pyperclip.copy(TARGET); send_keys("^v"); time.sleep(1.1); send_keys("{ENTER}"); time.sleep(1.2)

# dump 聊天区控件，找转账气泡
print("=== 控件 dump (找转账气泡) ===")
hits = []
for c in win.descendants():
    try:
        t = c.window_text() or ""
    except Exception:
        continue
    if any(k in t for k in ("转账", "待收款", "待你收款", "已收款", "¥")):
        r = c.rectangle()
        print(f"  {c.friendly_class_name()} text={t!r} rect={r}")
        hits.append(c)
print(f"命中 {len(hits)} 个转账相关控件")

if MODE == "--click" and hits:
    print("尝试点击第一个转账气泡...")
    hits[0].click_input(); time.sleep(1.5)
    # dump 弹窗找收款按钮
    print("=== 点击后全控件(找'收款'按钮) ===")
    for c in d.window(class_name="mmui::FramelessWindow").descendants() if False else win.descendants():
        try:
            t = c.window_text() or ""
        except Exception:
            continue
        if any(k in t for k in ("收款", "确认收款", "收钱")):
            print(f"  BTN {c.friendly_class_name()} text={t!r} rect={c.rectangle()}")
print("done (窗口尺寸未改变)")
```

- [ ] **Step 2: 真机 observe**：先 `--observe`，确认能定位到转账气泡控件。

Run: `python -X utf8 scripts/spike_receive_money.py "海边捡贝壳" --observe`
Expected: 打印出转账气泡的控件类型/文案/坐标。**记录**：气泡是 ButtonControl 还是 Custom？文案能区分"待收款/已收款"吗？

- [ ] **Step 3: 真机 click(用一笔小额测试转账)**：`--click`，观察能否弹出收款窗并定位"确认收款"按钮。**用户在场，可随时人工接管。**

Run: `python -X utf8 scripts/spike_receive_money.py "<测试客户>" --click`
Expected: 要么成功定位"收款"按钮(记录其控件路径)，要么失败(记录失败现象)。**截图存证。验证窗口尺寸前后不变。**

- [ ] **Step 4: 记录结论**：收款是否可自动化、控件定位方式、是否改变了窗口大小。这是 Phase 2 的输入。

### Task 0.3: Spike — OCR 读科目截图准确率 + 选型

**Files:**
- Create: `scripts/spike_ocr_subjects.py`

**背景**：OCR 库全未装(cv2/cnocr/paddleocr/easyocr/ddddocr 均 MISSING，仅 PIL 在)。科目截图样例见客户聊天(课程列表，如"2024春季形势与政策")。

- [ ] **Step 1: 装候选 OCR(选轻量优先)**：先试 `cnocr`(中文友好、装得快)。

Run: `python -m pip install cnocr -q`
Expected: 安装成功(若依赖过重/失败，换 `ddddocr` 或 `easyocr`，记录选型)。

- [ ] **Step 2: 写探针**：对一张/多张真实科目截图跑 OCR，打印识别文本，人工对比准确率。

```python
"""Spike: OCR 读科目截图。用法: python -X utf8 scripts/spike_ocr_subjects.py <图片路径...>"""
import sys
from cnocr import CnOcr
ocr = CnOcr()
for p in sys.argv[1:]:
    print(f"=== {p} ===")
    res = ocr.ocr(p)
    for line in res:
        print(f"  {line.get('text','')}  (score={line.get('score',0):.2f})")
print("done")
```

- [ ] **Step 3: 真机跑**：用用户提供的真实科目截图(如 `C:/Users/Administrator/Documents/xwechat_files/.../temp/InputTemp/*.png`)。

Run: `python -X utf8 scripts/spike_ocr_subjects.py "<科目截图路径>"`
Expected: 输出课程名文本。**记录**：能否读出完整课程名？准确率如何(几条对几条)？是否需要预处理(放大/二值化)？

- [ ] **Step 4: 记录结论 + 决策**：OCR 选型 + 准确率 + 是否够用。若准确率太低 → 回退"请客户文字发科目"策略(需求里的备选)，告知用户重新决策。

### Task 0.4: Spike 闸门总结(决策点)

- [ ] **Step 1: 汇总三个 spike 结论**到 `plan/功能开发/2026-06-03-个人微信下单bot-spike.md`(5 段式：背景/改了什么/验证步骤与结果/结论/关联)。

- [ ] **Step 2: 向用户报告 + 决策**：三点哪些通、哪些不通。
  - 全通 → 进 Phase 1。
  - 收款不通 → "自动收钱"档作废，退化为"读到转账提示就提醒人工收款"，需用户确认范围调整。
  - OCR 不通 → 退"请客户文字发科目"，需用户确认。
  - **不要在 spike 失败时硬继续。**

---

## Phase 1 — 发送层：pywinauto 替换 raw-uiautomation(不改窗口大小)

### Task 1.1: PywinautoSender 核心(开聊+发文本)

**Files:**
- Create: `wx/pywin_sender.py`
- Test: `tests/test_pywin_sender.py`

**说明**：现有 `wx/send.py` 的 `SendBackend` 用 raw `uiautomation` 找 `Name='搜索'` 的框，4.x 搜索框 Name 为空 → 永远失败。新建 `PywinautoSender` 用 pywinauto + 按位置定位(顶部 Edit=搜索、底部 Edit=输入)，中文用剪贴板粘贴。**绝不调用 maximize/move/resize。**

- [ ] **Step 1: 写失败测试(纯逻辑部分可单测：定位选择算法)**

```python
# tests/test_pywin_sender.py
from wx.pywin_sender import pick_search_edit, pick_input_edit

class FakeRect:
    def __init__(self, top): self.top = top
class FakeEdit:
    def __init__(self, top): self._r = FakeRect(top)
    def rectangle(self): return self._r

def test_pick_search_edit_is_topmost():
    edits = [FakeEdit(760), FakeEdit(46)]
    assert pick_search_edit(edits) is edits[1]   # top=46 最高

def test_pick_input_edit_is_bottommost():
    edits = [FakeEdit(46), FakeEdit(760)]
    assert pick_input_edit(edits) is edits[1]     # top=760 最低

def test_pick_edits_empty_returns_none():
    assert pick_search_edit([]) is None
    assert pick_input_edit([]) is None
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -X utf8 -m pytest tests/test_pywin_sender.py -v`
Expected: FAIL，ModuleNotFoundError: wx.pywin_sender

- [ ] **Step 3: 写最小实现**

```python
# wx/pywin_sender.py
"""个人微信 4.x 发送层：pywinauto 键鼠模拟。绝不改变窗口大小。

定位策略(4.x 搜索框/输入框 Name 均为空)：搜索框=顶部最高 Edit，输入框=底部最低 Edit。
中文用剪贴板粘贴(send_keys 打中文不可靠)。
"""
from __future__ import annotations
import logging
import time
from threading import Lock

import pyperclip

LOG = logging.getLogger(__name__)

MAIN_TITLE = "微信"
MAIN_CLASS = "mmui::MainWindow"


def pick_search_edit(edits):
    if not edits:
        return None
    return sorted(edits, key=lambda e: e.rectangle().top)[0]


def pick_input_edit(edits):
    if not edits:
        return None
    return sorted(edits, key=lambda e: e.rectangle().top)[-1]


class PywinautoSender:
    PER_SEND_INTERVAL_SEC = 0.8

    def __init__(self):
        self._win = None
        self._lock = Lock()
        self._last_send = 0.0

    def attach(self):
        from pywinauto import Desktop
        win = Desktop(backend="uia").window(title=MAIN_TITLE, class_name=MAIN_CLASS)
        win.wait("visible", timeout=8)
        # 仅置前，不改尺寸。绝不调 maximize/move_window/resize。
        win.set_focus()
        self._win = win

    def _edits(self):
        return [c for c in self._win.descendants() if "Edit" in c.friendly_class_name()]

    def _throttle(self):
        import time as _t
        elapsed = _t.time() - self._last_send
        if elapsed < self.PER_SEND_INTERVAL_SEC:
            _t.sleep(self.PER_SEND_INTERVAL_SEC - elapsed)
        self._last_send = _t.time()

    def open_chat(self, display_name: str) -> None:
        from pywinauto.keyboard import send_keys
        if self._win is None:
            self.attach()
        search = pick_search_edit(self._edits())
        if search is None:
            raise RuntimeError("search edit not found")
        search.click_input(); time.sleep(0.3)
        send_keys("^a"); send_keys("{DEL}"); time.sleep(0.15)
        pyperclip.copy(display_name); send_keys("^v"); time.sleep(1.1)
        send_keys("{ENTER}"); time.sleep(1.2)

    def send_text(self, display_name: str, text: str) -> bool:
        from pywinauto.keyboard import send_keys
        with self._lock:
            self._throttle()
            try:
                self.open_chat(display_name)
                inp = pick_input_edit(self._edits())
                if inp is None:
                    raise RuntimeError("input edit not found")
                inp.click_input(); time.sleep(0.3)
                pyperclip.copy(text); send_keys("^v"); time.sleep(0.3)
                send_keys("{ENTER}"); time.sleep(0.3)
                return True
            except Exception as e:
                LOG.error("send_text failed to %s: %s", display_name, e)
                return False
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `python -X utf8 -m pytest tests/test_pywin_sender.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: 提交**

```bash
git add wx/pywin_sender.py tests/test_pywin_sender.py
git commit -m "feat(wx): PywinautoSender 发送层(按位置定位,不改窗口大小)"
```

### Task 1.2: send_image(发图片，用于固定收款码/模板图)

**Files:**
- Modify: `wx/pywin_sender.py`
- Test: `tests/test_pywin_sender.py`

- [ ] **Step 1: 写失败测试(校验入参与剪贴板调用路径，mock)**

```python
# 追加到 tests/test_pywin_sender.py
def test_send_image_missing_file_returns_false(tmp_path):
    from wx.pywin_sender import PywinautoSender
    s = PywinautoSender()
    assert s.send_image("某人", str(tmp_path / "nope.png")) is False
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_pywin_sender.py::test_send_image_missing_file_returns_false -v`
Expected: FAIL (AttributeError: send_image)

- [ ] **Step 3: 实现 send_image(剪贴板贴图)**

```python
# 追加到 PywinautoSender
    def send_image(self, display_name: str, image_path: str) -> bool:
        from pywinauto.keyboard import send_keys
        from pathlib import Path
        if not Path(image_path).exists():
            LOG.error("send_image: file not found %s", image_path)
            return False
        with self._lock:
            self._throttle()
            try:
                self.open_chat(display_name)
                inp = pick_input_edit(self._edits())
                if inp is None:
                    raise RuntimeError("input edit not found")
                inp.click_input(); time.sleep(0.3)
                self._copy_image_to_clipboard(image_path)
                send_keys("^v"); time.sleep(0.5)
                send_keys("{ENTER}"); time.sleep(0.3)
                return True
            except Exception as e:
                LOG.error("send_image failed: %s", e)
                return False

    @staticmethod
    def _copy_image_to_clipboard(image_path: str) -> None:
        from PIL import Image
        from io import BytesIO
        import win32clipboard
        img = Image.open(image_path)
        out = BytesIO(); img.convert("RGB").save(out, "BMP")
        data = out.getvalue()[14:]; out.close()
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
        finally:
            win32clipboard.CloseClipboard()
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_pywin_sender.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add wx/pywin_sender.py tests/test_pywin_sender.py
git commit -m "feat(wx): PywinautoSender.send_image 剪贴板贴图发送"
```

### Task 1.3: 把 WxAdapter 的发送切到 PywinautoSender

**Files:**
- Modify: `wx/adapter.py:34,50-57`
- Test: `tests/test_adapter.py`

- [ ] **Step 1: 写失败测试**：WxAdapter.send_text 走 PywinautoSender(mock)，receiver→display 解析仍用 contacts/BUILTIN。

```python
# tests/test_adapter.py 追加
def test_adapter_send_text_uses_pywin_sender(monkeypatch, tmp_path):
    from wx.adapter import WxAdapter
    sent = {}
    class FakeSender:
        def attach(self): pass
        def send_text(self, display, text): sent.update(display=display, text=text); return True
        def send_image(self, display, path): return True
    a = WxAdapter(weixin_exe=tmp_path/"w.exe", sidecar_url="http://x",
                  decrypted_db_path=tmp_path/"c.db")
    a._send = FakeSender()
    # filehelper 走内置名解析
    rc = a.send_text("你好", "filehelper")
    assert rc == 0
    assert sent["text"] == "你好"
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_adapter.py::test_adapter_send_text_uses_pywin_sender -v`
Expected: FAIL(现有 _send 是 raw SendBackend，display 解析签名不符)

- [ ] **Step 3: 改 WxAdapter**：`self._send = PywinautoSender()`；`send_text` 内部用 `_resolve_display(receiver)`(从原 SendBackend 搬出，含 BUILTIN filehelper→"文件传输助手"、contacts 查名、拒 @chatroom) 再调 `self._send.send_text(display, msg)`。

```python
# wx/adapter.py 关键改动
from wx.pywin_sender import PywinautoSender
from wx.constants import FILEHELPER_WXID

BUILTIN_NAMES = {FILEHELPER_WXID: "文件传输助手"}

# __init__ 内:
self._send = PywinautoSender()

def _resolve_display(self, receiver_wxid: str):
    if not receiver_wxid:
        return None
    if receiver_wxid in BUILTIN_NAMES:
        return BUILTIN_NAMES[receiver_wxid]
    display = self._contacts.wxid_to_name(receiver_wxid)
    if not display or display.endswith("@chatroom"):
        return None
    return display

def send_text(self, msg: str, receiver: str, at_list: str = "") -> int:
    display = self._resolve_display(receiver)
    if not display:
        return 1
    return 0 if self._send.send_text(display, msg) else 1

def send_image(self, image_path, receiver: str) -> int:
    display = self._resolve_display(receiver)
    if not display:
        return 1
    return 0 if self._send.send_image(display, str(image_path)) else 1
```

- [ ] **Step 4: 运行，确认通过(含原有 adapter 测试不回归)**

Run: `python -X utf8 -m pytest tests/test_adapter.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add wx/adapter.py tests/test_adapter.py
git commit -m "refactor(wx): WxAdapter 发送切到 PywinautoSender"
```

### Task 1.4: 真机冒烟 — 给文件传输助手发一条(不改窗口大小)

**Files:**
- Modify: `scripts/smoke_send.py`

- [ ] **Step 1: 改冒烟脚本**走 WxAdapter.send_text("【冒烟】pywinauto OK", "filehelper")，**删除任何 maximize/resize**。

- [ ] **Step 2: 真机跑**

Run: `python -X utf8 scripts/smoke_send.py`
Expected: 文件传输助手收到消息；**人工确认窗口大小没变**。

- [ ] **Step 3: 提交**

```bash
git add scripts/smoke_send.py
git commit -m "test(wx): 发送层真机冒烟(文件助手,不改窗口)"
```

---

## Phase 2 — 转账收款 + 金额核对

> 本阶段实现依赖 Phase 0 Task 0.1/0.2 的结论(金额从哪取、收款按钮怎么点)。以下按"SSE 帧直出金额 + 收款按钮可点"的乐观契约写；若 spike 结论不同，按结论调整字段名/定位。

### Task 2.1: 转账消息解析(WxMsg → 转账信息)

**Files:**
- Create: `wx/transfer.py`
- Test: `tests/test_transfer.py`

- [ ] **Step 1: 写失败测试**：从一条转账内容解出金额(分→元)、状态、方向。用 spike 抓到的真实帧结构做 fixture。

```python
# tests/test_transfer.py
from wx.transfer import parse_transfer, TransferInfo

def test_parse_pending_incoming_transfer():
    # 用 spike 抓到的真实字段名替换(此处用占位契约)
    raw = {"type": "转账", "transfer": {"fee": "500", "paysubtype": "1", "feedesc": "¥5.00"}}
    info = parse_transfer(raw)
    assert isinstance(info, TransferInfo)
    assert info.amount_yuan == 5.0
    assert info.status == "pending"     # paysubtype=1 待收款
    assert info.is_incoming is True

def test_parse_non_transfer_returns_none():
    assert parse_transfer({"type": "文本", "content": "你好"}) is None
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_transfer.py -v`
Expected: FAIL (无 wx.transfer)

- [ ] **Step 3: 实现 parse_transfer**(字段名以 spike 结论为准)

```python
# wx/transfer.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

# paysubtype → 状态(见 sidecar mcp_server.py:918)
_PAYSUBTYPE = {"1": "pending", "7": "pending", "3": "received", "4": "refunded", "5": "refunded"}


@dataclass
class TransferInfo:
    amount_yuan: float
    status: str          # pending / received / refunded
    is_incoming: bool


def parse_transfer(raw: dict) -> Optional[TransferInfo]:
    if not isinstance(raw, dict):
        return None
    t = raw.get("transfer")
    if not t or raw.get("type") != "转账":
        return None
    fee = t.get("fee")
    try:
        amount = round(int(fee) / 100.0, 2)
    except (TypeError, ValueError):
        # 兜底：从 feedesc "¥5.00" 抽
        import re
        m = re.search(r"([\d.]+)", str(t.get("feedesc", "")))
        amount = float(m.group(1)) if m else 0.0
    status = _PAYSUBTYPE.get(str(t.get("paysubtype", "")), "pending")
    return TransferInfo(amount_yuan=amount, status=status, is_incoming=True)
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_transfer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add wx/transfer.py tests/test_transfer.py
git commit -m "feat(wx): 转账消息解析(金额/状态/方向)"
```

### Task 2.2: 收款动作 + 金额核对(dry_run 安全)

**Files:**
- Modify: `wx/pywin_sender.py` (加 `click_receive_money`)
- Create: `wx/receipt.py` (金额核对逻辑，纯函数)
- Test: `tests/test_receipt.py`

- [ ] **Step 1: 写失败测试(纯核对逻辑)**

```python
# tests/test_receipt.py
from wx.receipt import check_amount

def test_amount_match_ok():
    assert check_amount(expected=5.0, actual=5.0) == "ok"

def test_amount_short_pay():
    assert check_amount(expected=10.0, actual=5.0) == "mismatch"

def test_amount_over_pay():
    assert check_amount(expected=5.0, actual=8.0) == "mismatch"

def test_amount_tolerates_float_noise():
    assert check_amount(expected=5.0, actual=5.001) == "ok"
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_receipt.py -v`
Expected: FAIL

- [ ] **Step 3: 实现核对 + 收款动作**

```python
# wx/receipt.py
def check_amount(expected: float, actual: float, tol: float = 0.01) -> str:
    """返回 'ok' / 'mismatch'。"""
    if abs(float(expected) - float(actual)) <= tol:
        return "ok"
    return "mismatch"
```

```python
# 追加到 wx/pywin_sender.py PywinautoSender —— 收款动作(定位以 spike 0.2 结论为准)
    def click_receive_money(self, display_name: str, dry_run: bool = True) -> bool:
        """点开与某人的会话，找最新转账气泡并点'确认收款'。dry_run=True 只定位不点。"""
        from pywinauto.keyboard import send_keys
        with self._lock:
            try:
                self.open_chat(display_name)
                time.sleep(0.5)
                bubbles = [c for c in self._win.descendants()
                           if any(k in (c.window_text() or "")
                                   for k in ("待收款", "待你收款", "转账"))]
                if not bubbles:
                    LOG.warning("no transfer bubble for %s", display_name)
                    return False
                if dry_run:
                    LOG.info("[dry_run] 找到转账气泡，跳过点击收款")
                    return True
                bubbles[-1].click_input(); time.sleep(1.5)
                btns = [c for c in self._win.descendants()
                        if any(k in (c.window_text() or "") for k in ("确认收款", "收款", "收钱"))]
                if not btns:
                    LOG.warning("收款按钮未找到")
                    return False
                btns[0].click_input(); time.sleep(0.8)
                return True
            except Exception as e:
                LOG.error("click_receive_money failed: %s", e)
                return False
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_receipt.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add wx/receipt.py wx/pywin_sender.py tests/test_receipt.py
git commit -m "feat(wx): 收款动作(dry_run安全)+金额核对纯函数"
```

---

## Phase 3 — OCR 科目识别

### Task 3.1: OCR 模块(图片→课程名列表)

**Files:**
- Create: `wx/ocr.py`
- Test: `tests/test_ocr.py`
- Modify: `requirements.txt` (加 spike 选定的 OCR 库)

- [ ] **Step 1: 写失败测试(mock OCR 引擎，测后处理：去噪/筛课程名)**

```python
# tests/test_ocr.py
from wx.ocr import extract_courses_from_lines

def test_extract_courses_filters_noise():
    lines = ["课程名称", "2024春季形势与政策", "已通过", "马克思主义基本原理", "100%"]
    courses = extract_courses_from_lines(lines)
    assert "2024春季形势与政策" in courses
    assert "马克思主义基本原理" in courses
    assert "已通过" not in courses
    assert "100%" not in courses
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_ocr.py -v`
Expected: FAIL

- [ ] **Step 3: 实现(引擎调用 + 后处理分离，引擎部分按 spike 选型)**

```python
# wx/ocr.py
from __future__ import annotations
import logging
import re

LOG = logging.getLogger(__name__)

# 明显不是课程名的噪声行
_NOISE = re.compile(r"^(课程名称|已通过|未通过|进行中|\d+%|学习进度|状态|序号)\s*$")


def extract_courses_from_lines(lines: list[str]) -> list[str]:
    """从 OCR 行里筛出疑似课程名(去噪、去纯数字/百分比/表头)。"""
    out = []
    for ln in lines:
        s = (ln or "").strip()
        if not s or _NOISE.match(s):
            continue
        if re.fullmatch(r"[\d.%\s]+", s):
            continue
        if len(s) < 3:
            continue
        out.append(s)
    return out


def ocr_image(image_path: str) -> list[str]:
    """对图片 OCR，返回文本行。引擎按 spike 选型(此处 cnocr)。"""
    try:
        from cnocr import CnOcr
    except Exception as e:
        LOG.error("OCR engine missing: %s", e)
        return []
    ocr = CnOcr()
    return [r.get("text", "") for r in ocr.ocr(image_path)]


def extract_courses(image_path: str) -> list[str]:
    return extract_courses_from_lines(ocr_image(image_path))
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_ocr.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add wx/ocr.py tests/test_ocr.py requirements.txt
git commit -m "feat(wx): OCR 科目识别(引擎+后处理筛课程名)"
```

---

## Phase 4 — 下单流程编排(扩 OrderDraft + 状态机)

### Task 4.1: OrderDraft 扩字段(应收/实付/收款状态)

**Files:**
- Modify: `router/order_draft.py`
- Test: `tests/test_order_draft.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_order_draft.py 追加
def test_order_draft_has_payment_fields():
    from router.order_draft import OrderDraft
    d = OrderDraft(school=None, user=None, password=None, platform=None,
                   kcid=None, kcname=None, requester_wxid="x", created_at=0)
    assert d.expected_amount == 0.0
    assert d.paid_amount is None
    assert d.payment_status == "unpaid"
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_order_draft.py::test_order_draft_has_payment_fields -v`
Expected: FAIL

- [ ] **Step 3: 加字段**

```python
# router/order_draft.py OrderDraft 追加(放在 extract_rounds 后)
    expected_amount: float = 0.0
    paid_amount: float | None = None
    payment_status: str = "unpaid"   # unpaid / paid_ok / paid_mismatch
    courses: list = field(default_factory=list)   # OCR/文字解析出的课程名
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_order_draft.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add router/order_draft.py tests/test_order_draft.py
git commit -m "feat(order): OrderDraft 加应收/实付/收款状态/课程字段"
```

### Task 4.2: 收款核对→交单 闸门(OrderHandler 接入)

**Files:**
- Modify: `router/order.py` (加 `handle_transfer` 方法)
- Test: `tests/test_order_handler.py`

- [ ] **Step 1: 写失败测试**：金额对→交单(dry_run 返回成功)+ 通知 order_success；金额不符→不交单 + 通知人工。

```python
# tests/test_order_handler.py 追加
def test_handle_transfer_amount_ok_triggers_order(make_handler):
    h, fake_wx, fake_notifier = make_handler(dry_run=True)
    # 预置一个 complete draft，应收 5.0
    from router.order_draft import OrderDraft
    import time as _t
    d = OrderDraft(school="s", user="u", password="p", platform="1736",
                   kcid="40", kcname="形势与政策", requester_wxid="cust1",
                   created_at=int(_t.time()))
    d.expected_amount = 5.0
    h._pending["cust1"] = d
    h.handle_transfer("cust1", amount=5.0)
    assert d.payment_status == "paid_ok"
    # dry_run 交单成功后清 pending
    assert "cust1" not in h._pending

def test_handle_transfer_amount_mismatch_alerts_human(make_handler):
    h, fake_wx, fake_notifier = make_handler(dry_run=True)
    from router.order_draft import OrderDraft
    import time as _t
    d = OrderDraft(school="s", user="u", password="p", platform="1736",
                   kcid="40", kcname="形势与政策", requester_wxid="cust2",
                   created_at=int(_t.time()))
    d.expected_amount = 10.0
    h._pending["cust2"] = d
    h.handle_transfer("cust2", amount=5.0)
    assert d.payment_status == "paid_mismatch"
    assert "cust2" in h._pending   # 不交单,保留
    assert any("应收" in c or "实付" in c for c in fake_notifier.emitted_texts())
```

(注：`make_handler` fixture 需在 conftest 或测试文件内构造 OrderHandler + fake wx/notifier；沿用现有 test_order_handler.py 的构造方式。)

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_order_handler.py -k handle_transfer -v`
Expected: FAIL (无 handle_transfer)

- [ ] **Step 3: 实现 handle_transfer**

```python
# router/order.py OrderHandler 追加
    def handle_transfer(self, wxid: str, amount: float) -> None:
        """收到来自 wxid 的转账(金额 amount 元)。金额对→交单；不符→提醒人工。"""
        from wx.receipt import check_amount
        draft = self._pending.get(wxid)
        if draft is None or not draft.is_complete():
            # 没有待支付订单 → 记一笔，提醒人工
            self._notify_human(f"⚠收到 {wxid} 转账 ¥{amount}，但无待支付订单")
            return
        draft.paid_amount = amount
        verdict = check_amount(draft.expected_amount, amount)
        if verdict != "ok":
            draft.payment_status = "paid_mismatch"
            self._audit({"event": "amount_mismatch", "wxid": wxid,
                         "draft": draft.to_dict(),
                         "msg": f"应收 ¥{draft.expected_amount} 实付 ¥{amount}"})
            self._notify_human(
                f"⚠客户 {wxid} 金额不符：应收 ¥{draft.expected_amount}，实付 ¥{amount}，请人工处理")
            return
        draft.payment_status = "paid_ok"
        result = self.place_order(draft)
        self._pending.pop(wxid, None)
        self.wx.send_text(self._format_result(result), wxid)

    def _notify_human(self, text: str) -> None:
        try:
            self.wx.send_text(text, "filehelper")
        except Exception:
            pass
        if self.notifier is not None:
            try:
                self.notifier.emit(self.account_name, "error", {"msg": text})
            except Exception:
                pass
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_order_handler.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add router/order.py tests/test_order_handler.py
git commit -m "feat(order): 收款金额核对→交单/人工告警 闸门"
```

### Task 4.3: Dispatcher 接入转账事件

**Files:**
- Modify: `router/dispatch.py:87-151` (加转账分支)
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: 写失败测试**：收到转账类 WxMsg(非自己、1v1、解析出 TransferInfo) → 调 order.handle_transfer。

```python
# tests/test_dispatch.py 追加
def test_dispatch_routes_transfer_to_order(make_dispatcher):
    disp, fake_order = make_dispatcher()
    from wx.msg import WxMsg
    # 转账消息：用 spike 确认的 type/content 契约；此处用占位让 _maybe_transfer 命中
    m = WxMsg(id=1, type=49, sender="cust1", roomid="", content="<转账xml>",
              is_self=False, ts=1)
    # monkeypatch parse_transfer 返回一笔 5 元 incoming
    import router.dispatch as dmod
    dmod._parse_transfer_amount = lambda msg: 5.0
    disp.handle(m)
    assert fake_order.transfers == [("cust1", 5.0)]
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_dispatch.py -k transfer -v`
Expected: FAIL

- [ ] **Step 3: 加转账分支**(在 `_handle` 的 order_eligible 段，第 4 步之前)

```python
# router/dispatch.py 顶部加 helper
def _parse_transfer_amount(msg):
    """从转账消息解出金额(元)，非转账返回 None。契约以 spike 0.1 为准。"""
    try:
        from wx.transfer import parse_transfer
        import json
        # 若 content 是 JSON/已结构化，按 spike 结论解析；这里给最简入口
        info = parse_transfer(getattr(msg, "_raw", None) or {})
        if info and info.is_incoming and info.status == "pending":
            return info.amount_yuan
    except Exception:
        pass
    return None

# _handle 内，第 4 步(order pending)之前加：
        if order_eligible:
            amt = _parse_transfer_amount(msg)
            if amt is not None:
                self.order.handle_transfer(msg.sender, amt)
                return
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add router/dispatch.py tests/test_dispatch.py
git commit -m "feat(dispatch): 转账事件路由到 order.handle_transfer"
```

---

## Phase 5 — dashboard + 记录 + 文件助手通知

### Task 5.1: 成交记录 + dashboard 展示

**Files:**
- Modify: `router/order.py` (place_order 成功后写成交记录 + dashboard)
- Test: `tests/test_order_handler.py`

**说明**：现有 `_audit` 已落 audit_log + dashboard ring buffer + notifier。成交(place_real/place_dry_run)已映射 order_success/order_dry_run 通知。本任务补"成交专用记录"(含金额)。

- [ ] **Step 1: 写失败测试**：交单成功后，audit 里有 amount 字段，dashboard state.audit 收到。

```python
# tests/test_order_handler.py 追加
def test_successful_order_records_amount(make_handler):
    h, fake_wx, fake_notifier = make_handler(dry_run=True)
    from router.order_draft import OrderDraft
    import time as _t, json
    d = OrderDraft(school="s", user="u", password="p", platform="1736",
                   kcid="40", kcname="形势与政策", requester_wxid="cust3",
                   created_at=int(_t.time()))
    d.expected_amount = 5.0
    h._pending["cust3"] = d
    h.handle_transfer("cust3", amount=5.0)
    # 读 audit_log 最后一行
    lines = h.audit_log_path.read_text(encoding="utf-8").splitlines()
    last = json.loads(lines[-1])
    assert last.get("amount") == 5.0 or last.get("draft", {}).get("paid_amount") == 5.0
```

- [ ] **Step 2: 运行，确认失败**

Run: `python -X utf8 -m pytest tests/test_order_handler.py -k records_amount -v`
Expected: FAIL

- [ ] **Step 3: place_order 成功 audit 带 amount**(在 place_real/place_dry_run 的 audit dict 加 `"amount": draft.paid_amount`)

```python
# router/order.py place_order 内两处 _audit 调用补 amount:
        if self.safety.get("dry_run"):
            self._audit({"event": "place_dry_run", "draft": draft.to_dict(),
                         "amount": draft.paid_amount})
            ...
        ...
            self._audit({"event": "place_real", "draft": draft.to_dict(),
                         "result": result, "amount": draft.paid_amount})
```

- [ ] **Step 4: 运行，确认通过**

Run: `python -X utf8 -m pytest tests/test_order_handler.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add router/order.py tests/test_order_handler.py
git commit -m "feat(order): 成交记录带金额(dashboard+audit)"
```

### Task 5.2: dashboard 成交栏(若现有看板未展示金额)

**Files:**
- Modify: `dashboard/state.py` / `dashboard/server.py` / 前端模板(按现有结构)
- Test: `tests/test_state.py`

- [ ] **Step 1: 写失败测试**：BotState 暴露 today 成交额聚合(若已有则跳过本任务)。

```python
# tests/test_state.py 追加
def test_state_audit_holds_amount():
    from dashboard.state import get_state
    st = get_state()
    st.audit.append({"event": "place_real", "amount": 5.0})
    assert any(e.get("amount") == 5.0 for e in st.audit)
```

- [ ] **Step 2-4**: 运行→(若失败)在 state 暴露聚合→通过。(现有 ring buffer 已存 audit，多半只需前端展示，按实际差距实现。)

- [ ] **Step 5: 提交**

```bash
git add dashboard/ tests/test_state.py
git commit -m "feat(dashboard): 成交额展示"
```

---

## Phase 6 — 全链路 dry_run 验证 + 逐步开真档 + 存档

### Task 6.1: 全链路 dry_run 真机演练

- [ ] **Step 1**: 确认 `config.yaml order_safety.dry_run: true`。启动 main.py(个人微信 backend)。
- [ ] **Step 2**: 用测试客户走完整流程：问课→bot 报价→发账号+科目截图→bot OCR+算应收→发测试转账→bot(dry_run)定位收款气泡但不点、核对金额→(dry_run)模拟交单→回"OK 晚上统一安排"。
- [ ] **Step 3**: 检查 dashboard 显示该单、audit_log 有记录、文件助手收到通知。
- [ ] **Step 4**: 金额不符场景：发不符金额→确认 bot 不交单 + 文件助手告警。
- [ ] **Step 5**: 记录演练结果(截图)。

### Task 6.2: 逐步开真档(用户在场)

- [ ] **Step 1**: 先只开"真收款"(click_receive_money dry_run=False)，其余仍 dry_run，验一笔小额。
- [ ] **Step 2**: 确认收款成功后，再开"真交单"(order_safety.dry_run=false)，用一笔真实小订单验证 lexue 交单成功。
- [ ] **Step 3**: 观察一轮真实客户，确认稳定。

### Task 6.3: 全量测试 + 存档

- [ ] **Step 1**: 跑全套单测。

Run: `python -X utf8 -m pytest -q`
Expected: 全绿。

- [ ] **Step 2**: 写 5 段式存档 `plan/功能开发/2026-06-03-个人微信半自动下单bot.md`(背景/改了什么/验证步骤与结果/结论/关联)。
- [ ] **Step 3**: 提交 + 推送。

```bash
git add -A
git commit -m "docs: 个人微信半自动下单bot 存档 + 全量测试通过"
git push
```

---

## 自检清单(写计划后)

- **Spec 覆盖**：读消息(已有 sidecar)/发消息(Phase1)/报价(复用 pricing)/OCR 科目(Phase3)/转账金额核对(Phase2,4)/交单(复用 lexue xd,Phase4)/dashboard(Phase5)/成交记录(Phase5)/文件助手通知(Phase4,5)/不改窗口大小(Phase0,1 硬约束)/3spike前置(Phase0)/dry_run红线(全程) — 均有任务覆盖。✓
- **占位扫描**：转账字段名、收款按钮控件、OCR 引擎选型 — 三处显式标注"以 spike 结论为准"，这是真机依赖而非占位,spike 任务会产出确切值。✓
- **类型一致**：TransferInfo(amount_yuan/status/is_incoming)、check_amount('ok'/'mismatch')、OrderDraft(expected_amount/paid_amount/payment_status/courses)、handle_transfer(wxid,amount) — 跨任务一致。✓
