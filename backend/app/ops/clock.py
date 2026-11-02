"""Ops clock (V1.0-C): a runtime simulation clock that makes the control tower
*run* instead of sit still.

Advancing sim time crosses planned milestones; every crossed plan without an
event gets one emitted (source='clock', anchored to the plan row), then the
rule engine and notification fan-out run — exactly the production event
pipeline, just fed by the clock instead of a real FSU feed.
"""

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings

_TICK_INTERVAL_S = 1.0
_task: asyncio.Task | None = None  # module-global; one clock task per process


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _now_real() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_state() -> dict[str, Any]:
    conn = _conn()
    try:
        row = conn.execute("SELECT * FROM ops_clock WHERE id = 1").fetchone()
        if not row:
            raise RuntimeError("ops_clock row missing — run scripts/init_db.py")
        return dict(row)
    finally:
        conn.close()


def set_state(sim_now: str | None = None, speed: int | None = None, running: int | None = None) -> dict:
    conn = _conn()
    try:
        state = get_state_from(conn)
        new_sim = sim_now or state["sim_now"]
        new_speed = speed if speed is not None else state["speed"]
        new_running = running if running is not None else state["running"]
        conn.execute(
            "UPDATE ops_clock SET sim_now = ?, speed = ?, running = ?, last_tick_ts = ? WHERE id = 1",
            (new_sim, new_speed, new_running, _now_real()),
        )
        conn.commit()
        return get_state_from(conn)
    finally:
        conn.close()


def get_state_from(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM ops_clock WHERE id = 1").fetchone()
    if not row:
        raise RuntimeError("ops_clock row missing")
    return dict(row)


def _emit_for_plan(conn: sqlite3.Connection, plan: dict[str, Any], event_ts: str) -> bool:
    """Anchor an event to a specific plan row (same contract as FSU ingest)."""
    already = conn.execute(
        """
        SELECT 1 FROM fact_milestone_events e
        WHERE e.shipment_id = ? AND e.code = ?
          AND ((e.leg_id IS NULL AND ? IS NULL) OR e.leg_id = ?)
        """,
        (plan["shipment_id"], plan["code"], plan["leg_id"], plan["leg_id"]),
    ).fetchone()
    if already:
        return False
    key = hashlib.sha1(
        f"{plan['code']}|{plan['shipment_id']}|{plan['leg_id'] or ''}|{event_ts}".encode()
    ).hexdigest()
    try:
        conn.execute(
            "INSERT INTO fact_milestone_events (shipment_id, leg_id, code, event_ts, source, dedupe_key)"
            " VALUES (?, ?, ?, ?, 'clock', ?)",
            (plan["shipment_id"], plan["leg_id"], plan["code"], event_ts, key),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def tick() -> dict[str, Any]:
    """Advance the clock by one tick and emit crossed milestones + alerts."""
    conn = _conn()
    try:
        state = get_state_from(conn)
        if not state["running"]:
            return {"advanced_s": 0, "emitted": 0, "sim_now": state["sim_now"]}

        prev = datetime.strptime(state["sim_now"][:19], "%Y-%m-%dT%H:%M:%S")
        now = prev + timedelta(seconds=state["speed"] * _TICK_INTERVAL_S)
        now_s = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        # milestone plans crossed by this tick, still without events
        crossed = conn.execute(
            """
            SELECT p.shipment_id, p.leg_id, p.code, p.planned_ts FROM fact_milestones_plan p
            WHERE p.planned_ts > ? AND p.planned_ts <= ?
              AND NOT EXISTS (
                SELECT 1 FROM fact_milestone_events e
                WHERE e.shipment_id = p.shipment_id AND e.code = p.code
                  AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
              )
            ORDER BY p.planned_ts
            LIMIT 500
            """,
            (state["sim_now"], now_s),
        ).fetchall()

        emitted = 0
        for plan in crossed:
            event_ts = plan["planned_ts"] if plan["planned_ts"] <= now_s else now_s
            if _emit_for_plan(conn, dict(plan), event_ts):
                emitted += 1

        conn.execute(
            "UPDATE ops_clock SET sim_now = ?, last_tick_ts = ? WHERE id = 1",
            (now_s, _now_real()),
        )
        conn.commit()
    finally:
        conn.close()

    # rule engine + notification fan-out on the new event state
    if emitted:
        from app.milestones.rules import sync
        from app.notifications.outbox import enqueue_for_alerts

        rw = sqlite3.connect(get_settings().db_path)
        try:
            result = sync(rw)
            enqueue_for_alerts(result.get("alerts", []))
        finally:
            rw.close()

    return {"advanced_s": state["speed"] * _TICK_INTERVAL_S, "emitted": emitted, "sim_now": now_s}


async def _loop():
    while True:
        await asyncio.sleep(_TICK_INTERVAL_S)
        state = get_state()
        if not state["running"]:
            continue
        try:
            await asyncio.to_thread(tick)
        except Exception:  # never let a bad tick kill the clock
            continue


def ensure_task() -> None:
    """Start the background ticker (must be called from the event loop)."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(_loop())


def stop_task() -> None:
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
    _task = None
