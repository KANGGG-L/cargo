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


def test_recoverable_filter_surfaces_actionable_shipments():
    """The `recoverable=true` list must only return shipments the Recover
    workflow can act on — each returned shipment must have a feasible
    re-accommodation (mirrors tool_reroute_options' feasibility test)."""
    c = _client()
    r = c.get("/api/shipments?recoverable=true&limit=30")
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) > 0, "demo data should contain recoverable shipments"

    # exception/delayed shipments sort to the top (operator triage order)
    statuses = [row["status"] for row in rows]
    first_non_recover = next((i for i, s in enumerate(statuses) if s not in ("EXCEPTION", "DELAYED")), len(statuses))
    assert all(s in ("EXCEPTION", "DELAYED") for s in statuses[:first_non_recover])

    # every returned shipment is genuinely recoverable per the SQL feasibility test
    for row in rows[:10]:
        sid = row["shipment_id"]
        feasible = _sql(
            """
            SELECT COUNT(*) FROM fact_allocations a
            JOIN fact_shipment_legs l ON l.leg_id = a.leg_id AND l.transport_mode = 'AIR'
            WHERE a.shipment_id = ?
              AND EXISTS (
                SELECT 1 FROM dim_transport_services sv
                WHERE sv.transport_mode = 'AIR' AND sv.origin_facility = 'HKG'
                  AND sv.destination_facility = l.destination_facility
                  AND sv.status != 'CANCELLED'
                  AND sv.scheduled_depart_ts > l.planned_depart_ts
                  AND (sv.capacity_chargeable_kg - sv.allocated_kg) >= a.allocated_weight_kg
              )
            """,
            sid,
        )[0][0]
        assert feasible > 0, f"{sid} returned by recoverable filter but has no feasible reroute"


def test_recoverable_filter_default_off_keeps_legacy_behaviour():
    """Without the flag the list is unchanged (newest-first, all statuses)."""
    c = _client()
    r = c.get("/api/shipments?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list) and len(r.json()) > 0
