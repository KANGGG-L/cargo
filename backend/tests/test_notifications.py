"""F3 notification tests — self-contained: no cross-file state dependency.

Fan-out is exercised through enqueue_for_alerts directly with synthetic alerts;
subscription CRUD and dispatch semantics go through the API.
"""

import sqlite3
import uuid

from fastapi.testclient import TestClient

from app.config import get_settings
from app.notifications.outbox import enqueue_for_alerts


def _rw():
    return sqlite3.connect(get_settings().db_path)


def _client():
    from app.main import app

    return TestClient(app)


def _mk_alert(sid: str, severity: str = "high", kind: str = "DELAY") -> dict:
    return {
        "alert_id": f"AL-T{uuid.uuid4().hex[:6].upper()}",
        "shipment_id": sid,
        "rule_id": "R4" if kind == "DELAY" else "R2",
        "severity": severity,
        "title": f"Synthetic {kind} alert",
        "detail": "created by test_notifications",
        "event_kind": kind,
    }


def _sid() -> str:
    conn = _rw()
    try:
        return conn.execute("SELECT shipment_id FROM dim_shipments LIMIT 1").fetchone()[0]
    finally:
        conn.close()


def test_targeted_subscription_fans_out_and_dispatches():
    email = f"ops-{uuid.uuid4().hex[:8]}@demo.local"
    sid = _sid()
    client = _client()
    r = client.post(
        "/api/notifications/subscriptions",
        json={"email": email, "shipment_id": sid, "notify_on": "ALERT,DELAY,MISSING"},
    )
    assert r.status_code == 200
    sub_id = r.json()["id"]

    alert = _mk_alert(sid)
    assert enqueue_for_alerts([alert]) >= 1, "targeted subscription must enqueue"

    outbox = client.get("/api/notifications/outbox?limit=200").json()
    mine = [o for o in outbox if o["subscription_id"] == sub_id]
    assert mine and all(o["subscriber_email"] == email for o in mine)
    assert all(o["sent_ts"] is None for o in mine)
    assert any(o["shipment_id"] == sid for o in mine)

    assert client.post("/api/notifications/dispatch").json()["dispatched"] >= 1
    mine = [o for o in client.get("/api/notifications/outbox?limit=200").json()
            if o["subscription_id"] == sub_id]
    assert mine and all(o["sent_ts"] is not None for o in mine)

    # re-dispatch must not double-send (count only THIS subscription's rows —
    # the global outbox grows across runs and the limit-200 window slides)
    before = len([o for o in client.get("/api/notifications/outbox?limit=200").json()
                  if o["subscription_id"] == sub_id])
    client.post("/api/notifications/dispatch")
    after = len([o for o in client.get("/api/notifications/outbox?limit=200").json()
                 if o["subscription_id"] == sub_id])
    assert after == before

    client.delete(f"/api/notifications/subscriptions/{sub_id}")


def test_global_subscription_filters_low_severity():
    email = f"global-{uuid.uuid4().hex[:8]}@demo.local"
    client = _client()
    sub_id = client.post(
        "/api/notifications/subscriptions",
        json={"email": email, "shipment_id": None, "notify_on": "ALERT"},
    ).json()["id"]

    sid = _sid()
    high = _mk_alert(sid, severity="high")
    medium = _mk_alert(sid, severity="medium")
    enqueue_for_alerts([high, medium])

    rows = [o for o in client.get("/api/notifications/outbox?limit=200").json()
            if o["subscription_id"] == sub_id]
    assert rows, "high-severity alert must fan out to global subscription"
    assert all("HIGH" in o["subject"] for o in rows)
    assert not any(o["subject"].startswith("[HKG Cargo] MEDIUM") for o in rows)
    client.delete(f"/api/notifications/subscriptions/{sub_id}")


def test_other_shipment_alerts_do_not_leak_to_targeted_sub():
    email = f"solo-{uuid.uuid4().hex[:8]}@demo.local"
    conn = _rw()
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT shipment_id FROM dim_shipments LIMIT 2").fetchall()]
    finally:
        conn.close()
    sid, other = ids[0], ids[1]
    assert sid != other
    client = _client()
    sub_id = client.post(
        "/api/notifications/subscriptions",
        json={"email": email, "shipment_id": sid},
    ).json()["id"]

    enqueue_for_alerts([_mk_alert(other, severity="high")])

    rows = [o for o in client.get("/api/notifications/outbox?limit=200").json()
            if o["subscription_id"] == sub_id and o["shipment_id"] == other]
    assert not rows, "targeted subscription must not receive other shipments' alerts"
    client.delete(f"/api/notifications/subscriptions/{sub_id}")


def test_subscription_crud_and_invalid_email():
    client = _client()
    r = client.post(
        "/api/notifications/subscriptions",
        json={"email": "not-an-email"},
    )
    assert r.status_code == 422

    email = f"crud-{uuid.uuid4().hex[:8]}@demo.local"
    sub_id = client.post(
        "/api/notifications/subscriptions",
        json={"email": email, "shipment_id": None},
    ).json()["id"]
    listing = client.get("/api/notifications/subscriptions").json()
    assert any(s["id"] == sub_id for s in listing)
    assert client.delete(f"/api/notifications/subscriptions/{sub_id}").status_code == 200
    assert client.delete(f"/api/notifications/subscriptions/{sub_id}").status_code == 404
