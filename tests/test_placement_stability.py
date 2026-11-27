"""Selection frequencies, replicate seeds, and physical-edge drawing."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path

import networkx as nx
import pytest
import yaml

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.coverage import evaluate_coverage
from cyclesense.placement_stability import (
    CANONICAL_OUTPUTS,
    assert_calibration_only,
    empirical_percentile,
    frequency_counts,
    jaccard,
    overlap_summary,
    pairwise_overlaps,
    rank_summaries,
    replicate_seeds,
    require_saved_selection,
    selection_entropy,
    selection_frequencies,
)
from cyclesense.placement_stability_plots import physical_lines
from cyclesense.robust_placement import assign_weights
from cyclesense.routes import generate_modeled_routes

ROOT = Path(__file__).resolve().parents[1]


def test_configured_seeds_are_thirty_distinct_draws() -> None:
    study = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))["placement_stability"]
    seeds = replicate_seeds(int(study["replicate_seed_start"]), int(study["n_replicates"]))
    assert seeds == tuple(range(103000, 103030))
    assert len(seeds) == 30
    assert 42 not in seeds


def test_same_seed_reproduces_a_calibration_draw() -> None:
    graph, coordinates, candidates = _line_graph()
    kwargs = {
        "scenario": "uniform",
        "n_calibration": 4,
        "n_evaluation": 0,
        "calibration_seed": 103000,
        "evaluation_seed": 103000 + 1000003,
        "min_distance_m": 400,
        "max_distance_m": 2500,
        "min_eligible_edges": 1,
    }
    first, _stats = generate_modeled_routes(graph, coordinates, candidates, **kwargs)
    second, _stats = generate_modeled_routes(graph, coordinates, candidates, **kwargs)
    assert len(first) == 4
    assert [(route.origin_node, route.destination_node) for route in first] == [
        (route.origin_node, route.destination_node) for route in second
    ]
    assert_calibration_only([route.split for route in first])


def test_selection_frequency_and_bands() -> None:
    eligible = ["a", "b", "c", "d"]
    selections = [("a", "b"), ("a", "c"), ("a", "b"), ("d", "c")]
    frequencies = selection_frequencies(selections, eligible)
    assert frequencies["a"] == pytest.approx(0.75)
    assert frequencies["d"] == pytest.approx(0.25)
    assert all(0 <= value <= 1 for value in frequencies.values())
    bands = frequency_counts(frequencies, n_candidates=6)
    assert bands["n_ever_selected"] == 4
    assert bands["n_never_selected"] == 2
    assert bands["n_at_least_50"] == 3
    assert bands["n_at_least_80"] == 0
    with pytest.raises(ValueError, match="ineligible"):
        selection_frequencies([("a", "z")], eligible)


def test_pairwise_jaccard_and_percentile() -> None:
    rows = pairwise_overlaps([("a", "b"), ("a", "c"), ("a", "b")])
    assert rows[0]["shared"] == 1
    assert rows[0]["jaccard"] == pytest.approx(1 / 3)
    assert jaccard(["a", "b"], ["a", "b"]) == 1
    summary = overlap_summary(rows)
    assert summary["min_shared"] == 1
    assert summary["max_shared"] == 2
    assert empirical_percentile([0, 10], 0.05) == pytest.approx(0.5)


def test_rank_entropy_and_exact_budget() -> None:
    ranks = rank_summaries([("a", "b"), ("b", "a")])
    assert ranks["a"]["mean_rank"] == pytest.approx(1.5)
    assert ranks["a"]["times_first"] == 1
    assert selection_entropy({"only": 1.0}, budget=1) == 0
    assert selection_entropy({"a": 0.5, "b": 0.5}, budget=1) == pytest.approx(1)
    require_saved_selection(("a", "b"), ["a", "b", "c"], 2)
    saved = ("a", "b")
    require_saved_selection(saved, ["a", "b", "c"], 2)
    assert saved == ("a", "b")


def test_held_out_split_is_rejected_and_scenarios_stay_separate() -> None:
    with pytest.raises(ValueError, match="non-calibration"):
        assert_calibration_only(["calibration", "evaluation"])
    uniform = selection_frequencies([("u",)], ["u", "c"])
    commuter = selection_frequencies([("c",)], ["u", "c"])
    assert set(uniform) == {"u"}
    assert set(commuter) == {"c"}


def test_pooled_scenarios_receive_equal_weight() -> None:
    records = []
    for scenario, route_id in (("uniform", "uniform:r"), ("commuter_proxy", "commuter_proxy:r")):
        records.append({"scenario": scenario, "od_id": route_id, "role": "shortest", "route_key": route_id})
    weights = assign_weights(records, scenarios=("uniform", "commuter_proxy"), include_alternatives=False)
    assert weights["uniform:r"] == pytest.approx(0.5)
    assert weights["commuter_proxy:r"] == pytest.approx(0.5)
    covered = evaluate_coverage({"uniform:r": {"a"}, "commuter_proxy:r": set()}, ["a"], weights)
    assert covered.covered_weight == pytest.approx(0.5)


def test_directed_edges_share_one_physical_geometry() -> None:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=12.5, y=55.6)
    graph.add_node(2, x=12.51, y=55.61)
    graph.add_edge(1, 2, key=0, physical_edge_id="pe:1", length=10)
    graph.add_edge(2, 1, key=0, physical_edge_id="pe:1", length=10)
    assert list(physical_lines(graph)) == ["pe:1"]


def test_missing_artifacts_and_canonical_files_are_protected(tmp_path: Path) -> None:
    assert validated_m1_artifacts(tmp_path) is None
    assert "data/processed/m1/routes.csv" in CANONICAL_OUTPUTS
    assert "outputs/m2/results.csv" in CANONICAL_OUTPUTS


def _line_graph():
    graph = nx.MultiDiGraph()
    for index, position in enumerate((0, 800, 1600, 2400)):
        graph.add_node(index, x=position, y=0)
    candidates = set()
    for left, right in pairwise(range(4)):
        edge_id = f"pe:{left}:{right}"
        candidates.add(edge_id)
        for origin, destination in ((left, right), (right, left)):
            graph.add_edge(origin, destination, key=0, length=800, physical_edge_id=edge_id)
    coordinates = {node: (float(data["x"]), float(data["y"])) for node, data in graph.nodes(data=True)}
    return graph, coordinates, candidates
