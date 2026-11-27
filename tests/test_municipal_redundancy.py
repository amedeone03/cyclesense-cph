"""Unique coverage, exact Shapley attribution, and fixed municipal additions."""

from __future__ import annotations

import pytest

from cyclesense.coverage import evaluate_coverage
from cyclesense.municipal_redundancy import (
    attribute_sites,
    brute_force_shapley,
    complement_counts,
    cumulative_coverage,
    incremental_shapley,
    pairwise_overlap,
    validate_additions,
)


def test_unique_coverage_equals_leave_one_out_and_counts_a_route_once() -> None:
    routes = {"r1": {"a"}, "r2": {"a", "b"}, "r3": {"c"}, "r4": {"d"}}
    result = attribute_sites(routes, ["a", "b", "c"])
    assert result["coverage"] == pytest.approx(0.75)
    assert result["coverage"] == pytest.approx(evaluate_coverage(routes, ["a", "b", "c"]).coverage_fraction)
    assert result["n_uncovered"] == 1
    assert result["n_exactly_one"] == 2
    assert result["n_two_or_more"] == 1
    by_site = {row["physical_edge_id"]: row for row in result["sites"]}
    assert by_site["a"]["unique_routes"] == 1
    assert by_site["a"]["leave_one_out"] == pytest.approx(0.25)
    assert by_site["a"]["unique_fraction"] == pytest.approx(by_site["a"]["leave_one_out"])
    assert by_site["b"]["unique_routes"] == 0
    assert by_site["b"]["leave_one_out"] == 0
    assert by_site["b"]["shared_routes"] == 1
    assert by_site["b"]["shapley"] > by_site["b"]["leave_one_out"]


def test_zero_incidence_site_and_empty_routes() -> None:
    routes = {"r1": {"a"}}
    result = attribute_sites(routes, ["a", "missing"])
    missing = result["sites"][1]
    assert missing["physical_edge_id"] == "missing"
    assert missing["traversal_routes"] == 0
    assert missing["shapley"] == 0
    assert missing["leave_one_out"] == 0
    with pytest.raises(ValueError, match="at least one route"):
        attribute_sites({}, ["a"])


def test_shapley_sums_to_coverage_and_matches_brute_force() -> None:
    routes = {"r1": {"a", "b"}, "r2": {"b"}, "r3": {"a", "c"}, "r4": {"c", "b"}}
    weights = {"r1": 1.0, "r2": 2.0, "r3": 1.0, "r4": 3.0}
    result = attribute_sites(routes, ["a", "b", "c"], weights)
    brute = brute_force_shapley(routes, ["a", "b", "c"], weights)
    assert result["shapley_total"] == pytest.approx(result["coverage"])
    for row in result["sites"]:
        assert row["shapley"] >= 0
        assert row["shapley"] == pytest.approx(brute[row["physical_edge_id"]])
    symmetric = attribute_sites({"r1": {"a", "b"}}, ["a", "b"])
    values = [row["shapley"] for row in symmetric["sites"]]
    assert values[0] == pytest.approx(values[1])
    assert values[0] == pytest.approx(0.5)


def test_pairwise_overlap_is_symmetric_and_handles_an_empty_site() -> None:
    routes = {"r1": {"a", "b"}, "r2": {"a"}, "r3": {"c"}}
    rows = pairwise_overlap(routes, ["a", "b", "c", "d"])
    pair = {(row["site_a"], row["site_b"]): row for row in rows}
    assert pair[("a", "b")]["n_both"] == 1
    assert pair[("a", "b")]["jaccard"] == pytest.approx(1 / 2)
    assert pair[("a", "c")]["n_both"] == 0
    assert pair[("a", "c")]["jaccard"] == 0
    assert pair[("c", "d")]["conditional_b"] is None
    assert pair[("a", "b")]["conditional_a"] == pytest.approx(pair[("a", "b")]["n_both"] / 2)
    flipped = pairwise_overlap(routes, ["b", "a"])
    assert flipped[0]["n_both"] == pair[("a", "b")]["n_both"]
    assert flipped[0]["conditional_a"] == pytest.approx(pair[("a", "b")]["conditional_b"])


def test_additions_stay_distinct_and_cumulative_coverage_is_monotone() -> None:
    existing = ["m1", "m2"]
    ordered = ["a", "b"]
    validate_additions(existing, ordered)
    with pytest.raises(ValueError, match="repeats"):
        validate_additions(existing, ["a", "m1"])
    routes = {"r1": {"m1"}, "r2": {"a"}, "r3": {"b"}, "r4": {"a", "b"}}
    rows = cumulative_coverage(routes, existing, ordered)
    coverages = [row["coverage"] for row in rows]
    assert coverages == sorted(coverages)
    assert rows[1]["gain"] == pytest.approx(coverages[1] - coverages[0])
    assert rows[2]["gain"] == pytest.approx(coverages[2] - coverages[1])
    assert rows[2]["gain"] < rows[1]["gain"]
    shares = incremental_shapley(routes, existing, ordered)
    assert sum(shares.values()) == pytest.approx(coverages[-1] - coverages[0])
    counts = complement_counts(routes, existing, ordered)
    assert counts["n_newly_covered_routes"] == 3
    assert counts["n_additions_on_already_covered_routes"] == 0


def test_calibration_and_held_out_attributions_are_separate() -> None:
    calibration = {"c1": {"a"}, "c2": {"b"}}
    heldout = {"e1": {"b"}, "e2": {"b"}, "e3": set()}
    calibration_result = attribute_sites(calibration, ["a", "b"])
    heldout_result = attribute_sites(heldout, ["a", "b"])
    calibration_a = calibration_result["sites"][0]["leave_one_out"]
    heldout_a = heldout_result["sites"][0]["leave_one_out"]
    assert calibration_a != pytest.approx(heldout_a)
    assert {row["physical_edge_id"] for row in calibration_result["sites"]} == {"a", "b"}


def test_duplicate_ids_and_missing_weights_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        attribute_sites({"r1": {"a"}}, ["a", "a"])
    with pytest.raises(ValueError, match="weight"):
        attribute_sites({"r1": {"a"}}, ["a"], {})


def test_saved_municipal_baseline_when_artifacts_exist() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    routes_path = root / "data/processed/m1/routes.csv"
    coverage_path = root / "outputs/standout/coverage.csv"
    summary_path = root / "outputs/standout/summary.json"
    candidates_path = root / "data/processed/m1/candidates.csv"
    if not all(path.is_file() for path in (routes_path, coverage_path, summary_path, candidates_path)):
        pytest.skip("saved municipal artifacts are not in this checkout")
    import csv
    import json

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    sites = [
        row["physical_edge_id"]
        for row in summary["samples"]["recurring_name_agree"]["alignment_rows"]
        if row.get("physical_edge_id")
    ]
    assert len(sites) == len(set(sites)) == 26
    with candidates_path.open(newline="", encoding="utf-8") as handle:
        eligible = {row["physical_edge_id"] for row in csv.DictReader(handle)}
    assert set(sites) <= eligible
    stored = {}
    with routes_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            edges = {part for part in row["physical_edge_ids"].split("|") if part}
            stored.setdefault((row["scenario"], row["split"]), {})[row["route_id"]] = edges
    saved = {}
    with coverage_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["budget_new"] == "5":
                saved[row["scenario"]] = row
    for scenario, split, field in (
        ("uniform", "evaluation", "held_out_existing_coverage"),
        ("uniform", "calibration", "calibration_existing_coverage"),
        ("commuter_proxy", "evaluation", "held_out_existing_coverage"),
        ("commuter_proxy", "calibration", "calibration_existing_coverage"),
    ):
        result = attribute_sites(stored[(scenario, split)], sites)
        assert result["coverage"] == pytest.approx(float(saved[scenario][field]))
        assert sum(row["shapley"] for row in result["sites"]) == pytest.approx(result["coverage"])
