"""Shipment list, per-shipment leg trace and modal-flow (sankey) endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(prefix="/api/shipments", tags=["shipments"])


@router.get("")
def list_shipments(
    chain: str | None = Query(None, description="SEA_AIR_TRUCK | TRUCK_AIR_TRUCK | DIRECT_AIR"),
    status: str | None = Query(None, description="DELIVERED | DELAYED | EXCEPTION"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text(
            """
            SELECT s.shipment_id, s.transport_chain_type, s.cargo_category, s.status,
                   s.origin_location, s.destination_location,
                   s.total_chargeable_weight_kg, s.contracted_revenue_usd,
                   s.booking_ts, c.customer_name
            FROM dim_shipments s
            JOIN dim_customers c ON c.customer_id = s.customer_id
            WHERE (:chain IS NULL OR s.transport_chain_type = :chain)
              AND (:status IS NULL OR s.status = :status)
            ORDER BY s.booking_ts DESC
            LIMIT :limit
            """
        ),
        {"chain": chain, "status": status, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{shipment_id}/milestones")
def shipment_milestones(shipment_id: str, db: Session = Depends(get_db)):
    """Dual-track milestone view: planned baseline vs reported events, with deviations."""
    exists = db.execute(
        text("SELECT 1 FROM dim_shipments WHERE shipment_id = :sid"), {"sid": shipment_id}
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="shipment not found")

    rows = db.execute(
        text(
            """
            SELECT p.code, p.leg_id, p.planned_ts,
                   e.event_ts AS actual_ts, e.source AS event_source,
                   CASE
                     WHEN e.event_ts IS NULL THEN 'MISSING'
                     WHEN (julianday(e.event_ts) - julianday(p.planned_ts)) * 1440.0 > 60 THEN 'LATE'
                     ELSE 'ON_TIME'
                   END AS deviation
            FROM fact_milestones_plan p
            LEFT JOIN fact_milestone_events e
              ON e.shipment_id = p.shipment_id AND e.code = p.code
             AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
            WHERE p.shipment_id = :sid
            ORDER BY p.planned_ts, p.code
            """
        ),
        {"sid": shipment_id},
    ).mappings().all()
    return {"shipment_id": shipment_id, "milestones": [dict(r) for r in rows]}


@router.get("/{shipment_id}/trace")
def shipment_trace(shipment_id: str, db: Session = Depends(get_db)):
    shipment = db.execute(
        text(
            """
            SELECT s.*, c.customer_name, c.region
            FROM dim_shipments s JOIN dim_customers c ON c.customer_id = s.customer_id
            WHERE s.shipment_id = :sid
            """
        ),
        {"sid": shipment_id},
    ).mappings().one_or_none()
    if shipment is None:
        raise HTTPException(status_code=404, detail="shipment not found")

    legs = db.execute(
        text(
            """
            SELECT leg_id, leg_sequence, transport_mode, origin_facility, destination_facility,
                   carrier_code, voyage_flight_no, planned_depart_ts, actual_depart_ts,
                   planned_arrive_ts, actual_arrive_ts, delay_minutes, distance_km,
                   allocated_cost_usd, leg_status
            FROM fact_shipment_legs
            WHERE shipment_id = :sid
            ORDER BY leg_sequence
            """
        ),
        {"sid": shipment_id},
    ).mappings().all()

    return {"shipment": dict(shipment), "legs": [dict(l) for l in legs]}


@router.get("/flows/sankey")
def sankey_flows(min_legs: int = Query(20, ge=1), db: Session = Depends(get_db)):
    """Aggregated origin→destination leg volumes for the modal-flow diagram."""
    rows = db.execute(
        text(
            """
            SELECT origin_facility AS source, destination_facility AS target,
                   COUNT(*) AS value
            FROM fact_shipment_legs
            GROUP BY origin_facility, destination_facility
            HAVING COUNT(*) >= :min_legs
            ORDER BY value DESC
            """
        ),
        {"min_legs": min_legs},
    ).mappings().all()

    links = [dict(r) for r in rows]
    nodes = []
    seen = set()
    for l in links:
        for key in ("source", "target"):
            if l[key] not in seen:
                seen.add(l[key])
                nodes.append({"name": l[key]})
    return {"nodes": nodes, "links": links}
