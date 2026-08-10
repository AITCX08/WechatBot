"""Dump the real Weixin 4.x main-window UIA control tree → scripts/_wxtree.txt.

Root-cause tool for "search box not found": the current _open_chat assumes the
search box is EditControl(Name='搜索'). Weixin 4.x is a Qt app (mmui::MainWindow)
whose UIA exposure may differ. This prints every control's type / name /
automationId / class / bounding-rect so we can see what the search box and the
message input REALLY are (and where they sit — search=top, input=bottom).

Usage: python -X utf8 scripts/dump_wx_tree.py
"""
from __future__ import annotations
import sys
from pathlib import Path

import uiautomation as uia

NAMES = ("微信", "Weixin")
OUT = Path(__file__).resolve().parent / "_wxtree.txt"
lines: list[str] = []


def find_main():
    for name in NAMES:
        w = uia.WindowControl(searchDepth=2, Name=name)
        if w.Exists(maxSearchSeconds=2):
            try:
                cls = w.ClassName or ""
            except Exception:
                cls = ""
            if "Login" not in cls:
                return w, cls
    return None, None


def rect(ctrl):
    try:
        r = ctrl.BoundingRectangle
        return "(%d,%d,%d,%d)" % (r.left, r.top, r.right, r.bottom)
    except Exception:
        return "(?)"


def main():
    win, cls = find_main()
    if win is None:
        lines.append("NO main window (still logging out / not logged in?)")
        OUT.write_text("\n".join(lines), encoding="utf-8")
        print("NO_MAIN_WINDOW")
        return 2
    lines.append("MAIN window class=%r name=%r rect=%s" % (cls, win.Name, rect(win)))

    def visit(ctrl, depth):
        try:
            t = ctrl.ControlTypeName
        except Exception:
            t = "?"
        try:
            nm = ctrl.Name
        except Exception:
            nm = "?"
        try:
            aid = ctrl.AutomationId
        except Exception:
            aid = ""
        try:
            cn = ctrl.ClassName
        except Exception:
            cn = ""
        lines.append("%s%s name=%r aid=%r cls=%r %s" % (
            "  " * depth, t, nm, aid, cn, rect(ctrl)))

    uia.WalkControl(win, visit, maxDepth=18)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("DUMPED %d controls -> %s" % (len(lines), OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
