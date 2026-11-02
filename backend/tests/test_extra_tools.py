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


def test_diagnose_quiet_period_is_clean():
    result = asyncio.run(tool_diagnose_anomaly(scope="sea", anchor_date="2025-06-15"))
    assert result.payload["findings"] == [], "no sea anomalies were planted before 2026-03"


def test_simulation_is_deterministic_and_positive():
    a = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 48, 5))
    b = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 48, 5))
    assert a.payload == b.payload, "simulation must be deterministic"
    p = a.payload
    assert p["affected_air_legs"] > 0
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
