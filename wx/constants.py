"""Project-wide constants for wx-layer code."""
from __future__ import annotations

# The internal wxid used by WeChat / Weixin for the "文件传输助手" pseudo-contact.
# Stable across WeChat 3.x and Weixin 4.x. Centralized here so future
# version drift only needs a single edit.
FILEHELPER_WXID = "filehelper"
