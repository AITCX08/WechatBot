# Weixin 4.1.7.30 UIA Anchors

> Used by wx/send.py. Update here whenever Weixin's UI changes.
> **STATUS: Initial locators assumed from plan; needs validation in real Weixin.**

## Main Window
- ClassName: `WeChatMainWndForPC` (verify; may be different in 4.x)
- Name: `微信` (or `Weixin`)
- Locator: `WindowControl(searchDepth=2, Name='微信')`

## Search Box
- ControlType: `EditControl`
- Locator: `<main>.EditControl(searchDepth=10, Name='搜索')`
- Behavior: typing + Enter selects first matching conversation

## Conversation List
- ControlType: `ListControl`
- Locator: `<main>.ListControl(searchDepth=10, Name='会话')`

## Message Input
- ControlType: `EditControl`
- Locator: `<main>.EditControl(searchDepth=20)` (usually the only Edit in the bottom Pane)
- Trick: focus, then `pyperclip.copy(text); SendKeys('{Ctrl}v')`, then Enter

## Send Button
- ControlType: `ButtonControl`
- Locator: `<main>.ButtonControl(searchDepth=20, Name='发送(S)')`
- Fallback: press Enter (default behavior)

## @ in Group
- Type `@` in input → Weixin pops a member picker
- Send `displayname` characters → press Enter to insert

## Validation Procedure (when user wakes up)
1. Open Weixin and log in
2. Run `python -c "import uiautomation as uia; w = uia.WindowControl(searchDepth=2, Name='微信'); print(w.Exists()); uia.WalkTree(w, showAllName=False, maxDepth=4)"` and confirm tree
3. Adjust `MAIN_WINDOW_NAMES` and other locators in `wx/send.py` if needed
4. Run `python scripts/smoke_send.py` to verify a single 'ping' to 文件传输助手

## Known limitation — open-chat selection (review issue #3, NEEDS REAL DEVICE)

`_open_chat` types the name into the search box and presses Enter, selecting the
**first** result. For duplicate / prefix-matching names (e.g. "张三" also matches
"张三丰") this may open the WRONG conversation, and there is currently no check.

The robust fix is to read the opened chat's **title-bar control** and assert it
equals the intended `display_name` before sending. That requires the real
title-bar locator, which can only be discovered/validated against a live Weixin
client. When validating on a real device:
1. With a chat open, walk the tree and find the title TextControl (likely near
   the top of the chat pane).
2. Add `_verify_open_chat(expected_name)` in `wx/send.py` that reads it and
   raises on mismatch; call it at the end of `_open_chat`.
3. Add a unit test mocking the title control (matching vs mismatching Name).

Until then this is a documented risk, NOT speculative code.
