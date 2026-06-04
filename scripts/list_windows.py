"""Enumerate ALL top-level windows via win32gui (bypasses UIA).

Tells us definitively: is there a REAL visible Weixin window (non-zero rect,
not iconic)? what's its class? This disambiguates the two hypotheses for
'search box not found':
  H1: we attached to a hidden/proxy '微信' window; a real visible one exists.
  H2: Weixin 4.x (Qt6) exposes no usable window to drive at all.

Usage: python -X utf8 scripts/list_windows.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import win32gui

OUT = Path(__file__).resolve().parent / "_windows.txt"
rows: list[str] = []


def enum_cb(hwnd, _):
    try:
        title = win32gui.GetWindowText(hwnd)
        cls = win32gui.GetClassName(hwnd)
    except Exception:
        return
    blob = "%s %s" % (title, cls)
    if ("微信" not in blob) and ("eixin" not in blob) and ("WeChat" not in blob) \
       and ("mmui" not in cls) and ("Qt" not in cls):
        return
    try:
        vis = win32gui.IsWindowVisible(hwnd)
        iconic = win32gui.IsIconic(hwnd)
        l, t, r, b = win32gui.GetWindowRect(hwnd)
    except Exception:
        vis = iconic = "?"
        l = t = r = b = 0
    rows.append("hwnd=%s vis=%s iconic=%s rect=(%d,%d,%d,%d) class=%r title=%r" % (
        hwnd, vis, iconic, l, t, r, b, cls, title))


def main():
    win32gui.EnumWindows(enum_cb, None)
    if not rows:
        rows.append("NO matching top-level windows (微信/Weixin/mmui/Qt)")
    OUT.write_text("\n".join(rows), encoding="utf-8")
    print("FOUND %d window(s) -> %s" % (len(rows), OUT))
    for r in rows:
        # also echo to stdout (ascii-safe-ish; titles may have CJK)
        try:
            print(r)
        except Exception:
            print(r.encode("ascii", "replace").decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
