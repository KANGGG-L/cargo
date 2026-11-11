# P2 验收记录 — 网络级产品能力(Release 3 / Stage Gate ③)

> 日期:2026-11-09 | 阶段目标:Release 3 (P2) 网络级产品能力 (服务感知 ETA、告警班次聚类与 SLA、网络态势页与 Agent 决策工具)
> 结论:**数据+引擎+API+前端构建 PASS**;GUI 浏览器点击级 UAT **顺延**(同 P0/P1)

## 1. 交付内容

| 项 | 文件 | 说明 |
|---|---|---|
| ETA 指向班次 | `backend/app/tracking/eta.py`、`routers/orders.py` | `fact_planned_legs.service_id` 落列;`build_planned_legs(conn)` 绑定最早可行班次;分位数分组加 `service_no+lane+month` 层;输出 `expected_service_no` + `missed_cutoff_risk` |
| 告警聚类 + SLA | `backend/app/milestones/rules.py`、`routers/alerts.py` | `cluster_by_service()` 建 SERVICE 父单 + 子单 `parent_alert_id`;`fact_alerts` 加 `alert_scope/parent_alert_id/due_ts/escalation_level`;`?group_by=service`、`/cluster`、`/{id}/bulk-transition` |
| Agent 4 工具 | `backend/app/agent/extra_tools.py`、`tools.py` | `network_load` / `capacity_impact` / `reroute_options` / `manifest_lookup`(6→10 工具) |
| 语义层 | `backend/app/semantic_layer.py` | 3 张网络表进 TABLE_CATALOG;F1–F3 网络级 verified few-shot |
| mock 剧本 v3 | `backend/app/llm/mock.py` | `network_capacity` 剧本(capacity_impact,台风按优先级清关) |
| 前端态势页 | `frontend/src/app/network/capacity/page.tsx`、`lib/api.ts` | 容量水位、取消天数、峰值负载、rolled 原因、最满班次表 |
| 测试 | `tests/test_network_p2.py`(9) | §5.3.6 矩阵 |

## 2. 验证证据

- `pytest tests/` = **113 passed**(P1 的 104 + 9 P2)
- Agent 工具数 = 10(4 新工具注册并可调用,实测 summary 正常)
- 新表全部在 `ALLOWED_TABLES`(只读);customer 角色对 `/api/network/*` → 403(ops-only)
- **告警聚类 API⇔SQL 交叉核对**:cluster 建 100 父单 / 链 250 子单;`?group_by=service` 返回父单 child_count 与 `SELECT COUNT(*) WHERE parent_alert_id=?` **完全一致**(5==5)
- **ETA 服务感知**:新建订单 BOOKED 后 air planned leg 带 `service_id`;`/eta` 返回 `expected_service_no` + `missed_cutoff_risk`
- `pnpm build` 通过,新增 `/network/capacity` 路由静态产出
- `rebuild_demo.sh` 复演:794 告警、service-scope=0(聚类是演示时的显式动作,pristine 不预置)

## 3. 设计取舍(诚实声明)

- **ETA 班次绑定的 horizon 回退**:演示新建订单的 `booking_ts = 真实 now()`,其空运腿计划出发落在班次表 horizon(2026-10-31)之后。为让 ETA 仍能指向一个具体班次,`_find_service` 在"之后无班次"时回退到该 lane 最近一班作为**代表模板**(basis 标注 "template (past schedule horizon)"),不把计划时刻改到过去。历史货件走正常的"最早可行班次"路径。此为务实取舍,不影响历史数据的真实性。
- **桑基"需求 vs 舱位"双色流**:§5.3.3 提到的桑基升级本次未做(现有桑基保留);态势页以容量水位表 + rolled 原因分布覆盖了"竞争/积压"叙事。列为后续增量。
- **GUI 浏览器点击级 UAT**:环境无浏览器控制,API+SQL+构建兜底,不计入 PASS。

## 4. Release 1–3(P0–P2)累计
- 新增实体表 4(services/ulds/allocations/event_log)+ 2 只读视图;现有表加列 2 处(planned_legs.service_id、alerts 聚类/SLA)
- Agent 6→10 工具;测试 78→113;双引擎 A/B;事件日志 + 投影
- 下一步:Release 4(标准与数据质量)+ Release 5(治理与工程基线)
