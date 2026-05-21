# Weixin 4.x 迁移与下单自动化设计

- 日期：2026-05-22
- 状态：已设计，待实施计划（writing-plans）
- 上游 issue：腾讯服务端拒绝 WeChat 3.9.12.51 登录（社区 issue lich0821/WeChatFerry#424），wcferry 项目对 4.x 不打算支持

## 1. 背景与目标

### 1.1 触发问题
现有机器人基于 `wcferry` + 微信 3.9.12.51，腾讯服务端已拒绝该版本登录（"该版本不允许登录"），且 wcferry 上游和主流 fork（AITCX08、ttttupup/wxhelper 等）均未对 Weixin 4.x 做协议适配。本机已安装 Weixin 4.1.7.30，需要在不引入账号风险的前提下迁移机器人到该版本。

### 1.2 业务目标（按重要度）
1. **全自动好友通过** — 收到好友请求即通过，发送欢迎语
2. **群/私聊消息监听** — 实时捕获文本、图片等消息
3. **LLM 路由模板** — 入站消息按模板分流：静态关键词回复、菜单回复、LLM 闲聊、下单意图
4. **下单意图识别 + 自动下单** — 从用户消息中提取下单字段（学校 / 学号 / 密码 / 平台 / 课程 ID），经用户二次确认后调用乐学 API `xd()` 自动下单
5. **现有 `Lexxue_api.py`、关键词 JSON、AI 模型配置零改动**

### 1.3 非目标
- 不支持 wcferry 那种全部 39 个接口的等价能力——只覆盖 robot.py 实际调用的接口集（发文本/发图/查联系人/取群昵称/同意好友/收消息）
- 不做朋友圈、视频、文件下载、撤回检测
- 不做账号风控规避策略（**因为我们走的就是官方 Weixin 4.x 正常登录路径，无版本伪造**）

## 2. 关键事实与约束（调研产出）

- **wcferry 上游**：v39.5.2（2026-03-28）仍锁 3.9.12.51，作者明确暗示不会做 4.x
- **腾讯服务端**：3.9.12.51 登录被拒；现象为"扫码后手机端弹窗 → PC 退回登录界面"，是服务端校验，本地 patch 不可行
- **无开源 Weixin 4.x 完整 hook 框架**：
  - miloira/wxhook 开源代码硬编码 3.9.5.81，README 的 4.x 支持来自其闭源付费产品 `pywechat`
  - lyx102/WeChatHook 二进制工具与 miloira 完全一致，README 宣传与实际不符
  - airen3339/WeChat-Hook 有 4.1.5/4.1.8 真实 hook，但用易语言编写
  - msfm2018/wxrobot 有 4.x 偏移，但只做防撤回
- **可用免费方案**：
  - **`ylytdeng/wechat-decrypt`**（3535 ⭐, 2026-05 活跃）：Weixin 4.0+ SQLCipher 4 数据库解密 + 实时消息监听（SSE）
  - **`uiautomation`** Python 库：Windows UIA 事实标准，可操作 Weixin 4.x 窗口实现"打开会话、输入、发送、贴图"
- **账号风险**：使用 Weixin 4.1.7.30 + 正常扫码登录 + 无协议伪造 → 风险等同人工操作（仅"该账号有自动化行为"的轻微指纹，无版本不一致这种红线信号）

## 3. 架构

### 3.1 总览

```
┌────────────────────────────────────────────────────────────────┐
│  main.py / robot.py (改动 ≤ 10 行: import 切换 + LLM 路由调用) │
└────────────────────────┬───────────────────────────────────────┘
                         │
            ┌────────────▼────────────┐
            │   wx.WxAdapter (facade) │ 契约同 wcferry.Wcf 子集
            └─┬───────────┬──────────┬┘
              │           │          │
   ┌──────────▼─┐  ┌──────▼────┐  ┌─▼──────────────┐
   │ ReceiveBack│  │ SendBack  │  │ ContactsBack   │
   │ (sidecar子 │  │ (UIA on   │  │ (读已解密      │
   │  进程 SSE) │  │  Weixin)  │  │  Contact.db)   │
   └──────┬─────┘  └─────┬─────┘  └────────┬───────┘
          │              │                 │
   ┌──────▼──────┐       │         ┌───────▼────────┐
   │ wechat-     │       │         │ decrypted      │
   │ decrypt     │       │         │ MsgX.db /      │
   │ (sidecar)   │       │         │ Contact.db     │
   └──────┬──────┘       │         └────────────────┘
          │              ▼
          │     ┌──────────────────────┐
          └────►│ Weixin 4.1.7.30      │
                │ (官方版本, 正常登录) │
                └──────────────────────┘

┌───────────────────────────────────────────────┐
│              llm_router (新模块)              │
│  入站 WxMsg → 模板匹配链 →                   │
│   [静态回复 | 菜单 | 图片 | LLM 闲聊 |       │
│    下单意图 (extractor + confirmation)]      │
└───────────────────────────────────────────────┘
```

### 3.2 模块清单与归属

| 模块 | 路径 | 职责 | 是否新增 |
|---|---|---|---|
| `wx/msg.py` | 新 | `WxMsg` 数据类（mimic wcferry.WxMsg） | 新 |
| `wx/adapter.py` | 新 | `WxAdapter` facade，对外提供 6 个方法 | 新 |
| `wx/receive.py` | 新 | 启停 wechat-decrypt sidecar，订阅 SSE → 队列 | 新 |
| `wx/send.py` | 新 | UIA 操作 Weixin 主窗口发文本/图 | 新 |
| `wx/contacts.py` | 新 | 解密后 DB 读联系人，三向查询 + 缓存 | 新 |
| `wx/sidecar/` | 新 | wechat-decrypt 作为 git submodule | 新 |
| `router/template.py` | 新 | 模板匹配引擎（关键词 / 正则 / 意图分类） | 新 |
| `router/order.py` | 新 | 下单字段提取 + 二次确认状态机 + 调 Lexxue API | 新 |
| `router/dispatch.py` | 新 | 总分发器：WxMsg → 处理动作 | 新 |
| `robot.py` | 改 | 把 `Wcf` 换成 `WxAdapter`；`processMsg` 委托给 `router.dispatch` | 改 |
| `main.py` | 改 | `Wcf` 初始化路径调整 | 改 |
| `Lexxue_api.py` | 不改 | 现有 HTTP API 函数原样保留 | — |
| `configuration.py` / `config.yaml` | 改 | 新增 `weixin_path`、`decrypt_repo`、`order_safety` 几个键 | 改 |
| `关键词回复.json` / `关键词发图.json` / `菜单格式.json` | 不改 | 由 `router/template.py` 加载 | — |
| `requirements.txt` | 改 | 去掉 `wcferry`，加 `uiautomation`、`pyperclip`、`pywin32`、`requests`（已有）等 | 改 |

## 4. 组件契约（接口定义）

### 4.1 `wx/msg.py`
```python
@dataclass
class WxMsg:
    id: int
    type: int             # 1=文本 3=图片 37=好友请求 10000=系统
    sender: str           # wxid
    roomid: str           # 群 id；私聊为空串
    content: str          # 文本或 XML
    is_self: bool
    ts: int

    def from_group(self) -> bool
    def from_self(self) -> bool
    def is_at(self, wxid: str) -> bool   # 解析 content 里的 @ 段
```

### 4.2 `wx/adapter.py`
```python
class WxAdapter:
    def __init__(self, weixin_exe: Path, sidecar_url: str, decrypted_db_dir: Path)
    def get_self_wxid(self) -> str
    def send_text(self, msg: str, receiver: str, at_list: str = "") -> int
    def send_image(self, image_path: str | Path, receiver: str) -> int
    def query_sql(self, db: str, sql: str) -> list[dict]   # 仅 Contact 查询走 ContactsBackend, 其他 raise NotImplementedError
    def get_alias_in_chatroom(self, wxid: str, roomid: str) -> str
    def accept_new_friend(self, v3: str, v4: str, scene: int) -> int
        # 保留 wcferry 签名（兼容 robot.py 原有 autoAcceptFriendRequest）。
        # 在 UIA 后端，v3/v4/scene 当作不透明请求标识：实现内部从 ContactsBackend
        # 或最新一条 type=37 消息找到对应请求项，然后在"新的朋友"面板点击"通过"。
    def enable_receiving_msg(self) -> None
    def get_msg(self, timeout: float = 1.0) -> WxMsg
    def is_receiving_msg(self) -> bool
```

### 4.3 `wx/receive.py`
```python
class ReceiveBackend:
    def __init__(self, decrypt_repo: Path, msg_queue: Queue[WxMsg], contacts: ContactsBackend)
    def start(self) -> None
    def stop(self) -> None
    def is_alive(self) -> bool
    def _translate_event(self, sse_event: dict) -> WxMsg | None
```

### 4.4 `wx/send.py`
```python
class SendBackend:
    def __init__(self, weixin_exe: Path, contacts: ContactsBackend)
    def attach(self) -> None
    def send_text(self, receiver_wxid: str, msg: str, at_wxids: list[str] = ()) -> bool
    def send_image(self, receiver_wxid: str, image_path: Path) -> bool
    def accept_friend_request_via_ui(self, req_id: str) -> bool   # type=37 走 UI 点击通过
```

### 4.5 `wx/contacts.py`
```python
class ContactsBackend:
    def __init__(self, decrypted_db_path: Path)
    def refresh(self) -> None
    def wxid_to_name(self, wxid: str) -> str | None
    def name_to_wxid(self, name: str) -> str | None
    def alias_in_room(self, wxid: str, roomid: str) -> str
    def all_contacts(self) -> dict[str, str]
```

### 4.6 `router/dispatch.py`
```python
class Dispatcher:
    def __init__(self, wx: WxAdapter, config: Config, llm: BaseLLM, order_handler: OrderHandler)
    def handle(self, msg: WxMsg) -> None
    # 内部匹配链：
    # 1. msg.type == 37 → 好友请求 → auto_accept
    # 2. 黑名单 / from_self → 忽略
    # 3. 关键词模板（关键词回复.json / 关键词发图.json / 菜单格式.json）→ 静态回复
    # 4. order intent classifier → OrderHandler
    # 5. fallback → LLM 闲聊
```

### 4.7 `router/order.py`
```python
class OrderHandler:
    def __init__(self, lexue_creds: dict, llm: BaseLLM, wx: WxAdapter, audit_log: Path)

    def looks_like_order_intent(self, text: str) -> bool
    def extract_fields(self, text: str, history: list[str]) -> OrderDraft | MissingFields
    def request_confirmation(self, msg: WxMsg, draft: OrderDraft) -> None  # 发"请确认 [...]"
    def on_user_reply(self, msg: WxMsg) -> None  # 处理 "确认" / "取消" / 修正字段
    def place_order(self, draft: OrderDraft) -> OrderResult                # 调 Lexxue_api.xd()
    def audit(self, event: dict) -> None
```

```python
@dataclass
class OrderDraft:
    school: str
    user: str
    password: str
    platform: str   # noun
    kcid: str
    kcname: str
    requester_wxid: str
    created_at: int
    confirmed: bool = False
```

## 5. 数据流

### 5.1 接收路径
1. 用户/群发消息 → Weixin 4.1.7.30 写入加密 SQLCipher DB
2. `wechat-decrypt` sidecar（独立子进程）监听 DB / 内存 → SSE 推送事件
3. `ReceiveBackend` 订阅 SSE，按事件类型翻译为 `WxMsg`
4. `WxAdapter` 内部 `Queue[WxMsg]` 缓冲
5. main loop 调 `wx.get_msg()` → `Dispatcher.handle(msg)`

### 5.2 分发路径
```
Dispatcher.handle(msg):
    if msg.type == 37:
        auto_accept(msg) → send_welcome()
        return
    if msg.from_self() or in_blacklist(msg.sender):
        return
    if template_match(msg.content):           # 静态关键词
        send static reply / image / menu
        return
    if order_handler.is_pending_for(msg.sender):
        order_handler.on_user_reply(msg)      # 处于确认等待中
        return
    if order_handler.looks_like_order_intent(msg.content):
        draft = order_handler.extract_fields(...)
        if draft.complete:
            order_handler.request_confirmation(msg, draft)
        else:
            wx.send_text(missing_fields_prompt, msg.sender)
        return
    # fallback：LLM 闲聊
    wx.send_text(llm.chat(msg.content), msg.sender)
```

### 5.3 发送路径
1. `WxAdapter.send_text(msg, wxid, at_list)` 调用
2. `ContactsBackend.wxid_to_name(wxid)` → display_name
3. `SendBackend.attach()`（首次会启动 Weixin / 找窗口）
4. UIA: 定位搜索框 → 输入 display_name → 回车选中会话 → 焦点至输入框 → 剪贴板贴 msg → Ctrl+Enter / Enter 发送
5. 每次发送加 50–200ms 随机抖动 + 节流（≥ 800ms/条），避免触发风控

### 5.4 下单完整流程
```
User: "下单 北京理工 学号18543 密码wjx 形势与政策 课程40"
  → looks_like_order_intent = True
  → LLM extract → OrderDraft(school=..., user=..., password=..., kcid=..., kcname=..., platform=?)
  → 缺 platform → 反问："请补充平台编号"
User: "1736"
  → 补全 → request_confirmation
  → Bot: "确认下单:\n学校: 北京理工\n课程: 形势与政策(40)\n账号: 18543\n回复'确认'下单 / '取消'放弃 (5分钟有效)"
User: "确认"
  → place_order → Lexxue_api.xd(...) → 写入 audit log
  → Bot: "下单成功" 或 "下单失败：<msg>"
```

## 6. 错误处理与可靠性

| 故障 | 检测 | 响应 |
|---|---|---|
| Weixin 主窗口未找到 | UIA 查找超时 | 启动 Weixin → 等 5s → 重试一次 → 失败则告警（推送到 filehelper） |
| wechat-decrypt sidecar 崩溃 | 心跳超时 / SSE 断流 | 整体重启 sidecar，最多 3 次；超出则告警 |
| 解密 key 提取失败 | sidecar 报错 | 提示用户登录 Weixin 后再启动 bot |
| UIA 发送失败（窗口被遮挡等） | 发送后队列消息 / 截图比对 | 重试 1 次；仍失败 → 写失败队列 + 告警 |
| LLM 提取字段错误 | 字段格式校验失败 | 反问用户补充；最多 3 轮，超出走 fallback "联系客服" |
| Lexue API 调用 5xx / 超时 | response 状态 | 退避重试 3 次；最终失败回执给用户 + audit log |
| 用户在确认窗口超时未回 | OrderDraft.created_at + 5min | 自动丢弃 draft，回执"确认超时" |

**日志：**
- `logs/bot.log` — 主流程
- `logs/audit/orders.jsonl` — 所有下单 draft、确认、结果（不可删，供事后审计）
- `logs/sidecar.log` — wechat-decrypt 输出

**安全门：**
- `OrderHandler.place_order` 唯一调用点。每次必经过：(a) 字段完整 (b) 用户回复 "确认" (c) 在 5min 内
- 配置项 `order_safety.dry_run`：开启后只走流程不调 `xd()`，用于首部署验证

**状态持久化：**
- `OrderHandler` 内部 `pending_drafts: dict[wxid, OrderDraft]` 仅在内存。bot 重启会丢失未确认的 draft，用户重启后需重新发起下单。这是可接受的简化（5min 窗口本来就不长）。
- 已确认的订单和最终结果通过 `logs/audit/orders.jsonl` 持久化，重启不丢。
- `daily_limit` 计数：日切复位的简单实现是启动时读取当天 audit log 行数初始化，运行时计数；进程跨日重启自然重置。

## 7. 配置变更

新增 `config.yaml` 键：
```yaml
weixin:
  exe: "C:/Program Files/Tencent/Weixin/Weixin.exe"
  sidecar_repo: "./wx/sidecar/wechat-decrypt"
  sidecar_url: "http://127.0.0.1:5678"
  decrypted_db_dir: "./wx/decrypted"

lexue:
  user: "1492246"
  pass: "..."   # 从 Lexxue_api.py 迁移到 config
  url: "http://lxuexi.cn/"

order_safety:
  dry_run: true          # 首部署强制 true，验证后改 false
  confirm_timeout_sec: 300
  max_extract_rounds: 3
  daily_limit: 50        # 每日订单上限，超过停手
  per_user_cooldown_sec: 60

llm:
  intent_model: deepseek  # 用于意图分类 + 字段提取
  chitchat_model: deepseek
  intent_prompt_path: prompts/order_intent.md
  extract_prompt_path: prompts/order_extract.md
```

## 8. 测试策略

| 层级 | 内容 |
|---|---|
| 单元 | `WxMsg.is_at()`、`Dispatcher.handle()` 分支、`OrderHandler.extract_fields()`（mock LLM）、`ContactsBackend` 查询 |
| 集成 | `ReceiveBackend` ↔ wechat-decrypt mock SSE feeder；`SendBackend` 在真实 Weixin 上跑（手动小号） |
| 端到端 | dry_run 模式跑完整下单流程：模拟用户消息 → 看是否生成 OrderDraft + 请求确认 + 收到 "确认" 后**不调 xd()**（dry_run），audit log 完整 |
| 验收 | 关闭 dry_run，在小号 + 测试乐学账号上跑一次真实下单 |

## 9. 落地分期（建议 writing-plans 沿用此分期）

- **Phase 0 (0.5d)**：仓库准备 — 引入 wechat-decrypt submodule，requirements 更新，config 模板扩展
- **Phase 1 (1.5d)**：`wx/` 包整套 — msg/contacts/receive/send/adapter；写一个 smoke 脚本（不接 robot.py）跑通"启动 → 收到消息打印 → 主动发一条 'pong' 到 filehelper"
- **Phase 2 (0.5d)**：robot.py 切换 — `Wcf` → `WxAdapter`，老 chitchat 流程跑通
- **Phase 3 (1d)**：`router/dispatch.py` + 模板匹配 — 关键词回复 / 图片 / 菜单 / 友情请求自动通过，全部接进 dispatch
- **Phase 4 (1.5d)**：`router/order.py` — intent 分类 + 字段提取 + 确认状态机；dry_run 模式
- **Phase 5 (0.5d)**：联调 + 关闭 dry_run + 验收

合计 ~5.5 天工作量。

## 10. 风险与未决项

1. **wechat-decrypt 对 4.1.7.30 的覆盖**：README 标注 "WeChat 4.0+"，需要 Phase 0 验证 4.1.7.30 能成功提取 key 并实时监听。失败则需要降级方案（纯 UIA 收发）。
2. **UIA 发送的稳定性**：Weixin 4.x 控件结构未深入摸过，可能存在"搜索框定位不稳定"等问题。Phase 1 用 1 天 spike 做技术预研，必要时落地 `uiautomation` + `inspect.exe` 的控件树记录到 `docs/uia-anchors.md`。
3. **下单意图分类的误报率**：闲聊很容易被误判成下单。需要意图分类 prompt 谨慎设计，并以"宁可漏判不要误判"为基准。
4. **风控**：虽然不伪造版本，但 UIA 高频发送仍可能被识别。`per_user_cooldown_sec` 和 `daily_limit` 是第一道防线。
5. **乐学 API 变更**：`Lexxue_api.py` 里 `jd()` 函数有未定义变量 `passw`（line 89），说明这块代码可能没经过测试。不在本次范围内修复，但下单失败时记录原始响应供后续调试。
6. **跨日订单计数**：如果机器人当天频繁重启，每次重启都重新读 audit 日志计数，CPU/IO 开销极小（一天最多 50 条）。不需要单独的 daily_count 文件。

## 11. 何时算完成

- [ ] `python main.py` 启动后，Weixin 4.1.7.30 正常运行，bot 接收消息无卡顿
- [ ] 给 bot 发好友请求，5s 内自动通过且收到欢迎语
- [ ] 在群里 @bot 说话，bot 用 LLM 回复
- [ ] 私聊关键词命中，发对应静态回复 / 图 / 菜单
- [ ] 私聊"下单 ..." → 完整确认流程 → dry_run 模式下 audit log 写入，未调用 Lexxue
- [ ] 关闭 dry_run，小号 + 测试乐学账号上跑通一次真实下单
- [ ] Weixin 进程崩溃 / sidecar 崩溃后自动恢复（验证 supervisor 逻辑）
