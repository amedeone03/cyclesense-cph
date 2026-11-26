"""Route-choice-aware placement: weights, separation, and table checks."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from cyclesense.coverage import evaluate_coverage
from cyclesense.external_validation import additional_counters
from cyclesense.placement import fill_to_k
from cyclesense.robust_placement import (
    assert_disjoint_seeds,
    assign_weights,
    calibration_marginal_gains,
    paired_comparison,
    require_calibration,
    scenario_tradeoff,
    select_weighted,
    summarize_alternative,
)
from cyclesense.route_choice import coverage_transition

ROOT = Path(__file__).resolve().parents[1]


def _record(scenario: str, od_id: str, role: str, seed: int | None = None) -> dict[str, object]:
    suffix = "shortest" if role == "shortest" else f"alternative:{seed}"
    return {
        "route_key": f"{scenario}:{od_id}:{suffix}",
        "scenario": scenario,
        "od_id": od_id,
        "role": role,
    }


def test_training_rejects_held_out_routes() -> None:
    with pytest.raises(ValueError, match="calibration"):
        require_calibration([{"split": "calibration"}, {"split": "evaluation"}])
    require_calibration([{"split": "calibration"}])


def test_configured_seed_ranges_are_disjoint() -> None:
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))["robust_placement"]
    training = list(range(int(config["training_seed_start"]), int(config["training_seed_start"]) + int(config["training_n_seeds"])))
    fresh = list(range(int(config["evaluation_seed_start"]), int(config["evaluation_seed_start"]) + int(config["evaluation_n_seeds"])))
    reference = list(range(int(config["reference_seed_start"]), int(config["reference_seed_start"]) + int(config["reference_n_seeds"])))
    assert training == list(range(82000, 82010))
    assert fresh == list(range(92000, 92020))
    assert reference == list(range(91000, 91020))
    assert_disjoint_seeds(training, fresh, reference)
    with pytest.raises(ValueError, match="overlap"):
        assert_disjoint_seeds(training, [82000])


def test_scenario_weights_stay_equal_when_od_counts_differ() -> None:
    records = [
        _record("uniform", "a", "shortest"),
        _record("commuter_proxy", "b", "shortest"),
        _record("commuter_proxy", "c", "shortest"),
    ]
    weights = assign_weights(records, scenarios=("uniform", "commuter_proxy"), include_alternatives=False)
    uniform = sum(weight for key, weight in weights.items() if key.startswith("uniform:"))
    commuter = sum(weight for key, weight in weights.items() if key.startswith("commuter_proxy:"))
    assert uniform == pytest.approx(0.5)
    assert commuter == pytest.approx(0.5)
    assert weights["uniform:a:shortest"] == pytest.approx(0.5)
    assert weights["commuter_proxy:b:shortest"] == pytest.approx(0.25)


def test_extra_alternatives_do_not_increase_an_od_share() -> None:
    records = [
        _record("uniform", "a", "shortest"),
        _record("uniform", "b", "shortest"),
        _record("uniform", "a", "alternative", 1),
        _record("uniform", "a", "alternative", 2),
        _record("uniform", "b", "alternative", 1),
    ]
    weights = assign_weights(records, scenarios=("uniform",), include_alternatives=True)
    alternative_a = weights["uniform:a:alternative:1"] + weights["uniform:a:alternative:2"]
    alternative_b = weights["uniform:b:alternative:1"]
    assert alternative_a == pytest.approx(alternative_b)
    assert alternative_a == pytest.approx(0.25)
    assert sum(weights.values()) == pytest.approx(1.0)


def test_weighted_greedy_uses_physical_edges_and_is_deterministic() -> None:
    routes = {
        "uniform:a:shortest": {"pe:bridge"},
        "uniform:b:shortest": {"pe:bridge", "pe:side"},
    }
    weights = {"uniform:a:shortest": 0.2, "uniform:b:shortest": 0.8}
    first = select_weighted(["pe:bridge", "pe:side", "pe:unused"], routes, weights, 1)
    second = select_weighted(["pe:unused", "pe:side", "pe:bridge"], routes, weights, 1)
    assert first == second == ("pe:bridge",)
    scored = evaluate_coverage(routes, first, weights)
    assert scored.coverage_fraction == pytest.approx(1.0)


def test_marginal_gains_match_the_training_objective() -> None:
    routes = {
        "uniform:a:shortest": {"pe:1"},
        "commuter_proxy:b:shortest": {"pe:2"},
    }
    weights = {"uniform:a:shortest": 0.25, "commuter_proxy:b:shortest": 0.75}
    gains = calibration_marginal_gains(routes, weights, ["pe:2", "pe:1"])
    assert gains[0]["calibration_marginal_gain"] == pytest.approx(0.75)
    assert gains[0]["commuter_new_weight"] == pytest.approx(0.75)
    assert gains[1]["uniform_new_weight"] == pytest.approx(0.25)
    assert gains[1]["cumulative_calibration_coverage"] == pytest.approx(1.0)


def test_municipal_additions_keep_the_existing_sites() -> None:
    routes = {
        "uniform:a:shortest": {"m1"},
        "uniform:b:shortest": {"new"},
    }
    weights = {"uniform:a:shortest": 0.4, "uniform:b:shortest": 0.6}
    added = additional_counters(routes, ["m1"], ["m1", "new", "later"], 1, weights)
    selected = fill_to_k(added, ["later", "new"], 1)
    assert selected == ("new",)
    assert set(selected).isdisjoint({"m1"})
    assert len(selected) == len(set(selected)) == 1


def test_alternative_summary_and_paired_difference_reconcile() -> None:
    summary = summarize_alternative([0.50, 0.40, 0.60, 0.50], 0.70, [0.2, 0.2, 0.2, 0.2])
    assert summary["coverage_mean"] == pytest.approx(0.5)
    assert summary["coverage_min"] == pytest.approx(0.4)
    assert summary["difference_mean"] == pytest.approx(-0.2)
    assert summary["loss_percentage_points"] == pytest.approx(20.0)
    original = {"r1": {"pe:a"}, "r2": {"pe:b"}}
    alternative = {"r1": {"pe:c"}, "r2": {"pe:b"}}
    transition = coverage_transition(original, alternative, ["pe:a"])
    assert transition["difference"] == pytest.approx(
        transition["alternative_coverage"] - transition["shortest_coverage"]
    )
    assert transition["n_net"] == transition["n_gained"] - transition["n_lost"]
    compared = paired_comparison(
        {1: 0.6, 2: 0.4},
        {1: 0.5, 2: 0.5},
        shortest_left=0.7,
        shortest_right=0.8,
    )
    assert compared["mean_left_minus_right"] == pytest.approx(0.0)
    assert compared["fraction_left_beats_right"] == pytest.approx(0.5)
    trade = scenario_tradeoff(0.6, 0.4)
    assert trade["mean_coverage"] == pytest.approx(0.5)
    assert trade["min_coverage"] == pytest.approx(0.4)


def test_saved_shortest_coverage_matches_m4_when_artifacts_exist() -> None:
    routes_path = ROOT / "data/processed/m1/routes.csv"
    placements_path = ROOT / "outputs/m4/placements.csv"
    if not routes_path.is_file() or not placements_path.is_file():
        pytest.skip("saved M1 routes or M4 placements are not in this checkout")
    selected = {}
    with placements_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row["scenario"] == "uniform"
                and row["source"] == "louvain"
                and float(row["threshold"]) == 0.5
                and float(row["lambda"]) == 0.0
                and int(row["k"]) == 10
            ):
                selected = tuple(part for part in row["selected_edges"].split("|") if part)
                saved = float(row["heldout_coverage"])
    routes = {}
    with routes_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["scenario"] == "uniform" and row["split"] == "evaluation":
                routes[row["route_id"]] = {part for part in row["eligible_edge_ids"].split("|") if part}
    assert len(selected) == 10
    assert evaluate_coverage(routes, selected).coverage_fraction == pytest.approx(saved, abs=5e-4)


def test_protected_outputs_are_named_by_the_runner() -> None:
    script = (ROOT / "scripts/run_robust_placement.py").read_text(encoding="utf-8")
    for relative in (
        "data/processed/m1/routes.csv",
        "outputs/m4/placements.csv",
        "outputs/m5/summary.json",
        "outputs/standout/summary.json",
        "outputs/route_choice/summary.json",
    ):
        assert relative in script
