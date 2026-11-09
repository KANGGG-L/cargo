"""Shipment list, per-shipment leg trace and modal-flow (sankey) endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_ops, require_session, require_shipment_access
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(
    prefix="/api/shipments",
    tags=["shipments"],
    dependencies=[Depends(require_session)],
)


def _customer_of(db: Session, shipment_id: str) -> str | None:
    return db.execute(
        text("SELECT customer_id FROM dim_shipments WHERE shipment_id = :sid"),
        {"sid": shipment_id},
    ).scalar()


@router.get("")
def list_shipments(
    request: Request,
    chain: str | None = Query(None, description="SEA_AIR_TRUCK | TRUCK_AIR_TRUCK | DIRECT_AIR"),
    status: str | None = Query(None, description="DELIVERED | DELAYED | EXCEPTION"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    user = require_session(request)
    rows = db.execute(
        text(
            """
            SELECT s.shipment_id, s.customer_id, s.transport_chain_type, s.cargo_category,
                   s.status, s.origin_location, s.destination_location,
                   s.total_chargeable_weight_kg, s.contracted_revenue_usd,
                   s.booking_ts, c.customer_name
            FROM dim_shipments s
            JOIN dim_customers c ON c.customer_id = s.customer_id
            WHERE (:chain IS NULL OR s.transport_chain_type = :chain)
              AND (:status IS NULL OR s.status = :status)
              AND (:customer IS NULL OR s.customer_id = :customer)
            ORDER BY s.booking_ts DESC
            LIMIT :limit
            """
        ),
        {
            "chain": chain,
            "status": status,
            "limit": limit,
            "customer": user.get("customer_id") if user.get("role") == "customer" else None,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{shipment_id}/milestones")
def shipment_milestones(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    """Dual-track milestone view: planned baseline vs reported events, with deviations."""
    exists = db.execute(
        text("SELECT 1 FROM dim_shipments WHERE shipment_id = :sid"), {"sid": shipment_id}
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="shipment not found")
    require_shipment_access(request, _customer_of(db, shipment_id))

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


@router.get("/{shipment_id}/tracks")
def shipment_tracks(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    """Great-circle/road polylines per leg for the map view (simulated positions)."""
    require_shipment_access(request, _customer_of(db, shipment_id))
    legs = db.execute(
        text(
            """
            SELECT leg_id, leg_sequence, transport_mode, origin_facility, destination_facility
            FROM fact_shipment_legs WHERE shipment_id = :sid ORDER BY leg_sequence
            """
        ),
        {"sid": shipment_id},
    ).mappings().all()
    from app.tracking.simulator import shipment_tracks

    return {"shipment_id": shipment_id, "tracks": shipment_tracks([dict(l) for l in legs])}


@router.get("/{shipment_id}/trace")
def shipment_trace(shipment_id: str, request: Request, db: Session = Depends(get_db)):
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
    require_shipment_access(request, shipment["customer_id"])

    legs = db.execute(
        text(
            """
            SELECT l.leg_id, l.leg_sequence, l.transport_mode, l.origin_facility,
                   l.destination_facility, l.carrier_code, l.voyage_flight_no,
                   l.planned_depart_ts, l.actual_depart_ts, l.planned_arrive_ts,
                   l.actual_arrive_ts, l.delay_minutes, l.distance_km,
                   l.allocated_cost_usd, l.leg_status,
                   a.service_id, a.allocation_status, a.priority_class,
                   svc.service_no
            FROM fact_shipment_legs l
            LEFT JOIN fact_allocations a ON a.leg_id = l.leg_id
            LEFT JOIN dim_transport_services svc ON svc.service_id = a.service_id
            WHERE l.shipment_id = :sid
            ORDER BY l.leg_sequence
            """
        ),
        {"sid": shipment_id},
    ).mappings().all()

    # annotate each leg with how many *other* shipments share its service
    leg_dicts = []
    for l in legs:
        d = dict(l)
        if d.get("service_id"):
            d["co_loaded_shipments"] = db.execute(
                text(
                    "SELECT COUNT(DISTINCT shipment_id) - 1 FROM fact_allocations "
                    "WHERE service_id = :svc AND shipment_id != :sid"
                ),
                {"svc": d["service_id"], "sid": shipment_id},
            ).scalar()
        else:
            d["co_loaded_shipments"] = None
        leg_dicts.append(d)

    return {"shipment": dict(shipment), "legs": leg_dicts}


@router.get("/flows/sankey")
def sankey_flows(request: Request, min_legs: int = Query(20, ge=1), db: Session = Depends(get_db)):
    """Aggregated origin→destination leg volumes for the modal-flow diagram."""
    require_ops(request)
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
