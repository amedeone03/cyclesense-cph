import networkx as nx
import pytest

from cyclesense.balanced import community_size_counts, shuffle_labels
from cyclesense.retrieval_benchmark import exact_similar_pairs, lsh_verified_pairs
from cyclesense.routes import generate_modeled_routes
from cyclesense.validation_stats import (
    outside_central_90,
    paired_differences,
    sample_summary,
)


def test_sample_summary_percentiles_are_ordered() -> None:
    summary = sample_summary(list(range(1, 101)))
    assert summary["n"] == 100
    assert summary["mean"] == pytest.approx(50.5)
    assert summary["min"] == 1
    assert summary["max"] == 100
    assert float(summary["p05"]) < float(summary["p50"]) < float(summary["p95"])
    assert float(summary["std"]) > 0


def test_paired_differences_follow_the_sample_index() -> None:
    assert paired_differences([0.5, 0.4], [0.5, 0.3]) == pytest.approx([0.0, -0.1])
    with pytest.raises(ValueError):
        paired_differences([0.1], [0.1, 0.2])


def test_central_interval_is_descriptive() -> None:
    summary = sample_summary([float(value) for value in range(30)])
    assert outside_central_90(-1.0, summary)
    assert not outside_central_90(float(summary["p50"]), summary)


def test_thirty_shuffles_keep_the_size_distribution() -> None:
    labels = {f"r{index}": index // 4 for index in range(20)}
    expected = community_size_counts(labels)
    seen = []
    for seed in range(30):
        shuffled = shuffle_labels(labels, seed)
        assert community_size_counts(shuffled) == expected
        seen.append(tuple(shuffled[route_id] for route_id in sorted(shuffled)))
    assert len(set(seen)) > 1


def test_verified_lsh_pairs_are_exact_matches() -> None:
    routes = [{"a", "b", "c"}, {"a", "b", "c"}, {"x", "y", "z"}]
    exact = exact_similar_pairs(routes, 0.5)
    candidates, verified = lsh_verified_pairs(
        routes, num_perm=16, bands=16, rows=1, threshold=0.5, seed=1
    )
    assert exact == {(0, 1)}
    assert verified <= candidates
    assert (0, 1) in verified
    assert verified <= exact


def _grid(size: int = 4) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for i in range(size):
        for j in range(size):
            graph.add_node(i * size + j, x=float(i * 120), y=float(j * 120))
    osmid = 1
    for i in range(size):
        for j in range(size):
            node = i * size + j
            if i + 1 < size:
                graph.add_edge(node, node + size, osmid=osmid, length=120.0, highway="residential")
                graph.add_edge(node + size, node, osmid=osmid, length=120.0, highway="residential")
                osmid += 1
            if j + 1 < size:
                graph.add_edge(node, node + 1, osmid=osmid, length=120.0, highway="residential")
                graph.add_edge(node + 1, node, osmid=osmid, length=120.0, highway="residential")
                osmid += 1
    return graph


def test_blocked_canonical_paths_stay_out_of_a_new_sample() -> None:
    from cyclesense.network import assign_physical_edge_ids, build_candidates

    graph = _grid()
    assign_physical_edge_ids(graph)
    candidates, _stats = build_candidates(graph, min_length_m=15)
    candidate_ids = {row["physical_edge_id"] for row in candidates}
    coordinates = {int(node): (float(data["x"]), float(data["y"])) for node, data in graph.nodes(data=True)}
    original, _stats = generate_modeled_routes(
        graph,
        coordinates,
        candidate_ids,
        scenario="uniform",
        n_calibration=2,
        n_evaluation=0,
        calibration_seed=1,
        evaluation_seed=2,
        min_distance_m=200,
        max_distance_m=700,
        min_eligible_edges=2,
        max_attempts_factor=40,
    )
    blocked_paths = [route.physical_edge_ids for route in original]
    blocked_od = [(route.origin_node, route.destination_node) for route in original]
    fresh, stats = generate_modeled_routes(
        graph,
        coordinates,
        candidate_ids,
        scenario="uniform",
        n_calibration=0,
        n_evaluation=2,
        calibration_seed=4,
        evaluation_seed=3,
        min_distance_m=200,
        max_distance_m=700,
        min_eligible_edges=2,
        max_attempts_factor=40,
        blocked_od=blocked_od,
        blocked_paths=blocked_paths,
    )
    assert stats["evaluation"]["kept"] == 2
    assert {route.physical_edge_ids for route in fresh}.isdisjoint(blocked_paths)
    assert {(route.origin_node, route.destination_node) for route in fresh}.isdisjoint(blocked_od)


def test_validation_seeds_do_not_reuse_the_canonical_streams() -> None:
    canonical = {42, 42 + 10007, 24242}
    evaluation = {81000 + index for index in range(20)}
    shuffles = set(range(30))
    assert evaluation.isdisjoint(canonical)
    assert shuffles.isdisjoint(evaluation)
