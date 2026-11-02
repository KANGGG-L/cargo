"""SSE chat endpoint for the control tower agent."""

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.loop import run_agent_stream
from app.config import is_mock_mode

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(req: ChatRequest) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        try:
            async for ev in run_agent_stream(
                req.message, [m.model_dump() for m in req.history]
            ):
                yield _sse(ev)
        except Exception as e:  # never leave the stream hanging
            yield _sse({"type": "error", "content": f"agent crashed: {e}"})
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/mode")
async def mode() -> dict[str, str]:
    return {"llm_mode": "mock" if is_mock_mode() else "live"}
