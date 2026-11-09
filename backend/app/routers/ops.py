"""Ops clock endpoints (V1.0-C)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.ops import clock

router = APIRouter(prefix="/api/ops", tags=["ops"])


class ClockStart(BaseModel):
    speed: int = Field(default=3600, ge=1, le=86400, description="sim seconds per real second")
    sim_now: str | None = Field(default=None, max_length=30)


@router.get("/clock")
def clock_state():
    return clock.get_state()


@router.post("/clock/start")
def clock_start(req: ClockStart):
    # the ticker task lives in the app lifespan; this only resumes the clock
    return clock.set_state(speed=req.speed, running=1, sim_now=req.sim_now)


@router.post("/clock/stop")
def clock_stop():
    return clock.set_state(running=0)


@router.post("/clock/reset")
def clock_reset(req: ClockStart):
    state = clock.set_state(sim_now=req.sim_now, running=0, speed=req.speed)
    return state


@router.post("/clock/tick")
def clock_tick():
    """Manual single tick — deterministic hook for tests and demos."""
    return clock.tick()


@router.get("/metrics")
def ops_metrics():
    """SLO/observability panel (R5-4): rule hit counts, agent tool success +
    confirmation gate, webhook delivery, access-log volume. Each figure is a
    re-computable SQL aggregate."""
    import sqlite3

    from app.config import get_settings

    conn = sqlite3.connect(f"file:{get_settings().db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        def scalar(sql):
            r = conn.execute(sql).fetchone()
            return r[0] if r else 0

        alerts_by_status = {
            r["status"]: r["n"]
            for r in conn.execute("SELECT status, COUNT(*) AS n FROM fact_alerts GROUP BY status")
        }
        tool_audit = [
            dict(r) for r in conn.execute(
                "SELECT tool_name, tool_kind, confirmed, COUNT(*) AS n "
                "FROM fact_agent_tool_audit GROUP BY tool_name, tool_kind, confirmed"
            )
        ]
        outbox = {
            "sent": scalar("SELECT COUNT(*) FROM notification_outbox WHERE sent_ts IS NOT NULL"),
            "pending": scalar("SELECT COUNT(*) FROM notification_outbox WHERE sent_ts IS NULL"),
            "retrying": scalar("SELECT COUNT(*) FROM notification_outbox WHERE attempt_count > 0 AND sent_ts IS NULL"),
        }
        access = {
            "total": scalar("SELECT COUNT(*) FROM fact_access_log"),
            "denied_401_403": scalar("SELECT COUNT(*) FROM fact_access_log WHERE status IN (401, 403)"),
        }
        return {
            "alerts_by_status": alerts_by_status,
            "agent_tool_audit": tool_audit,
            "webhook_outbox": outbox,
            "access_log": access,
        }
    finally:
        conn.close()
