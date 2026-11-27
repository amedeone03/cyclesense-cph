"""Planner catalog tests.

Synthetic checks always run. Checks against the Copenhagen study run only
when those saved outputs are present.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from cyclesense.placement_stability import CANONICAL_OUTPUTS
from cyclesense.planner import build_catalog, render_planner, set_comparison, write_planner

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "outputs" / "m2" / "results.csv"
HAS_STUDY = RESULTS.is_file() and (ROOT / "outputs" / "placement_stability" / "segment_frequencies.csv").is_file()


def test_set_comparison_counts_shared_edges() -> None:
    result = set_comparison(["b", "a", "c"], ["c", "d"])
    assert result["shared"] == ["c"]
    assert result["only_left"] == ["a", "b"]
    assert result["only_right"] == ["d"]
    assert result["jaccard"] == 0.25


def test_page_states_when_a_metric_is_missing_and_stays_offline() -> None:
    catalog = {
        "place_label": "Example",
        "network": [],
        "basemap": {"water": [], "green": [], "streets": []},
        "placements": [],
        "municipal": {"existing_ids": [], "plans": []},
        "stability": {},
        "notes": ["Routes are simulated.", "<script>"],
    }
    page = render_planner(catalog)
    assert "Not evaluated for this combination" in page
    assert "tile.openstreetmap" not in page
    assert "cdn.jsdelivr" not in page
    assert "leaflet" not in page.lower()
    assert "<script>" not in page.split('type="application/json">', 1)[1].split("</script>", 1)[0]


@pytest.mark.skipif(not HAS_STUDY, reason="saved study outputs are not in this checkout")
def test_catalog_matches_saved_results() -> None:
    catalog = build_catalog(ROOT)
    placements = {item["id"]: item for item in catalog["placements"]}
    network = {edge["id"] for edge in catalog["network"]}
    greedy = placements["greedy:uniform:10"]
    assert [edge["id"] for edge in greedy["edges"]] == _m2_edges("uniform", "greedy", "10")
    assert set(greedy["edges"][0]) >= {"id", "name", "rank", "marginal"}
    assert all(edge["id"] in network for item in placements.values() for edge in item["edges"])
    assert greedy["evaluations"]["uniform|shortest"]["value"] == _m2_float("uniform", "greedy", "10", "heldout_coverage")
    assert greedy["calibration"]["value"] == _m2_float("uniform", "greedy", "10", "calibration_coverage")
    assert greedy["training_label"] == "Uniform"
    assert "commuter_proxy|shortest" in greedy["evaluations"]
    assert "uniform|detour_15" in greedy["evaluations"]
    assert "commuter_proxy|shortest" not in placements["greedy:uniform:5"]["evaluations"]
    assert "route_frequency:uniform:10" in placements
    assert "uniform|detour_15" not in placements["route_frequency:uniform:10"]["evaluations"]
    assert "geographical_kmeans:uniform:5" in placements
    assert "pooled:both:5" not in placements
    assert "route_choice:both:30" not in placements
    assert "milp:uniform:5" in placements
    milp = placements["milp:uniform:10"]
    assert milp["certified_optimal"] is True
    assert milp["evaluations"]["uniform|shortest"]["value"] == _milp_float("uniform", "10", "heldout_exact")
    assert "uniform|detour_15" not in milp["evaluations"]
    assert milp["objective"] == greedy["objective"]
    balanced = placements["balanced:uniform:10"]
    assert balanced["training_label"] == "Uniform"
    assert balanced["objective"] != greedy["objective"]
    assert balanced["calibration"]["value"] == _m4_float("uniform", "10", "calibration_coverage")
    large = placements["greedy:uniform:20"]
    assert len(large["edges"]) == 20
    assert [edge["id"] for edge in large["edges"]] == _m2_edges("uniform", "greedy", "20")
    overlap = set_comparison(
        [edge["id"] for edge in greedy["edges"]],
        [edge["id"] for edge in milp["edges"]],
    )
    assert len(overlap["shared"]) == int(_milp_float("uniform", "10", "n_shared"))
    frequencies = catalog["stability"]["greedy|uniform|10"]["frequencies"]
    saved = _stability("greedy", "uniform", "10")
    assert frequencies == saved
    assert max(frequencies.values()) == 1.0
    assert "geographical_kmeans|uniform|10" not in catalog["stability"]
    municipal = {plan["id"]: plan for plan in catalog["municipal"]["plans"]}
    existing = municipal["municipal:uniform:26"]
    assert len(existing["existing"]) == 26
    assert all(edge["aadt"] is not None for edge in existing["existing"])
    assert all("aadt" not in edge for edge in existing["added"])
    added = municipal["municipal:uniform:original5"]["added"]
    assert len(added) == 5
    assert all("aadt" not in edge for edge in added)
    assert "uniform|detour_15" not in municipal["municipal:uniform:original10"]["evaluations"]
    assert municipal["municipal:uniform:milp5"]["certified_optimal"] is True
    assert municipal["municipal:uniform:robust5"]["calibration"] is None
    pooled = placements["pooled:both:10"]
    assert pooled["edges"][0]["marginal"] == _marginal("pooled_shortest", "10", pooled["edges"][0]["id"])
    assert pooled["stability_key"] == "pooled_shortest|pooled|10"
    assert placements["route_choice:both:10"]["stability_key"] == "route_choice|pooled|10"
    knippel = next(edge for edge in greedy["edges"] if frequencies.get(edge["id"]) == 1.0)
    assert knippel["name"]
    assert knippel["rank"] == 1


@pytest.mark.skipif(not HAS_STUDY, reason="saved study outputs are not in this checkout")
def test_writing_the_planner_does_not_change_study_files(tmp_path: Path) -> None:
    before = {relative: _digest(ROOT / relative) for relative in CANONICAL_OUTPUTS}
    destination = write_planner(ROOT, tmp_path / "cyclesense_planner.html")
    after = {relative: _digest(ROOT / relative) for relative in CANONICAL_OUTPUTS}
    assert after == before
    page = destination.read_text(encoding="utf-8")
    assert "Not evaluated for this combination" in page
    payload = json.loads(page.split('type="application/json">', 1)[1].split("</script>", 1)[0])
    assert payload["placements"][0]["edges"][0]["id"].startswith("pe:")


def _m2_edges(scenario: str, method: str, budget: str) -> list[str]:
    for row in csv.DictReader(RESULTS.open(encoding="utf-8")):
        seed = row["seed"] == "42" if method == "geographical_kmeans" else row["seed"] == ""
        if row["scenario"] == scenario and row["method"] == method and row["k"] == budget and seed:
            return [edge for edge in row["selected_edges"].split("|") if edge]
    raise AssertionError(f"missing M2 row {method} {scenario} {budget}")


def _m2_float(scenario: str, method: str, budget: str, column: str) -> float:
    for row in csv.DictReader(RESULTS.open(encoding="utf-8")):
        if row["scenario"] == scenario and row["method"] == method and row["k"] == budget and row["seed"] == "":
            return float(row[column])
    raise AssertionError(column)


def _m4_float(scenario: str, budget: str, column: str) -> float:
    path = ROOT / "outputs" / "m4" / "placements.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row["scenario"] == scenario and row["k"] == budget and row["lambda"] == "0.25" and row["threshold"] == "0.5":
            return float(row[column])
    raise AssertionError(column)


def _milp_float(scenario: str, budget: str, column: str) -> float:
    path = ROOT / "outputs" / "exact_optimization" / "greedy_comparison.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row["objective"] == "unweighted" and row["scenario"] == scenario and row["k"] == budget:
            return float(row[column])
    raise AssertionError(column)


def _stability(method: str, scenario: str, budget: str) -> dict[str, float]:
    path = ROOT / "outputs" / "placement_stability" / "segment_frequencies.csv"
    return {
        row["physical_edge_id"]: float(row["selection_frequency"])
        for row in csv.DictReader(path.open(encoding="utf-8"))
        if row["method"] == method and row["scenario"] == scenario and row["k"] == budget
    }


def _marginal(method: str, budget: str, edge_id: str) -> float:
    path = ROOT / "outputs" / "robust_placement" / "placements.csv"
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row["method"] == method and row["k"] == budget and row["physical_edge_id"] == edge_id:
            return float(row["calibration_marginal_gain"])
    raise AssertionError(edge_id)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
