"""Recovery closed-loop: re-accommodate a shipment's air leg onto a new service.

This is the "operator does something" half of the control tower. A reroute
query (agent tool_reroute_options) only *proposes*; this module *commits*:

  1. roll the current AIR-leg allocation off its service onto the chosen one,
  2. keep shared-capacity water-lines conservative (old service frees weight,
     new service takes it; reject if the new service can't fit),
  3. realign the leg's service_no / schedule so leg and allocation stay in sync,
  4. auto-resolve the shipment's OPEN exception alerts (same resolve contract as
     FSU-ingest auto-resolve),
  5. enqueue a proactive recovery notice to subscribers,
  6. audit the write.

Deterministic and idempotent: re-accommodating a shipment that is already on the
target service is a no-op (no second roll, no duplicate notice).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings


class RecoveryError(Exception):
    """Raised when a re-accommodation cannot be performed (bad request / no fit)."""

    def __init__(self, message: str, *, code: str = "invalid"):
        super().__init__(message)
        self.code = code  # "not_found" | "no_fit" | "invalid"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rw() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _resolve_alerts(conn: sqlite3.Connection, shipment_id: str, note: str) -> list[str]:
    """Resolve the shipment's OPEN/ACK alerts. Mirrors ingest auto-resolve."""
    rows = conn.execute(
        "SELECT alert_id FROM fact_alerts "
        "WHERE shipment_id = ? AND status IN ('OPEN', 'ACKNOWLEDGED')",
        (shipment_id,),
    ).fetchall()
    resolved = []
    now = _now()
    for (alert_id,) in rows:
        conn.execute(
            "UPDATE fact_alerts SET status = 'RESOLVED', updated_ts = ?, resolution_note = ? "
            "WHERE alert_id = ?",
            (now, note, alert_id),
        )
        resolved.append(alert_id)
    return resolved


def reaccommodate(
    shipment_id: str,
    to_service_id: str,
    reason: str = "DISRUPTION",
    actor: str = "ops",
) -> dict[str, Any]:
    """Roll a shipment's AIR-leg allocation onto ``to_service_id`` and close the loop.

    Returns a summary dict. Raises RecoveryError on bad input or insufficient capacity.
    All writes happen in a single transaction; capacity stays conservative.
    """
    valid_reasons = {"CAPACITY", "CUTOFF", "MCT", "DG_LIMIT", "DISRUPTION"}
    reason = reason.upper()
    if reason not in valid_reasons:
        raise RecoveryError(f"reason must be one of {sorted(valid_reasons)}", code="invalid")

    conn = _rw()
    try:
        # current AIR-leg allocation for this shipment
        alloc = conn.execute(
            """
            SELECT a.allocation_id, a.leg_id, a.service_id, a.allocated_weight_kg,
                   a.allocated_volume_cbm, a.allocation_status
            FROM fact_allocations a
            JOIN fact_shipment_legs l ON l.leg_id = a.leg_id
            WHERE a.shipment_id = ? AND l.transport_mode = 'AIR'
            ORDER BY a.allocation_status = 'CONFIRMED' DESC
            LIMIT 1
            """,
            (shipment_id,),
        ).fetchone()
        if alloc is None:
            raise RecoveryError(f"no AIR-leg allocation for {shipment_id}", code="not_found")

        from_service_id = alloc["service_id"]

        # idempotent: already on target -> no-op
        if from_service_id == to_service_id:
            return {
                "shipment_id": shipment_id,
                "rolled_from": from_service_id,
                "rolled_to": to_service_id,
                "no_op": True,
                "resolved_alerts": [],
                "notifications_enqueued": 0,
            }

        target = conn.execute(
            "SELECT service_id, service_no, scheduled_depart_ts, scheduled_arrive_ts, "
            "capacity_chargeable_kg, allocated_kg, status "
            "FROM dim_transport_services WHERE service_id = ?",
            (to_service_id,),
        ).fetchone()
        if target is None:
            raise RecoveryError(f"unknown service {to_service_id}", code="not_found")
        if target["status"] == "CANCELLED":
            raise RecoveryError(f"service {to_service_id} is cancelled", code="invalid")

        weight = alloc["allocated_weight_kg"]
        free = target["capacity_chargeable_kg"] - target["allocated_kg"]
        if weight > free + 1e-6:
            raise RecoveryError(
                f"service {to_service_id} has {free:.0f} kg free, needs {weight:.0f} kg",
                code="no_fit",
            )

        now = _now()

        # 1. free weight on the old service, load it on the new one (capacity conservation)
        conn.execute(
            "UPDATE dim_transport_services SET allocated_kg = allocated_kg - ? WHERE service_id = ?",
            (weight, from_service_id),
        )
        conn.execute(
            "UPDATE dim_transport_services SET allocated_kg = allocated_kg + ? WHERE service_id = ?",
            (weight, to_service_id),
        )

        # 2. roll the allocation onto the new service
        conn.execute(
            """
            UPDATE fact_allocations
            SET service_id = ?, allocation_status = 'REACCOMMODATED',
                rolled_from_service_id = ?, roll_reason = ?, decided_ts = ?
            WHERE allocation_id = ?
            """,
            (to_service_id, from_service_id, reason, now, alloc["allocation_id"]),
        )

        # 3. keep the leg in sync with its new service (service_no + schedule)
        conn.execute(
            """
            UPDATE fact_shipment_legs
            SET voyage_flight_no = ?, planned_depart_ts = ?, planned_arrive_ts = ?
            WHERE leg_id = ?
            """,
            (target["service_no"], target["scheduled_depart_ts"],
             target["scheduled_arrive_ts"], alloc["leg_id"]),
        )

        # 4. auto-resolve the shipment's open exceptions
        note = f"reaccommodated {from_service_id}->{to_service_id} ({reason}) by {actor}"
        resolved = _resolve_alerts(conn, shipment_id, note)

        conn.commit()
    except RecoveryError:
        conn.rollback()
        conn.close()
        raise
    except Exception:
        conn.rollback()
        conn.close()
        raise
    finally:
        if conn:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                pass

    # 5. proactive recovery notice (separate connection; outbox manages its own)
    enqueued = _enqueue_recovery_notice(
        shipment_id, from_service_id, to_service_id, target["scheduled_depart_ts"]
    )

    # 6. audit
    try:
        from app.agent.governance import audit_tool_call

        audit_tool_call(
            tool_name="reaccommodate",
            tool_kind="recovery",
            args={"shipment_id": shipment_id, "to_service_id": to_service_id, "reason": reason},
            confirmed=True,
            result_summary=f"rolled {from_service_id}->{to_service_id}; resolved {len(resolved)} alerts",
        )
    except Exception:
        pass  # audit is additive, never block the recovery

    return {
        "shipment_id": shipment_id,
        "rolled_from": from_service_id,
        "rolled_to": to_service_id,
        "no_op": False,
        "resolved_alerts": resolved,
        "notifications_enqueued": enqueued,
    }


def _enqueue_recovery_notice(
    shipment_id: str, from_service: str, to_service: str, new_depart: str
) -> int:
    """Enqueue a recovery notice to this shipment's subscribers via the outbox.

    Reuses enqueue_for_alerts' subscription-matching by presenting the recovery
    as an ALERT-kind event; the outbox dedupe key keeps re-runs idempotent.
    """
    from app.notifications.outbox import enqueue_for_alerts

    notice = {
        "alert_id": f"REACC-{shipment_id}-{to_service}",
        "shipment_id": shipment_id,
        "severity": "high",
        "title": f"Re-accommodated to {to_service}",
        "detail": (
            f"Shipment {shipment_id} rolled from {from_service} to {to_service}. "
            f"New departure {new_depart}."
        ),
        "event_kind": "ALERT",
    }
    return enqueue_for_alerts([notice])
