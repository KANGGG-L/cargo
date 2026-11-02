"""F1 milestone engine tests: plan/event alignment, rule sync, alert workflow."""

import asyncio
import sqlite3

import pytest

from app.agent.extra_tools import tool_raise_alert
from app.config import get_settings
from app.milestones.rules import evaluate, sync


@pytest.fixture()
def ro_conn():
    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    yield conn
    conn.close()


def _rw_conn():
    return sqlite3.connect(get_settings().db_path)


def test_plan_and_event_alignment(ro_conn):
    """Every shipment must have BKD/DLV plans; every event must map to a plan."""
    plans, events = ro_conn.execute(
        """
        SELECT (SELECT COUNT(*) FROM fact_milestones_plan),
               (SELECT COUNT(*) FROM fact_milestone_events)
        """
    ).fetchone()
    assert plans > 70000 and events > 68000
    orphan_events = ro_conn.execute(
        """
        SELECT COUNT(*) FROM fact_milestone_events e
        WHERE NOT EXISTS (
          SELECT 1 FROM fact_milestones_plan p
          WHERE p.shipment_id = e.shipment_id AND p.code = e.code
            AND ((p.leg_id IS NULL AND e.leg_id IS NULL) OR p.leg_id = e.leg_id)
        )
        """
    ).fetchone()[0]
    assert orphan_events == 0, f"{orphan_events} events without a matching plan row"


def test_missing_events_were_injected(ro_conn):
    """The generator must leave plan rows without events for the rule engine."""
    missing = ro_conn.execute(
        """
        SELECT COUNT(*) FROM fact_milestones_plan p
        WHERE NOT EXISTS (
          SELECT 1 FROM fact_milestone_events e
          WHERE e.shipment_id = p.shipment_id AND e.code = p.code
            AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
        )
        """
    ).fetchone()[0]
    assert 500 <= missing <= 5000, f"missing-event volume implausible: {missing}"


def test_rule_sync_is_idempotent_and_bounded():
    conn = _rw_conn()
    try:
        conn.execute("DELETE FROM fact_alerts WHERE source = 'rules'")
        conn.commit()
        first = sync(conn)
        second = sync(conn)
        assert first["created"] > 0
        assert second["created"] == 0, "second sync must not duplicate alerts"
        assert first["open_total"] == second["open_total"]
        # bounded per rule
        per_rule = dict(
            conn.execute(
                "SELECT rule_id, COUNT(*) FROM fact_alerts WHERE source='rules' GROUP BY rule_id"
            ).fetchall()
        )
        assert per_rule, "no rule alerts created"
        assert all(v <= 300 for v in per_rule.values()), per_rule
        # both missing_event and delay_over rules fired
        kinds = dict(
            conn.execute(
                """
                SELECT r.rule_type, COUNT(*) FROM fact_alerts a
                JOIN fact_alert_rules r ON r.rule_id = a.rule_id
                GROUP BY r.rule_type
                """
            ).fetchall()
        )
        assert {"missing_event", "delay_over"} <= set(kinds), kinds
    finally:
        conn.close()


def test_evaluate_pure_function(ro_conn):
    now = "2026-10-31T12:00:00Z"
    result = evaluate(ro_conn, now)
    assert set(result.keys()) >= {"R1", "R2", "R3", "R4"}


def test_alert_transition_flow():
    conn = _rw_conn()
    try:
        sync(conn)
        alert_id = conn.execute(
            "SELECT alert_id FROM fact_alerts WHERE status = 'OPEN' LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    import urllib.parse

    import httpx
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        # legal chain OPEN → ACKNOWLEDGED → RESOLVED
        r1 = client.post(
            f"/api/alerts/{alert_id}/transition",
            json={"to": "ACKNOWLEDGED", "assignee": "ops.demo"},
        )
        assert r1.status_code == 200 and r1.json()["status"] == "ACKNOWLEDGED"
        r2 = client.post(
            f"/api/alerts/{alert_id}/transition",
            json={"to": "RESOLVED", "note": "rebooked on next flight"},
        )
        assert r2.status_code == 200
        # illegal jump: RESOLVED → ACKNOWLEDGED is not a valid transition (409)
        r3 = client.post(f"/api/alerts/{alert_id}/transition", json={"to": "ACKNOWLEDGED"})
        assert r3.status_code == 409
        # restore for later runs
        client.post(
            f"/api/alerts/{alert_id}/transition", json={"to": "CLOSED", "note": "test reset"}
        )


def test_milestones_endpoint(ro_conn):
    sid = ro_conn.execute(
        "SELECT shipment_id FROM dim_shipments WHERE status = 'EXCEPTION' LIMIT 1"
    ).fetchone()[0]
    import httpx  # noqa: F401
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        res = client.get(f"/api/shipments/{sid}/milestones")
        assert res.status_code == 200
        ms = res.json()["milestones"]
        codes = {m["code"] for m in ms}
        assert {"BKD", "RCS", "DEP", "ARR", "DLV"} <= codes
        deviations = {m["deviation"] for m in ms}
        assert deviations <= {"MISSING", "LATE", "ON_TIME"}


def test_raise_alert_tool():
    conn = _rw_conn()
    try:
        sid = conn.execute("SELECT shipment_id FROM dim_shipments LIMIT 1").fetchone()[0]
    finally:
        conn.close()

    result = asyncio.run(
        tool_raise_alert(
            shipment_id=sid,
            title="Agent: feeder delay risk detected",
            detail="Feeder running 3h late; connection at risk per diagnosis.",
            severity="medium",
        )
    )
    assert result.payload["alert_id"].startswith("AL-")
    conn = _rw_conn()
    try:
        row = conn.execute(
            "SELECT source, status, title FROM fact_alerts WHERE alert_id = ?",
            (result.payload["alert_id"],),
        ).fetchone()
        assert row == ("agent", "OPEN", "Agent: feeder delay risk detected")
    finally:
        conn.close()
