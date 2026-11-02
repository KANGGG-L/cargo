"""F6 portal auth + F8 settlement tests."""

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _client():
    return TestClient(app)


def test_login_and_customer_row_level_scope():
    client = _client()
    # wrong password rejected
    r = client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "wrong"})
    assert r.status_code == 401

    # customer login works, row-level scoping applies
    r = client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "demo1234"})
    assert r.status_code == 200
    assert r.json()["role"] == "customer"

    portal = client.get("/api/portal/shipments").json()
    assert portal["viewer"]["role"] == "customer"
    # CUST-001 owns no shipments in the synthetic data → empty scope, never leaks
    assert all(True for _ in portal["shipments"])
    conn = sqlite3.connect(get_settings().db_path)
    try:
        foreign = [
            s for s in portal["shipments"]
            if conn.execute(
                "SELECT customer_id FROM dim_shipments WHERE shipment_id = ?", (s["shipment_id"],)
            ).fetchone()[0] != "CUST-001"
        ]
    finally:
        conn.close()
    assert not foreign, "customer scope leaked other customers' shipments"


def test_unauthenticated_portal_rejected():
    r = _client().get("/api/portal/shipments")
    assert r.status_code == 401


def test_ops_sees_full_network():
    client = _client()
    client.post("/api/portal/login", json={"email": "ops@demo.local", "password": "demo1234"})
    portal = client.get("/api/portal/shipments").json()
    assert portal["viewer"]["role"] == "ops"
    assert len(portal["shipments"]) >= 50, "ops role sees the full network"


def _new_sid() -> str:
    """A shipment without an existing invoice (recycle the oldest if exhausted)."""
    conn = sqlite3.connect(get_settings().db_path)
    try:
        row = conn.execute(
            """
            SELECT s.shipment_id FROM dim_shipments s
            WHERE NOT EXISTS (SELECT 1 FROM fact_invoices i WHERE i.shipment_id = s.shipment_id)
            LIMIT 1
            """
        ).fetchone()
        if row:
            return row[0]
        oldest = conn.execute(
            "SELECT invoice_id, shipment_id FROM fact_invoices ORDER BY invoice_id LIMIT 1"
        ).fetchone()
        conn.execute("DELETE FROM fact_charge_lines WHERE shipment_id = ?", (oldest[1],))
        conn.execute("DELETE FROM fact_invoices WHERE invoice_id = ?", (oldest[0],))
        conn.commit()
        return oldest[1]
    finally:
        conn.close()


def test_settlement_charges_deterministic_and_invoice_lifecycle():
    client = _client()
    sid = _new_sid()

    c1 = client.post(f"/api/settlement/{sid}/charges").json()
    assert c1["total_usd"] > 0
    kinds = {l["charge_type"] for l in c1["lines"]}
    assert {"freight", "fuel", "thc"} <= kinds

    c2 = client.post(f"/api/settlement/{sid}/charges").json()
    assert c2["total_usd"] == c1["total_usd"], "charge computation must be deterministic"

    inv = client.post(f"/api/settlement/{sid}/invoice").json()
    assert inv["amount_usd"] == c1["total_usd"]

    r = client.post(f"/api/settlement/{sid}/invoice")
    assert r.status_code == 409, "duplicate invoice rejected"

    r = client.post(f"/api/settlement/invoice/{inv['invoice_id']}/pay")
    assert r.json()["status"] == "paid"
    r = client.post(f"/api/settlement/invoice/{inv['invoice_id']}/pay")
    assert r.status_code == 409
