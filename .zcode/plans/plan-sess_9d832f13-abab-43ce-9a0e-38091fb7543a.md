# HKG Cargo Control Tower — 多式联运 AI 货运控制塔 实施计划

## Context

为申请国泰货运毕业培训生(及后续海运/陆路货运岗位)构建作品集项目:一个展示 **Sea-Air-Land 多式联运链路**的 AI 货运控制塔,包含 BI 仪表盘和一个多工具 AI Agent。核心叙事对齐 GT 项目 5 项学习目标中的 Item 4(审视运营流程、提改进建议)和 Item 5(善用最新科技创造竞争优势)。空仓库从零搭建。

**已定技术决策:** Next.js(App Router, TS)+ FastAPI(Python)+ SQLite 星型模式;ECharts;界面英文 + README/讲解中文;手写异步 function-calling 循环(openai SDK);LLM 走 OpenAI 兼容适配器(GLM/DeepSeek/OpenAI/本地 Ollama 均兼容该协议)+ 无 key 时 mock 回放模式保证演示零风险;数据 = 公开宏观数据(带来源引用)+ 按真实行业 KPI 校准的合成明细。

## 目录结构

```
cargo/
├── README.md                  # 门面: 截图 + 架构图 + 面试叙事
├── docs/
│   ├── ARCHITECTURE.md        # 架构与设计决策
│   ├── DATA_DICTIONARY.md     # 业务指标定义(语义层的文档版)
│   └── DEMO_SCRIPT.md         # 面试演示剧本(5 个预置问题 + 预期结果)
├── data/
│   ├── public/                # 宏观数据 CSV(HKG 吞吐、SCFI 运价指数,每文件头部注明来源 URL)
│   └── synthetic/             # 合成运营明细 CSV
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI 入口 + CORS + 路由
│   │   ├── config.py          # 环境变量: LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
│   │   ├── db.py / models.py  # SQLAlchemy + 星型模式 ORM
│   │   ├── semantic_layer.py  # 指标字典 + few-shot Q→SQL(喂给 Agent 的上下文)
│   │   ├── agent/
│   │   │   ├── loop.py        # 手写异步工具调用循环(SSE 流式)
│   │   │   ├── tools.py       # 4 个工具的定义与执行
│   │   │   ├── prompts.py     # 系统提示词(控制塔分析师人设)
│   │   │   └── safety.py      # SQL 只读校验
│   │   ├── llm/client.py      # OpenAI 兼容适配器(base_url 可指 Ollama)
│   │   ├── llm/mock.py        # 预录轨迹回放(断网/无 key 演示)
│   │   └── routers/
│   │       ├── chat.py        # POST /api/chat (SSE: token/工具事件/图表 spec)
│   │       ├── analytics.py   # KPI 预聚合
│   │       ├── shipments.py   # 链路 trace
│   │       └── simulation.py  # 扰动模拟参数化模型
│   ├── scripts/generate_data.py   # 种子随机合成数据生成器
│   ├── scripts/init_db.py
│   └── tests/                 # SQL 安全、工具函数、模拟模型的 pytest
└── frontend/
    └── src/
        ├── app/page.tsx           # 控制塔总览
        ├── app/network/page.tsx   # 链路视图
        ├── app/agent/page.tsx     # Agent 对话
        └── components/            # KpiCard / ChartPanel / ChatWindow / TraceTimeline / ToolActivityCard
```

## 数据模型(SQLite 星型模式,模态无关是复用海/陆申请的关键)

- `fact_shipment_legs`:每段运输一行,含 `mode`(sea/truck/air)、起讫、计划/实际时间、delay_minutes、weight_tonnes、revenue_usd、cost_usd、carrier、status
- `dim_shipments`(客户、品类、incoterm、渠道)、`dim_customers`(forwarder/e-commerce/manufacturer、区域)
- `fact_air_kpi_daily`(航线×日: 载货率、OTP、ATK)、`fact_ocean_rate_weekly`(运价指数)、`fact_disruption_events`(台风/港口拥堵/罢工,含受影响航线)
- 语义层:载货率、OTP(空运 ±15min / 海运 ±4h)、吨公里收益、枢纽停留时间等指标定义 + 每指标的标准 SQL + 20+ 条 few-shot 问答

**合成数据规模:** 18 个月、约 8000 票货 × 平均 2.5 段 ≈ 2 万条 legs。**刻意注入 3 个可复现的异常剧情**(不是随机噪声):① 超强台风袭港一周 → 空运段 OTP 骤降;② 盐田港拥堵 → 需 feeder 海运段延误 +2.5 天;③ 某航线定价失误 → 利润率异常。诊断工具有真实故事可挖,演示 100% 可复现。

## Agent 设计(单一多工具 Agent,4 个工具)

1. `query_data` — 自然语言查数:语义层上下文 → 生成 SQL → 安全校验 → 执行 → 自动图表 spec
2. `diagnose_anomaly` — KPI 偏离基线检测(z-score)→ LLM 结合扰动事件表归因 → 输出瓶颈报告 + 3 条流程改进建议(直指 Item 4)
3. `simulate_disruption` — 参数化模拟(如"台风关闭 HKG 48h"):确定性公式算受影响货量、延误分布、收入风险、积压恢复曲线,LLM 撰写应对建议
4. `quote_booking` — 费率卡查询(航线×模态×重量段)+ 时效估算,支持海空联运组合报价

**SQL 安全:** 只读连接 + sqlglot 解析校验 + 表白名单 + 强制 LIMIT 200。
**SSE 事件流:** token 流、tool_call 开始/结束(前端渲染"正在查询数据库…"活动卡片)、图表 spec、最终回答。
**Mock 模式:** 为 5-6 个预置问题录制真实工具调用轨迹,无 key 时按脚本回放,保证面试演示零风险。

## 实施阶段(每阶段结束 git commit)

**Phase 0 脚手架(0.5 天):** 验证 node/python 工具链 → `git init`(cargo 内独立仓库,与父级 GitHub 目录仓库分离)→ 前后端骨架、.env.example、README 骨架。验证:两端 dev server 均能启动。

**Phase 1 数据层(1-1.5 天):** generate_data.py + ORM + init_db + 语义层 + 公开宏观数据落盘(脚本抓取,抓不到则手工整理带引用)。验证:init_db 后用 sqlite3 跑 5 条验证查询(异常剧情存在性断言)。

**Phase 2 BI API + 总览仪表盘(1 天):** analytics 路由(KPI 卡、趋势、模态分布、Top 航线)→ Overview 页 ECharts 渲染,深色控制塔主题。验证:curl 断言 KPI 数值与 SQL 直查一致;npm run build 通过。

**Phase 3 Agent 核心(1.5 天,最关键):** llm 适配器 + mock 回放 → 工具循环 → query_data + SQL 安全 → /api/chat SSE → ChatWindow(流式 + 工具活动卡片 + 内联图表)。验证:pytest 安全测试(注入 DML/跨表攻击全被拒);真实 LLM 和 mock 两模式下跑通 DEMO_SCRIPT 前 3 问。

**Phase 4 其余三工具(1.5-2 天):** diagnose/simulate/quote 工具 + 对应 UI(诊断报告卡、模拟面板、报价卡)。验证:三个异常剧情逐一被 diagnose 挖出并归因正确;模拟结果确定性可复现(同参数同结果);mock 轨迹扩充覆盖全部工具。

**Phase 5 链路页 + 打磨(1 天):** Network 页(货主筛选、逐段 trace 时间线、海→陆→空桑基图)→ README 完整版(截图 + 架构图 + 叙事)→ DEMO_SCRIPT + ARCHITECTURE 文档。验证:browser-use 全流程 GUI 走查 3 个页面 + 5 个预置问题。

**明确不做(除非后续要求):** 地图航线视图、用户认证、docker-compose、云端部署(Vercel/Railway 可作后续加分项)。

## 端到端验证

1. `backend`: `pytest` 全绿;`uvicorn` 启动后 curl 全部路由 200
2. `frontend`: `npm run build` 通过;三个页面 GUI 走查无控制台报错
3. 演示彩排:按 DEMO_SCRIPT 用 mock 模式完整跑一遍 5 问,断网状态可复现
4. 复用性演练:仅改首页文案 + 预置问题集,验证海运岗叙事可切换(证明架构决策成立)