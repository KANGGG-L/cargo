"""The control tower's three specialist tools.

All computations are deterministic queries over the star schema so that the
same question always produces the same evidence (demo + interview safe).
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.agent.tools import ToolResult, ToolSpec
from app.config import get_settings

# --------------------------------------------------------------------------
# helpers


def _ro() -> sqlite3.Connection:
    path = get_settings().db_path
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn


def _data_horizon(conn: sqlite3.Connection) -> str:
    return conn.execute("SELECT MAX(report_date) FROM fact_air_kpi_daily").fetchone()[0]


# --------------------------------------------------------------------------
# diagnose_anomaly


def _deviation(conn: sqlite3.Connection, sql: str, params: tuple) -> list[dict[str, Any]]:
    return [dict(zip([c[0] for c in conn.execute(sql, params).description], row))
            for row in conn.execute(sql, params).fetchall()]


AIR_SQL = """
WITH recent AS (
  SELECT route_lane, ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS recent_otp,
         ROUND(AVG(cargo_load_factor) * 100.0, 1) AS recent_lf,
         SUM(cancelled_flights) AS recent_cancellations
  FROM fact_air_kpi_daily
  WHERE report_date > DATE(:anchor, '-14 days') AND report_date <= :anchor
  GROUP BY route_lane
),
baseline AS (
  SELECT route_lane, ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS baseline_otp
  FROM fact_air_kpi_daily
  WHERE report_date > DATE(:anchor, '-104 days') AND report_date <= DATE(:anchor, '-14 days')
  GROUP BY route_lane
)
SELECT r.route_lane, r.recent_otp, b.baseline_otp,
       ROUND(b.baseline_otp - r.recent_otp, 1) AS otp_drop_pp,
       r.recent_lf, r.recent_cancellations
FROM recent r JOIN baseline b ON r.route_lane = b.route_lane
WHERE b.baseline_otp - r.recent_otp > 8
ORDER BY otp_drop_pp DESC
"""

SEA_SQL = """
WITH recent AS (
  SELECT origin_facility AS port, COUNT(*) AS legs,
         ROUND(AVG(delay_minutes) / 60.0, 1) AS recent_delay_h,
         ROUND(100.0 * SUM(CASE WHEN delay_minutes <= 240 THEN 1 ELSE 0 END) / COUNT(*), 1) AS recent_otp
  FROM fact_shipment_legs
  WHERE transport_mode = 'SEA' AND planned_depart_ts >= DATETIME(:anchor_ts, '-14 days')
    AND planned_depart_ts <= DATETIME(:anchor_ts, '+1 day')
  GROUP BY origin_facility
),
baseline AS (
  SELECT origin_facility AS port, ROUND(AVG(delay_minutes) / 60.0, 1) AS baseline_delay_h
  FROM fact_shipment_legs
  WHERE transport_mode = 'SEA'
    AND planned_depart_ts >= DATETIME(:anchor_ts, '-104 days')
    AND planned_depart_ts < DATETIME(:anchor_ts, '-14 days')
  GROUP BY origin_facility
)
SELECT r.port, r.legs, r.recent_delay_h, b.baseline_delay_h,
       ROUND(r.recent_delay_h - b.baseline_delay_h, 1) AS delay_increase_h, r.recent_otp
FROM recent r JOIN baseline b ON r.port = b.port
WHERE r.recent_delay_h - b.baseline_delay_h > 4
ORDER BY delay_increase_h DESC
"""

COMMERCIAL_SQL = """
WITH recent AS (
  SELECT destination_location AS dest, COUNT(*) AS shipments,
         ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 1) AS recent_margin
  FROM dim_shipments
  WHERE booking_ts >= DATETIME(:anchor_ts, '-30 days') AND booking_ts <= DATETIME(:anchor_ts, '+1 day')
  GROUP BY destination_location
),
baseline AS (
  SELECT destination_location AS dest,
         ROUND(100.0 * (SUM(contracted_revenue_usd) - SUM(actual_cost_usd)) / SUM(contracted_revenue_usd), 1) AS baseline_margin
  FROM dim_shipments
  WHERE booking_ts >= DATETIME(:anchor_ts, '-120 days') AND booking_ts < DATETIME(:anchor_ts, '-30 days')
  GROUP BY destination_location
)
SELECT r.dest, r.shipments, r.recent_margin, b.baseline_margin,
       ROUND(r.recent_margin - b.baseline_margin, 1) AS margin_drop_pp
FROM recent r JOIN baseline b ON r.dest = b.dest
WHERE r.recent_margin - b.baseline_margin < -8
ORDER BY margin_drop_pp ASC
"""

TRUCK_SQL = """
WITH recent AS (
  SELECT checkpoint, ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS recent_otp,
         ROUND(AVG(avg_crossing_minutes), 0) AS recent_crossing_min,
         ROUND(AVG(queue_backlog_trucks), 0) AS recent_backlog
  FROM fact_truck_kpi_daily
  WHERE report_date > DATE(:anchor, '-7 days') AND report_date <= :anchor
  GROUP BY checkpoint
),
baseline AS (
  SELECT checkpoint, ROUND(AVG(on_time_arrival_rate) * 100.0, 1) AS baseline_otp,
         ROUND(AVG(avg_crossing_minutes), 0) AS baseline_crossing_min
  FROM fact_truck_kpi_daily
  WHERE report_date > DATE(:anchor, '-67 days') AND report_date <= DATE(:anchor, '-7 days')
  GROUP BY checkpoint
)
SELECT r.checkpoint, r.recent_otp, b.baseline_otp,
       ROUND(b.baseline_otp - r.recent_otp, 1) AS otp_drop_pp,
       r.recent_crossing_min, b.baseline_crossing_min, r.recent_backlog
FROM recent r JOIN baseline b ON r.checkpoint = b.checkpoint
WHERE b.baseline_otp - r.recent_otp > 8
ORDER BY otp_drop_pp DESC
"""

EVENTS_SQL = """
SELECT event_code, event_category, primary_location, start_timestamp, end_timestamp, description
FROM fact_disruption_events
WHERE end_timestamp >= DATETIME(:anchor_ts, '-30 days') AND start_timestamp <= DATETIME(:anchor_ts, '+1 day')
"""


async def tool_diagnose_anomaly(
    scope: str = "all", anchor_date: str | None = None
) -> ToolResult:
    conn = _ro()
    try:
        anchor = anchor_date or _data_horizon(conn)
        anchor_ts = f"{anchor}T12:00:00Z"
        findings: list[dict[str, Any]] = []

        if scope in ("all", "air"):
            findings += [
                {**r, "metric": "air_otp"} for r in _deviation(conn, AIR_SQL, {"anchor": anchor})
            ]
        if scope in ("all", "sea"):
            findings += [
                {**r, "metric": "sea_delay"} for r in _deviation(conn, SEA_SQL, {"anchor_ts": anchor_ts})
            ]
        if scope in ("all", "truck"):
            findings += [
                {**r, "metric": "truck_otp"} for r in _deviation(conn, TRUCK_SQL, {"anchor": anchor})
            ]
        if scope in ("all", "commercial"):
            findings += [
                {**r, "metric": "gross_margin"} for r in _deviation(conn, COMMERCIAL_SQL, {"anchor_ts": anchor_ts})
            ]

        events = [dict(zip([c[0] for c in conn.execute(EVENTS_SQL, {"anchor_ts": anchor_ts}).description], row))
                  for row in conn.execute(EVENTS_SQL, {"anchor_ts": anchor_ts}).fetchall()]
    finally:
        conn.close()

    if not findings:
        digest = f"No KPI deviations beyond threshold as of {anchor}."
        payload = {"anchor": anchor, "findings": [], "overlapping_events": events}
        return ToolResult(
            summary="no anomalies detected",
            payload=payload,
            llm_digest=digest,
        )

    lines = [f"- {f['metric']}: {f.get('route_lane') or f.get('port') or f.get('dest')} "
             f"(baseline {f.get('baseline_otp', f.get('baseline_delay_h', f.get('baseline_margin')))} → "
             f"recent {f.get('recent_otp', f.get('recent_delay_h', f.get('recent_margin')))})" for f in findings]
    event_lines = [f"- {e['event_code']} at {e['primary_location']} ({e['start_timestamp'][:10]} → {e['end_timestamp'][:10]})" for e in events]
    digest = (
        f"KPI deviations vs baseline as of {anchor}:\n" + "\n".join(lines)
        + "\nOverlapping disruption events:\n" + ("\n".join(event_lines) if event_lines else "- none on record")
    )
    return ToolResult(
        summary=f"{len(findings)} finding(s), {len(events)} event(s) in window",
        payload={"anchor": anchor, "findings": findings, "overlapping_events": events},
        llm_digest=digest,
    )


DIAGNOSE_SPEC = ToolSpec(
    name="diagnose_anomaly",
    description="Compare recent KPIs against their baseline, attribute deviations to known disruption events and propose process improvements. Use for 'why did X drop' questions.",
    parameters={
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["all", "air", "sea", "truck", "commercial"],
                "description": "Which KPI families to scan. Default 'all'.",
            },
            "anchor_date": {
                "type": "string",
                "description": "Optional ISO date (YYYY-MM-DD) to diagnose 'as of' a historical moment. Defaults to the latest data date.",
            },
        },
    },
    executor=tool_diagnose_anomaly,
)


# --------------------------------------------------------------------------
# simulate_disruption


async def tool_simulate_disruption(
    event_type: str = "typhoon_hkg_closure",
    duration_hours: int = 48,
    severity: int = 4,
) -> ToolResult:
    conn = _ro()
    try:
        horizon = _data_horizon(conn)
        stats = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM fact_shipment_legs
                WHERE transport_mode = 'AIR' AND origin_facility = 'HKG') AS total_air_legs,
              (SELECT julianday(MAX(planned_depart_ts)) - julianday(MIN(planned_depart_ts))
                 FROM fact_shipment_legs WHERE transport_mode = 'AIR') AS span_days,
              (SELECT SUM(total_chargeable_weight_kg) FROM dim_shipments) AS total_weight_kg,
              (SELECT SUM(contracted_revenue_usd) FROM dim_shipments) AS total_revenue_usd,
              (SELECT COUNT(*) FROM dim_shipments) AS total_shipments,
              (SELECT AVG(scheduled_trips) FROM fact_truck_kpi_daily) AS avg_daily_truck_trips
            """
        ).fetchone()
        total_air_legs, span_days, total_weight_kg, total_revenue, total_shipments, avg_daily_truck_trips = stats
        span_days = max(span_days or 548, 1)
        legs_per_day = total_air_legs / span_days
        tonnes_per_day = (total_weight_kg / span_days) / 1000.0
        revenue_per_tonne = total_revenue / (total_weight_kg / 1000.0)
        avg_daily_truck_trips = avg_daily_truck_trips or 50.0

        if event_type == "port_congestion_yantian":
            uplift = 1.0 + 0.08 * severity
            affected_legs = int(legs_per_day * 0.4 * duration_hours / 24 * 2)  # 40% of feeders touch CNYTN
            delay_hours = round(12 + 14 * severity, 1)
            rate_note = f"Yantian feeder spot rates estimated +{int((uplift - 1) * 100)}% while congestion lasts"
            mode = "SEA"
        elif event_type == "border_congestion_szbp":
            # Cross-border truck congestion at Shenzhen Bay: SZX feeder trucks queue,
            # missed HKG connections cascade into the air network downstream.
            affected_legs = int(avg_daily_truck_trips / 3 * duration_hours / 24)  # ~1/3 of trips use SZBP
            delay_hours = round(2 + 1.2 * severity, 1)
            rate_note = (
                "Trucking spot cost rises 10-25% (queue hours are unpaid but demurrage at factories accrues); "
                "downstream air legs absorb the missed connections as next-day rebooking"
            )
            mode = "TRUCK"
        else:  # typhoon_hkg_closure (default)
            affected_legs = int(legs_per_day * duration_hours / 24)
            delay_hours = round(18 + 16 * severity, 1)
            rate_note = "spot air rates typically spike 15-30% after reopening as backlog clears"
            mode = "AIR"

        backlog_tonnes = round(tonnes_per_day * duration_hours / 24 * (1 + 0.15 * (severity - 3)), 1)
        revenue_at_risk_musd = round(backlog_tonnes * revenue_per_tonne / 1e6, 2)
        surge_capacity = tonnes_per_day * 1.3  # post-event recovery assumption
        recovery_days = max(1, int(backlog_tonnes / surge_capacity + 0.999))

        curve, remaining = [], backlog_tonnes
        for day in range(recovery_days + 1):
            curve.append({"day": f"D+{day}", "backlog_tonnes": round(remaining, 1)})
            remaining = max(0.0, remaining - surge_capacity)
    finally:
        conn.close()

    payload = {
        "scenario": event_type,
        "mode": mode,
        "duration_hours": duration_hours,
        "severity": severity,
        "affected_legs": affected_legs,
        "avg_delay_hours": delay_hours,
        "backlog_tonnes": backlog_tonnes,
        "revenue_at_risk_musd": revenue_at_risk_musd,
        "recovery_days": recovery_days,
        "recovery_curve": curve,
        "as_of_data_horizon": horizon,
    }
    digest = (
        f"Simulation ({event_type}, {duration_hours}h, severity {severity}/5): "
        f"{affected_legs} {mode.lower()} legs affected, avg delay {delay_hours} h, backlog {backlog_tonnes} t, "
        f"revenue at risk ${revenue_at_risk_musd}M, backlog clears in {recovery_days} days at 130% surge capacity. "
        f"Market note: {rate_note}."
    )
    return ToolResult(
        summary=f"{affected_legs} legs · ${revenue_at_risk_musd}M at risk · {recovery_days}d recovery",
        payload=payload,
        llm_digest=digest,
    )


SIMULATE_SPEC = ToolSpec(
    name="simulate_disruption",
    description="Quantified what-if simulation of a disruption: affected shipments, delays, revenue at risk and a backlog-recovery curve. Deterministic.",
    parameters={
        "type": "object",
        "properties": {
            "event_type": {
                "type": "string",
                "enum": ["typhoon_hkg_closure", "port_congestion_yantian", "border_congestion_szbp"],
            },
            "duration_hours": {"type": "integer", "minimum": 6, "maximum": 240},
            "severity": {"type": "integer", "minimum": 1, "maximum": 5},
        },
    },
    executor=tool_simulate_disruption,
)


# --------------------------------------------------------------------------
# quote_booking


async def tool_quote_booking(
    origin: str, destination: str, weight_kg: float, mode: str = "auto"
) -> ToolResult:
    conn = _ro()
    try:
        mode = mode.lower()
        legs: list[dict[str, Any]] = []

        def rate_for(m: str, o: str, d: str, w: float) -> dict[str, Any] | None:
            rows = conn.execute(
                """
                SELECT rate_id, weight_break, base_rate_usd
                FROM fact_rate_cards
                WHERE transport_mode = :m AND origin_zone = :o AND dest_zone = :d
                """,
                {"m": m, "o": o, "d": d},
            ).fetchall()
            if not rows:
                return None
            # Standard tariff semantics: pick the cheapest *rate line* for the
            # shipment (per-kg weight breaks vs per-container options), subject
            # to the MINimum charge floor.
            min_floor = next((r[2] for r in rows if r[1] == "MIN"), 0.0)
            rate_lines = [
                r for r in rows
                if r[1] != "MIN"
                and (
                    r[1] in ("PER_FEU", "PER_TRUCK")
                    or (r[1] == "+300KG" and w >= 300)
                    or (r[1] == "+1000KG" and w >= 1000)
                    or r[1] == "+0KG"
                )
            ]
            candidates = rate_lines or rows

            def eff_charge(r) -> float:
                if r[1] in ("PER_FEU", "PER_TRUCK"):
                    return r[2]  # flat per-container charge
                return max(min_floor, r[2] * w)

            best = min(candidates, key=eff_charge)
            return {
                "rate_id": best[0],
                "weight_break": best[1],
                "rate_usd": best[2],
                "charge_usd": round(eff_charge(best), 2),
            }

        def transit_days(m: str, o: str, d: str) -> float | None:
            row = conn.execute(
                """
                SELECT ROUND(AVG(julianday(actual_arrive_ts) - julianday(actual_depart_ts)), 1)
                FROM fact_shipment_legs
                WHERE transport_mode = :m AND origin_facility = :o AND destination_facility = :d
                """,
                {"m": m, "o": o, "d": d},
            ).fetchone()
            return row[0] if row and row[0] is not None else None

        chain = []
        if mode in ("sea_air", "auto") and origin not in ("HKG",):
            chain.append(("sea", origin, "HKG"))
        chain.append(("air", "HKG", destination))

        total = 0.0
        for m, o, d in chain:
            q = rate_for(m.upper(), o, d, weight_kg)
            if q is None:
                return ToolResult(
                    summary="no rate card for this lane",
                    payload={"error": f"no {m} rate card for {o}->{d}"},
                    llm_digest=f"No {m} rate card exists for {o}→{d}; cannot quote.",
                )
            t = transit_days(m.upper(), o, d)
            legs.append({"mode": m, "origin": o, "dest": d, **q,
                         "avg_transit_days": t})
            total += q["charge_usd"]
    finally:
        conn.close()

    transit_total = sum(l["avg_transit_days"] or 0 for l in legs)
    payload = {
        "origin": origin,
        "destination": destination,
        "chargeable_weight_kg": weight_kg,
        "legs": legs,
        "total_usd": round(total, 2),
        "estimated_transit_days": round(transit_total, 1),
    }
    leg_lines = "\n".join(
        f"- {l['mode'].upper()} {l['origin']}→{l['dest']}: ${l['charge_usd']} "
        f"({l['weight_break']} @ ${l['rate_usd']}, avg transit {l['avg_transit_days']} d)"
        for l in legs
    )
    digest = (
        f"Quote {origin}→{destination}, {weight_kg} kg, {'+'.join(l['mode'] for l in legs)} chain: "
        f"total ${round(total, 2)}, estimated door-to-airport transit {round(transit_total, 1)} days.\n{leg_lines}"
    )
    return ToolResult(
        summary=f"${round(total, 2)} · {round(transit_total, 1)} d · {'+'.join(l['mode'] for l in legs)}",
        payload=payload,
        llm_digest=digest,
    )


QUOTE_SPEC = ToolSpec(
    name="quote_booking",
    description="Freight quote by lane and weight break (air / sea / truck / sea-air combination) with transit-time estimates from historical leg performance.",
    parameters={
        "type": "object",
        "properties": {
            "origin": {"type": "string", "description": "Origin code, e.g. CNYTN, CNSHA, HKG."},
            "destination": {"type": "string", "description": "Destination code, e.g. LAX, LHR, FRA."},
            "weight_kg": {"type": "number", "minimum": 1},
            "mode": {
                "type": "string",
                "enum": ["auto", "air", "sea_air"],
                "description": "'auto' adds a sea feeder leg when origin is a GBA/South China port.",
            },
        },
        "required": ["origin", "destination", "weight_kg"],
    },
    executor=tool_quote_booking,
)


# --------------------------------------------------------------------------
# raise_alert: agent findings → exception ticket (closes the analysis→action loop)


async def tool_raise_alert(
    shipment_id: str, title: str, detail: str = "", severity: str = "medium"
) -> ToolResult:
    conn = sqlite3.connect(get_settings().db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        if not exists:
            return ToolResult(
                summary="shipment not found",
                payload={"error": f"unknown shipment {shipment_id}"},
                llm_digest=f"Cannot raise alert: shipment {shipment_id} does not exist.",
            )
        if severity not in ("info", "medium", "high"):
            severity = "medium"
        n = int((conn.execute("SELECT MAX(alert_id) FROM fact_alerts").fetchone()[0] or "AL-000000").split("-")[1]) + 1
        alert_id = f"AL-{n:06d}"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """
            INSERT INTO fact_alerts (alert_id, shipment_id, rule_id, source, severity,
                                     title, detail, status, created_ts, updated_ts)
            VALUES (?, ?, NULL, 'agent', ?, ?, ?, 'OPEN', ?, ?)
            """,
            (alert_id, shipment_id, severity, title[:120], detail[:500], now, now),
        )
        conn.commit()
    finally:
        conn.close()

    return ToolResult(
        summary=f"{alert_id} · {severity}",
        payload={"alert_id": alert_id, "shipment_id": shipment_id, "severity": severity, "title": title},
        llm_digest=f"Alert {alert_id} created (severity {severity}) for {shipment_id}: {title}. The operations workbench will pick it up.",
    )


RAISE_ALERT_SPEC = ToolSpec(
    name="raise_alert",
    description="Create an exception ticket in the alert workbench from a diagnosis finding, so operations can act on it.",
    parameters={
        "type": "object",
        "properties": {
            "shipment_id": {"type": "string"},
            "title": {"type": "string", "description": "One-line summary of the exception."},
            "detail": {"type": "string", "description": "Evidence and recommended action."},
            "severity": {"type": "string", "enum": ["info", "medium", "high"]},
        },
        "required": ["shipment_id", "title"],
    },
    executor=tool_raise_alert,
)
