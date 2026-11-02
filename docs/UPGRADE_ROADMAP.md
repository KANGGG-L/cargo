# 升级路线图 v0.2 → v1.0:对标成熟产品的详细实施方案

> 目标:把当前的"分析型控制塔"升级为对标成熟产品的"运营型控制塔"。每个功能给出:对齐基准(哪个成熟产品的哪个行为)、数据模型变更、API/接口、UI 变更、Agent 集成、验收标准、工作量。与 [PRODUCT_GAP_ANALYSIS.md](PRODUCT_GAP_ANALYSIS.md) 的差距矩阵一一对应。

## 0. 对齐基准总表

| 功能域 | 对标产品 | 对齐的具体行为 |
|---|---|---|
| 里程碑/规则 | IATA Cargo iQ + Terminal49 | 标准里程碑字典(RCS/DEP/ARR/RCF/NFD/DLV + 海陆对照)、计划 vs 实际、缺失/超时规则告警 |
| 异常工作流 | FourKites exception management | 异常单状态流转 open→acknowledged→resolved→closed、负责人、处置记录 |
| 地图追踪 | project44 + 国泰 UltraTrack | 多模态航迹(海 AIS/空 ADS-B/陆 GPS 的模拟替身)、在途货移动动点 |
| 通知订阅 | 国泰 Track & Trace 订阅页 | 按 AWB/阈值订阅里程碑与延误,邮件/webhook 推送 |
| 数据接入 | CARGO-IMP FSU / Cargo-XML / Flexport API | 报文进站解析、事件去重、乱序处理、信任分级 |
| 订单/订舱 | ERPNext Shipment + Flexport quote→book | 状态机 DRAFT→QUOTED→BOOKED→…、订舱生成 AWB 号 |
| 角色门户 | Flexport 门户 + ERPNext 角色 | 运营全网视图 / 客户只读自己货件与文档 |
| 文档合规 | CargoWise ECM + IATA e-AWB | 文档类型表、挂货件、PDF 生成、e-AWB 状态 |
| 结算 | ERPNext 发票 + 海运 demurrage 惯例 | 费用分录(运费+附加费)、应收、对账状态 |

## Release 1 — v0.2「真实性跃升包」(预计 7.5 人日)

### F1 里程碑与计划双轨引擎(P0,2.5d)— 一切的地基

**对齐基准**:Cargo iQ 里程碑体系;Terminal49 的 container milestone 模型(每个里程碑都有 planned/actual/偏差)。

**数据模型(4 张新表)**:
```sql
dim_milestone_codes(code PK, name, mode, seq_group, description)
  -- AIR: RCS(收货) MAN(打板) DEP(离港) ARR(到港) RCF(卸货收妥) NFD(待提) DLV(交付)
  -- SEA: GI(进闸) LOV(装船) DOV(卸船) GO(出闸)
  -- TRUCK: PU(提货) BIN(进境) BOUT(出境) POD(签收)
fact_milestones_plan(id, shipment_id, leg_id, code, planned_ts)          -- 计划刻度
fact_milestone_events(id, shipment_id, code, event_ts, source, dedupe_key UNIQUE)
fact_alert_rules(rule_id PK, code, rule_type missing_after_h|delay_over_min, threshold, severity)
fact_alerts(alert_id PK, shipment_id, rule_id, triggered_ts, status, assignee, resolution_note, closed_ts)
```

**生成器**:由现有 legs 的计划/实际时间推导计划里程碑与实际事件(确定性,seed=42 延续);按 3% 概率漏报某事件(制造"缺失"素材)。

**API**:
- `GET /api/shipments/{id}/milestones` → `{plan:[], actual:[], deviations:[]}`
- `GET /api/alerts?status=&severity=` / `POST /api/alerts` / `POST /api/alerts/{id}/transition {to, note}`
- 规则评估器 `app/milestones/rules.py`:纯函数,`evaluate(shipments) -> [alerts]`,uvicorn 启动时跑一次 + 每小时调度

**UI**:Network 页时间线升级为双轨(上方计划刻度/下方实际事件,偏差红色);新增 `/alerts` 工作台页(筛选、认领、处置、关闭)。

**Agent**:`raise_alert` 第五工具——diagnose 结论一键生成异常单,把"分析"接入"执行"。

**验收**:①植入 5 个漏报事件 → 规则引擎全部命中;②异常单流转留痕;③Agent 从诊断创建异常单;④pytest 覆盖规则引擎边界(阈值边界、重复触发抑制)。

### F2 地图与多模态航迹(P0,2d)

**对齐基准**:project44 多模态视图;国泰 UltraTrack 的"位置感"。

**选型**:Leaflet + OSM 瓦片(零 API key,自托管演示稳)+ `dim_locations(code, name, lat, lon, kind port|airport|checkpoint|metro)`。

**位置模拟器** `app/tracking/simulator.py`:确定性的"伪实时"——按当前时间在 planned→actual 区间内插值:空运大圆航线、海运恒向线、卡车固定路线折线;`GET /api/shipments/{id}/positions?at=<iso>` 返回轨迹点;`GET /api/network/live-positions` 返回全部在途货当前位置(SSE 增量推送可选)。页面明示 "simulated positions"。

**UI**:Network 页新增地图面板(选中货航迹,按模态着色,里程碑事件打点)+ Overview 新增"在途动点"地图(全部 in_transit 货)。

**验收**:①地图上选中任意 SEA_AIR_TRUCK 货可见三段航迹与模态切换点;②live-positions 随时间移动;③坐标字典与现有设施代码全覆盖(有测试)。

### F3 通知与订阅(P1,1.5d)

**对齐基准**:国泰 Track & Trace 的 AWB 订阅(事件 + 延误阈值,邮件推送)。

**数据模型**:`dim_subscriptions(id, subscriber_email, shipment_id|awb_prefix, notify_on csv(milestone,deviation,alert), delay_threshold_min, channel email|webhook)`;`notification_outbox(id, subscription_id, event_type, payload, created_ts, sent_ts, channel_ref)`(outbox 模式,worker 只标 sent,SMTP 可配)。

**触发点**(复用 F1):异常单创建、里程碑偏差超阈、DEP 延误>N min。

**API/UI**:`POST /api/subscriptions`、`GET /api/notifications/outbox`(演示用发件箱视图替代真实 SMTP);Network 页"订阅此货件"对话框。

**验收**:①订阅某货 → 触发偏差 → outbox 出现对应邮件(断言收件人/主题/正文含货件号与偏差);②取消订阅后不再生成;③pytest 覆盖触发条件矩阵。

### F4 FSU/Cargo-XML 报文接入层(mock)(P1,1.5d)

**对齐基准**:CARGO-IMP FSU 状态报文;Flexport webhook 事件流的去重与乱序现实。

**实现**:`POST /api/ingest/fsu` 接收 FSU 报文文本(演示配一个 `data/samples/fsu_replay.txt`:含 3 条重复、2 条乱序、1 条未知代码);解析器 `app/ingest/fsu.py`:按行解析 `(状态码, AWB, 站点, 时间)` → `dedupe_key = sha1(code|awb|station|ts)` 去重 → 乱序按 `event_ts` 落位(非处理顺序)→ 未知代码进 `ingest_rejects`;`ingest_log(id, raw, parsed_count, rejected_count, processed_ts)`。

**UI**:Ingest 演示页(粘贴报文 → 显示解析/去重/拒绝统计)——面试讲"数据从哪来、有多脏"的实物证据。

**验收**:replay 文件处理后:重复被吞、乱序正确落位、未知代码进 rejects;幂等(重放全量文件零新增事件);pytest 覆盖三类脏数据。

**R1 验收彩排**:DEMO_SCRIPT v2 —— 台风周地图上看到货停在 HKG → 告警工作台 5 张单 → Agent 诊断 → 一键生成异常单 → 订阅客户收到 outbox 通知 → FSU 重放补录事件,告警自动解除。

## Release 2 — v0.3「运营闭环包」(预计 6 人日)

### F5 订单状态机与订舱流(P0,2d)
状态机 `DRAFT→QUOTED→BOOKED→IN_PROGRESS→COMPLETED|CANCELLED`( guards:QUOTED 需费率快照;BOOKED 生成 AWB 号 `dim_awb(awb_no, shipment_id, airline_prefix)`);事件表 `shipment_status_history`。API `POST /api/orders/{id}/transition`。UI:订单页(新建→选链型→走 quote 工具→订舱)。Agent:`create_booking` 工具。对齐 ERPNext 状态枚举与 Flexport quote→book。验收:非法迁移被拒(测试矩阵);订舱后货件出现在追踪与地图。

### F6 角色与客户门户(P1,1.5d)
`dim_users(id, email, role ops|manager|customer, customer_id?)` + session cookie 简易认证(demo 账号 ops@demo / acme@demo);行级隔离中间件(customer 只见自己货件/文档/告警);前端按角色隐藏运营面板。对齐 Flexport 门户。验收:customer 登录遍历所有 API 均被行级过滤(测试)。

### F7 文档中心(P1,1.5d)
`dim_documents(id, shipment_id, doc_type AWB|DG_DECL|PACKING_LIST|INVOICE|CUSTOMS, file_path, eawb_status none|sent|accepted)`;PDF 生成(reportlab,模板:AWB 样式 + DG 申报含 UN 号/类别/包装组);从订单一键生成。对齐 CargoWise ECM。验收:AWB PDF 与货件数据一致(抽字段断言);DG 货件强制要求 DG_DECL 才能进 BOOKED(guard)。

### F8 结算与对账(P2,1d)
`fact_charge_lines(shipment_id, charge_type freight|fuel|thc|demurrage|uld, amount, basis)`(费率卡 + 规则生成);`fact_invoices(invoice_id, customer_id, amount, status open|paid|disputed)`。验收:ORD 事故货件的费用线与毛利 -23% 对得上(一致性测试)。

## Release 3 — v1.0「生产化方向」(设计稿级,作品集可只做方案页)

- **真实接入**:ADS-B(FlightAware AeroAPI)/ AIS / 承运人 EDI;接入层已由 F4 备好契约
- **预测 ETA**:按历史腿级延误分布给 ETA 分位数(FourKites Dynamic ETA 概念,对现有确定性模拟是天然延伸)
- **多租户 + Postgres + docker-compose + CI(GitHub Actions: pytest+build)**
- **可观测**:结构化日志、告警规则命中率看板

## 依赖与顺序

```
F1 里程碑/规则 ──► F3 通知 ─────────┐
   │            ► F4 FSU(事件落库) │
   └─► 异常工作台 ◄── F4 补录解锁告警  ├─► R1 彩排
F2 地图(独立,可与 F1 并行)          ┘
F5 订单 ──► F6 门户 / F7 文档 ──► F8 结算
```

**建议实施顺序**:F1 → F4(共用电表模型)→ F3 → F2(视觉大件放后面不阻塞)→ R1 彩排 → F5 → F7 → F6 → F8。

## 工作量汇总

| Release | 内容 | 工作量 |
|---|---|---|
| v0.2 | F1 里程碑 2.5d + F2 地图 2d + F3 通知 1.5d + F4 FSU 1.5d | **7.5d** |
| v0.3 | F5 订单 2d + F6 门户 1.5d + F7 文档 1.5d + F8 结算 1d | **6d** |
| v1.0 | 真实接入/预测 ETA/多租户/CI | 设计稿级 |

## 新增数据模型汇总(13 张)

dim_milestone_codes、fact_milestones_plan、fact_milestone_events、fact_alert_rules、fact_alerts、dim_locations、dim_subscriptions、notification_outbox、ingest_log、ingest_rejects、dim_awb、dim_users、dim_documents、fact_charge_lines、fact_invoices(15 张含计数更正)。

## 面试叙事映射(升级后)

- F1/F4:GT 面试讲"我懂 Cargo iQ/FSU 里程碑体系与数据脏现实"(行业语言)
- F1 异常闭环 + Agent raise_alert:GT Item 4 从"提建议"升级为"驱动处置"
- F2:控制塔门面 + 懂多模态数据源差异(AIS/ADS-B/GPS)
- F5-F8:讲得出 forwarder/货代完整业务流(quote→book→ship→docs→invoice)

## 来源

沿用 PRODUCT_GAP_ANALYSIS.md 的调研来源(IATA Cargo iQ、Cathay Cargo Track & Trace/UltraTrack、project44/FourKites/CargoWise/Flexport、ERPNext/Odoo/Traccar、Terminal49/CargoSmart API 档案等),不再重复列出。
