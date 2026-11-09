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

# R4-4 data-quality SLA view: coverage, freshness, late events, source trust.
# Every metric is a pure SQL aggregate so it can be independently re-computed
# (answers "how do you prove 96.7% coverage isn't made up?").
CREATE_DATA_QUALITY_VIEW = """
CREATE VIEW IF NOT EXISTS v_data_quality AS
WITH plan AS (SELECT COUNT(*) AS planned FROM fact_milestones_plan),
     reported AS (
       SELECT COUNT(*) AS covered FROM fact_milestones_plan p
       WHERE EXISTS (
         SELECT 1 FROM fact_milestone_events e
         WHERE e.shipment_id = p.shipment_id AND e.code = p.code
           AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id))
     ),
     late AS (
       SELECT COUNT(*) AS late_events FROM fact_milestones_plan p
       JOIN fact_milestone_events e
         ON e.shipment_id = p.shipment_id AND e.code = p.code
        AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
       WHERE (julianday(e.event_ts) - julianday(p.planned_ts)) * 1440.0 > 60
     ),
     rej AS (
       SELECT COALESCE(SUM(rejected),0) AS rejected, COALESCE(SUM(parsed),0) AS parsed
       FROM ingest_log
     )
SELECT
  (SELECT planned FROM plan) AS planned_milestones,
  (SELECT covered FROM reported) AS covered_milestones,
  ROUND(100.0 * (SELECT covered FROM reported) / NULLIF((SELECT planned FROM plan),0), 2) AS coverage_pct,
  (SELECT late_events FROM late) AS late_events,
  ROUND(100.0 * (SELECT late_events FROM late) / NULLIF((SELECT covered FROM reported),0), 2) AS late_pct,
  (SELECT rejected FROM rej) AS ingest_rejected,
  (SELECT parsed FROM rej) AS ingest_parsed,
  ROUND(100.0 * (SELECT rejected FROM rej) / NULLIF((SELECT rejected FROM rej)+(SELECT parsed FROM rej),0), 2) AS reject_pct
"""

# source trust distribution from the event log (R4-4)
CREATE_SOURCE_TRUST_VIEW = """
CREATE VIEW IF NOT EXISTS v_source_trust AS
SELECT source, trust_level, COUNT(*) AS n
FROM fact_event_log GROUP BY source, trust_level
"""


def ensure_views(conn: sqlite3.Connection) -> None:
    conn.execute(CREATE_CAPACITY_VIEW)
    conn.execute(CREATE_DATA_QUALITY_VIEW)
    conn.execute(CREATE_SOURCE_TRUST_VIEW)
    conn.commit()
