"""Notification fan-out: subscriptions → transactional outbox.

Enqueue happens synchronously with the triggering event (rule sync / agent
alert); the dispatch worker only flips sent_ts. No event → no row; every row
is auditable even before an SMTP server exists.
"""

import sqlite3
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def enqueue_for_alerts(alerts: list[dict[str, Any]]) -> int:
    """Match freshly created alerts against subscriptions and enqueue emails.

    Matching rules:
    - subscription on a specific shipment → alerts for that shipment
    - global subscription (shipment_id NULL) → high-severity alerts only
    - notify_on gates: ALERT (any ticket), DELAY (delay_over rules),
      MISSING (missing_event rules)
    """
    if not alerts:
        return 0
    conn = sqlite3.connect(get_settings().db_path)
    try:
        subs = conn.execute(
            "SELECT id, subscriber_email, shipment_id, notify_on, delay_threshold_min, channel "
            "FROM dim_subscriptions"
        ).fetchall()
        now = _now()
        rows = []
        for sub_id, email, sub_shipment, notify_on, threshold, channel in subs:
            interests = {x.strip() for x in (notify_on or "").split(",")}
            for a in alerts:
                triggers = {"ALERT"}
                if a.get("event_kind") == "DELAY":
                    triggers.add("DELAY")
                if a.get("event_kind") == "MISSING":
                    triggers.add("MISSING")
                if not interests & triggers:
                    continue
                if sub_shipment is not None and sub_shipment != a["shipment_id"]:
                    continue
                if sub_shipment is None and a["severity"] != "high":
                    continue
                rows.append(
                    (
                        sub_id,
                        "ALERT",
                        a["shipment_id"],
                        f"[HKG Cargo] {a['severity'].upper()}: {a['title'][:100]}",
                        (
                            f"Shipment {a['shipment_id']} raised an exception.\n\n"
                            f"{a['detail']}\n\n"
                            f"Severity: {a['severity']} · Alert {a['alert_id']}\n"
                            f"Track: /network (select {a['shipment_id']})"
                        ),
                        channel,
                        now,
                    )
                )
        if rows:
            conn.executemany(
                """
                INSERT INTO notification_outbox (subscription_id, event_type, shipment_id,
                                                 subject, body, channel, created_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return len(rows)
    finally:
        conn.close()


def dispatch_pending() -> int:
    """Mark every pending outbox row as sent (simulated SMTP worker)."""
    conn = sqlite3.connect(get_settings().db_path)
    try:
        cur = conn.execute(
            "UPDATE notification_outbox SET sent_ts = ? WHERE sent_ts IS NULL", (_now(),)
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
