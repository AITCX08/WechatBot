# 实施计划：Filehelper 命令通道 MVP

> 日期：2026-05-23 ｜ 类型：实施计划 ｜ 状态：✅ 已完成

## 背景

让操作者给自己的「文件传输助手」发斜杠命令或中文关键词，远程查状态、暂停/恢复 bot——
不用打开 Dashboard 网页。

## 分阶段任务（全部完成）

- [x] **FH-1/2/3**：WxMsg 加 `receiver` 字段（默认 ""，向后兼容）；receive.py 从 SSE
      `to_user` 填充；新增 `wx/constants.py` `FILEHELPER_WXID` 常量
- [x] **FH-4**：`router/commands.py`——CommandRegistry + 4 handler（/status /pause /resume /help
      + 中文别名）+ try_handle_filehelper_command 入口
- [x] **FH-5**：Dispatcher 接入——`_handle` 第 0 步插命令分支；`handle()` 让 filehelper 命令
      绕过 paused 标志（否则 /resume 解不了暂停）

## 怎么验证

- [x] filehelper 发 /status、状态、/help、帮助 都正确响应
- [x] /pause 后群/私聊不再回复；/resume 恢复
- [x] 未知 /xyz → 「未知命令」提示；普通自言自语不误触发
- [x] 146 个测试全绿

## 安全门（关键，已测试覆盖）

仅当 `from_self == True && receiver == "filehelper" && type == 1` 三条件全成立才识别为命令：
- 别人 DM 发 /pause → ❌ 无效
- 自己在群里发 /pause → ❌ 无效
- 自己 DM 别的朋友发 /pause → ❌ 无效

## 关键决策

- filehelper 识别用固定 wxid `"filehelper"`（常量集中一处），而非「接收人是自己 wxid」——无歧义
- 命令分支放 `_handle` 最前 early-return，不污染原路由链
- 中文别名用简单 dict.get，不引 trie/模糊匹配（MVP 不值得）

## 关联

- 细节计划：`docs/superpowers/plans/2026-05-23-filehelper-commands-mvp.md`
- 功能存档：`plan/功能开发/2026-05-23-Filehelper命令通道.md`
- commits：`e8bacbf` → `8a97dc9`
