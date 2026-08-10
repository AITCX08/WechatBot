"""Test hypothesis: Weixin window is minimized/hidden → UIA tree empty.

Try several activation methods, after each re-measure the window rect and count
immediate children. If activation makes the rect non-zero and children appear,
the root cause of 'search box not found' is a non-visible window, and the fix is
to restore+activate before driving UIA.

Usage: python -X utf8 scripts/activate_wx.py
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import uiautomation as uia

NAMES = ("微信", "Weixin")
OUT = Path(__file__).resolve().parent / "_activate.txt"
log: list[str] = []


def find_main():
    for name in NAMES:
        w = uia.WindowControl(searchDepth=2, Name=name)
        if w.Exists(maxSearchSeconds=2):
            try:
                cls = w.ClassName or ""
            except Exception:
                cls = ""
            if "Login" not in cls:
                return w
    return None


def measure(win, tag):
    try:
        r = win.BoundingRectangle
        rect = "(%d,%d,%d,%d)" % (r.left, r.top, r.right, r.bottom)
    except Exception as e:
        rect = "rect-err:%r" % e
    try:
        n = len(win.GetChildren())
    except Exception as e:
        n = "children-err:%r" % e
    log.append("[%s] rect=%s children=%s" % (tag, rect, n))


def main():
    win = find_main()
    if win is None:
        log.append("NO main window")
        OUT.write_text("\n".join(log), encoding="utf-8")
        print("NO_MAIN")
        return 2

    measure(win, "before")

    # 1) SetActive
    try:
        win.SetActive(waitTime=0.5)
        log.append("SetActive ok")
    except Exception as e:
        log.append("SetActive err:%r" % e)
    time.sleep(0.5)
    measure(win, "after SetActive")

    # 2) ShowWindow Restore (9) then ShowNormal (1)
    for code, label in ((9, "Restore"), (1, "ShowNormal"), (3, "Maximize")):
        try:
            win.ShowWindow(code, waitTime=0.4)
            log.append("ShowWindow(%s=%d) ok" % (label, code))
        except Exception as e:
            log.append("ShowWindow(%s) err:%r" % (label, e))
        time.sleep(0.4)
        measure(win, "after %s" % label)

    # 3) SetTopmost then activate again
    try:
        win.SetActive(waitTime=0.5)
    except Exception:
        pass
    time.sleep(0.5)
    measure(win, "final")

    # If children now exist, dump shallow tree (depth 6) to find search/input
    try:
        nkids = len(win.GetChildren())
    except Exception:
        nkids = 0
    if nkids:
        log.append("--- shallow tree (depth<=6) ---")

        def visit(ctrl, depth):
            try:
                t = ctrl.ControlTypeName
                nm = ctrl.Name
                aid = ctrl.AutomationId
            except Exception:
                t, nm, aid = "?", "?", "?"
            log.append("%s%s name=%r aid=%r" % ("  " * depth, t, nm, aid))

        uia.WalkControl(win, visit, maxDepth=6)

    OUT.write_text("\n".join(log), encoding="utf-8")
    print("DONE children_final=%s -> %s" % (nkids, OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
