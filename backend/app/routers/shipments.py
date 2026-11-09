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
    """Modal-flow diagram as a demand-vs-capacity two-tone sankey (§5.3.3).

    Each origin→destination link carries both the demand tonnage that actually
    moved (allocated chargeable weight) and the capacity tonnage the shared
    services on that lane offered, so the UI can render demand against available
    slot. `value` stays = demand tonnes for backward compatibility; leg_count is
    kept for lanes with no service/allocation coverage (e.g. last-mile METRO)."""
    require_ops(request)
    # demand + capacity per lane from the shared-service network
    svc_rows = db.execute(
        text(
            """
            SELECT s.origin_facility AS source, s.destination_facility AS target,
                   ROUND(SUM(s.allocated_kg) / 1000.0, 1) AS demand_tonnes,
                   ROUND(SUM(s.capacity_chargeable_kg) / 1000.0, 1) AS capacity_tonnes,
                   COUNT(*) AS services
            FROM dim_transport_services s
            GROUP BY s.origin_facility, s.destination_facility
            HAVING SUM(s.allocated_kg) > 0
            """
        )
    ).mappings().all()
    svc_by_lane = {(r["source"], r["target"]): dict(r) for r in svc_rows}

    # leg-count lanes (covers last-mile + any lane without a service row)
    leg_rows = db.execute(
        text(
            """
            SELECT origin_facility AS source, destination_facility AS target,
                   COUNT(*) AS leg_count,
                   ROUND(SUM(s.total_chargeable_weight_kg) / 1000.0, 1) AS leg_tonnes
            FROM fact_shipment_legs l
            JOIN dim_shipments s ON s.shipment_id = l.shipment_id
            GROUP BY origin_facility, destination_facility
            HAVING COUNT(*) >= :min_legs
            ORDER BY leg_count DESC
            """
        ),
        {"min_legs": min_legs},
    ).mappings().all()

    links = []
    for r in leg_rows:
        lane = (r["source"], r["target"])
        svc = svc_by_lane.get(lane)
        demand = svc["demand_tonnes"] if svc else r["leg_tonnes"]
        capacity = svc["capacity_tonnes"] if svc else None
        headroom = round(capacity - demand, 1) if capacity is not None else None
        util_pct = round(100.0 * demand / capacity, 1) if capacity else None
        links.append({
            "source": r["source"],
            "target": r["target"],
            "value": demand,                 # backward-compatible: demand tonnes
            "demand_tonnes": demand,
            "capacity_tonnes": capacity,
            "headroom_tonnes": headroom,
            "utilization_pct": util_pct,
            "leg_count": r["leg_count"],
        })

    nodes = []
    seen = set()
    for l in links:
        for key in ("source", "target"):
            if l[key] not in seen:
                seen.add(l[key])
                nodes.append({"name": l[key]})
    return {"nodes": nodes, "links": links}
