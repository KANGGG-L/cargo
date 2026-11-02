"""Alert workbench API: rule sync, listing, and status transitions."""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import require_session
from app.config import get_settings
from app.milestones.rules import sync

router = APIRouter(
    prefix="/api/alerts",
    dependencies=[Depends(require_session)],
    tags=["alerts"])

VALID_TRANSITIONS = {
    "OPEN": {"ACKNOWLEDGED"},
    "ACKNOWLEDGED": {"RESOLVED", "CLOSED"},
    "RESOLVED": {"CLOSED"},
    "CLOSED": set(),
}


def _ro() -> sqlite3.Connection:
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/sync")
def sync_alerts():
    conn = _ro()
    try:
        result = sync(conn)
    finally:
        conn.close()

    from app.notifications.outbox import enqueue_for_alerts

    enqueued = enqueue_for_alerts(result.get("alerts", []))
    return {k: v for k, v in result.items() if k != "alerts"} | {"notifications_enqueued": enqueued}


@router.get("")
def list_alerts(
    status: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    conn = _ro()
    try:
        rows = conn.execute(
            """
            SELECT a.alert_id, a.shipment_id, a.rule_id, a.source, a.severity, a.title,
                   a.detail, a.status, a.created_ts, a.updated_ts, a.assignee,
                   a.resolution_note, s.transport_chain_type, s.destination_location,
                   CAST((julianday('now') - julianday(a.created_ts)) AS INTEGER) AS days_open
            FROM fact_alerts a
            JOIN dim_shipments s ON s.shipment_id = a.shipment_id
            WHERE (:status IS NULL OR a.status = :status)
              AND (:severity IS NULL OR a.severity = :severity)
            ORDER BY a.created_ts DESC, a.alert_id DESC
            LIMIT :limit
            """,
            {"status": status, "severity": severity, "limit": limit},
        ).fetchall()
        cols = [c[0] for c in conn.execute("SELECT * FROM fact_alerts LIMIT 0").description]
        extra = ["transport_chain_type", "destination_location", "days_open"]
        return [dict(zip(cols + extra, r)) for r in rows]
    finally:
        conn.close()


@router.get("/summary")
def alerts_summary():
    conn = _ro()
    try:
        by_status = dict(
            conn.execute("SELECT status, COUNT(*) FROM fact_alerts GROUP BY status").fetchall()
        )
        by_severity = dict(
            conn.execute(
                "SELECT severity, COUNT(*) FROM fact_alerts WHERE status = 'OPEN' GROUP BY severity"
            ).fetchall()
        )
        return {"by_status": by_status, "open_by_severity": by_severity}
    finally:
        conn.close()


class TransitionRequest(BaseModel):
    to: str = Field(pattern="^(ACKNOWLEDGED|RESOLVED|CLOSED)$")
    note: str | None = Field(default=None, max_length=500)
    assignee: str | None = Field(default=None, max_length=40)


@router.post("/{alert_id}/transition")
def transition_alert(alert_id: str, req: TransitionRequest):
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}")
    try:
        row = conn.execute(
            "SELECT status FROM fact_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="alert not found")
        current = row[0]
        if req.to not in VALID_TRANSITIONS.get(current, set()):
            raise HTTPException(
                status_code=409,
                detail=f"illegal transition {current} → {req.to}",
            )
        conn.execute(
            """
            UPDATE fact_alerts
            SET status = ?, updated_ts = ?,
                assignee = COALESCE(?, assignee),
                resolution_note = COALESCE(?, resolution_note)
            WHERE alert_id = ?
            """,
            (req.to, _now(), req.assignee, req.note, alert_id),
        )
        conn.commit()
        updated = conn.execute(
            "SELECT alert_id, status, updated_ts, assignee, resolution_note FROM fact_alerts WHERE alert_id = ?",
            (alert_id,),
        ).fetchone()
        return dict(zip(["alert_id", "status", "updated_ts", "assignee", "resolution_note"], updated))
    finally:
        conn.close()
