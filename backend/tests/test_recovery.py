"""Recovery closed-loop tests (Release A).

Re-accommodating a shipment's AIR leg onto another service must:
  - roll the allocation (status REACCOMMODATED, rolled_from set),
  - keep shared-capacity water-lines conservative (sum allocated unchanged),
  - auto-resolve the shipment's OPEN alerts,
  - enqueue a notice (when a subscription matches),
  - stay idempotent (same target twice = no-op),
  - reject when the target service has no room.
"""

import os
import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.recovery.reaccommodate import RecoveryError, reaccommodate

DB = os.environ["DB_PATH"]


def _conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def _pick_shipment_with_air_alloc():
    conn = _conn()
    try:
        return conn.execute(
            """
            SELECT a.shipment_id, a.service_id, a.allocated_weight_kg, a.leg_id,
                   s.destination_facility
            FROM fact_allocations a
            JOIN fact_shipment_legs l ON l.leg_id = a.leg_id
            JOIN dim_transport_services s ON s.service_id = a.service_id
            WHERE l.transport_mode = 'AIR' AND a.allocation_status = 'CONFIRMED'
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()


def _find_target_with_room(dest, exclude_service, weight):
    conn = _conn()
    try:
        return conn.execute(
            """
            SELECT service_id FROM dim_transport_services
            WHERE transport_mode = 'AIR' AND origin_facility = 'HKG'
              AND destination_facility = ? AND service_id != ?
              AND status != 'CANCELLED'
              AND (capacity_chargeable_kg - allocated_kg) >= ?
            LIMIT 1
            """,
            (dest, exclude_service, weight),
        ).fetchone()
    finally:
        conn.close()


def _total_allocated(conn):
    return conn.execute("SELECT ROUND(SUM(allocated_kg), 3) FROM dim_transport_services").fetchone()[0]


def test_reaccommodate_rolls_allocation_and_conserves_capacity():
    src = _pick_shipment_with_air_alloc()
    assert src is not None, "fixture needs an AIR allocation"
    target = _find_target_with_room(src["destination_facility"], src["service_id"], src["allocated_weight_kg"])
    assert target is not None, "fixture needs a target service with room"

    conn = _conn()
    before_total = _total_allocated(conn)
    conn.close()

    result = reaccommodate(src["shipment_id"], target["service_id"], reason="DISRUPTION", actor="tester")
    assert result["no_op"] is False
    assert result["rolled_from"] == src["service_id"]
    assert result["rolled_to"] == target["service_id"]

    conn = _conn()
    try:
        # capacity conservation: total allocated kg across services unchanged
        assert _total_allocated(conn) == before_total

        alloc = conn.execute(
            "SELECT service_id, allocation_status, rolled_from_service_id, roll_reason "
            "FROM fact_allocations WHERE leg_id = ?",
            (src["leg_id"],),
        ).fetchone()
        assert alloc["service_id"] == target["service_id"]
        assert alloc["allocation_status"] == "REACCOMMODATED"
        assert alloc["rolled_from_service_id"] == src["service_id"]
        assert alloc["roll_reason"] == "DISRUPTION"

        # leg realigned to the new service's flight number
        new_no = conn.execute(
            "SELECT service_no FROM dim_transport_services WHERE service_id = ?",
            (target["service_id"],),
        ).fetchone()[0]
        leg_no = conn.execute(
            "SELECT voyage_flight_no FROM fact_shipment_legs WHERE leg_id = ?",
            (src["leg_id"],),
        ).fetchone()[0]
        assert leg_no == new_no
    finally:
        conn.close()


def test_reaccommodate_resolves_open_alert():
    src = _pick_shipment_with_air_alloc()
    target = _find_target_with_room(src["destination_facility"], src["service_id"], src["allocated_weight_kg"])
    assert src and target

    # plant an OPEN alert for this shipment (numeric suffix so it doesn't poison
    # MAX(alert_id) parsing used by the raise_alert id generator)
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO fact_alerts (alert_id, shipment_id, source, severity, title, detail, "
            "status, created_ts, updated_ts) VALUES "
            "('AL-900001', ?, 'rules', 'high', 'test open', 'planted', 'OPEN', "
            "'2025-01-01T00:00:00Z', '2025-01-01T00:00:00Z')",
            (src["shipment_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    result = reaccommodate(src["shipment_id"], target["service_id"], actor="tester")
    assert "AL-900001" in result["resolved_alerts"]

    conn = _conn()
    try:
        status = conn.execute(
            "SELECT status FROM fact_alerts WHERE alert_id = 'AL-900001'"
        ).fetchone()[0]
        assert status == "RESOLVED"
    finally:
        conn.close()


def test_reaccommodate_idempotent_noop_on_same_service():
    src = _pick_shipment_with_air_alloc()
    assert src is not None
    result = reaccommodate(src["shipment_id"], src["service_id"], actor="tester")
    assert result["no_op"] is True
    assert result["resolved_alerts"] == []


def test_reaccommodate_rejects_when_no_fit():
    src = _pick_shipment_with_air_alloc()
    assert src is not None
    # a cancelled or over-full target: force no_fit by picking a service and
    # filling it; simplest is to target a service and assert RecoveryError when
    # the weight can't fit. Build a synthetic over-full service.
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO dim_transport_services (service_id, transport_mode, carrier_code, "
            "service_no, origin_facility, destination_facility, scheduled_depart_ts, "
            "scheduled_arrive_ts, cutoff_ts, mct_minutes, capacity_chargeable_kg, capacity_cbm, "
            "allocated_kg, allocated_cbm, status) VALUES "
            "('SVC-FULL-TEST', 'AIR', 'CX', 'CX999', 'HKG', ?, '2099-01-01T00:00:00Z', "
            "'2099-01-02T00:00:00Z', '2098-12-31T00:00:00Z', 90, 100.0, 10.0, 100.0, 10.0, 'SCHEDULED')",
            (src["destination_facility"],),
        )
        conn.commit()
    finally:
        conn.close()

    try:
        reaccommodate(src["shipment_id"], "SVC-FULL-TEST", actor="tester")
        assert False, "expected RecoveryError for no fit"
    except RecoveryError as e:
        assert e.code == "no_fit"


def test_reaccommodate_endpoint_contract():
    src = _pick_shipment_with_air_alloc()
    target = _find_target_with_room(src["destination_facility"], src["service_id"], src["allocated_weight_kg"])
    assert src and target
    c = TestClient(app)

    # reroute options read endpoint
    r = c.get(f"/api/network/reroute-options/{src['shipment_id']}")
    assert r.status_code == 200
    assert "options" in r.json()

    # commit
    r = c.post(
        f"/api/network/reaccommodate/{src['shipment_id']}",
        json={"to_service_id": target["service_id"], "reason": "DISRUPTION"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rolled_to"] == target["service_id"]


def test_reaccommodate_unknown_shipment_404():
    try:
        reaccommodate("SHP-DOES-NOT-EXIST", "SVC-ANY", actor="tester")
        assert False, "expected RecoveryError"
    except RecoveryError as e:
        assert e.code == "not_found"
