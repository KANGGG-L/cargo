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


def sync(conn: sqlite3.Connection) -> dict[str, int]:
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
    inserts = []
    for rule_id in sorted(candidates):
        for cand in candidates[rule_id]:
            key = (cand["shipment_id"], rule_id)
            if key in existing:
                continue
            existing.add(key)
            inserts.append(
                (
                    f"AL-{next_num:06d}",
                    cand["shipment_id"],
                    cand["rule_id"],
                    "rules",
                    cand["severity"],
                    cand["title"],
                    cand["detail"],
                    "OPEN",
                    now,
                    now,
                )
            )
            next_num += 1
            created += 1

    conn.execute("PRAGMA query_only = OFF")
    conn.executemany(
        """
        INSERT INTO fact_alerts (alert_id, shipment_id, rule_id, source, severity,
                                 title, detail, status, created_ts, updated_ts)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        inserts,
    )
    conn.commit()
    open_count = conn.execute("SELECT COUNT(*) FROM fact_alerts WHERE status = 'OPEN'").fetchone()[0]
    return {"created": created, "open_total": open_count}
