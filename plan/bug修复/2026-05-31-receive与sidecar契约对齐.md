# Bug 修复：receive/contacts 与真实 sidecar 契约对齐

> 日期：2026-05-31 ｜ 类型：bug 修复（源码级逆向核验，非真机） ｜ 状态：✅ 已修复并推送
> commits：`b855f0e`（代码+测试+fixtures）、`2caee52`（契约文档）；CI 双绿

## 背景（现象）

step 1 真实环境联调的前置：191 个单测全绿，但全是 mock+纯逻辑，`wx/receive.py` / `wx/contacts.py`
对 sidecar 的字段/表结构假设**从未核对真实源码**。本次用 12-agent workflow 直读
`wx/sidecar/wechat-decrypt/` 源码（monitor_web.py 3093 行等），对抗式交叉验证，发现 2 处
**会在真机 100% 失效**的根因 —— 而旧 fixture 编码了一套「虚构协议」把它们全盖住了。

## 改了什么

### wx/receive.py — `_translate_event` 整段重写
旧代码过滤 `event_type=="new_message"` 并读 `event["data"]["msg_id"/"from_user"/...]`，
但 sidecar 广播的是**裸 `data: <json>` 帧**（monitor_web.py:583-589），JSON 顶层字段是
time/timestamp/chat/username/is_group/sender/type(中文串)/content —— **无 wrapper、无 msg_id/
from_user/is_send**。后果：每条真实消息都返回 None（一条都收不到）。重写后含 3 个适配：
- 中文 type → 数字码（`_TYPE_CN_TO_NUM`：'文本'→1, '图片'→3…），上层 `msg.type==1` 零改
- 单聊 sender=username（对端 wxid）；群 roomid=username（无 room_id，靠 is_group 区分）
- **filehelper 桥接**：filehelper 会话的消息本质是操作者本人所发 → `username==FILEHELPER_WXID`
  时标 `is_self=True`+`receiver="filehelper"`，让命令通道在「无方向位」的 SSE 下继续工作
- 带 `event` 键的异步帧（image_update/rich_update/tool_log）+ 心跳 → 忽略

### wx/contacts.py — SQL 对齐真实表
真实 `contact` 表列是 username/**nick_name**(下划线)/remark，**无 type 列**（mcp_server.py:267）；
Weixin 4.x **无 chatroom_member_nickname 表**。旧 SQL 会抛 `no such column: nickname`。
改 SQL + alias_in_room 降级为全局显示名。

### fixtures + 文档
- `sample_sse_events.py` / `sample_contact.py` 重写成真实裸帧 / 真实 contact schema
- 新增 `docs/sidecar-verification.md`：完整源码级契约 + 真机待确认清单

## 为什么这么改

- 字段/表名全部以 sidecar 源码 file:line 为准，不再猜（对抗式 verify 还驳回了 2 条 agent 误报）
- filehelper 桥接是关键设计：SSE 不提供消息方向，但 filehelper 通道是 bot 的远程控制命脉，
  用「会话身份即方向」把它救活
- **没做** Msg_<md5> 消息库回查（还原群发送方 wxid / 精确方向）—— 需真实解密库才能验证，
  不写无法单测的猜测代码，列为真机阶段任务

## 怎么验证

- TDD：先写真实裸帧 fixture + 测试看 RED（旧代码 6 failed），再改 receive.py 看 GREEN
- 全套 191 → **193 passed**（receive 7→9 测真实协议，contacts 8→9）
- GitHub Actions CI：`b855f0e` + `2caee52` **双 completed/success**

## 关联

- 源码契约：`docs/sidecar-verification.md`
- 重构存档：`plan/重构与大模块/2026-05-22-wcferry到WxAdapter迁移.md`（receive/contacts 属其产物）
- no-phone blockers（仍需真机）：filehelper 会话 username 是否字面 "filehelper"、真实事件 JSON 取值、
  好友请求(37) 在 4.x 的承载、Msg 库回查方向 —— 详见 sidecar-verification.md 第六节
