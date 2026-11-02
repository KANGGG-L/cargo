"""Order workbench: lifecycle state machine, AWB allocation.

States: DRAFT → QUOTED → BOOKED → IN_PROGRESS → COMPLETED, CANCELLED anytime
before COMPLETED. Guards: BOOKED requires an AWB (and a DG declaration for
dangerous goods); IN_PROGRESS requires an RCS milestone event.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import require_session
from app.config import get_settings
from app.db import get_db

router = APIRouter(
    prefix="/api/orders",
    dependencies=[Depends(require_session)],
    tags=["orders"])

LIFECYCLE = ["DRAFT", "QUOTED", "BOOKED", "IN_PROGRESS", "COMPLETED"]
TRANSITIONS = {
    "DRAFT": {"QUOTED", "CANCELLED"},
    "QUOTED": {"BOOKED", "CANCELLED"},
    "BOOKED": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"COMPLETED"},
    "COMPLETED": set(),
}

AIRLINE_PREFIX = {"CX": "160", "KE": "180", "EK": "176", "UPS": "406"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_milestone(conn, shipment_id: str, code: str, ts: str, source: str = "agent"):
    """Plan + event pair for a lifecycle-driven milestone (keeps the
    every-event-anchors-to-a-plan invariant of the FSU ingest layer)."""
    import hashlib

    conn.execute(
        "INSERT INTO fact_milestones_plan (shipment_id, leg_id, code, planned_ts) VALUES (?, NULL, ?, ?)",
        (shipment_id, code, ts),
    )
    key = hashlib.sha1(f"{code}|{shipment_id}||{ts}".encode()).hexdigest()
    conn.execute(
        "INSERT INTO fact_milestone_events (shipment_id, leg_id, code, event_ts, source, dedupe_key)"
        " VALUES (?, NULL, ?, ?, ?, ?)",
        (shipment_id, code, ts, source, key),
    )


def _rw():
    return sqlite3.connect(get_settings().db_path)
    # row tuples accessed by index throughout


def _current_status(conn, shipment_id: str) -> str | None:
    row = conn.execute(
        "SELECT status FROM fact_order_lifecycle WHERE shipment_id = ? ORDER BY id DESC LIMIT 1",
        (shipment_id,),
    ).fetchone()
    return row[0] if row else None


class OrderRequest(BaseModel):
    customer_id: str = Field(max_length=20)
    origin_location: str = Field(max_length=10)
    destination_location: str = Field(max_length=10)
    transport_chain_type: str = Field(pattern="^(SEA_AIR_TRUCK|TRUCK_AIR_TRUCK|DIRECT_AIR)$")
    cargo_category: str = Field(default="General", max_length=30)
    total_chargeable_weight_kg: float = Field(gt=0)
    contracted_revenue_usd: float = Field(gt=0)


class TransitionRequest(BaseModel):
    to: str = Field(pattern="^(QUOTED|BOOKED|IN_PROGRESS|COMPLETED|CANCELLED)$")
    note: str | None = Field(default=None, max_length=300)


class AwbRequest(BaseModel):
    airline_code: str = Field(pattern="^(CX|KE|EK|UPS)$")


@router.post("")
def create_order(req: OrderRequest, db=Depends(get_db)):
    cust = db.execute(
        text("SELECT customer_id FROM dim_customers WHERE customer_id = :c"),
        {"c": req.customer_id},
    ).scalar()
    if not cust:
        raise HTTPException(status_code=404, detail="customer not found")

    conn = _rw()
    try:
        n = int(conn.execute(
            "SELECT COUNT(*) FROM fact_order_lifecycle WHERE shipment_id LIKE 'SHO-%'"
        ).fetchone()[0]) + 1
        shipment_id = f"SHO-2026-{n:05d}"
        now = _now()
        conn.execute(
            """
            INSERT INTO dim_shipments (shipment_id, customer_id, origin_location,
              destination_location, transport_chain_type, cargo_category,
              total_chargeable_weight_kg, total_volume_cbm, total_pieces,
              booking_ts, contracted_revenue_usd, estimated_cost_usd, actual_cost_usd, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, 0, 0, 'PLANNED')
            """,
            (shipment_id, req.customer_id, req.origin_location, req.destination_location,
             req.transport_chain_type, req.cargo_category, req.total_chargeable_weight_kg,
             now, req.contracted_revenue_usd),
        )
        conn.execute(
            "INSERT INTO fact_order_lifecycle (shipment_id, status, note, ts) VALUES (?, 'DRAFT', 'created via workbench', ?)",
            (shipment_id, now),
        )
        _record_milestone(conn, shipment_id, "BKD", now, source="agent")
        conn.commit()
    finally:
        conn.close()
    return {"shipment_id": shipment_id, "status": "DRAFT"}


@router.get("")
def list_orders(db=Depends(get_db)):
    rows = db.execute(
        text(
            """
            SELECT l.shipment_id, l.status AS lifecycle, l.ts AS since,
                   s.transport_chain_type, s.cargo_category, s.origin_location,
                   s.destination_location, s.total_chargeable_weight_kg,
                   s.contracted_revenue_usd, s.status AS delivery_status,
                   c.customer_name, a.awb_no
            FROM (SELECT shipment_id, MAX(id) AS mid FROM fact_order_lifecycle GROUP BY shipment_id) last
            JOIN fact_order_lifecycle l ON l.id = last.mid
            JOIN dim_shipments s ON s.shipment_id = l.shipment_id
            JOIN dim_customers c ON c.customer_id = s.customer_id
            LEFT JOIN dim_awb a ON a.shipment_id = l.shipment_id
            ORDER BY l.id DESC LIMIT 100
            """
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{shipment_id}")
def order_detail(shipment_id: str, db=Depends(get_db)):
    history = db.execute(
        text(
            "SELECT status, note, ts FROM fact_order_lifecycle "
            "WHERE shipment_id = :sid ORDER BY id"
        ),
        {"sid": shipment_id},
    ).mappings().all()
    if not history:
        raise HTTPException(status_code=404, detail="order not found")
    awb = db.execute(
        text("SELECT awb_no, airline_code, created_ts FROM dim_awb WHERE shipment_id = :sid"),
        {"sid": shipment_id},
    ).mappings().one_or_none()
    docs = db.execute(
        text("SELECT doc_id, doc_type, eawb_status, created_ts FROM dim_documents WHERE shipment_id = :sid"),
        {"sid": shipment_id},
    ).mappings().all()
    return {
        "shipment_id": shipment_id,
        "lifecycle": [dict(h) for h in history],
        "current": history[-1]["status"],
        "awb": dict(awb) if awb else None,
        "documents": [dict(d) for d in docs],
    }


@router.post("/{shipment_id}/transition")
def transition(shipment_id: str, req: TransitionRequest, db=Depends(get_db)):
    conn = _rw()
    try:
        current = _current_status(conn, shipment_id)
        if current is None:
            raise HTTPException(status_code=404, detail="order not found")
        if req.to not in TRANSITIONS.get(current, set()):
            raise HTTPException(status_code=409, detail=f"illegal transition {current} → {req.to}")

        if req.to == "BOOKED":
            awb = conn.execute(
                "SELECT 1 FROM dim_awb WHERE shipment_id = ?", (shipment_id,)
            ).fetchone()
            if not awb:
                raise HTTPException(status_code=409, detail="BOOKED requires an AWB — allocate one first")
            category = conn.execute(
                "SELECT cargo_category FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
            ).fetchone()[0]
            if category == "Dangerous_Goods":
                dg = conn.execute(
                    "SELECT 1 FROM dim_documents WHERE shipment_id = ? AND doc_type = 'DG_DECL'",
                    (shipment_id,),
                ).fetchone()
                if not dg:
                    raise HTTPException(
                        status_code=409,
                        detail="Dangerous goods shipments require a DG_DECL document before booking",
                    )
            # build the planned multimodal chain — the schedule the ETA model and
            # the map predict against until real milestones replace it
            conn.row_factory = sqlite3.Row
            shipment = dict(conn.execute(
                "SELECT * FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
            ).fetchone())
            booking_ts = shipment["booking_ts"]
            from app.tracking.eta import build_planned_legs

            planned = build_planned_legs(dict(shipment), booking_ts)
            conn.execute("DELETE FROM fact_planned_legs WHERE shipment_id = ?", (shipment_id,))
            conn.executemany(
                """
                INSERT INTO fact_planned_legs (shipment_id, leg_sequence, transport_mode,
                  origin_facility, destination_facility, carrier_code,
                  planned_depart_ts, planned_arrive_ts, basis)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(shipment_id, p["leg_sequence"], p["transport_mode"], p["origin_facility"],
                  p["destination_facility"], p["carrier_code"], p["planned_depart_ts"],
                  p["planned_arrive_ts"], p["basis"]) for p in planned],
            )
        if req.to == "IN_PROGRESS":
            rcs = conn.execute(
                "SELECT 1 FROM fact_milestone_events WHERE shipment_id = ? AND code = 'RCS'",
                (shipment_id,),
            ).fetchone()
            if not rcs:
                raise HTTPException(status_code=409, detail="IN_PROGRESS requires an RCS milestone event")

        conn.execute(
            "INSERT INTO fact_order_lifecycle (shipment_id, status, note, ts) VALUES (?, ?, ?, ?)",
            (shipment_id, req.to, req.note, _now()),
        )
        if req.to == "IN_PROGRESS":
            _record_milestone(conn, shipment_id, "RCS", _now(), source="agent")
        if req.to == "COMPLETED":
            _record_milestone(conn, shipment_id, "DLV", _now(), source="agent")
        conn.commit()
        return {"shipment_id": shipment_id, "status": req.to}
    finally:
        conn.close()


@router.get("/{shipment_id}/eta")
def order_eta(shipment_id: str, db=Depends(get_db)):
    """Empirical-quantile ETA for a booked order (per leg + end-to-end)."""
    from app.tracking.eta import predict_eta

    conn = _rw()
    conn.row_factory = sqlite3.Row
    try:
        result = predict_eta(conn, shipment_id)
    finally:
        conn.close()
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="no planned legs — transition the order to BOOKED first",
        )
    return result


@router.post("/{shipment_id}/awb")
def allocate_awb(shipment_id: str, req: AwbRequest, db=Depends(get_db)):
    conn = _rw()
    try:
        exists = conn.execute(
            "SELECT 1 FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="shipment not found")
        if conn.execute("SELECT 1 FROM dim_awb WHERE shipment_id = ?", (shipment_id,)).fetchone():
            raise HTTPException(status_code=409, detail="AWB already allocated")
        prefix = AIRLINE_PREFIX[req.airline_code]
        serial = int(hashlib.sha1(shipment_id.encode()).hexdigest()[:8], 16) % 10_000_000
        check = serial % 7  # IATA: the 7-digit serial number modulo 7
        awb_no = f"{prefix}-{serial:07d}{check}"
        conn.execute(
            "INSERT INTO dim_awb (awb_no, shipment_id, airline_code, created_ts) VALUES (?, ?, ?, ?)",
            (awb_no, shipment_id, req.airline_code, _now()),
        )
        conn.commit()
        return {"awb_no": awb_no, "airline_code": req.airline_code}
    finally:
        conn.close()
