# 产品差距分析:现状 vs 真实货运运营系统

> 调研日期 2026-11-03。两路调研:GitHub 开源成熟产品盘点 + 真实行业运营需求(以国泰 Sea-Air / GBA 方案、Cargo iQ、project44/FourKites/CargoWise 等为参照)。结论服务于一个问题:**这个作品集要补什么,才从 toy code 变成"像真系统"。**

## 一句话结论

当前产品是一个**分析后视镜**(BI + AI 复盘),而真实控制塔的本质是**运营方向盘**——围绕"订单 × 里程碑 × 异常闭环"驱动人做事。最大差距不在可视化,而在**业务对象模型**(订单生命周期、计划里程碑、异常工单)与**数据接入层**。

## 现状盘点(已有)

| 域 | 已有 | 成熟度 |
|---|---|---|
| BI 仪表盘 | 三模态 KPI、趋势、桑基、航线健康度 | ★★★☆(口径清晰,缺下钻) |
| 货件追踪 | 逐段 trace 时间线(计划 vs 实际)、筛选、桑基流 | ★★☆(有计划基线,但无标准里程碑语言) |
| AI Agent | Text-to-SQL(语义层+防火墙)、异常诊断、扰动模拟、报价 | ★★★(分析闭环,无执行闭环) |
| 数据层 | 星型模式、只读防火墙、确定性合成数据、宏观引用 | ★★★ |
| 完全缺失 | 地图、订单管理、异常工单、通知订阅、文档合规、角色权限、集成接入、审计 | — |

## 差距矩阵(按真实运营刚需排序)

| # | 功能域 | 为什么真实运营必需 | 成熟参照 | 缺口 | 优先级 | 工作量 |
|---|---|---|---|---|---|---|
| 1 | **里程碑与规则引擎** | 控制塔本质 = 计划 vs 实际偏差管理。行业语言是 Cargo iQ / FSU 状态码(RCS 收货、DEP 离港、ARR/RCF 到港、NFD 待提、DLV 交付);"RCF 后 24h 无 NFD = 清关卡住"这类规则驱动告警 | IATA Cargo iQ;Limco 里程碑指南 | 现有 trace 只有自定义状态,无标准里程碑字典与"缺失/超时"规则 | **P0** | 中(纯模拟数据即可做) |
| 2 | **订单/货件生命周期状态机** | 追踪、文档、结算全部挂在订单上;没它桑基图没有业务实体。状态:报价→订舱(生成 AWB)→收货→打板→离港→到港→清关→签收 | ERPNext Shipment、OFBiz Order/Shipment、Flexport 门户 | 有货件但生命周期是静态字段(DELIVERED/DELAYED),不是可流转的状态机 | **P0** | 中 |
| 3 | **地图可视化** | "控制塔"的用户默认心智就是地图;时间线只有事件没有位置 | project44 多模态;FlightAware ADS-B / AIS;国泰 UltraTrack(ULD 蓝牙) | 无 | **P0** | 中(Mapbox/Leaflet + 港口机场坐标 + 模拟航迹) |
| 4 | **异常工作流(告警→认领→处置→关闭)** | 诊断只输出结论=看板;真系统按规则生成异常单、派工、留处置记录——控制塔与报表的分水岭 | FourKites exception flagging + 预测 ETA | AI 诊断无闭环载体 | **P1** | 中 |
| 5 | **通知与订阅** | 控制塔价值在主动推送(客户按 AWB/阈值订阅里程碑与延误);国泰 Track & Trace 即标配邮件订阅 | Cathay Track & Trace 订阅、Traccar 告警 | 无 | **P1** | 小(邮件/webhook + 订阅表) |
| 6 | **文档与合规** | e-AWB(FWB/FHL)、危险品申报(UN 号/类别)、报关单证——没有文档域,产品无法支撑真实操作 | CargoWise ECM+海关、IATA e-AWB | 无 | P1(演示可做文档中心壳) | 中 |
| 7 | **数据接入层(命门)** | 事件从哪来:空运 FSU 状态报文、航班 ADS-B、海 AIS、陆 ELD;且脏数据是常态(晚点/重复/乱序,需去重+时间戳信任分级+预测 ETA 兜底);e-AWB 渗透率 ~85%,必须兼容纸质兜底 | CARGO-IMP/Cargo-XML、Flexport webhook 事件流 | 完全模拟,连"报文进站"的形态都没有 | P1(做 mock FSU 解析器即可高性价比证明) | 中 |
| 8 | **角色与客户门户** | 货主/货代/运营权限不同,客户只见自己的货与 POD | ERPNext 角色行级权限、Odoo 门户 | 无 | P2 | 中 |
| 9 | **费率与结算** | 附加费规则(demurrage/detention、ULD 费)自动挂账、应收应付 | Freightos R&R、ERPNext 发票 | 有报价无结算 | P2 | 中 |
| 10 | **审计日志 / 主数据管理 / 导入导出** | 合规与运维基线 | Frappe Version、Odoo base_import | 无 | P2 | 小 |

开源关键事实:**TMS/货代领域没有单一开源霸主**——该空间由商业 API(Terminal49、CargoSmart、project44)主导,开源成熟度集中在 ERP(Odoo 55.5k★/ERPNext 40.9k★)、WMS(OpenBoxes)、车队追踪(Traccar 8k★)。这既是坏消息(没有可抄的整体答案),也是好消息(此赛道的开源控制塔是空白,作品集差异化成立)。

## 路线图建议

**v0.2 —— 真实性跃升包(性价比最高,全部可用模拟数据)**
1. Cargo iQ 里程碑字典 + 计划/实际双轨时间线 + 缺失/超时规则引擎(RCS/DEP/ARR/RCF/NFD/DLV)
2. 异常工作台:规则/AI 诊断 → 异常单(open→acknowledged→resolved→closed)+ 处置记录;Agent 的 diagnose 结果一键生成异常单
3. 地图:HKG 枢纽 + 港口/机场坐标 + 多段航迹动点(模拟轨迹流,注明 mock)
4. 通知:邮件订阅(按 AWB/阈值)+ 延误 webhook

**v0.3 —— 运营闭环包**
5. 订单状态机 + 订舱流(报价单 → 订舱确认 → AWB 号回填)
6. mock FSU/Cargo-XML 报文进站解析器 + 去重/乱序处理(证明懂数据接入现实)
7. 文档中心(e-AWB/DG/报关单据的生成与挂载)、角色与客户只读门户

**v1.0 方向(作品集可只做设计稿)**
真实接入层(ADS-B/AIS API)、结算与对账、预测 ETA(FourKites 式)、多租户。

## 面试叙事价值对照

- 里程碑规则引擎 → "我懂 Cargo iQ/CIMP 里程碑体系"(行业语言能力,GT 面试最加分)
- 异常工作台 + AI 诊断入流 → GT Item 4(审视流程提改进)的**执行闭环**,不只是建议
- mock FSU 解析器 → "我知道数据从哪来、有多脏"(控制塔产品经理思维)
- 地图 → 控制塔门面,第一印象

## 来源

开源盘点:odoo/odoo(55.5k★)、frappe/erpnext(40.9k★)、metabase(50.1k★)、traccar/traccar(8.0k★)、apache/ofbiz、OpenBoxes、OCA/wms、next-tms/freight_kit;topics: ocean-freight / cargo-tracking。
行业参照:IATA Cargo iQ 讲义(iata.org)、Limco 里程碑指南、IATA Cargo-XML(eAWB FWB/FHL/FSU)、Cathay Cargo GBA 方案页与 Track & Trace 订阅页、UltraTrack(Descartes/Swire 公告)、project44/TRADLINX 对比、FourKites 异常与预测 ETA、CargoWise 海关/ECM、Freightos 报价、VizionAPI 海运里程碑、FlightAware AeroAPI、AIS 数据质量研究(ResearchGate)、Flexport API 文档。星数与产品功能以 2026-11-03 实际核验为准,未核实项已在正文标注。
