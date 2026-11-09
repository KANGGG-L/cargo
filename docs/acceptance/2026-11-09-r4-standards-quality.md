# Release 4 验收记录 — 标准与数据质量(Stage Gate ④)

> 日期:2026-11-09 | 对应计划:`docs/NETWORK_UPGRADE_PLAN.md` §6.2(R4-1…R4-5)
> 结论:**数据+API 层 PASS**;GUI 浏览器点击级 UAT 顺延(同前)

## 1. 交付内容

| # | 项 | 文件 | 说明 |
|---|---|---|---|
| R4-1 | 标准里程碑/报文契约 | `app/ingest/standards.py`、`fsu.py`、`docs/MILESTONE_MAPPING.md` | 6 内部码 ↔ Cargo iQ / ONE Record / CIMP 别名;FSU 解析接受 FOH/RCF/MAN 等别名并解析为内部码;仅用公开部分,不宣称 DCSA v3 合规 |
| R4-2 | 订阅与回调契约 | `app/models.py`、`notifications/outbox.py` | `dim_subscriptions` 加 `event_types`/`secret`;`notification_outbox` 加 `dedupe_key`(唯一,幂等)/`signature`(HMAC)/`attempt_count`/`next_retry_ts`/`last_error`;事件类型过滤 + 指数退避 + `X-Subscription-Id`/`X-Notification-Signature` 头 |
| R4-3 | 单证与配载合规 | `scripts/generate_data.py` | 每 AIR 班次 DG 数量上限 2;超额 roll 为 `roll_reason='DG_LIMIT'`(实测 40 条);e-AWB 状态机既有 |
| R4-4 | 数据质量 SLA 看板 | `app/events/projector.py`、`routers/network.py` | `v_data_quality`(覆盖率/迟到率/拒绝率)+ `v_source_trust`;`GET /api/network/data-quality`;每项可被 SQL 独立复算 |
| R4-5 | 闭环自证拆解 | `app/agent/extra_tools.py`(既有结构)+ 测试 | 诊断**检测**仅用观测层(KPI/legs/shipments 的 baseline-vs-recent),**不读** world 层注入答案键 `fact_disruption_events.target_metric_impact`;归因另行引用扰动事件的公开字段 |

## 2. 验证证据

- `pytest tests/` = **123 passed**(P2 的 113 + 10 R4)
- R4-1 别名:FOH→RCS / RCF→ARR / MAN→DEP 实测解析正确;未知码仍拒绝
- R4-2:HMAC 签名稳定可复算(64 hex);outbox/subscription 契约列齐备;`dedupe_key` 唯一约束保证幂等重入
- R4-3:DG/AIR 单班上限实测 ≤2;DG_LIMIT 滚动 40 条;I1 容量守恒仍 0 越界;共享班次 4,081
- R4-4:`v_data_quality` 覆盖率 96.7% = 独立复算 `100*covered/planned`;`/api/network/data-quality` 返回同值
- R4-5:检测 SQL(AIR/SEA/TRUCK/COMMERCIAL)静态断言不含 `target_metric_impact` 与 `fact_disruption_events`;诊断仍能从观测发现 Yantian 异常

## 3. 设计取舍(诚实声明)

- **R4-5 的务实边界**:计划 D10 设想"把生成器拆成 world/observation 两层并改工具读权限"。本 repo 的诊断**检测**本就只读观测层,故 R4-5 落为:① 明确 `fact_disruption_events.target_metric_impact` 为 world-only 答案键;② 用测试锁死"检测 SQL 不读答案键";③ 归因仅引用扰动事件的公开描述字段。没有为此重写生成器(R1 风险),闭环自证的核心主张(检测不依赖注入答案)已被测试保证。若后续要更彻底的物理分层(独立 observation 表 + 行级权限),建议在 R5-6 迁移基线后进行。
- **R4-2 未接真实 SMTP/外部 webhook 回调验证**:签名/退避/幂等为契约级实现,实际投递仍走既有 urllib POST(断网留队重试),符合非目标"不接真实 SMTP"。
- **GUI UAT**:同前,API+SQL+构建兜底。

## 4. 下一步(Release 5)
R5-1 语义层 eval harness、R5-2 Agent 写操作审计 + confirmation_token、R5-3 身份审计、R5-4 可观测 SLO、R5-5 OpenAPI 契约、R5-6 迁移基线。
