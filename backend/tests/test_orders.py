"""F5 order lifecycle tests: state machine guards, AWB allocation, RCS gate."""

import uuid

from fastapi.testclient import TestClient

from app.main import app


def _client():
    return TestClient(app)


def _customer_id() -> str:
    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(get_settings().db_path)
    try:
        return conn.execute("SELECT customer_id FROM dim_customers LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def _create_order(client, category="General"):
    r = client.post(
        "/api/orders",
        json={
            "customer_id": _customer_id(),
            "origin_location": "CNYTN",
            "destination_location": "LAX",
            "transport_chain_type": "SEA_AIR_TRUCK",
            "cargo_category": category,
            "total_chargeable_weight_kg": 500,
            "contracted_revenue_usd": 2350,
        },
    )
    assert r.status_code == 200
    return r.json()["shipment_id"]


def test_order_lifecycle_happy_path_with_guards():
    client = _client()
    sid = _create_order(client)

    # illegal: DRAFT → BOOKED directly
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 409

    # BOOKED requires AWB first
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "QUOTED"})
    assert r.status_code == 200
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 409

    # allocate AWB → BOOKED ok
    r = client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    assert r.status_code == 200
    awb_no = r.json()["awb_no"]
    assert awb_no.startswith("160-") and len(awb_no) == 12
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 200, r.json()

    # IN_PROGRESS requires RCS milestone
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "IN_PROGRESS"})
    assert r.status_code == 409, r.json()

    # inject RCS via ingest-format event
    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(get_settings().db_path)
    try:
        conn.execute(
            "INSERT INTO fact_milestone_events (shipment_id, leg_id, code, event_ts, source, dedupe_key)"
            " VALUES (?, NULL, 'RCS', '2026-11-03T10:00:00Z', 'agent', ?)",
            (sid, f"rcs-test-{uuid.uuid4().hex[:10]}"),
        )
        conn.commit()
    finally:
        conn.close()

    r = client.post(f"/api/orders/{sid}/transition", json={"to": "IN_PROGRESS"})
    assert r.status_code == 200, r.json()
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "COMPLETED"})
    assert r.status_code == 200, r.json()

    detail = client.get(f"/api/orders/{sid}").json()
    assert detail["current"] == "COMPLETED"
    assert detail["awb"]["awb_no"] == awb_no


def test_new_order_appears_in_shipments_and_network():
    client = _client()
    sid = _create_order(client)
    r = client.get("/api/shipments?limit=200")
    assert any(s["shipment_id"] == sid for s in r.json())


def test_duplicate_awb_rejected():
    client = _client()
    sid = _create_order(client)
    client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    r = client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    assert r.status_code == 409
