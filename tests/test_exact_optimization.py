"""Exact maximum coverage against brute force and status rules."""

from __future__ import annotations

import pytest

from cyclesense.coverage import evaluate_coverage
from cyclesense.exact_optimization import (
    APPROXIMATION_RATIO,
    brute_force_maximum_coverage,
    coverage_bounds,
    greedy_optimality_gap,
    meets_approximation_guarantee,
    solve_maximum_coverage,
)
from cyclesense.placement import select_greedy

ROUTES = {
    "r1": {"a", "b"},
    "r2": {"a"},
    "r3": {"b", "c"},
    "r4": {"c"},
    "r5": set(),
}
WEIGHTS = {"r1": 0.1, "r2": 0.3, "r3": 0.2, "r4": 0.3, "r5": 0.1}
EDGES = ["c", "a", "b", "d"]


def test_milp_matches_brute_force_for_weighted_and_unweighted() -> None:
    for weights in (None, WEIGHTS):
        table = {route_id: 1.0 / len(ROUTES) for route_id in ROUTES} if weights is None else weights
        for budget in (1, 2, 3):
            exact = solve_maximum_coverage(ROUTES, table, EDGES, budget, time_limit_seconds=10)
            _support, best = brute_force_maximum_coverage(ROUTES, table, EDGES, budget)
            assert exact.proven_optimal is True
            assert exact.status == "optimal"
            assert exact.solver_objective == pytest.approx(best, abs=1e-6)
            assert len(exact.selected) == budget
            assert len(set(exact.selected)) == budget
            assert set(exact.selected) <= set(EDGES)


def test_candidate_index_and_physical_ids_are_stable() -> None:
    first = solve_maximum_coverage(ROUTES, WEIGHTS, ["b", "a", "c", "d"], 2, time_limit_seconds=10)
    second = solve_maximum_coverage(ROUTES, WEIGHTS, ["d", "c", "b", "a"], 2, time_limit_seconds=10)
    assert first.selected == second.selected
    assert all(edge.startswith(("a", "b", "c", "d")) for edge in first.selected)


def test_zero_incidence_and_duplicate_routes() -> None:
    routes = {"covered": {"e"}, "again": {"e"}, "empty": set(), "zero": {"z"}}
    weights = {"covered": 0.4, "again": 0.4, "empty": 0.2, "zero": 0.0}
    exact = solve_maximum_coverage(routes, weights, ["e", "z", "other"], 1, time_limit_seconds=10)
    assert exact.proven_optimal
    assert exact.support == ("e",)
    scored = evaluate_coverage(routes, exact.selected, weights)
    assert scored.covered_weight == pytest.approx(0.8)
    assert exact.coverage == pytest.approx(scored.coverage_fraction)


def test_fewer_than_k_counters_are_filled_without_changing_coverage() -> None:
    routes = {"only": {"e"}}
    weights = {"only": 1.0}
    exact = solve_maximum_coverage(routes, weights, ["e", "a", "b"], 3, time_limit_seconds=10)
    assert exact.support == ("e",)
    assert exact.selected == ("e", "a", "b")
    assert exact.coverage == pytest.approx(1.0)


def test_bounds_flip_the_minimized_objective() -> None:
    incumbent, upper = coverage_bounds(-0.8, -1.0)
    assert incumbent == pytest.approx(0.8)
    assert upper == pytest.approx(1.0)
    gap = greedy_optimality_gap(1.0, 0.8, proven=True)
    assert gap["absolute_gap"] == pytest.approx(0.2)
    assert gap["relative_gap"] == pytest.approx(0.2)
    assert greedy_optimality_gap(1.0, 0.8, proven=False) == {"absolute_gap": None, "relative_gap": None}
    with pytest.raises(ValueError, match="exceeds"):
        greedy_optimality_gap(0.5, 0.8, proven=True)


def test_zero_optimum_gap_and_approximation_ratio() -> None:
    assert greedy_optimality_gap(0.0, 0.0, proven=True)["relative_gap"] == 0.0
    assert meets_approximation_guarantee(APPROXIMATION_RATIO, 1.0)
    assert not meets_approximation_guarantee(0.5, 1.0)


def test_greedy_stays_within_a_certified_optimum() -> None:
    exact = solve_maximum_coverage(ROUTES, WEIGHTS, EDGES, 2, time_limit_seconds=10)
    greedy = select_greedy(EDGES, ROUTES, 2, WEIGHTS)
    greedy_value = evaluate_coverage(ROUTES, greedy, WEIGHTS).covered_weight
    assert greedy_value <= exact.solver_objective + 1e-6
    assert meets_approximation_guarantee(greedy_value, exact.solver_objective)


def test_time_limit_status_is_not_optimal(monkeypatch: pytest.MonkeyPatch) -> None:
    from cyclesense import exact_optimization as module

    def fake_solve(*_args, **_kwargs):
        return {
            "status_code": 1,
            "message": "time limit",
            "x": None,
            "fun": None,
            "dual": -1.0,
            "route_ids": list(ROUTES),
            "incidence": (),
        }

    monkeypatch.setattr(module, "_solve_milp", fake_solve)
    result = solve_maximum_coverage(ROUTES, WEIGHTS, EDGES, 1, time_limit_seconds=10)
    assert result.status == "no_incumbent"
    assert result.proven_optimal is False
    assert result.selected == ()


def test_fixed_municipal_edges_are_excluded_from_new_selection() -> None:
    installed = {"municipal"}
    routes = {"already": {"municipal"}, "fresh": {"new"}, "other": {"other"}}
    residual = {route_id: edges for route_id, edges in routes.items() if edges.isdisjoint(installed)}
    weights = {route_id: 1.0 / len(residual) for route_id in residual}
    exact = solve_maximum_coverage(residual, weights, ["new", "other"], 1, time_limit_seconds=10)
    assert exact.proven_optimal
    assert "municipal" not in exact.selected
    assert exact.solver_objective == pytest.approx(0.5)


def test_held_out_routes_are_not_an_argument_of_the_solver() -> None:
    assert "evaluation" not in solve_maximum_coverage.__doc__
    source = solve_maximum_coverage.__doc__ or ""
    assert "at most" in source
