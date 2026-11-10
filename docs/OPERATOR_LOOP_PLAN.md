# 全面推进计划:从"分析后视镜"到"运营方向盘"

> 目标:把控制塔补成一个完整的 **侦测 → 分诊 → 诊断 → 恢复 → 通知 → 升级** 闭环,
> 并把演示从"模块导览"改成"一次台风值班的生命周期"。
> 本计划落到文件/函数级别,逐项带验收标准。状态:🔲 待办 / ✅ 完成。
> **全部 Release(A–D)已实现并验证**:后端 161 测试全绿、前端 `pnpm lint && pnpm build` 零问题、`openapi.json` 契约同步(55 paths)。下方子项勾选已与实现同步。

## 现状盘点(已核验的集成点)

| 能力 | 现状 | 关键代码 |
|---|---|---|
| 告警状态流转 | ✅ 有 `transition` / `bulk-transition`,合法流转表 | `routers/alerts.py` `VALID_TRANSITIONS`、`transition_alert` |
| 自动销警(进站补录) | ✅ 有,可复用其 resolve 路径 | `ingest/fsu.py` `_auto_resolve_missing` |
| 通知 outbox | ✅ 事务性 enqueue + dispatch(含 webhook 重试) | `notifications/outbox.py` `enqueue_for_alerts` / `dispatch_pending` |
| 运营时钟 | ✅ tick 发射里程碑 + 跑规则 + 扇出通知 | `ops/clock.py` `tick`;`routers/ops.py` `/clock/tick` |
| 改航选项 | ⚠️ **只读** 查询,不能落地 | `agent/extra_tools.py` `tool_reroute_options` |
| 改配写库 | ❌ **运行时无任何代码写 `fact_allocations`** | — |
| 升级(due_ts/escalation_level) | ❌ 有字段(`routers/alerts.py` 查询里读到),**但无代码推进** | — |

**两个断点**:(1) reroute "能查不能做";(2) 升级字段"有数据无逻辑"。本计划补齐。

---

## Release A — 恢复闭环(P0,核心卖点)

目标:操作员选一个改航方案 → 真正改签 allocation(写库)→ 关联告警自动 RESOLVED → 发通知,全链路一次完成且幂等、可审计。

### A1 ✅ 后端:allocation 改签领域函数
- 新建 `backend/app/recovery/__init__.py` 与 `backend/app/recovery/reaccommodate.py`
- 函数 `reaccommodate(shipment_id, to_service_id, reason, actor) -> dict`:
  1. 读该货 AIR leg 当前 allocation(复用 `tool_reroute_options` 的 leg 查询)
  2. 容量校验:目标 service `allocated_kg + weight <= capacity_chargeable_kg`,否则 `RecoveryError(code='no_fit')` → 409
  3. **原地改签**(实现决策,优于计划原稿):直接把该 allocation 行的 `service_id` 改到目标、`allocation_status='REACCOMMODATED'`、记 `rolled_from_service_id`/`roll_reason`/`decided_ts`——保持 PK 稳定并尊重 `(leg_id, service_id)` 唯一索引;同时在 `dim_transport_services` 上旧 service 释放、新 service 占用,**容量守恒**
  4. 回填 `fact_shipment_legs.voyage_flight_no`、`planned_depart_ts`/`planned_arrive_ts` 为新 service 时刻(保持 leg 与 allocation 一致——呼应 commit `a92a27b` 的 resync 约束)
  5. 调 `_resolve_alerts`:把该货 OPEN/ACK 告警置 `RESOLVED`,`resolution_note='reaccommodated <from>-><to> (<reason>) by <actor>'`(复用 `_auto_resolve_missing` 同款 UPDATE)
  6. enqueue 通知:`_enqueue_recovery_notice` 构造 alert-like dict 调 `enqueue_for_alerts`(outbox dedupe 保幂等)
  7. 审计:`governance.audit_tool_call(tool_kind='recovery')`
  - **幂等**:已在目标 service 则返回 `no_op=True`,无二次改签、无重复通知
- **不变量**:容量守恒(测试断言 `SUM(allocated_kg)` 不变)、配载唯一(改签后 leg 仍只在一条 allocation)

### A2 ✅ 后端:REST 端点
- `backend/app/routers/network.py` 新增 `POST /api/network/reaccommodate`
  - body:`{shipment_id, to_service_id, reason}`;`require_write`
  - 成功 200 返回 `{rolled_from, rolled_to, resolved_alerts, notifications_enqueued}`
  - 容量不足 409、无 AIR leg 404
- `scripts/export_openapi.py` 重新导出(CI 有契约校验)

### A3 ✅ 前端:reroute 面板可下单
- `frontend/src/lib/api.ts` 新增 `rerouteOptions(id)` + `reaccommodate(shipmentId, toServiceId, reason)`(POST 模式照抄 `transitionAlert`)
- `frontend/src/app/network/page.tsx`(或告警详情抽屉):trace 面板里当某票有 OPEN 告警/脱班时,显示 "Recovery options" 列表(来自 reroute_options),每行一个 **Re-accommodate** 按钮 → 调 A2 → 成功后刷新 trace + 告警
- 复用 `ToolActivityCard` 风格呈现结果

### A4 ✅ 测试
- `backend/tests/test_recovery.py`:
  - 改签成功:旧 allocation ROLLED、新 CONFIRMED、告警 RESOLVED、outbox +1、audit +1
  - 容量不足 → 409 且无写入(事务回滚)
  - 幂等:二次调用 no-op
  - 不变量:改签后容量守恒、配载唯一仍成立
- `backend/tests/test_network_api.py` 补端点契约

---

## Release B — 自动升级(P1)

目标:`due_ts` 过期的 OPEN 告警自动 `escalation_level++` 并标红置顶,由运营时钟驱动,呼应 SLA/升级矩阵。

### B1 ✅ 后端:升级引擎
- `backend/app/milestones/rules.py` 新增 `escalate(conn, now) -> dict`:
  - 对 `status IN ('OPEN','ACKNOWLEDGED')` 且 `due_ts < now` 且 `escalation_level < 3` 的告警:`escalation_level += 1`、`updated_ts=now`、把下一个 `due_ts` 按 `SLA_HOURS` 顺延
  - 升级到 L2/L3 时追加一条升级通知(enqueue)
  - 幂等:同一 due 窗口内不重复升级(用 due_ts 顺延保证)
- 给新建的 `rules.sync`/alert 写入补 `due_ts`:创建告警时按 `SLA_HOURS[severity]` 设初始 `due_ts`(当前只有 cluster 父单设了 due_ts)

### B2 ✅ 接入时钟
- `ops/clock.py` `tick()`:在 `sync` 之后追加 `escalate(rw, now_s)`(用 sim_now 作为"现在")
- `routers/ops.py` `/clock/tick` 的返回体加 `escalated` 计数

### B3 ✅ 前端:升级可视化
- `frontend/src/app/alerts/page.tsx`:
  - `escalation_level >= 1` 的行加红色左边框 + "L{n} ESCALATED" 徽标
  - 按 `escalation_level DESC, due_ts ASC` 排序置顶
  - 显示 "due in / overdue by" 相对时间(基于 `due_ts`)
- 列表接口已返回 `due_ts`/`escalation_level`,前端只需消费

### B4 ✅ 测试
- `backend/tests/test_escalation.py`:
  - due 过期 → L1;再过 → L2;L3 封顶
  - 升级产生通知
  - 幂等:同窗口重复 tick 不重复升级
  - RESOLVED 的不再升级

---

## Release C — 决策反事实(P1,差异化)

目标:把已有 `simulate_disruption` 的 fifo/des 用于"改配 vs 不改配"的成本/时效对比卡。

### C1 ✅ 后端:对比工具
- `agent/extra_tools.py` 新增 `tool_recovery_tradeoff(shipment_id | service_id)`:
  - 方案 A(不改配):当前 ETA 带 + SLA 违约数 + 预估赔付(复用 `predict_eta` 分位数)
  - 方案 B(改配到 reroute 首选):改配后 ETA 带 + 成本增量(service 间费率差)
  - 返回两方案对照表,`llm_digest` 给结论
- 注册进 `tools.get_tool_specs()` 与 `openai_tool_schemas`
- mock 剧本 `llm/mock.py` 加一拍:诊断后触发 tradeoff

### C2 ✅ 前端:决策卡
- Agent 页 `ToolActivityCard` 支持渲染两列对照表(成本 vs 时效)

### C3 ✅ 测试
- 实际落在 `backend/tests/test_extra_tools.py`(而非独立文件):两方案字段齐全、确定性(同输入同输出)、未知货件回 error、工具注册表计数(11 个工具,含 recovery_tradeoff)

---

## Release D — 运营员叙事 & 文档(P0,零/低代码)

### D1 ✅ 重写演示剧本
- `docs/DEMO_SCRIPT.md` 增补 v3「台风值班生命周期」:接班(红灯已亮)→ 分诊(SLA 排序 + 聚类)→ 诊断(Agent)→ **决策反事实(recovery_tradeoff)** → **恢复(改配下单)** → 通知(主动推送)→ **升级(到点标红)**,每站附自验 curl;v2 模块导览保留备查

### D2 ✅ README 定位 + 闭环图
- `README.md` 工程亮点区加 "operator-centric:按值班生命周期演示,不按模块",并加一张**运营员闭环 ASCII 图**(侦测→分诊→诊断→决策→恢复→通知→升级,运营时钟 tick 驱动)

### D3 ✅ 闭环文档
- 本文件保持为权威推进计划,完成项已打 ✅,并与实现对齐(A1 原地改签、C3 测试归属)

---

## 执行顺序与验收总表(全部 ✅ 完成)

| 顺序 | Release | 关键产出 | 状态 |
|---|---|---|---|
| 1 | A1–A4 | 改配写库闭环(`app/recovery/reaccommodate.py`、`POST /api/network/reaccommodate`、前端 Recover 面板、6 测试) | ✅ |
| 2 | B1–B4 | 自动升级(`rules.escalate` + 时钟接入 + 前端标红置顶、6 测试) | ✅ |
| 3 | C1–C3 | 反事实决策卡(`recovery_tradeoff` 工具 + mock 剧本 + ToolActivityCard 对照卡、4 测试) | ✅ |
| 4 | D1–D3 | 运营员叙事(DEMO_SCRIPT v3 + README operator-centric) | ✅ |

**最终状态**:后端 161 测试全绿;前端 `pnpm lint && pnpm build` 零问题;`openapi.json` 契约同步(55 paths)。
