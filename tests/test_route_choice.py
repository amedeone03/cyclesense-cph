"""Route-choice perturbations on a small directed multigraph."""

import random

import networkx as nx
import pytest

from cyclesense.route_choice import (
    alternative_route,
    build_adjacency,
    classify_proposal,
    coverage_transition,
    detour_summary,
    edge_cost_factors,
    proposed_shortest,
    shortest_path_from_nodes,
)


def _graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    graph.add_edge(0, 1, key=0, length=10.0, physical_edge_id="pe:direct-a")
    graph.add_edge(0, 1, key=1, length=12.0, physical_edge_id="pe:direct-b")
    graph.add_edge(1, 2, key=0, length=10.0, physical_edge_id="pe:mid")
    graph.add_edge(0, 3, key=0, length=10.0, physical_edge_id="pe:side-a")
    graph.add_edge(3, 2, key=0, length=12.0, physical_edge_id="pe:side-b")
    return graph


def _original(graph: nx.MultiDiGraph):
    return shortest_path_from_nodes(graph, [0, 1, 2])


def test_original_uses_the_lighter_parallel_edge():
    path = _original(_graph())
    assert path.origin == 0 and path.destination == 2
    assert path.edges[0] == (0, 1, 0)
    assert path.physical_edge_ids == ("pe:direct-a", "pe:mid")
    assert path.length_m == 20.0


def test_parallel_edge_key_is_the_one_with_lower_perturbed_cost():
    graph = _graph()
    adjacency = build_adjacency(graph)
    factors = {(u, v, key): 1.0 for u, v, key, _length, _edge in adjacency.nodes}
    factors[(0, 1, 0)] = 3.0
    factors[(0, 1, 1)] = 1.0
    factors[(0, 3, 0)] = 5.0
    factors[(3, 2, 0)] = 5.0
    proposed = proposed_shortest(adjacency, 0, 2, factors)
    assert proposed is not None
    assert proposed.edges[0] == (0, 1, 1)
    assert proposed.physical_edge_ids[0] == "pe:direct-b"
    assert proposed.length_m == 22.0


def test_detour_uses_original_length_and_rejects_above_the_cap():
    graph = _graph()
    adjacency = build_adjacency(graph)
    original = _original(graph)
    factors = {(u, v, key): 5.0 for u, v, key, _length, _edge in adjacency.nodes}
    factors[(0, 3, 0)] = 0.1
    factors[(3, 2, 0)] = 0.1
    proposed = proposed_shortest(adjacency, 0, 2, factors)
    assert proposed is not None
    assert proposed.length_m == 22.0
    accepted = classify_proposal(original, proposed, 0.15)
    rejected = classify_proposal(original, proposed, 0.05)
    assert accepted.status == "changed"
    assert accepted.detour == pytest.approx(0.10)
    assert accepted.path.physical_edge_ids == ("pe:side-a", "pe:side-b")
    assert rejected.status == "rejected_detour"
    assert rejected.path.physical_edge_ids == original.physical_edge_ids
    assert rejected.detour is None
    assert rejected.proposed_detour == pytest.approx(0.10)


def test_unchanged_when_the_physical_path_does_not_change():
    graph = _graph()
    adjacency = build_adjacency(graph)
    original = _original(graph)
    factors = {(u, v, key): 1.0 for u, v, key, _length, _edge in adjacency.nodes}
    decision = alternative_route(adjacency, original, factors, 0.30)
    assert decision.status == "unchanged"
    assert decision.path.edges == original.edges


def test_path_follows_directed_edges_and_stays_connected():
    graph = _graph()
    graph.add_edge(2, 0, key=0, length=1.0, physical_edge_id="pe:reverse")
    adjacency = build_adjacency(graph)
    factors = edge_cost_factors(adjacency, seed=5, sigma=0.8)
    proposed = proposed_shortest(adjacency, 0, 2, factors)
    assert proposed is not None
    assert all(u_node != 2 or v_node != 0 for u_node, v_node, _key in proposed.edges)
    for left, right in zip(proposed.edges, proposed.edges[1:], strict=False):
        assert left[1] == right[0]


def test_missing_alternative_is_an_explicit_failure():
    original = _original(_graph())
    decision = classify_proposal(original, None, 0.15)
    assert decision.status == "failed"
    assert decision.path == original


def test_factors_are_positive_and_repeat_for_a_fixed_seed():
    adjacency = build_adjacency(_graph())
    first = edge_cost_factors(adjacency, seed=91000, sigma=0.35)
    second = edge_cost_factors(adjacency, seed=91000, sigma=0.35)
    assert first == second
    assert all(value > 0 for value in first.values())
    assert edge_cost_factors(adjacency, seed=91001, sigma=0.35) != first


def test_routing_does_not_change_graph_lengths_or_the_original_record():
    graph = _graph()
    before = {(u, v, key): data["length"] for u, v, key, data in graph.edges(keys=True, data=True)}
    original = _original(graph)
    original_edges = original.edges
    adjacency = build_adjacency(graph)
    factors = edge_cost_factors(adjacency, seed=3, sigma=0.35)
    alternative_route(adjacency, original, factors, 0.30)
    after = {(u, v, key): data["length"] for u, v, key, data in graph.edges(keys=True, data=True)}
    assert after == before
    assert original.edges == original_edges


def test_coverage_transitions_match_the_coverage_difference():
    original = {"a": {"e1"}, "b": {"e2"}, "c": {"e3"}}
    alternative = {"a": {"e9"}, "b": {"e2"}, "c": {"e1"}}
    result = coverage_transition(original, alternative, ["e1"])
    assert result["n_lost"] == 1
    assert result["n_gained"] == 1
    assert result["n_net"] == 0
    assert result["difference"] == pytest.approx(0.0)
    assert result["shortest_coverage"] == pytest.approx(1 / 3)
    assert result["alternative_coverage"] == pytest.approx(1 / 3)


def test_detour_summary_matches_the_raw_values():
    summary = detour_summary([0.01, 0.02, 0.03, 0.04])
    assert summary["max"] == 0.04
    assert summary["mean"] == pytest.approx(0.025)
    assert summary["median"] == pytest.approx(0.025)


def test_accepted_detour_never_exceeds_the_requested_cap():
    graph = _graph()
    adjacency = build_adjacency(graph)
    original = _original(graph)
    generator = random.Random(11)
    for _draw in range(30):
        factors = {
            (u, v, key): generator.uniform(0.2, 3.0) for u, v, key, _length, _edge in adjacency.nodes
        }
        decision = alternative_route(adjacency, original, factors, 0.15)
        if decision.status == "changed":
            assert decision.detour is not None
            assert 0 <= decision.detour <= 0.15 + 1e-9
            assert decision.path.origin == original.origin
            assert decision.path.destination == original.destination
        else:
            assert decision.path.physical_edge_ids == original.physical_edge_ids
