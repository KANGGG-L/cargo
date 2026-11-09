"""Projectors: derive read models from the append-only fact_event_log.

The event log is the source of truth; these functions rebuild/refresh read
models from it. Projection is idempotent — replaying the whole log produces no
new rows in the projected tables (test_event_idempotency).

Note (R2 compatibility): fact_milestone_events keeps its existing contract and
is still written directly by the clock/FSU paths. The projector here provides
the *capacity-state* read model and an idempotency-checked milestone projection
used by tests; it never double-writes milestone rows that already exist.
"""

import sqlite3
from typing import Any

from app.events.adapters import CODE_TO_EVENT_TYPE

EVENT_TYPE_TO_CODE = {v: k for k, v in CODE_TO_EVENT_TYPE.items()}


def project_milestones(conn: sqlite3.Connection) -> dict[str, int]:
    """Project SHIPMENT events from the log into fact_milestone_events, skipping
    any (shipment, code, leg) that already has an event. Idempotent."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT aggregate_id, event_type, event_ts, source, payload_json
        FROM fact_event_log
        WHERE aggregate_type = 'SHIPMENT' AND trust_level = 'trusted'
        ORDER BY event_id
        """
    ).fetchall()
    import json

    created = 0
    for r in rows:
        code = EVENT_TYPE_TO_CODE.get(r["event_type"])
        if code is None:
            continue
        payload = json.loads(r["payload_json"] or "{}")
        leg_id = payload.get("leg_id")
        exists = conn.execute(
            """
            SELECT 1 FROM fact_milestone_events
            WHERE shipment_id = ? AND code = ?
              AND ((leg_id IS NULL AND ? IS NULL) OR leg_id = ?)
            """,
            (r["aggregate_id"], code, leg_id, leg_id),
        ).fetchone()
        if exists:
            continue
        import hashlib

        key = hashlib.sha1(
            f"{code}|{r['aggregate_id']}|{leg_id or ''}|{r['event_ts']}".encode()
        ).hexdigest()
        try:
            conn.execute(
                "INSERT INTO fact_milestone_events "
                "(shipment_id, leg_id, code, event_ts, source, dedupe_key) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (r["aggregate_id"], leg_id, code, r["event_ts"], r["source"], key),
            )
            created += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return {"projected_milestones": created}


def capacity_state(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Capacity water-line read model from services + allocations (the v_capacity_state
    view backs this; the function is the programmatic accessor)."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM v_capacity_state ORDER BY day").fetchall()
    return [dict(r) for r in rows]


CREATE_CAPACITY_VIEW = """
CREATE VIEW IF NOT EXISTS v_capacity_state AS
SELECT substr(s.scheduled_depart_ts, 1, 10) AS day,
       s.transport_mode AS mode,
       COUNT(*) AS services,
       SUM(CASE WHEN s.status = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_services,
       ROUND(SUM(s.allocated_kg), 1) AS allocated_kg,
       ROUND(SUM(s.capacity_chargeable_kg), 1) AS capacity_kg,
       ROUND(100.0 * SUM(s.allocated_kg) / NULLIF(SUM(s.capacity_chargeable_kg), 0), 1) AS load_pct
FROM dim_transport_services s
GROUP BY day, s.transport_mode
"""


def ensure_views(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_CAPACITY_VIEW)
    conn.commit()
