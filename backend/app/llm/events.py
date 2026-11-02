"""Provider-agnostic streaming events shared by live and mock LLM backends."""

from dataclasses import dataclass


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCallChunk:
    """Incremental tool-call arguments (streamed by index)."""

    index: int
    call_id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class StreamEnd:
    finish_reason: str  # "tool_calls" | "stop"


StreamEvent = TextDelta | ToolCallChunk | StreamEnd
