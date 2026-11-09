"""Read-only SQL firewall for LLM-generated queries.

Three independent layers:
1. sqlglot AST validation — single statement, SELECT-only, table whitelist.
2. LIMIT clamping — every query is capped at MAX_LIMIT rows.
3. SQLite read-only connection (mode=ro + PRAGMA query_only) as the hard backstop.
"""

import sqlite3
from pathlib import Path

import sqlglot
from sqlglot import exp

MAX_LIMIT = 200

ALLOWED_TABLES = {
    "dim_customers",
    "dim_shipments",
    "fact_shipment_legs",
    "fact_air_kpi_daily",
    "fact_ocean_rate_weekly",
    "fact_rate_cards",
    "fact_disruption_events",
    "public_hkg_air_cargo_monthly",
    "public_scfi_ocean_rate_weekly",
    # shared capacity network (P0) — read-only for the analyst
    "dim_transport_services",
    "dim_ulds",
    "fact_allocations",
    # event layer (P1) — read-only
    "fact_event_log",
    "v_capacity_state",
    # data quality (R4-4) — read-only
    "v_data_quality",
    "v_source_trust",
    # agent-own runtime tables — the analyst must see its own alerts
    "fact_alerts",
    "fact_alert_rules",
    "fact_milestone_events",
    "fact_milestones_plan",
    "fact_planned_legs",
    "fact_charge_lines",
    "fact_invoices",
    "dim_awb",
    "dim_documents",
}

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.TruncateTable,
    exp.Merge,
    exp.Attach,
    exp.Detach,
    exp.Pragma,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Grant,
    exp.Revoke,
    exp.Command,  # raw unmatched statements (VACUUM, ATTACH, load_extension, ...)
)


class SQLSafetyError(Exception):
    """Raised when a generated query fails the read-only firewall."""


def validate_and_rewrite(sql: str) -> str:
    """Validate a generated query and return a safe, LIMIT-clamped rewrite."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="sqlite") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SQLSafetyError(f"SQL parse error: {e}") from e

    if len(statements) != 1:
        raise SQLSafetyError("Exactly one statement is allowed")

    tree = statements[0]
    if not isinstance(tree, exp.Select):
        raise SQLSafetyError("Only SELECT queries are allowed")

    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLSafetyError(f"Forbidden SQL construct: {type(node).__name__}")
    if tree.args.get("into") is not None:
        raise SQLSafetyError("SELECT ... INTO is not allowed")

    for table in tree.find_all(exp.Table):
        # CTE aliases surface as Table nodes too; only real sources need whitelisting.
        if table.name.lower() in cte_names:
            continue
        if table.name.lower() not in ALLOWED_TABLES:
            raise SQLSafetyError(f"Table not allowed: {table.name}")

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(MAX_LIMIT)
    else:
        try:
            requested = int(limit.expression.name)  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            requested = MAX_LIMIT
        if requested > MAX_LIMIT:
            tree = tree.limit(MAX_LIMIT)

    return tree.sql(dialect="sqlite")


def execute_readonly(sql: str, db_path: Path) -> tuple[list[str], list[list]]:
    """Run a validated query on a read-only connection. Returns (columns, rows)."""
    safe_sql = validate_and_rewrite(sql)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(safe_sql)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchmany(MAX_LIMIT)]
        return columns, rows
    finally:
        conn.close()
