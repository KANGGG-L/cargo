"""Agent write-operation governance (R5-2).

Write tools (raise_alert, order transitions via agent) must:
  1. be audited in fact_agent_tool_audit (caller, args, source-text hash, result);
  2. require a confirmation_token — a deterministic HMAC over the tool name + args
     — so a write cannot fire straight from unverified extracted text without an
     explicit confirm step (document-to-transaction integrity, FreightSkillBench).

The confirmation_token is NOT a security boundary against a malicious operator;
it is a human-in-the-loop gate so that a tampered document field cannot silently
become a booked transaction. The audit row is written either way.
"""

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone

from app.config import get_settings

WRITE_TOOLS = {"raise_alert"}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def confirmation_token(tool_name: str, args: dict) -> str:
    """Deterministic token the caller must echo back to authorize a write."""
    secret = get_settings().agent_confirm_secret
    canonical = tool_name + "|" + json.dumps(args, sort_keys=True, separators=(",", ":"))
    return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()[:16]


def verify_confirmation(tool_name: str, args: dict, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(confirmation_token(tool_name, args), token)


def audit_tool_call(tool_name: str, tool_kind: str, args: dict, confirmed: bool,
                    result_summary: str = "", source_text: str | None = None) -> None:
    """Append an audit row. source_text is hashed, never stored raw."""
    src_hash = hashlib.sha256(source_text.encode()).hexdigest() if source_text else None
    # strip the confirmation_token from logged args (it's control, not data)
    logged = {k: v for k, v in args.items() if k != "confirmation_token"}
    conn = sqlite3.connect(get_settings().db_path)
    try:
        conn.execute(
            """
            INSERT INTO fact_agent_tool_audit
              (tool_name, tool_kind, args_json, source_text_hash, confirmed, result_summary, created_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tool_name, tool_kind, json.dumps(logged, separators=(",", ":"))[:800],
             src_hash, 1 if confirmed else 0, result_summary[:200], _now()),
        )
        conn.commit()
    finally:
        conn.close()
