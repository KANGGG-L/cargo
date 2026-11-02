"""Subscription management and the notification outbox view/dispatch."""

import re
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import require_session
from app.config import get_settings
from app.notifications.outbox import dispatch_pending

router = APIRouter(
    prefix="/api/notifications",
    dependencies=[Depends(require_session)],
    tags=["notifications"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SubscriptionRequest(BaseModel):
    email: str = Field(max_length=120)
    shipment_id: str | None = Field(default=None, max_length=30)
    notify_on: str = Field(default="ALERT,DELAY,MISSING", max_length=60)
    delay_threshold_min: int = Field(default=120, ge=15, le=2880)
    channel: str = Field(default="email", pattern="^(email|webhook)$")


@router.post("/subscriptions")
def create_subscription(req: SubscriptionRequest):
    if not EMAIL_RE.match(req.email):
        raise HTTPException(status_code=422, detail="invalid email")
    if req.shipment_id is not None:
        conn = _conn()
        try:
            if not conn.execute(
                "SELECT 1 FROM dim_shipments WHERE shipment_id = ?", (req.shipment_id,)
            ).fetchone():
                raise HTTPException(status_code=404, detail="shipment not found")
        finally:
            conn.close()

    conn = _conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO dim_subscriptions (subscriber_email, shipment_id, notify_on,
                                           delay_threshold_min, channel, created_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (req.email, req.shipment_id, req.notify_on, req.delay_threshold_min,
             req.channel, _now()),
        )
        conn.commit()
        return {"id": cur.lastrowid, **req.model_dump()}
    finally:
        conn.close()


@router.get("/subscriptions")
def list_subscriptions():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM dim_subscriptions ORDER BY id DESC LIMIT 100"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: int):
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM dim_subscriptions WHERE id = ?", (sub_id,))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="subscription not found")
        return {"deleted": sub_id}
    finally:
        conn.close()


@router.get("/outbox")
def outbox(limit: int = Query(50, ge=1, le=200)):
    conn = _conn()
    try:
        rows = conn.execute(
            """
            SELECT o.*, s.subscriber_email FROM notification_outbox o
            JOIN dim_subscriptions s ON s.id = o.subscription_id
            ORDER BY o.id DESC LIMIT :limit
            """,
            {"limit": limit},
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("/dispatch")
def dispatch():
    sent = dispatch_pending()
    return {"dispatched": sent}
