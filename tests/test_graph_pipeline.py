import pytest

nx = pytest.importorskip("networkx")

from cyclesense.coverage import greedy_max_coverage
from cyclesense.network import (
    add_contraflow_edges,
    assign_physical_edge_ids,
    audit_topology,
    build_candidates,
    drop_unroutable_edges,
)
from cyclesense.routes import generate_modeled_routes, shared_route_keys


def _add_both(graph: nx.MultiDiGraph, u_node: int, v_node: int, osmid: int, **attrs: object) -> None:
    payload = {"osmid": osmid, "length": 100.0, "highway": "residential", "oneway": False}
    payload.update(attrs)
    graph.add_edge(u_node, v_node, **payload)
    graph.add_edge(v_node, u_node, **dict(payload))


def _grid(size: int = 5) -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    for i in range(size):
        for j in range(size):
            graph.add_node(i * size + j, x=float(i * 100), y=float(j * 100))
    osmid = 1
    for i in range(size):
        for j in range(size):
            node = i * size + j
            if i + 1 < size:
                _add_both(graph, node, node + size, osmid)
                osmid += 1
            if j + 1 < size:
                _add_both(graph, node, node + 1, osmid)
                osmid += 1
    return graph


def test_physical_ids_merge_grid_directions_and_feed_the_existing_baseline() -> None:
    graph = _grid()
    assert add_contraflow_edges(graph) == 0
    physical_count = assign_physical_edge_ids(graph)
    undirected = graph.number_of_edges() // 2
    assert physical_count == undirected
    for u_node, v_node, data in graph.edges(data=True):
        reverse = min(graph[v_node][u_node].values(), key=lambda item: item["length"])
        assert data["physical_edge_id"] == reverse["physical_edge_id"]

    candidates, stats = build_candidates(graph, min_length_m=15)
    assert stats["n_candidates"] == physical_count
    candidate_ids = {row["physical_edge_id"] for row in candidates}
    coordinates = {int(node): (float(data["x"]), float(data["y"])) for node, data in graph.nodes(data=True)}
    common = {
        "n_calibration": 5,
        "n_evaluation": 4,
        "calibration_seed": 42,
        "evaluation_seed": 10049,
        "min_distance_m": 80,
        "max_distance_m": 700,
        "min_eligible_edges": 2,
        "max_attempts_factor": 40,
    }
    uniform, _uniform_stats = generate_modeled_routes(
        graph, coordinates, candidate_ids, scenario="uniform", anchor_xy=None, **common
    )
    commuter, _commuter_stats = generate_modeled_routes(
        graph, coordinates, candidate_ids, scenario="commuter_proxy", anchor_xy=(0.0, 0.0), **common
    )
    again, _again_stats = generate_modeled_routes(
        graph, coordinates, candidate_ids, scenario="uniform", anchor_xy=None, **common
    )
    routes = uniform + commuter
    assert [route.physical_edge_ids for route in uniform] == [route.physical_edge_ids for route in again]
    assert len(uniform) == 9
    assert len(commuter) == 9
    overlap = shared_route_keys(routes)
    assert overlap == {"shared_od_pairs": 0, "shared_paths": 0}
    for route in routes:
        assert route.scenario_weight == 1
        assert route.eligible_edge_ids == route.physical_edge_ids
        assert set(route.physical_edge_ids) <= candidate_ids
        assert len(route.node_ids) == len(route.physical_edge_ids) + 1
    result = greedy_max_coverage(
        {route.route_id: set(route.physical_edge_ids) for route in routes},
        budget=2,
        eligible_edges=candidate_ids,
    )
    assert set(result.selected_edges) <= candidate_ids
    assert result.coverage_fraction > 0


def test_contraflow_tag_adds_the_missing_reverse_direction() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(0, x=0.0, y=0.0)
    graph.add_node(1, x=100.0, y=0.0)
    graph.add_edge(
        0,
        1,
        osmid=5,
        length=100.0,
        highway="residential",
        oneway=True,
        **{"oneway:bicycle": "no"},
    )
    assert not graph.has_edge(1, 0)
    assert add_contraflow_edges(graph) == 1
    assert graph.has_edge(1, 0)
    assign_physical_edge_ids(graph)
    forward = min(graph[0][1].values(), key=lambda item: item["length"])
    backward = min(graph[1][0].values(), key=lambda item: item["length"])
    assert forward["physical_edge_id"] == backward["physical_edge_id"]
    assert add_contraflow_edges(graph) == 0


def test_ineligible_driveway_stays_on_the_path_but_not_in_the_candidate_set() -> None:
    graph = nx.MultiDiGraph()
    for index in range(4):
        graph.add_node(index, x=float(index * 100), y=0.0)
    _add_both(graph, 0, 1, 1)
    _add_both(graph, 1, 2, 2)
    _add_both(graph, 2, 3, 3, highway="service", service="driveway")
    assign_physical_edge_ids(graph)
    candidates, _stats = build_candidates(graph, min_length_m=15)
    candidate_ids = {row["physical_edge_id"] for row in candidates}
    assert len(candidate_ids) == 2
    coordinates = {index: (float(index * 100), 0.0) for index in range(4)}
    routes, _stats = generate_modeled_routes(
        graph,
        coordinates,
        candidate_ids,
        scenario="uniform",
        n_calibration=1,
        n_evaluation=1,
        calibration_seed=3,
        evaluation_seed=9,
        min_distance_m=250,
        max_distance_m=400,
        min_eligible_edges=2,
        max_attempts_factor=50,
    )
    long_routes = [route for route in routes if route.origin_node in {0, 3} and route.destination_node in {0, 3}]
    assert long_routes
    for route in long_routes:
        assert len(route.physical_edge_ids) == 3
        assert len(route.eligible_edge_ids) == 2
        assert set(route.eligible_edge_ids) <= candidate_ids
        assert set(route.physical_edge_ids) - candidate_ids


def test_audit_flags_a_disconnected_node_and_drop_removes_bad_lengths() -> None:
    graph = _grid(size=3)
    graph.add_node(999, x=0.0, y=0.0)
    graph.add_edge(0, 1, osmid=99, length=0.0, highway="residential")
    audit = audit_topology(graph)
    assert audit["n_strong_components"] >= 2
    assert audit["length_m"]["missing_or_nonpositive"] >= 1
    removed = drop_unroutable_edges(graph)
    assert removed >= 1
    assert all(float(data["length"]) > 0 for _u, _v, data in graph.edges(data=True))


def test_example_maps_write_pngs(tmp_path) -> None:
    pytest.importorskip("matplotlib")
    from pathlib import Path

    from cyclesense.plotting import plot_study_maps

    graph = _grid(size=4)
    assign_physical_edge_ids(graph)
    candidates, _stats = build_candidates(graph, min_length_m=15)
    coordinates = {int(node): (float(data["x"]), float(data["y"])) for node, data in graph.nodes(data=True)}
    routes, _stats = generate_modeled_routes(
        graph,
        coordinates,
        {row["physical_edge_id"] for row in candidates},
        scenario="uniform",
        n_calibration=3,
        n_evaluation=2,
        calibration_seed=1,
        evaluation_seed=2,
        min_distance_m=50,
        max_distance_m=800,
        min_eligible_edges=2,
    )
    paths = plot_study_maps(
        graph,
        candidates,
        routes,
        tmp_path,
        title_suffix="synthetic grid",
        coordinate_note="metres in a synthetic plane",
    )
    for path in paths.values():
        assert Path(path).stat().st_size > 1000
        assert Path(path).parent == tmp_path
