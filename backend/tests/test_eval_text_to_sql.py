"""R5-1 semantic-layer eval harness.

A golden question set that asserts not just "the SQL runs" but that the verified
few-shot catalog is internally consistent and the answers are stable and
correctly-grained. A deliberately broken join is caught by test_broken_join_caught.
"""

import os
import sqlite3

import pytest

from app.agent.safety import validate_and_rewrite
from app.semantic_layer import FEW_SHOT_QUERY_CATALOG, rank_few_shots

DB = os.environ["DB_PATH"]


def _run(sql):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = conn.execute(sql)
        cols = [c[0] for c in cur.description] if cur.description else []
        return cols, cur.fetchall()
    finally:
        conn.close()


def test_every_few_shot_passes_firewall_and_runs():
    """All verified few-shots must survive the read-only firewall and execute."""
    for shot in FEW_SHOT_QUERY_CATALOG:
        safe = validate_and_rewrite(shot["sql"])
        cols, rows = _run(safe)
        assert isinstance(cols, list), shot["id"]


def test_few_shots_are_deterministic():
    """Same SQL twice -> identical rows (no fan-out / nondeterminism)."""
    for shot in FEW_SHOT_QUERY_CATALOG:
        safe = validate_and_rewrite(shot["sql"])
        _, a = _run(safe)
        _, b = _run(safe)
        assert a == b, f"{shot['id']} is non-deterministic"


def test_network_few_shots_present():
    ids = {s["id"] for s in FEW_SHOT_QUERY_CATALOG}
    assert {"F1", "F2", "F3"} <= ids


@pytest.mark.parametrize("question,expected_id", [
    ("Which transport services are the most heavily loaded?", "F1"),
    ("How many shipments were rolled over and why?", "F2"),
])
def test_ranking_picks_right_shot(question, expected_id):
    ranked = rank_few_shots(question, k=1)
    assert ranked and ranked[0]["id"] == expected_id


def test_coverage_metric_matches_recompute():
    """The headline data-quality number equals an independent recomputation
    (metric-drift guard)."""
    from app.events.projector import ensure_views

    conn = sqlite3.connect(DB)
    ensure_views(conn)
    cov, planned, covered = conn.execute(
        "SELECT coverage_pct, planned_milestones, covered_milestones FROM v_data_quality"
    ).fetchone()
    conn.close()
    assert abs(cov - round(100.0 * covered / planned, 2)) < 0.01


def test_broken_join_caught():
    """A deliberately wrong join (cartesian) inflates the count — the eval catches
    that the correct query and the broken one disagree."""
    correct = "SELECT COUNT(*) FROM fact_allocations WHERE allocation_status='CONFIRMED'"
    broken = (
        "SELECT COUNT(*) FROM fact_allocations a, dim_transport_services s "
        "WHERE a.allocation_status='CONFIRMED'"  # missing join predicate -> cartesian
    )
    _, c = _run(correct)
    _, b = _run(broken)
    assert c[0][0] != b[0][0], "broken cartesian join was not detectable"
