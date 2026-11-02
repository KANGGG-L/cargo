"""SQL firewall tests — every attack vector must be rejected."""

import pytest

from app.agent.safety import SQLSafetyError, validate_and_rewrite


def test_plain_select_passes_and_gets_limit():
    sql = "SELECT COUNT(*) FROM dim_shipments"
    out = validate_and_rewrite(sql)
    assert out.upper().count("LIMIT") == 1
    assert "200" in out


def test_existing_limit_clamped():
    sql = "SELECT * FROM dim_shipments LIMIT 50000"
    out = validate_and_rewrite(sql)
    assert "LIMIT 200" in out


def test_rejects_update_and_delete():
    for sql in (
        "UPDATE dim_shipments SET status = 'X'",
        "DELETE FROM dim_shipments",
        "INSERT INTO dim_shipments VALUES (1)",
        "DROP TABLE dim_shipments",
        "CREATE TABLE evil (id INT)",
        "ATTACH DATABASE 'x' AS e",
        "PRAGMA database_list",
    ):
        with pytest.raises(SQLSafetyError):
            validate_and_rewrite(sql)


def test_rejects_multiple_statements():
    with pytest.raises(SQLSafetyError):
        validate_and_rewrite(
            "SELECT COUNT(*) FROM dim_shipments; DROP TABLE dim_shipments"
        )


def test_rejects_non_whitelisted_table():
    with pytest.raises(SQLSafetyError):
        validate_and_rewrite("SELECT * FROM sqlite_master")


def test_rejects_select_into():
    with pytest.raises(SQLSafetyError):
        validate_and_rewrite(
            "SELECT * INTO evil_table FROM dim_shipments"
        )


def test_cte_select_allowed():
    sql = """
    WITH final_legs AS (
      SELECT shipment_id, ROW_NUMBER() OVER (PARTITION BY shipment_id ORDER BY leg_sequence DESC) AS rn
      FROM fact_shipment_legs
    )
    SELECT COUNT(*) FROM final_legs WHERE rn = 1
    """
    out = validate_and_rewrite(sql)
    assert "LIMIT" in out.upper()


def test_subquery_table_whitelist_enforced():
    with pytest.raises(SQLSafetyError):
        validate_and_rewrite(
            "SELECT * FROM dim_shipments WHERE customer_id IN (SELECT customer_id FROM sqlite_master)"
        )


def test_query_data_tool_end_to_end():
    """Full tool path in mock mode: question → scripted SQL → real rows."""
    import asyncio

    from app.agent.tools import tool_query_data

    result = asyncio.run(
        tool_query_data(
            "What is the overall air network On-Time Performance (OTP) across all flights?"
        )
    )
    assert "row" in result.summary
    assert result.payload["row_count"] >= 1
    assert "air_otp_pct" in result.payload["columns"]
    assert "SELECT" in result.payload["sql"].upper()
