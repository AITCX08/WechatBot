"""DECISIVE test: does the REAL visible Weixin 4.x window expose a UIA tree?

UIA's WindowControl(Name='微信') attaches to 'mmui::MainWindow' (a near-empty
shell). The actually-visible window is class 'Qt51514QWindowIcon'. This walks
the UIA tree of EVERY visible 微信/Weixin window via ControlFromHandle and
reports: total control count, EditControl count, anything named like 搜索.

If a visible window yields a rich tree with a search box + edits → UIA send is
salvageable (attach to the right window). If all yield ~0 children → Qt exposes
no UIA tree → UIA send is a dead end on Weixin 4.x.

Usage: python -X utf8 scripts/walk_hwnd.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import win32gui
import uiautomation as uia

OUT = Path(__file__).resolve().parent / "_walk.txt"
log: list[str] = []


def targets():
    found = []

    def cb(hwnd, _):
        try:
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            vis = win32gui.IsWindowVisible(hwnd)
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        if not vis:
            return
        if ("微信" in title or title == "Weixin") and (r - l) > 50 and (b - t) > 50:
            found.append((hwnd, cls, (l, t, r, b)))

    win32gui.EnumWindows(cb, None)
    return found


def walk(hwnd, cls, rect):
    log.append("\n===== hwnd=%s class=%r rect=%s =====" % (hwnd, cls, rect))
    try:
        root = uia.ControlFromHandle(hwnd)
    except Exception as e:
        log.append("ControlFromHandle ERR %r" % e)
        return
    if root is None:
        log.append("ControlFromHandle -> None")
        return
    stats = {"total": 0, "edit": 0}
    edits = []
    searchish = []
    sample = []

    def visit(ctrl, depth):
        stats["total"] += 1
        try:
            t = ctrl.ControlTypeName
            nm = ctrl.Name or ""
        except Exception:
            t, nm = "?", "?"
        if t == "EditControl":
            stats["edit"] += 1
            edits.append((depth, nm))
        if "搜" in nm or "搜索" in nm:
            searchish.append((depth, t, nm))
        if stats["total"] <= 120:
            sample.append("%s%s name=%r" % ("  " * depth, t, nm))

    uia.WalkControl(root, visit, maxDepth=14)
    log.append("TOTAL controls=%d  EditControls=%d" % (stats["total"], stats["edit"]))
    log.append("search-ish: %r" % searchish)
    log.append("edits: %r" % edits[:20])
    log.append("--- sample (first 120) ---")
    log.extend(sample)


def main():
    tg = targets()
    log.append("VISIBLE 微信/Weixin windows: %d" % len(tg))
    for hwnd, cls, rect in tg:
        walk(hwnd, cls, rect)
    OUT.write_text("\n".join(log), encoding="utf-8")
    print("DONE -> %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
