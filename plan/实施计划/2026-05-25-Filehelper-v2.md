# 实施计划：Filehelper v2（通知 + 日报 + 价格）

> 日期：2026-05-25 ｜ 类型：实施计划 ｜ 状态：✅ 已完成

## 背景

把 filehelper 升级为完整运维通道：主动事件通知 + 每日统计报告 + 基于价格表的金额汇总。
每个账号的通知发到各自的 filehelper。

## 分阶段任务（全部完成）

- [x] **V2-1**：`router/pricing.py` PricingTable（平台/课程二级查表 + estimate_total）
- [x] **V2-2**：`router/reporter.py` Reporter（按 today/yesterday/Nd 聚合 audit log + 中文渲染）
- [x] **V2-3**：`router/notifier.py` Notifier（事件 → filehelper，每账号+每事件 cooldown，
      quiet_hours 静默时段，CRITICAL 绕过限频）
- [x] **V2-4**：新增 /report /pending /pricing 命令 + 中文别名（日报/待确认/价格）
- [x] **V2-5**：Notifier 接入 OrderHandler._audit + AccountManager 上下线 hook
- [x] **V2-6**：每日报告定时调度（schedule 库，默认 22:00）
- [x] **V2-7**：config.yaml.template 文档化 pricing + filehelper 调优项

## 怎么验证

- [x] /report、/report yesterday、/report 7d 返回对应时窗统计
- [x] 上线/下线/下单成败 自动推 filehelper
- [x] 价格表缺课程 → 平台 default → 全局 default 逐级回退
- [x] 同事件 5 分钟冷却；CRITICAL（error/order_failure）绕过
- [x] 184 个测试全绿（+38）

## 收尾补强（2026-05-27）

- [x] `push_daily_report_to_all` 从调度器闭包提取为模块级可测函数 + 7 个测试
- [x] CHANGELOG.md 记录 6 个里程碑（191 测试）

## 关键决策

- Reporter 读 audit log 文件而非内存 RingBuffer（重启不丢历史）
- 限频 key = (account, event_type)，多账号互不干扰
- 金额从 pricing 配置算，不依赖乐学 API 返回价格（API 不返回价格）

## 关联

- 细节计划：`docs/superpowers/plans/2026-05-25-filehelper-v2.md`
- 功能存档：`plan/功能开发/2026-05-25-通知与日报系统.md`
- commits：`be6aebe` → `9a8b9a7`、`735822a`
