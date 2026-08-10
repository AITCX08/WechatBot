"""真机发送验证：用 pywinauto 给「文件传输助手」发一条消息（Weixin 4.1.9.62）。

证明 4.x 个人微信可用 Python(UIA) 自动发送。定位策略（4.x 搜索框/输入框 Name 都为空）：
  搜索框 = 顶部最高的 Edit；输入框 = 开聊后底部最低的 Edit。
中文用剪贴板粘贴（type_keys 打中文不可靠）。这是前台 RPA：会动鼠标/占用窗口。

用法: python -X utf8 scripts/send_pywinauto.py ["消息内容"] ["目标名"]
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import pyperclip
from pywinauto import Desktop
from pywinauto.keyboard import send_keys

ROOT = Path(__file__).resolve().parents[1]
MSG = sys.argv[1] if len(sys.argv) > 1 else "【真机测试】pywinauto 自动发送收发联调 ✅"
TARGET = sys.argv[2] if len(sys.argv) > 2 else "文件传输助手"
OUT = ROOT / "scripts" / "_send_pywinauto.txt"
log: list[str] = []


def w(s):
    log.append(str(s))


def edits_of(win):
    return [c for c in win.descendants() if "Edit" in c.friendly_class_name()]


def main():
    try:
        d = Desktop(backend="uia")
        win = d.window(title="微信", class_name="mmui::MainWindow")
        win.wait("visible", timeout=8)
        win.set_focus()
        time.sleep(0.6)

        edits = edits_of(win)
        w("edits found=%d" % len(edits))
        for i, e in enumerate(edits):
            try:
                w("  edit#%d rect=%s" % (i, e.rectangle()))
            except Exception as ex:
                w("  edit#%d rect-err %r" % (i, ex))
        if not edits:
            w("NO_EDITS")
            OUT.write_text("\n".join(log), encoding="utf-8")
            print("NO_EDITS")
            return 1

        # 1) 搜索框 = 顶部最高的 Edit
        search = sorted(edits, key=lambda e: e.rectangle().top)[0]
        w("search edit rect=%s" % search.rectangle())
        search.click_input()
        time.sleep(0.3)
        send_keys("^a")
        send_keys("{DEL}")
        time.sleep(0.15)
        pyperclip.copy(TARGET)
        send_keys("^v")
        time.sleep(1.1)          # 等搜索结果
        send_keys("{ENTER}")     # 打开第一个结果
        time.sleep(1.2)

        # 2) 输入框 = 开聊后底部最低的 Edit
        edits2 = edits_of(win)
        inp = sorted(edits2, key=lambda e: e.rectangle().top)[-1]
        w("input edit rect=%s (of %d)" % (inp.rectangle(), len(edits2)))
        inp.click_input()
        time.sleep(0.3)
        pyperclip.copy(MSG)
        send_keys("^v")
        time.sleep(0.3)
        send_keys("{ENTER}")
        time.sleep(0.4)
        w("SENT_OK target=%r msg=%r" % (TARGET, MSG))
        OUT.write_text("\n".join(log), encoding="utf-8")
        print("SENT_OK")
        return 0
    except Exception as e:
        import traceback
        w("SEND_ERR %r" % e)
        w(traceback.format_exc())
        OUT.write_text("\n".join(log), encoding="utf-8")
        print("SEND_ERR %r" % e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
