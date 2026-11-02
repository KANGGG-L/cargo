# 迭代计划 R2-fix:基于双验收的修复清单(2026-11-03)

> 输入:docs/acceptance/ 两份严格验收(面试 7/10、产品运营 6/10)。本轮目标:消除全部"主张与实现不符",修复演示工程,让项目经得起运营专家与面试官的双向深挖。

## 批次 A — 真实性修复(消除"会被当场戳穿")

| # | 问题(验收证据) | 修复 | 验收标准 |
|---|---|---|---|
| A1 | AWB 校验位算法错:用 (前缀×10⁷+流水)%7,CX/KE/EK 全错(产品验收#1) | 改 IATA 规则:**7 位流水号 mod 7**,前缀只做路由 | 测试断言 160-XXXXXXX(X 为 serial%7);三航司样本全对 |
| A2 | 级联模拟三场景同一套代码,chain.py 不读 event_type(产品验收 FAIL 域 c) | 场景配置化:每 event_type 一条"首损节点+传播边"——hkg_closure=空运离港取消(现模型);yantian=CNYTN feeder 滞留→其货物的 HKG 空运衔接取消;szbp=SZX 卡车滞留→同传播;删除 chain.py 死代码 | 三个场景输出可区分(受影响集合/滞留腿/细分维度不同);死代码移除 |
| A3 | 盐田运价"+35~55%"与实测 +22% 矛盾(数据诚实破功) | 生成器:feeder 基准价噪声收窄(520-600)+ 拥堵乘数保持 1.35-1.55,使尖峰真实落带;README/DATA_DICTIONARY 改为与实测一致口径 | 测试断言尖峰/基线 ∈ [1.3, 1.6];文档数字与数据一致 |

## 批次 B — 隔离与信任(系统级承诺)

| # | 问题 | 修复 | 验收标准 |
|---|---|---|---|
| B1 | 测试直写演示库:第 4 站高光不可重演(面试验收#1) | tests/conftest.py:**每会话把真实库拷贝到临时路径**,经 DB_PATH 环境变量注入(pydantic-settings 原生支持),测试与演示库彻底隔离 | 演示库不被测试改动:跑完测试后 ingest 样例仍能 ingested≥1 且自动销警 |
| B2 | 行级隔离只守 portal 一门,无凭证 /api/shipments 等全 200(产品验收 FAIL 域 g) | 数据端点(shipments/alerts/orders/settlement/documents)统一鉴权依赖;前端应用加载即以 ops@demo 自动登录(demo 语义);/api/analytics/overview(纯聚合)与 /api/chat 保持开放并在文档声明 | 无 cookie curl 数据端点 → 401;前端七页照常工作(自动登录);测试全部经登录 fixture |
| B3 | 事件时间戳无信任分级:17 个月"延误"可入库(产品验收差距 2) | ingest/clock 发射时校验 \|event_ts − planned_ts\| ≤ 45 天,越界 reject('implausible timestamp') | 测试:越界行进拒绝队列,正常补录不受影响 |
| B4 | Agent 白名单不含告警/事件表(面试刀题 #2) | ALLOWED_TABLES + 语义层补 fact_alerts / fact_milestone_events / fact_planned_legs(只读) | Agent 可答"当前有哪些未处理异常" |
| B5 | eawb_status 硬编码 sent,"accepted" 不可达 | AWB 文档生成 = sent;补录 AWB 确认事件(FSU 格式 ACK 行或订单端点)→ accepted | 测试覆盖 sent→accepted 流转 |
| B6 | demurrage 记账基础错(吨·小时,应箱/天) | 口径改 **TEU·天**:volume_cbm/67 折算 TEU,滞留天 = max(0, 延误-24h)/24;basis 字符串如实描述;disputed 状态接通(POST dispute) | 测试:滞期费随延误天数线性、封顶生效;dispute 流转可达 |

## 批次 C — 演示工程

| # | 问题 | 修复 |
|---|---|---|
| C1 | MOCK_PLANS 缺 raise_alert | 诊断剧本第二拍 raise_alert(诊断→工单闭环可离线演示) |
| C2 | 剧本数字漂移 | DEMO_SCRIPT 改为"口径+自验命令"写法(不锁死具体数值,给出核对命令),并修订阅字段、README 测试数 |
| C3 | 演示库重建 | scripts/rebuild_demo.sh:generate→init→sync→开时钟;剧本头部引用 |
| C4 | live LLM 429 | .env 建议:演示默认 mock(README 明确),live 仅作可选 |

## 不做(记录理由)

- CIMP 报文全格式/报关单/AR 账龄:超出作品集性价比,ROADMAP v1.0 保留
- 告警聚类/SLA:P2,记录
- 真实 ADS-B/AIS:契约已备,留 v1.0 未做项

## 验收

- 全部测试 ≥3 连绿(隔离库);演示链路(订阅→sync→补录→销警)在演示库复演成功
- 重新自查三处"主张与实现不符"全部消除
