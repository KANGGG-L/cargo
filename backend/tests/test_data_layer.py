"""Automated test suite for Phase 1 Data Layer & Semantic Engine."""

import sqlite3
from pathlib import Path
import pytest
from app.config import get_settings
from app.semantic_layer import (
    FEW_SHOT_QUERY_CATALOG,
    METRIC_DEFINITIONS,
    TABLE_CATALOG,
)

settings = get_settings()
ROOT_DIR = Path(__file__).resolve().parents[2]
PUBLIC_DIR = ROOT_DIR / "data" / "public"
SYNTHETIC_DIR = ROOT_DIR / "data" / "synthetic"
DB_PATH = settings.db_path


@pytest.fixture(scope="module")
def db_conn():
    assert DB_PATH.exists(), f"Database does not exist at {DB_PATH}"
    conn = sqlite3.connect(DB_PATH)
    yield conn
    conn.close()


def test_public_macro_files_exist():
    hkg_file = PUBLIC_DIR / "hkg_air_cargo_monthly.csv"
    scfi_file = PUBLIC_DIR / "scfi_ocean_rate_weekly.csv"

    assert hkg_file.exists(), "hkg_air_cargo_monthly.csv missing"
    assert scfi_file.exists(), "scfi_ocean_rate_weekly.csv missing"

    with open(hkg_file, "r", encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
        assert len(lines) == 35, f"Expected 34 rows + header, got {len(lines)}"

    with open(scfi_file, "r", encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#") and l.strip()]
        assert len(lines) == 149, f"Expected 148 rows + header, got {len(lines)}"


def test_synthetic_files_exist():
    expected_files = [
        "dim_customers.csv",
        "dim_shipments.csv",
        "fact_shipment_legs.csv",
        "fact_air_kpi_daily.csv",
        "fact_ocean_rate_weekly.csv",
        "fact_rate_cards.csv",
        "fact_disruption_events.csv",
    ]
    for fn in expected_files:
        p = SYNTHETIC_DIR / fn
        assert p.exists(), f"Synthetic file {fn} missing"


def test_assertion_1_shipment_and_leg_scale(db_conn):
    cursor = db_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM dim_shipments")
    total_shipments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM fact_shipment_legs")
    total_legs = cursor.fetchone()[0]

    assert 7500 <= total_shipments <= 8500, f"Total shipments out of range: {total_shipments}"
    assert 18000 <= total_legs <= 22000, f"Total legs out of range: {total_legs}"


def test_assertion_2_typhoon_anomaly(db_conn):
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT 
          COUNT(*) as typhoon_air_legs,
          ROUND(100.0 * SUM(CASE WHEN ABS(delay_minutes) <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS air_otp_pct
        FROM fact_shipment_legs
        WHERE transport_mode = 'AIR'
          AND origin_facility = 'HKG'
          AND planned_depart_ts >= '2025-09-15T00:00:00Z'
          AND planned_depart_ts <= '2025-09-21T23:59:59Z';
        """
    )
    row = cursor.fetchone()
    count = row[0]
    air_otp_pct = row[1]

    assert count > 0, "No air legs found in typhoon window"
    assert air_otp_pct < 50.0, f"Typhoon OTP did not drop below 50%: {air_otp_pct}%"


def test_assertion_3_yantian_congestion_anomaly(db_conn):
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT 
          COUNT(*) as sea_legs_cnt,
          ROUND(AVG(delay_minutes), 1) as avg_delay_min
        FROM fact_shipment_legs
        WHERE transport_mode = 'SEA'
          AND origin_facility = 'CNYTN'
          AND planned_depart_ts >= '2026-03-01T00:00:00Z'
          AND planned_depart_ts <= '2026-03-15T23:59:59Z';
        """
    )
    row = cursor.fetchone()
    count = row[0]
    avg_delay_min = row[1]

    assert count > 0, "No sea legs found in Yantian congestion window"
    assert avg_delay_min > 3000.0, f"Yantian delay did not exceed 3000 min: {avg_delay_min}"


def test_assertion_4_negative_margin_anomaly(db_conn):
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT 
          COUNT(*) as shipment_cnt,
          ROUND(SUM(contracted_revenue_usd), 2) as total_rev,
          ROUND(SUM(actual_cost_usd), 2) as total_cost,
          ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 2) as margin_pct
        FROM dim_shipments s
        JOIN fact_shipment_legs l ON s.shipment_id = l.shipment_id
        WHERE l.transport_mode = 'AIR'
          AND l.origin_facility = 'HKG'
          AND l.destination_facility = 'ORD'
          AND l.planned_depart_ts >= '2026-06-01T00:00:00Z'
          AND l.planned_depart_ts <= '2026-06-30T23:59:59Z';
        """
    )
    row = cursor.fetchone()
    count = row[0]
    total_rev = row[1]
    total_cost = row[2]
    margin_pct = row[3]

    assert count > 0, "No shipments found for HKG-ORD in June 2026"
    assert total_cost > total_rev, f"Total cost not greater than rev: {total_cost} vs {total_rev}"
    assert margin_pct < 0.0, f"Gross margin is not negative: {margin_pct}%"


def test_assertion_5_referential_integrity(db_conn):
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) as orphan_legs_count
        FROM fact_shipment_legs l
        LEFT JOIN dim_shipments s ON l.shipment_id = s.shipment_id
        WHERE s.shipment_id IS NULL;
        """
    )
    orphan_count = cursor.fetchone()[0]
    assert orphan_count == 0, f"Orphan legs found: {orphan_count}"


def test_no_negative_hub_dwell(db_conn):
    """Air legs must never depart before the inbound feeder physically arrives."""
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*) FROM fact_shipment_legs feed
        JOIN fact_shipment_legs air
          ON feed.shipment_id = air.shipment_id
         AND air.transport_mode = 'AIR' AND air.origin_facility = 'HKG'
        WHERE feed.destination_facility = 'HKG'
          AND feed.leg_sequence < air.leg_sequence
          AND julianday(air.actual_depart_ts) < julianday(feed.actual_arrive_ts);
        """
    )
    negative_dwell = cursor.fetchone()[0]
    assert negative_dwell == 0, f"{negative_dwell} air legs depart before feeder arrival (negative dwell)"


def test_shipment_status_distribution_is_plausible(db_conn):
    """With a 1 h end-to-end tolerance most historical shipments should be DELIVERED."""
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT status, COUNT(*) FROM dim_shipments GROUP BY status"
    )
    counts = dict(cursor.fetchall())
    total = sum(counts.values())
    delivered_share = counts.get("DELIVERED", 0) / total
    assert delivered_share >= 0.55, f"DELIVERED share too low: {delivered_share:.0%} ({counts})"


def test_yantian_congestion_spikes_feeder_rates(db_conn):
    """Congestion window must show visibly higher feeder spot rates than baseline."""
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT ROUND(AVG(CASE WHEN week_start_date BETWEEN '2026-03-01' AND '2026-03-15'
                              THEN average_rate_per_feu_usd END), 1) AS spike_avg,
               ROUND(AVG(CASE WHEN week_start_date BETWEEN '2026-02-01' AND '2026-02-21'
                              THEN average_rate_per_feu_usd END), 1) AS baseline_avg
        FROM fact_ocean_rate_weekly
        WHERE feeder_corridor = 'YANTIAN_FEEDER_HKG';
        """
    )
    spike, baseline = cursor.fetchone()
    assert spike is not None and baseline is not None
    assert spike > baseline * 1.25, f"Congestion spike too small: {baseline} -> {spike}"


def test_ord_yield_dips_during_pricing_error(db_conn):
    """HKG-ORD yield must collapse below the network baseline in June 2026."""
    cursor = db_conn.cursor()
    cursor.execute(
        """
        SELECT ROUND(AVG(CASE WHEN route_lane = 'HKG-ORD'
                               AND report_date BETWEEN '2026-06-01' AND '2026-06-30'
                              THEN cargo_yield_per_rtk_usd END), 3) AS ord_jun,
               ROUND(AVG(cargo_yield_per_rtk_usd), 3) AS network_avg
        FROM fact_air_kpi_daily;
        """
    )
    ord_jun, network_avg = cursor.fetchone()
    assert ord_jun is not None
    assert ord_jun < network_avg * 0.65, f"ORD yield not depressed: {ord_jun} vs network {network_avg}"


def test_semantic_layer_metrics(db_conn):
    cursor = db_conn.cursor()
    assert len(METRIC_DEFINITIONS) == 8, f"Expected 8 metrics, got {len(METRIC_DEFINITIONS)}"
    for key, metric in METRIC_DEFINITIONS.items():
        sql = metric["canonical_sql"]
        cursor.execute(sql)
        row = cursor.fetchone()
        assert row is not None, f"Metric query {key} returned None"
        assert row[0] is not None, f"Metric value {key} is None"


def test_semantic_layer_few_shot_queries(db_conn):
    cursor = db_conn.cursor()
    assert len(FEW_SHOT_QUERY_CATALOG) >= 20, f"Expected >= 20 queries, got {len(FEW_SHOT_QUERY_CATALOG)}"
    for item in FEW_SHOT_QUERY_CATALOG:
        sql = item["sql"]
        cursor.execute(sql)
        res = cursor.fetchall()
        assert res is not None, f"Query {item['id']} execution failed"
