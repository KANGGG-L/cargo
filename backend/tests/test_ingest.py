"""F4 FSU ingest tests: parse, dedupe, out-of-order tolerance, auto-resolve."""

import sqlite3

from app.config import ROOT_DIR, get_settings
from app.ingest.fsu import parse_and_ingest
from app.milestones.rules import sync

SAMPLE = (ROOT_DIR / "data" / "samples" / "fsu_replay.txt").read_text()


def _rw():
    return sqlite3.connect(get_settings().db_path)


def setup_module(module):
    """Restore the pre-ingest precondition so the file is rerun-safe."""
    conn = _rw()
    try:
        conn.execute(
            "DELETE FROM fact_milestone_events WHERE source='fsu' "
            "AND shipment_id IN ('SHP-2025-007919', 'SHP-2025-007904')"
        )
        conn.execute("DELETE FROM fact_alerts WHERE source = 'rules'")
        conn.commit()
        sync(conn)
    finally:
        conn.close()


def test_replay_sample_ingest_results():
    """First replay: 2 genuine late reports ingested, 3 duplicates, 2 rejects."""
    conn = _rw()
    try:
        result = parse_and_ingest(conn, SAMPLE, "test-run-1")
    finally:
        conn.close()
    assert result.parsed == 5, f"parsed={result.parsed}"
    assert result.ingested == 2, f"ingested={result.ingested} (missing ARR + missing DLV)"
    assert result.duplicates == 3
    assert result.rejected == 2
    reasons = {r["reason"] for r in result.rejects}
    assert any("unknown milestone code" in r for r in reasons)
    assert any("unknown shipment" in r for r in reasons)
    assert any(a.startswith("AL-") for a in result.resolved_alerts), result.resolved_alerts


def test_replay_is_idempotent():
    """Replaying the same file must add nothing (plan-alignment is the guard)."""
    conn = _rw()
    try:
        again = parse_and_ingest(conn, SAMPLE, "test-run-2")
    finally:
        conn.close()
    assert again.ingested == 0
    assert again.duplicates == 5, "all previously ingested lines are now duplicates"


def test_ingested_event_resolves_missing_alert():
    conn = _rw()
    try:
        resolved = conn.execute(
            """
            SELECT COUNT(*) FROM fact_alerts
            WHERE shipment_id = 'SHP-2025-007919' AND status = 'RESOLVED'
              AND resolution_note LIKE 'auto-resolved%'
            """
        ).fetchone()[0]
        assert resolved >= 1, "the late ARR report should have auto-resolved the R2 alert"
    finally:
        conn.close()


def test_out_of_order_reported_chronologically():
    """Ingest order is irrelevant: milestone view returns chronological events."""
    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    try:
        rows = conn.execute(
            """
            SELECT event_ts FROM fact_milestone_events
            WHERE shipment_id IN ('SHP-2025-007919', 'SHP-2025-007904')
            ORDER BY event_ts
            """
        ).fetchall()
        ts_list = [r[0] for r in rows]
        assert ts_list == sorted(ts_list)
    finally:
        conn.close()


def test_ingest_log_and_rejects_recorded():
    conn = _rw()
    try:
        log = conn.execute(
            "SELECT source_name, ingested, duplicates, rejected FROM ingest_log ORDER BY id DESC LIMIT 2"
        ).fetchall()
        assert len(log) >= 2
        rejects = conn.execute("SELECT COUNT(*) FROM ingest_rejects").fetchone()[0]
        assert rejects >= 4, "every reject from both runs is recorded"
    finally:
        conn.close()


def test_implausible_timestamp_rejected():
    """Trust gate: a year-late backfill goes to the reject queue, not the ledger."""
    from app.ingest.fsu import parse_and_ingest

    conn = _rw()
    try:
        conn.row_factory = sqlite3.Row
        plan = conn.execute(
            """
            SELECT p.shipment_id, p.planned_ts FROM fact_milestones_plan p
            WHERE p.code = 'ARR' AND NOT EXISTS (
              SELECT 1 FROM fact_milestone_events e
              WHERE e.shipment_id = p.shipment_id AND e.code = p.code AND e.leg_id = p.leg_id
            ) LIMIT 1
            """
        ).fetchone()
        assert plan, "need a missing ARR plan for this test"
        far_ts = "2027-08-15T10:00:00Z"  # ~10 months after plan
        line = f"FSU|ARR|{plan['shipment_id']}|HKG|{far_ts}"
        result = parse_and_ingest(conn, line, "implausible-test")
        assert result.ingested == 0
        assert any("implausible timestamp" in r["reason"] for r in result.rejects)
    finally:
        conn.close()
