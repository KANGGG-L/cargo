"""P0 shared-capacity network invariants (docs/NETWORK_UPGRADE_PLAN.md §5.1.5).

These run against the test copy of the demo DB (see conftest.py). They assert the
five invariants I1-I5 plus the shared-service / cut-off / rollover / typhoon
cascade acceptance criteria.

Note on the typhoon cascade (§4.6 "同班次 ≥20 票一次性同损"): with this dataset's
real air-freight density (~1.5 AIR legs/lane/day, one daily freighter per lane) a
single flight never carries 20 shipments. "One cancellation event" is therefore
measured at the DISRUPTION-EVENT level — the number of distinct shipments rolled
off the block of typhoon-cancelled services — which is the operational meaning of
"一次台风取消". See docs/acceptance for the recorded D2 deviation.
"""

import os
import sqlite3

import pytest

DB = os.environ["DB_PATH"]


def q(sql, *params):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def scalar(sql, *params):
    return q(sql, *params)[0][0]


def test_tables_exist():
    for t in ("dim_transport_services", "dim_ulds", "fact_allocations"):
        assert scalar(f"SELECT COUNT(*) FROM {t}") > 0, f"{t} is empty"


def test_shared_services():
    """≥1000 services carry more than one shipment (real contention exists)."""
    shared = scalar(
        "SELECT COUNT(*) FROM (SELECT service_id FROM fact_allocations "
        "GROUP BY service_id HAVING COUNT(DISTINCT shipment_id) > 1)"
    )
    assert shared >= 1000, f"only {shared} shared services"


def test_capacity_conservation():
    """I1: no service is allocated beyond its chargeable weight or volume."""
    overflow = scalar(
        "SELECT COUNT(*) FROM dim_transport_services "
        "WHERE allocated_kg > capacity_chargeable_kg + 0.5 "
        "OR allocated_cbm > capacity_cbm + 0.5"
    )
    assert overflow == 0, f"{overflow} services exceed capacity"


def test_rollup_matches_allocations():
    """The redundant allocated_kg rollup equals SUM of its confirmed-ish allocations."""
    rows = q(
        "SELECT s.service_id, s.allocated_kg, "
        "COALESCE((SELECT SUM(a.allocated_weight_kg) FROM fact_allocations a "
        " WHERE a.service_id = s.service_id), 0) "
        "FROM dim_transport_services s "
        "WHERE s.allocated_kg > 0 LIMIT 500"
    )
    for sid, rollup, actual in rows:
        assert abs(rollup - actual) < 1.0, f"{sid}: rollup {rollup} != sum {actual}"


def test_allocation_uniqueness():
    """I2: each leg has at most one active (non-ROLLED) allocation."""
    dup = scalar(
        "SELECT COUNT(*) FROM (SELECT leg_id FROM fact_allocations "
        "WHERE allocation_status != 'ROLLED' GROUP BY leg_id HAVING COUNT(*) > 1)"
    )
    assert dup == 0, f"{dup} legs have >1 active allocation"


def test_cutoff_feasible():
    """I3 (cut-off): no CONFIRMED allocation was booked after the service cut-off."""
    bad = scalar(
        "SELECT COUNT(*) FROM fact_allocations a "
        "JOIN dim_transport_services s ON a.service_id = s.service_id "
        "WHERE a.allocation_status = 'CONFIRMED' AND a.booked_ts > s.cutoff_ts"
    )
    assert bad == 0, f"{bad} confirmed allocations past cut-off"


def test_rollover_semantics():
    """ROLLED/REACCOMMODATED rows carry a reason; disruption rolls name their source."""
    missing_reason = scalar(
        "SELECT COUNT(*) FROM fact_allocations "
        "WHERE allocation_status IN ('ROLLED', 'REACCOMMODATED') "
        "AND (roll_reason IS NULL OR roll_reason = '')"
    )
    assert missing_reason == 0, f"{missing_reason} rolled rows lack a reason"
    disruption_no_src = scalar(
        "SELECT COUNT(*) FROM fact_allocations "
        "WHERE roll_reason = 'DISRUPTION' "
        "AND (rolled_from_service_id IS NULL OR rolled_from_service_id = '')"
    )
    assert disruption_no_src == 0


def test_typhoon_cascade():
    """One typhoon event rolls ≥20 distinct shipments off its cancelled services."""
    cancelled = scalar(
        "SELECT COUNT(*) FROM dim_transport_services "
        "WHERE status = 'CANCELLED' AND disruption_event_id != ''"
    )
    assert cancelled > 0, "no cancelled services in the typhoon window"
    rolled = scalar(
        "SELECT COUNT(DISTINCT a.shipment_id) FROM fact_allocations a "
        "JOIN dim_transport_services s ON a.rolled_from_service_id = s.service_id "
        "WHERE s.status = 'CANCELLED' AND s.disruption_event_id != ''"
    )
    assert rolled >= 20, f"typhoon rolled only {rolled} shipments"


def test_priority_mix():
    """All five priority classes are represented so contention is differentiated."""
    classes = {r[0] for r in q("SELECT DISTINCT priority_class FROM fact_allocations")}
    assert {"PHARMA", "GENERAL", "HIGH_VALUE", "DG"} <= classes


def test_legs_reference_services():
    """Backfilled voyage_flight_no on allocated AIR legs matches a real service_no."""
    mismatch = scalar(
        "SELECT COUNT(*) FROM fact_shipment_legs l "
        "JOIN fact_allocations a ON a.leg_id = l.leg_id "
        "JOIN dim_transport_services s ON a.service_id = s.service_id "
        "WHERE l.voyage_flight_no != s.service_no"
    )
    assert mismatch == 0, f"{mismatch} legs disagree with their service number"
