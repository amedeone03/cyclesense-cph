import pytest

from cyclesense.coverage import evaluate_coverage
from cyclesense.placement import (
    CandidateSite,
    fill_to_k,
    local_metres,
    mean_pairwise_distance_m,
    multi_counter_fraction,
    select_counters,
    select_frequency,
    select_greedy,
    select_kmeans,
    select_random,
    snap_centroids,
)

SITES = (
    CandidateSite("a", 12.0, 55.0, 0.0, 0.0),
    CandidateSite("b", 12.0, 55.0, 1.0, 0.0),
    CandidateSite("c", 12.0, 55.0, 10.0, 0.0),
    CandidateSite("d", 12.0, 55.0, 100.0, 0.0),
    CandidateSite("only_eval", 12.0, 55.0, 50.0, 0.0),
)
CALIBRATION = {"r1": {"a", "b"}, "r2": {"a"}, "r3": {"c"}}
EVALUATION = {"held": {"only_eval"}}


def test_local_metres_points_east_of_the_reference() -> None:
    x_m, y_m = local_metres(1.0, 0.0, 0.0, 0.0)
    assert x_m == pytest.approx(111_320.0)
    assert y_m == pytest.approx(0.0)


def test_random_is_exactly_k_and_repeats_for_a_fixed_seed() -> None:
    first = select_random(["b", "a", "c", "d"], 2, seed=7)
    second = select_random(["c", "a", "b", "d"], 2, seed=7)
    assert first == second
    assert len(first) == 2
    assert len(set(first)) == 2
    assert set(first) <= {"a", "b", "c", "d"}


def test_frequency_ranks_calibration_weight_and_breaks_ties_by_id() -> None:
    selected = select_frequency(["a", "b", "c", "d", "only_eval"], CALIBRATION, 3)
    assert selected == ("a", "b", "c")
    assert "only_eval" not in selected


def test_greedy_matches_coverage_and_fills_to_exactly_k() -> None:
    selected = select_greedy(["a", "b", "c", "d"], CALIBRATION, 3)
    assert selected[:2] == ("a", "c")
    assert selected[2] == "b"
    assert len(set(selected)) == 3
    scored = evaluate_coverage(CALIBRATION, selected)
    assert scored.coverage_fraction == pytest.approx(1.0)
    doubled = evaluate_coverage({"r1": {"a", "b"}}, ["a", "b"])
    assert doubled.covered_weight == pytest.approx(1.0)


def test_frequency_and_greedy_do_not_use_held_out_edges() -> None:
    eligible = [site.edge_id for site in SITES]
    frequency = select_frequency(eligible, CALIBRATION, 1)
    greedy = select_greedy(eligible, CALIBRATION, 1)
    assert frequency == ("a",)
    assert greedy == ("a",)
    assert "only_eval" not in frequency
    assert "only_eval" not in greedy
    heldout = evaluate_coverage(EVALUATION, greedy).coverage_fraction
    assert heldout == 0.0


def test_snap_centroids_skips_an_already_used_site() -> None:
    sites = (
        CandidateSite("a", 0, 0, 0.0, 0.0),
        CandidateSite("b", 0, 0, 1.0, 0.0),
        CandidateSite("c", 0, 0, 10.0, 0.0),
    )
    selected = snap_centroids([(0.1, 0.0), (0.2, 0.0)], sites)
    assert selected == ("a", "b")


def test_kmeans_is_deterministic_and_separates_distant_groups() -> None:
    pytest.importorskip("sklearn")
    sites = (
        CandidateSite("west_a", 0, 0, 0.0, 0.0),
        CandidateSite("west_b", 0, 0, 1.0, 0.0),
        CandidateSite("east_a", 0, 0, 1000.0, 0.0),
        CandidateSite("east_b", 0, 0, 1001.0, 0.0),
    )
    first = select_kmeans(sites, 2, seed=0)
    second = select_kmeans(sites, 2, seed=0)
    assert first == second
    assert len(set(first)) == 2
    by_id = {site.edge_id: site.x_m for site in sites}
    assert abs(by_id[first[0]] - by_id[first[1]]) > 500


def test_dispatcher_rejects_a_missing_stochastic_seed() -> None:
    with pytest.raises(ValueError):
        select_counters("random", SITES, CALIBRATION, 1, seed=None)


def test_multi_counter_fraction_and_dispersion() -> None:
    routes = {"one": {"a"}, "two": {"a", "b"}, "three": {"a", "c"}}
    assert multi_counter_fraction(routes, ["a", "b"]) == pytest.approx(1 / 3)
    assert mean_pairwise_distance_m([(0.0, 0.0), (3.0, 4.0)]) == pytest.approx(5.0)
    assert fill_to_k(("a",), ["b", "a", "c"], 2) == ("a", "b")
