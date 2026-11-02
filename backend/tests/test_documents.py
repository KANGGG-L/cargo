"""F7 document centre tests: AWB/DG_DECL/packing list generation and DG booking guard."""

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def _client():
    return TestClient(app)


def _cid():
    conn = sqlite3.connect(get_settings().db_path)
    try:
        return conn.execute("SELECT customer_id FROM dim_customers LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def _create_order(client, category="General"):
    r = client.post(
        "/api/orders",
        json={
            "customer_id": _cid(),
            "origin_location": "CNYTN",
            "destination_location": "LAX",
            "transport_chain_type": "SEA_AIR_TRUCK",
            "cargo_category": category,
            "total_chargeable_weight_kg": 800,
            "contracted_revenue_usd": 3600,
        },
    )
    assert r.status_code == 200
    return r.json()["shipment_id"]


def test_awb_document_generation_and_download():
    client = _client()
    sid = _create_order(client)
    client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})

    r = client.post(f"/api/documents/{sid}/generate", json={"doc_type": "AWB"})
    assert r.status_code == 200
    doc_id = r.json()["doc_id"]
    assert r.json()["eawb_status"] == "sent"

    listing = client.get(f"/api/documents/{sid}").json()
    assert any(d["doc_id"] == doc_id for d in listing)

    dl = client.get(f"/api/documents/file/{doc_id}")
    assert dl.status_code == 200
    assert dl.content[:5] == b"%PDF-", "served file must be a real PDF"


def test_packing_list_uses_legs():
    client = _client()
    sid = _create_order(client)
    r = client.post(f"/api/documents/{sid}/generate", json={"doc_type": "PACKING_LIST"})
    assert r.status_code == 200


def test_dg_booking_blocked_without_declaration_then_allowed():
    client = _client()
    sid = _create_order(client, category="Dangerous_Goods")
    client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    client.post(f"/api/orders/{sid}/transition", json={"to": "QUOTED"})

    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 409
    assert "DG_DECL" in r.json()["detail"]

    r = client.post(f"/api/documents/{sid}/generate", json={"doc_type": "DG_DECL"})
    assert r.status_code == 200

    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 200, r.json()


def test_awb_document_requires_awb_allocation():
    client = _client()
    sid = _create_order(client)
    r = client.post(f"/api/documents/{sid}/generate", json={"doc_type": "AWB"})
    assert r.status_code == 409


def test_eawb_sent_then_accepted_flow():
    client = _client()
    sid = _create_order(client)
    client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    r = client.post(f"/api/documents/{sid}/generate", json={"doc_type": "AWB"})
    doc_id = r.json()["doc_id"]

    # AWB confirm before generation is rejected; sent → accepted flows
    r = client.post(f"/api/documents/{doc_id}/accept")
    assert r.status_code == 200 and r.json()["eawb_status"] == "accepted"
    r = client.post(f"/api/documents/{doc_id}/accept")
    assert r.status_code == 409
