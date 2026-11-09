"""Shared-capacity network endpoints (P0).

Exposes the transport-service schedule, per-service manifests and capacity
utilisation that the single-chain view could not represent. All routes are
ops-facing read APIs guarded by the shared session dependency.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import require_ops, require_session
from app.db import get_db

router = APIRouter(
    prefix="/api/network",
    tags=["network"],
    dependencies=[Depends(require_session)],
)


@router.get("/services")
def list_services(
    request: Request,
    mode: str | None = Query(None, description="AIR | SEA | TRUCK"),
    origin: str | None = Query(None),
    destination: str | None = Query(None),
    status: str | None = Query(None, description="SCHEDULED | CANCELLED | DEPARTED | RECOVERING"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Service list with live capacity water-line (allocated vs capacity)."""
    require_ops(request)
    rows = db.execute(
        text(
            """
            SELECT service_id, transport_mode, carrier_code, service_no,
                   origin_facility, destination_facility,
                   scheduled_depart_ts, scheduled_arrive_ts, cutoff_ts,
                   capacity_chargeable_kg, allocated_kg,
                   capacity_cbm, allocated_cbm, status, disruption_event_id,
                   CASE WHEN capacity_chargeable_kg > 0
                        THEN ROUND(allocated_kg / capacity_chargeable_kg, 4)
                        ELSE 0 END AS load_factor
            FROM dim_transport_services
            WHERE (:mode IS NULL OR transport_mode = :mode)
              AND (:origin IS NULL OR origin_facility = :origin)
              AND (:dest IS NULL OR destination_facility = :dest)
              AND (:status IS NULL OR status = :status)
              AND (:dfrom IS NULL OR scheduled_depart_ts >= :dfrom)
              AND (:dto IS NULL OR scheduled_depart_ts <= :dto)
            ORDER BY scheduled_depart_ts
            LIMIT :limit
            """
        ),
        {
            "mode": mode, "origin": origin, "dest": destination, "status": status,
            "dfrom": date_from, "dto": date_to, "limit": limit,
        },
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/services/{service_id}")
def service_detail(service_id: str, request: Request, db: Session = Depends(get_db)):
    """Service header + loaded shipment count + priority-class breakdown."""
    require_ops(request)
    svc = db.execute(
        text("SELECT * FROM dim_transport_services WHERE service_id = :sid"),
        {"sid": service_id},
    ).mappings().one_or_none()
    if svc is None:
        raise HTTPException(status_code=404, detail="service not found")

    breakdown = db.execute(
        text(
            """
            SELECT priority_class, allocation_status, COUNT(*) AS n,
                   ROUND(SUM(allocated_weight_kg), 1) AS kg
            FROM fact_allocations WHERE service_id = :sid
            GROUP BY priority_class, allocation_status
            ORDER BY priority_class, allocation_status
            """
        ),
        {"sid": service_id},
    ).mappings().all()
    loaded = db.execute(
        text(
            "SELECT COUNT(DISTINCT shipment_id) FROM fact_allocations "
            "WHERE service_id = :sid AND allocation_status != 'ROLLED'"
        ),
        {"sid": service_id},
    ).scalar()
    return {
        "service": dict(svc),
        "loaded_shipments": loaded,
        "priority_breakdown": [dict(r) for r in breakdown],
    }


@router.get("/services/{service_id}/manifest")
def service_manifest(service_id: str, request: Request, db: Session = Depends(get_db)):
    """MAWB/HAWB manifest and ULD occupancy for a service (doc-centre narrative)."""
    require_ops(request)
    exists = db.execute(
        text("SELECT 1 FROM dim_transport_services WHERE service_id = :sid"),
        {"sid": service_id},
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail="service not found")

    allocations = db.execute(
        text(
            """
            SELECT a.allocation_id, a.shipment_id, a.mawb_no, a.hawb_no,
                   a.priority_class, a.allocated_weight_kg, a.allocated_volume_cbm,
                   a.allocation_status, a.uld_id, s.cargo_category, s.customer_id
            FROM fact_allocations a
            JOIN dim_shipments s ON s.shipment_id = a.shipment_id
            WHERE a.service_id = :sid
            ORDER BY a.priority_class, a.shipment_id
            """
        ),
        {"sid": service_id},
    ).mappings().all()
    ulds = db.execute(
        text(
            "SELECT uld_id, uld_type, max_weight_kg, max_volume_cbm "
            "FROM dim_ulds WHERE service_id = :sid ORDER BY uld_id"
        ),
        {"sid": service_id},
    ).mappings().all()
    return {
        "service_id": service_id,
        "allocations": [dict(r) for r in allocations],
        "ulds": [dict(r) for r in ulds],
    }


@router.get("/capacity")
def capacity_timeseries(
    request: Request,
    mode: str | None = Query(None, description="AIR | SEA | TRUCK"),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    db: Session = Depends(get_db),
):
    """Daily capacity water-line and rolled-cargo series (P1 DES fills richer fields)."""
    require_ops(request)
    util = db.execute(
        text(
            """
            SELECT substr(scheduled_depart_ts, 1, 10) AS day,
                   ROUND(SUM(allocated_kg), 1) AS allocated_kg,
                   ROUND(SUM(capacity_chargeable_kg), 1) AS capacity_kg,
                   SUM(CASE WHEN status = 'CANCELLED' THEN 1 ELSE 0 END) AS cancelled_services,
                   COUNT(*) AS services
            FROM dim_transport_services
            WHERE (:mode IS NULL OR transport_mode = :mode)
              AND (:dfrom IS NULL OR scheduled_depart_ts >= :dfrom)
              AND (:dto IS NULL OR scheduled_depart_ts <= :dto)
            GROUP BY day ORDER BY day
            LIMIT 600
            """
        ),
        {"mode": mode, "dfrom": date_from, "dto": date_to},
    ).mappings().all()
    rolled = db.execute(
        text(
            """
            SELECT roll_reason, COUNT(*) AS n
            FROM fact_allocations
            WHERE allocation_status IN ('ROLLED', 'REACCOMMODATED')
              AND roll_reason != ''
            GROUP BY roll_reason ORDER BY n DESC
            """
        )
    ).mappings().all()
    return {
        "utilization": [dict(r) for r in util],
        "rolled_by_reason": [dict(r) for r in rolled],
    }
