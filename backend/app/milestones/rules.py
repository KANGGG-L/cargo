"""Milestone rule engine: plan vs actual deviations → exception alerts.

Deterministic and idempotent — the same database state always produces the
same alert set; already-open tickets are never duplicated or reset.
"""

import sqlite3
from typing import Any

from app.config import get_settings

# Bounds keep the demo workbench usable while staying deterministic.
RECENT_WINDOW_DAYS = 120
MAX_ALERTS_PER_RULE = 300


def _ro() -> sqlite3.Connection:
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _horizon(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT strftime('%Y-%m-%dT12:00:00Z', MAX(report_date)) FROM fact_air_kpi_daily"
    ).fetchone()[0]


def evaluate_rule_meta(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {"rule_id": r[0], "name": r[1], "rule_type": r[2], "code": r[3],
         "threshold_minutes": r[4], "severity": r[5]}
        for r in conn.execute(
            "SELECT rule_id, name, rule_type, code, threshold_minutes, severity FROM fact_alert_rules"
        ).fetchall()
    ]


def _next_alert_id(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT MAX(alert_id) FROM fact_alerts").fetchone()[0]
    n = int(row.split("-")[1]) + 1 if row else 1
    return f"AL-{n:06d}"


def evaluate(conn: sqlite3.Connection, now: str) -> dict[str, list[dict[str, Any]]]:
    """Pure evaluation: rule_id -> candidate alerts (no writes)."""
    rules = conn.execute(
        "SELECT rule_id, name, rule_type, code, threshold_minutes, severity FROM fact_alert_rules"
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {}

    for rule_id, name, rtype, code, threshold, severity in rules:
        if rtype == "missing_event":
            rows = conn.execute(
                """
                SELECT p.shipment_id, p.planned_ts, s.destination_location
                FROM fact_milestones_plan p
                JOIN dim_shipments s ON s.shipment_id = p.shipment_id
                WHERE p.code = :code
                  AND p.planned_ts <= :cut
                  AND NOT EXISTS (
                    SELECT 1 FROM fact_milestone_events e
                    WHERE e.shipment_id = p.shipment_id AND e.code = p.code
                      AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
                  )
                ORDER BY p.planned_ts DESC
                LIMIT :cap
                """,
                {"code": code, "cut": f"{now[:10]}", "cap": MAX_ALERTS_PER_RULE},
            ).fetchall()
            out[rule_id] = [
                {
                    "shipment_id": r[0],
                    "rule_id": rule_id,
                    "severity": severity,
                    "title": f"{code} milestone missing — {name}",
                    "detail": (
                        f"Planned {code} at {r[1]} never reported (threshold "
                        f"{threshold} min). Destination {r[2]}."
                    ),
                }
                for r in rows
            ]
        else:  # delay_over: actual event later than plan by more than threshold
            rows = conn.execute(
                """
                SELECT p.shipment_id, p.planned_ts, e.event_ts, s.destination_location,
                       ROUND((julianday(e.event_ts) - julianday(p.planned_ts)) * 1440.0, 0) AS delay_min
                FROM fact_milestones_plan p
                JOIN fact_milestone_events e
                  ON e.shipment_id = p.shipment_id AND e.code = p.code
                 AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
                JOIN dim_shipments s ON s.shipment_id = p.shipment_id
                WHERE p.code = :code
                  AND (julianday(e.event_ts) - julianday(p.planned_ts)) * 1440.0 > :threshold
                  AND p.planned_ts >= DATE(:cut, '-{win} days')
                ORDER BY p.planned_ts DESC
                LIMIT :cap
                """.format(win=RECENT_WINDOW_DAYS),
                {"code": code, "threshold": threshold, "cut": f"{now[:10]}", "cap": MAX_ALERTS_PER_RULE},
            ).fetchall()
            out[rule_id] = [
                {
                    "shipment_id": r[0],
                    "rule_id": rule_id,
                    "severity": severity,
                    "title": f"{code} delayed {int(r[4])} min — {name}",
                    "detail": (
                        f"Planned {r[1]}, reported {r[2]} (+{int(r[4])} min, threshold "
                        f"{threshold}). Destination {r[3]}."
                    ),
                }
                for r in rows
            ]
    return out


def sync(conn: sqlite3.Connection) -> dict[str, Any]:
    """Evaluate rules and upsert OPEN alerts. Idempotent across re-runs."""
    now = _horizon(conn)
    candidates = evaluate(conn, now)
    existing = {
        (r[0], r[1]) for r in conn.execute(
            "SELECT shipment_id, rule_id FROM fact_alerts WHERE source = 'rules'"
        )
    }
    next_num = int((conn.execute("SELECT MAX(alert_id) FROM fact_alerts").fetchone()[0] or "AL-000000").split("-")[1]) + 1

    created = 0
    created_alerts: list[dict[str, Any]] = []
    inserts = []
    for rule_id in sorted(candidates):
        rule_meta = next(
            r for r in evaluate_rule_meta(conn) if r["rule_id"] == rule_id
        )
        for cand in candidates[rule_id]:
            key = (cand["shipment_id"], rule_id)
            if key in existing:
                continue
            existing.add(key)
            alert_id = f"AL-{next_num:06d}"
            inserts.append(
                (
                    alert_id,
                    cand["shipment_id"],
                    cand["rule_id"],
                    "rules",
                    cand["severity"],
                    cand["title"],
                    cand["detail"],
                    "OPEN",
                    now,
                    now,
                    _due_from(now, cand["severity"]),
                )
            )
            created_alerts.append(
                {
                    "alert_id": alert_id,
                    "shipment_id": cand["shipment_id"],
                    "rule_id": rule_id,
                    "severity": cand["severity"],
                    "title": cand["title"],
                    "detail": cand["detail"],
                    "event_kind": "MISSING" if rule_meta["rule_type"] == "missing_event" else "DELAY",
                }
            )
            next_num += 1
            created += 1

    conn.execute("PRAGMA query_only = OFF")
    conn.executemany(
        """
        INSERT INTO fact_alerts (alert_id, shipment_id, rule_id, source, severity,
                                 title, detail, status, created_ts, updated_ts, due_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    conn.commit()
    open_count = conn.execute("SELECT COUNT(*) FROM fact_alerts WHERE status = 'OPEN'").fetchone()[0]
    return {"created": created, "open_total": open_count, "alerts": created_alerts}


# SLA hours by severity — overdue escalation driver (P2)
SLA_HOURS = {"high": 4, "medium": 12, "info": 48}

# Escalation ceiling: L0 (fresh) → L3 (exec). Each breach bumps a level and
# pushes due_ts out by the SLA window again.
MAX_ESCALATION_LEVEL = 3


def _due_from(now: str, severity: str) -> str | None:
    """Initial due timestamp = now + SLA window for the severity."""
    hours = SLA_HOURS.get(severity)
    if hours is None:
        return None
    from datetime import datetime, timedelta

    base = datetime.strptime(now[:19], "%Y-%m-%dT%H:%M:%S")
    return (base + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def escalate(conn: sqlite3.Connection, now: str) -> dict[str, Any]:
    """Advance escalation_level on OPEN/ACK alerts whose due_ts has passed.

    Each escalation bumps the level (capped at MAX_ESCALATION_LEVEL) and pushes
    due_ts out by the SLA window so the same breach is not counted twice within
    one window (idempotent per window). L2+ emits a notification.
    """
    conn.execute("PRAGMA query_only = OFF")
    rows = conn.execute(
        """
        SELECT alert_id, shipment_id, severity, title, detail,
               COALESCE(escalation_level, 0) AS lvl
        FROM fact_alerts
        WHERE status IN ('OPEN', 'ACKNOWLEDGED')
          AND due_ts IS NOT NULL AND due_ts < :now
          AND COALESCE(escalation_level, 0) < :cap
        ORDER BY alert_id
        """,
        {"now": now, "cap": MAX_ESCALATION_LEVEL},
    ).fetchall()

    escalated: list[dict[str, Any]] = []
    for alert_id, shipment_id, severity, title, detail, lvl in rows:
        new_lvl = lvl + 1
        new_due = _due_from(now, severity)
        conn.execute(
            "UPDATE fact_alerts SET escalation_level = ?, due_ts = ?, updated_ts = ? "
            "WHERE alert_id = ?",
            (new_lvl, new_due, now, alert_id),
        )
        escalated.append(
            {
                "alert_id": alert_id,
                "shipment_id": shipment_id,
                "severity": "high" if new_lvl >= 2 else severity,
                "title": f"L{new_lvl} ESCALATED: {title}"[:120],
                "detail": f"SLA breached (L{new_lvl}). {detail}"[:500],
                "event_kind": "ALERT",
                "escalation_level": new_lvl,
            }
        )
    conn.commit()

    # L2+ escalations fan out a notice (reuse the alert outbox matcher)
    notify = [e for e in escalated if e["escalation_level"] >= 2]
    enqueued = 0
    if notify:
        from app.notifications.outbox import enqueue_for_alerts

        enqueued = enqueue_for_alerts(notify)

    return {"escalated": len(escalated), "notifications_enqueued": enqueued}


def cluster_by_service(conn: sqlite3.Connection) -> dict[str, Any]:
    """Group OPEN shipment-level alerts by the shared service their air leg rode,
    creating one SERVICE-scope parent per service with ≥2 affected shipments.

    Idempotent: a service that already has a parent alert is skipped. Child
    alerts get parent_alert_id + alert_scope='SHIPMENT'; parents carry the
    affected count and priority breakdown in their detail.
    """
    now = _horizon(conn)
    conn.execute("PRAGMA query_only = OFF")

    # candidate services: >=2 OPEN alerts whose shipment has an allocation on it,
    # and no existing SERVICE parent yet.
    rows = conn.execute(
        """
        SELECT a.service_id, COUNT(DISTINCT al.alert_id) AS n_alerts,
               COUNT(DISTINCT al.shipment_id) AS n_shipments,
               GROUP_CONCAT(DISTINCT a.priority_class) AS classes
        FROM fact_alerts al
        JOIN fact_allocations a ON a.shipment_id = al.shipment_id
        JOIN dim_transport_services s ON s.service_id = a.service_id
        WHERE al.status = 'OPEN' AND al.alert_scope IS NULL
        GROUP BY a.service_id
        HAVING n_shipments >= 2
        ORDER BY n_shipments DESC
        LIMIT 100
        """
    ).fetchall()

    next_num = int((conn.execute("SELECT MAX(alert_id) FROM fact_alerts").fetchone()[0] or "AL-000000").split("-")[1]) + 1
    parents_created = 0
    children_linked = 0

    for service_id, n_alerts, n_shipments, classes in rows:
        already = conn.execute(
            "SELECT alert_id FROM fact_alerts WHERE alert_scope = 'SERVICE' AND detail LIKE ?",
            (f"%{service_id}%",),
        ).fetchone()
        if already:
            continue
        parent_id = f"AL-{next_num:06d}"
        next_num += 1
        # representative shipment for the parent row's shipment_id FK
        rep = conn.execute(
            """SELECT al.shipment_id FROM fact_alerts al
               JOIN fact_allocations a ON a.shipment_id = al.shipment_id
               WHERE a.service_id = ? AND al.status = 'OPEN' LIMIT 1""",
            (service_id,),
        ).fetchone()[0]
        due = conn.execute(
            "SELECT strftime('%Y-%m-%dT%H:%M:%SZ', ?, '+4 hours')", (now,)
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO fact_alerts (alert_id, shipment_id, rule_id, source, severity,
                title, detail, status, created_ts, updated_ts, alert_scope, due_ts, escalation_level)
            VALUES (?, ?, NULL, 'rules', 'high', ?, ?, 'OPEN', ?, ?, 'SERVICE', ?, 0)
            """,
            (
                parent_id, rep,
                f"Service {service_id}: {n_shipments} shipments affected",
                f"Clustered exception on service {service_id}; {n_shipments} shipments, "
                f"{n_alerts} child alerts; priority classes: {classes}.",
                now, now, due,
            ),
        )
        parents_created += 1
        # link children
        conn.execute(
            """
            UPDATE fact_alerts SET parent_alert_id = ?, alert_scope = 'SHIPMENT'
            WHERE status = 'OPEN' AND alert_scope IS NULL AND shipment_id IN (
                SELECT al.shipment_id FROM fact_alerts al
                JOIN fact_allocations a ON a.shipment_id = al.shipment_id
                WHERE a.service_id = ?
            )
            """,
            (parent_id, service_id),
        )
        children_linked += conn.execute("SELECT changes()").fetchone()[0]

    conn.commit()
    return {"service_parents_created": parents_created, "children_linked": children_linked}
