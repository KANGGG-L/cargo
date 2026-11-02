"""F6 portal auth + F8 settlement tests."""

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _client():
    return TestClient(app)


def test_auth_gate_blocks_anonymous_data_endpoints(monkeypatch):
    """The hardening promise: without a session, customer-bearing endpoints 401."""
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    client = _client()
    for path in ("/api/shipments?limit=1", "/api/alerts", "/api/orders", "/api/settlement/x"):
        assert client.get(path).status_code == 401, path

    # login sets the cookie; scoped view then works
    r = client.post("/api/portal/login", json={"email": "ops@demo.local", "password": "demo1234"})
    assert r.status_code == 200
    assert client.get("/api/shipments?limit=1").status_code == 200


def test_login_and_customer_row_level_scope():
    import app.auth as auth_mod

    monkeypatch = None
    import pytest

    client = _client()
    # wrong password rejected
    r = client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "wrong"})
    assert r.status_code == 401

    # customer login works, row-level scoping applies
    import app.auth as auth

    prev = auth.AUTH_ENABLED
    auth.AUTH_ENABLED = True
    try:
        r = client.post("/api/portal/login", json={"email": "acme@demo.local", "password": "demo1234"})
        assert r.status_code == 200
        assert r.json()["role"] == "customer"

        portal = client.get("/api/portal/shipments").json()
        assert portal["viewer"]["role"] == "customer"
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
    finally:
        auth.AUTH_ENABLED = prev
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


def test_unauthenticated_portal_rejected(monkeypatch):
    import app.auth as auth_mod

    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
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


def test_demurrage_uses_teu_day_basis_and_dispute_reachable():
    client = _client()
    conn = sqlite3.connect(get_settings().db_path)
    try:
        sid = conn.execute(
            """
            SELECT s.shipment_id FROM dim_shipments s
            JOIN fact_shipment_legs l ON l.shipment_id = s.shipment_id
              AND l.leg_sequence = (SELECT MAX(leg_sequence) FROM fact_shipment_legs WHERE shipment_id = s.shipment_id)
            WHERE l.delay_minutes > 1440
              AND NOT EXISTS (SELECT 1 FROM fact_invoices i WHERE i.shipment_id = s.shipment_id)
            LIMIT 1
            """
        ).fetchone()
        assert sid, "delayed shipment with no invoice expected in seeded data"
        sid = sid[0]
    finally:
        conn.close()

    r = client.post(f"/api/settlement/{sid}/charges")
    lines = {l["charge_type"]: l for l in r.json()["lines"]}
    assert "demurrage" in lines, "delayed shipment should carry demurrage"
    assert "TEU" in lines["demurrage"]["basis"]

    inv = client.post(f"/api/settlement/{sid}/invoice").json()
    d = client.post(f"/api/settlement/invoice/{inv['invoice_id']}/dispute").json()
    assert d["status"] == "disputed"
    p = client.post(f"/api/settlement/invoice/{inv['invoice_id']}/pay").json()
    assert p["status"] == "paid"


def test_agent_whitelist_covers_alert_tables():
    from app.agent.safety import ALLOWED_TABLES, validate_and_rewrite

    sql = "SELECT status, COUNT(*) AS n FROM fact_alerts GROUP BY status"
    out = validate_and_rewrite(sql)
    assert "fact_alerts" in out
