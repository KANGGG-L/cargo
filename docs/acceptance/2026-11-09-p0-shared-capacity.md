# P0 验收记录 — 共享运力数据地基(Release 1 / Stage Gate ①)

> 日期:2026-11-09 | 执行:自动化实施(交接 goal:一次做完全量 + 每 Release 阶段验收)
> 对应计划:`docs/NETWORK_UPGRADE_PLAN.md` §5.1、§7.2、§10.4
> 结论:**数据层 + API 层 PASS**;GUI 浏览器 UAT **顺延**(见 §4,环境无浏览器控制能力)

## 1. 交付内容

| 项 | 文件 | 说明 |
|---|---|---|
| 3 张实体表 | `backend/app/models.py` | `dim_transport_services` / `dim_ulds` / `fact_allocations` |
| 生成器 3 个纯函数 | `backend/scripts/generate_data.py` | `generate_transport_services` / `generate_ulds` / `assign_allocations`,**独立 `Random(42)` 实例**(R1) |
| CSV 装载 | `backend/scripts/init_db.py` | 新 3 张表按 FK 顺序追加 |
| 5 个 API(4 新 + 1 扩展) | `backend/app/routers/network.py`、`shipments.py` | services / detail / manifest / capacity + trace 扩展(service_id/co_loaded) |
| SQL 白名单 | `backend/app/agent/safety.py` | 3 张表加入 `ALLOWED_TABLES`(只读) |
| 测试 | `tests/test_network_p0.py`(10)、`tests/test_network_api.py`(6) | 不变量 + API⇔SQL 交叉核对 |

## 2. 数据实测(2026-11-09 重建后)

- services 8,784 / ULDs 15,440 / allocations 13,869
- 共享班次(>1 票)**4,071**(目标 ≥1,000)✓
- I1 容量守恒越界 **0** ✓;I2 单 leg 多活跃配载 **0** ✓;I3 CONFIRMED 超截关 **0** ✓
- 台风事件滚动票数 **61**(目标:一次事件 ≥20)✓
- 优先级类齐全:PHARMA / GENERAL / HIGH_VALUE / DG ✓
- 确定性:两次生成 4 个网络 CSV **sha256 全同**(I4)✓
- 兼容:`dim_shipments` / `fact_milestone_events` / `fact_air_kpi_daily` **字节级未变**(R1 证据);78 项既有测试全绿(I5)✓

## 3. 验证证据

- `pytest tests/` = **94 passed**(78 基线 + 10 P0 不变量 + 6 P0 API)
- 防火墙:新表 SELECT 放行,INSERT/UPDATE/DELETE 全拒(R6)
- 鉴权(AUTH_ENABLED=True 实测):无 cookie → 401;ops → 200;customer → 403(ops-only)——满足 §7.1
- `scripts/rebuild_demo.sh` 复演:794 告警,与 P0 前一致(演示链路未回归)

## 4. 已记录的偏差(诚实声明)

### D2 密度修正(对计划的实质调整)
计划 §5.1 / D2=B 设"每 lane 每天 3 班 **且** 单班 8–15 票"。实测这两者**算术上不自洽**:真实需求仅 ~1.5 AIR legs/lane/天(7,980 票 / 549 天 / 7 lane),3 班/天会把单班均载压到 1.4,**消灭竞争**。故改为**每 lane 每天 1 班日班货机**并下调舱位,使平日 55–80% 满载、台风窗口整块取消。

- 代价:单班均载 ~2.1 票,**达不到 8–15**;单架航班也**装不下 20 票**。
- "一次取消 ≥20 票同损"按**扰动事件级**判定(台风一次取消 49 班、滚动 61 票),这是 "一次台风取消" 的运营语义,而非单班 20 票。`test_typhoon_cascade` 据此断言;§4.6 的"同班次 ≥20"在本数据密度下不可达,不伪造。
- 该偏差已在 `test_network_p0.py` 头部与本记录显式标注;建议计划 §4.6 / D2 据此更正口径。

### GUI 浏览器 UAT 顺延
交接 goal 要求每 Release **操纵内置浏览器做 UAT**。本会话环境**无浏览器控制能力**(无 power、无浏览器工具;`uvicorn` 后台进程被沙箱拦截)。按工作区记忆既定规则("未启用时 HTTP 断言只能临时兜底,不得冒充 UAT"):

- 已用 **FastAPI TestClient 在进程内**跑通真实路由 + DB + 鉴权,并把端点输出与直查 SQL 交叉核对(等价于 API⇔SQL 门)。
- **未**执行真实点击/输入级 GUI 走查 → 该子项标记为**顺延**,不计入 PASS。
- 待用户开启 Settings → Agent → Browser control(+扩展)后补做;或我在其可用时一次性补齐。

## 5. 待办(进入 P1 前)
- P1 将新增 `fact_event_log` + `v_capacity_state` + DES 引擎;表结构再变前考虑 R5-6 迁移基线。
- 文档数字漂移(README 67/73、chain-fifo-v1、"五个工具")留待横切批统一更正。
