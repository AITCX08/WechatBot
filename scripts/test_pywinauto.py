"""Re-test the 'Weixin 4.x exposes no UIA' conclusion with pywinauto (uia backend).

pywechat (1529★) claims 4.1.6~4.1.9 support via pywinauto, contradicting my raw
uiautomation.WalkControl result (which found ~0 children). pywinauto's enumeration
is more robust (proper top-window selection, retries). If pywinauto finds a rich
tree with the search box + edits, my earlier conclusion was a tooling artifact and
the simple Python RPA path is viable. If it also finds nothing, UIA is truly dead.

Usage: python -X utf8 scripts/test_pywinauto.py
"""
from __future__ import annotations
from pathlib import Path

OUT = Path(__file__).resolve().parent / "_pywinauto.txt"
log: list[str] = []


def main():
    try:
        from pywinauto import Desktop
    except Exception as e:
        OUT.write_text("import pywinauto FAILED: %r" % e, encoding="utf-8")
        print("NO_PYWINAUTO")
        return 2

    d = Desktop(backend="uia")
    try:
        wins = [w for w in d.windows() if (w.window_text() or "") in ("微信", "Weixin")]
    except Exception as e:
        log.append("windows() ERR %r" % e)
        wins = []
    log.append("uia top windows titled 微信/Weixin: %d" % len(wins))

    for w in wins:
        try:
            cls = w.class_name()
        except Exception:
            cls = "?"
        try:
            rect = w.rectangle()
        except Exception:
            rect = "?"
        log.append("\n=== WIN class=%s rect=%s ===" % (cls, rect))
        try:
            desc = w.descendants()
        except Exception as e:
            log.append("  descendants() ERR %r" % e)
            continue
        log.append("  descendants=%d" % len(desc))
        try:
            edits = [c for c in desc if "Edit" in c.friendly_class_name()]
            log.append("  Edit controls=%d" % len(edits))
            for e in edits[:8]:
                log.append("    EDIT %r" % (e.window_text() or ""))
        except Exception as e:
            log.append("  edit scan ERR %r" % e)
        try:
            searchish = [(c.friendly_class_name(), c.window_text())
                         for c in desc if "搜索" in (c.window_text() or "")]
            log.append("  搜索-ish: %r" % searchish[:6])
        except Exception:
            pass
        # sample first 50 controls
        log.append("  --- first 50 controls ---")
        for c in desc[:50]:
            try:
                log.append("    %s | %r" % (c.friendly_class_name(), (c.window_text() or "")[:34]))
            except Exception:
                log.append("    <ctrl err>")

    OUT.write_text("\n".join(log), encoding="utf-8")
    print("DONE -> %s" % OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
