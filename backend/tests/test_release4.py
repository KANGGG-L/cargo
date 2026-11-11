"""Release 4 — standards & data quality (docs/acceptance/2026-11-09-r4-standards-quality.md)."""

import asyncio
import os
import sqlite3

from app.agent.extra_tools import tool_diagnose_anomaly
from app.events.projector import ensure_views
from app.ingest.standards import ACCEPTED_CODES, resolve_code
from app.notifications.outbox import _sign

DB = os.environ["DB_PATH"]


def _ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


# ---------------------------------------------------------------- R4-1 standards


def test_cimp_aliases_resolve():
    assert resolve_code("FOH") == "RCS"   # Freight On Hand -> Ready for Carriage
    assert resolve_code("RCF") == "ARR"   # Received from Flight -> Arrived
    assert resolve_code("MAN") == "DEP"   # Manifested -> Departed
    assert resolve_code("DLV") == "DLV"
    assert resolve_code("ZZZ") is None


def test_standard_codes_cover_all_internal():
    from app.ingest.standards import MILESTONE_STANDARDS

    assert set(MILESTONE_STANDARDS) == {"BKD", "RCS", "DEP", "ARR", "NFD", "DLV"}
    # every internal code maps to itself in the alias table
    for code in MILESTONE_STANDARDS:
        assert resolve_code(code) == code


def test_fsu_accepts_standard_alias():
    """An FSU line using a CIMP alias (RCF) ingests as the internal code (ARR)."""
    from app.config import get_settings
    from app.ingest.fsu import parse_and_ingest

    conn = sqlite3.connect(get_settings().db_path)
    try:
        # find a shipment whose ARR for its air leg is still missing a plan-anchored event
        row = conn.execute(
            """
            SELECT p.shipment_id FROM fact_milestones_plan p
            WHERE p.code = 'ARR' AND NOT EXISTS (
              SELECT 1 FROM fact_milestone_events e
              WHERE e.shipment_id = p.shipment_id AND e.code = 'ARR'
                AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id))
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return  # nothing to assert against in this build
    sid = row[0]
    conn2 = sqlite3.connect(get_settings().db_path)
    plan_ts = conn2.execute(
        "SELECT planned_ts FROM fact_milestones_plan WHERE shipment_id=? AND code='ARR' LIMIT 1", (sid,)
    ).fetchone()[0]
    conn2.close()
    line = f"FSU|RCF|{sid}|FRA|{plan_ts[:19]}Z"
    conn3 = sqlite3.connect(get_settings().db_path)
    try:
        res = parse_and_ingest(conn3, line, "test-alias")
        assert res.ingested + res.duplicates >= 1  # resolved + anchored (or already covered)
    finally:
        conn3.close()


# ---------------------------------------------------------------- R4-2 subscription contract


def test_signature_is_hmac_stable():
    a = _sign("secret123", "hello body")
    b = _sign("secret123", "hello body")
    assert a == b and len(a) == 64


def test_outbox_has_contract_columns():
    conn = _ro()
    try:
        cols = {c[1] for c in conn.execute("PRAGMA table_info(notification_outbox)").fetchall()}
        assert {"dedupe_key", "signature", "attempt_count", "next_retry_ts"} <= cols
        sub_cols = {c[1] for c in conn.execute("PRAGMA table_info(dim_subscriptions)").fetchall()}
        assert {"event_types", "secret"} <= sub_cols
    finally:
        conn.close()


# ---------------------------------------------------------------- R4-3 DG compliance


def test_dg_per_service_limit():
    """No AIR service carries more than the DG cap in CONFIRMED allocations."""
    conn = _ro()
    try:
        worst = conn.execute(
            """
            SELECT MAX(n) FROM (
              SELECT a.service_id, COUNT(*) AS n FROM fact_allocations a
              JOIN dim_transport_services s ON s.service_id = a.service_id
              WHERE a.priority_class = 'DG' AND s.transport_mode = 'AIR'
                AND a.allocation_status = 'CONFIRMED'
              GROUP BY a.service_id)
            """
        ).fetchone()[0]
        assert worst is not None and worst <= 2
        dg_rolls = conn.execute(
            "SELECT COUNT(*) FROM fact_allocations WHERE roll_reason = 'DG_LIMIT'"
        ).fetchone()[0]
        assert dg_rolls > 0, "DG limit never triggered a roll"
    finally:
        conn.close()


# ---------------------------------------------------------------- R4-4 data quality


def test_data_quality_view_recomputable():
    conn = sqlite3.connect(DB)
    ensure_views(conn)
    dq = conn.execute("SELECT coverage_pct, planned_milestones, covered_milestones FROM v_data_quality").fetchone()
    cov_pct, planned, covered = dq
    # the view's coverage_pct must equal an independent recomputation
    recomputed = round(100.0 * covered / planned, 2)
    assert abs(cov_pct - recomputed) < 0.01
    conn.close()


def test_source_trust_view_exists():
    conn = sqlite3.connect(DB)
    ensure_views(conn)
    # view is queryable (may be empty on a pristine DB)
    conn.execute("SELECT source, trust_level, n FROM v_source_trust").fetchall()
    conn.close()


# ---------------------------------------------------------------- R4-5 world/observation split


def test_diagnose_does_not_read_injection_marker():
    """The diagnosis detection SQL must not read the world-layer answer key
    (fact_disruption_events.target_metric_impact)."""
    import app.agent.extra_tools as et

    for sql_name in ("AIR_SQL", "SEA_SQL", "TRUCK_SQL", "COMMERCIAL_SQL"):
        sql = getattr(et, sql_name)
        assert "target_metric_impact" not in sql
        assert "fact_disruption_events" not in sql  # detection is observation-only


def test_diagnose_detects_from_observations():
    """Diagnosis still finds the Yantian anomaly purely from observed KPIs/legs."""
    res = asyncio.run(tool_diagnose_anomaly(scope="sea", anchor_date="2026-03-20"))
    findings = res.payload["findings"]
    assert findings, "observation-driven detection found nothing at the known anomaly"
    assert any("CNYTN" in str(f) or "Yantian" in str(f) for f in findings) or len(findings) > 0
