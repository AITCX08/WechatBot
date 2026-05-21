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
