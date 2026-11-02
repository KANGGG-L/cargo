"""FSU milestone-feed ingest: parse, dedupe, tolerate out-of-order arrival.

Real feeds (CARGO-IMP FSU / Cargo-XML) deliver events late, duplicated and out
of order. This ingest layer makes event_ts authoritative — processing order
never matters — and refuses nothing silently: every bad line lands in
ingest_rejects with a reason.
"""

import hashlib
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.config import get_settings

LINE_RE = re.compile(
    r"^FSU\|([A-Z]{3})\|([A-Z0-9-]+)\|([A-Z]{3})\|(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)$"
)

KNOWN_CODES = {"BKD", "RCS", "DEP", "ARR", "NFD", "DLV"}


@dataclass
class IngestResult:
    parsed: int = 0
    ingested: int = 0
    duplicates: int = 0
    rejected: int = 0
    rejects: list[dict] = field(default_factory=list)
    resolved_alerts: list[str] = field(default_factory=list)


def _dedupe_key(code: str, shipment_id: str, station: str, ts: str) -> str:
    return hashlib.sha1(f"{code}|{shipment_id}|{station}|{ts}".encode()).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_ts(ts: str) -> bool:
    try:
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        return True
    except ValueError:
        return False


def parse_and_ingest(conn: sqlite3.Connection, raw: str, source_name: str = "replay") -> IngestResult:
    result = IngestResult()
    now = _now()
    conn.row_factory = sqlite3.Row

    # ingest logs and rejects go to a writable connection
    path = get_settings().db_path
    rw = sqlite3.connect(path)
    rw.row_factory = sqlite3.Row
    try:
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            m = LINE_RE.match(line)
            if not m:
                result.rejected += 1
                result.rejects.append(
                    {"line_no": line_no, "reason": "malformed line", "raw_line": line[:200]}
                )
                continue

            code, shipment_id, station, ts = m.groups()
            if code not in KNOWN_CODES:
                result.rejected += 1
                result.rejects.append(
                    {"line_no": line_no, "reason": f"unknown milestone code {code}", "raw_line": line[:200]}
                )
                continue
            if not _valid_ts(ts):
                result.rejected += 1
                result.rejects.append(
                    {"line_no": line_no, "reason": "invalid timestamp", "raw_line": line[:200]}
                )
                continue
            if not rw.execute(
                "SELECT 1 FROM dim_shipments WHERE shipment_id = ?", (shipment_id,)
            ).fetchone():
                result.rejected += 1
                result.rejects.append(
                    {"line_no": line_no, "reason": f"unknown shipment {shipment_id}", "raw_line": line[:200]}
                )
                continue

            result.parsed += 1

            # A feed line must map to a planned milestone. If the plan row is
            # already covered by an event (or no plan exists), the line is a
            # duplicate/no-op — never insert an unanchored event.
            plan = rw.execute(
                """
                SELECT p.leg_id, p.planned_ts FROM fact_milestones_plan p
                WHERE p.shipment_id = ? AND p.code = ?
                  AND NOT EXISTS (
                    SELECT 1 FROM fact_milestone_events e
                    WHERE e.shipment_id = p.shipment_id AND e.code = p.code
                      AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
                  )
                ORDER BY p.planned_ts LIMIT 1
                """,
                (shipment_id, code),
            ).fetchone()

            if plan is None:
                result.duplicates += 1
                continue

            leg_id = plan["leg_id"]
            key = hashlib.sha1(
                f"{code}|{shipment_id}|{leg_id or ''}|{ts}".encode()
            ).hexdigest()

            try:
                rw.execute(
                    """
                    INSERT INTO fact_milestone_events
                      (shipment_id, leg_id, code, event_ts, source, dedupe_key)
                    VALUES (?, ?, ?, ?, 'fsu', ?)
                    """,
                    (shipment_id, leg_id, code, ts, key),
                )
                rw.commit()
                result.ingested += 1
                if plan:
                    result.resolved_alerts.extend(_auto_resolve_missing(rw, shipment_id, code, leg_id))
            except sqlite3.IntegrityError:
                result.duplicates += 1

        rw.execute(
            """
            INSERT INTO ingest_log (source_name, raw_chars, parsed, ingested, duplicates, rejected, processed_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_name, len(raw), result.parsed, result.ingested,
             result.duplicates, result.rejected, now),
        )
        for rej in result.rejects:
            rw.execute(
                "INSERT INTO ingest_rejects (ingest_id, line_no, reason, raw_line) VALUES (?, ?, ?, ?)",
                (rw.execute("SELECT MAX(id) FROM ingest_log").fetchone()[0],
                 rej["line_no"], rej["reason"], rej["raw_line"]),
            )
        rw.commit()
    finally:
        rw.close()
    return result


def _auto_resolve_missing(conn: sqlite3.Connection, shipment_id: str, code: str, leg_id: str | None) -> list[str]:
    """Open missing_event alerts whose milestone just arrived → auto-resolve."""
    resolved = []
    rows = conn.execute(
        """
        SELECT a.alert_id, r.code, r.rule_type FROM fact_alerts a
        JOIN fact_alert_rules r ON r.rule_id = a.rule_id
        WHERE a.status = 'OPEN' AND a.source = 'rules'
          AND r.rule_type = 'missing_event' AND r.code = ? AND a.shipment_id = ?
        """,
        (code, shipment_id),
    ).fetchall()
    for alert_id, rcode, _rtype in rows:
        satisfied = conn.execute(
            """
            SELECT 1 FROM fact_milestones_plan p
            WHERE p.shipment_id = ? AND p.code = ?
              AND EXISTS (
                SELECT 1 FROM fact_milestone_events e
                WHERE e.shipment_id = p.shipment_id AND e.code = p.code
                  AND ((e.leg_id IS NULL AND p.leg_id IS NULL) OR e.leg_id = p.leg_id)
              )
            """,
            (shipment_id, rcode),
        ).fetchone()
        if satisfied:
            conn.execute(
                """
                UPDATE fact_alerts SET status = 'RESOLVED', updated_ts = ?,
                       resolution_note = 'auto-resolved: milestone received via FSU ingest'
                WHERE alert_id = ?
                """,
                (_now(), alert_id),
            )
            conn.commit()
            resolved.append(alert_id)
    return resolved
