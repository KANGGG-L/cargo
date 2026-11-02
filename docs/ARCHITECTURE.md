# 架构与设计决策

## 总体形态

三层:Next.js 前端(BI + 对话)→ FastAPI(分析 API + Agent 编排)→ SQLite 星型模式。选型的取舍:

| 决策 | 选择 | 理由 | 放弃的选项 |
|---|---|---|---|
| 前端框架 | Next.js 16 App Router | 企业级全栈叙事,ECharts 生态最全(桑基/多轴/dataZoom) | Streamlit(观感偏 demo)、纯 SPA(丢 SSR/路由) |
| 后端 | FastAPI | 异步原生适合 SSE 流式;Python 数据栈与 Agent 生态无缝 | Node 全栈(LLM/数据分析生态弱) |
| 数据库 | SQLite 单文件 | 零部署依赖、作品集可一键复现;2 万行级完全够用 | Postgres(重;需要容器) |
| Agent 编排 | 手写 async function-calling 循环(~150 行) | 每一步可讲清、零框架锁定、SSE 事件完全可控;与简历上的 LangChain RAG 项目形成互补 | LangGraph(抽象层厚,排障成本高) |
| LLM 接入 | OpenAI 兼容协议适配器 + mock 回放 | GLM/DeepSeek/OpenAI/Ollama 全兼容;断网/无 key 演示零风险 | 只接单一厂商 |
| 图表 | ECharts 6 | 桑基图(模态流)、双轴、markArea(台风窗口)开箱即用 | Recharts(桑基要自己造) |

## 核心设计

### 1. 模态无关的星型模式

运营事实的最小颗粒是**段(leg)**,每段带 `transport_mode ∈ {SEA, TRUCK, AIR}`:

```
dim_customers ──< dim_shipments ──< fact_shipment_legs
fact_air_kpi_daily(航线×日)  fact_ocean_rate_weekly(驳船走廊×周)
fact_rate_cards(报价)       fact_disruption_events(扰动事件)
public_hkg_air_cargo_monthly / public_scfi_ocean_rate_weekly(宏观)
```

一票货的链路由 `transport_chain_type`(如 SEA_AIR_TRUCK)+ `leg_sequence` 描述。**申请海运或陆运岗位时,只换叙事焦点与预置问题集,代码零改动** —— 这是"作品集可复用"要求的落地。

时间戳以 ISO-8601 字符串存储:SQLite 下字典序即时间序,且能直接进 `julianday()/strftime()`,换取 schema 的简单与可移植。

### 2. 语义层(Text-to-SQL 的准确率来源)

`app/semantic_layer.py` 三件套:

- **指标定义**:8 个业务指标(空/海/陆 OTP、端到端 OTP、载货率、yield、枢纽停留、毛利)各带公式 + canonical SQL,口径唯一(如空运 OTP = ±15 min,端到端 = ±60 min 容差)
- **表目录**:每列的业务含义说明
- **20 条 verified few-shot**(Q→SQL),全部有测试保证可在当前库上执行

nl_to_sql 流程:df 加权检索 top-3 few-shot + schema 上下文 → LLM 产 JSON `{sql, chart}` → 防火墙校验(失败带错误反馈重试一次)→ 执行。few-shot 检索用文档频率加权(稀有词主导),避免 "air/otp" 这类通用词把 "overall OTP" 误配到台风日报。

### 3. 只读 SQL 防火墙(三层,纵深防御)

1. **AST 层**(sqlglot):单语句、必须是 SELECT、禁 DML/DDL/PRAGMA/ATTACH/SELECT-INTO、表白名单(含 CTE 别名豁免)
2. **重写层**:无 LIMIT 补 `LIMIT 200`,超限钳制
3. **连接层**:`file:...?mode=ro` + `PRAGMA query_only = ON` —— 即使前两层被绕过,数据库连接本身只读

### 4. Agent 循环与事件流

手写循环,最多 6 轮:LLM 流式输出(token 直接推 SSE)→ finish_reason=tool_calls 时并行执行工具 → 工具结果以 digest 回填 → 下一轮。SSE 事件五种:`token` / `tool_start` / `tool_end`(带 UI 渲染 payload)/ `error` / `done`。

工具结果有三张面孔:`summary`(UI 一行)、`payload`(前端渲染:表格/图表 spec/发现列表/恢复曲线/报价明细)、`llm_digest`(回给模型的紧凑文本,大表截 10 行)。

### 5. mock 模式 = 剧本 + 真执行

MockLLM 与 LiveLLM 实现同一接口。剧本命中时按 plan 发出工具调用;**SQL 来自语义层 verified few-shot,在真库上真执行** —— 演示的说服力来自真实数据,而不是假对话。未命中的问题也会走真实 query_data,仅叙述受限并明示 mock 状态。

### 6. 异常剧情是"设计出来的",不是"碰出来的"

三个剧情(2025-09 台风袭港 / 2026-03 盐田拥堵 / 2026-06 HKG-ORD 运价事故)在生成器中显式注入,并跨表一致:腿级延误、日级 KPI(OTP/取消/积压)、周级运价(+35~55%)、货级毛利全部联动。测试断言其存在与幅度,演示因此可复现、可深挖。

## 已知取舍(面试可聊)

- 时间戳用字符串而非 DATETIME 类型(可移植性 vs 严格类型)
- 腿级无收入列:收入记在货级(合同口径),腿级只有成本分摊 —— 航线毛利分析走货级 + 空运 KPI yield 两条路
- 模拟模型是参数化启发式(吞吐×时长×严重度),不是离散事件仿真 —— 面试可展开"生产化会怎么做"
- 单机 SQLite 无并发写场景(应用只读 + 脚本重建)
