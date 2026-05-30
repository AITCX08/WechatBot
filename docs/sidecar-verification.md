# wechat-decrypt sidecar 真实契约（源码级核验）

> 日期：2026-05-31 ｜ 方法：12-agent workflow 从 sidecar 源码逐行提取 + 对抗式交叉验证（纯读源码，非真机）
> 来源：`wx/sidecar/wechat-decrypt/`（ylytdeng/wechat-decrypt）；结论带 `monitor_web.py` / `mcp_server.py` / `decrypt_db.py` 的 file:line 出处
> 严重度：**major**（receive 路径的事件契约对不上，原代码 100% 收不到消息；非推倒重来）

## 一、实时推送：SSE，真实存在 ✅

- 机制：**SSE**（Server-Sent Events），手写 `http.server`（非 Flask/FastAPI）
- 端点：**`GET /stream`**（monitor_web.py:2850）
- 端口：**5678**（`PORT=5678` monitor_web.py:47）
- 内部：30ms 轮询 session.db / WAL 的 mtime（POLL_MS=30）→ 全量解密 → `broadcast_sse()`
- 心跳：空闲 15s 发 `: hb\n\n`（:2867）
- 图片资源：`GET /img/<filename>`（同端口）

### 线缆帧格式（我方原假设错）
- **普通新消息 = 裸 data 帧**：`data: <json>\n\n` —— **没有 `event:` 行、没有 `event_type` key、没有 `data` 外层包裹**
- 异步更新帧才带 event 名：`event: <type>\ndata: <json>\n\n`，type ∈ {image_update, rich_update, tool_log, tool_done}
- JSON 用 `json.dumps(..., ensure_ascii=False)`
- 出处：broadcast_sse() monitor_web.py:583-589

### 新消息事件真实字段（monitor_web.py:1527-1540）
| 字段 | 含义 |
|---|---|
| `username` | **会话标识**：单聊=对方 wxid，群=`xxx@chatroom`。**不是单条消息 from/to** |
| `chat` | 会话显示名（备注/昵称 或 群名） |
| `is_group` | bool；判定 = `'@chatroom' in username`。**群 id 就是 username，无 room_id** |
| `sender` | 群内发送者**显示名**（仅群聊填，单聊恒空串）。**不是 wxid** |
| `type` | **中文串**（'文本'/'图片'/'语音'…），由 format_msg_type 映射，**不是数字码** |
| `type_icon` | emoji 图标 |
| `content` | 正文（图片/富媒体首推常是占位，靠 image_update/rich_update 异步补） |
| `timestamp` | epoch 秒 |
| `time` | `HH:MM:SS` 字符串 |
| `unread` / `decrypt_ms` / `pages` | 未读数 / 性能调试 |

### 类型码映射（format_msg_type, monitor_web.py:567-572）
`1=文本 3=图片 34=语音 42=名片 43=视频 47=表情 48=位置 49=链接/文件 50=通话 10000=系统 10002=撤回`，未知 = `type=N`。
**注意：好友请求(37) 在 sidecar 源码无映射** —— 4.x 好友请求不走这条 SessionTable 流。

## 二、致命语义缺口（影响 bot 核心）

SSE 来自 **SessionTable（会话表）** —— 一个「哪个会话刚有新消息 + 摘要」的活动流，**不是带发送方/接收方/方向的单条消息信封**。以下我方强依赖、SSE 不提供：

| 我方需要 | SSE 提供？ | 真相 |
|---|---|---|
| `from_user`（发送方 wxid） | ❌ | 单聊发送方 = `username`（对端）；群聊 `sender` 只是显示名 |
| `to_user` / `receiver` | ❌ | 无接收方字段 |
| `is_send` / 方向 | ❌ | SessionTable 无方向位；last_timestamp 变大就推 |
| `room_id` | ❌ | 群 id = username，用 `is_group` 区分 |
| `msg_id` | ❌ | 对外只能用 `(username, timestamp)` 关联 |
| 数字 `type` | ❌ | type 是中文串；好友请求码源码里没有 |

发送方 wxid / 方向 / 数字 type 只在**解密后的消息库** `Msg_<md5>`（要 `Name2Id` 还原）—— 见第四节。

## 三、我方的桥接策略（已在 wx/receive.py 落地）

源码缺口里，有一部分能在 **receive 层无损桥接**（可单测），有一部分必须真机：

| 缺口 | 桥接（已做，可单测） | 真机确认项 |
|---|---|---|
| type 中文串 | `_TYPE_CN_TO_NUM` 反查回数字码（'文本'→1…），上层 `msg.type==1` 零改 | — |
| 单聊发送方 | `sender = username`（单聊 username 就是对端 wxid） | — |
| 群标识 | `roomid = username if is_group else ""` | — |
| **filehelper 命令通道** | `username == FILEHELPER_WXID` → 视作自己发给文件助手：`is_self=True` + `receiver="filehelper"`，让已上线的命令通道在 SSE 下继续工作 | filehelper 会话的 username 字面值是否真是 `"filehelper"` |
| 一般 is_self/方向 | 固定 `False`（SSE 不提供） | 要精确区分需回查 Msg 库（真机阶段） |
| 异步帧/心跳 | `"event" in payload` → 丢弃 | — |

## 四、解密 DB 真实结构（vs 我方 wx/contacts.py 旧假设）

全部是**标准明文 SQLite**（decrypt_db.py:22 写 `SQLite format 3\x00` 头，无 PRAGMA key，标准 sqlite3 可直接读）。

| 我方旧假设 | 真实 | 出处 |
|---|---|---|
| `contact(username, nickname, remark, type)` | `contact`，列 `username` / **`nick_name`**（下划线）/ `remark`；**无 type 列** | mcp_server.py:250-298, :267 |
| 联系人 type/分组 | `contact_label(label_id_, label_name_, sort_order_)` + `contact.extra_buffer`(protobuf) | mcp_server.py:431, :445 |
| `chatroom_member_nickname(roomid, wxid, display_name)` | **不存在**（全 repo 0 命中）。群内昵称走 `Name2Id`+`contact` 或正文 `wxid:\n` 前缀 | 全仓 grep 无 |
| 联系人库路径 | `<decrypted_dir>/contact/contact.db`（contact/ 子目录） | mcp_server.py:310-313 |

消息库（真机阶段才接入）：`<decrypted_dir>/message/message_N.db` 分片，表 `Msg_<md5(对方username)>`，
列 `local_id / local_type(数字) / create_time / real_sender_id(整数→Name2Id还原wxid) / message_content / WCDB_CT_message_content`。

## 五、启动方式

- 命令：`python monitor_web.py`（我方假设正确 ✅）
- 默认 0.0.0.0:5678
- 前置：微信已登录 + 已提取密钥；解密产物落 `<decrypted_dir>/`

## 六、仍需真机扫码才能最终确认（no-phone blockers）

1. 自己发到 filehelper 的消息是否触发 SSE（理论上会，bump SessionTable.last_timestamp）
2. filehelper 会话 username 是否字面 `"filehelper"`（源码 0 特判，无法从源码证实/否认）
3. 真实事件 JSON 的确切取值、Msg 表分片/压缩行为、好友请求(37) 在 4.x 的真实承载
4. 同一消息是否被主路径 + hidden 路径推两次（去重靠 `(username, timestamp)`）

## 七、对我方代码的处置（本次 2026-05-31 已做）

| 文件 | 处置 |
|---|---|
| `wx/receive.py` | 重写 `_translate_event`：解析真实裸 data 帧 + 真实字段 + type 反查 + filehelper 桥接 + 跳过异步/心跳帧 |
| `wx/contacts.py` | `SELECT username, nick_name, remark FROM contact`；删 type 列；chatroom_member_nickname 死查询保留 + 注明真机无此表 |
| `tests/fixtures/*` | 重写成真实裸帧 / 真实 contact schema |
| 消息库回查（Msg_<md5> 还原发送方/方向） | **未做** —— 需真实解密库才能验证，列为真机阶段任务，不写无法单测的猜测代码 |
