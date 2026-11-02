# 数据字典与指标口径

## 事实表

### fact_shipment_legs(运营核心,粒度 = 运输段)

| 列 | 说明 |
|---|---|
| leg_id / shipment_id / leg_sequence | 段主键;所属货件;链内序号(1..n) |
| transport_mode | `SEA`(驳船进港)/ `AIR`(远洋空运)/ `TRUCK`(跨境集卡或末端派送) |
| origin_facility / destination_facility | 设施代码:海港 `CNSHA` 上海、`CNNGB` 宁波、`CNYTN` 盐田;空港 `HKG`、`LAX`、`ORD`、`LHR`、`FRA`、`NRT`、`SIN`、`SYD`;末端 `*_METRO` |
| carrier_code / voyage_flight_no | 承运人(CX = Cathay Cargo 航段;其余为虚构承运人)与航班/航次 |
| planned_/actual_ depart_/arrive_ts | ISO-8601 时间戳(字符串,字典序即时间序) |
| delay_minutes | 实际到达 - 计划到达(分钟,可为负=早到) |
| distance_km / allocated_cost_usd | 段距离;段分摊成本 |
| leg_status | COMPLETED(按各模态 OTP 容差)/ DELAYED |

### fact_air_kpi_daily(航线×日)

`scheduled/completed/cancelled_flights`、`atk_thousand`/`rtk_thousand`(可用/收入吨公里,千)、`cargo_load_factor`(0-1)、`on_time_departure_rate`/`on_time_arrival_rate`(0-1)、`cargo_yield_per_rtk_usd`、`backlog_tonnes`(未提离港积压)。

### fact_ocean_rate_weekly(驳船走廊×周) / fact_rate_cards(费率卡)

走廊:`YANTIAN_FEEDER_HKG`、`PRD_FEEDER_HKG`、`NINGBO/SHANGHAI_COASTAL_HKG`。费率卡按 `mode × origin × dest × weight_break`(MIN/+0KG/+300KG/+1000KG 美元每公斤;PER_FEU/PER_TRUCK 每箱/每车)。

### fact_disruption_events(三个可复现剧情)

| 事件 | 窗口 | 数据指纹 |
|---|---|---|
| TYPHOON_2025_09(HKG,WEATHER) | 2025-09-15 → 09-21 | 空运 OTP 86% → ~30%,大量取消,积压 3-4k t |
| YANTIAN_CONGESTION_2026_03(CNYTN,PORT_CONGESTION) | 2026-03-01 → 03-15 | 盐田驳船延误 ~2h → 50-70h;走廊运价 +35~55% |
| PRICING_ERROR_2026_06(HKG-ORD,COMMERCIAL) | 2026-06-01 → 06-30 | 航线毛利 +20% → −23%;yield 塌至网络 45% |

### public_*(宏观,带来源)

`public_hkg_air_cargo_monthly` —— HKAA 月度吞吐量(总量/进/出/转口 + 同环比),来源:hongkongairport.com 交通统计。
`public_scfi_ocean_rate_weekly` —— 上海航运交易所 SCFI 综合指数与分航线即期运价,来源:en.sse.net.cn。

## 维度表

**dim_customers**:50 家虚构货主(forwarder / e_commerce / manufacturer / perishable_broker / pharma_logistics;区域、tier、账期)。
**dim_shipments**:货级合同口径 —— 链型(`SEA_AIR_TRUCK` 40% / `TRUCK_AIR_TRUCK` 35% / `DIRECT_AIR` 25%)、品类、计费重/体积/件数、`contracted_revenue_usd`、`estimated/actual_cost_usd`、`status`(**±60 min 端到端容差**:DELIVERED / DELAYED / EXCEPTION=+24h 以上)。

## 指标口径(语义层的文档版)

| 指标 | 口径 | 基准水位 |
|---|---|---|
| 空运 OTP | 到达延迟 \|Δ\| ≤ 15 min 的航段占比 | 85-95%(台风窗口 ~30%) |
| 海运 OTP | 延误 ≤ 240 min(4 h) | ~87-90% |
| 卡车 OTP | 延误 ≤ 60 min | ~90% |
| 端到端货件 OTP | 末段实际到达与计划差 ≤ 60 min | ~79% |
| 载货率 CLF | SUM(RTK)/SUM(ATK) | 76-88%(台风期 55-70%) |
| 空运 yield | 美元/RTK(RTK 加权) | 0.28-0.42(ORD 事故期 0.16-0.20) |
| 枢纽停留 | 驳船实际到达 → 货机实际离港 | 平均 ~9 h(下限物理约束 1.5 h) |
| 毛利 | (合同收入-实际成本)/合同收入 | 15-30%(ORD 事故 −23%) |

## 合成数据生成

`backend/scripts/generate_data.py`,seed=42,2025-05-01 → 2026-10-31 共 18 个月,7,980 票 / 21,936 段。级联逻辑:驳船/卡车晚点 → 若压缩计划停留 <2h 则触发脱班改签(改签延误 ≥ feeder 晚点 + 1.5 h,保证物理一致)→ 末端卡车段叠加空运段延误。重跑字节级一致(md5 已验证)。
