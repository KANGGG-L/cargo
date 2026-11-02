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


def build_planned_legs(shipment: dict[str, Any], booked_ts: str) -> list[dict[str, Any]]:
    """Schedule template by chain type — durations from network medians, air
    duration from great-circle distance at 850 km/h."""
    origin = shipment["origin_location"]
    dest = shipment["destination_location"]
    chain = shipment["transport_chain_type"]
    hk = LOCATIONS["HKG"]
    t = datetime.strptime(booked_ts[:19], "%Y-%m-%dT%H:%M:%S")

    def iso(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    legs: list[dict[str, Any]] = []
    seq = 1

    def add(mode: str, o: str, d: str, depart: datetime, arrive: datetime, basis: str):
        nonlocal seq
        legs.append({
            "leg_sequence": seq, "transport_mode": mode, "origin_facility": o,
            "destination_facility": d, "carrier_code": "CX" if mode == "AIR" else (
                "Feeder_Line_A" if mode == "SEA" else "CrossBorder_Fleet_B"),
            "planned_depart_ts": iso(depart), "planned_arrive_ts": iso(arrive),
            "basis": basis,
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
    air_arrive = air_depart + timedelta(hours=flight_h)
    add("AIR", "HKG" if chain != "DIRECT_AIR" else origin, dest,
        air_depart, air_arrive,
        f"great-circle {flight_h:.1f} h @ {FLIGHT_SPEED_KMH:.0f} km/h")

    add("TRUCK", dest, f"{dest}_METRO", air_arrive + timedelta(hours=2),
        air_arrive + timedelta(hours=2 + DELIVERY_HOURS), "metro delivery median")
    return legs



def empirical_quantiles(conn: sqlite3.Connection, mode: str, lane: str) -> dict[str, float]:
    """P50/P80/P95 arrival-delay minutes for a mode+lane bucket, mode fallback."""
    for sql, params in (
        (
            "SELECT delay_minutes FROM fact_shipment_legs WHERE transport_mode = ? AND origin_facility || '-' || destination_facility = ?",
            (mode, lane),
        ),
        ("SELECT delay_minutes FROM fact_shipment_legs WHERE transport_mode = ?", (mode,)),
    ):
        vals = sorted(v[0] for v in conn.execute(sql, params).fetchall() if v[0] is not None)
        if len(vals) >= 20:
            return {
                "p50": _quantile(vals, 0.5),
                "p80": _quantile(vals, 0.8),
                "p95": _quantile(vals, 0.95),
                "sample": len(vals),
            }
    return {"p50": 0.0, "p80": 60.0, "p95": 240.0, "sample": 0}


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
        q = empirical_quantiles(conn, leg["transport_mode"], lane)
        if cursor is None:
            booking_min = (depart - datetime(1970, 1, 1)).total_seconds() / 60.0
            cursor = booking_min
        eta = {}
        for level in ("p50", "p80", "p95"):
            # arrival = departure point + duration + quantile delay
            eta[level] = round(cursor + duration_min + q[level] - booking_min, 1)
        cursor = booking_min + eta["p50"]
        legs_out.append({
            "leg_sequence": leg["leg_sequence"],
            "transport_mode": leg["transport_mode"],
            "lane": lane,
            "planned_arrive_ts": leg["planned_arrive_ts"],
            "eta_minutes_from_booking": eta,
            "delay_quantiles_min": q,
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
