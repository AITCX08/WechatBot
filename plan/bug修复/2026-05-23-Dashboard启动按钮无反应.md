# Bug 修复：Dashboard 启动按钮点了没反应

> 日期：2026-05-23 ｜ 类型：bug 修复 ｜ 状态：✅ 已修复（commit 3daaeea）
> 调试方法：systematic-debugging 四阶段

## 背景（现象）

用户点 Dashboard 账号卡片的「▶ 启动」按钮，没有任何反应。

### Phase 1 根因调查（先收证据，不臆测）
1. 探测 `127.0.0.1:9090` → dashboard 在跑
2. `GET /api/accounts` → 正常，账号都是 stopped
3. **模拟点击** `POST /api/accounts/demo-main/start`
   → **HTTP 400 `{"detail":"bot factory not registered"}`**
4. 翻前端 JS：`accStart(name) { fetch(...); }` —— **完全不读响应**

### 根因（双重 bug，互相独立）
| # | 根因 | 触发条件 |
|---|------|----------|
| 1 | standalone 模式（`python -m dashboard`）没注册 bot factory，Start 被服务端拒绝 | 仅 standalone |
| 2 | 前端 fetch 忽略响应，错误既不显示也不刷新状态 | 全模式 |

bug #1 = 「启动不了」，bug #2 = 「点了没反应」——合起来正好是用户描述的两个现象。

## 改了什么

**后端**（`dashboard/state.py` + `accounts.py`）
- `AccountManager.factory_registered` 属性
- `/api/status` 暴露 `factory_registered: bool`

**前端**（`dashboard/templates/index.html`）
- 新增 `apiCall(method, url, opts)`：读 `response.ok` + `detail`，失败弹红 toast、
  成功弹绿 toast + 立即刷新状态
- 6 个控件方法全换成 apiCall
- standalone 模式：顶部黄 banner 提示用 `python main.py -c 7`；Start 按钮 `:disabled`

## 为什么这么改

- 前端 fetch 必须读 `response.ok`——静默吞错误是「点了没反应」类 bug 的头号成因
- 用 `factory_registered` 让 UI 区分 standalone vs 真实模式，从根上避免误导

## 怎么验证

- [x] 137 个测试全绿（+5：factory_registered 属性 + status 字段 + 端点）
- [x] 实测 dashboard 重启后 HTML 含 apiCall/factory_registered/showToast/Standalone
- [x] `/api/status` 返回 `factory_registered: false`（standalone 模式）

## 关联

- commit：`3daaeea`
- 看板存档：`plan/功能开发/2026-05-22-Dashboard看板.md`
