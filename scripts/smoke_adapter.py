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
