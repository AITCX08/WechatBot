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
