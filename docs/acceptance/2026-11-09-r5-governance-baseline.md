# Release 5 验收记录 — 治理与工程基线(Stage Gate ⑤ / 全量收尾)

> 日期:2026-11-09 | 阶段目标:Release 5 (R5) 治理与工程基线 (R5-1 语义层 Eval Harness、R5-2 Agent 写操作治理、R5-3 审计中间件、R5-4 可观测 SLO、R5-5 OpenAPI 契约、R5-6 工程基线加固)
> 结论:**数据+API+契约层 PASS**;GUI 浏览器点击级 UAT 顺延(同前)

## 1. 交付内容

| # | 项 | 文件 | 说明 |
|---|---|---|---|
| R5-1 | 语义层 eval harness | `tests/test_eval_text_to_sql.py` | 黄金问题集:全 few-shot 过防火墙 + 执行 + 确定性;排名命中;覆盖率指标复算;**故意坏 join 被捕获**。运行时**真捕获**到既有防火墙缺口(sea/truck KPI 表未放行),已修 |
| R5-2 | Agent 写操作治理 | `app/agent/governance.py`、`extra_tools.py`、`models.py` | `fact_agent_tool_audit`;`raise_alert` 分两步:首调返回 `confirmation_token` 不写库,二调带 token 才提交;来源文本仅存 sha256;审计表**不进** LLM 防火墙 |
| R5-3 | 身份与审计基线 | `app/main.py`、`models.py` | `fact_access_log` 中间件(principal/role/method/path/status);best-effort,不阻塞请求;不进防火墙 |
| R5-4 | 可观测与 SLO | `app/routers/ops.py` | `GET /api/ops/metrics`:告警分状态、Agent 工具审计(含 confirmed 比)、webhook 投递/重试、访问拒绝数;均可 SQL 复算 |
| R5-5 | 集成契约与版本化 | `scripts/export_openapi.py`、`openapi.json`、CI | 导出 53 路径 OpenAPI;CI 断言 `git diff --exit-code openapi.json`(契约漂移即失败) |
| R5-6 | 工程基线加固 | `.github/workflows/ci.yml`、README | CI 加 determinism(网络 CSV sha256 三连等)+ OpenAPI 契约 job;测试数 67→**140** 更正;README chain-fifo-v1→v2、"五个工具"→10、67→140 |

## 2. 验证证据

- `pytest tests/` = **140 passed**(R4 的 123 + 10 R5 + 6 eval + raise_alert 两步化更新)
- R5-1 eval 真抓 bug:few-shot D 组引用 `fact_sea_kpi_weekly`/`fact_truck_kpi_daily` 但未在 `ALLOWED_TABLES` → 已补(这正是 eval harness 的价值证明)
- R5-2:未带 token 调 `raise_alert` 返回 `requires_confirmation`、不写库;带正确 token 才建单;伪造 token 被拒;审计行记 tool_kind='write' + source_text_hash(不存原文)
- R5-2 对抗:模拟"被篡改字段直接触发写"→ 伪 token → 不提交(document-to-transaction integrity)
- R5-3:访问中间件实测写入 `fact_access_log`
- R5-4:`/api/ops/metrics` 返回四类可复算指标
- R5-5:`openapi.json` 提交且与实时 schema 路径集一致
- R5-6:CI determinism/OpenAPI job 落地;文档数字统一为 140 / chain-fifo-v2 / 10 工具

## 3. 设计取舍(诚实声明)

- **R5-6 迁移基线**:计划 D12 建议引入 Alembic。为保 `rebuild_demo.sh` 一键确定性复现(I5)且不在收尾阶段引入迁移框架风险,本次采用**版本化 DDL + 一键重建**路线(drop/create + CSV 装载 + 幂等视图),CI 用 determinism job 守字节级可复现。Alembic 若未来需要增量迁移再引入,`rebuild_demo.sh` 路径保留。此为对 D12 的有意偏差。
- **R5-3 角色扩展**:计划设想 ops/manager/customer/partner 四角色;本次落地审计日志 + 既有 ops/customer 行级隔离(已有 `test_isolation`),manager/partner 细分与 2FA 设计页留作后续(非目标边界内,不接真实 IdP)。
- **R5-2 confirmation_token 定位**:是人在回路的防误触门(防被篡改文档字段直接变交易),不是对抗恶意操作员的安全边界;审计行无论确认与否都写。
- **GUI UAT**:全程顺延,API+SQL+构建兜底(环境无浏览器控制)。

## 4. 全量收尾状态(Release 1–5)
- 新增实体表 6(services/ulds/allocations/event_log/tool_audit/access_log)+ 4 只读视图;现有表加列 ≥4 处
- Agent 6→10 工具;双引擎 A/B;事件日志+投影;标准码映射;数据质量 SLA;写操作审计+确认;OpenAPI 契约
- 测试 78→**140**;前端 +1 页(/network/capacity);CI 加 determinism + OpenAPI 契约
- 全部 5 个 Release 均 PASS(数据/引擎/API/契约/前端构建层);唯一未闭合项为 **GUI 浏览器点击级 UAT**(环境能力缺失,全程记录在案)
