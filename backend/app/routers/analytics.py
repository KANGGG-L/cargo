"""BI analytics endpoints — pre-aggregated KPIs and chart-ready series.

All heavy aggregation happens in SQL against the star schema; the frontend
receives render-ready payloads.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """KPI cards for the control tower landing view."""
    kpi = db.execute(
        text(
            """
            WITH final_legs AS (
              SELECT shipment_id, actual_arrive_ts, planned_arrive_ts,
                     ROW_NUMBER() OVER (PARTITION BY shipment_id ORDER BY leg_sequence DESC) AS rn
              FROM fact_shipment_legs
            )
            SELECT
              (SELECT ROUND(100.0 * SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) / COUNT(*), 1)
                 FROM fact_shipment_legs WHERE transport_mode = 'AIR') AS air_otp_pct,
              (SELECT ROUND(100.0 * SUM(CASE WHEN (julianday(actual_arrive_ts) - julianday(planned_arrive_ts)) * 1440.0 <= 60 THEN 1 ELSE 0 END) / COUNT(*), 1)
                 FROM final_legs WHERE rn = 1) AS multimodal_otp_pct,
              (SELECT ROUND(100.0 * SUM(rtk_thousand) / SUM(atk_thousand), 1)
                 FROM fact_air_kpi_daily) AS load_factor_pct,
              (SELECT ROUND(AVG((julianday(air.actual_depart_ts) - julianday(feed.actual_arrive_ts)) * 24.0), 1)
                 FROM fact_shipment_legs feed
                 JOIN fact_shipment_legs air
                   ON feed.shipment_id = air.shipment_id
                  AND air.transport_mode = 'AIR' AND air.origin_facility = 'HKG'
                WHERE feed.destination_facility = 'HKG'
                  AND feed.leg_sequence < air.leg_sequence) AS avg_dwell_hours,
              (SELECT COUNT(*) FROM dim_shipments) AS total_shipments,
              (SELECT ROUND(SUM(total_chargeable_weight_kg) / 1000.0, 0) FROM dim_shipments) AS total_tonnes,
              (SELECT ROUND(SUM(contracted_revenue_usd) / 1000000.0, 2) FROM dim_shipments) AS total_revenue_musd,
              (SELECT ROUND(SUM(actual_cost_usd) / 1000000.0, 2) FROM dim_shipments) AS total_cost_musd,
              (SELECT ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 1)
                 FROM dim_shipments) AS gross_margin_pct
            """
        )
    ).mappings().one()

    disruptions = db.execute(
        text(
            """
            SELECT event_id, event_code, event_category, affected_mode,
                   start_timestamp, end_timestamp, primary_location, description
            FROM fact_disruption_events
            ORDER BY start_timestamp DESC
            LIMIT 3
            """
        )
    ).mappings().all()

    return {"kpis": dict(kpi), "recent_disruptions": [dict(d) for d in disruptions]}


@router.get("/trends")
def trends(db: Session = Depends(get_db)):
    """Daily air performance, monthly commercial results and weekly feeder rates."""
    daily = db.execute(
        text(
            """
            SELECT report_date AS date,
                   ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS air_otp_pct,
                   ROUND(100.0 * SUM(rtk_thousand) / SUM(atk_thousand), 1) AS load_factor_pct,
                   ROUND(AVG(backlog_tonnes), 0) AS backlog_tonnes
            FROM fact_air_kpi_daily
            GROUP BY report_date
            ORDER BY report_date
            """
        )
    ).mappings().all()

    monthly = db.execute(
        text(
            """
            SELECT strftime('%Y-%m', booking_ts) AS month,
                   COUNT(*) AS shipments,
                   ROUND(SUM(contracted_revenue_usd) / 1000000.0, 3) AS revenue_musd,
                   ROUND(SUM(actual_cost_usd) / 1000000.0, 3) AS cost_musd,
                   ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd))
                         / SUM(contracted_revenue_usd), 1) AS gross_margin_pct
            FROM dim_shipments
            GROUP BY month
            ORDER BY month
            """
        )
    ).mappings().all()

    rates = db.execute(
        text(
            """
            SELECT week_start_date AS week,
                   ROUND(MAX(CASE WHEN feeder_corridor = 'YANTIAN_FEEDER_HKG' THEN average_rate_per_feu_usd END), 0) AS yantian_feu,
                   ROUND(MAX(CASE WHEN feeder_corridor = 'PRD_FEEDER_HKG' THEN average_rate_per_feu_usd END), 0) AS prd_feu
            FROM fact_ocean_rate_weekly
            GROUP BY week_start_date
            ORDER BY week
            """
        )
    ).mappings().all()

    return {
        "daily": [dict(r) for r in daily],
        "monthly": [dict(r) for r in monthly],
        "weekly_rates": [dict(r) for r in rates],
    }


@router.get("/network")
def network(db: Session = Depends(get_db)):
    """Modal split, chain mix, top air lanes and feeder-port health."""
    mode_split = db.execute(
        text(
            """
            SELECT transport_mode AS mode, COUNT(*) AS legs,
                   ROUND(SUM(distance_km) / 1000.0, 0) AS thousand_km
            FROM fact_shipment_legs
            GROUP BY transport_mode
            """
        )
    ).mappings().all()

    chain_mix = db.execute(
        text(
            """
            SELECT transport_chain_type AS chain, COUNT(*) AS shipments,
                   ROUND(SUM(contracted_revenue_usd) / 1000000.0, 2) AS revenue_musd
            FROM dim_shipments
            GROUP BY transport_chain_type
            """
        )
    ).mappings().all()

    air_lanes = db.execute(
        text(
            """
            SELECT l.destination_facility AS dest,
                   COUNT(*) AS legs,
                   ROUND(SUM(s.total_chargeable_weight_kg) / 1000.0, 1) AS tonnes,
                   ROUND(SUM(s.contracted_revenue_usd) / 1000000.0, 2) AS revenue_musd,
                   ROUND(AVG(l.delay_minutes), 1) AS avg_delay_min
            FROM fact_shipment_legs l
            JOIN dim_shipments s ON l.shipment_id = s.shipment_id
            WHERE l.transport_mode = 'AIR' AND l.origin_facility = 'HKG'
            GROUP BY dest
            ORDER BY tonnes DESC
            """
        )
    ).mappings().all()

    feeder_ports = db.execute(
        text(
            """
            SELECT origin_facility AS port,
                   COUNT(*) AS legs,
                   ROUND(AVG(delay_minutes) / 60.0, 1) AS avg_delay_hours,
                   ROUND(100.0 * SUM(CASE WHEN delay_minutes <= 240 THEN 1 ELSE 0 END) / COUNT(*), 1) AS sea_otp_pct
            FROM fact_shipment_legs
            WHERE transport_mode = 'SEA' AND destination_facility = 'HKG'
            GROUP BY origin_facility
            ORDER BY legs DESC
            """
        )
    ).mappings().all()

    return {
        "mode_split": [dict(r) for r in mode_split],
        "chain_mix": [dict(r) for r in chain_mix],
        "air_lanes": [dict(r) for r in air_lanes],
        "feeder_ports": [dict(r) for r in feeder_ports],
    }
