# 延后项闭合记录 — 桑基双色流 + 四角色/2FA 设计

> 日期:2026-11-09 | 对应计划:`NETWORK_UPGRADE_PLAN.md` §5.3.3、§6.3 R5-3
> 结论:两个此前标注"延后"的子项已完成并验证。计划 §4.2 的**非目标**(真实 ADS-B/AIS、Postgres/Kafka/K8s、ML ETA、真实 SMTP、Gartner 评级)仍按约定**不做**。

## 1. 桑基"需求 vs 舱位"双色流(§5.3.3)

- 后端 `GET /api/shipments/flows/sankey` 从纯 leg 计数升级:每条 lane 现带 `demand_tonnes`(实际配载吨位)、`capacity_tonnes`(共享班次可售舱位)、`headroom_tonnes`、`utilization_pct`;`value` 仍=demand 吨位(向后兼容)。
- 前端 `/network` 桑基:连线按利用率双色(<70% 绿 / 70–90% 琥珀 / ≥90% 玫红),tooltip 显示 需求/舱位/余量/利用率。
- **浏览器核对**:`/network` 桑基 canvas 渲染;浏览器内 fetch 返回 19 条连线、12 条有共享运力支撑,示例 CNYTN→HKG 需求 6904.7t vs 舱位 85644t(8.1%)。
- 回归测试 `test_sankey_demand_vs_capacity`。

## 2. 四角色模型 + 2FA 设计(R5-3)

- 角色:`ops`(读写全网)/`manager`(读写全网)/`partner`(只读全网)/`customer`(行级只读)。
- `backend/app/auth.py`:`ROLE_CAPABILITIES` + `require_write`(ops/manager)+ `require_full_read`(ops/manager/partner)+ `scoped_customer_id`;`require_shipment_access` 按 full_read 放行。
- 写端点(alerts sync/cluster/transition/bulk)改 `require_write`;网络读端点改 `require_full_read`。
- 种子账号:`manager@demo.local` / `partner@demo.local`(密码 demo1234)。
- **实测角色矩阵**(AUTH_ENABLED=True):
  - partner:network-read 200 / alert-write **403**
  - manager:network-read 200 / alert-write 200
  - customer:network-read 403 / alert-write 403
- 2FA:`docs/AUTH_ROLES_2FA.md` 给出 TOTP 登录 step-up + 敏感写操作 step-up(复用 R5-2 confirmation_token)+ 锁定审计的**设计**;按计划范围**不实装**(单文件 SQLite demo 不伪造加密凭证库),差距显式写明。
- 测试:`test_role_capabilities_map` / `test_partner_can_read_but_not_write` / `test_manager_can_write`。

## 验证
- `pytest tests/` = **145 passed**(R5 的 141 + 4 新:3 角色 + 1 桑基)
- `pnpm build` 通过;`openapi.json` 重新导出(新增 `sort` 参数);前后端经 Orca 浏览器复验
- 演示库已复原 pristine(含 4 个角色账号)

## 仍然不做(计划 §4.2 非目标,范围纪律)
真实 ADS-B/AIS/承运人 EDI 接入、Postgres/Kafka/K8s、多租户 SaaS、ML ETA 训练、真实 SMTP、LangGraph 替换、Gartner 式评级。这些是刻意的作品集可复现性取舍,不在本轮范围。
