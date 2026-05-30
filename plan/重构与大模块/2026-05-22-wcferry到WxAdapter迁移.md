# 重构与大模块：wcferry → WxAdapter 迁移

> 日期：2026-05-22 ｜ 类型：架构级替换 ｜ 状态：✅ 已完成（v1.0）

## 背景

腾讯服务端拒绝微信 3.9.12.51 登录，wcferry 失效且不适配 4.x。必须把整个「微信交互层」
从 wcferry 换成自研方案，同时让上层业务代码（robot.py）尽量不动。

## 改了什么

设计核心：**契约 + 双后端 + facade**。把 `wcferry.Wcf` 当契约（robot.py 实际只用 6 个方法），
用同形状的 `WxAdapter` 替换，内部把「收」「发」分到独立后端。

```
robot.py (几乎不动: from wx import WxAdapter as Wcf)
   │ 6 个方法契约
   ▼
WxAdapter (facade)
   ├─► ReceiveBackend  → wechat-decrypt sidecar (子进程 + SSE)
   ├─► SendBackend     → uiautomation 驱动 Weixin 窗口
   └─► ContactsBackend → 读解密后的 SQLite DB
```

| 文件 | 职责 |
|------|------|
| `wx/msg.py` | WxMsg 数据类（mimic wcferry.WxMsg） |
| `wx/adapter.py` | facade，暴露 wcferry 兼容子集 |
| `wx/receive.py` | sidecar 子进程 + SSE 订阅 → 队列 |
| `wx/send.py` | UIA 发文/发图/同意好友 |
| `wx/contacts.py` | 读解密 DB，三向查询 + 缓存 |
| `wx/sidecar/wechat-decrypt/` | git submodule |

依赖图无环、单向；每个 backend 可用 mock 独立测试。

## 为什么这么改

1. **sidecar 当子进程而非 import 模块**：解耦更新节奏，只通过「SSE 流 + sqlite 文件」两个
   稳定接口对话，它内部怎么 hook 与我们无关
2. **send 用 uiautomation 自己写薄封装**：不用第三方实验性 UIA 库（多为 1★ 实验品）
3. **WxMsg 完全模仿 wcferry.WxMsg**：属性 + 方法全对齐，robot.py 的 processMsg 一行不改也能跑

范围裁剪（YAGNI）：只实现 robot.py 实际用到的接口子集；`query_sql` 只支持 Contact 表，
其他 raise NotImplementedError；不做朋友圈/视频/下载/撤回检测。

## 怎么验证

- 56 个单元测试全绿（msg/contacts/receive/adapter 各自 mock 测试）
- robot.py 改动 ≤ 10 行（主要是换 import）；Lexxue_api.py、关键词 JSON、AI 模型层全不动

## 遗留 / 需人工验证

- sidecar SSE 事件字段名基于预期写的，需在真实 Weixin 4.x 核对后调 `wx/receive.py:_translate_event`
- UIA 定位器需用 inspect 校准 `docs/uia-anchors.md`

## 关联

- 设计 spec：`docs/superpowers/specs/2026-05-22-weixin4-migration-and-order-automation-design.md`
- 实施计划：`plan/实施计划/2026-05-22-Weixin4迁移与自动下单.md`
- 验证记录：`docs/sidecar-verification.md`、`docs/uia-anchors.md`
