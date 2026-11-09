"""Notification fan-out: subscriptions → transactional outbox.

Enqueue happens synchronously with the triggering event (rule sync / agent
alert); the dispatch worker only flips sent_ts. No event → no row; every row
is auditable even before an SMTP server exists.
"""

import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import get_settings


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sign(secret: str, body: str) -> str:
    return hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()


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
            "SELECT id, subscriber_email, shipment_id, notify_on, delay_threshold_min, channel, "
            "event_types, secret FROM dim_subscriptions"
        ).fetchall()
        now = _now()
        rows = []
        for sub_id, email, sub_shipment, notify_on, threshold, channel, event_types, secret in subs:
            interests = {x.strip() for x in (notify_on or "").split(",")}
            type_filter = {x.strip() for x in (event_types or "").split(",") if x.strip()}
            for a in alerts:
                triggers = {"ALERT"}
                if a.get("event_kind") == "DELAY":
                    triggers.add("DELAY")
                if a.get("event_kind") == "MISSING":
                    triggers.add("MISSING")
                if not interests & triggers:
                    continue
                # R4-2 event-type filter: if set, the alert kind must be listed
                if type_filter and not (type_filter & triggers):
                    continue
                if sub_shipment is not None and sub_shipment != a["shipment_id"]:
                    continue
                if sub_shipment is None and a["severity"] != "high":
                    continue
                subject = f"[HKG Cargo] {a['severity'].upper()}: {a['title'][:100]}"
                body = (
                    f"Shipment {a['shipment_id']} raised an exception.\n\n"
                    f"{a['detail']}\n\n"
                    f"Severity: {a['severity']} · Alert {a['alert_id']}\n"
                    f"Track: /network (select {a['shipment_id']})"
                )
                # idempotent dedupe key per (subscription, alert)
                dedupe = hashlib.sha1(f"{sub_id}|{a['alert_id']}".encode()).hexdigest()
                signature = _sign(secret, body) if secret else None
                rows.append(
                    (sub_id, "ALERT", a["shipment_id"], subject, body, channel, now,
                     dedupe, signature, 0, None)
                )
        if rows:
            # INSERT OR IGNORE on the unique dedupe_key => idempotent re-enqueue
            conn.executemany(
                """
                INSERT OR IGNORE INTO notification_outbox (subscription_id, event_type, shipment_id,
                    subject, body, channel, created_ts, dedupe_key, signature, attempt_count, next_retry_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        return conn.total_changes if rows else 0
    finally:
        conn.close()


def dispatch_pending() -> int:
    """Deliver pending outbox rows: email rows are marked sent (simulated SMTP),
    webhook rows actually POST their payload to the subscription URL."""
    import urllib.request

    conn = sqlite3.connect(get_settings().db_path)
    conn.row_factory = sqlite3.Row
    sent = 0
    try:
        pending = conn.execute(
            """
            SELECT o.id, o.channel, o.subject, o.body, o.shipment_id,
                   o.signature, o.attempt_count, o.dedupe_key,
                   s.webhook_url, s.id AS sub_id
            FROM notification_outbox o
            JOIN dim_subscriptions s ON s.id = o.subscription_id
            WHERE o.sent_ts IS NULL
              AND (o.next_retry_ts IS NULL OR o.next_retry_ts <= ?)
            """,
            (_now(),),
        ).fetchall()
        now = _now()
        for row in pending:
            ok = True
            err = None
            if row["channel"] == "webhook":
                if not row["webhook_url"]:
                    continue  # misconfigured — stays pending
                payload = json.dumps({
                    "event": "cargo.alert",
                    "shipment_id": row["shipment_id"],
                    "subject": row["subject"],
                    "body": row["body"],
                }).encode()
                headers = {
                    "Content-Type": "application/json",
                    "X-Subscription-Id": str(row["sub_id"]),
                }
                if row["signature"]:
                    headers["X-Notification-Signature"] = row["signature"]
                req = urllib.request.Request(row["webhook_url"], data=payload, headers=headers)
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        ok = 200 <= resp.status < 300
                        if not ok:
                            err = f"HTTP {resp.status}"
                except Exception as e:
                    ok = False
                    err = str(e)[:200]
            if ok:
                conn.execute(
                    "UPDATE notification_outbox SET sent_ts = ?, last_error = NULL WHERE id = ?",
                    (now, row["id"]),
                )
                sent += 1
            else:
                # exponential backoff: 2^attempt minutes, capped at 60
                attempt = (row["attempt_count"] or 0) + 1
                backoff_min = min(2 ** attempt, 60)
                next_retry = (
                    datetime.now(timezone.utc) + timedelta(minutes=backoff_min)
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                conn.execute(
                    "UPDATE notification_outbox SET attempt_count = ?, next_retry_ts = ?, last_error = ? WHERE id = ?",
                    (attempt, next_retry, err, row["id"]),
                )
        conn.commit()
        return sent
    finally:
        conn.close()
