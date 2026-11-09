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
    duration_hours: int | None = None,
    severity: int = 4,
    start_date: str | None = None,
    engine: str = "fifo",
) -> ToolResult:
    from datetime import datetime

    from app.simulation.chain import Scenario as ChainScenario, run_chain_simulation
    from app.simulation.des_engine import Scenario as DesScenario, run_des_simulation

    if event_type not in SCENARIO_WINDOWS:
        return ToolResult(
            summary="unknown scenario",
            payload={"error": f"unknown scenario {event_type}"},
            llm_digest=f"Unknown scenario {event_type}. Options: {list(SCENARIO_WINDOWS)}.",
        )
    if engine not in ("fifo", "des", "both"):
        engine = "both"
    default_start, default_hours = SCENARIO_WINDOWS[event_type]
    start_s = start_date or default_start
    duration = duration_hours or default_hours
    start = datetime.strptime(start_s[:19], "%Y-%m-%dT%H:%M:%S")

    conn = _ro()
    try:
        fifo = None
        des = None
        if engine in ("fifo", "both"):
            fifo = run_chain_simulation(
                conn, ChainScenario(event_type, start, duration, severity)
            )
        if engine in ("des", "both"):
            # DES import is optional: if simpy is missing, fall back to fifo (R3)
            try:
                des = run_des_simulation(
                    conn, DesScenario(event_type, start, duration, severity)
                )
            except ImportError:
                des = None
                if fifo is None:
                    fifo = run_chain_simulation(
                        conn, ChainScenario(event_type, start, duration, severity)
                    )
        horizon = _data_horizon(conn)
    finally:
        conn.close()

    # primary result = DES when available, else fifo (DES answers network questions)
    primary = des or fifo
    payload = {
        **primary,
        "as_of_data_horizon": horizon,
        "recovery_curve": primary["backlog_tonnes_by_day"],
        "affected_legs": primary["cancelled_air_legs"],
        "engine_requested": engine,
    }
    if engine == "both" and fifo is not None and des is not None:
        payload["fifo_baseline"] = {
            "model": fifo["model"],
            "clearance_days": len(fifo["backlog_tonnes_by_day"]),
            "recovery_curve": fifo["backlog_tonnes_by_day"],
            "delay_quantiles_min": fifo["delay_quantiles_min"],
        }
        payload["des_vs_fifo"] = {
            "des_model": des["model"],
            "des_clearance_by_priority": des.get("clearance_day_by_priority", {}),
            "des_queue_wait_by_priority": des.get("queue_wait_by_priority", {}),
        }

    q = primary["delay_quantiles_min"]
    extra = ""
    if des is not None:
        cdp = des.get("clearance_day_by_priority", {})
        if cdp:
            extra = (
                " Priority clearance: "
                + ", ".join(f"{k} {v}" for k, v in sorted(cdp.items()))
                + "."
            )
    digest = (
        f"Disruption simulation ({event_type}, {duration} h, severity {severity}/5, "
        f"engine={engine}): {primary['affected_shipments']} shipments affected; "
        f"delay P50 {q['p50']} min / P80 {q['p80']} / P95 {q['p95']}; "
        f"revenue at risk ${primary['revenue_at_risk_usd']:,.0f}. "
        f"Model: {primary['model']}.{extra} "
        + " ".join(primary["notes"][-2:])
    )
    return ToolResult(
        summary=(
            f"{primary['affected_shipments']} shipments · "
            f"${primary['revenue_at_risk_usd'] / 1e6:.2f}M at risk · "
            f"P95 delay {q['p95'] / 60:.1f} h · {primary['model'].split(' ')[0]}"
        ),
        payload=payload,
        llm_digest=digest,
    )


SCENARIO_WINDOWS = {
    # planted disruption windows -> anchor the simulation on real history
    "typhoon_hkg_closure": ("2025-09-15T00:00:00Z", 96),
    "port_congestion_yantian": ("2026-03-01T00:00:00Z", 240),
    "border_congestion_szbp": ("2025-11-10T00:00:00Z", 240),
}



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
            "engine": {
                "type": "string",
                "enum": ["fifo", "des", "both"],
                "description": "fifo = chain heuristic baseline; des = discrete-event resource model; both = A/B compare.",
            },
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
    shipment_id: str, title: str, detail: str = "", severity: str = "medium",
    confirmation_token: str | None = None,
) -> ToolResult:
    from app.agent.governance import (
        audit_tool_call, confirmation_token as make_token, verify_confirmation,
    )

    args = {"shipment_id": shipment_id, "title": title, "detail": detail, "severity": severity}
    # R5-2: a write cannot fire without an explicit confirmation token. First call
    # returns the token + a preview; the agent must call again echoing the token.
    if not verify_confirmation("raise_alert", args, confirmation_token):
        token = make_token("raise_alert", args)
        audit_tool_call("raise_alert", "write", args, confirmed=False,
                        result_summary="unconfirmed — token issued", source_text=detail)
        return ToolResult(
            summary="confirmation required",
            payload={"requires_confirmation": True, "confirmation_token": token, "preview": args},
            llm_digest=(
                f"raise_alert needs confirmation before it writes a ticket for {shipment_id}. "
                f"To proceed, call raise_alert again with the same arguments plus "
                f"confirmation_token=\"{token}\". This human-in-the-loop gate prevents an "
                f"unverified document field from silently becoming a booked exception."
            ),
        )

    conn = sqlite3.connect(get_settings().db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
        ).fetchone()
        if not exists:
            audit_tool_call("raise_alert", "write", args, confirmed=True,
                            result_summary="rejected — unknown shipment", source_text=detail)
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

    audit_tool_call("raise_alert", "write", args, confirmed=True,
                    result_summary=f"created {alert_id}", source_text=detail)
    return ToolResult(
        summary=f"{alert_id} · {severity}",
        payload={"alert_id": alert_id, "shipment_id": shipment_id, "severity": severity, "title": title},
        llm_digest=f"Alert {alert_id} created (severity {severity}) for {shipment_id}: {title}. The operations workbench will pick it up.",
    )


RAISE_ALERT_SPEC = ToolSpec(
    name="raise_alert",
    description="Create an exception ticket in the alert workbench from a diagnosis finding. WRITE tool: the first call returns a confirmation_token; call again echoing it to commit (human-in-the-loop gate).",
    parameters={
        "type": "object",
        "properties": {
            "shipment_id": {"type": "string"},
            "title": {"type": "string", "description": "One-line summary of the exception."},
            "detail": {"type": "string", "description": "Evidence and recommended action."},
            "severity": {"type": "string", "enum": ["info", "medium", "high"]},
            "confirmation_token": {"type": "string", "description": "Echo the token from the first call to commit the write."},
        },
        "required": ["shipment_id", "title"],
    },
    executor=tool_raise_alert,
)


# --------------------------------------------------------------------------
# predict_eta: empirical-quantile ETA for booked orders (V1.0-B)


async def tool_predict_eta(shipment_id: str) -> ToolResult:
    from app.tracking.eta import predict_eta

    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    try:
        result = predict_eta(conn, shipment_id)
    finally:
        conn.close()
    if result is None:
        return ToolResult(
            summary="no planned legs",
            payload={"error": f"{shipment_id} has no planned legs (not booked via workbench)"},
            llm_digest=f"{shipment_id} has no planned chain to predict against — book it via the order workbench first.",
        )

    e2e_h = result["eta_end_to_end_min"] / 60.0
    risky = [l for l in result["legs"] if l["at_risk"]]
    digest = (
        f"ETA prediction ({result['method']}) for {shipment_id}: "
        f"end-to-end P50 {e2e_h / 24:.1f} d from booking"
        + (f"; {len(risky)} leg(s) at risk: " + ", ".join(l["lane"] for l in risky) if risky else "; no legs flagged at risk")
        + ". Per-leg P50/P80/P95 delay quantiles come from the empirical history of the same mode+lane."
    )
    return ToolResult(
        summary=f"P50 {e2e_h / 24:.1f} d · {'at risk' if result['at_risk'] else 'on plan'}",
        payload=result,
        llm_digest=digest,
    )


PREDICT_ETA_SPEC = ToolSpec(
    name="predict_eta",
    description="Predict end-to-end ETA for a booked order using empirical delay quantiles (P50/P80/P95) per mode+lane from operating history.",
    parameters={
        "type": "object",
        "properties": {"shipment_id": {"type": "string"}},
        "required": ["shipment_id"],
    },
    executor=tool_predict_eta,
)


# --------------------------------------------------------------------------
# P2 network tools: network_load / capacity_impact / reroute_options / manifest_lookup


async def tool_network_load(scope: str = "HKG", date_from: str | None = None,
                            date_to: str | None = None) -> ToolResult:
    """Current load and backlog for a hub or lane over a window."""
    conn = _ro()
    try:
        where = "WHERE 1=1"
        params: dict[str, Any] = {}
        if scope and scope != "ALL":
            where += " AND (origin_facility = :scope OR destination_facility = :scope)"
            params["scope"] = scope
        if date_from:
            where += " AND scheduled_depart_ts >= :df"
            params["df"] = date_from
        if date_to:
            where += " AND scheduled_depart_ts <= :dt"
            params["dt"] = date_to
        row = conn.execute(
            f"""
            SELECT COUNT(*) AS services,
                   SUM(CASE WHEN status='CANCELLED' THEN 1 ELSE 0 END) AS cancelled,
                   ROUND(SUM(allocated_kg),1) AS allocated_kg,
                   ROUND(SUM(capacity_chargeable_kg),1) AS capacity_kg,
                   ROUND(100.0*SUM(allocated_kg)/NULLIF(SUM(capacity_chargeable_kg),0),1) AS load_pct
            FROM dim_transport_services {where}
            """,
            params,
        ).fetchone()
        by_mode = conn.execute(
            f"""SELECT transport_mode, COUNT(*),
                   ROUND(100.0*SUM(allocated_kg)/NULLIF(SUM(capacity_chargeable_kg),0),1)
                FROM dim_transport_services {where} GROUP BY transport_mode""",
            params,
        ).fetchall()
    finally:
        conn.close()
    payload = {
        "scope": scope,
        "services": row[0], "cancelled_services": row[1],
        "allocated_kg": row[2], "capacity_kg": row[3], "load_pct": row[4],
        "by_mode": [{"mode": m, "services": n, "load_pct": lp} for m, n, lp in by_mode],
    }
    digest = (
        f"Network load for {scope}: {row[0]} services ({row[1]} cancelled), "
        f"{row[4]}% chargeable-weight utilisation "
        f"({row[2]:,.0f}/{row[3]:,.0f} kg). "
        + "; ".join(f"{m} {lp}%" for m, n, lp in by_mode)
    )
    return ToolResult(summary=f"{scope}: {row[4]}% load · {row[1]} cancelled", payload=payload, llm_digest=digest)


async def tool_capacity_impact(event_type: str = "typhoon_hkg_closure",
                               severity: int = 5, engine: str = "des") -> ToolResult:
    """Clearance day and rolled count per priority class after a disruption."""
    res = await tool_simulate_disruption(event_type, None, severity, engine=engine)
    p = res.payload
    payload = {
        "event_type": event_type, "severity": severity, "engine": p.get("engine", engine),
        "affected_shipments": p["affected_shipments"],
        "clearance_day_by_priority": p.get("clearance_day_by_priority", {}),
        "queue_wait_by_priority": p.get("queue_wait_by_priority", {}),
        "rolled_shipments": p.get("rolled_shipments"),
        "revenue_at_risk_usd": p["revenue_at_risk_usd"],
    }
    cdp = p.get("clearance_day_by_priority", {})
    digest = (
        f"Capacity impact ({event_type}, severity {severity}): "
        f"{p['affected_shipments']} shipments affected, "
        f"revenue at risk ${p['revenue_at_risk_usd']:,.0f}. "
        + ("Clearance by priority: " + ", ".join(f"{k} {v}" for k, v in sorted(cdp.items())) + "." if cdp else "")
    )
    return ToolResult(summary=f"{p['affected_shipments']} shipments · {len(cdp)} priority tiers", payload=payload, llm_digest=digest)


async def tool_reroute_options(shipment_id: str, at_ts: str | None = None) -> ToolResult:
    """Alternative feasible services for a shipment's air leg after a missed cut-off."""
    conn = _ro()
    try:
        row = conn.execute(
            """
            SELECT l.destination_facility, l.planned_depart_ts, a.service_id
            FROM fact_shipment_legs l
            LEFT JOIN fact_allocations a ON a.leg_id = l.leg_id
            WHERE l.shipment_id = ? AND l.transport_mode = 'AIR' LIMIT 1
            """,
            (shipment_id,),
        ).fetchone()
        if not row:
            return ToolResult(
                summary="no air leg", payload={"error": f"no air leg for {shipment_id}"},
                llm_digest=f"{shipment_id} has no air leg to reroute.")
        dest, pdep, cur_service = row
        after = at_ts or pdep
        alts = conn.execute(
            """
            SELECT service_id, service_no, scheduled_depart_ts, cutoff_ts,
                   ROUND(100.0*allocated_kg/NULLIF(capacity_chargeable_kg,0),1) AS load_pct
            FROM dim_transport_services
            WHERE transport_mode='AIR' AND origin_facility='HKG' AND destination_facility=?
              AND status != 'CANCELLED' AND scheduled_depart_ts > ?
            ORDER BY scheduled_depart_ts LIMIT 5
            """,
            (dest, after),
        ).fetchall()
    finally:
        conn.close()
    options = [
        {"service_id": s[0], "service_no": s[1], "depart": s[2], "cutoff": s[3],
         "load_pct": s[4], "has_room": (s[4] or 0) < 100}
        for s in alts
    ]
    digest = (
        f"Reroute options for {shipment_id} (HKG→{dest}) after {after}: "
        + (", ".join(f"{o['service_no']} @ {o['depart']} ({o['load_pct']}% full)" for o in options)
           if options else "no alternative services found in the schedule.")
    )
    return ToolResult(
        summary=f"{len(options)} option(s) to {dest}",
        payload={"shipment_id": shipment_id, "destination": dest, "current_service": cur_service, "options": options},
        llm_digest=digest,
    )


async def tool_manifest_lookup(service_id: str) -> ToolResult:
    """MAWB/HAWB + ULD manifest for a service."""
    conn = _ro()
    try:
        svc = conn.execute(
            "SELECT service_no, transport_mode, origin_facility, destination_facility, status "
            "FROM dim_transport_services WHERE service_id = ?", (service_id,),
        ).fetchone()
        if not svc:
            return ToolResult(summary="service not found", payload={"error": f"unknown service {service_id}"},
                              llm_digest=f"No service {service_id}.")
        allocs = conn.execute(
            """SELECT shipment_id, mawb_no, hawb_no, priority_class, allocated_weight_kg, allocation_status
               FROM fact_allocations WHERE service_id = ? ORDER BY priority_class LIMIT 100""",
            (service_id,),
        ).fetchall()
        ulds = conn.execute(
            "SELECT uld_id, uld_type, max_weight_kg FROM dim_ulds WHERE service_id = ?", (service_id,),
        ).fetchall()
    finally:
        conn.close()
    payload = {
        "service_id": service_id, "service_no": svc[0], "mode": svc[1],
        "lane": f"{svc[2]}-{svc[3]}", "status": svc[4],
        "shipments": len(allocs),
        "allocations": [
            {"shipment_id": a[0], "mawb_no": a[1], "hawb_no": a[2],
             "priority_class": a[3], "weight_kg": a[4], "status": a[5]} for a in allocs
        ],
        "ulds": [{"uld_id": u[0], "uld_type": u[1], "max_weight_kg": u[2]} for u in ulds],
    }
    digest = (
        f"Manifest for {svc[0]} ({service_id}, {svc[2]}→{svc[3]}, status {svc[4]}): "
        f"{len(allocs)} shipments across {len(ulds)} ULDs."
    )
    return ToolResult(summary=f"{svc[0]} · {len(allocs)} shipments · {len(ulds)} ULDs", payload=payload, llm_digest=digest)


NETWORK_LOAD_SPEC = ToolSpec(
    name="network_load",
    description="Current capacity load and backlog for a hub or lane over a date window (uses the shared-service schedule).",
    parameters={
        "type": "object",
        "properties": {
            "scope": {"type": "string", "description": "Facility code (HKG, CNYTN, LAX...) or ALL."},
            "date_from": {"type": "string"}, "date_to": {"type": "string"},
        },
    },
    executor=tool_network_load,
)

CAPACITY_IMPACT_SPEC = ToolSpec(
    name="capacity_impact",
    description="After a disruption, how many shipments roll and when each priority class clears (discrete-event model).",
    parameters={
        "type": "object",
        "properties": {
            "event_type": {"type": "string", "enum": ["typhoon_hkg_closure", "port_congestion_yantian", "border_congestion_szbp"]},
            "severity": {"type": "integer", "minimum": 1, "maximum": 5},
            "engine": {"type": "string", "enum": ["fifo", "des", "both"]},
        },
    },
    executor=tool_capacity_impact,
)

REROUTE_SPEC = ToolSpec(
    name="reroute_options",
    description="List alternative feasible services for a shipment's air leg after a missed cut-off or cancellation.",
    parameters={
        "type": "object",
        "properties": {
            "shipment_id": {"type": "string"},
            "at_ts": {"type": "string", "description": "ISO timestamp; only services departing after this are returned."},
        },
        "required": ["shipment_id"],
    },
    executor=tool_reroute_options,
)

MANIFEST_SPEC = ToolSpec(
    name="manifest_lookup",
    description="MAWB/HAWB and ULD manifest for a transport service (which shipments ride it).",
    parameters={
        "type": "object",
        "properties": {"service_id": {"type": "string"}},
        "required": ["service_id"],
    },
    executor=tool_manifest_lookup,
)
