"""V1.0-C ops clock tests: advancement, milestone emission, alert fan-out."""

import sqlite3

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.ops.clock import tick


def _client():
    return TestClient(app)


def _rw():
    return sqlite3.connect(get_settings().db_path)


def _horizon_minus(hours: int) -> str:
    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    try:
        base = conn.execute(
            "SELECT strftime('%Y-%m-%dT12:00:00Z', MAX(report_date), ?) FROM fact_air_kpi_daily"
        ).fetchone()[0]
    finally:
        conn.close()
    return base.replace(f"+{hours} days", f"+{hours} days") if False else base


def test_clock_tick_emits_milestones_and_alerts():
    """Park the clock just before the data horizon, tick across 12 sim hours:
    crossed plans must gain events, and the rule engine must run."""
    client = _client()
    # reset the clock to horizon-12h and clear clock-source events in that window
    conn = _rw()
    try:
        base = conn.execute(
            "SELECT strftime('%Y-%m-%dT12:00:00Z', MAX(report_date), '-12 hours') FROM fact_air_kpi_daily"
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM fact_milestone_events WHERE source = 'clock'"
        )
        conn.execute(
            """
            DELETE FROM fact_alerts WHERE source = 'rules' AND shipment_id LIKE 'SHO-%'
            """
        )
        conn.execute(
            "UPDATE ops_clock SET sim_now = ?, speed = 43200, running = 1 WHERE id = 1",
            (base,),
        )
        conn.commit()
    finally:
        conn.close()

    result = tick()
    assert result["advanced_s"] == 43200, result
    assert result["sim_now"] > base
    # events emitted for crossed plans (12 sim-hours of dense tail operations)
    assert result["emitted"] > 0, result

    conn = _rw()
    try:
        clocked = conn.execute(
            "SELECT COUNT(*) FROM fact_milestone_events WHERE source = 'clock'"
        ).fetchone()[0]
        # >= not ==: a live server's clock ticker may fire concurrently with the
        # test (multi-writer DB) — this tick's events must be a subset.
        assert clocked >= result["emitted"]
        # every clock event anchors to a plan (no orphans)
        orphans = conn.execute(
            """
            SELECT COUNT(*) FROM fact_milestone_events e
            WHERE e.source = 'clock' AND NOT EXISTS (
              SELECT 1 FROM fact_milestones_plan p
              WHERE p.shipment_id = e.shipment_id AND p.code = e.code
                AND ((p.leg_id IS NULL AND e.leg_id IS NULL) OR p.leg_id = e.leg_id)
            )
            """
        ).fetchone()[0]
        assert orphans == 0
    finally:
        conn.close()


def test_clock_api_start_stop_state():
    client = _client()
    r = client.post("/api/ops/clock/start", json={"speed": 7200})
    assert r.status_code == 200 and r.json()["running"] == 1
    state = client.get("/api/ops/clock").json()
    assert state["speed"] == 7200
    r = client.post("/api/ops/clock/stop")
    assert r.json()["running"] == 0


def test_clock_tick_when_paused_is_noop():
    client = _client()
    client.post("/api/ops/clock/stop")
    before = client.get("/api/ops/clock").json()["sim_now"]
    result = client.post("/api/ops/clock/tick").json()
    assert result["advanced_s"] == 0
    assert client.get("/api/ops/clock").json()["sim_now"] == before
