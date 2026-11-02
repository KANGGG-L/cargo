"""V1.0-B planned legs + empirical ETA tests."""

import asyncio
import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.agent.extra_tools import tool_predict_eta
from app.config import get_settings
from app.main import app
from app.tracking.eta import build_planned_legs, empirical_quantiles, predict_eta


def _client():
    return TestClient(app)


def _cid():
    conn = sqlite3.connect(get_settings().db_path)
    try:
        return conn.execute("SELECT customer_id FROM dim_customers LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def _booked_order(client, category="General"):
    r = client.post(
        "/api/orders",
        json={
            "customer_id": _cid(),
            "origin_location": "CNYTN",
            "destination_location": "LAX",
            "transport_chain_type": "SEA_AIR_TRUCK",
            "cargo_category": category,
            "total_chargeable_weight_kg": 500,
            "contracted_revenue_usd": 2350,
        },
    )
    assert r.status_code == 200
    sid = r.json()["shipment_id"]
    client.post(f"/api/orders/{sid}/awb", json={"airline_code": "CX"})
    client.post(f"/api/orders/{sid}/transition", json={"to": "QUOTED"})
    r = client.post(f"/api/orders/{sid}/transition", json={"to": "BOOKED"})
    assert r.status_code == 200, r.json()
    return sid


def test_booking_creates_multimodal_planned_chain():
    client = _client()
    sid = _booked_order(client)
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        legs = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM fact_planned_legs WHERE shipment_id = ? ORDER BY leg_sequence",
                (sid,),
            ).fetchall()
        ]
    finally:
        conn.close()
    modes = [l["transport_mode"] for l in legs]
    assert modes == ["SEA", "AIR", "TRUCK"], modes
    # chain temporality: each leg departs after the previous arrives
    for prev, nxt in zip(legs, legs[1:]):
        assert nxt["planned_depart_ts"] >= prev["planned_arrive_ts"]
    # hub dwell honored
    assert legs[1]["origin_facility"] == "HKG" and legs[1]["destination_facility"] == "LAX"


def test_eta_quantiles_ordered_and_tool_works():
    client = _client()
    sid = _booked_order(client)

    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        eta = predict_eta(conn, sid)
    finally:
        conn.close()
    assert eta is not None
    assert eta["eta_end_to_end_min"] > 0
    for leg in eta["legs"]:
        q = leg["delay_quantiles_min"]
        assert q["p50"] <= q["p80"] <= q["p95"]
    assert eta["legs"][0]["transport_mode"] == "SEA"

    result = asyncio.run(tool_predict_eta(sid))
    assert result.payload["shipment_id"] == sid
    assert "ETA prediction" in result.llm_digest


def test_eta_requires_booked_order():
    client = _client()
    r = client.post(
        "/api/orders",
        json={
            "customer_id": _cid(),
            "origin_location": "CNYTN",
            "destination_location": "LAX",
            "transport_chain_type": "DIRECT_AIR",
            "cargo_category": "General",
            "total_chargeable_weight_kg": 300,
            "contracted_revenue_usd": 1500,
        },
    )
    sid = r.json()["shipment_id"]  # stays DRAFT
    r = client.get(f"/api/orders/{sid}/eta")
    assert r.status_code == 409


def test_empirical_quantiles_fallback():
    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    try:
        q = empirical_quantiles(conn, "AIR", "HKG-LAX")
        assert q["sample"] > 0
        assert q["p50"] <= q["p80"] <= q["p95"]
    finally:
        conn.close()
