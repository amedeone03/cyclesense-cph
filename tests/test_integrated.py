"""Synthetic checks for the verified-LSH placement pipeline.

These tests do not read the Copenhagen extract and do not claim a traffic result.
"""

import pytest

from cyclesense.communities import detect_communities, similarity_graph
from cyclesense.coverage import evaluate_coverage
from cyclesense.integrated import (
    CANONICAL_ARTIFACTS,
    OUTPUT_DIRNAME,
    adjusted_rand_index,
    balanced_selection,
    compare_similarity_graphs,
    exact_similarity_graph,
    normalized_mutual_information,
    placement_overlap,
    same_weighted_graph,
    streaming_exact_graph,
    tracked_call,
    verified_lsh_graph,
)
from cyclesense.minhash import verify_candidates
from cyclesense.placement import assert_selection

ROUTES = {
    "a": {"e1", "e2", "e3", "e4"},
    "b": {"e1", "e2", "e3", "e4"},
    "c": {"z1", "z2", "z3"},
    "heldout": {"e1", "e2"},
}


def test_streaming_exact_matches_materialized_graph_partition_and_counters() -> None:
    routes = {
        "a": {"e1", "e2", "e3", "e4"},
        "b": {"e1", "e2", "e3", "e5"},
        "c": {"e1"},
        "d": set(),
        "e": {"q1", "q2"},
    }
    exact_graph, pairs = exact_similarity_graph(routes, 0.5)
    streamed = streaming_exact_graph(routes, 0.5)
    assert len(pairs) > exact_graph.number_of_edges()
    assert same_weighted_graph(exact_graph, streamed)
    assert "d" in streamed
    assert streamed.degree("d") == 0
    exact_labels, _modularity, _sizes = detect_communities(exact_graph, 42)
    streamed_labels, _modularity, _sizes = detect_communities(streamed, 42)
    assert exact_labels == streamed_labels
    eligible = ["e1", "e2", "e3", "e4", "e5", "q1"]
    placement = {route_id: set(edges) & set(eligible) for route_id, edges in routes.items()}
    exact_selected, _weights = balanced_selection(eligible, placement, exact_labels, 0.25, 2)
    streamed_selected, _weights = balanced_selection(eligible, placement, streamed_labels, 0.25, 2)
    assert exact_selected == streamed_selected
    assert_selection(streamed_selected, eligible, 2)


def test_verified_graph_has_same_nodes_and_exact_weights() -> None:
    calibration = {route_id: edges for route_id, edges in ROUTES.items() if route_id != "heldout"}
    exact, _pairs = exact_similarity_graph(calibration, 0.5)
    approximate, _candidates, verified = verified_lsh_graph(
        calibration,
        num_perm=32,
        bands=16,
        rows=2,
        threshold=0.5,
        seed=42,
    )
    comparison = compare_similarity_graphs(exact, approximate)
    assert set(approximate.nodes) == set(calibration)
    assert "heldout" not in approximate
    assert verified == {(0, 1)}
    assert comparison["n_edges_missed"] == 0
    assert comparison["graph_edge_recall"] == 1
    assert approximate["a"]["b"]["weight"] == 1.0


def test_verification_drops_a_dissimilar_candidate() -> None:
    kept = verify_candidates({(0, 1)}, [{"e1"}, {"z1"}], 0.5)
    assert kept == set()


def test_invented_edge_is_rejected() -> None:
    calibration = {route_id: edges for route_id, edges in ROUTES.items() if route_id != "heldout"}
    exact, _pairs = exact_similarity_graph(calibration, 0.5)
    invented = similarity_graph(calibration, [("a", "c", 0.9)], 0.5)
    with pytest.raises(ValueError, match="invented"):
        compare_similarity_graphs(exact, invented)


def test_unknown_route_cannot_enter_the_graph() -> None:
    with pytest.raises(ValueError, match="not a graph node"):
        similarity_graph(["a"], [("a", "heldout", 1.0)], 0.5)


def test_louvain_is_deterministic_for_a_fixed_seed() -> None:
    calibration = {route_id: edges for route_id, edges in ROUTES.items() if route_id != "heldout"}
    graph, _pairs = exact_similarity_graph(calibration, 0.5)
    first, _modularity, _sizes = detect_communities(graph, 42)
    second, _modularity, _sizes = detect_communities(graph, 42)
    assert first == second
    assert set(first) == set(calibration)


def test_partition_metrics_ignore_label_numbers() -> None:
    left = {"a": 0, "b": 0, "c": 1, "d": 1}
    swapped = {"a": 7, "b": 7, "c": 3, "d": 3}
    assert adjusted_rand_index(left, swapped) == pytest.approx(1)
    assert normalized_mutual_information(left, swapped) == pytest.approx(1)
    crossed = {"a": 0, "b": 1, "c": 0, "d": 1}
    assert adjusted_rand_index(left, crossed) < 1


def test_lambda_zero_ignores_the_partition_and_returns_k_edges() -> None:
    routes = {"a": {"e1"}, "b": {"e2"}, "c": {"e1", "e3"}}
    eligible = ["e1", "e2", "e3"]
    first, _weights = balanced_selection(eligible, routes, {"a": 0, "b": 0, "c": 1}, 0.0, 2)
    second, _weights = balanced_selection(eligible, routes, {"a": 1, "b": 2, "c": 2}, 0.0, 2)
    assert first == second
    assert_selection(first, eligible, 2)
    assert evaluate_coverage(routes, first).coverage_fraction == pytest.approx(1)


def test_placement_overlap_and_coverage_difference() -> None:
    overlap = placement_overlap(["e1", "e2"], ["e2", "e3"])
    assert overlap["n_shared"] == 1
    assert overlap["selected_jaccard"] == pytest.approx(1 / 3)
    routes = {"r1": {"e1"}, "r2": {"e2"}, "r3": {"e3"}, "r4": {"e1"}}
    exact = evaluate_coverage(routes, ["e1", "e2"]).coverage_fraction
    approximate = evaluate_coverage(routes, ["e2", "e3"]).coverage_fraction
    assert exact == pytest.approx(0.75)
    assert approximate - exact == pytest.approx(-0.25)


def test_tracked_call_reports_python_allocations() -> None:
    def allocate():
        return [0] * 1000

    value, elapsed, peak_mb = tracked_call(allocate)
    assert len(value) == 1000
    assert elapsed >= 0
    assert peak_mb > 0


def test_study_outputs_do_not_replace_canonical_artifacts() -> None:
    assert OUTPUT_DIRNAME == "outputs/integrated"
    joined = " ".join(CANONICAL_ARTIFACTS)
    assert "outputs/m3/summary.json" in joined
    assert "outputs/m4/placements.csv" in joined
    assert "outputs/m5/summary.json" in joined
    assert not any(path.startswith(OUTPUT_DIRNAME) for path in CANONICAL_ARTIFACTS)
