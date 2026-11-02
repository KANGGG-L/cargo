"""Chain-coupled disruption simulation over the real shipment network (v2).

Scenario-aware: each event type has a "first-loss node + propagation edge"
configuration instead of sharing one closure model.

- hkg_closure: hub airport closes → HKG air departures inside the window are
  cancelled (severity-scaled); inbound feeder legs arriving during the closure
  are held at the hub.
- port_congestion_yantian: Yantian feeder berths congest → CNYTN departures are
  held, so the air connections their shipments feed into are missed and that
  cargo joins the re-accommodation backlog.
- border_congestion_szbp: Shenzhen Bay checkpoint stalls cross-border trucks →
  same propagation with the SZX truck feeder.

Affected air cargo then clears through FIFO re-accommodation at a
capacity-constrained daily recovery rate. Deterministic — no RNG anywhere.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

SURGE_CAPACITY = 1.3
BASELINE_DAYS = 90

SCENARIOS: dict[str, dict[str, str]] = {
    "typhoon_hkg_closure": {"loss_mode": "AIR", "loss_origin": "HKG"},
    "port_congestion_yantian": {"loss_mode": "SEA", "loss_origin": "CNYTN"},
    "border_congestion_szbp": {"loss_mode": "TRUCK", "loss_origin": "SZX"},
}


@dataclass
class Scenario:
    event_type: str
    start: datetime
    duration_hours: int
    severity: int  # 1..5


def _ts(s: str) -> datetime:
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _quantile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, round(q * (len(sorted_vals) - 1))))
    return round(sorted_vals[idx], 1)


def run_chain_simulation(conn: sqlite3.Connection, scenario: Scenario) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    cfg = SCENARIOS[scenario.event_type]
    end = scenario.start + timedelta(hours=scenario.duration_hours)
    start_s, end_s = _iso(scenario.start), _iso(end)

    # ---- baseline daily air throughput departing HKG
    row = conn.execute(
        """
        SELECT COUNT(*) AS n,
               julianday(MAX(planned_depart_ts)) - julianday(MIN(planned_depart_ts)) AS span,
               COALESCE(SUM(s.total_chargeable_weight_kg), 0) AS weight_kg
        FROM fact_shipment_legs l JOIN dim_shipments s ON s.shipment_id = l.shipment_id
        WHERE l.transport_mode = 'AIR' AND l.origin_facility = 'HKG'
        """
    ).fetchone()
    span_days = max(row["span"] or 548, 1)
    legs_per_day = row["n"] / span_days

    # ---- first-loss legs: the mode/origin the scenario hits, departing in-window
    first_loss = [
        dict(l)
        for l in conn.execute(
            """
            SELECT l.leg_id, l.shipment_id, l.leg_sequence, l.transport_mode,
                   l.origin_facility, l.destination_facility, l.planned_depart_ts,
                   l.planned_arrive_ts, s.total_chargeable_weight_kg,
                   s.contracted_revenue_usd
            FROM fact_shipment_legs l JOIN dim_shipments s ON s.shipment_id = l.shipment_id
            WHERE l.transport_mode = :mode AND l.origin_facility = :origin
              AND l.planned_depart_ts >= :start AND l.planned_depart_ts <= :end
            ORDER BY l.planned_depart_ts
            """,
            {"mode": cfg["loss_mode"], "origin": cfg["loss_origin"],
             "start": start_s, "end": end_s},
        ).fetchall()
    ]

    delays: list[float] = []
    held_first_loss = 0
    affected_shipments: set[str] = set()
    revenue_at_risk = 0.0
    per_lane: dict[str, dict[str, Any]] = {}

    if cfg["loss_mode"] == "AIR":  # hub-closure: first loss IS the air departure
        # hub closure: first-loss legs ARE the air departures — cancelled
        cancel_rate = min(0.3 + 0.14 * scenario.severity, 0.95)
        n_cancel = int(len(first_loss) * cancel_rate)
        cancelled_air = first_loss[:n_cancel]
        for leg in cancelled_air:
            affected_shipments.add(leg["shipment_id"])
            revenue_at_risk += leg["contracted_revenue_usd"] or 0.0
            lane = f"HKG-{leg['destination_facility']}"
            per_lane.setdefault(lane, {"lane": lane, "affected_legs": 0, "tonnes": 0.0})
            per_lane[lane]["affected_legs"] += 1
            per_lane[lane]["tonnes"] += (leg["total_chargeable_weight_kg"] or 0) / 1000.0
        cancelled_air_legs, held_feeder_legs = len(cancelled_air), 0

        # inbound feeders arriving during closure are held at the hub
        inbound = conn.execute(
            """
            SELECT leg_id, planned_arrive_ts FROM fact_shipment_legs
            WHERE transport_mode IN ('SEA', 'TRUCK') AND destination_facility = 'HKG'
              AND planned_arrive_ts >= :start AND planned_arrive_ts <= :end
            """,
            {"start": start_s, "end": end_s},
        ).fetchall()
        for l in inbound:
            delays.append(round((end - _ts(l["planned_arrive_ts"])).total_seconds() / 60.0, 1))
            held_feeder_legs += 1
    else:
        # feeder congestion: first-loss feeder departures are held; their
        # shipments' HKG air connections are missed → FIFO backlog
        cancelled_air_legs, held_feeder_legs = 0, len(first_loss)
        affected_air: dict[str, dict[str, Any]] = {}
        feeder_origin = cfg["loss_origin"]
        for fl in first_loss:
            held_min = (end - _ts(fl["planned_depart_ts"])).total_seconds() / 60.0
            delays.append(round(held_min, 1))
            affected_shipments.add(fl["shipment_id"])
            revenue_at_risk += fl["contracted_revenue_usd"] or 0.0
            lane = f"{feeder_origin}-HKG"
            per_lane.setdefault(lane, {"lane": lane, "affected_legs": 0, "tonnes": 0.0})
            per_lane[lane]["affected_legs"] += 1
            per_lane[lane]["tonnes"] += (fl["total_chargeable_weight_kg"] or 0) / 1000.0

            # propagation edge: feeder arrival slips to window end → does the
            # shipment's air connection (sequence = feeder seq + 1) still hold?
            air = conn.execute(
                """
                SELECT l.leg_id, l.shipment_id, l.destination_facility, l.planned_depart_ts,
                       s.total_chargeable_weight_kg, s.contracted_revenue_usd
                FROM fact_shipment_legs l JOIN dim_shipments s ON s.shipment_id = l.shipment_id
                WHERE l.shipment_id = :sid AND l.leg_sequence = :seq + 1 AND l.transport_mode = 'AIR'
                """,
                {"sid": fl["shipment_id"], "seq": fl["leg_sequence"]},
            ).fetchone()
            if not air:
                continue
            delayed_feeder_arrive = _ts(fl["planned_arrive_ts"]) + timedelta(minutes=held_min)
            if delayed_feeder_arrive + timedelta(hours=2) > _ts(air["planned_depart_ts"]):
                affected_air[air["leg_id"]] = dict(air)
                cancelled_air_legs += 1
                affected_shipments.add(air["shipment_id"])
        cancelled_air = list(affected_air.values())

    # ---- FIFO re-accommodation of the affected air legs after reopening
    reopened = end
    daily_recover = max(
        1, int(legs_per_day * SURGE_CAPACITY * (1.15 - 0.05 * scenario.severity))
    )
    ordered = sorted(cancelled_air, key=lambda l: l["planned_depart_ts"])
    backlog_tonnes_total = sum((l.get("total_chargeable_weight_kg") or 0) for l in ordered) / 1000.0

    for i, leg in enumerate(ordered):
        slot_day = i // daily_recover + 1
        effective = max(reopened + timedelta(days=slot_day - 1), _ts(leg["planned_depart_ts"]))
        delays.append(round((effective - _ts(leg["planned_depart_ts"])).total_seconds() / 60.0, 1))

    backlog_curve, remaining = [], len(ordered)
    day = 0
    if remaining == 0:
        backlog_curve.append({"day": "D+1", "backlog_tonnes": 0.0})
    while remaining > 0:
        remaining = max(0, remaining - daily_recover)
        day += 1
        backlog_curve.append({
            "day": f"D+{day}",
            "backlog_tonnes": round(backlog_tonnes_total * remaining / max(len(ordered), 1), 1),
        })

    delays_sorted = sorted(delays)
    return {
        "scenario": scenario.event_type,
        "first_loss_node": f"{cfg['loss_mode']}@{cfg['loss_origin']}",
        "window": {"start": start_s, "end": end_s, "duration_hours": scenario.duration_hours},
        "severity": scenario.severity,
        "affected_shipments": len(affected_shipments),
        "cancelled_air_legs": cancelled_air_legs,
        "held_feeder_legs": held_feeder_legs,
        "delay_quantiles_min": {
            "p50": _quantile(delays_sorted, 0.5),
            "p80": _quantile(delays_sorted, 0.8),
            "p95": _quantile(delays_sorted, 0.95),
            "max": delays_sorted[-1] if delays_sorted else 0.0,
        },
        "revenue_at_risk_usd": round(revenue_at_risk, 2),
        "backlog_tonnes_by_day": backlog_curve,
        "per_lane": sorted(per_lane.values(), key=lambda x: -x["affected_legs"]),
        "notes": [
            f"First-loss node: {cfg['loss_mode']}@{cfg['loss_origin']}; "
            f"recovery {daily_recover} air departures/day ({SURGE_CAPACITY}× baseline, severity-adjusted).",
            f"Affected shipments: {len(affected_shipments)}; revenue at risk ${round(revenue_at_risk, 2):,.0f}.",
        ],
        "model": "chain-fifo-v2 (scenario-aware)",
    }
