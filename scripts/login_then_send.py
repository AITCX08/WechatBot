"""真机联调：等微信扫码登录成功 → 用我们自己的 SendBackend 给文件传输助手发一条。

登录窗口和主窗口的 Name 都是 "微信"，靠 ClassName 区分：
  登录窗 ClassName 含 'Login'；主窗口不含。
检测到非登录主窗口后，settle 几秒，再走 SendBackend.send_text("filehelper", ...)。

用法: python -X utf8 scripts/login_then_send.py [message] [timeout_sec]
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uiautomation as uia  # noqa: E402
from wx.send import SendBackend  # noqa: E402
from wx.contacts import ContactsBackend  # noqa: E402
from wx.constants import FILEHELPER_WXID  # noqa: E402

MSG = sys.argv[1] if len(sys.argv) > 1 else "【真机测试】文件传输助手收发联调 ✅"
TIMEOUT = int(sys.argv[2]) if len(sys.argv) > 2 else 600
WEIXIN_EXE = Path(r"C:\Program Files\Tencent\WeChat4.1.9\Weixin\Weixin.exe")
NAMES = ("微信", "Weixin")


def find_main_window():
    """Return the logged-in main window (Name in NAMES, ClassName !~ Login), else None.

    Uses uia.WindowControl(searchDepth=2, Name=...) — the lookup that works
    reliably in the interactive desktop session (GetRootControl().GetChildren()
    throws COM errors under non-interactive/background shells).
    """
    for name in NAMES:
        w = uia.WindowControl(searchDepth=2, Name=name)
        if w.Exists(maxSearchSeconds=1):
            cls = ""
            try:
                cls = w.ClassName or ""
            except Exception:
                cls = ""
            if "Login" not in cls:
                return w, cls
    return None, None


def main():
    print("WAIT_LOGIN start timeout=%ds msg=%r" % (TIMEOUT, MSG), flush=True)
    deadline = time.time() + TIMEOUT
    win = None
    cls = None
    while time.time() < deadline:
        win, cls = find_main_window()
        if win is not None:
            print("LOGIN_DETECTED main window class=%r" % cls, flush=True)
            break
        time.sleep(3)
    else:
        print("LOGIN_TIMEOUT no main window appeared", flush=True)
        return 2

    # 主窗口出现后，等界面（搜索框/会话列表）渲染稳定
    print("SETTLE 8s for UI to render...", flush=True)
    time.sleep(8)

    backend = SendBackend(WEIXIN_EXE, ContactsBackend(ROOT / "_nonexistent_contact.db"))
    backend._main = win  # 直接绑定已确认的主窗口，跳过按名查找（避免误绑登录窗）

    print("SENDING to filehelper (%s)..." % FILEHELPER_WXID, flush=True)
    try:
        ok = backend.send_text(FILEHELPER_WXID, MSG)
        print("SEND_RESULT %s" % ok, flush=True)
        return 0 if ok else 1
    except Exception as e:
        print("SEND_EXCEPTION %r" % e, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
