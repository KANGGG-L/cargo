"""Alert workbench API: rule sync, listing, and status transitions."""

import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth import require_session, require_write
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
def sync_alerts(request: Request):
    require_write(request)
    conn = _ro()
    try:
        result = sync(conn)
    finally:
        conn.close()

    from app.notifications.outbox import enqueue_for_alerts

    enqueued = enqueue_for_alerts(result.get("alerts", []))
    return {k: v for k, v in result.items() if k != "alerts"} | {"notifications_enqueued": enqueued}


@router.post("/cluster")
def cluster_alerts(request: Request):
    """Group OPEN shipment alerts by shared service into SERVICE-scope parents."""
    require_write(request)
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}")
    try:
        from app.milestones.rules import cluster_by_service

        return cluster_by_service(conn)
    finally:
        conn.close()


@router.get("")
def list_alerts(
    request: Request,
    status: str | None = Query(None),
    severity: str | None = Query(None),
    group_by: str | None = Query(None, description="service | None"),
    limit: int = Query(100, ge=1, le=500),
):
    user = require_session(request)
    conn = _ro()
    try:
        if group_by == "service":
            rows = conn.execute(
                """
                SELECT alert_id, shipment_id, severity, title, detail, status,
                       created_ts, due_ts, escalation_level,
                       (SELECT COUNT(*) FROM fact_alerts c WHERE c.parent_alert_id = a.alert_id) AS child_count
                FROM fact_alerts a
                WHERE a.alert_scope = 'SERVICE'
                  AND (:status IS NULL OR a.status = :status)
                ORDER BY child_count DESC, a.created_ts DESC
                LIMIT :limit
                """,
                {"status": status, "limit": limit},
            ).fetchall()
            cols = ["alert_id", "shipment_id", "severity", "title", "detail", "status",
                    "created_ts", "due_ts", "escalation_level", "child_count"]
            return [dict(zip(cols, r)) for r in rows]

        rows = conn.execute(
            """
            SELECT a.alert_id, a.shipment_id, a.rule_id, a.source, a.severity, a.title,
                   a.detail, a.status, a.created_ts, a.updated_ts, a.assignee,
                   a.resolution_note, a.alert_scope, a.parent_alert_id, a.due_ts,
                   a.escalation_level, s.transport_chain_type, s.destination_location,
                   CAST((julianday('now') - julianday(a.created_ts)) AS INTEGER) AS days_open
            FROM fact_alerts a
            JOIN dim_shipments s ON s.shipment_id = a.shipment_id
            WHERE (:status IS NULL OR a.status = :status)
              AND (:severity IS NULL OR a.severity = :severity)
              AND (:customer IS NULL OR s.customer_id = :customer)
            ORDER BY a.created_ts DESC, a.alert_id DESC
            LIMIT :limit
            """,
            {
                "status": status,
                "severity": severity,
                "limit": limit,
                "customer": user.get("customer_id") if user.get("role") == "customer" else None,
            },
        ).fetchall()
        cols = ["alert_id", "shipment_id", "rule_id", "source", "severity", "title",
                "detail", "status", "created_ts", "updated_ts", "assignee",
                "resolution_note", "alert_scope", "parent_alert_id", "due_ts",
                "escalation_level", "transport_chain_type", "destination_location", "days_open"]
        return [dict(zip(cols, r)) for r in rows]
    finally:
        conn.close()


@router.get("/summary")
def alerts_summary(request: Request):
    user = require_session(request)
    customer = user.get("customer_id") if user.get("role") == "customer" else None
    conn = _ro()
    try:
        by_status = dict(
            conn.execute(
                """SELECT a.status, COUNT(*) FROM fact_alerts a
                   JOIN dim_shipments s ON s.shipment_id = a.shipment_id
                   WHERE (:customer IS NULL OR s.customer_id = :customer)
                   GROUP BY a.status""",
                {"customer": customer},
            ).fetchall()
        )
        by_severity = dict(
            conn.execute(
                """SELECT a.severity, COUNT(*) FROM fact_alerts a
                   JOIN dim_shipments s ON s.shipment_id = a.shipment_id
                   WHERE a.status = 'OPEN' AND (:customer IS NULL OR s.customer_id = :customer)
                   GROUP BY a.severity""",
                {"customer": customer},
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
def transition_alert(alert_id: str, req: TransitionRequest, request: Request):
    require_write(request)
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


class BulkTransitionRequest(BaseModel):
    to: str = Field(pattern="^(ACKNOWLEDGED|RESOLVED|CLOSED)$")
    note: str | None = Field(default=None, max_length=500)
    assignee: str | None = Field(default=None, max_length=40)


@router.post("/{alert_id}/bulk-transition")
def bulk_transition(alert_id: str, req: BulkTransitionRequest, request: Request):
    """Transition a SERVICE-scope parent and every child alert in one action."""
    require_write(request)
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}")
    try:
        parent = conn.execute(
            "SELECT status, alert_scope FROM fact_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()
        if parent is None:
            raise HTTPException(status_code=404, detail="alert not found")
        if parent[1] != "SERVICE":
            raise HTTPException(status_code=400, detail="bulk-transition is for SERVICE-scope alerts")

        # affected = parent + children, restricted to legal transitions
        targets = conn.execute(
            "SELECT alert_id, status FROM fact_alerts "
            "WHERE alert_id = ? OR parent_alert_id = ?",
            (alert_id, alert_id),
        ).fetchall()
        changed = 0
        for aid, cur in targets:
            if req.to in VALID_TRANSITIONS.get(cur, set()):
                conn.execute(
                    "UPDATE fact_alerts SET status = ?, updated_ts = ?, "
                    "assignee = COALESCE(?, assignee), resolution_note = COALESCE(?, resolution_note) "
                    "WHERE alert_id = ?",
                    (req.to, _now(), req.assignee, req.note, aid),
                )
                changed += 1
        conn.commit()
        return {"parent": alert_id, "to": req.to, "transitioned": changed, "total_in_cluster": len(targets)}
    finally:
        conn.close()
