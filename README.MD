# WechatBot

> 基于 Weixin 4.x + UIA + wechat-decrypt sidecar 的多账号微信机器人。
> 内置 Web Dashboard、文件传输助手命令通道、LLM 路由与自动下单（乐学 API）。

[![tests](https://github.com/AITCX08/WechatBot/actions/workflows/test.yml/badge.svg)](https://github.com/AITCX08/WechatBot/actions)
![python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python&logoColor=white)
![platform](https://img.shields.io/badge/Windows-10%2F11-007ACC?logo=windows&logoColor=white)
![license](https://img.shields.io/badge/license-MIT-green)

---

## 项目背景

原项目（`lich0821/WeChatRobot`）依赖 `wcferry` + 微信 3.9.12.51。2026-05 起腾讯服务端拒绝该旧版登录，并且上游对 4.x 不打算适配。

本项目把架构迁到 **Weixin 4.x**，用：
- **`wechat-decrypt` sidecar**（实时解密 SQLCipher DB + SSE 推消息）做接收
- **`uiautomation` UIA** 操作 Weixin 主窗口做发送
- **FastAPI + Alpine 单页**做 Web Dashboard

不伪造版本，正常扫码登录，**账号风险等同人工操作**。

---

## 功能一览

### 多账号架构
每个账号一份独立 `WxAdapter / Robot / OrderHandler / 接收队列 / audit log`，互不干扰。

- 配置驱动：`config.yaml` 里 `weixin.instances` 列表
- UI 动态添加：Dashboard "+ 添加账号" → 写入 `data/runtime_accounts.json`，重启不丢
- 每账号独立 sidecar 端口 + 独立解密 DB 路径

### Dashboard（http://127.0.0.1:9090）
- 全局状态卡：运行时长 / 在线账号数 / 队列深度 / 待确认订单 / 今日订单
- 每账号卡片：状态徽章 + Weixin/Sidecar/队列/订单指标 + 启停/暂停/恢复/删除按钮
- 4 个 Tab：日志（等级 + 关键词过滤）/ 消息（实时时间线）/ 订单（待确认 + 事件流）/ 联系人
- SSE 实时推送 1s 一帧；失败操作弹红 toast
- standalone 预览模式可单独运行（`python -m dashboard`）

### Filehelper 命令通道
操作者给自己的"文件传输助手"发命令，bot 在同一窗口回复。

| 命令 | 中文别名 | 作用 |
|---|---|---|
| `/status` | 状态 | 运行状态摘要 |
| `/pause` | 暂停 | 全局暂停回复 |
| `/resume` | 恢复 | 取消暂停 |
| `/report [today\|yesterday\|7d\|30d]` | 日报 / 今日 / 报告 | 下单统计报告 |
| `/pending` | 待确认 / 待办 | 待确认订单列表 |
| `/pricing` | 价格 / 价目 | 当前价格表 |
| `/help` | 帮助 | 命令清单 |

**安全门**：仅响应 `from_self=True && receiver=="filehelper" && type==1` 的消息——别人发 `/pause` 无效。

### 主动通知
事件发生时 bot 自动推到对应账号的 filehelper：
- 🟢 上线 / 🔴 下线
- ✅ 真实下单成功 / 🟡 dry_run 下单 / ❌ 下单失败
- ❗ 错误 / 配额触顶

支持：每账号+每事件类型独立 cooldown（默认 5 分钟）；CRITICAL 事件绕过冷却；`quiet_hours` 静默时段（INFO 抑制，CRITICAL 仍推）。

### LLM 路由 + 自动下单
对群消息和私聊消息：
1. 关键词模板回复（`关键词回复.json` / `关键词发图.json` / `菜单格式.json`）
2. 下单意图分类（LLM JSON 输出）
3. 字段提取 + 缺字段反问
4. 用户回 `确认` → 调乐学 API `xd()` → 成功推 filehelper
5. dry_run 模式：走完所有流程但不真调 API，写 audit log

每日报告（默认 22:00）按 `pricing` 配置算金额，汇总笔数/成功率/服务用户数/Top 课程。

---

## 快速启动

### 0. 环境
- Windows 10/11
- Python 3.10+
- Weixin 4.x（路径 `C:\Program Files\Tencent\Weixin\Weixin.exe`，多账号需复制到不同目录）

### 1. 克隆 + 依赖

```bash
git clone --recursive https://github.com/AITCX08/WechatBot.git
cd WechatBot
pip install -r requirements.txt
```

`--recursive` 是为了一起拉 `wx/sidecar/wechat-decrypt` submodule。漏了可补：

```bash
git submodule update --init --recursive
```

### 2. Sidecar 准备（首次）

```bash
cd wx/sidecar/wechat-decrypt
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cd ..\..\..
```

### 3. 配置

首次运行会自动从 `config.yaml.template` 复制 `config.yaml`。改 `weixin.exe` 指向你的 Weixin.exe 路径（默认即标准安装路径）。

多账号示例：

```yaml
weixin:
  dashboard_port: 9090
  instances:
    - name: main
      label: 主账号
      exe: "C:/Program Files/Tencent/Weixin/Weixin.exe"
      sidecar_url: "http://127.0.0.1:5678"
      decrypted_db_path: "./wx/decrypted/main/contact.db"
    - name: support
      label: 客服号
      exe: "C:/Program Files/Tencent/Weixin2/Weixin.exe"
      sidecar_url: "http://127.0.0.1:5679"
      decrypted_db_path: "./wx/decrypted/support/contact.db"

order_safety:
  dry_run: true              # 首部署务必 true，验证后再改 false
```

### 4. 启动

```bash
# 方式 A：双击 start.bat（推荐）
start.bat

# 方式 B：命令行
python main.py -c 0
```

打开 http://127.0.0.1:9090 → 点账号卡片的 **▶ 启动** → Weixin 窗口弹出 → **手机扫码** → 登录完成后 bot 自动接管。

### 5. 仅预览 Dashboard（不连 Weixin）

```bash
python -m dashboard --port 9090
```

会注册 2 个演示账号，启动按钮会被禁用（因为没注册 factory）。

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│  main.py / robot.py                                          │
└────────────────────────┬─────────────────────────────────────┘
                         │
       ┌─────────────────┼─────────────────────┐
       ▼                 ▼                     ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐
│ Dashboard    │  │ AccountMgr   │  │  Notifier (filehelper)│
│ FastAPI+SSE  │  │ N x Robot     │  │  Reporter (audit→报告)│
└──────────────┘  └──────┬───────┘  └──────────────────────┘
                         │
              ┌──────────┴───────────┐
              ▼                      ▼
       ┌──────────────┐       ┌──────────────┐
       │ Per-account  │       │ Per-account  │
       │ Robot 1      │  ...  │ Robot N      │
       │ + Dispatcher │       │ + Dispatcher │
       │ + OrderHand. │       │ + OrderHand. │
       └──────┬───────┘       └──────┬───────┘
              │                      │
              ▼                      ▼
       ┌──────────────┐       ┌──────────────┐
       │ WxAdapter 1  │       │ WxAdapter N  │
       │  + UIA send  │       │              │
       │  + SSE recv  │       │              │
       │  + Contacts  │       │              │
       └──────┬───────┘       └──────┬───────┘
              │                      │
              ▼                      ▼
       ┌──────────────┐       ┌──────────────┐
       │ Weixin 4.x   │       │ Weixin 4.x   │
       │ (instance 1) │       │ (instance N) │
       └──────────────┘       └──────────────┘
```

### 关键模块

| 路径 | 责任 |
|---|---|
| `wx/msg.py` | `WxMsg` 数据类（wcferry.WxMsg shim） |
| `wx/adapter.py` | `WxAdapter` facade：组合 contacts/recv/send + 暴露 wcferry 兼容子集 |
| `wx/contacts.py` | 读解密 DB 的联系人三向查询 + 缓存 |
| `wx/receive.py` | 启停 sidecar 子进程，订阅 SSE，转 WxMsg 入队 |
| `wx/send.py` | UIA 操作 Weixin 主窗口（发文/发图/同意好友） |
| `wx/sidecar/wechat-decrypt/` | git submodule（[ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt)） |
| `router/dispatch.py` | 入站消息路由链 |
| `router/commands.py` | filehelper 命令注册表 + 7 个 handler |
| `router/template.py` | 关键词/图片/菜单 JSON 匹配 |
| `router/order.py` | 下单意图 + 字段提取 + 确认状态机 + 调乐学 API |
| `router/order_draft.py` | `OrderDraft` 数据类 |
| `router/notifier.py` | 事件 → filehelper 通知 + cooldown + quiet_hours |
| `router/reporter.py` | audit log 时间窗口聚合 + 文本渲染 |
| `router/pricing.py` | 平台/课程二级查表 |
| `dashboard/server.py` | FastAPI + SSE + REST 端点 |
| `dashboard/state.py` | 单例 BotState（含 AccountManager） |
| `dashboard/accounts.py` | `AccountManager` 生命周期状态机 |
| `dashboard/launcher.py` | spawn Weixin.exe + 等待登录窗口 |
| `dashboard/log_handler.py` | logging → 内存环形缓冲 |
| `dashboard/templates/index.html` | 单页 UI（Tailwind+Alpine CDN） |
| `prompts/order_intent.md` | LLM 意图分类 prompt |
| `prompts/order_extract.md` | LLM 字段提取 prompt |
| `Lexxue_api.py` | 乐学 HTTP API（既有，不动） |

---

## API 速查（Dashboard 后端）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 单页 HTML |
| GET | `/api/status` | 全局状态 + 各账号 snapshot + factory_registered |
| POST | `/api/pause` `/api/resume` | 全局暂停/恢复 |
| GET | `/api/accounts` | 账号列表 |
| POST | `/api/accounts` | 添加账号 |
| DELETE | `/api/accounts/{name}` | 删除账号（仅 STOPPED 状态） |
| POST | `/api/accounts/{name}/start\|stop\|pause\|resume` | 账号生命周期 |
| GET | `/api/logs?n=&level=&q=&since_seq=` | 日志（支持过滤 + 增量） |
| GET | `/api/messages?n=&q=&since_seq=` | 消息时间线 |
| GET | `/api/audit?n=&event=&since_seq=` | 审计事件 |
| GET | `/api/contacts?q=&n=&account=` | 联系人搜索 |
| GET | `/api/orders/pending?account=` | 待确认订单 |
| GET | `/api/events` | SSE 实时推送（status/logs/messages/audit） |

---

## 测试

```bash
pytest tests/ -v
```

当前 184 测试，覆盖：
- `wx/` 包（msg/contacts/receive/adapter）
- `router/` 包（dispatch/template/order/commands/pricing/reporter/notifier）
- `dashboard/` 包（state/server/ring_buffer/accounts）

每个 PR 由 [GitHub Actions](.github/workflows/test.yml) 自动跑全套。

---

## 故障排查

| 现象 | 可能原因 | 处置 |
|---|---|---|
| Dashboard 加载但账号卡 Start 按钮变灰 | 用 `python -m dashboard` 启动（standalone，无 factory） | 改用 `python main.py -c 0` |
| 点 Start 后账号变 ERROR + last_error 显示 | sidecar 没起 / Weixin 没装 / 路径不对 | 检查 `weixin.exe` 路径；先手动跑 sidecar `python wx/sidecar/wechat-decrypt/monitor_web.py` |
| 5 分钟内 Weixin 没弹登录窗口 | `ensure_weixin_running` 超时 | 改 `weixin.login_timeout_sec` |
| filehelper 发命令没反应 | 不是 self-message / receiver 不是 filehelper | 必须在自己的"文件传输助手"对话里发 |
| /pause 在暂停时无效 | 你试错命令了？/pause 在暂停时直接接受（幂等），/resume 才能解除 | 看 status 确认状态 |
| dry_run 模式下单都没真调 API | 故意的，验收用 | `config.yaml` 改 `order_safety.dry_run: false` |
| sidecar SSE 连不上 | 端口冲突 / sidecar 路径不对 | 每账号 `sidecar_url` 必须互不冲突 |

详尽诊断见 `docs/superpowers/STATUS-2026-05-22.md`。

---

## 文档

| 路径 | 内容 |
|---|---|
| `docs/superpowers/specs/` | 设计 spec 历史 |
| `docs/superpowers/plans/` | 实施计划（按日期） |
| `docs/superpowers/STATUS-*.md` | 阶段性状态报告 |
| `docs/uia-anchors.md` | Weixin 4.x UIA 控件定位器（需要用户校准） |
| `docs/sidecar-verification.md` | wechat-decrypt 在 4.x 上的验证记录 |

---

## Local RPA text send service

This optional service accepts **one text message at a time** and controls only an
already-running, already-logged-in PC Weixin client through the existing UI
Automation sender. It does not start, stop, restart, inject into, or use a
private protocol for Weixin.

1. Keep the default `rpa.enabled: false` in `config.yaml` until the local
   setup has been reviewed. When enabling it, keep `host: "127.0.0.1"` and
   start with the sole default allowlist recipient, `filehelper`.
2. Set a local shell-only API key; do not place it in `config.yaml`:

   ```powershell
   $env:WECHAT_RPA_API_KEY = "replace-with-a-long-random-local-secret"
   ```

3. Start the service from this repository:

   ```powershell
   python -m rpa
   ```

4. Confirm the local listener before submitting any message:

   ```powershell
   Invoke-RestMethod http://127.0.0.1:9922/health
   ```

The service binds only to `127.0.0.1`. It requires a logged-in Weixin desktop
window and a readable configured contact DB when a send is requested. API
requests require the `X-API-Key` header, recipients must be explicitly
allowlisted, and responses/audit data omit message text. Do not use it to send
messages until the operator has explicitly authorized the individual send.

---

## License

MIT。本项目仅供学习交流，禁止商用/灰产；微信账号风险由使用者承担。

致谢：
- [`lich0821/WeChatFerry`](https://github.com/lich0821/WeChatFerry) — 原项目灵感
- [`ylytdeng/wechat-decrypt`](https://github.com/ylytdeng/wechat-decrypt) — Weixin 4.x 数据库解密 + 实时监听 sidecar
- [`yapf/uiautomation`](https://github.com/yinkaisheng/Python-UIAutomation-for-Windows) — Windows UIA Python 绑定
