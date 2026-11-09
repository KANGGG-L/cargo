# P1 验收记录 — 离散事件引擎 + 事件日志(Release 2 / Stage Gate ②)

> 日期:2026-11-09 | 对应计划:`docs/NETWORK_UPGRADE_PLAN.md` §5.2、§7.2
> 结论:**数据+引擎+API 层 PASS**;GUI 浏览器 UAT **顺延**(环境无浏览器能力,同 P0)

## 1. 交付内容

| 项 | 文件 | 说明 |
|---|---|---|
| DES 引擎 | `backend/app/simulation/des_engine.py` | SimPy `PriorityResource` 枢纽产能恢复模型;优先级仲裁 + 非匀速 ramp |
| 双引擎 A/B | `backend/app/agent/extra_tools.py` | `engine=fifo\|des\|both`;`fifo` 为默认(保 mock/demo 契约),`both` 并排对比 |
| 事件日志表 | `backend/app/models.py` | `fact_event_log`(append-only,`dedupe_key` 唯一) |
| 适配器 | `backend/app/events/adapters.py` | 里程碑/容量变更 → ONE Record 风格事件;幂等 append |
| 投影器 + 视图 | `backend/app/events/projector.py` | `project_milestones`(幂等)+ `v_capacity_state` 只读视图 |
| 时钟降级 | `backend/app/ops/clock.py` | `tick()` 额外把事件镜像进 `fact_event_log`(附加式,不改既有里程碑契约,守 R2) |
| 依赖 | `requirements.txt` | `simpy>=4.1`(纯 Python,无编译,守 R3) |
| 白名单 | `backend/app/agent/safety.py` | `fact_event_log` + `v_capacity_state` 只读放行 |
| 测试 | `tests/test_network_p1.py`(10) | §5.2.6 矩阵 |

## 2. DES 涌现行为实测(typhoon severity 5)

- **确定性 I4**:同参数两次(含跨进程)结果 JSON 全等 ✓
- **优先级仲裁**:中位等待 PHARMA 2100min < GENERAL 6266min(≥2× 差距)✓;清关日 PHARMA D+3 / GENERAL D+6 ✓
- **非匀速恢复**:每日清出 4→10→13→16(相邻差不全等)✓
- **场景可区分**:三场景首损节点 `AIR@HKG` / `SEA@CNYTN` / `TRUCK@SZX` 互异 ✓
- **双引擎可比**:`engine=both` 同时返回 des-v1 主结果 + `fifo_baseline` + `des_vs_fifo` ✓
- **缺 simpy 回退 R3**:强制 ImportError 时自动回退 chain-fifo ✓

## 3. 事件日志实测

- append 幂等:同 dedupe_key 第二次返回 False、不新增 ✓
- 投影幂等:`project_milestones` 第二次 projected=0 ✓
- 信任级别记录:`unverified` 落库可查 ✓
- 容量代理一致:`v_capacity_state` 的 allocated_kg 合计 == `dim_transport_services` 合计(46,386,622 kg)✓

## 4. 兼容与回归

- `pytest tests/` = **104 passed**(P0 的 94 + 10 P1)
- `fifo` 仍为 simulate 默认 → mock 回放与既有 `test_extra_tools` 的 `chain-fifo-v2` 断言不破
- `rebuild_demo.sh` 复演:794 告警、`v_capacity_state` 1,647 行、event_log 洁净为 0(I5)
- 时钟事件镜像为**附加式**:`fact_milestone_events` 契约与去重键完全不变(R2)

## 5. 设计取舍说明(诚实声明)

- **单源投影的务实实现**:计划 §5.2.5 要求"时钟降级为事件源之一、状态由事件投影"。为守 R2(78+ 测试与演示链路对 `fact_milestone_events` 的硬依赖),采用**附加镜像**而非改写主写路径:时钟仍直写里程碑表(契约不变),同时把同一事件 append 进 `fact_event_log`;投影器提供容量读模型与幂等里程碑投影供测试与未来读侧使用。架构目标(单一事实源 + 投影 + 多源适配 + append-only)已具备,但主写路径的"完全切换到投影"留待有迁移基线(R5-6)后再做,避免破坏演示。此为对 §5.2.5 的有意偏差,已记录。
- **ULD 队列 / SEA·TRUCK 资源细分**:DES 当前对三场景统一用枢纽 build-up `PriorityResource` 建模恢复;泊位/关口的独立服务时间曲线(§5.2.2 的 ×3 服务时间)留到 P2 态势页需要时细化。场景可区分性已由首损节点与规模差异满足。
- **GUI 浏览器 UAT**:同 P0,环境无浏览器控制能力,HTTP/TestClient 兜底,不计入 PASS。

## 6. 下一步(P2)
ETA 指向班次、告警按 service 聚类 + SLA、`/network/capacity` 态势页、Agent 新增 network_load/capacity_impact/reroute/manifest_lookup 工具、演示剧本 v3。
