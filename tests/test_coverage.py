import pytest

from cyclesense.coverage import evaluate_coverage, greedy_max_coverage

ROUTES = {
    "r1": {"a", "b"},
    "r2": {"a", "c"},
    "r3": {"d"},
}


def test_selects_highest_new_route_coverage() -> None:
    result = greedy_max_coverage(ROUTES, budget=1)
    assert result.selected_edges == ("a",)
    assert result.coverage_fraction == pytest.approx(2 / 3)


def test_does_not_double_count_a_route() -> None:
    result = evaluate_coverage(ROUTES, selected_edges={"a", "b"})
    assert result.coverage_fraction == pytest.approx(2 / 3)


def test_second_counter_improves_coverage() -> None:
    result = greedy_max_coverage(ROUTES, budget=2)
    assert result.selected_edges == ("a", "d")
    assert result.coverage_fraction == pytest.approx(1)


def test_weighted_route_coverage() -> None:
    weights = {"r1": 1, "r2": 1, "r3": 10}
    result = greedy_max_coverage(ROUTES, budget=1, weights=weights)
    assert result.selected_edges == ("d",)
    assert result.coverage_fraction == pytest.approx(10 / 12)


def test_candidate_filter_is_respected() -> None:
    result = greedy_max_coverage(ROUTES, budget=2, eligible_edges={"b", "d"})
    assert result.selected_edges == ("b", "d")
    assert result.coverage_fraction == pytest.approx(2 / 3)


def test_zero_budget() -> None:
    result = greedy_max_coverage(ROUTES, budget=0)
    assert result.selected_edges == ()
    assert result.coverage_fraction == 0.0


def test_invalid_budget_and_weights() -> None:
    with pytest.raises(ValueError):
        greedy_max_coverage(ROUTES, budget=-1)
    with pytest.raises(ValueError):
        greedy_max_coverage(ROUTES, budget=1, weights={"r1": -2.0})


def test_deterministic_tiebreak() -> None:
    result = greedy_max_coverage({"r1": {"z"}, "r2": {"a"}}, budget=1)
    assert result.selected_edges == ("a",)
