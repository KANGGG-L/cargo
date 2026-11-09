"""Source adapters: normalize heterogeneous inputs into fact_event_log rows.

Each adapter maps a source-specific record onto the common event envelope:
  (dedupe_key, aggregate_type, aggregate_id, event_type, event_ts, source,
   trust_level, payload_json, correlation_id)

ONE Record-style event-type names are used so the log reads like a standard
LogisticsEvent stream (see docs/NETWORK_UPGRADE_PLAN.md R4-1). The milestone
code <-> event_type map is intentionally small and explicit.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone

# milestone code -> ONE Record-ish logistics event type
CODE_TO_EVENT_TYPE = {
    "BKD": "BookingConfirmed",
    "RCS": "ReadyForCarriage",
    "DEP": "Departed",
    "ARR": "Arrived",
    "NFD": "NotifiedForDelivery",
    "DLV": "Delivered",
}


def _now_real() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dedupe_key(source: str, aggregate_id: str, event_type: str, event_ts: str,
               leg_id: str | None = None) -> str:
    return hashlib.sha1(
        f"{source}|{aggregate_id}|{leg_id or ''}|{event_type}|{event_ts}".encode()
    ).hexdigest()


def append_event(
    conn: sqlite3.Connection,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    event_ts: str,
    source: str,
    trust_level: str = "trusted",
    payload: dict | None = None,
    correlation_id: str | None = None,
    leg_id: str | None = None,
) -> bool:
    """Append one event to fact_event_log. Idempotent by dedupe_key — returns
    True if newly inserted, False if a duplicate was skipped."""
    key = dedupe_key(source, aggregate_id, event_type, event_ts, leg_id)
    try:
        conn.execute(
            """
            INSERT INTO fact_event_log
              (dedupe_key, aggregate_type, aggregate_id, event_type, event_ts,
               ingest_ts, source, trust_level, payload_json, correlation_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key, aggregate_type, aggregate_id, event_type, event_ts,
                _now_real(), source, trust_level,
                json.dumps(payload or {}, separators=(",", ":")), correlation_id,
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def milestone_to_event(
    conn: sqlite3.Connection,
    *,
    shipment_id: str,
    leg_id: str | None,
    code: str,
    event_ts: str,
    source: str,
    trust_level: str = "trusted",
) -> bool:
    """Adapter for a milestone-shaped event (clock / FSU / generator)."""
    return append_event(
        conn,
        aggregate_type="SHIPMENT",
        aggregate_id=shipment_id,
        event_type=CODE_TO_EVENT_TYPE.get(code, code),
        event_ts=event_ts,
        source=source,
        trust_level=trust_level,
        payload={"code": code, "leg_id": leg_id},
        leg_id=leg_id,
    )


def capacity_change_to_event(
    conn: sqlite3.Connection,
    *,
    service_id: str,
    new_status: str,
    event_ts: str,
    disruption_event_id: str | None = None,
) -> bool:
    """Adapter for a service capacity/status change (e.g. typhoon cancellation)."""
    return append_event(
        conn,
        aggregate_type="SERVICE",
        aggregate_id=service_id,
        event_type="CapacityStatusChanged",
        event_ts=event_ts,
        source="capacity",
        payload={"status": new_status, "disruption_event_id": disruption_event_id},
        correlation_id=disruption_event_id,
    )
