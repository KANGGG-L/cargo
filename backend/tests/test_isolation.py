"""Row-level isolation + credential-hygiene regression tests (PM review batch).

Covers the fixes for: customer cross-tenant read/write on orders / documents /
settlement / alerts (ISS-02), password_hash exposure via /api/portal/me (ISS-05),
and the AR aging naive/aware datetime crash (ISS-04).
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _client():
    return TestClient(app)


@pytest.fixture()
def auth_on(monkeypatch):
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    return auth_mod


def _login(client: TestClient, email: str, password: str = "demo1234"):
    r = client.post("/api/portal/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()


def _mk_order(client: TestClient, customer_id: str) -> str:
    r = client.post(
        "/api/orders",
        json={
            "customer_id": customer_id,
            "origin_location": "HKG",
            "destination_location": "NRT",
            "transport_chain_type": "DIRECT_AIR",
            "total_chargeable_weight_kg": 100,
            "contracted_revenue_usd": 900,
        },
    )
    assert r.status_code == 200
    return r.json()["shipment_id"]


def test_me_response_has_no_password_hash(auth_on):
    client = _client()
    _login(client, "ops@demo.local")
    body = client.get("/api/portal/me").json()
    assert "password_hash" not in body
    assert body["email"] == "ops@demo.local"


def test_customer_orders_scoped_and_writes_blocked(auth_on):
    client = _client()
    _login(client, "ops@demo.local")
    own = _mk_order(client, "CUST-001")
    foreign = _mk_order(client, "CUST-002")

    client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "demo1234"})
    listed = client.get("/api/orders").json()
    ids = [o["shipment_id"] for o in listed]
    assert own in ids and foreign not in ids, "customer order list leaked another tenant"

    r = client.post(
        f"/api/orders/{foreign}/transition", json={"to": "CANCELLED", "note": "probe"}
    )
    assert r.status_code == 403, "customer must not transition a foreign order"
    r = client.post(f"/api/orders/{foreign}/awb", json={"airline_code": "CX"})
    assert r.status_code == 403
    r = client.post(
        "/api/orders",
        json={
            "customer_id": "CUST-002",
            "origin_location": "HKG",
            "destination_location": "NRT",
            "transport_chain_type": "DIRECT_AIR",
            "total_chargeable_weight_kg": 1,
            "contracted_revenue_usd": 1,
        },
    )
    assert r.status_code == 403, "customers are read-only on the workbench"
    # own order detail stays readable
    assert client.get(f"/api/orders/{own}").status_code == 200
    # foreign detail is out of scope
    assert client.get(f"/api/orders/{foreign}").status_code == 403


def test_customer_documents_settlement_alerts_scoped(auth_on):
    client = _client()
    _login(client, "ops@demo.local")
    foreign = _mk_order(client, "CUST-002")

    client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "demo1234"})
    assert client.get(f"/api/documents/{foreign}").status_code == 403
    assert client.post(
        f"/api/documents/{foreign}/generate", json={"doc_type": "PACKING_LIST"}
    ).status_code == 403
    assert client.get(f"/api/settlement/{foreign}").status_code == 403
    assert client.post(f"/api/settlement/{foreign}/charges").status_code == 403
    assert client.post(f"/api/settlement/{foreign}/invoice").status_code == 403
    assert client.get("/api/settlement/aging/summary").status_code == 403
    assert client.get("/api/shipments/flows/sankey").status_code == 403

    alerts = client.get("/api/alerts").json()
    assert alerts, "customer should still see alerts for own shipments"
    conn = sqlite3.connect(get_settings().db_path)
    try:
        leaked = [
            a
            for a in alerts
            if conn.execute(
                "SELECT customer_id FROM dim_shipments WHERE shipment_id = ?",
                (a["shipment_id"],),
            ).fetchone()[0]
            != "CUST-001"
        ]
    finally:
        conn.close()
    assert not leaked, "customer alert list leaked another tenant's alerts"


def test_ar_aging_returns_buckets(auth_on):
    """ISS-04: naive/aware subtraction crashed with a 500; buckets must render."""
    client = _client()
    _login(client, "ops@demo.local")
    r = client.get("/api/settlement/aging/summary")
    assert r.status_code == 200
    buckets = r.json()["buckets_usd"]
    assert set(buckets.keys()) == {"0-30", "31-60", "61-90", "90+"}


def test_ops_unaffected_after_isolation_changes(auth_on):
    client = _client()
    _login(client, "ops@demo.local")
    assert client.get("/api/orders").status_code == 200
    assert client.get("/api/shipments?limit=1").status_code == 200
    assert client.get("/api/alerts?limit=1").status_code == 200
    assert client.get("/api/shipments/flows/sankey?min_legs=100").status_code == 200
    sid = _mk_order(client, "CUST-002")
    assert client.post(f"/api/orders/{sid}/transition", json={"to": "CANCELLED"}).status_code == 200
