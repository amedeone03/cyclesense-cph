import random

import pytest

from cyclesense.balanced import (
    community_size_counts,
    community_weights,
    represented_communities,
    shuffle_labels,
    status_coverage,
)
from cyclesense.communities import similarity_graph
from cyclesense.coverage import evaluate_coverage
from cyclesense.placement import select_greedy


def test_weights_are_nonnegative_and_sum_to_one() -> None:
    labels = {"a": 0, "b": 0, "c": 1, "d": 1, "e": 1, "f": 1, "s": 2}
    weights, info = community_weights(labels, 0.25)
    assert info["fallback_uniform"] is False
    assert sum(weights.values()) == pytest.approx(1.0)
    assert all(value >= 0 for value in weights.values())
    assert info["n_non_singleton_communities"] == 2


def test_lambda_zero_is_uniform_and_matches_unweighted_greedy() -> None:
    labels = {"r1": 0, "r2": 0, "r3": 1}
    weights, info = community_weights(labels, 0.0)
    assert info["fallback_uniform"] is False
    assert list(weights.values()) == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    routes = {"r1": {"a", "b"}, "r2": {"a"}, "r3": {"c"}}
    weighted = select_greedy(["a", "b", "c", "d"], routes, 2, weights)
    unweighted = select_greedy(["a", "b", "c", "d"], routes, 2)
    assert weighted == unweighted
    scored = evaluate_coverage(routes, weighted)
    assert scored.covered_weight == pytest.approx(3.0)


def test_non_singleton_communities_share_the_balancing_weight() -> None:
    labels = {"a": 0, "b": 0, "c": 1, "d": 1, "e": 1, "f": 1, "s": 2}
    weights, _info = community_weights(labels, 1.0)
    assert weights["s"] == pytest.approx(0.0)
    pair = weights["a"] + weights["b"]
    quad = weights["c"] + weights["d"] + weights["e"] + weights["f"]
    assert pair == pytest.approx(quad)
    assert pair == pytest.approx(0.5)


def test_all_singletons_fall_back_to_uniform_weights() -> None:
    labels = {"a": 0, "b": 1, "c": 2}
    weights, info = community_weights(labels, 0.5)
    assert info["fallback_uniform"] is True
    assert list(weights.values()) == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_shuffle_preserves_community_sizes_and_is_reproducible() -> None:
    labels = {"a": 0, "b": 0, "c": 1, "d": 2, "e": 3}
    first = shuffle_labels(labels, seed=5)
    second = shuffle_labels(labels, seed=5)
    assert first == second
    assert community_size_counts(first) == community_size_counts(labels)
    assert community_size_counts(shuffle_labels(labels, seed=6)) == (1, 1, 1, 2)


def test_represented_community_counts_a_route_once() -> None:
    routes = {"a": {"x", "y"}, "b": {"y"}, "c": {"z"}}
    labels = {"a": 0, "b": 0, "c": 1}
    report = represented_communities(routes, labels, ["y"])
    assert report["n_represented"] == 1
    assert report["n_large_represented"] == 1
    assert report["large_member_coverage_mean"] == pytest.approx(1.0)
    doubled = evaluate_coverage(routes, ["x", "y"])
    assert doubled.covered_weight == pytest.approx(2.0)


def test_status_coverage_keeps_ambiguous_and_unassigned_routes() -> None:
    routes = {"near": {"a"}, "split": {"b"}, "far": {"c"}}
    assignments = [
        {"route_id": "near", "status": "assigned"},
        {"route_id": "split", "status": "ambiguous"},
        {"route_id": "far", "status": "unassigned"},
    ]
    report = status_coverage(routes, assignments, ["a", "b"])
    assert report["assigned_coverage"] == pytest.approx(1.0)
    assert report["ambiguous_coverage"] == pytest.approx(1.0)
    assert report["unassigned_coverage"] == pytest.approx(0.0)
    assert report["overall_coverage"] == pytest.approx(2 / 3)


def test_greedy_tie_break_and_zero_weight_do_not_add_a_duplicate() -> None:
    routes = {"r1": {"z"}, "r2": {"a"}, "dead": {"q"}}
    weights = {"r1": 1.0, "r2": 1.0, "dead": 0.0}
    selected = select_greedy(["z", "a", "q"], routes, 2, weights)
    assert selected == ("a", "z")
    assert len(set(selected)) == 2
    again = select_greedy(["z", "a", "q"], routes, 2, weights)
    assert again == selected


def test_selection_does_not_read_an_evaluation_only_route() -> None:
    calibration = {"train": {"a"}}
    weights, _info = community_weights({"train": 0}, 0.0)
    selected = select_greedy(["a", "only_eval"], calibration, 1, weights)
    assert selected == ("a",)
    assert "heldout" not in weights


def test_both_similarity_thresholds_keep_different_edges() -> None:
    pairs = (("a", "b", 0.4), ("a", "c", 0.2))
    at_0_3 = similarity_graph(["a", "b", "c"], pairs, 0.3)
    at_0_5 = similarity_graph(["a", "b", "c"], pairs, 0.5)
    assert at_0_3.number_of_edges() == 1
    assert at_0_5.number_of_edges() == 0


def test_invalid_lambda_and_empty_labels_are_rejected() -> None:
    with pytest.raises(ValueError):
        community_weights({}, 0.0)
    with pytest.raises(ValueError):
        community_weights({"a": 0}, 1.5)


def test_shuffle_seed_changes_the_assignment_without_changing_sizes() -> None:
    labels = {f"r{index}": index // 3 for index in range(12)}
    left = shuffle_labels(labels, 1)
    right = shuffle_labels(labels, 2)
    assert left != right
    assert community_size_counts(left) == community_size_counts(right)
    assert random.Random(1).random() != random.Random(2).random()
