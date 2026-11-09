"""Empirical ETA model: historical delay quantiles per mode/lane bucket.

The distribution is mined from fact_shipment_legs at request time (deterministic
for a given database state) — P50/P80/P95 of arrival delay per
(transport_mode, origin→destination) bucket with mode-level fallback. Predicted
arrival for each leg = previous leg's P50 ETA + planned duration + quantile delay.
"""

import math
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app.config import get_settings
from app.tracking.simulator import LOCATIONS

FLIGHT_SPEED_KMH = 850.0

SEA_FEEDER_HOURS = 34.0
TRUCK_CROSSING_HOURS = 5.0
HUB_DWELL_HOURS = 9.0
DELIVERY_HOURS = 4.0

RISK_THRESHOLDS_MIN = {"p80": 240, "p95": 1440}


def _haversine_km(a: dict, b: dict) -> float:
    rad = math.pi / 180.0
    la1, lo1, la2, lo2 = a["lat"] * rad, a["lon"] * rad, b["lat"] * rad, b["lon"] * rad
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 1)


def build_planned_legs(shipment: dict[str, Any], booked_ts: str,
                       conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    """Schedule template by chain type — durations from network medians, air
    duration from great-circle distance at 850 km/h. When `conn` is given, the
    AIR leg is bound to the earliest feasible shared service (P2)."""
    origin = shipment["origin_location"]
    dest = shipment["destination_location"]
    chain = shipment["transport_chain_type"]
    hk = LOCATIONS["HKG"]
    t = datetime.strptime(booked_ts[:19], "%Y-%m-%dT%H:%M:%S")

    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    legs: list[dict[str, Any]] = []
    seq = 1

    def add(mode: str, o: str, d: str, depart: datetime, arrive: datetime, basis: str,
            service_id: str | None = None):
        nonlocal seq
        legs.append({
            "leg_sequence": seq, "transport_mode": mode, "origin_facility": o,
            "destination_facility": d, "carrier_code": "CX" if mode == "AIR" else (
                "Feeder_Line_A" if mode == "SEA" else "CrossBorder_Fleet_B"),
            "planned_depart_ts": iso(depart), "planned_arrive_ts": iso(arrive),
            "basis": basis, "service_id": service_id,
        })
        seq += 1

    if chain in ("SEA_AIR_TRUCK", "TRUCK_AIR_TRUCK"):
        sea = chain.startswith("SEA")
        hours = SEA_FEEDER_HOURS if sea else TRUCK_CROSSING_HOURS
        add("SEA" if sea else "TRUCK", origin, "HKG", t, t + timedelta(hours=hours),
            f"{'feeder' if sea else 'cross-border'} median from history")
        air_depart = t + timedelta(hours=hours + HUB_DWELL_HOURS)
    else:
        air_depart = t + timedelta(hours=4)

    o_loc = LOCATIONS.get(origin if chain == "DIRECT_AIR" else "HKG", hk)
    d_loc = LOCATIONS.get(dest, hk)
    flight_h = _haversine_km(o_loc, d_loc) / FLIGHT_SPEED_KMH
    air_origin = "HKG" if chain != "DIRECT_AIR" else origin
    # bind to the earliest feasible shared service when a connection is available
    air_service_id = None
    air_basis = f"great-circle {flight_h:.1f} h @ {FLIGHT_SPEED_KMH:.0f} km/h"
    if conn is not None:
        svc = _find_service(conn, "AIR", air_origin, dest, iso(air_depart))
        if svc:
            air_service_id = svc["service_id"]
            svc_depart = datetime.strptime(svc["scheduled_depart_ts"][:19], "%Y-%m-%dT%H:%M:%S")
            if svc_depart >= air_depart:
                # real forward-looking connection: snap to the service schedule
                air_depart = svc_depart
                air_basis = f"service {svc['service_no']} scheduled departure"
            else:
                # booking past the schedule horizon: bind as representative template
                air_basis = f"service {svc['service_no']} template (past schedule horizon)"
    air_arrive = air_depart + timedelta(hours=flight_h)
    add("AIR", air_origin, dest, air_depart, air_arrive, air_basis, air_service_id)

    add("TRUCK", dest, f"{dest}_METRO", air_arrive + timedelta(hours=2),
        air_arrive + timedelta(hours=2 + DELIVERY_HOURS), "metro delivery median")
    return legs



def _find_service(conn: sqlite3.Connection, mode: str, origin: str, dest: str,
                  earliest_depart: str) -> dict | None:
    """Earliest scheduled, non-cancelled service on this lane after earliest_depart.
    If the booking is past the schedule horizon (e.g. a fresh demo order booked at
    wall-clock now), fall back to the most recent service on the lane as a
    representative template so ETA can still reason about a specific service."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT service_id, service_no, scheduled_depart_ts, scheduled_arrive_ts,
               cutoff_ts, capacity_chargeable_kg, allocated_kg
        FROM dim_transport_services
        WHERE transport_mode = ? AND origin_facility = ? AND destination_facility = ?
          AND status != 'CANCELLED' AND scheduled_depart_ts >= ?
        ORDER BY scheduled_depart_ts LIMIT 1
        """,
        (mode, origin, dest, earliest_depart),
    ).fetchone()
    if row is None:
        row = conn.execute(
            """
            SELECT service_id, service_no, scheduled_depart_ts, scheduled_arrive_ts,
                   cutoff_ts, capacity_chargeable_kg, allocated_kg
            FROM dim_transport_services
            WHERE transport_mode = ? AND origin_facility = ? AND destination_facility = ?
              AND status != 'CANCELLED'
            ORDER BY scheduled_depart_ts DESC LIMIT 1
            """,
            (mode, origin, dest),
        ).fetchone()
    return dict(row) if row else None


def empirical_quantiles(conn: sqlite3.Connection, mode: str, lane: str,
                        service_no: str | None = None, month: str | None = None) -> dict[str, float]:
    """P50/P80/P95 arrival-delay minutes. Grouping tiers (most to least specific):
    service_no+lane+month -> mode+lane -> mode. Needs >=20 samples to accept a tier."""
    tiers = []
    if service_no and month:
        tiers.append((
            "SELECT delay_minutes FROM fact_shipment_legs "
            "WHERE transport_mode = ? AND origin_facility || '-' || destination_facility = ? "
            "AND voyage_flight_no = ? AND substr(planned_depart_ts,1,7) = ?",
            (mode, lane, service_no, month),
        ))
    tiers.append((
        "SELECT delay_minutes FROM fact_shipment_legs WHERE transport_mode = ? AND origin_facility || '-' || destination_facility = ?",
        (mode, lane),
    ))
    tiers.append((
        "SELECT delay_minutes FROM fact_shipment_legs WHERE transport_mode = ?", (mode,),
    ))
    for i, (sql, params) in enumerate(tiers):
        vals = sorted(v[0] for v in conn.execute(sql, params).fetchall() if v[0] is not None)
        if len(vals) >= 20:
            return {
                "p50": _quantile(vals, 0.5),
                "p80": _quantile(vals, 0.8),
                "p95": _quantile(vals, 0.95),
                "sample": len(vals),
                "grain": ["service+lane+month", "mode+lane", "mode"][min(i, 2)],
            }
    return {"p50": 0.0, "p80": 60.0, "p95": 240.0, "sample": 0, "grain": "default"}


def predict_eta(conn: sqlite3.Connection, shipment_id: str) -> dict[str, Any] | None:
    """Chain ETA with empirical delay quantiles per remaining/planned leg."""
    conn.row_factory = sqlite3.Row
    shipment = conn.execute(
        "SELECT * FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
    ).fetchone()
    if not shipment:
        return None
    shipment = dict(shipment)

    planned = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM fact_planned_legs WHERE shipment_id = ? ORDER BY leg_sequence",
            (shipment_id,),
        ).fetchall()
    ]
    if not planned:
        return None

    legs_out = []
    cursor = None  # running ETA timestamp (minutes since epoch)
    booking_min = 0.0
    for leg in planned:
        depart = datetime.strptime(leg["planned_depart_ts"][:19], "%Y-%m-%dT%H:%M:%S")
        arrive = datetime.strptime(leg["planned_arrive_ts"][:19], "%Y-%m-%dT%H:%M:%S")
        duration_min = (arrive - depart).total_seconds() / 60.0
        lane = f"{leg['origin_facility']}-{leg['destination_facility']}"
        # service-aware grouping when the planned leg points at a service
        svc_no = None
        svc_cutoff = None
        service_id = leg.get("service_id")
        if service_id:
            svc = conn.execute(
                "SELECT service_no, cutoff_ts FROM dim_transport_services WHERE service_id = ?",
                (service_id,),
            ).fetchone()
            if svc:
                svc_no = svc["service_no"] if hasattr(svc, "keys") else svc[0]
                svc_cutoff = svc["cutoff_ts"] if hasattr(svc, "keys") else svc[1]
        month = leg["planned_depart_ts"][:7]
        q = empirical_quantiles(conn, leg["transport_mode"], lane, svc_no, month)
        if cursor is None:
            booking_min = (depart - datetime(1970, 1, 1)).total_seconds() / 60.0
            cursor = booking_min
        eta = {}
        for level in ("p50", "p80", "p95"):
            # arrival = departure point + duration + quantile delay
            eta[level] = round(cursor + duration_min + q[level] - booking_min, 1)
        cursor = booking_min + eta["p50"]
        # missed cut-off risk: p80 feeder delay would push arrival past the next
        # service cut-off for connecting legs
        missed_cutoff_risk = False
        if svc_cutoff is not None:
            projected_arrive = arrive + timedelta(minutes=q["p80"])
            missed_cutoff_risk = projected_arrive.strftime("%Y-%m-%dT%H:%M:%SZ") > svc_cutoff
        legs_out.append({
            "leg_sequence": leg["leg_sequence"],
            "transport_mode": leg["transport_mode"],
            "lane": lane,
            "expected_service_no": svc_no,
            "planned_arrive_ts": leg["planned_arrive_ts"],
            "eta_minutes_from_booking": eta,
            "delay_quantiles_min": q,
            "missed_cutoff_risk": missed_cutoff_risk,
            "at_risk": q["p95"] >= RISK_THRESHOLDS_MIN["p95"] or eta["p95"] - eta["p50"] >= RISK_THRESHOLDS_MIN["p80"],
        })

    e2e = legs_out[-1]["eta_minutes_from_booking"]["p50"]
    e2e_bands = {
        level: legs_out[-1]["eta_minutes_from_booking"][level] for level in ("p50", "p80", "p95")
    }
    return {
        "shipment_id": shipment_id,
        "legs": legs_out,
        "eta_end_to_end_min": e2e,
        "eta_end_to_end_bands_min": e2e_bands,
        "at_risk": any(l["at_risk"] for l in legs_out),
        "method": "empirical-quantiles-v1 (P50 chain, P80/P95 risk bands)",
    }
