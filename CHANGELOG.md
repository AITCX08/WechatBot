# CHANGELOG

格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号按业务里程碑分段（非语义化）。

---

## [2026-05-27] 生产化收尾

### Added
- 完整中文 `README.MD`：架构图 / 模块清单 / 多账号配置 / Dashboard API 速查 / Filehelper 命令表 / 故障排查表
- `start.bat` / `stop.bat` 一键启停脚本（Windows）
- GitHub Actions CI：windows-latest × Python 3.10/3.11/3.12 矩阵跑 pytest
- 调度器单元测试 7 个（`push_daily_report_to_all` 提取为可测函数）
- 本 `CHANGELOG.md`

### Changed
- `main._schedule_daily_reports` 内部闭包重构为模块级 `push_daily_report_to_all` 函数（可独立测试）

---

## [2026-05-25] Filehelper v2 — 主动通知 + 日报 + 价格

### Added
- `router/pricing.py` `PricingTable`：平台/课程二级查表 + `estimate_total`
- `router/reporter.py` `Reporter`：按时间窗口（today/yesterday/Nd）聚合 audit log，渲染中文文本
- `router/notifier.py` `Notifier`：事件分发到 filehelper，每账号+每事件类型独立 cooldown，支持 `quiet_hours`，CRITICAL 事件绕过限频
- 3 个新 filehelper 命令：`/report` / `/pending` / `/pricing`（含中文别名 日报/待确认/价格）
- 每日报告定时调度（`schedule` 库，默认 22:00 推送各运行中账号的 filehelper）
- Notifier 接入 `OrderHandler._audit`（成功/dry_run/失败/配额事件全自动推送）
- AccountManager 增加 `set_on_status_change` 回调；启停时自动推上下线
- Dispatcher 接收 reporter+pricing 注入 CommandContext

### Tests
- +38 个新测试（PricingTable 7、Reporter 8、Notifier 11、commands 8、order 2、accounts 2）
- 总测试 146 → 184

---

## [2026-05-23] Filehelper 命令通道 MVP + Dashboard 修复

### Added
- `wx/constants.py` `FILEHELPER_WXID = "filehelper"` 常量
- `wx/msg.py` `WxMsg` 新增 `receiver` 字段（默认 ""，向后兼容）
- `wx/receive.py` 从 SSE `to_user` 字段填充 receiver
- `router/commands.py`：`CommandContext` + `CommandRegistry` + `try_handle_filehelper_command` + 4 个 MVP handler（/status, /pause, /resume, /help + 中文别名）
- `router/dispatch.py` 在 `_handle` 第 0 步插入 filehelper 命令分支；`handle()` 让 filehelper 命令绕过 paused 标志（否则 /resume 解不了暂停）
- Dashboard 新增"+ 添加账号" UI + POST/DELETE 端点 + `data/runtime_accounts.json` 持久化（重启不丢）
- Dashboard 删除按钮（仅 STOPPED 状态可删）
- `AccountManager.unregister` / `factory_registered` 属性 / `set_persistence` 回调

### Fixed
- Dashboard 启动按钮"点了没反应" — 前端 fetch 不读 response 错误。新增 `apiCall` helper：失败弹红 toast，成功弹绿 toast + 立即刷新状态
- standalone 预览模式（`python -m dashboard`）添加禁用按钮 + 顶部黄色 banner 提示用 `python main.py -c 7`
- `/api/status` 暴露 `factory_registered: bool` 字段

### Tests
- +25 新测试（commands 18、dispatch 8 含 3 项关键安全测试）
- 总 105 → 130 → 146

### Security
- filehelper 命令只在 `from_self && receiver=="filehelper" && type==1` 三条件全部成立时识别。覆盖测试：别人 DM /pause 无效；自己群里 /pause 无效；自己 DM 别的朋友 /pause 无效

---

## [2026-05-22] Dashboard 多账号 + 添加账号

### Added
- `dashboard/accounts.py`：`AccountConfig` / `AccountState` / `AccountManager` 完整状态机（STOPPED → STARTING → RUNNING → STOPPING → ERROR）
- `dashboard/launcher.py` `ensure_weixin_running()`：spawn Weixin.exe + UIA 轮询登录窗口
- Dashboard 多账号视图：每账号独立状态卡 + 启停按钮 + 错误展示
- 全局暂停 + 顶部账号过滤器
- `config.WEIXIN_INSTANCES`：legacy 单账号配置自动合成 default 实例

### Tests
- +20 新测试（accounts 11、server 8、state +1）

---

## [2026-05-22] Dashboard MVP

### Added
- `dashboard/` 包：FastAPI 服务 + 单页 HTML（Tailwind + Alpine via CDN）
- `RingBuffer` 内存环形缓冲（线程安全，FIFO，monotonic seq）
- `BotState` 单例 + logging Handler 转发到内存缓冲
- 6 张状态卡 + 4 个 tab（日志/消息/订单/联系人）
- SSE `/api/events` 1s 一帧推送增量
- main.py 启动 dashboard 后台线程；`--dashboard-only` 模式

### Tests
- 28 新测试（ring_buffer 8、state 7、server 13）

---

## [2026-05-22] Weixin 4.x 迁移 + 自动下单

### Added
- `wx/` 包替换 `wcferry`：
  - `WxMsg` (shim) / `WxAdapter` (facade) / `ContactsBackend` (SQLite) / `ReceiveBackend` (sidecar SSE) / `SendBackend` (UIA)
  - `wx/sidecar/wechat-decrypt` git submodule
- `router/` 包：`TemplateMatcher` 关键词匹配；`Dispatcher` 路由链；`OrderHandler` 状态机
- `OrderDraft` 数据类 + `prompts/order_intent.md` / `order_extract.md` LLM prompts
- `configuration.py` 新增 `WEIXIN` / `LEXUE` / `ORDER_SAFETY` / `LLM` 配置块
- `robot.py` 删除内置 `NullOrderHandler` 占位，接入真实 OrderHandler
- `main.py` 用 WxAdapter 替换 Wcf 启动

### Removed
- `wcferry` 依赖（腾讯服务端拒绝 3.9.12.51 登录）

### Tests
- 56 测试（initial green baseline）

---

## 历史溯源

本项目基于 [`lich0821/WeChatRobot`](https://github.com/lich0821/WeChatRobot) fork。
2026-05 起所有改动详见 `docs/superpowers/specs/` 与 `docs/superpowers/plans/`。
