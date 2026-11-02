"""Hand-rolled async function-calling loop driving the multi-tool agent.

Yields SSE-ready event dicts:
  {"type": "token", "content": str}
  {"type": "tool_start", "name": str, "args": dict}
  {"type": "tool_end", "name": str, "summary": str, "payload": dict}
  {"type": "error", "content": str}
  {"type": "done"}
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.agent.prompts import SYSTEM_PROMPT
from app.agent.tools import execute_tool, get_tool_specs, openai_tool_schemas
from app.llm.events import StreamEnd, TextDelta, ToolCallChunk
from app.llm.client import get_llm

MAX_ROUNDS = 6


def _data_context() -> str:
    """Ground the live model in the dataset's actual horizon and known events.

    Without this, the model invents anchor dates outside the planted windows
    and diagnose_anomaly comes back empty-handed.
    """
    try:
        from app.agent.extra_tools import _ro

        conn = _ro()
        try:
            first, last = conn.execute(
                "SELECT MIN(report_date), MAX(report_date) FROM fact_air_kpi_daily"
            ).fetchone()
            events = conn.execute(
                "SELECT event_code, start_timestamp, end_timestamp, affected_mode "
                "FROM fact_disruption_events ORDER BY start_timestamp"
            ).fetchall()
        finally:
            conn.close()
        lines = [f"Dataset horizon: {first} to {last} (operations history)."]
        lines.append("Known disruption events on record:")
        for code, start, end, mode in events:
            lines.append(f"- {code} ({mode}): {start[:10]} → {end[:10]}")
        lines.append(
            "When diagnosing a suspected window, set anchor_date to the LAST day of "
            "the suspected disruption window — the scan compares the 7 days up to "
            "that anchor against the prior ~3 months."
        )
        return "\n".join(lines)
    except Exception:
        return ""


def _build_messages(user_message: str, history: list[dict[str, str]]) -> list[dict[str, Any]]:
    system = SYSTEM_PROMPT
    ctx = _data_context()
    if ctx:
        system += "\n\n## Dataset facts\n" + ctx
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in history[-8:]:
        if msg.get("role") in ("user", "assistant") and msg.get("content"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})
    return messages


async def run_agent_stream(
    user_message: str, history: list[dict[str, str]] | None = None
) -> AsyncIterator[dict[str, Any]]:
    specs = get_tool_specs()
    llm = get_llm()
    messages = _build_messages(user_message, history or [])

    for _ in range(MAX_ROUNDS):
        text_acc = ""
        tool_calls: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"

        try:
            async for ev in llm.chat_stream(messages, tools=openai_tool_schemas(specs)):
                if isinstance(ev, TextDelta):
                    text_acc += ev.text
                    yield {"type": "token", "content": ev.text}
                elif isinstance(ev, ToolCallChunk):
                    slot = tool_calls.setdefault(
                        ev.index, {"id": None, "name": None, "arguments": ""}
                    )
                    if ev.call_id:
                        slot["id"] = ev.call_id
                    if ev.name:
                        slot["name"] = ev.name
                    slot["arguments"] += ev.arguments_delta
                elif isinstance(ev, StreamEnd):
                    finish_reason = ev.finish_reason
        except Exception as e:  # provider/network failure — surface, don't crash
            yield {"type": "error", "content": f"LLM stream failed: {e}"}
            yield {"type": "done"}
            return

        if finish_reason != "tool_calls" or not tool_calls:
            break  # final answer already streamed

        # Flush any text that came before the tool calls, then execute them.
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": text_acc or None}
        assistant_msg["tool_calls"] = [
            {
                "id": slot["id"] or f"call_{i}",
                "type": "function",
                "function": {"name": slot["name"], "arguments": slot["arguments"] or "{}"},
            }
            for i, slot in sorted(tool_calls.items())
        ]
        messages.append(assistant_msg)

        for i, slot in sorted(tool_calls.items()):
            call_id = slot["id"] or f"call_{i}"
            name = slot["name"] or "unknown"
            try:
                args = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            yield {"type": "tool_start", "name": name, "args": args}

            result = await execute_tool(specs, name, args)
            yield {
                "type": "tool_end",
                "name": name,
                "summary": result.summary,
                "payload": result.payload,
            }
            messages.append(
                {"role": "tool", "tool_call_id": call_id, "content": result.llm_digest}
            )

    yield {"type": "done"}
