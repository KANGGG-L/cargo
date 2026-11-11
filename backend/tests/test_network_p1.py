"""P1 DES engine + event-log invariants (docs/acceptance/2026-11-09-p1-des-eventlog.md)."""

import asyncio
import os
import sqlite3

from app.agent.extra_tools import tool_simulate_disruption
from app.events.adapters import append_event, milestone_to_event
from app.events.projector import ensure_views, project_milestones

DB = os.environ["DB_PATH"]


def _rw():
    return sqlite3.connect(DB)


def _ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


# ---------------------------------------------------------------- DES engine


def test_des_deterministic():
    a = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="des"))
    b = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="des"))
    assert a.payload == b.payload


def test_priority_ordering():
    """Pharma clears meaningfully faster than general cargo under contention."""
    p = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="des")).payload
    waits = p["queue_wait_by_priority"]
    assert "PHARMA" in waits and "GENERAL" in waits
    assert waits["PHARMA"] < waits["GENERAL"]
    assert waits["GENERAL"] >= 2 * waits["PHARMA"]


def test_nonuniform_recovery():
    """The recovery/utilisation curve is not a straight line (emergent, not formulaic)."""
    p = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="des")).payload
    cleared = [d["cleared"] for d in p["capacity_utilization_curve"]]
    assert len(cleared) >= 2
    deltas = {cleared[i + 1] - cleared[i] for i in range(len(cleared) - 1)}
    assert len(deltas) > 1, f"recovery is uniform: {cleared}"


def test_scenario_distinguishable():
    """The three scenarios hit different first-loss resources."""
    typ = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="des")).payload
    yan = asyncio.run(tool_simulate_disruption("port_congestion_yantian", 240, 5, engine="des")).payload
    szx = asyncio.run(tool_simulate_disruption("border_congestion_szbp", 240, 5, engine="des")).payload
    nodes = {typ["first_loss_node"], yan["first_loss_node"], szx["first_loss_node"]}
    assert len(nodes) == 3, nodes


def test_engine_comparable():
    """engine=both returns both a DES result and a fifo baseline block."""
    p = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="both")).payload
    assert p["engine"] == "des-v1"
    assert "fifo_baseline" in p and "recovery_curve" in p["fifo_baseline"]
    assert "des_vs_fifo" in p


def test_engine_fallback_on_missing_simpy(monkeypatch):
    """If simpy import fails, the tool still answers via the fifo engine (R3)."""
    import app.simulation.des_engine as des

    def boom(*a, **k):
        raise ImportError("simpy missing")

    monkeypatch.setattr(des, "run_des_simulation", boom)
    p = asyncio.run(tool_simulate_disruption("typhoon_hkg_closure", 96, 5, engine="both")).payload
    assert p["model"].startswith("chain-fifo")


# ---------------------------------------------------------------- event log


def test_event_append_idempotent():
    conn = _rw()
    try:
        first = milestone_to_event(
            conn, shipment_id="SHP-TEST-0001", leg_id=None, code="DEP",
            event_ts="2026-01-01T00:00:00Z", source="fsu",
        )
        second = milestone_to_event(
            conn, shipment_id="SHP-TEST-0001", leg_id=None, code="DEP",
            event_ts="2026-01-01T00:00:00Z", source="fsu",
        )
        conn.commit()
        assert first is True and second is False
    finally:
        conn.close()


def test_projection_idempotent():
    """Projecting the same log twice creates nothing new the second time."""
    conn = _rw()
    try:
        append_event(
            conn, aggregate_type="SHIPMENT", aggregate_id="SHP-PROJ-0001",
            event_type="Delivered", event_ts="2026-02-02T00:00:00Z", source="fsu",
            payload={"code": "DLV", "leg_id": None},
        )
        conn.commit()
        r1 = project_milestones(conn)
        r2 = project_milestones(conn)
        assert r1["projected_milestones"] >= 1
        assert r2["projected_milestones"] == 0
    finally:
        conn.close()


def test_event_trust_level_recorded():
    conn = _rw()
    try:
        append_event(
            conn, aggregate_type="SHIPMENT", aggregate_id="SHP-TRUST-0001",
            event_type="Arrived", event_ts="2026-03-03T00:00:00Z", source="fsu",
            trust_level="unverified", payload={},
        )
        conn.commit()
        lvl = conn.execute(
            "SELECT trust_level FROM fact_event_log WHERE aggregate_id = 'SHP-TRUST-0001'"
        ).fetchone()[0]
        assert lvl == "unverified"
    finally:
        conn.close()


def test_capacity_proxy_matches_services():
    """v_capacity_state totals equal the dim_transport_services rollup."""
    conn = _ro()
    try:
        ensure_views(sqlite3.connect(DB))  # view exists in the test copy
        view_total = conn.execute("SELECT ROUND(SUM(allocated_kg), 0) FROM v_capacity_state").fetchone()[0]
        base_total = conn.execute("SELECT ROUND(SUM(allocated_kg), 0) FROM dim_transport_services").fetchone()[0]
        assert view_total == base_total
    finally:
        conn.close()
