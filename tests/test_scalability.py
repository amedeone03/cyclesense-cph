"""Scalability helpers on a small grid and on hand-built route sets."""

import networkx as nx
import pytest

from cyclesense.integrated import (
    compare_similarity_graphs,
    streaming_exact_graph,
    verified_lsh_graph,
)
from cyclesense.minhash import build_lsh_buckets, build_signatures, query_lsh_pairs
from cyclesense.network import assign_physical_edge_ids, build_candidates
from cyclesense.routes import generate_modeled_routes
from cyclesense.scalability import (
    OUTPUT_DIRNAME,
    PROTECTED_OUTPUTS,
    ResourceLimit,
    assert_no_evaluation_leakage,
    assert_physical_ids,
    assert_selection,
    candidate_statistics,
    dataset_diagnostics,
    measured,
    nested_prefixes,
    query_lsh_pairs_bounded,
    run_verified_lsh,
    summarize_times,
)
from cyclesense.similarity import jaccard_similarity


def _grid() -> tuple[nx.MultiDiGraph, dict[int, tuple[float, float]], set[str]]:
    graph = nx.MultiDiGraph()
    for i in range(4):
        for j in range(4):
            graph.add_node(i * 4 + j, x=float(i * 100), y=float(j * 100))
    osmid = 1
    for i in range(4):
        for j in range(4):
            node = i * 4 + j
            if i + 1 < 4:
                _both(graph, node, node + 4, osmid)
                osmid += 1
            if j + 1 < 4:
                _both(graph, node, node + 1, osmid)
                osmid += 1
    assign_physical_edge_ids(graph)
    candidates, _stats = build_candidates(graph, min_length_m=15)
    coordinates = {int(node): (float(data["x"]), float(data["y"])) for node, data in graph.nodes(data=True)}
    return graph, coordinates, {row["physical_edge_id"] for row in candidates}


def _both(graph: nx.MultiDiGraph, u_node: int, v_node: int, osmid: int) -> None:
    payload = {"osmid": osmid, "length": 100.0, "highway": "residential", "oneway": False}
    graph.add_edge(u_node, v_node, **payload)
    graph.add_edge(v_node, u_node, **dict(payload))


def _routes():
    graph, coordinates, candidates = _grid()
    common = {
        "scenario": "uniform",
        "n_calibration": 8,
        "n_evaluation": 0,
        "calibration_seed": 11,
        "evaluation_seed": 12,
        "min_distance_m": 80,
        "max_distance_m": 500,
        "min_eligible_edges": 2,
        "max_attempts_factor": 30,
    }
    return generate_modeled_routes(graph, coordinates, candidates, **common)[0], candidates, graph


def test_generation_is_reproducible_and_prefixes_are_nested():
    first, candidates, graph = _routes()
    second, _candidates, _graph = _routes()
    assert [route.physical_edge_ids for route in first] == [route.physical_edge_ids for route in second]
    assert [route.route_id for route in first] == [route.route_id for route in second]
    prefixes = nested_prefixes(first, [3, 6])
    assert [route.route_id for route in prefixes[1][:3]] == [route.route_id for route in prefixes[0]]
    known = {str(data["physical_edge_id"]) for _u, _v, data in graph.edges(data=True)}
    assert_physical_ids(first, known)
    for route in first:
        assert set(route.physical_edge_ids) <= candidates
    diagnostics = dataset_diagnostics(first, generation_seconds=1.0, requested=8)
    assert diagnostics["duplicate_fraction"] == 0.0
    assert diagnostics["n_unique_physical_sets"] == len(first)


def test_nested_prefixes_reject_a_size_the_collection_does_not_contain():
    routes, _candidates, _graph = _routes()
    with pytest.raises(ValueError):
        nested_prefixes(routes, [4, 100])


def test_candidate_pairs_are_unique_and_fractions_match_the_pair_count():
    sets = [{"a", "b", "c"}, {"a", "b", "d"}, {"a", "b", "e"}, {"z"}]
    signatures = build_signatures(sets, 32, seed=42)
    buckets = build_lsh_buckets(signatures, 16, 2)
    pairs = query_lsh_pairs(signatures, buckets, 16, 2)
    bounded = query_lsh_pairs_bounded(signatures, buckets, 16, 2, max_pairs=100, max_bucket_size=10)
    assert pairs == bounded
    assert len(pairs) == len({tuple(sorted(pair)) for pair in pairs})
    stats = candidate_statistics(len(pairs), len(sets))
    possible = 4 * 3 // 2
    assert stats["n_possible_pairs"] == possible
    assert stats["candidate_fraction"] == pytest.approx(len(pairs) / possible)
    assert stats["candidate_reduction"] == pytest.approx(1 - len(pairs) / possible)


def test_verified_edges_match_exact_jaccard_and_do_not_invent_edges():
    routes = {
        "a": {"e1", "e2", "e3", "e4"},
        "b": {"e1", "e2", "e3", "e5"},
        "c": {"e1", "e2"},
        "d": {"z1", "z2", "z3"},
    }
    exact = streaming_exact_graph(routes, 0.5)
    approximate, _candidates, _verified = run_verified_lsh(
        routes,
        num_perm=64,
        bands=32,
        rows=2,
        threshold=0.5,
        seed=42,
        max_pairs=100,
        max_bucket_size=10,
    )
    for left, right, data in approximate.edges(data=True):
        assert float(data["weight"]) == pytest.approx(jaccard_similarity(routes[left], routes[right]))
        assert float(data["weight"]) >= 0.5
    comparison = compare_similarity_graphs(exact, approximate)
    assert comparison["n_edges_missed"] >= 0
    direct, _candidates, _verified = verified_lsh_graph(
        routes, num_perm=64, bands=32, rows=2, threshold=0.5, seed=42
    )
    assert set(direct.edges) == set(approximate.edges)


def test_evaluation_routes_cannot_enter_the_graph_and_selection_has_k_edges():
    with pytest.raises(ValueError):
        assert_no_evaluation_leakage({"uniform:calibration:0000"}, {"uniform:calibration:0000"})
    assert_no_evaluation_leakage({"uniform:calibration:0000"}, {"uniform:evaluation:0000"})
    assert_selection(("pe:1", "pe:2"), {"pe:1", "pe:2", "pe:3"}, 2)
    with pytest.raises(ValueError):
        assert_selection(("pe:1", "pe:1"), {"pe:1"}, 2)


def test_timing_summary_and_missing_measurements():
    summary = summarize_times([1.0, 4.0, 2.0])
    assert summary.median == 2.0
    assert summary.minimum == 1.0
    assert summary.maximum == 4.0
    assert summary.stdev == pytest.approx(1.5275252316519468)
    rows = [
        {"status": "measured", "median_seconds": 1.0},
        {"status": "not_run", "median_seconds": ""},
        {"status": "resource_limit", "reason": "cap"},
    ]
    assert measured(rows) == [rows[0]]


def test_resource_limit_does_not_report_a_finished_candidate_set():
    buckets = {(0, (1,)): [0, 1, 2, 3]}
    signatures = [(1, 1), (1, 1), (1, 1), (1, 1)]
    with pytest.raises(ResourceLimit) as caught:
        query_lsh_pairs_bounded(signatures, buckets, 1, 2, max_pairs=100, max_bucket_size=3)
    assert "bucket" in caught.value.reason
    assert "n_candidates" not in caught.value.observed


def test_outputs_do_not_point_at_canonical_artifacts():
    assert OUTPUT_DIRNAME == "outputs/scalability"
    for protected in PROTECTED_OUTPUTS:
        assert not protected.startswith(OUTPUT_DIRNAME)
        assert not OUTPUT_DIRNAME.startswith(protected)
