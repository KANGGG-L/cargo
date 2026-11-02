# 面试演示剧本(5 分钟)

前置:`backend` 起 uvicorn(8000),`frontend` 起 `pnpm start`(3000)。无 API key 也能全程演示(mock 模式,数据真实执行)。

## 开场(30 秒)

> "这是一个面向 Sea-Air-Land 多式联运的货运控制塔:货从盐田驳船进港、香港转运、远洋空运、末端卡车派送。左边是 BI,右边是一个能查数、能诊断、能模拟、能报价的 AI 运营分析师。数据是按行业基准校准的合成数据,里面埋了三个真实风格的事故,我们逐一挖出来。"

## 第 1 站:控制塔总览(页面 `/`)

- 指认 KPI:空运 OTP 85.8%、端到端 79.3%、载货率 81.9%、枢纽停留 9.3h、毛利 19.5%
- 指出日线图上的**红色阴影带**(2025-09 台风):OTP 直落、积压跳升
- 指出月度毛利线的 **2026-06 凹坑**(HKG-ORD 运价事故)
- 叙事点:OTP 用了两种口径(航段 ±15min vs 端到端 ±60min)——说明"指标口径"是 BI 的第一性问题

## 第 2 站:链路追踪(页面 `/network`)

- 点一票 SEA_AIR_TRUCK 货:盐田驳船 → CX 货机 → 法兰克福卡车,逐段计划 vs 实际
- 指出底部桑基图:全网物流量如何汇聚 HKG 枢纽再辐射出去
- 叙事点:数据模型按"段"存储且模态无关,同一 schema 支撑海/陆/空叙事

## 第 3 站:异常诊断(Agent,问题 1)

输入:`Why did sea OTP drop in March 2026?`

- Agent 调 `diagnose_anomaly`(scope=sea, anchor=2026-03-20)
- 工具卡:基线 3.3h → 近期 16.7h,匹配扰动事件 EVT-2026-002(盐田拥堵 03-01→03-15)
- 回答含改进建议(驳船改签阈值、拥堵附加条款)
- 叙事点:**这不是查询,是"发现+归因+建议"的闭环**,对应流程改进能力

## 第 4 站:Text-to-SQL(问题 2)

输入:`Which air lanes carry the most tonnage?` 或 `Show the HKG-ORD monthly gross margin in 2026`

- 展开"Querying control tower database"工具卡:**给面试官看生成的 SQL**
- 叙事点:准确率来自语义层(指标口径 + verified few-shot),安全来自只读防火墙(sqlglot AST + 表白名单 + LIMIT 钳制 + mode=ro 三层)
- 可追问演示:尝试 `DELETE FROM ...` 会被防火墙拦截(有测试覆盖 9 类攻击向量)

## 第 5 站:扰动模拟(问题 3)

输入:`Simulate a 48h typhoon closure of HKG`

- 确定性模型:受影响航段数、积压吨数、收入风险、恢复曲线(130% 疏运能力)
- 叙事点:同一参数永远同一结果(可复现),模型假设透明(可在 ARCHITECTURE.md 讲生产化路径:离散事件仿真)

## 收尾(可选,30 秒)

输入:`Quote 500kg from CNYTN to LAX sea-air`

- 海空联运报价:驳船段 + 货机段,标准运价语义(重量段、最低收费、整箱竞争)
- 叙事点:一个 Agent 四个工具,架构上随时可挂第五个(如舱位确认)

## 备用问答(应对深挖)

- **数据哪来的?** 运营明细是合成数据,seed=42 字节级可复现,KPI 分布按 HKAA/SCFI 等公开基准校准,来源写在 CSV 头部和 DATA_DICTIONARY
- **为什么不用 LangChain/LangGraph?** 简历上已有 LangChain RAG 项目;这里故意手写循环,演示对 function-calling 协议本身的理解,也换来 SSE 事件流的完全可控
- **生产化缺什么?** 真实数据接入(CDM/AODB)、流式更新、离散事件仿真、权限与审计
- **海/陆岗位怎么复用?** 换叙事焦点 + 预置问题集即可;schema 的 mode 字段就是为此设计的
