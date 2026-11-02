# HKG Cargo Control Tower

面向 **Sea-Air-Land 多式联运**的 AI 货运控制塔 —— 以香港枢纽为核心,把 BI 数据分析与一个多工具 AI Agent 装进同一个驾驶舱。

> 本项目是面向航空/海运/陆运货运管培生申请的 portfolio 作品:虚构但按真实行业基准校准的运营数据,真实的工程实现。

![stack](https://img.shields.io/badge/Next.js%2016-React%2019-blue) ![api](https://img.shields.io/badge/FastAPI-Python%203.14-green) ![db](https://img.shields.io/badge/SQLite-星型模式-orange) ![llm](https://img.shields.io/badge/LLM-OpenAI兼容协议-purple)

## 它解决什么问题

多式联运货物(盐田驳船 → 香港枢纽 → 远洋货机 → 目的港卡车)的运营数据散落在各环节,控制塔把它们合成**一条链路的一张视图**:

1. **BI 总览** — 空/海/陆三模态 KPI(OTP、载货率、枢纽停留、毛利)、月度营收与利润率趋势、航线与驳船港口健康度
2. **链路追踪** — 任意一票货的逐段 trace(计划 vs 实际、延误归因、每段成本),以及全网络的模态流桑基图
3. **AI 运营分析师** — 一个 Agent、四个工具:
   - `query_data` — 自然语言查数(Text-to-SQL + 语义层 + 只读 SQL 防火墙),自动配表和图
   - `diagnose_anomaly` — KPI 偏离基线检测 + 扰动事件归因 + 流程改进建议
   - `simulate_disruption` — 台风关闭/港口拥堵的确定性量化模拟(受影响航段、积压、收入风险、恢复曲线)
   - `quote_booking` — 按航线×模态×重量段报价(标准运价语义:重量段 + 最低收费 + 整箱竞争),支持海空联运

数据里**刻意埋了三个可复现的异常剧情**(超强台风袭港、盐田港拥堵、HKG-ORD 运价配置事故),诊断与演示 100% 可复现。

## 快速开始

```bash
# 后端(Python 3.12+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_data.py   # 合成数据 → data/synthetic/*.csv(seed=42,字节级可复现)
python scripts/init_db.py         # CSV → data/control_tower.sqlite
uvicorn app.main:app --port 8000

# 前端(Node 20+)
cd frontend
pnpm install && pnpm build && pnpm start   # http://localhost:3000
```

**LLM 配置(可选)**:复制 `backend/.env.example` → `backend/.env`,填入任一 OpenAI 兼容端点(GLM / DeepSeek / OpenAI / 本地 Ollama)。**不填 key 也能完整演示** —— mock 模式按剧本回放 verified trace,但 SQL 与数据全部真实执行。

## 架构

```
┌─ Next.js 16 (App Router) ─────────────────────────────┐
│  控制塔总览 · 链路追踪 · Agent 对话(SSE 流式)           │
└─────────────────┬─────────────────────────────────────┘
                  │ REST + Server-Sent Events
┌─ FastAPI ───────▼─────────────────────────────────────┐
│  analytics / shipments / chat 路由                     │
│  多工具 Agent 循环(手写 async function-calling)        │
│   ├ query_data ──── 语义层 → SQL 防火墙 → 只读执行       │
│   ├ diagnose_anomaly  基线偏差 → 事件归因 → 改进建议      │
│   ├ simulate_disruption 参数化确定性模型                 │
│   └ quote_booking ── 费率卡 → 标准运价语义               │
│  LLM 适配器:OpenAI 兼容协议(GLM/DeepSeek/Ollama/mock) │
└─────────────────┬─────────────────────────────────────┘
                  │ SQLAlchemy / 只读 sqlite3(mode=ro)
┌─ SQLite ────────▼─────────────────────────────────────┐
│  星型模式:fact_shipment_legs(mode=SEA/AIR/TRUCK)      │
│  + 4 张事实表 + 2 张维度表 + 2 张公开宏观数据表           │
└───────────────────────────────────────────────────────┘
```

关键设计决策见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),指标口径见 [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md),面试演示剧本见 [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)。

## 工程亮点

- **只读 SQL 防火墙**(三层):sqlglot AST 校验(单语句、纯 SELECT、表白名单)+ LIMIT 强制钳制 + SQLite `mode=ro` 硬兜底 —— LLM 生成的 SQL 一律过闸
- **模态无关的数据模型**:运营事实按"段"存储并带 `transport_mode` 字段,空运/海运/陆运叙事共用同一 schema,切换业务线零迁移
- **mock/live 双模式 LLM**:同一事件接口;mock 用 df 加权匹配语义层 verified few-shot,语言是剧本、数据是真的
- **确定性合成数据**:seed=42 字节级可复现;延误级联(驳船晚点 → 脱班改签 → 端到端延误)有物理一致性约束
- **29 项测试**:防火墙攻击向量、三异常剧情存在性断言、引用完整性、模拟确定性、报价语义

## 数据诚实声明

- 运营明细(`data/synthetic/`)为**合成数据**,KPI 分布按公开行业基准校准(载货率 65-88%、空运 OTP 85-95%、多式联运毛利 15-30%),公司名均为虚构
- 宏观数据(`data/public/`)来自香港机场管理局与上海航运交易所 SCFI 的公开统计,每个 CSV 头部注明来源 URL
- 所有图表和 AI 回答都基于上述数据,不含真实货主或商业敏感信息

## 与管培生项目的对应

| GT 学习目标 | 本项目的体现 |
|---|---|
| 审视现有操作流程并提出改进建议 | `diagnose_anomaly` 的基线扫描 + 每个异常剧情配套的流程改进建议(如盐田拥堵下的驳船改签策略) |
| 善用最新科技为业务创造竞争优势 | 多工具 Agent + 语义层 Text-to-SQL + 扰动模拟决策支持 |
| 理解组织与运作 | 控制塔本身就是多式联运业务的全景视图:链路、KPI、成本、时效 |

## License / 说明

个人学习作品。数据生成与运行方式见上文,欢迎面试官复现验证。
