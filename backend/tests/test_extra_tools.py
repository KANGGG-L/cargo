"""Specialist tool tests — diagnose / simulate / quote on real synthetic data."""

import asyncio

from app.agent.extra_tools import (
    tool_diagnose_anomaly,
    tool_quote_booking,
    tool_simulate_disruption,
)


def test_diagnose_finds_typhoon_otp_collapse():
    result = asyncio.run(tool_diagnose_anomaly(scope="air", anchor_date="2025-09-25"))
    findings = result.payload["findings"]
    assert findings, "expected air OTP deviations around the typhoon window"
    assert any(f.get("otp_drop_pp", 0) > 8 for f in findings)
    assert any(e["event_code"] == "TYPHOON_2025_09" for e in result.payload["overlapping_events"])


def test_diagnose_finds_ord_margin_anomaly():
    result = asyncio.run(tool_diagnose_anomaly(scope="commercial", anchor_date="2026-06-25"))
    dests = {f.get("dest") for f in result.payload["findings"]}
    assert "ORD" in dests, f"ORD margin anomaly not detected: {dests}"


def test_diagnose_finds_szbp_checkpoint_congestion():
    result = asyncio.run(tool_diagnose_anomaly(scope="truck", anchor_date="2025-11-25"))
    findings = result.payload["findings"]
    assert findings, "expected truck OTP deviations around the SZBP congestion window"
    assert any(f.get("checkpoint") == "SZBP" and f.get("otp_drop_pp", 0) > 8 for f in findings)
    assert any(e["event_code"] == "SHENZHEN_BAY_CONGESTION_2025_11" for e in result.payload["overlapping_events"])


def test_sea_and_truck_kpi_tables_exist_and_are_balanced():
    """All three modes must have first-class KPI series, not just air."""
    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    try:
        sea_rows, truck_rows = conn.execute(
            "SELECT (SELECT COUNT(*) FROM fact_sea_kpi_weekly), (SELECT COUNT(*) FROM fact_truck_kpi_daily)"
        ).fetchone()
        assert sea_rows > 250, f"sea KPI weekly too thin: {sea_rows}"
        assert truck_rows > 1500, f"truck KPI daily too thin: {truck_rows}"
        # every mode has a story: 4 disruption events covering AIR/TRUCK/SEA/COMMERCIAL
        modes = {m for (m,) in conn.execute("SELECT affected_mode FROM fact_disruption_events")}
        assert {"AIR", "SEA", "TRUCK"} <= modes, f"mode coverage incomplete: {modes}"
    finally:
        conn.close()


def test_truck_kpi_szbp_congestion_window():
    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    try:
        spike, base = conn.execute(
            """
            SELECT
              (SELECT AVG(on_time_arrival_rate) FROM fact_truck_kpi_daily
                WHERE checkpoint='SZBP' AND report_date BETWEEN '2025-11-10' AND '2025-11-24'),
              (SELECT AVG(on_time_arrival_rate) FROM fact_truck_kpi_daily
                WHERE checkpoint='SZBP' AND report_date BETWEEN '2025-10-01' AND '2025-10-31')
            """
        ).fetchone()
        assert base > 0.85 and spike < 0.70, f"SZBP congestion not planted: {base} -> {spike}"
    finally:
        conn.close()


def test_simulate_border_congestion_is_deterministic():
    a = asyncio.run(tool_simulate_disruption("border_congestion_szbp", 72, 4))
    b = asyncio.run(tool_simulate_disruption("border_congestion_szbp", 72, 4))
    assert a.payload == b.payload
    p = a.payload
    assert p["mode"] == "TRUCK"
    assert p["affected_legs"] > 0 and p["recovery_curve"][-1]["backlog_tonnes"] == 0.0


def test_diagnose_quiet_period_is_clean():
    result = asyncio.run(tool_diagnose_anomaly(scope="sea", anchor_date="2025-06-15"))
    assert result.payload["findings"] == [], "no sea anomalies were planted before 2026-03"


def test_simulation_is_deterministic_and_positive():
    a = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 48, 5))
    b = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 48, 5))
    assert a.payload == b.payload, "simulation must be deterministic"
    p = a.payload
    assert p["affected_legs"] > 0
    assert p["backlog_tonnes"] > 0
    assert p["revenue_at_risk_musd"] > 0
    assert p["recovery_days"] >= 1
    assert p["recovery_curve"][0]["backlog_tonnes"] == p["backlog_tonnes"]
    assert p["recovery_curve"][-1]["backlog_tonnes"] == 0.0


def test_yantian_congestion_scenario_scales_with_severity():
    low = asyncio.run(tool_simulate_disruption("port_congestion_yantian", 48, 1))
    high = asyncio.run(tool_simulate_disruption("port_congestion_yantian", 48, 5))
    assert high.payload["avg_delay_hours"] > low.payload["avg_delay_hours"]
    assert high.payload["recovery_curve"][0]["backlog_tonnes"] >= low.payload["recovery_curve"][0]["backlog_tonnes"]


def test_quote_sea_air_chain_sums_legs():
    result = asyncio.run(tool_quote_booking("CNYTN", "LAX", 500, "auto"))
    p = result.payload
    modes = [leg["mode"] for leg in p["legs"]]
    assert modes == ["sea", "air"], f"expected sea+air chain, got {modes}"
    assert p["total_usd"] == round(sum(l["charge_usd"] for l in p["legs"]), 2)
    assert p["estimated_transit_days"] > 0
    assert all(l["avg_transit_days"] for l in p["legs"])


def test_quote_unknown_lane_reports_cleanly():
    result = asyncio.run(tool_quote_booking("CNYTN", "JNB", 500, "auto"))
    assert "error" in result.payload
