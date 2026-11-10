# 面试演示剧本 v3(operator-centric:按一次值班的生命周期演示)

> **讲法升级**:v2 是"按模块导览"(第 1 站总览、第 2 站地图……),让面试官看到"你做了哪些页面"。
> v3 按**一次台风值班的生命周期**串起来——侦测 → 分诊 → 诊断 → **恢复** → 通知 → **升级**,
> 让面试官看到"你懂控制塔怎么运转"。下面 v3 剧本在前,v2 模块导览保留在后作为备查。

前置:面试前一天跑 `scripts/rebuild_demo.sh`;`backend` 起 uvicorn(8000),`frontend` 起 `pnpm start`(3000)。

## v3 台风值班生命周期(8 分钟)

控制塔的唯一 KPI 是"红灯亮起到客户收到改期通知的响应时间"。整条链路一次演完:

1. **接班 / 侦测(`/alerts`)** — 运营时钟在你"睡觉时"推进(`POST /api/ops/clock/start`),规则引擎(R1-R4)已把看板点红。不是"我点 Run scan",而是"我接班,看板已经红了"。
   - 自验:`curl -s localhost:8000/api/alerts/summary`
2. **分诊(`/alerts`)** — 升级/超时的告警带红色左边框 + `L{n} ESCALATED` 徽标**自动置顶**;点 **Cluster** 把一整班航班的滞留货聚成 1 个 SERVICE 父单。讲点:exception-first——"我不逐票看,先看最致命的那班航班"。
3. **诊断(`/agent`)** — `Why did air OTP collapse in September 2025?` → `diagnose_anomaly` 把 OTP 塌陷归因到 `TYPHOON_2025_09`。讲点:AI 是分诊助手。
4. **决策反事实(`/agent`)** — `What should I do about SHP-2025-000001?` → `recovery_tradeoff` 给"不改配 vs 改配"的成本/时效对照卡 + 推荐。讲点:控制塔不只告诉你出事,还**量化每个恢复动作的代价**。
5. **恢复(`/network`,核心高光)** — 选中那票货,点 **Recover** → 列出可行改配航班 → **Re-accommodate**:一次动作完成「改配写库(allocation ROLLED→REACCOMMODATED)+ 容量守恒 + 关联告警自动 RESOLVED + 发通知」。讲点:这是"能查更能做"的执行闭环,不是停在看板。
   - 自验:改配后回 `/alerts`,该票告警已 RESOLVED;`/network` capacity 页 rolled-by-reason +1。
6. **通知(`/alerts` 发件箱)** — 订阅者按 AWB 收到主动改期推送(PENDING → Dispatch → SENT)。讲点:台风下主动推送,而不是等客户 WISMO 来问。
7. **升级(`/alerts`)** — 继续推进运营时钟,未处理且过 `due_ts` 的告警自动 `escalation_level++` 并标红置顶。讲点:SLA 超时自动升级,呼应行业的升级矩阵。

**一句收束**:"从红灯亮起,到改配落地、客户收到改期通知——我演示的是这条链路的响应时间,这是控制塔唯一真正的 KPI。"

---

# 面试演示剧本 v2(8 分钟,模块导览,备查)


前置:面试前一天跑 `scripts/rebuild_demo.sh`(重建演示库到初态,seed=42 字节级可复现);`backend` 起 uvicorn(8000),`frontend` 起 `pnpm start`(3000)。

> 本文出现的具体数值(794 张 OPEN、OTP 百分比等)在 seed=42 下可复现,但随运营时钟/演示操作会自然漂移——**讲解时以屏上实时数字为准**,每站附自验命令。

## 开场(30 秒)

> "这是一个面向 Sea-Air-Land 多式联运的货运控制塔:货从盐田驳船进港、香港转运、远洋空运、末端卡车派送。BI 看全局,地图看轨迹,告警工作台驱动处置,AI 分析师负责查数、诊断、模拟、报价。数据是按行业基准校准的合成数据,埋了四个真实风格的事故——空、陆、海、商业各一个。"

## 第 1 站:控制塔总览(`/`)

- 三模态 KPI 并列:Air OTP 85.8 / Sea OTP 86.2 / Truck OTP 81.6 / E2E 79.3%
- 图表:台风阴影(2025-09)、深圳湾口岸阴影(2025-11)、盐田走廊阴影(2026-03)、月度毛利 2026-06 塌陷
- 叙事点:三模态对等——这不是空运仪表盘

## 第 2 站:链路 + 地图(`/network`)

- 选一票 SEA_AIR_TRUCK 货:双轨里程碑条(计划 vs 实际 vs NOT REPORTED)
- 逐段 trace(机/船/车牌号、成本、延误)
- **Route Map**:三段航迹按模态着色,大圆线跨欧亚
- 点 Subscribe(POST /api/notifications/subscriptions,字段 `email`):输入邮箱订阅该票的里程碑与延误告警
- 底部桑基:全网物流量汇聚 HKG 枢纽

## 第 3 站:告警工作台(`/alerts`)

- OPEN 告警(R1 漏交付 / R2 漏到达 / R3 起飞延误 / R4 到达延误;数量以 `curl -s localhost:8000/api/alerts/summary` 实时为准)
- 点 **Run rule scan**:幂等重扫(0 新增,证明不重复)
- 任选一张 Acknowledge → Resolve:状态流转留痕
- 下方发件箱:订阅产生的通知(PENDING → Dispatch → SENT)

## 第 4 站:数据接入(`/ingest`)

- Load dirty sample:含重复/乱序/未知代码/未知货件
- Ingest:parsed 5 / ingested 0(全判重,幂等)——讲解 dedupe 与乱序策略
- 现场补录:重放样例 → 若该缺失事件已在上次演示中补录,则 ingested 0(幂等即卖点);需重演高光就先跑 `scripts/rebuild_demo.sh` → ingested 1 → **对应缺失告警自动 RESOLVED**(回 /alerts 验证)

## 第 5 站:AI 分析师(`/agent`)

1. `Why did truck OTP drop in November 2025?` → diagnose(truck, anchor 11-24)→ SZBP 84.7→60.8,匹配 EVT-2025-002
2. `Show the HKG-ORD monthly gross margin in 2026` → 展开 SQL 工具卡,讲语义层 + 防火墙(可现场试 `DELETE` 被拒)
3. `Simulate a 48h typhoon closure of HKG` → 确定性模拟:28 legs / $0.3M / 2 天恢复曲线
4. 诊断后让 Agent **raise_alert**(mock 剧本第二拍自动触发):回到 /alerts 看到新工单(source: agent)——分析闭环到执行

## 收尾(30 秒)

- `Quote 500kg from CNYTN to LAX sea-air`:海+空链报价 $2350,标准运价语义
- 一句话收束:里程碑语言(Cargo iQ)、事件接入(FSU)、异常闭环、三模态对等——控制塔该有的骨架都在

## 备用问答(应对深挖)

- **数据哪来的?** 运营明细合成(seed=42 字节级可复现,KPI 按 HKAA/SCFI 公开基准校准);宏观表带官方来源
- **真实系统怎么接?** 接入层契约已就位:换掉模拟器接 ADS-B/AIS/承运人 EDI,FSU 解析器即生产入口
- **为什么手写 Agent 循环?** 事件流可控、每步可讲;与简历 LangChain 项目互补
- **生产化缺什么?** 见 docs/UPGRADE_ROADMAP.md v1.0(预测 ETA、多租户、CI)
