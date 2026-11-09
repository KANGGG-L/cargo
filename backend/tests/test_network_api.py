"""P0 network API contract tests (§5.1.4).

Cross-checks the service / manifest / capacity endpoints against direct SQL so
the API provably agrees with the warehouse (the same check used at the UAT gate).
"""

import os
import sqlite3

from fastapi.testclient import TestClient

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


def test_services_list_matches_sql():
    c = _client()
    r = c.get("/api/network/services", params={"mode": "AIR", "limit": 50})
    assert r.status_code == 200
    body = r.json()
    assert len(body) > 0
    for row in body:
        assert row["transport_mode"] == "AIR"
        # load_factor is allocated/capacity and must be within [0, 1]
        assert 0.0 <= row["load_factor"] <= 1.0


def test_service_detail_breakdown():
    c = _client()
    # pick a service that actually carries cargo
    sid = _sql(
        "SELECT service_id FROM fact_allocations GROUP BY service_id "
        "ORDER BY COUNT(*) DESC LIMIT 1"
    )[0][0]
    r = c.get(f"/api/network/services/{sid}")
    assert r.status_code == 200
    body = r.json()
    assert body["service"]["service_id"] == sid
    sql_loaded = _sql(
        "SELECT COUNT(DISTINCT shipment_id) FROM fact_allocations "
        "WHERE service_id = ? AND allocation_status != 'ROLLED'", sid
    )[0][0]
    assert body["loaded_shipments"] == sql_loaded


def test_service_manifest():
    c = _client()
    sid = _sql(
        "SELECT service_id FROM dim_ulds GROUP BY service_id LIMIT 1"
    )[0][0]
    r = c.get(f"/api/network/services/{sid}/manifest")
    assert r.status_code == 200
    body = r.json()
    assert len(body["ulds"]) > 0


def test_service_not_found():
    assert _client().get("/api/network/services/SVC-NOPE/manifest").status_code == 404


def test_capacity_series():
    c = _client()
    r = c.get("/api/network/capacity", params={"mode": "AIR"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["utilization"]) > 0
    reasons = {x["roll_reason"] for x in body["rolled_by_reason"]}
    assert "DISRUPTION" in reasons or "CAPACITY" in reasons


def test_services_sort_by_load():
    """sort=load returns services ordered by descending load_factor (the fix for
    the capacity page showing an arbitrary 100-row window instead of the busiest
    services — caught in browser UAT)."""
    c = _client()
    r = c.get("/api/network/services", params={"mode": "AIR", "sort": "load", "limit": 10})
    assert r.status_code == 200
    body = r.json()
    loads = [row["load_factor"] for row in body]
    assert loads == sorted(loads, reverse=True), "sort=load not descending"
    # the top service must match the SQL-busiest AIR service
    top = _sql(
        "SELECT ROUND(allocated_kg / capacity_chargeable_kg, 4) FROM dim_transport_services "
        "WHERE transport_mode='AIR' AND capacity_chargeable_kg > 0 "
        "ORDER BY allocated_kg / capacity_chargeable_kg DESC LIMIT 1"
    )[0][0]
    assert abs(body[0]["load_factor"] - top) < 0.001


def test_trace_includes_service_and_coload():
    c = _client()
    # a shipment whose air leg is allocated to a shared service
    sid = _sql(
        "SELECT a.shipment_id FROM fact_allocations a "
        "JOIN fact_shipment_legs l ON l.leg_id = a.leg_id "
        "WHERE l.transport_mode = 'AIR' LIMIT 1"
    )[0][0]
    r = c.get(f"/api/shipments/{sid}/trace")
    assert r.status_code == 200
    legs = r.json()["legs"]
    air = [l for l in legs if l["transport_mode"] == "AIR"]
    assert air and air[0]["service_id"]
    assert air[0]["co_loaded_shipments"] is not None
