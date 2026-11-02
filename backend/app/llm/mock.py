"""Offline mock LLM: deterministic scripted traces for zero-risk demos.

No API key needed. Preset questions are matched by keyword and answered with a
canned tool-call plan whose SQL is drawn from the *verified* few-shot catalog —
so the data behind a mock demo is the real database, only the language model is
simulated. Unmatched questions get a graceful notice instead of a failure.
"""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.events import StreamEnd, StreamEvent, TextDelta, ToolCallChunk


def match_few_shot(question: str) -> dict[str, str] | None:
    """Best few-shot match via df-weighted ranking; None when nothing is close."""
    from app.semantic_layer import rank_few_shots

    ranked = rank_few_shots(question, k=1)
    if not ranked:
        return None
    best = ranked[0]
    # Guard: a question sharing no distinctive vocabulary gets no scripted SQL.
    q_words = set(re.findall(r"[a-z]{3,}", question.lower()))
    if not q_words & set(re.findall(r"[a-z]{3,}", best["question"].lower())):
        return None
    return best


def match_plan(user_message: str) -> dict[str, Any] | None:
    q = user_message.lower()
    for plan in MOCK_PLANS:
        if any(kw in q for kw in plan["keywords"]):
            return plan
    return None


class MockLLM:
    """Same chat_stream/complete_text surface as LiveLLM, fully deterministic."""

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[StreamEvent]:
        user_message = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        tool_digests = [m["content"] for m in messages if m["role"] == "tool"]
        plan = match_plan(user_message)

        if not tool_digests:
            # Round 1: scripted plan if the question matches one, otherwise a
            # generic query_data call — the SQL is still real either way.
            if plan is not None:
                steps, call_id = plan["steps"], f"mock_call_{plan['id']}_0"
            else:
                steps = [{"tool": "query_data", "args": {"question": user_message}}]
                call_id = "mock_call_adhoc_0"
            for i, step in enumerate(steps):
                yield ToolCallChunk(
                    index=i,
                    call_id=f"{call_id}_{i}" if i else call_id,
                    name=step["tool"],
                    arguments_delta=json.dumps(step["args"]),
                )
            yield StreamEnd("tool_calls")
        else:
            if plan is not None:
                yield TextDelta(plan["answer"])
            else:
                digest_head = (tool_digests[-1] or "")[:400]
                yield TextDelta(
                    "(Mock mode — set LLM_API_KEY for full live narration.)\n\n"
                    "The database returned:\n\n" + digest_head
                )
            yield StreamEnd("stop")

    async def complete_text(self, system: str, user: str, question_hint: str | None = None) -> str:
        """nl_to_sql in mock mode: return the verified few-shot SQL as JSON."""
        question = (question_hint or user).strip()
        shot = match_few_shot(question)
        if shot is None:
            return json.dumps({"sql": "", "chart": "none", "error": "no scripted match"})
        # "auto" lets the chart-inference heuristic pick bar/line from the shape.
        return json.dumps({"sql": shot["sql"], "chart": "auto"})


MOCK_PLANS: list[dict[str, Any]] = [{
        "id": "truck",
        "keywords": ["truck", "checkpoint", "border", "shenzhen bay", "crossing"],
        "steps": [
            {
                "tool": "diagnose_anomaly",
                "args": {"scope": "truck", "anchor_date": "2025-11-25"},
            }
        ],
        "answer": (
            "The road-side scan (as of 2025-11-25) flags Shenzhen Bay (SZBP): truck "
            "OTP collapsed to ~58% against a ~90% baseline and average crossing time "
            "tripled from ~45 to ~215 minutes — matching EVT-2025-002 (checkpoint "
            "congestion, Nov 10-24).\n\n"
            "Recommendations: re-route time-critical feeder trips via Huanggang while "
            "SZBP queue depth exceeds a set threshold, pre-book extended counter "
            "windows with the terminal, and alert shippers feeding the Nov peak."
        ),
    },
    {
        "id": "diagnose",
        "keywords": ["why did", "anomaly", "diagnose", "what's wrong", "deviation"],
        "steps": [
            {
                "tool": "diagnose_anomaly",
                "args": {"scope": "sea", "anchor_date": "2026-03-20"},
            }
        ],
        "answer": (
            "The sea-feeder scan (as of 2026-03-20) flags Yantian: average feeder "
            "delay jumped from a ~3 h baseline to ~17 h, and the disruption log "
            "matches it to EVT-2026-002 (Yantian congestion, Mar 1-15).\n\n"
            "Improvement actions: (1) automate a weekly baseline-vs-actual scan so "
            "these surface within days, not months; (2) gate new contract rates "
            "against a cost floor at upload; (3) tie the feeder booking system to a "
            "congestion index that reroutes Sea-Air cargo proactively."
        ),
    },
    {
        "id": "simulate",
        "keywords": ["simulate", "what if", "what-if", "scenario", "typhoon closure"],
        "steps": [
            {
                "tool": "simulate_disruption",
                "args": {"event_type": "typhoon_hkg_closure", "duration_hours": 48, "severity": 5},
            }
        ],
        "answer": (
            "A 48-hour full HKG closure (severity 5) grounds ~28 freighter "
            "departures. Backlog peaks at ~122 t (about half a day of throughput), "
            "putting ~$0.3M of revenue at risk, and the model clears it in ~2 days "
            "at 130% surge capacity after reopening.\n\n"
            "Playbook: freeze non-urgent bookings 24 h before landfall, secure "
            "extra freighter capacity for the 48 h after reopening, and keep a "
            "pre-approved customer communication list for priority cargo."
        ),
    },
    {
        "id": "typhoon",
        "keywords": ["typhoon", "september 2025", "sep 2025"],
        "steps": [
            {
                "tool": "query_data",
                "args": {
                    "question": "What was the daily air leg OTP and backlog tonnage during the September 2025 typhoon?"
                },
            }
        ],
        "answer": (
            "During Typhoon week (Sep 15–21, 2025), air OTP collapsed to roughly 30% "
            "against a ~86% baseline, with hundreds of cancelled flights and terminal "
            "backlog spiking to 3–4k tonnes.\n\n"
            "Recommendations: pre-activate a typhoon playbook 72 h ahead (slot re-booking, "
            "priority triage for pharma/perishables), pre-position backlog recovery "
            "capacity for the 48 h after reopening, and publish proactive customer ETAs "
            "from the disruption event feed."
        ),
    },
    {
        "id": "yantian",
        "keywords": ["yantian", "congestion", "feeder", "sea delay", "march 2026"],
        "steps": [
            {
                "tool": "query_data",
                "args": {
                    "question": "What was the average delay for feeder sea legs departing Yantian during March 2026?"
                },
            }
        ],
        "answer": (
            "Yantian feeder legs during the Mar 1–15, 2026 congestion event averaged "
            "over 50 h of delay (vs ~2 h normally), and the feeder spot rate jumped "
            "from ~$550 to ~$860 per FEU.\n\n"
            "Recommendations: shift time-critical Sea-Air cargo to Nanjing/Shanghai "
            "feeder origins when Yantian yard utilization crosses a defined threshold, "
            "and add a congestion surcharge clause to feeder contracts to protect margin."
        ),
    },
    {
        "id": "margin",
        "keywords": ["hkg-ord", "pricing error", "pricing", "profit", "loss"],
        "steps": [
            {
                "tool": "query_data",
                "args": {
                    "question": "Show the monthly gross margin percentage for lane HKG-ORD across 2026."
                },
            }
        ],
        "answer": (
            "HKG-ORD ran at ~+20% gross margin through 2026 — except June, where a "
            "contract-rate misconfiguration priced freight below charter + fuel cost and "
            "the lane posted roughly −20% margin on that month's shipments.\n\n"
            "Recommendations: add a rate-floor validation against cost-per-kg at "
            "contract upload time, and alert on any lane whose trailing 7-day margin "
            "turns negative before the exposure compounds."
        ),
    },
    {
        "id": "quote",
        "keywords": ["quote", "how much to ship", "rate for", "book", "ship 500 kg"],
        "steps": [
            {
                "tool": "quote_booking",
                "args": {"origin": "CNYTN", "destination": "LAX", "weight_kg": 500, "mode": "auto"},
            }
        ],
        "answer": (
            "For 500 kg from Yantian to LAX on the Sea-Air chain: feeder barge "
            "Yantian→HKG (~1.3 d) plus a freighter HKG→LAX (~1.2 d flight, total "
            "door-to-airport ~2 d including handling). The rate card prices the air "
            "leg at the +300KG break; combined quote lands in the low four figures "
            "USD — see the breakdown card above for exact numbers from the tariff."
        ),
    },
    {
        "id": "dwell",
        "keywords": ["dwell", "hub", "transit"],
        "steps": [
            {
                "tool": "query_data",
                "args": {"question": "What is the average hub dwell time at HKG for multimodal shipments?"}
            }
        ],
        "answer": (
            "Average HKG hub dwell is ~9 h between feeder arrival and freighter "
            "departure. Missed connections are the main tail risk: when a feeder runs "
            ">2 h late the cargo is re-accommodated, adding ~24 h end-to-end.\n\n"
            "Recommendations: reserve a protected daily flight slot for late-feeder "
            "recovery, and raise the planned dwell buffer from 6–12 h for shipments "
            "with Yantian origins during congestion periods."
        ),
    },
]
