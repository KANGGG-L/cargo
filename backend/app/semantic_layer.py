"""Semantic Layer for HKG Cargo Control Tower.

Defines the semantic domain model, business metric calculations, table catalogs,
and 20+ verified few-shot Question -> SQL pairs for natural language querying.
"""

from typing import Any, Dict, List

# ---------------------------------------------------------------- Metric Definitions

METRIC_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "air_otp": {
        "name": "Air On-Time Performance",
        "description": "Proportion of air legs where actual arrival is within +/- 15 minutes of scheduled arrival.",
        "unit": "percentage",
        "formula": "100.0 * SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) / COUNT(*)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS air_otp_pct "
            "FROM fact_shipment_legs WHERE transport_mode = 'AIR'"
        ),
    },
    "sea_otp": {
        "name": "Sea Feeder On-Time Performance",
        "description": "Proportion of feeder sea legs arriving within 240 minutes (4 hours) of schedule.",
        "unit": "percentage",
        "formula": "100.0 * SUM(CASE WHEN delay_minutes <= 240 THEN 1 ELSE 0 END) / COUNT(*)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * SUM(CASE WHEN delay_minutes <= 240 THEN 1 ELSE 0 END) / COUNT(*), 2) AS sea_otp_pct "
            "FROM fact_shipment_legs WHERE transport_mode = 'SEA'"
        ),
    },
    "truck_otp": {
        "name": "Cross-Border Truck On-Time Performance",
        "description": "Proportion of truck legs arriving within 60 minutes of schedule.",
        "unit": "percentage",
        "formula": "100.0 * SUM(CASE WHEN delay_minutes <= 60 THEN 1 ELSE 0 END) / COUNT(*)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * SUM(CASE WHEN delay_minutes <= 60 THEN 1 ELSE 0 END) / COUNT(*), 2) AS truck_otp_pct "
            "FROM fact_shipment_legs WHERE transport_mode = 'TRUCK'"
        ),
    },
    "multimodal_shipment_otp": {
        "name": "Multimodal End-to-End Shipment OTP",
        "description": "Percentage of complete shipments where the final leg arrives within 60 minutes of the planned arrival.",
        "unit": "percentage",
        "formula": "100.0 * SUM(CASE WHEN (julianday(final_leg.actual_arrive_ts) - julianday(final_leg.planned_arrive_ts)) * 1440.0 <= 60 THEN 1 ELSE 0 END) / COUNT(*)",
        "canonical_sql": (
            "WITH final_legs AS ("
            "  SELECT shipment_id, actual_arrive_ts, planned_arrive_ts, "
            "         ROW_NUMBER() OVER (PARTITION BY shipment_id ORDER BY leg_sequence DESC) as rn "
            "  FROM fact_shipment_legs"
            ") "
            "SELECT ROUND(100.0 * SUM(CASE WHEN (julianday(actual_arrive_ts) - julianday(planned_arrive_ts)) * 1440.0 <= 60 THEN 1 ELSE 0 END) / COUNT(*), 2) AS shipment_otp_pct "
            "FROM final_legs WHERE rn = 1"
        ),
    },
    "cargo_load_factor": {
        "name": "Cargo Load Factor (CLF)",
        "description": "Ratio of Revenue Tonne Kilometres (RTK) performed to Available Tonne Kilometres (ATK) supplied.",
        "unit": "percentage",
        "formula": "100.0 * SUM(rtk_thousand) / SUM(atk_thousand)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * SUM(rtk_thousand) / SUM(atk_thousand), 2) AS cargo_load_factor_pct "
            "FROM fact_air_kpi_daily"
        ),
    },
    "cargo_yield": {
        "name": "Air Cargo Yield",
        "description": "Revenue generated per Revenue Tonne Kilometre (USD / RTK).",
        "unit": "USD_per_RTK",
        "formula": "SUM(cargo_yield_per_rtk_usd * rtk_thousand) / SUM(rtk_thousand)",
        "canonical_sql": (
            "SELECT ROUND(SUM(cargo_yield_per_rtk_usd * rtk_thousand) / SUM(rtk_thousand), 4) AS avg_yield_usd_per_rtk "
            "FROM fact_air_kpi_daily"
        ),
    },
    "sea_kpi_departure_otp": {
        "name": "Feeder Departure OTP (weekly KPI)",
        "description": "Weekly feeder sailings departing within 240 minutes of schedule, averaged across the corridor from fact_sea_kpi_weekly.",
        "unit": "percentage",
        "formula": "100.0 * AVG(on_time_departure_rate)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * AVG(on_time_departure_rate), 2) AS sea_otp_pct "
            "FROM fact_sea_kpi_weekly"
        ),
    },
    "truck_kpi_arrival_otp": {
        "name": "Cross-Border Truck OTP (daily KPI)",
        "description": "Daily truck trips arriving within 60 minutes of schedule at GBA checkpoints, averaged from fact_truck_kpi_daily.",
        "unit": "percentage",
        "formula": "100.0 * AVG(on_time_arrival_rate)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * AVG(on_time_arrival_rate), 2) AS truck_otp_pct "
            "FROM fact_truck_kpi_daily"
        ),
    },
    "hub_dwell_time": {
        "name": "HKG Hub Dwell Time",
        "description": "Average hours spent at HKG between inbound feeder leg arrival and outbound air leg departure.",
        "unit": "hours",
        "formula": "AVG((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0)",
        "canonical_sql": (
            "SELECT ROUND(AVG((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0), 2) AS avg_dwell_hours "
            "FROM fact_shipment_legs feeder_leg "
            "JOIN fact_shipment_legs air_leg ON feeder_leg.shipment_id = air_leg.shipment_id "
            "WHERE feeder_leg.destination_facility = 'HKG' "
            "  AND air_leg.origin_facility = 'HKG' "
            "  AND feeder_leg.leg_sequence < air_leg.leg_sequence"
        ),
    },
    "gross_margin": {
        "name": "Commercial Gross Margin",
        "description": "Percentage gross margin: (contracted_revenue - actual_cost) / contracted_revenue.",
        "unit": "percentage",
        "formula": "100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd)",
        "canonical_sql": (
            "SELECT ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 2) AS gross_margin_pct "
            "FROM dim_shipments"
        ),
    },
}

# ---------------------------------------------------------------- Table Catalog

TABLE_CATALOG: Dict[str, Dict[str, Any]] = {
    "dim_customers": {
        "description": "Master dimension table for desensitized cargo forwarders, brokers, and enterprise shippers.",
        "columns": {
            "customer_id": "Unique customer identifier (CUST-001 to CUST-050)",
            "customer_name": "Fictional masked company name (e.g. Golden Dragon Logistics, Pacific Bridge Forwarding)",
            "industry_segment": "Customer industry sector (forwarder, e_commerce, manufacturer, perishable_broker, pharma_logistics)",
            "region": "Commercial operating region (Greater_Bay_Area, APAC, EMEA, Americas)",
            "tier": "Account tier classification (Strategic, Tier_1, Tier_2)",
            "payment_terms": "Standard billing payment terms (Net_30, Net_60, Prepaid)",
        },
    },
    "dim_shipments": {
        "description": "Consignment level header table tracking multimodal freight shipments across the network.",
        "columns": {
            "shipment_id": "Primary key identifier (SHP-2025-XXXXXX)",
            "customer_id": "Foreign key reference to dim_customers.customer_id",
            "origin_location": "Original dispatch facility/port (CNSHA, CNNGB, CNYTN, CNCAN, SZX, HKG)",
            "destination_location": "Final delivery destination airport or city (LAX, ORD, LHR, FRA, NRT, SIN, SYD)",
            "transport_chain_type": "Intermodal transport routing pattern (SEA_AIR_TRUCK, TRUCK_AIR_TRUCK, DIRECT_AIR)",
            "cargo_category": "Commodity category (General, High_Tech, E_Commerce, Pharma_Cold_Chain, Dangerous_Goods)",
            "total_chargeable_weight_kg": "Total chargeable weight in kilograms",
            "total_volume_cbm": "Total cargo volume in cubic meters",
            "total_pieces": "Number of physical pieces or cartons",
            "booking_ts": "ISO-8601 initial booking timestamp",
            "contracted_revenue_usd": "Total billed customer revenue in USD",
            "estimated_cost_usd": "Initial estimated operating cost in USD",
            "actual_cost_usd": "Final actual aggregated cost across all legs in USD",
            "status": "Delivery milestone status (DELIVERED = arrived within 1 h of plan, DELAYED, EXCEPTION = over 24 h late)",
        },
    },
    "fact_shipment_legs": {
        "description": "Operational leg granularity fact table capturing discrete transport legs for each shipment.",
        "columns": {
            "leg_id": "Primary key leg identifier (LEG-XXXXXX)",
            "shipment_id": "Foreign key reference to dim_shipments.shipment_id",
            "leg_sequence": "Sequential position within shipment journey (1, 2, or 3)",
            "transport_mode": "Physical transport modality (SEA, AIR, TRUCK)",
            "origin_facility": "Departure facility/port code",
            "destination_facility": "Arrival facility/port code",
            "carrier_code": "Operating transport carrier code (CX for Cathay Cargo, Feeder_Line_A, etc.)",
            "voyage_flight_no": "Flight number, vessel voyage, or truck manifest ID",
            "planned_depart_ts": "Scheduled departure timestamp (ISO-8601)",
            "actual_depart_ts": "Actual departure timestamp (ISO-8601)",
            "planned_arrive_ts": "Scheduled arrival timestamp (ISO-8601)",
            "actual_arrive_ts": "Actual arrival timestamp (ISO-8601)",
            "delay_minutes": "Arrival variance in minutes (actual_arrive_ts - planned_arrive_ts)",
            "distance_km": "Estimated distance traversed in kilometers",
            "allocated_cost_usd": "Direct allocated operating cost for this leg in USD",
            "leg_status": "Execution status (COMPLETED, DELAYED, CANCELLED)",
        },
    },
    "fact_air_kpi_daily": {
        "description": "Daily flight operational performance aggregations across key flight lanes departing HKG.",
        "columns": {
            "report_date": "Date of performance report (YYYY-MM-DD)",
            "route_lane": "Corridor identifier (HKG-LAX, HKG-ORD, HKG-LHR, etc.)",
            "scheduled_flights": "Number of scheduled flights for the date",
            "completed_flights": "Number of operated flights",
            "cancelled_flights": "Number of cancelled flights",
            "atk_thousand": "Available Tonne Kilometres in thousands",
            "rtk_thousand": "Revenue Tonne Kilometres performed in thousands",
            "cargo_load_factor": "Ratio of RTK to ATK (0.0 to 1.0)",
            "on_time_departure_rate": "Fraction of flights departing within 15 minutes of schedule",
            "on_time_arrival_rate": "Fraction of flights arriving within 15 minutes of schedule",
            "cargo_yield_per_rtk_usd": "Yield per revenue tonne-km in USD",
            "backlog_tonnes": "Estimated unlifted freight backlog tonnage in HKG terminals",
        },
    },
    "fact_ocean_rate_weekly": {
        "description": "Weekly feeder sea rate benchmarks for GBA feeder barge connections into HKG.",
        "columns": {
            "week_start_date": "Monday or release date of weekly quote (YYYY-MM-DD)",
            "feeder_corridor": "Feeder barge corridor (PRD_FEEDER_HKG, YANTIAN_FEEDER_HKG, etc.)",
            "average_rate_per_feu_usd": "Average rate per Forty-Foot Equivalent Unit in USD",
            "fuel_surcharge_baf": "Bunker adjustment factor surcharge in USD",
            "terminal_handling_charge_usd": "Terminal handling charge in USD",
        },
    },
    "fact_rate_cards": {
        "description": "Commercial tariff rate cards by transport mode, lane zone, and weight break.",
        "columns": {
            "rate_id": "Unique rate identifier (RC-XXXX)",
            "transport_mode": "Transport mode (AIR, SEA, TRUCK)",
            "origin_zone": "Origin geographic zone or facility",
            "dest_zone": "Destination geographic zone or facility",
            "weight_break": "Applicable weight bracket (MIN, +0KG, +300KG, +1000KG, PER_FEU, PER_TRUCK)",
            "base_rate_usd": "Base commercial rate in USD per kg or unit",
            "effective_start_date": "Effective validity start date",
            "effective_end_date": "Effective validity end date",
        },
    },
    "fact_disruption_events": {
        "description": "Authoritative log of external disruption events injected into network operational history.",
        "columns": {
            "event_id": "Disruption event identifier (EVT-YYYY-XXX)",
            "event_code": "Machine-readable anomaly code",
            "event_category": "Category classification (WEATHER, PORT_CONGESTION, COMMERCIAL_MISCONFIGURATION)",
            "affected_mode": "Impacted transport modality (AIR, SEA, COMMERCIAL)",
            "start_timestamp": "Start timestamp of disruption impact",
            "end_timestamp": "End timestamp of disruption impact",
            "primary_location": "Primary focal facility or hub",
            "description": "Full narrative description of disruption incident",
            "target_metric_impact": "Primary metric expected to show anomalous deviation",
        },
    },
    "fact_sea_kpi_weekly": {
        "description": "Weekly feeder-barge performance per corridor — the sea counterpart of the air lane daily KPI.",
        "columns": {
            "week_start_date": "Monday of the sailing week (YYYY-MM-DD)",
            "feeder_corridor": "Feeder corridor (PRD_FEEDER_HKG, YANTIAN_FEEDER_HKG, NINGBO_COASTAL_HKG, SHANGHAI_COASTAL_HKG)",
            "scheduled_sailings": "Sailings scheduled in the week",
            "completed_sailings": "Sailings operated",
            "cancelled_sailings": "Sailings cancelled",
            "on_time_departure_rate": "Fraction departing within 240 minutes of schedule (0.0-1.0)",
            "avg_transit_hours": "Average port-to-port transit hours",
            "slot_utilization": "Booked slot utilization (0.0-1.0)",
            "backlog_teu": "Unshipped TEU waiting at origin",
        },
    },
    "fact_truck_kpi_daily": {
        "description": "Daily cross-border truck performance per GBA checkpoint — the road counterpart of the air lane daily KPI.",
        "columns": {
            "report_date": "Date of report (YYYY-MM-DD)",
            "checkpoint": "GBA boundary checkpoint (SZBP = Shenzhen Bay, HGA = Huanggang, WJD = Wenjindu)",
            "scheduled_trips": "Cross-border feeder trips scheduled",
            "completed_trips": "Trips completed",
            "cancelled_trips": "Trips cancelled",
            "on_time_arrival_rate": "Fraction arriving within 60 minutes of schedule (0.0-1.0)",
            "avg_crossing_minutes": "Average border crossing time in minutes",
            "queue_backlog_trucks": "Trucks waiting in queue at checkpoint",
            "avg_cost_per_tonne_usd": "Average trucking cost per tonne",
        },
    },
    "public_hkg_air_cargo_monthly": {
        "description": "Official Hong Kong Airport Authority monthly cargo tonnage throughput statistics.",
        "columns": {
            "year_month": "Calendar year and month (YYYY-MM)",
            "cargo_tonnage_total": "Total handled air cargo tonnage",
            "cargo_tonnage_inbound": "Inbound cargo tonnage into HKG",
            "cargo_tonnage_outbound": "Outbound cargo tonnage from HKG",
            "cargo_tonnage_transshipment": "Transshipment cargo tonnage connecting via HKG",
            "yoy_growth_rate": "Year-on-year growth rate percentage",
            "mom_growth_rate": "Month-on-month growth rate percentage",
            "data_source": "Source citation identifier",
        },
    },
    "public_scfi_ocean_rate_weekly": {
        "description": "Shanghai Containerized Freight Index weekly global container spot rate benchmarks.",
        "columns": {
            "week_date": "SCFI release date (YYYY-MM-DD)",
            "composite_index": "SCFI composite index value",
            "shanghai_europe_usd_teu": "Freight rate to Northern Europe in USD/TEU",
            "shanghai_med_usd_teu": "Freight rate to Mediterranean in USD/TEU",
            "shanghai_uswc_usd_feu": "Freight rate to US West Coast in USD/FEU",
            "shanghai_usec_usd_feu": "Freight rate to US East Coast in USD/FEU",
            "shanghai_seasia_usd_teu": "Freight rate to Southeast Asia in USD/TEU",
            "data_source": "Source citation identifier",
        },
    },
    "dim_transport_services": {
        "description": "Shared transport capacity schedule (P0): one row per flight / barge sailing / truck trip that many shipments compete for. Join fact_allocations on service_id to see which shipments ride it.",
        "columns": {
            "service_id": "Primary key (SVC-AIR-HKG-ORD-20250915-01)",
            "transport_mode": "AIR | SEA | TRUCK",
            "carrier_code": "Operating carrier",
            "service_no": "Outward service number (CX887) — equals fact_shipment_legs.voyage_flight_no",
            "origin_facility": "Departure facility code",
            "destination_facility": "Arrival facility code",
            "scheduled_depart_ts": "Scheduled departure ISO-8601",
            "scheduled_arrive_ts": "Scheduled arrival ISO-8601",
            "cutoff_ts": "Cargo/doc cut-off before departure",
            "mct_minutes": "Minimum connecting time at the hub",
            "capacity_chargeable_kg": "Sellable chargeable weight capacity",
            "allocated_kg": "Chargeable weight currently allocated (load water-line)",
            "capacity_cbm": "Volume capacity",
            "allocated_cbm": "Volume allocated",
            "status": "SCHEDULED | DEPARTED | CANCELLED | RECOVERING",
            "disruption_event_id": "FK to fact_disruption_events when cancelled by a disruption",
        },
    },
    "fact_allocations": {
        "description": "Booking bridge (P0): a shipment leg loaded onto a shared service (and ULD). Where capacity contention, roll-over and MAWB/HAWB consolidation live.",
        "columns": {
            "allocation_id": "Primary key (ALC-XXXXXX)",
            "shipment_id": "FK to dim_shipments",
            "leg_id": "FK to fact_shipment_legs",
            "service_id": "FK to dim_transport_services",
            "uld_id": "FK to dim_ulds (AIR only)",
            "mawb_no": "Master air waybill (per service)",
            "hawb_no": "House air waybill (per shipment)",
            "priority_class": "PHARMA | PERISHABLE | HIGH_VALUE | DG | GENERAL",
            "allocated_weight_kg": "Chargeable weight this allocation occupies",
            "allocated_volume_cbm": "Volume occupied",
            "allocation_status": "CONFIRMED | ROLLED | REACCOMMODATED",
            "rolled_from_service_id": "Service this allocation was rolled off",
            "roll_reason": "CAPACITY | CUTOFF | MCT | DG_LIMIT | DISRUPTION",
            "booked_ts": "Booking timestamp",
            "decided_ts": "Allocation decision timestamp",
        },
    },
    "dim_ulds": {
        "description": "Unit Load Devices (P0): containers/pallets on an AIR service. One service holds many ULDs; one ULD carries many shipments.",
        "columns": {
            "uld_id": "Primary key",
            "service_id": "FK to dim_transport_services",
            "uld_type": "PMC | PAG | LD3 | AKE",
            "max_weight_kg": "Max chargeable weight",
            "max_volume_cbm": "Max volume",
        },
    },
}

# ---------------------------------------------------------------- Few-Shot Q->SQL Catalog

FEW_SHOT_QUERY_CATALOG: List[Dict[str, str]] = [
    # ---------------- Group A: Overall KPI Aggregations
    {
        "id": "A1",
        "category": "Overall KPI Aggregations",
        "question": "What is our overall air network On-Time Performance (OTP) across all flights?",
        "sql": (
            "SELECT ROUND(100.0 * SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS air_otp_pct, "
            "       COUNT(*) AS total_air_legs, "
            "       SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) AS on_time_legs "
            "FROM fact_shipment_legs "
            "WHERE transport_mode = 'AIR';"
        ),
    },
    {
        "id": "A2",
        "category": "Overall KPI Aggregations",
        "question": "What is the monthly average cargo load factor across all routes in 2025?",
        "sql": (
            "SELECT strftime('%Y-%m', report_date) AS month, "
            "       ROUND(100.0 * SUM(rtk_thousand) / SUM(atk_thousand), 2) AS avg_load_factor_pct, "
            "       ROUND(SUM(rtk_thousand), 1) AS total_rtk_thousand, "
            "       ROUND(SUM(atk_thousand), 1) AS total_atk_thousand "
            "FROM fact_air_kpi_daily "
            "WHERE report_date >= '2025-01-01' AND report_date <= '2025-12-31' "
            "GROUP BY month "
            "ORDER BY month ASC;"
        ),
    },
    {
        "id": "A3",
        "category": "Overall KPI Aggregations",
        "question": "What is total billed shipment revenue and overall gross margin percentage for the full 18-month period?",
        "sql": (
            "SELECT ROUND(SUM(contracted_revenue_usd), 2) AS total_revenue_usd, "
            "       ROUND(SUM(actual_cost_usd), 2) AS total_cost_usd, "
            "       ROUND(SUM(contracted_revenue_usd) - SUM(actual_cost_usd), 2) AS total_gross_profit_usd, "
            "       ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 2) AS gross_margin_pct "
            "FROM dim_shipments;"
        ),
    },
    {
        "id": "A4",
        "category": "Overall KPI Aggregations",
        "question": "What is the total tonnage carried and total flight count by destination airport?",
        "sql": (
            "SELECT destination_facility AS dest_airport, "
            "       COUNT(*) AS flight_legs_count, "
            "       ROUND(SUM(s.total_chargeable_weight_kg) / 1000.0, 2) AS total_tonnes "
            "FROM fact_shipment_legs l "
            "JOIN dim_shipments s ON l.shipment_id = s.shipment_id "
            "WHERE l.transport_mode = 'AIR' AND l.origin_facility = 'HKG' "
            "GROUP BY dest_airport "
            "ORDER BY total_tonnes DESC;"
        ),
    },
    {
        "id": "A5",
        "category": "Overall KPI Aggregations",
        "question": "What is the average hub dwell time at HKG for all multimodal shipments?",
        "sql": (
            "SELECT ROUND(AVG((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0), 2) AS avg_hkg_dwell_hours, "
            "       ROUND(MIN((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0), 2) AS min_dwell_hours, "
            "       ROUND(MAX((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0), 2) AS max_dwell_hours "
            "FROM fact_shipment_legs feeder_leg "
            "JOIN fact_shipment_legs air_leg ON feeder_leg.shipment_id = air_leg.shipment_id "
            "WHERE feeder_leg.destination_facility = 'HKG' "
            "  AND air_leg.origin_facility = 'HKG' "
            "  AND feeder_leg.leg_sequence < air_leg.leg_sequence;"
        ),
    },

    # ---------------- Group B: Multimodal Bottlenecks & Intermodal Connections
    {
        "id": "B1",
        "category": "Multimodal Bottlenecks & Intermodal Connections",
        "question": "Which origin feeder ports have the highest average sea leg arrival delay into HKG?",
        "sql": (
            "SELECT origin_facility AS feeder_port, "
            "       COUNT(*) AS total_feeder_legs, "
            "       ROUND(AVG(delay_minutes), 1) AS avg_delay_minutes, "
            "       ROUND(100.0 * SUM(CASE WHEN delay_minutes <= 240 THEN 1 ELSE 0 END) / COUNT(*), 2) AS sea_otp_pct "
            "FROM fact_shipment_legs "
            "WHERE transport_mode = 'SEA' AND destination_facility = 'HKG' "
            "GROUP BY feeder_port "
            "ORDER BY avg_delay_minutes DESC;"
        ),
    },
    {
        "id": "B2",
        "category": "Multimodal Bottlenecks & Intermodal Connections",
        "question": "Compare average HKG hub dwell time between Sea-Air cargo and Truck-Air cargo.",
        "sql": (
            "SELECT s.transport_chain_type, "
            "       COUNT(DISTINCT s.shipment_id) AS shipment_count, "
            "       ROUND(AVG((julianday(air_leg.actual_depart_ts) - julianday(feeder_leg.actual_arrive_ts)) * 24.0), 2) AS avg_dwell_hours "
            "FROM dim_shipments s "
            "JOIN fact_shipment_legs feeder_leg ON s.shipment_id = feeder_leg.shipment_id AND feeder_leg.leg_sequence = 1 "
            "JOIN fact_shipment_legs air_leg ON s.shipment_id = air_leg.shipment_id AND air_leg.leg_sequence = 2 "
            "WHERE s.transport_chain_type IN ('SEA_AIR_TRUCK', 'TRUCK_AIR_TRUCK') "
            "GROUP BY s.transport_chain_type;"
        ),
    },
    {
        "id": "B3",
        "category": "Multimodal Bottlenecks & Intermodal Connections",
        "question": "What percentage of shipments through the Yantian feeder suffered missed flight connections at HKG?",
        "sql": (
            "SELECT COUNT(DISTINCT s.shipment_id) AS total_yantian_shipments, "
            "       ROUND(100.0 * SUM(CASE WHEN (julianday(air_leg.actual_depart_ts) - julianday(air_leg.planned_depart_ts)) * 1440.0 > 120 THEN 1 ELSE 0 END) / COUNT(*), 2) AS missed_or_delayed_connection_pct "
            "FROM dim_shipments s "
            "JOIN fact_shipment_legs sea_leg ON s.shipment_id = sea_leg.shipment_id AND sea_leg.leg_sequence = 1 "
            "JOIN fact_shipment_legs air_leg ON s.shipment_id = air_leg.shipment_id AND air_leg.leg_sequence = 2 "
            "WHERE sea_leg.origin_facility = 'CNYTN' AND sea_leg.transport_mode = 'SEA';"
        ),
    },
    {
        "id": "B4",
        "category": "Multimodal Bottlenecks & Intermodal Connections",
        "question": "What is the end-to-end On-Time Performance (OTP, within 60 minutes) for Sea-Air-Truck shipments compared to Direct Air shipments?",
        "sql": (
            "WITH shipment_final_legs AS ("
            "  SELECT s.shipment_id, s.transport_chain_type, l.actual_arrive_ts, l.planned_arrive_ts, "
            "         ROW_NUMBER() OVER (PARTITION BY s.shipment_id ORDER BY l.leg_sequence DESC) AS rn "
            "  FROM dim_shipments s "
            "  JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id "
            ") "
            "SELECT transport_chain_type, "
            "       COUNT(*) AS total_shipments, "
            "       ROUND(100.0 * SUM(CASE WHEN (julianday(actual_arrive_ts) - julianday(planned_arrive_ts)) * 1440.0 <= 60 THEN 1 ELSE 0 END) / COUNT(*), 2) AS final_otp_pct "
            "FROM shipment_final_legs "
            "WHERE rn = 1 AND transport_chain_type IN ('SEA_AIR_TRUCK', 'DIRECT_AIR') "
            "GROUP BY transport_chain_type;"
        ),
    },
    {
        "id": "B5",
        "category": "Multimodal Bottlenecks & Intermodal Connections",
        "question": "Show the top 5 destination hubs by total inbound delayed volume in metric tonnes.",
        "sql": (
            "SELECT s.destination_location, "
            "       COUNT(DISTINCT s.shipment_id) AS delayed_shipment_count, "
            "       ROUND(SUM(s.total_chargeable_weight_kg) / 1000.0, 2) AS delayed_tonnes "
            "FROM dim_shipments s "
            "WHERE s.status IN ('DELAYED', 'EXCEPTION') "
            "GROUP BY s.destination_location "
            "ORDER BY delayed_tonnes DESC "
            "LIMIT 5;"
        ),
    },

    # ---------------- Group C: Anomaly Diagnostics
    {
        "id": "C1",
        "category": "Anomaly Diagnostics",
        "question": "What was the daily air leg OTP and backlog tonnage at HKG between September 15 and September 21, 2025 during the typhoon?",
        "sql": (
            "SELECT report_date, "
            "       ROUND(AVG(on_time_arrival_rate) * 100.0, 2) AS avg_arrival_otp_pct, "
            "       ROUND(AVG(on_time_departure_rate) * 100.0, 2) AS avg_departure_otp_pct, "
            "       SUM(cancelled_flights) AS total_cancelled_flights, "
            "       ROUND(SUM(backlog_tonnes), 1) AS total_backlog_tonnes "
            "FROM fact_air_kpi_daily "
            "WHERE report_date >= '2025-09-15' AND report_date <= '2025-09-21' "
            "GROUP BY report_date "
            "ORDER BY report_date ASC;"
        ),
    },
    {
        "id": "C2",
        "category": "Anomaly Diagnostics",
        "question": "How many total shipments experienced delay during the September 2025 typhoon window at HKG?",
        "sql": (
            "SELECT COUNT(DISTINCT l.shipment_id) AS impacted_shipments, "
            "       ROUND(AVG(l.delay_minutes), 1) AS avg_delay_minutes, "
            "       ROUND(MAX(l.delay_minutes), 1) AS max_delay_minutes "
            "FROM fact_shipment_legs l "
            "WHERE l.transport_mode = 'AIR' "
            "  AND l.origin_facility = 'HKG' "
            "  AND l.planned_depart_ts >= '2025-09-15T00:00:00Z' "
            "  AND l.planned_depart_ts <= '2025-09-21T23:59:59Z' "
            "  AND l.delay_minutes > 15;"
        ),
    },
    {
        "id": "C3",
        "category": "Anomaly Diagnostics",
        "question": "What was the average delay in hours for feeder sea legs departing Yantian (CNYTN) during March 2026?",
        "sql": (
            "SELECT COUNT(*) AS total_yantian_feeder_legs, "
            "       ROUND(AVG(delay_minutes) / 60.0, 1) AS avg_delay_hours, "
            "       ROUND(MIN(delay_minutes) / 60.0, 1) AS min_delay_hours, "
            "       ROUND(MAX(delay_minutes) / 60.0, 1) AS max_delay_hours "
            "FROM fact_shipment_legs "
            "WHERE transport_mode = 'SEA' "
            "  AND origin_facility = 'CNYTN' "
            "  AND planned_depart_ts >= '2026-03-01T00:00:00Z' "
            "  AND planned_depart_ts <= '2026-03-15T23:59:59Z';"
        ),
    },
    {
        "id": "C4",
        "category": "Anomaly Diagnostics",
        "question": "List all shipments originating in CNYTN in March 2026 that had a feeder delay exceeding 48 hours.",
        "sql": (
            "SELECT s.shipment_id, s.customer_id, s.destination_location, "
            "       l.origin_facility, l.planned_depart_ts, ROUND(l.delay_minutes / 60.0, 1) AS delay_hours, "
            "       s.status "
            "FROM dim_shipments s "
            "JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id "
            "WHERE l.transport_mode = 'SEA' "
            "  AND l.origin_facility = 'CNYTN' "
            "  AND l.planned_depart_ts >= '2026-03-01T00:00:00Z' "
            "  AND l.planned_depart_ts <= '2026-03-15T23:59:59Z' "
            "  AND l.delay_minutes > 2880 "
            "ORDER BY l.delay_minutes DESC;"
        ),
    },
    {
        "id": "C5",
        "category": "Anomaly Diagnostics",
        "question": "Show the monthly gross margin percentage for lane HKG-ORD across all of 2026.",
        "sql": (
            "SELECT strftime('%Y-%m', l.planned_depart_ts) AS month, "
            "       COUNT(DISTINCT s.shipment_id) AS shipments_count, "
            "       ROUND(SUM(s.contracted_revenue_usd), 2) AS total_revenue, "
            "       ROUND(SUM(s.actual_cost_usd), 2) AS total_cost, "
            "       ROUND(100.0 * (SUM(s.contracted_revenue_usd) - SUM(s.actual_cost_usd)) / SUM(s.contracted_revenue_usd), 2) AS gross_margin_pct "
            "FROM dim_shipments s "
            "JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id "
            "WHERE l.transport_mode = 'AIR' "
            "  AND l.origin_facility = 'HKG' "
            "  AND l.destination_facility = 'ORD' "
            "  AND l.planned_depart_ts >= '2026-01-01T00:00:00Z' "
            "  AND l.planned_depart_ts <= '2026-10-31T23:59:59Z' "
            "GROUP BY month "
            "ORDER BY month ASC;"
        ),
    },
    {
        "id": "C6",
        "category": "Anomaly Diagnostics",
        "question": "Identify all air shipments on route HKG-ORD in June 2026 where actual cost exceeded contracted revenue, and calculate the total financial loss.",
        "sql": (
            "SELECT COUNT(DISTINCT s.shipment_id) AS loss_making_shipment_count, "
            "       ROUND(SUM(s.contracted_revenue_usd), 2) AS total_revenue_usd, "
            "       ROUND(SUM(s.actual_cost_usd), 2) AS total_cost_usd, "
            "       ROUND(SUM(s.actual_cost_usd) - SUM(s.contracted_revenue_usd), 2) AS net_financial_loss_usd, "
            "       ROUND(100.0 * (SUM(s.contracted_revenue_usd) - SUM(s.actual_cost_usd)) / SUM(s.contracted_revenue_usd), 2) AS negative_margin_pct "
            "FROM dim_shipments s "
            "JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id "
            "WHERE l.transport_mode = 'AIR' "
            "  AND l.origin_facility = 'HKG' "
            "  AND l.destination_facility = 'ORD' "
            "  AND l.planned_depart_ts >= '2026-06-01T00:00:00Z' "
            "  AND l.planned_depart_ts <= '2026-06-30T23:59:59Z' "
            "  AND s.actual_cost_usd > s.contracted_revenue_usd;"
        ),
    },

    # ---------------- Group D: Customer & Lane Commercial Performance
    {
        "id": "D1",
        "category": "Customer & Lane Commercial Performance",
        "question": "Who are the top 10 customers by total freight volume (chargeable weight) and what is their corresponding gross margin?",
        "sql": (
            "SELECT c.customer_id, c.customer_name, c.industry_segment, "
            "       ROUND(SUM(s.total_chargeable_weight_kg) / 1000.0, 2) AS total_weight_tonnes, "
            "       ROUND(SUM(s.contracted_revenue_usd), 2) AS total_revenue_usd, "
            "       ROUND(100.0 * (SUM(s.contracted_revenue_usd) - SUM(s.actual_cost_usd)) / SUM(s.contracted_revenue_usd), 2) AS gross_margin_pct "
            "FROM dim_customers c "
            "JOIN dim_shipments s ON c.customer_id = s.customer_id "
            "GROUP BY c.customer_id, c.customer_name, c.industry_segment "
            "ORDER BY total_weight_tonnes DESC "
            "LIMIT 10;"
        ),
    },
    {
        "id": "D2",
        "category": "Customer & Lane Commercial Performance",
        "question": "Which customer industry segment has the highest delay rate across multimodal shipments?",
        "sql": (
            "SELECT c.industry_segment, "
            "       COUNT(*) AS total_shipments, "
            "       SUM(CASE WHEN s.status IN ('DELAYED', 'EXCEPTION') THEN 1 ELSE 0 END) AS delayed_shipments, "
            "       ROUND(100.0 * SUM(CASE WHEN s.status IN ('DELAYED', 'EXCEPTION') THEN 1 ELSE 0 END) / COUNT(*), 2) AS delay_rate_pct "
            "FROM dim_customers c "
            "JOIN dim_shipments s ON c.customer_id = s.customer_id "
            "GROUP BY c.industry_segment "
            "ORDER BY delay_rate_pct DESC;"
        ),
    },
    {
        "id": "D3",
        "category": "Customer & Lane Commercial Performance",
        "question": "Rank the top 5 air trade lanes by total revenue and show their average cargo yield per RTK.",
        "sql": (
            "SELECT k.route_lane, "
            "       ROUND(SUM(k.rtk_thousand * k.cargo_yield_per_rtk_usd * 1000.0), 2) AS estimated_revenue_usd, "
            "       ROUND(SUM(k.rtk_thousand * k.cargo_yield_per_rtk_usd) / SUM(k.rtk_thousand), 4) AS weighted_yield_usd_per_rtk, "
            "       ROUND(100.0 * SUM(k.rtk_thousand) / SUM(k.atk_thousand), 2) AS load_factor_pct "
            "FROM fact_air_kpi_daily k "
            "GROUP BY k.route_lane "
            "ORDER BY estimated_revenue_usd DESC "
            "LIMIT 5;"
        ),
    },
    {
        "id": "D4",
        "category": "Customer & Lane Commercial Performance",
        "question": "Which customer tier experienced the lowest multimodal delivery OTP in 2026?",
        "sql": (
            "WITH shipment_final_legs AS ("
            "  SELECT s.shipment_id, s.customer_id, l.actual_arrive_ts, l.planned_arrive_ts, "
            "         ROW_NUMBER() OVER (PARTITION BY s.shipment_id ORDER BY l.leg_sequence DESC) AS rn "
            "  FROM dim_shipments s "
            "  JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id "
            "  WHERE l.planned_depart_ts >= '2026-01-01T00:00:00Z' "
            ") "
            "SELECT c.tier, "
            "       COUNT(*) AS total_shipments_2026, "
            "       ROUND(100.0 * SUM(CASE WHEN (julianday(fl.actual_arrive_ts) - julianday(fl.planned_arrive_ts)) * 1440.0 <= 60 THEN 1 ELSE 0 END) / COUNT(*), 2) AS delivery_otp_pct "
            "FROM dim_customers c "
            "JOIN shipment_final_legs fl ON c.customer_id = fl.customer_id "
            "WHERE fl.rn = 1 "
            "GROUP BY c.tier "
            "ORDER BY delivery_otp_pct ASC;"
        ),
    },
    # ---------------- Group E: Sea & Road Mode Performance
    {
        "id": "E1",
        "category": "Sea & Road Mode Performance",
        "question": "How did the Yantian feeder corridor perform during the March 2026 congestion (weekly sailings and OTP)?",
        "sql": (
            "SELECT week_start_date, scheduled_sailings, completed_sailings, cancelled_sailings, "
            "       ROUND(on_time_departure_rate * 100.0, 1) AS departure_otp_pct, "
            "       ROUND(avg_transit_hours, 1) AS avg_transit_hours, "
            "       ROUND(backlog_teu, 0) AS backlog_teu "
            "FROM fact_sea_kpi_weekly "
            "WHERE feeder_corridor = 'YANTIAN_FEEDER_HKG' "
            "  AND week_start_date BETWEEN '2026-02-23' AND '2026-03-30' "
            "ORDER BY week_start_date ASC;"
        ),
    },
    {
        "id": "E2",
        "category": "Sea & Road Mode Performance",
        "question": "Which feeder corridor has the highest slot utilization and the lowest average transit time?",
        "sql": (
            "SELECT feeder_corridor, "
            "       ROUND(AVG(slot_utilization) * 100.0, 1) AS avg_slot_utilization_pct, "
            "       ROUND(AVG(avg_transit_hours), 1) AS avg_transit_hours, "
            "       ROUND(AVG(on_time_departure_rate) * 100.0, 1) AS avg_departure_otp_pct "
            "FROM fact_sea_kpi_weekly "
            "GROUP BY feeder_corridor "
            "ORDER BY avg_slot_utilization_pct DESC;"
        ),
    },
    {
        "id": "E3",
        "category": "Sea & Road Mode Performance",
        "question": "How did the Shenzhen Bay checkpoint perform during the November 2025 congestion compared to the other checkpoints?",
        "sql": (
            "SELECT checkpoint, "
            "       ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS arrival_otp_pct, "
            "       ROUND(AVG(avg_crossing_minutes), 0) AS avg_crossing_minutes, "
            "       ROUND(AVG(queue_backlog_trucks), 0) AS avg_queue_backlog_trucks "
            "FROM fact_truck_kpi_daily "
            "WHERE report_date BETWEEN '2025-11-10' AND '2025-11-24' "
            "GROUP BY checkpoint "
            "ORDER BY arrival_otp_pct ASC;"
        ),
    },
    {
        "id": "E4",
        "category": "Sea & Road Mode Performance",
        "question": "What is the daily truck OTP trend at Shenzhen Bay checkpoint around the November 2025 congestion window?",
        "sql": (
            "SELECT report_date, "
            "       ROUND(on_time_arrival_rate * 100.0, 1) AS arrival_otp_pct, "
            "       ROUND(avg_crossing_minutes, 0) AS avg_crossing_minutes, "
            "       ROUND(queue_backlog_trucks, 0) AS queue_backlog_trucks "
            "FROM fact_truck_kpi_daily "
            "WHERE checkpoint = 'SZBP' "
            "  AND report_date BETWEEN '2025-11-05' AND '2025-11-29' "
            "ORDER BY report_date ASC;"
        ),
    },
    {
        "id": "F1",
        "category": "Network & Shared Capacity",
        "question": "Which transport services are the most heavily loaded, by chargeable weight utilisation?",
        "sql": (
            "SELECT service_id, service_no, transport_mode, "
            "       origin_facility || '-' || destination_facility AS lane, "
            "       ROUND(100.0 * allocated_kg / NULLIF(capacity_chargeable_kg, 0), 1) AS load_pct, "
            "       (SELECT COUNT(DISTINCT shipment_id) FROM fact_allocations a "
            "        WHERE a.service_id = s.service_id) AS shipments "
            "FROM dim_transport_services s "
            "WHERE allocated_kg > 0 "
            "ORDER BY load_pct DESC LIMIT 20;"
        ),
    },
    {
        "id": "F2",
        "category": "Network & Shared Capacity",
        "question": "How many shipments were rolled over and for what reasons?",
        "sql": (
            "SELECT roll_reason, allocation_status, COUNT(*) AS n "
            "FROM fact_allocations "
            "WHERE allocation_status IN ('ROLLED', 'REACCOMMODATED') "
            "GROUP BY roll_reason, allocation_status "
            "ORDER BY n DESC;"
        ),
    },
    {
        "id": "F3",
        "category": "Network & Shared Capacity",
        "question": "Which shipments share the same flight as a given shipment on a lane to LAX?",
        "sql": (
            "SELECT a2.shipment_id, a2.priority_class, a2.allocated_weight_kg, "
            "       a2.allocation_status, s.service_no "
            "FROM fact_allocations a1 "
            "JOIN fact_allocations a2 ON a2.service_id = a1.service_id "
            "JOIN dim_transport_services s ON s.service_id = a1.service_id "
            "WHERE s.destination_facility = 'LAX' AND a2.shipment_id != a1.shipment_id "
            "ORDER BY a2.priority_class LIMIT 50;"
        ),
    },
]


def rank_few_shots(question: str, k: int = 3) -> list[Dict[str, str]]:
    """Rank few-shot examples against a question by df-weighted keyword overlap.

    Rare words (overall, network, typhoon, ...) dominate the score while common
    words (what, air, otp) barely count — plain overlap would match the wrong
    example whenever two questions share generic vocabulary.
    """
    import re

    catalog = FEW_SHOT_QUERY_CATALOG
    q_words = set(re.findall(r"[a-z]{3,}", question.lower()))
    tokenized = [set(re.findall(r"[a-z]{3,}", item["question"].lower())) for item in catalog]
    df: Dict[str, int] = {}
    for words in tokenized:
        for w in words:
            df[w] = df.get(w, 0) + 1

    def score(item_words: set) -> float:
        return sum(1.0 / df.get(w, 1) for w in q_words & item_words)

    ranked = sorted(zip(catalog, tokenized), key=lambda pair: score(pair[1]), reverse=True)
    return [item for item, _ in ranked[:k]]


def get_schema_context_prompt() -> str:
    """Generate markdown schema context describing tables, relationships and metrics for LLM system prompts."""
    lines = ["# Database Schema & Semantic Metrics Context\n"]
    lines.append("## Star-Schema Tables\n")
    for tbl_name, tbl_info in TABLE_CATALOG.items():
        lines.append(f"### `{tbl_name}`: {tbl_info['description']}")
        lines.append("| Column | Description |")
        lines.append("| :--- | :--- |")
        for col_name, col_desc in tbl_info["columns"].items():
            lines.append(f"| `{col_name}` | {col_desc} |")
        lines.append("")

    lines.append("## Core Logistics Metrics Reference\n")
    for metric_key, metric_info in METRIC_DEFINITIONS.items():
        lines.append(f"### {metric_info['name']} (`{metric_key}`)")
        lines.append(f"- **Description**: {metric_info['description']}")
        lines.append(f"- **Unit**: {metric_info['unit']}")
        lines.append(f"- **Formula**: `{metric_info['formula']}`")
        lines.append("```sql")
        lines.append(metric_info["canonical_sql"])
        lines.append("```\n")

    return "\n".join(lines)
