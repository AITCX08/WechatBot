# 功能开发：Web Dashboard 看板

> 日期：2026-05-22 ｜ 类型：功能开发 ｜ 状态：✅ 已上线（v1.1）

## 背景

需要一个网页控制台，无需命令行即可启停账号、看运行状态、查日志、查订单。端口 `http://127.0.0.1:9090`，仅本机访问。

## 改了什么

| 文件 | 职责 |
|------|------|
| `dashboard/server.py` | FastAPI 应用 + REST 端点 + SSE 流；`create_app()` / `run_in_thread()` |
| `dashboard/state.py` | 单例 `BotState`（含 AccountManager + 三个 RingBuffer：logs/messages/audit） |
| `dashboard/ring_buffer.py` | 线程安全定长 FIFO，带 monotonic seq（支持增量拉取） |
| `dashboard/log_handler.py` | logging.Handler，把日志转发进 BotState.logs |
| `dashboard/templates/index.html` | 单页 UI（Tailwind + Alpine via CDN，零构建） |
| `dashboard/__main__.py` | `python -m dashboard` standalone 预览入口 |

对外接口（REST + SSE）：
- `GET /` 单页 / `GET /api/status` 全局状态 / `POST /api/pause|resume` 全局暂停
- `GET /api/logs|messages|audit`（过滤 + 增量 since_seq）/ `GET /api/contacts` / `GET /api/orders/pending`
- `GET /api/events` SSE 1s 一帧（status/logs/messages/audit）

UI：顶部全局暂停 + 6 张状态卡 + 账号列表 + 4 个 Tab（日志/消息/订单/联系人）。

## 为什么这么改

- dashboard 同进程跑（uvicorn 后台线程），不独立部署，最低成本
- 先启 dashboard 再做 bot 初始化：bot 挂了 UI 仍能看到错误日志
- 环形缓冲在内存（重启丢失）；订单 audit 落文件（重启不丢）
- router 层用「惰性 import + 宽 except」调 dashboard，未初始化时降级 no-op

## 怎么验证

- 28 个单元测试全绿（ring_buffer 8、state 7、server 13）
- 裸 socket 实测 `/api/status` 返回 200 + JSON
- standalone 模式（`python -m dashboard`）可纯预览 UI

## 关联

- commits：`498762f`、`855c891`、`21f0eec`
- 后续 bug：`plan/bug修复/2026-05-23-Dashboard启动按钮无反应.md`
