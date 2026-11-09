"""P2 network-level product tests (docs/NETWORK_UPGRADE_PLAN.md §5.3.6)."""

import asyncio
import os
import sqlite3

from fastapi.testclient import TestClient

from app.agent.extra_tools import (
    tool_capacity_impact,
    tool_manifest_lookup,
    tool_network_load,
    tool_reroute_options,
)
from app.agent.tools import get_tool_specs
from app.main import app

DB = os.environ["DB_PATH"]


def _client():
    return TestClient(app)


def _sql(q, *p):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return conn.execute(q, p).fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------- agent tools


def test_agent_has_network_tools():
    names = {s.name for s in get_tool_specs()}
    assert {"network_load", "capacity_impact", "reroute_options", "manifest_lookup"} <= names
    assert len(names) == 10


def test_network_load_tool():
    r = asyncio.run(tool_network_load("HKG"))
    assert r.payload["services"] > 0
    assert 0 <= r.payload["load_pct"] <= 100


def test_capacity_impact_priority_tiers():
    r = asyncio.run(tool_capacity_impact("typhoon_hkg_closure", 5, "des"))
    cdp = r.payload["clearance_day_by_priority"]
    assert "PHARMA" in cdp and "GENERAL" in cdp


def test_reroute_options_tool():
    sid = _sql(
        "SELECT a.shipment_id FROM fact_allocations a "
        "JOIN fact_shipment_legs l ON l.leg_id = a.leg_id "
        "WHERE l.transport_mode = 'AIR' LIMIT 1"
    )[0][0]
    r = asyncio.run(tool_reroute_options(sid))
    assert "options" in r.payload


def test_manifest_lookup_tool():
    svc = _sql("SELECT service_id FROM dim_ulds GROUP BY service_id LIMIT 1")[0][0]
    r = asyncio.run(tool_manifest_lookup(svc))
    assert r.payload["service_id"] == svc
    assert len(r.payload["ulds"]) > 0


def test_agent_whitelist_new_tables():
    from app.agent.safety import ALLOWED_TABLES

    assert {"dim_transport_services", "fact_allocations", "dim_ulds",
            "fact_event_log", "v_capacity_state"} <= ALLOWED_TABLES


# ---------------------------------------------------------------- alert clustering


def test_alert_clustering_and_bulk_transition():
    c = _client()
    cl = c.post("/api/alerts/cluster")
    assert cl.status_code == 200
    created = cl.json()["service_parents_created"]
    # list service-scope alerts
    grouped = c.get("/api/alerts", params={"group_by": "service"})
    assert grouped.status_code == 200
    if created > 0:
        parents = grouped.json()
        assert len(parents) >= 1
        pid = parents[0]["alert_id"]
        assert parents[0]["child_count"] >= 2
        bt = c.post(f"/api/alerts/{pid}/bulk-transition", json={"to": "ACKNOWLEDGED"})
        assert bt.status_code == 200
        assert bt.json()["transitioned"] >= 1


# ---------------------------------------------------------------- ETA service-awareness


def test_eta_service_aware_fields():
    """A freshly booked order gets planned legs bound to a service, and predict_eta
    surfaces expected_service_no + missed_cutoff_risk."""
    c = _client()
    cust = _sql("SELECT customer_id FROM dim_customers LIMIT 1")[0][0]
    r = c.post("/api/orders", json={
        "customer_id": cust, "origin_location": "CNYTN", "destination_location": "LAX",
        "transport_chain_type": "SEA_AIR_TRUCK", "cargo_category": "General",
        "total_chargeable_weight_kg": 500, "contracted_revenue_usd": 2350,
    })
    assert r.status_code == 200
    sid = r.json()["shipment_id"]
    # quote, allocate AWB, then book to generate planned legs
    c.post(f"/api/orders/{sid}/transition", json={"to": "QUOTED"})
    aw = c.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    assert aw.status_code == 200, aw.text
    bk = c.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert bk.status_code == 200, bk.text
    # planned air leg should carry a service_id
    svc = _sql(
        "SELECT service_id FROM fact_planned_legs WHERE shipment_id = ? AND transport_mode = 'AIR'",
        sid,
    )
    assert svc and svc[0][0] is not None, "air planned leg not bound to a service"
    eta = c.get(f"/api/orders/{sid}/eta")
    assert eta.status_code == 200
    air_legs = [l for l in eta.json()["legs"] if l["transport_mode"] == "AIR"]
    assert air_legs and air_legs[0]["expected_service_no"] is not None
    assert "missed_cutoff_risk" in air_legs[0]


# ---------------------------------------------------------------- mock plan v3


def test_mock_plan_network_scenario():
    from app.llm.mock import match_plan

    plan = match_plan("what is the capacity impact and how many shipments roll after the typhoon?")
    assert plan is not None
    assert plan["id"] == "network_capacity"
    assert plan["steps"][0]["tool"] == "capacity_impact"


def test_sankey_demand_vs_capacity():
    """§5.3.3 two-tone flow: links carry demand + capacity + utilisation, and a
    shared-service lane reports capacity headroom."""
    c = _client()
    r = c.get("/api/shipments/flows/sankey", params={"min_legs": 100})
    assert r.status_code == 200
    links = r.json()["links"]
    assert links
    for l in links:
        assert "demand_tonnes" in l and "capacity_tonnes" in l and "utilization_pct" in l
        assert l["value"] == l["demand_tonnes"]  # backward-compatible
    # at least one lane is backed by shared-service capacity with a real util%
    covered = [l for l in links if l["capacity_tonnes"]]
    assert covered, "no lane reported shared-service capacity"
    for l in covered:
        assert 0 <= l["utilization_pct"] <= 100.0
        assert abs(l["headroom_tonnes"] - (l["capacity_tonnes"] - l["demand_tonnes"])) < 0.2
