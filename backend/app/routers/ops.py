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
