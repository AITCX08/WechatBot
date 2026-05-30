# 功能开发：Filehelper 命令通道

> 日期：2026-05-23（MVP）+ 2026-05-25（v2 命令） ｜ 类型：功能开发 ｜ 状态：✅ 已上线

## 背景

操作者给自己微信的「文件传输助手」发命令，bot 在同一窗口回复——手机上就能远程操控 bot，无需开 Dashboard。

## 改了什么

| 文件 | 职责 |
|------|------|
| `router/commands.py` | CommandRegistry（斜杠命令 + 中文别名）+ 7 个 handler + 入口函数 |
| `wx/constants.py` | `FILEHELPER_WXID = "filehelper"` 常量 |
| `router/dispatch.py` | `_handle` 第 0 步调 `try_handle_filehelper_command` |

命令清单（7 条）：
| 命令 | 别名 | 作用 |
|------|------|------|
| /status | 状态 | 运行状态摘要 |
| /pause /resume | 暂停/恢复 | 全局暂停/取消 |
| /report [today\|yesterday\|7d] | 日报/今日/报告 | 下单统计 |
| /pending | 待确认/待办 | 待确认订单列表 |
| /pricing | 价格/价目 | 当前价格表 |
| /help | 帮助 | 命令清单 |

## 为什么这么改

- 安全门：仅 `from_self && receiver=="filehelper" && type==1` 三条件全成立才识别
  （反例：别人 DM /pause、自己群里 /pause、自己 DM 朋友 /pause 全部无效）
- 命令绕过 paused 标志：否则暂停后无法用 /resume 解除
- handler 抛异常 → 回「❗ 执行失败」+ 写 log，后续命令仍正常
- 未知斜杠命令 → 提示；非斜杠非别名普通文本 → 静默不回（不打扰自言自语）

## 怎么验证

- commands 18 测试 + dispatch 8 测试（含 3 项关键安全测试）全绿
- 146 → 184 测试（v2 命令 +8）

## 关联

- 实施计划：`plan/实施计划/2026-05-23-Filehelper命令通道MVP.md`、`plan/实施计划/2026-05-25-Filehelper-v2.md`
- 通知日报：`plan/功能开发/2026-05-25-通知与日报系统.md`
- commits：`d4586a6`、`8a97dc9`、`f40d30e`
