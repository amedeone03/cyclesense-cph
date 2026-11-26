"""Train shared counter sets on simulated route choices and score them on held-out OD pairs.

Selection uses calibration routes only. The fresh evaluation seeds are
92000–92019. Seeds 91000–91019 are scored afterwards for comparison with
the saved M5.6 draws. Neither block is used to choose or change a counter.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
import tracemalloc
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from cyclesense.artifacts import validated_m1_artifacts
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
from cyclesense.robust_placement_plots import (
    plot_coverage_by_method,
    plot_municipal,
    plot_placement_map,
    plot_robust_gap,
    plot_scenario_tradeoff,
)
from cyclesense.route_choice import (
    alternative_route,
    build_adjacency,
    classify_proposal,
    coverage_transition,
    edge_cost_factors,
    eligible_ids,
    proposed_shortest,
    shortest_path_from_nodes,
)

CANONICAL = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m2/summary.json",
    "outputs/m3/summary.json",
    "outputs/m3/communities.csv",
    "outputs/m4/summary.json",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
    "outputs/integrated/summary.json",
    "outputs/route_choice/summary.json",
    "outputs/scalability/summary.json",
    "outputs/standout/summary.json",
    "outputs/standout/coverage.csv",
    "data/external/trafiktal.csv",
    "configs/pilot.yaml",
    "configs/reproducibility.yaml",
)


def main() -> None:
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))["robust_placement"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("M1 artifacts are missing. Robust placement was not run.")
    before = _fingerprint()
    scenarios = tuple(config["scenarios"])
    sigma = float(config["sigma"])
    training_limit = float(config["training_detour_limit"])
    training_seeds = _seeds(config["training_seed_start"], config["training_n_seeds"])
    fresh_seeds = _seeds(config["evaluation_seed_start"], config["evaluation_n_seeds"])
    reference_seeds = _seeds(config["reference_seed_start"], config["reference_n_seeds"])
    limits = tuple(float(value) for value in config["evaluation_detour_limits"])
    budgets = tuple(int(value) for value in config["budgets"])
    addition_budget = int(config["municipal_additions"])
    assert_disjoint_seeds(training_seeds, fresh_seeds, reference_seeds)
    if set(training_seeds) & set(range(91000, 91020)):
        raise SystemExit("training seeds overlap the M5.6 evaluation seeds")

    output = ROOT / "outputs/robust_placement"
    output.mkdir(parents=True, exist_ok=True)
    (output / "experiment_config.json").write_text(
        json.dumps(
            {
                "sigma": sigma,
                "training_detour_limit": training_limit,
                "training_seeds": training_seeds,
                "fresh_evaluation_seeds": fresh_seeds,
                "reference_evaluation_seeds": reference_seeds,
                "evaluation_detour_limits": limits,
                "budgets": budgets,
                "scenarios": scenarios,
                "scenario_weights": "equal",
                "within_scenario": "half shortest paths, half alternative realizations",
                "within_pool": "equal weight per calibration OD; extra realizations split that OD",
                "held_out_used_for_selection": False,
                "fixed_before_held_out_scoring": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    candidates = _candidate_table(artifacts["candidates"])
    candidate_ids = set(candidates)
    names = {edge_id: row["name"] for edge_id, row in candidates.items()}
    calibration_rows = _read_routes(artifacts["routes"], "calibration")
    evaluation_rows = _read_routes(artifacts["routes"], "evaluation")
    require_calibration(calibration_rows)
    if {row["scenario"] for row in calibration_rows} != set(scenarios):
        raise SystemExit("calibration scenarios do not match the robust-placement config")
    print(
        f"Loading the routing graph and checking {len(calibration_rows)} calibration routes.",
        flush=True,
    )
    graph = ox.load_graphml(artifacts["routing_wgs84"])
    adjacency = build_adjacency(graph)
    calibration = [_checked_original(graph, row, candidate_ids) for row in calibration_rows]
    evaluation = [_checked_original(graph, row, candidate_ids) for row in evaluation_rows]
    by_scenario = {
        "calibration": _by_scenario(calibration),
        "evaluation": _by_scenario(evaluation),
    }

    started = time.perf_counter()
    training_records, diagnostics = _training_realizations(
        by_scenario["calibration"], adjacency, training_seeds, sigma, training_limit, candidate_ids
    )
    generation_seconds = time.perf_counter() - started
    print(f"Training realizations: {len(training_records)} in {generation_seconds:.1f}s", flush=True)

    table_started = time.perf_counter()
    robust_weights = assign_weights(training_records, scenarios=scenarios, include_alternatives=True)
    shortest_records = [record for record in training_records if record["role"] == "shortest"]
    pooled_weights = assign_weights(shortest_records, scenarios=scenarios, include_alternatives=False)
    robust_routes = {record["route_key"]: record["eligible"] for record in training_records}
    pooled_routes = {record["route_key"]: record["eligible"] for record in shortest_records}
    weight_table_seconds = time.perf_counter() - table_started

    saved = _saved_placements(
        ROOT / "outputs/m4/placements.csv",
        budgets,
        float(config["balanced_lambda"]),
        float(config["placement_threshold"]),
    )
    selections: dict[str, dict[int, tuple[str, ...]]] = {
        "uniform_greedy": {k: saved[("uniform", "greedy", k)] for k in budgets},
        "commuter_greedy": {k: saved[("commuter_proxy", "greedy", k)] for k in budgets},
        "uniform_balanced": {k: saved[("uniform", "balanced", k)] for k in budgets},
        "commuter_balanced": {k: saved[("commuter_proxy", "balanced", k)] for k in budgets},
    }
    timing: dict[str, float] = {}
    memory: dict[str, float] = {}
    for budget in budgets:
        timing[f"pooled_shortest_k{budget}_seconds"] = _timed_select(
            candidate_ids, pooled_routes, pooled_weights, budget, selections, "pooled_shortest"
        )
        timing[f"robust_pooled_k{budget}_seconds"] = _timed_select(
            candidate_ids, robust_routes, robust_weights, budget, selections, "robust_pooled"
        )
        traced, peak_mb = _traced_select(candidate_ids, robust_routes, robust_weights, budget)
        if traced != selections["robust_pooled"][budget]:
            raise SystemExit("robust selection changed between the timed and traced calls")
        memory[f"robust_pooled_k{budget}_peak_mb"] = peak_mb
    print("Placements selected. Scoring held-out routes.", flush=True)

    marginal = {
        "pooled_shortest": {
            budget: calibration_marginal_gains(pooled_routes, pooled_weights, selections["pooled_shortest"][budget])
            for budget in budgets
        },
        "robust_pooled": {
            budget: calibration_marginal_gains(robust_routes, robust_weights, selections["robust_pooled"][budget])
            for budget in budgets
        },
    }
    municipal = _municipal_additions(
        robust_routes,
        robust_weights,
        candidate_ids,
        addition_budget,
        names,
    )
    seed_rows: list[dict[str, Any]] = []
    for block_name, seeds in (("fresh", fresh_seeds), ("reference", reference_seeds)):
        seed_rows.extend(
            _score_block(
                block_name,
                seeds,
                by_scenario["evaluation"],
                adjacency,
                sigma,
                limits,
                candidate_ids,
                selections,
                municipal,
                scenarios,
            )
        )
    aggregate = _aggregate(seed_rows)
    comparison = _comparison(selections, seed_rows, aggregate, scenarios, budgets)
    calibration_rows_out = _calibration_scores(
        selections, robust_routes, robust_weights, pooled_routes, pooled_weights, by_scenario["calibration"]
    )
    _write_training_diagnostics(output / "training_route_diagnostics.csv", diagnostics)
    _write_placements(output / "placements.csv", selections, names, marginal, budgets)
    _write_csv(output / "calibration_coverage.csv", calibration_rows_out)
    _write_csv(output / "heldout_seed_coverage.csv", seed_rows)
    _write_csv(output / "aggregate_coverage.csv", aggregate)
    _write_csv(output / "comparison.csv", comparison)
    if municipal["available"]:
        _write_csv(output / "municipal_additions.csv", municipal["rows"])
    plot_coverage_by_method(aggregate, output / "figure1_coverage.png")
    plot_robust_gap(seed_rows, output / "figure2_robust_gap.png")
    plot_scenario_tradeoff(comparison, output / "figure3_scenario_tradeoff.png")
    _plot_maps(graph, selections, municipal, candidates, output)
    summary = _summary(
        selections,
        aggregate,
        comparison,
        diagnostics,
        training_records,
        generation_seconds,
        weight_table_seconds,
        timing,
        memory,
        municipal,
        seed_rows,
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    after = _fingerprint()
    if after != before:
        changed = [name for name in before if before[name] != after.get(name)]
        raise SystemExit(f"canonical files changed: {changed}")
    print(f"Wrote {output.relative_to(ROOT)}", flush=True)
    print(summary["headline"], flush=True)


def _seeds(start: object, count: object) -> list[int]:
    first = int(start)
    return list(range(first, first + int(count)))


def _training_realizations(
    grouped: dict[str, list[dict[str, Any]]],
    adjacency: Any,
    seeds: Sequence[int],
    sigma: float,
    limit: float,
    candidates: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for scenario, items in grouped.items():
        for item in items:
            records.append(_record(scenario, item, "shortest", None, item["eligible"]))
            diagnostics.append(_diagnostic(scenario, item, "shortest", None, "shortest", item["path"], item["path"], 0.0))
    for seed in seeds:
        factors = edge_cost_factors(adjacency, seed, sigma)
        for scenario, items in grouped.items():
            for item in items:
                decision = alternative_route(adjacency, item["path"], factors, limit)
                eligible = set(eligible_ids(decision.path.physical_edge_ids, candidates))
                records.append(_record(scenario, item, "alternative", seed, eligible))
                diagnostics.append(
                    _diagnostic(scenario, item, "alternative", seed, decision.status, item["path"], decision.path, decision.detour)
                )
    return records, diagnostics


def _record(scenario: str, item: dict[str, Any], role: str, seed: int | None, eligible: set[str]) -> dict[str, Any]:
    suffix = "shortest" if seed is None else f"alternative:{seed}"
    return {
        "route_key": f"{scenario}:{item['od_id']}:{suffix}",
        "scenario": scenario,
        "od_id": item["od_id"],
        "role": role,
        "seed": seed,
        "eligible": eligible,
    }


def _diagnostic(
    scenario: str,
    item: dict[str, Any],
    role: str,
    seed: int | None,
    status: str,
    original: Any,
    realized: Any,
    detour: float | None,
) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "od_id": item["od_id"],
        "route_id": item["route_id"],
        "origin_node": original.origin,
        "destination_node": original.destination,
        "role": role,
        "seed": "" if seed is None else seed,
        "status": status,
        "original_length_m": round(original.length_m, 3),
        "alternative_length_m": round(realized.length_m, 3),
        "detour": "" if detour is None else round(detour, 6),
        "physical_edge_ids": "|".join(realized.physical_edge_ids),
    }


def _timed_select(
    eligible: set[str],
    routes: dict[str, set[str]],
    weights: dict[str, float],
    budget: int,
    selections: dict[str, dict[int, tuple[str, ...]]],
    method: str,
) -> float:
    started = time.perf_counter()
    selections.setdefault(method, {})[budget] = select_weighted(eligible, routes, weights, budget)
    return time.perf_counter() - started


def _traced_select(
    eligible: set[str],
    routes: dict[str, set[str]],
    weights: dict[str, float],
    budget: int,
) -> tuple[tuple[str, ...], float]:
    tracemalloc.start()
    try:
        selected = select_weighted(eligible, routes, weights, budget)
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return selected, peak / (1024 * 1024)


def _score_block(
    block: str,
    seeds: Sequence[int],
    grouped: dict[str, list[dict[str, Any]]],
    adjacency: Any,
    sigma: float,
    limits: Sequence[float],
    candidates: set[str],
    selections: dict[str, dict[int, tuple[str, ...]]],
    municipal: dict[str, Any],
    scenarios: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    originals = {
        scenario: {item["route_id"]: item["eligible"] for item in items} for scenario, items in grouped.items()
    }
    for scenario in scenarios:
        for method, by_k in _methods_for(selections, municipal, scenario):
            for budget, edges in by_k:
                transition = coverage_transition(originals[scenario], originals[scenario], edges)
                rows.append(
                    _seed_row(block, scenario, method, budget, "shortest", "", transition, 0.0, len(originals[scenario]))
                )
    for seed in seeds:
        print(f"  {block} seed {seed}", flush=True)
        factors = edge_cost_factors(adjacency, seed, sigma)
        proposals = {
            scenario: [
                proposed_shortest(adjacency, item["path"].origin, item["path"].destination, factors) for item in items
            ]
            for scenario, items in grouped.items()
        }
        for limit in limits:
            alternatives = {}
            changed = {}
            for scenario, items in grouped.items():
                decisions = [
                    classify_proposal(item["path"], proposal, limit)
                    for item, proposal in zip(items, proposals[scenario], strict=True)
                ]
                alternatives[scenario] = {
                    item["route_id"]: set(eligible_ids(decision.path.physical_edge_ids, candidates))
                    for item, decision in zip(items, decisions, strict=True)
                }
                changed[scenario] = sum(decision.status == "changed" for decision in decisions) / len(decisions)
            for scenario in scenarios:
                for method, by_k in _methods_for(selections, municipal, scenario):
                    for budget, edges in by_k:
                        transition = coverage_transition(originals[scenario], alternatives[scenario], edges)
                        rows.append(
                            _seed_row(
                                block,
                                scenario,
                                method,
                                budget,
                                f"{limit:.2f}",
                                seed,
                                transition,
                                changed[scenario],
                                len(originals[scenario]),
                            )
                        )
    return rows


def _methods_for(
    selections: dict[str, dict[int, tuple[str, ...]]],
    municipal: dict[str, Any],
    scenario: str,
) -> list[tuple[str, list[tuple[int, tuple[str, ...]]]]]:
    methods = [
        (method, [(budget, edges) for budget, edges in sorted(by_k.items())])
        for method, by_k in selections.items()
    ]
    if municipal["available"]:
        methods.append(("municipal_26", [(0, municipal["existing"])]))
        methods.append(("municipal_original_plus5", [(5, municipal["existing"] + municipal["original"][scenario])]))
        methods.append(("municipal_robust_plus5", [(5, municipal["existing"] + municipal["robust"])]))
    return methods


def _seed_row(
    block: str,
    scenario: str,
    method: str,
    budget: int,
    condition: str,
    seed: object,
    transition: dict[str, float | int],
    fraction_changed: float,
    n_routes: int,
) -> dict[str, Any]:
    if transition["n_net"] != transition["n_gained"] - transition["n_lost"]:
        raise RuntimeError("paired route transitions do not reconcile")
    return {
        "seed_block": block,
        "scenario": scenario,
        "method": method,
        "k": budget,
        "condition": condition,
        "seed": seed,
        "coverage": transition["alternative_coverage"],
        "shortest_coverage": transition["shortest_coverage"],
        "difference": transition["difference"],
        "fraction_changed": fraction_changed,
        "n_routes": n_routes,
        "n_lost": transition["n_lost"],
        "n_gained": transition["n_gained"],
        "n_net": transition["n_net"],
    }


def _aggregate(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in seed_rows:
        grouped[(row["seed_block"], row["scenario"], row["method"], row["k"], row["condition"])].append(row)
    records = []
    for key, rows in sorted(grouped.items(), key=lambda item: tuple(str(part) for part in item[0])):
        shortest_values = {float(row["shortest_coverage"]) for row in rows}
        if len(shortest_values) != 1:
            raise RuntimeError("shortest-path coverage changed inside one evaluation block")
        shortest = shortest_values.pop()
        if key[4] == "shortest":
            records.append(
                {
                    "seed_block": key[0],
                    "scenario": key[1],
                    "method": key[2],
                    "k": key[3],
                    "condition": key[4],
                    "n_seeds": 1,
                    "coverage_mean": shortest,
                    "coverage_median": shortest,
                    "coverage_std": "",
                    "coverage_p05": "",
                    "coverage_p95": "",
                    "coverage_min": shortest,
                    "shortest_coverage": shortest,
                    "difference_mean": 0.0,
                    "loss_percentage_points": 0.0,
                    "fraction_changed_mean": 0.0,
                }
            )
            continue
        summary = summarize_alternative(
            [float(row["coverage"]) for row in rows],
            shortest,
            [float(row["fraction_changed"]) for row in rows],
        )
        records.append(
            {
                "seed_block": key[0],
                "scenario": key[1],
                "method": key[2],
                "k": key[3],
                "condition": key[4],
                **summary,
            }
        )
    return records


def _comparison(
    selections: dict[str, dict[int, tuple[str, ...]]],
    seed_rows: list[dict[str, Any]],
    aggregate: list[dict[str, Any]],
    scenarios: Sequence[str],
    budgets: Sequence[int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for left_name, left in selections.items():
        for right_name, right in selections.items():
            if left_name >= right_name:
                continue
            for budget in budgets:
                shared = len(set(left[budget]) & set(right[budget]))
                union = len(set(left[budget]) | set(right[budget]))
                rows.append(
                    {
                        "kind": "overlap",
                        "method": left_name,
                        "other": right_name,
                        "k": budget,
                        "n_shared": shared,
                        "jaccard": shared / union if union else 1.0,
                        "seed_block": "",
                        "condition": "",
                        "scenario": "",
                    }
                )
    for budget in budgets:
        for condition in ("shortest", "0.15", "0.30"):
            for method in selections:
                uniform = _one(aggregate, "fresh", "uniform", method, budget, condition)
                commuter = _one(aggregate, "fresh", "commuter_proxy", method, budget, condition)
                trade = scenario_tradeoff(float(uniform["coverage_mean"]), float(commuter["coverage_mean"]))
                rows.append(
                    {
                        "kind": "scenario_tradeoff",
                        "method": method,
                        "other": "",
                        "k": budget,
                        "seed_block": "fresh",
                        "condition": condition,
                        "scenario": "both",
                        **trade,
                    }
                )
    for budget in budgets:
        for scenario in scenarios:
            for condition in ("0.15", "0.30"):
                left = _by_seed(seed_rows, "fresh", scenario, "robust_pooled", budget, condition)
                right = _by_seed(seed_rows, "fresh", scenario, "pooled_shortest", budget, condition)
                compared = paired_comparison(
                    left,
                    right,
                    shortest_left=float(_one(aggregate, "fresh", scenario, "robust_pooled", budget, "shortest")["coverage_mean"]),
                    shortest_right=float(
                        _one(aggregate, "fresh", scenario, "pooled_shortest", budget, "shortest")["coverage_mean"]
                    ),
                )
                rows.append(
                    {
                        "kind": "robust_minus_pooled",
                        "method": "robust_pooled",
                        "other": "pooled_shortest",
                        "k": budget,
                        "seed_block": "fresh",
                        "condition": condition,
                        "scenario": scenario,
                        **compared,
                    }
                )
    return rows


def _calibration_scores(
    selections: dict[str, dict[int, tuple[str, ...]]],
    robust_routes: dict[str, set[str]],
    robust_weights: dict[str, float],
    pooled_routes: dict[str, set[str]],
    pooled_weights: dict[str, float],
    calibration: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows = []
    for budget, edges in selections["robust_pooled"].items():
        scored = evaluate_coverage(robust_routes, edges, robust_weights)
        rows.append(
            {
                "method": "robust_pooled",
                "k": budget,
                "score": "robust_training_objective",
                "scenario": "both",
                "coverage": scored.coverage_fraction,
            }
        )
    for budget, edges in selections["pooled_shortest"].items():
        scored = evaluate_coverage(pooled_routes, edges, pooled_weights)
        rows.append(
            {
                "method": "pooled_shortest",
                "k": budget,
                "score": "pooled_shortest_objective",
                "scenario": "both",
                "coverage": scored.coverage_fraction,
            }
        )
        robust_scored = evaluate_coverage(robust_routes, edges, robust_weights)
        rows.append(
            {
                "method": "pooled_shortest",
                "k": budget,
                "score": "robust_training_objective",
                "scenario": "both",
                "coverage": robust_scored.coverage_fraction,
            }
        )
    for method, by_k in selections.items():
        for scenario, items in calibration.items():
            routes = {item["route_id"]: item["eligible"] for item in items}
            for budget, edges in by_k.items():
                scored = evaluate_coverage(routes, edges)
                rows.append(
                    {
                        "method": method,
                        "k": budget,
                        "score": "unweighted_shortest_calibration",
                        "scenario": scenario,
                        "coverage": scored.coverage_fraction,
                    }
                )
    return rows


def _municipal_additions(
    routes: dict[str, set[str]],
    weights: dict[str, float],
    eligible: set[str],
    budget: int,
    names: dict[str, str],
) -> dict[str, Any]:
    summary_path = ROOT / "outputs/standout/summary.json"
    coverage_path = ROOT / "outputs/standout/coverage.csv"
    if not summary_path.is_file() or not coverage_path.is_file():
        return {"available": False, "reason": "standout municipal artifacts are missing"}
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    alignment = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    existing = tuple(row["physical_edge_id"] for row in alignment if row.get("physical_edge_id"))
    if len(existing) != 26 or len(set(existing)) != 26:
        raise SystemExit("the saved name-verified municipal set is not 26 distinct segments")
    if not set(existing) <= eligible:
        raise SystemExit("a municipal segment is not in the eligible candidate set")
    original: dict[str, tuple[str, ...]] = {}
    with coverage_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["budget_new"]) == budget:
                edges = tuple(part for part in row["added_edges"].split("|") if part)
                original[row["scenario"]] = edges[:budget]
    if set(original) != {"uniform", "commuter_proxy"}:
        raise SystemExit("saved municipal additions are missing a scenario")
    for scenario, edges in original.items():
        if len(edges) != budget or len(set(edges)) != budget or set(edges) & set(existing):
            raise SystemExit(f"saved {scenario} additions are not {budget} new segments")
    added = additional_counters(routes, existing, eligible, budget, weights)
    robust = fill_to_k(added, sorted(eligible - set(existing)), budget)
    if set(robust) & set(existing):
        raise SystemExit("a robust addition duplicates a municipal segment")
    rows = []
    for edge in existing:
        rows.append(_addition_row("municipal_26", "existing", edge, "", names))
    for scenario, edges in original.items():
        for rank, edge in enumerate(edges, start=1):
            rows.append(_addition_row("municipal_original_plus5", "original_addition", edge, scenario, names, rank))
    for rank, edge in enumerate(robust, start=1):
        rows.append(_addition_row("municipal_robust_plus5", "robust_addition", edge, "both", names, rank))
    return {"available": True, "existing": existing, "original": original, "robust": robust, "rows": rows}


def _addition_row(
    method: str, role: str, edge: str, scenario: str, names: dict[str, str], rank: int | str = ""
) -> dict[str, Any]:
    return {
        "method": method,
        "role": role,
        "scenario": scenario,
        "rank": rank,
        "physical_edge_id": edge,
        "street_name": names.get(edge, ""),
    }


def _write_placements(
    path: Path,
    selections: dict[str, dict[int, tuple[str, ...]]],
    names: dict[str, str],
    marginal: dict[str, dict[int, list[dict[str, Any]]]],
    budgets: Sequence[int],
) -> None:
    shared = {"pooled_shortest", "robust_pooled"}
    uniform = {budget: set(selections["uniform_greedy"][budget]) for budget in budgets}
    commuter = {budget: set(selections["commuter_greedy"][budget]) for budget in budgets}
    pooled = {budget: set(selections["pooled_shortest"][budget]) for budget in budgets}
    robust = {budget: set(selections["robust_pooled"][budget]) for budget in budgets}
    rows = []
    for method, by_k in selections.items():
        for budget, edges in by_k.items():
            gains = {row["physical_edge_id"]: row for row in marginal.get(method, {}).get(budget, [])}
            for rank, edge in enumerate(edges, start=1):
                gain = gains.get(edge, {})
                rows.append(
                    {
                        "method": method,
                        "shared": method in shared,
                        "k": budget,
                        "rank": gain.get("rank", rank),
                        "physical_edge_id": edge,
                        "street_name": names.get(edge, ""),
                        "calibration_marginal_gain": gain.get("calibration_marginal_gain", ""),
                        "cumulative_calibration_coverage": gain.get("cumulative_calibration_coverage", ""),
                        "uniform_new_weight": gain.get("uniform_new_weight", ""),
                        "commuter_new_weight": gain.get("commuter_new_weight", ""),
                        "in_uniform_greedy": edge in uniform[budget],
                        "in_commuter_greedy": edge in commuter[budget],
                        "in_pooled_shortest": edge in pooled[budget],
                        "in_robust_pooled": edge in robust[budget],
                    }
                )
    _write_csv(path, rows)


def _plot_maps(graph: Any, selections: dict[str, dict[int, tuple[str, ...]]], municipal: dict[str, Any], candidates: dict, output: Path) -> None:
    pooled = set(selections["pooled_shortest"][10])
    robust = set(selections["robust_pooled"][10])
    background = [(float(row["midpoint_lon"]), float(row["midpoint_lat"])) for row in candidates.values()]
    plot_placement_map(
        background,
        _lines_for(graph, pooled - robust),
        _lines_for(graph, robust - pooled),
        _lines_for(graph, pooled & robust),
        output / "figure4_k10_map.png",
    )
    if not municipal["available"]:
        return
    original = set(municipal["original"]["uniform"]) | set(municipal["original"]["commuter_proxy"])
    plot_municipal(
        _read_back(output / "aggregate_coverage.csv"),
        _lines_for(graph, set(municipal["existing"])),
        _lines_for(graph, original - set(municipal["robust"])),
        _lines_for(graph, set(municipal["robust"])),
        output / "figure5_municipal.png",
    )


def _lines_for(graph: Any, edge_ids: set[str]) -> list[list[tuple[float, float]]]:
    found: dict[str, list[tuple[float, float]]] = {}
    for u_node, v_node, _key, data in graph.edges(keys=True, data=True):
        edge_id = str(data.get("physical_edge_id", ""))
        if edge_id in edge_ids and edge_id not in found:
            found[edge_id] = [
                (float(graph.nodes[u_node]["x"]), float(graph.nodes[u_node]["y"])),
                (float(graph.nodes[v_node]["x"]), float(graph.nodes[v_node]["y"])),
            ]
    return list(found.values())


def _summary(
    selections: dict[str, dict[int, tuple[str, ...]]],
    aggregate: list[dict[str, Any]],
    comparison: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    training_records: list[dict[str, Any]],
    generation_seconds: float,
    weight_table_seconds: float,
    timing: dict[str, float],
    memory: dict[str, float],
    municipal: dict[str, Any],
    seed_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    fresh = [
        row
        for row in aggregate
        if row["seed_block"] == "fresh" and row["method"] in {"robust_pooled", "pooled_shortest"} and int(row["k"]) in {10, 20}
    ]
    unique_sets = len({frozenset(record["eligible"]) for record in training_records})
    changed = [
        row for row in diagnostics if row["role"] == "alternative" and row["status"] == "changed"
    ]
    alternatives = [row for row in diagnostics if row["role"] == "alternative"]
    heldout_match = _saved_heldout_match(seed_rows)
    headline = _headline(fresh)
    return {
        "routes_are_simulated": True,
        "training_uses_calibration_only": True,
        "held_out_used_for_selection": False,
        "seed_ranges_disjoint": True,
        "objective": "expected modeled-route coverage, not worst-case coverage",
        "guarantee": "greedy 1-1/e applies to the weighted calibration objective only",
        "headline": headline,
        "fresh_results": fresh,
        "hypotheses": _hypotheses(comparison, aggregate),
        "municipal_available": bool(municipal["available"]),
        "municipal_robust_additions": list(municipal.get("robust", ())),
        "n_training_realizations": len(training_records),
        "n_unique_eligible_sets": unique_sets,
        "fraction_training_routes_changed": len(changed) / len(alternatives) if alternatives else None,
        "runtime_seconds": {
            "route_generation": generation_seconds,
            "weight_table": weight_table_seconds,
            **timing,
        },
        "selection_peak_mb": memory,
        "memory_note": "tracemalloc peak during a separate greedy call, not process RSS, and not included in the timed call",
        "shortest_matches_saved_m4": heldout_match,
        "reference_matches_m56": _reference_match(seed_rows),
        "n_selected": {method: {str(k): len(edges) for k, edges in by_k.items()} for method, by_k in selections.items()},
    }


def _headline(fresh: list[dict[str, Any]]) -> str:
    def value(method: str, scenario: str, budget: int, condition: str) -> float:
        row = _one(fresh, "fresh", scenario, method, budget, condition)
        return float(row["coverage_mean"])

    robust = value("robust_pooled", "uniform", 10, "0.15")
    pooled = value("pooled_shortest", "uniform", 10, "0.15")
    return (
        "Fresh uniform K=10 mean coverage at the 15% cap: "
        f"robust {robust:.1%}, pooled shortest {pooled:.1%}. "
        "These are simulated held-out routes."
    )


def _hypotheses(comparison: list[dict[str, Any]], aggregate: list[dict[str, Any]]) -> dict[str, Any]:
    gaps = [row for row in comparison if row["kind"] == "robust_minus_pooled" and row["condition"] == "0.15"]
    return {
        "h1_mean_gap_by_cell": [
            {
                "scenario": row["scenario"],
                "k": row["k"],
                "mean_robust_minus_pooled": row["mean_left_minus_right"],
            }
            for row in gaps
        ],
        "h5_fraction_robust_beats_pooled": [
            {"scenario": row["scenario"], "k": row["k"], "fraction": row["fraction_left_beats_right"]} for row in gaps
        ],
        "note": "Hypotheses are descriptive. A negative gap means robust coverage was lower on that cell.",
        "shortest_k10": [
            {
                "method": method,
                "scenario": scenario,
                "coverage": float(_one(aggregate, "fresh", scenario, method, 10, "shortest")["coverage_mean"]),
            }
            for method in ("pooled_shortest", "robust_pooled", "uniform_greedy", "commuter_greedy")
            for scenario in ("uniform", "commuter_proxy")
        ],
    }


def _saved_heldout_match(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved = {}
    with (ROOT / "outputs/m4/placements.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["source"] != "louvain" or float(row["threshold"]) != 0.5:
                continue
            if float(row["lambda"]) == 0.0:
                method = "greedy"
            elif float(row["lambda"]) == 0.25:
                method = "balanced"
            else:
                continue
            if int(row["k"]) in {10, 20}:
                saved[(row["scenario"], method, int(row["k"]))] = float(row["heldout_coverage"])
    checks = []
    seen = set()
    for row in seed_rows:
        if row["condition"] != "shortest":
            continue
        scenario = row["scenario"]
        if row["method"] == f"{'uniform' if scenario == 'uniform' else 'commuter'}_greedy":
            method = "greedy"
        elif row["method"] == f"{'uniform' if scenario == 'uniform' else 'commuter'}_balanced":
            method = "balanced"
        else:
            continue
        key = (scenario, method, int(row["k"]))
        if key in seen:
            continue
        seen.add(key)
        checks.append(
            {
                "scenario": scenario,
                "method": method,
                "k": int(row["k"]),
                "recomputed": float(row["coverage"]),
                "saved": saved[key],
                "matches": abs(float(row["coverage"]) - saved[key]) < 5e-4,
            }
        )
    if not all(check["matches"] for check in checks):
        raise SystemExit(f"shortest-path coverage does not match saved M4 values: {checks}")
    return checks


def _reference_match(seed_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    path = ROOT / "outputs/route_choice/aggregate_coverage.csv"
    if not path.is_file():
        return None
    saved = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "greedy" and int(row["k"]) == 10:
                saved[(row["scenario"], float(row["detour_limit"]))] = float(row["coverage_mean"])
    recomputed = {}
    for scenario in ("uniform", "commuter_proxy"):
        for limit in (0.15, 0.30):
            values = [
                float(row["coverage"])
                for row in seed_rows
                if row["seed_block"] == "reference"
                and row["scenario"] == scenario
                and row["method"] == f"{'uniform' if scenario == 'uniform' else 'commuter'}_greedy"
                and int(row["k"]) == 10
                and row["condition"] == f"{limit:.2f}"
            ]
            recomputed[(scenario, limit)] = sum(values) / len(values)
    gaps = {f"{scenario}:{limit}": recomputed[(scenario, limit)] - saved[(scenario, limit)] for scenario, limit in saved}
    if any(abs(gap) > 5e-4 for gap in gaps.values()):
        raise SystemExit(f"reference seeds do not reproduce the saved M5.6 means: {gaps}")
    return {"difference_from_saved_mean": gaps}


def _one(
    rows: list[dict[str, Any]] | Sequence[Mapping[str, Any]],
    block: str,
    scenario: str,
    method: str,
    budget: int,
    condition: str,
) -> Mapping[str, Any]:
    match = [
        row
        for row in rows
        if row["seed_block"] == block
        and row["scenario"] == scenario
        and row["method"] == method
        and int(row["k"]) == budget
        and row["condition"] == condition
    ]
    if len(match) != 1:
        raise RuntimeError(f"missing aggregate row {block} {scenario} {method} K={budget} {condition}")
    return match[0]


def _by_seed(
    rows: list[dict[str, Any]], block: str, scenario: str, method: str, budget: int, condition: str
) -> dict[int, float]:
    return {
        int(row["seed"]): float(row["coverage"])
        for row in rows
        if row["seed_block"] == block
        and row["scenario"] == scenario
        and row["method"] == method
        and int(row["k"]) == budget
        and row["condition"] == condition
    }


def _saved_placements(
    path: Path, budgets: Sequence[int], balanced_lambda: float, threshold: float
) -> dict[tuple[str, str, int], tuple[str, ...]]:
    if not path.is_file():
        raise SystemExit("outputs/m4/placements.csv is missing. Existing placements were not recomputed.")
    selected: dict[tuple[str, str, int], tuple[str, ...]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["source"] != "louvain" or float(row["threshold"]) != threshold:
                continue
            budget = int(row["k"])
            if budget not in budgets:
                continue
            lam = float(row["lambda"])
            if lam == 0.0:
                method = "greedy"
            elif lam == balanced_lambda:
                method = "balanced"
            else:
                continue
            edges = tuple(part for part in row["selected_edges"].split("|") if part)
            if len(set(edges)) != budget:
                raise SystemExit(f"saved {row['scenario']} {method} K={budget} is not {budget} distinct edges")
            selected[(row["scenario"], method, budget)] = edges
    return selected


def _checked_original(graph: Any, row: dict[str, str], candidates: set[str]) -> dict[str, Any]:
    path = shortest_path_from_nodes(graph, [int(node) for node in row["node_ids"].split("|") if node])
    stored = tuple(part for part in row["physical_edge_ids"].split("|") if part)
    if path.physical_edge_ids != stored:
        raise SystemExit(f"{row['route_id']} no longer matches the saved physical edges")
    eligible = set(eligible_ids(path.physical_edge_ids, candidates))
    return {
        "route_id": row["route_id"],
        "scenario": row["scenario"],
        "split": row["split"],
        "od_id": f"{path.origin}:{path.destination}",
        "path": path,
        "eligible": eligible,
    }


def _by_scenario(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[item["scenario"]].append(item)
    return dict(grouped)


def _candidate_table(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return {row["physical_edge_id"]: row for row in rows}


def _read_routes(path: Path, split: str) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["split"] == split]


def _write_training_diagnostics(path: Path, rows: list[dict[str, Any]]) -> None:
    _write_csv(path, rows)


def _read_back(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _fingerprint() -> dict[str, str]:
    found = {}
    for relative in CANONICAL:
        file_path = ROOT / relative
        if file_path.is_file():
            found[relative] = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return found


if __name__ == "__main__":
    main()
