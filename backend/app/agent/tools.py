"""Agent tools: schema definitions, executors and result payloads.

Each tool returns a ToolResult with three faces:
- `summary`: one UI line ("12 rows · bar chart")
- `payload`: structured data the frontend renders (table + chart spec / report)
- `llm_digest`: compact text fed back to the model for narration
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.prompts import NL_TO_SQL_PROMPT
from app.agent.safety import SQLSafetyError, execute_readonly, validate_and_rewrite
from app.config import get_settings
from app.llm.client import get_llm
from app.llm.mock import match_few_shot
from app.semantic_layer import (
    FEW_SHOT_QUERY_CATALOG,
    get_schema_context_prompt,
)

DATE_PREFIX = re.compile(r"^\d{4}-\d{2}")


@dataclass
class ToolResult:
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    llm_digest: str = ""


# --------------------------------------------------------------------------
# query_data: natural language → SQL → rows + chart


def _select_few_shots(question: str, k: int = 3) -> str:
    """Top-k few-shot examples by df-weighted similarity, to steer SQL generation."""
    from app.semantic_layer import rank_few_shots

    ranked = rank_few_shots(question, k=k)
    return "\n\n".join(f"Q: {s['question']}\nSQL:\n{s['sql']}" for s in ranked)


def _parse_json_reply(raw: str) -> tuple[str, str]:
    """Extract {"sql": ..., "chart": ...} from a model reply, tolerating code fences."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("model reply is not JSON")
    data = json.loads(text[start : end + 1])
    return data.get("sql", "").strip(), data.get("chart", "none")


async def nl_to_sql(question: str, llm: Any) -> tuple[str, str]:
    """Generate + firewall-validate SQL for a question. One corrective retry."""
    prompt = NL_TO_SQL_PROMPT.format(
        schema_context=get_schema_context_prompt(),
        few_shots=_select_few_shots(question),
        question=question,
    )
    feedback = ""
    last_error: Exception | None = None
    for _ in range(2):
        raw = await llm.complete_text(
            system="You output strict JSON only.",
            user=prompt + feedback,
            question_hint=question,
        )
        try:
            sql, chart = _parse_json_reply(raw)
            return validate_and_rewrite(sql), chart
        except (ValueError, json.JSONDecodeError, SQLSafetyError) as e:
            last_error = e
            feedback = f"\n\nYour previous reply failed: {e}. Fix it and reply with strict JSON again."
    raise SQLSafetyError(f"SQL generation failed after retry: {last_error}")


def infer_chart(columns: list[str], rows: list[list], hint: str) -> dict[str, Any] | None:
    """Pick a sensible chart spec for the result shape."""
    if not rows or len(columns) < 2 or hint == "none":
        return None
    numeric_idx = [
        i
        for i, col in enumerate(columns[1:], start=1)
        if all(isinstance(r[i], (int, float)) and not isinstance(r[i], bool) for r in rows)
    ]
    if not numeric_idx:
        return None
    # Keep only series in the same order of magnitude as the headline series —
    # e.g. OTP % must not share an axis with backlog tonnage (off-screen noise).
    def col_max(i: int) -> float:
        return max((abs(r[i]) for r in rows if isinstance(r[i], (int, float))), default=0)

    headline = col_max(numeric_idx[0]) or 1.0
    numeric_idx = [
        i for i in numeric_idx if headline * 0.2 <= col_max(i) <= headline * 5
    ]
    chart_type = hint if hint in ("bar", "line", "pie") else None
    if chart_type is None:
        looks_temporal = bool(DATE_PREFIX.match(str(rows[0][0])))
        chart_type = "line" if looks_temporal else "bar"
    return {
        "type": chart_type,
        "x_key": columns[0],
        "y_keys": [columns[i] for i in numeric_idx],
    }


async def tool_query_data(question: str) -> ToolResult:
    llm = get_llm()
    sql, chart_hint = await nl_to_sql(question, llm)
    if not sql:  # mock mode: question matched no scripted few-shot
        return ToolResult(
            summary="no scripted SQL for this question in mock mode",
            payload={"sql": "", "columns": [], "rows": [], "row_count": 0, "chart": None},
            llm_digest="query_data returned no data (mock mode has no scripted SQL for this question).",
        )
    columns, rows = execute_readonly(sql, get_settings().db_path)
    chart = infer_chart(columns, rows, chart_hint)
    preview = rows[:10]
    digest_rows = "\n".join(" | ".join(str(v) for v in r) for r in preview)
    return ToolResult(
        summary=f"{len(rows)} rows · {chart['type'] if chart else 'table'}",
        payload={
            "sql": sql,
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "chart": chart,
        },
        llm_digest=(
            f"SQL: {sql}\nColumns: {columns}\nRows ({len(rows)}, showing up to 10):\n{digest_rows}"
        ),
    )


# --------------------------------------------------------------------------
# Tool registry


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    executor: Any


QUERY_DATA_SPEC = ToolSpec(
    name="query_data",
    description="Answer a data question by running SQL over the cargo star schema. Returns columns, rows and a chart spec.",
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The data question, self-contained and rephrased in English.",
            }
        },
        "required": ["question"],
    },
    executor=tool_query_data,
)


def get_tool_specs() -> list[ToolSpec]:
    """All five specialist tools behind the single agent loop."""
    from app.agent.extra_tools import DIAGNOSE_SPEC, QUOTE_SPEC, RAISE_ALERT_SPEC, SIMULATE_SPEC

    return [QUERY_DATA_SPEC, DIAGNOSE_SPEC, SIMULATE_SPEC, QUOTE_SPEC, RAISE_ALERT_SPEC]


def openai_tool_schemas(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": s.name,
                "description": s.description,
                "parameters": s.parameters,
            },
        }
        for s in specs
    ]


async def execute_tool(specs: list[ToolSpec], name: str, args: dict[str, Any]) -> ToolResult:
    for spec in specs:
        if spec.name == name:
            try:
                return await spec.executor(**args)
            except SQLSafetyError as e:
                return ToolResult(
                    summary="blocked by SQL firewall",
                    payload={"error": str(e)},
                    llm_digest=f"query_data failed the read-only firewall: {e}. Rephrase or use a different approach.",
                )
            except TypeError as e:
                return ToolResult(
                    summary="bad arguments",
                    payload={"error": str(e)},
                    llm_digest=f"Tool {name} got invalid arguments: {e}.",
                )
    return ToolResult(
        summary="unknown tool",
        payload={"error": f"unknown tool {name}"},
        llm_digest=f"Tool {name} does not exist. Available: {[s.name for s in specs]}.",
    )
