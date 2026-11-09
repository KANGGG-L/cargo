"""Release 5 — governance & engineering baseline (§6.3, R5-2..R5-6)."""

import asyncio
import json
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.agent.extra_tools import tool_raise_alert
from app.agent.governance import confirmation_token, verify_confirmation
from app.agent.safety import ALLOWED_TABLES
from app.main import app

DB = os.environ["DB_PATH"]


def _client():
    return TestClient(app)


def _rw():
    return sqlite3.connect(DB)


# ---------------------------------------------------------------- R5-2 write governance


def test_write_tool_requires_confirmation():
    sid = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
        "SELECT shipment_id FROM dim_shipments LIMIT 1"
    ).fetchone()[0]
    first = asyncio.run(tool_raise_alert(sid, "test gate", "detail", "medium"))
    assert first.payload.get("requires_confirmation") is True
    assert "alert_id" not in first.payload


def test_write_tool_commits_with_token():
    sid = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
        "SELECT shipment_id FROM dim_shipments LIMIT 1"
    ).fetchone()[0]
    args = {"shipment_id": sid, "title": "confirmed write", "detail": "d", "severity": "info"}
    token = confirmation_token("raise_alert", args)
    res = asyncio.run(tool_raise_alert(**args, confirmation_token=token))
    assert res.payload["alert_id"].startswith("AL-")


def test_bad_token_rejected():
    assert verify_confirmation("raise_alert", {"a": 1}, "deadbeef") is False
    assert verify_confirmation("raise_alert", {"a": 1}, None) is False


def test_tool_audit_rows_written():
    sid = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
        "SELECT shipment_id FROM dim_shipments LIMIT 1"
    ).fetchone()[0]
    asyncio.run(tool_raise_alert(sid, "audit me", "detail text", "medium"))
    conn = _rw()
    try:
        row = conn.execute(
            "SELECT tool_kind, confirmed, source_text_hash FROM fact_agent_tool_audit "
            "WHERE tool_name = 'raise_alert' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == "write"
        assert row[2] is not None  # source text was hashed, not stored raw
    finally:
        conn.close()


def test_audit_tables_not_in_llm_firewall():
    """Audit/access tables must NOT be queryable by the agent (§7.2)."""
    assert "fact_agent_tool_audit" not in ALLOWED_TABLES
    assert "fact_access_log" not in ALLOWED_TABLES


def test_tampered_field_cannot_autofire_write():
    """Simulated document-to-transaction integrity: a write triggered straight
    from (untrusted) extracted args without a token does not commit."""
    sid = sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute(
        "SELECT shipment_id FROM dim_shipments LIMIT 1"
    ).fetchone()[0]
    # attacker-controlled args with a *wrong* token
    res = asyncio.run(tool_raise_alert(sid, "tampered hazmat flag", "x", "high",
                                       confirmation_token="forged0000000000"))
    assert res.payload.get("requires_confirmation") is True
    assert "alert_id" not in res.payload


# ---------------------------------------------------------------- R5-3 access log


def test_access_log_records_requests():
    c = _client()
    c.get("/api/network/services?mode=AIR&limit=2")
    conn = _rw()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM fact_access_log WHERE path LIKE '/api/network/%'"
        ).fetchone()[0]
        assert n >= 1
    finally:
        conn.close()


# ---------------------------------------------------------------- R5-4 metrics


def test_ops_metrics_endpoint():
    c = _client()
    r = c.get("/api/ops/metrics")
    assert r.status_code == 200
    body = r.json()
    assert "alerts_by_status" in body
    assert "webhook_outbox" in body
    assert "access_log" in body


# ---------------------------------------------------------------- R5-5 OpenAPI contract


def test_openapi_committed_and_in_sync():
    committed = Path(__file__).resolve().parents[1] / "openapi.json"
    assert committed.exists(), "run scripts/export_openapi.py and commit openapi.json"
    on_disk = json.loads(committed.read_text())
    live = app.openapi()
    # compare the stable surface: the set of paths (drift in routes fails CI)
    assert set(on_disk["paths"]) == set(live["paths"]), "openapi.json out of sync with routes"


# ---------------------------------------------------------------- R5-6 migration baseline


def test_schema_version_table_or_rebuild_path():
    """The one-shot deterministic rebuild path still exists (rebuild_demo.sh)."""
    root = Path(__file__).resolve().parents[2]
    assert (root / "scripts" / "rebuild_demo.sh").exists()
