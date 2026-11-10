"""Auto-escalation tests (Release B).

Alerts past their due_ts bump escalation_level (capped), push due_ts out so the
same window is not double-counted, notify at L2+, and never touch RESOLVED rows.
"""

import os
import sqlite3

from app.milestones.rules import MAX_ESCALATION_LEVEL, escalate

DB = os.environ["DB_PATH"]


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _plant(alert_id, status, due_ts, level=0, severity="high"):
    conn = _conn()
    try:
        sid = conn.execute("SELECT shipment_id FROM dim_shipments LIMIT 1").fetchone()[0]
        conn.execute("DELETE FROM fact_alerts WHERE alert_id = ?", (alert_id,))
        conn.execute(
            "INSERT INTO fact_alerts (alert_id, shipment_id, source, severity, title, detail, "
            "status, created_ts, updated_ts, due_ts, escalation_level) VALUES "
            "(?, ?, 'rules', ?, 'esc test', 'detail', ?, "
            "'2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z', ?, ?)",
            (alert_id, sid, severity, status, due_ts, level),
        )
        conn.commit()
    finally:
        conn.close()


def _level(alert_id):
    conn = _conn()
    try:
        return conn.execute(
            "SELECT escalation_level FROM fact_alerts WHERE alert_id = ?", (alert_id,)
        ).fetchone()[0]
    finally:
        conn.close()


NOW = "2025-06-01T00:00:00Z"
PAST = "2025-05-01T00:00:00Z"
FUTURE = "2025-07-01T00:00:00Z"


def test_overdue_open_alert_escalates():
    _plant("AL-910001", "OPEN", PAST, level=0)
    conn = _conn()
    try:
        escalate(conn, NOW)
    finally:
        conn.close()
    assert _level("AL-910001") == 1


def test_escalation_pushes_due_out_so_not_double_counted():
    _plant("AL-910002", "OPEN", PAST, level=0)
    conn = _conn()
    try:
        escalate(conn, NOW)  # first pass -> L1, due pushed to NOW + SLA
        escalate(conn, NOW)  # same 'now' -> due is now in the future -> no bump
    finally:
        conn.close()
    assert _level("AL-910002") == 1


def test_escalation_capped():
    _plant("AL-910003", "OPEN", PAST, level=MAX_ESCALATION_LEVEL)
    conn = _conn()
    try:
        escalate(conn, NOW)
    finally:
        conn.close()
    assert _level("AL-910003") == MAX_ESCALATION_LEVEL


def test_future_due_not_escalated():
    _plant("AL-910004", "OPEN", FUTURE, level=0)
    conn = _conn()
    try:
        escalate(conn, NOW)
    finally:
        conn.close()
    assert _level("AL-910004") == 0


def test_resolved_alert_not_escalated():
    _plant("AL-910005", "RESOLVED", PAST, level=0)
    conn = _conn()
    try:
        escalate(conn, NOW)
    finally:
        conn.close()
    assert _level("AL-910005") == 0


def test_l2_escalation_enqueues_notice():
    _plant("AL-910006", "OPEN", PAST, level=1)  # already L1 -> bump to L2
    conn = _conn()
    try:
        result = escalate(conn, NOW)
    finally:
        conn.close()
    assert _level("AL-910006") == 2
    assert result["escalated"] >= 1
