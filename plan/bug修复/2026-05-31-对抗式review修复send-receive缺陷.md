# Bug 修复：对抗式 review 揪出的 send/receive 缺陷批量修复

> 日期：2026-05-31 ｜ 类型：bug 修复（28-agent 对抗式 review） ｜ 状态：✅ 已修复并推送
> commits：`c01c56a`（第一批 5 处）、`c84e35a`（第二批 3 处 + 文档）；211 测试全绿

## 背景（现象）

把 receive/contacts 对齐真实 sidecar 契约（`90edc05`）后，用 28-agent workflow 做对抗式
review（4 lens 并行找问题 + 每条 skeptic 默认证伪核验），从 wx/send.py + wx/receive.py +
wx/contacts.py + 上层消费方共**确认 16 个真问题**（驳回 8 个误报）。按严重度 + 是否可单测
分两批修，并对 7 条做了「不修」的克制取舍。

## 改了什么

### 第一批 `c01c56a`（critical + major，可单测）
- **[critical] filehelper 命令回复发不出**：回复经 `send_text(receiver="filehelper")`，但
  filehelper 不在 contact 表 → `wxid_to_name` 返回 None → return False，通道「能进不能出」。
  修：`SendBackend.BUILTIN_NAMES={filehelper:文件传输助手}` + `_resolve_display()` 优先查内置。
- **[major] is_alive 不消费心跳**：sidecar 空闲每 15s 发 `: hb`，但 is_alive 只看「最近投递
  消息」→ 低流量健康 sidecar 30s 被误判死亡。修：`_last_line_ts` 记录任意 SSE 行（含心跳），
  is_alive 用 `max(event_ts, line_ts)`。
- **[major] 群回复 raw @chatroom id**：无备注/群名的群回退成 `xxx@chatroom` 原串搜不到。
  修：`_resolve_display` 拒绝 `endswith('@chatroom')` 与 None。
- **[major] _focus_input 误选搜索框**：搜索框也是 EditControl。修：`_pick_input_edit()` 排除
  `Name=='搜索'` 再取底部。
- **[major→文档] _open_chat 无选中校验**：输名+Enter 选首条，重名发错人。robust 修法需真机
  定位标题栏 → 文档化为真机任务（docs/uia-anchors.md）。

### 第二批 `c84e35a`（major + minor，可单测）
- **[major] 群消息 sender 当 wxid 用**：群 sender 是显示名，下单 pending 键/冷却/审计/回信
  全错乱。修：dispatch 用 `order_eligible = not msg.from_group()` 门控，群消息不进下单流程。
- **[minor] filehelper 桥接缺 is_group 守卫**：群 id 字面=filehelper 被提权为本人命令。
  修：`username==FILEHELPER_WXID and not is_group`。
- **[minor] 脏 timestamp 静默塌成 ts=0**：修：不可解析的 timestamp 当坏帧丢弃 + warn。
- **[minor→文档] type==37 好友请求死代码**：真实 SSE 永不产 37。文档标注能力缺口。

## 为什么这么改（取舍）

karpathy 克制原则——**不修**这 7 条（合理现状/猜测/YAGNI）：
- [5] 异步帧判别靠 body 有无 'event' 键：测试证明分类正确，重构收益低
- [7] id=ts 同秒碰撞：上层不依赖 id 唯一
- [9]死查询清理 [10]重名去重 [13]剪贴板恢复 [15]异常分层：nit/cleanup，无当前需求
- [12] 群@纯文本：已知 MVP 限制，真机才能做真@

## 怎么验证

- TDD：每条先写失败测试看 RED，再修看 GREEN
- 全套 → **211 passed**；受影响 3 文件 dispatch 14 + receive 17 + send 12 = 43 全绿
- 两 commit 工作树干净（已用 Grep 工具逐文件核验标记，规避终端中文乱码误判）

## 过程教训（诚实记录）

ultracode 高速并行下多次因单条 bash 失败（GBK 解码 / 反引号 / subprocess encoding）
连带取消整批，导致部分 Write/commit 没落地、且一次终端输出乱码差点误判文件状态。
**每次都靠「提交前用 git rev-parse + Grep 工具核验真实磁盘状态」逮住**——这是 ultracode
下的硬纪律：高吞吐不等于可盲信，断言前必须有干净证据。后续已改为：测试用
`errors='replace'`、提交信息走文件、状态核验用 Grep 工具而非 bash grep。

## 关联

- 契约文档：`docs/sidecar-verification.md`（含好友请求缺口 + no-phone blockers）
- UIA 真机任务：`docs/uia-anchors.md`（_open_chat 标题栏校验）
- 前序：`plan/bug修复/2026-05-31-receive与sidecar契约对齐.md`
