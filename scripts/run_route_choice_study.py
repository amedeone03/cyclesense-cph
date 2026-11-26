"""Score fixed counter placements on alternative routes.

The evaluation OD pairs and the selected physical-edge IDs stay as saved.
Each seed draws one positive edge-cost field. Both detour caps are applied
to that same field, so the 30% cap is a relaxation of the 15% cap rather
than a new random network. Coverage uses the existing unweighted definition.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.route_choice import (
    build_adjacency,
    classify_proposal,
    coverage_transition,
    detour_summary,
    edge_cost_factors,
    eligible_ids,
    proposed_shortest,
    set_jaccard,
    shortest_path_from_nodes,
)
from cyclesense.route_choice_plots import (
    plot_coverage_comparison,
    plot_difference_distribution,
    plot_examples,
    plot_method_gap,
    plot_route_generation,
)
from cyclesense.validation_stats import sample_summary

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
    "outputs/standout/summary.json",
    "outputs/standout/coverage.csv",
    "data/external/trafiktal.csv",
)


def main() -> None:
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text())["route_choice"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("M1 artifacts are missing. Route choice was not run and no routes were invented.")
    placements_path = ROOT / "outputs/m4/placements.csv"
    if not placements_path.is_file():
        raise SystemExit("outputs/m4/placements.csv is missing. Placements were not recomputed.")
    before = _fingerprint()
    sigma = float(config["sigma"])
    limits = tuple(float(value) for value in config["detour_limits"])
    seeds = list(range(int(config["seed_start"]), int(config["seed_start"]) + int(config["n_seeds"])))
    budgets = tuple(int(value) for value in config["budgets"])
    balanced_lambda = float(config["balanced_lambda"])
    threshold = float(config["placement_threshold"])

    routes = _evaluation_routes(artifacts["routes"])
    candidates = _candidate_ids(artifacts["candidates"])
    placements = _placements(placements_path, budgets, balanced_lambda, threshold)
    municipal = _municipal_sets()
    graph = ox.load_graphml(artifacts["routing_wgs84"])
    adjacency = build_adjacency(graph)
    originals = {
        scenario: [_checked_original(graph, row, candidates) for row in rows]
        for scenario, rows in routes.items()
    }

    output = ROOT / "outputs/route_choice"
    output.mkdir(parents=True, exist_ok=True)
    route_rows: list[dict[str, Any]] = []
    seed_rows: list[dict[str, Any]] = []
    municipal_rows: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []

    for seed in seeds:
        factors = edge_cost_factors(adjacency, seed, sigma)
        for scenario, prepared in originals.items():
            proposals = [
                proposed_shortest(adjacency, item["path"].origin, item["path"].destination, factors)
                for item in prepared
            ]
            for limit in limits:
                decisions = [
                    classify_proposal(item["path"], proposal, limit)
                    for item, proposal in zip(prepared, proposals, strict=True)
                ]
                alternative_sets = {}
                original_sets = {}
                jaccards = []
                detours = []
                for item, decision in zip(prepared, decisions, strict=True):
                    if decision.status == "changed" and decision.detour is not None:
                        detours.append(decision.detour)
                    jaccards.append(set_jaccard(item["path"].physical_edge_ids, decision.path.physical_edge_ids))
                    original_sets[item["route_id"]] = item["eligible"]
                    alternative_sets[item["route_id"]] = set(eligible_ids(decision.path.physical_edge_ids, candidates))
                    route_rows.append(
                        {
                            "scenario": scenario,
                            "seed": seed,
                            "detour_limit": limit,
                            "route_id": item["route_id"],
                            "origin_node": item["path"].origin,
                            "destination_node": item["path"].destination,
                            "status": decision.status,
                            "original_length_m": round(item["path"].length_m, 3),
                            "alternative_length_m": round(decision.path.length_m, 3),
                            "detour": "" if decision.detour is None else round(decision.detour, 6),
                            "proposed_detour": ""
                            if decision.proposed_detour is None
                            else round(decision.proposed_detour, 6),
                            "set_jaccard": round(
                                set_jaccard(item["path"].physical_edge_ids, decision.path.physical_edge_ids), 6
                            ),
                        }
                    )
                if scenario == "uniform" and seed == seeds[0] and limit == max(limits) and len(examples) < 3:
                    examples.extend(_example_paths(graph, prepared, decisions))
                detours_described = detour_summary(detours)
                counts = _status_counts(decisions)
                for method, k, selected in placements[scenario]:
                    transition = coverage_transition(original_sets, alternative_sets, selected)
                    if transition["n_net"] != transition["n_gained"] - transition["n_lost"]:
                        raise RuntimeError("net coverage change does not match gained minus lost")
                    seed_rows.append(
                        {
                            "scenario": scenario,
                            "method": method,
                            "k": k,
                            "detour_limit": limit,
                            "seed": seed,
                            "n_routes": counts["n"],
                            "n_changed": counts["changed"],
                            "n_unchanged": counts["unchanged"],
                            "n_rejected_detour": counts["rejected_detour"],
                            "n_failed": counts["failed"],
                            "fraction_changed": counts["changed"] / counts["n"],
                            "detour_mean": _blank(detours_described["mean"]),
                            "detour_median": _blank(detours_described["median"]),
                            "detour_p90": _blank(detours_described["p90"]),
                            "detour_max": _blank(detours_described["max"]),
                            "mean_set_jaccard": sum(jaccards) / len(jaccards),
                            "coverage": transition["alternative_coverage"],
                            "shortest_coverage": transition["shortest_coverage"],
                            "difference": transition["difference"],
                            "n_lost": transition["n_lost"],
                            "n_gained": transition["n_gained"],
                            "n_net": transition["n_net"],
                        }
                    )
                if municipal and scenario in municipal:
                    for label, selected in municipal[scenario].items():
                        transition = coverage_transition(original_sets, alternative_sets, selected)
                        municipal_rows.append(
                            {
                                "scenario": scenario,
                                "placement": label,
                                "detour_limit": limit,
                                "seed": seed,
                                "coverage": transition["alternative_coverage"],
                                "shortest_coverage": transition["shortest_coverage"],
                                "difference": transition["difference"],
                                "fraction_changed": counts["changed"] / counts["n"],
                            }
                        )

    aggregate = _aggregate(seed_rows)
    ranking = _ranking(seed_rows)
    association = _changed_fraction_association(seed_rows)
    _write_csv(output / "route_diagnostics.csv", route_rows)
    _write_csv(output / "seed_coverage.csv", seed_rows)
    _write_csv(output / "aggregate_coverage.csv", aggregate)
    _write_csv(output / "ranking.csv", ranking)
    if municipal_rows:
        _write_csv(output / "municipal_coverage.csv", municipal_rows)
    plot_coverage_comparison(seed_rows, output / "coverage_comparison.png")
    plot_difference_distribution(seed_rows, output / "coverage_differences.png")
    plot_route_generation(route_rows, output / "route_generation.png")
    plot_method_gap(seed_rows, output / "method_gap.png")
    plot_examples(examples[:3], output / "example_routes.png")
    summary = {
        "sigma": sigma,
        "perturbation": "length * exp(sigma * Z), Z standard normal, one factor per directed edge",
        "detour_definition": "alternative_original_length / shortest_original_length - 1",
        "detour_limits": list(limits),
        "seeds": seeds,
        "same_perturbation_for_both_detour_limits": True,
        "budgets": list(budgets),
        "balanced_lambda": balanced_lambda,
        "placement_threshold": threshold,
        "n_evaluation": {scenario: len(rows) for scenario, rows in routes.items()},
        "shortest_coverage_matches_saved_m4": _shortest_matches(seed_rows, placements_path, threshold),
        "association_fraction_changed_vs_absolute_difference": association,
        "municipal_included": bool(municipal_rows),
        "routes_are_simulated": True,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    after = _fingerprint()
    if before != after:
        changed = [path for path in CANONICAL if before.get(path) != after.get(path)]
        raise SystemExit(f"canonical artifacts changed: {changed}")
    print(f"Wrote {output}")
    print(f"Seeds {seeds[0]}-{seeds[-1]}")
    for row in aggregate:
        if row["method"] == "greedy" and int(row["k"]) == 10:
            print(
                f"{row['scenario']} {float(row['detour_limit']):.0%} "
                f"changed {float(row['fraction_changed_mean']):.1%} "
                f"coverage {float(row['coverage_mean']):.3f} "
                f"diff {float(row['difference_mean']):.4f}"
            )


def _evaluation_routes(path: Path) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["split"] == "evaluation":
                grouped[row["scenario"]].append(row)
    if set(grouped) != {"uniform", "commuter_proxy"}:
        raise SystemExit(f"unexpected evaluation scenarios: {sorted(grouped)}")
    return dict(grouped)


def _candidate_ids(path: Path) -> set[str]:
    with path.open(newline="") as handle:
        return {row["physical_edge_id"] for row in csv.DictReader(handle)}


def _checked_original(graph: Any, row: dict[str, str], candidates: set[str]) -> dict[str, Any]:
    path = shortest_path_from_nodes(graph, [int(node) for node in row["node_ids"].split("|")])
    stored = tuple(part for part in row["physical_edge_ids"].split("|") if part)
    if path.physical_edge_ids != stored:
        raise SystemExit(f"{row['route_id']} physical edges do not match the graph")
    if path.origin != int(row["origin_node"]) or path.destination != int(row["destination_node"]):
        raise SystemExit(f"{row['route_id']} endpoints do not match the stored OD pair")
    eligible = set(eligible_ids(path.physical_edge_ids, candidates))
    stored_eligible = {part for part in row["eligible_edge_ids"].split("|") if part}
    if eligible != stored_eligible:
        raise SystemExit(f"{row['route_id']} eligible edges do not match the candidate set")
    return {"route_id": row["route_id"], "path": path, "eligible": eligible}


def _placements(
    path: Path, budgets: tuple[int, ...], balanced_lambda: float, threshold: float
) -> dict[str, list[tuple[str, int, tuple[str, ...]]]]:
    selected: dict[tuple[str, str, int], tuple[str, ...]] = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["source"] != "louvain" or float(row["threshold"]) != threshold:
                continue
            k = int(row["k"])
            if k not in budgets:
                continue
            lam = float(row["lambda"])
            if lam == 0.0:
                method = "greedy"
            elif lam == balanced_lambda:
                method = "balanced"
            else:
                continue
            edges = tuple(part for part in row["selected_edges"].split("|") if part)
            if len(edges) != k:
                raise SystemExit(f"{row['scenario']} {method} K={k} does not contain {k} edges")
            selected[(row["scenario"], method, k)] = edges
    expected = {
        (scenario, method, k)
        for scenario in ("uniform", "commuter_proxy")
        for method in ("greedy", "balanced")
        for k in budgets
    }
    if set(selected) != expected:
        raise SystemExit(f"missing placements: {sorted(expected - set(selected))}")
    return {
        scenario: [(method, k, selected[(scenario, method, k)]) for method in ("greedy", "balanced") for k in budgets]
        for scenario in ("uniform", "commuter_proxy")
    }


def _municipal_sets() -> dict[str, dict[str, tuple[str, ...]]] | None:
    summary_path = ROOT / "outputs/standout/summary.json"
    coverage_path = ROOT / "outputs/standout/coverage.csv"
    if not summary_path.is_file() or not coverage_path.is_file():
        return None
    summary = json.loads(summary_path.read_text())
    rows = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    existing = tuple(row["physical_edge_id"] for row in rows if row.get("physical_edge_id"))
    if len(existing) != 26 or len(set(existing)) != 26:
        raise SystemExit("municipal name-verified sites are not the saved 26 segments")
    additions: dict[str, tuple[str, ...]] = {}
    with coverage_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if int(row["budget_new"]) == 5:
                additions[row["scenario"]] = tuple(row["added_edges"].split("|")[:5])
    return {
        scenario: {
            "municipal_26": existing,
            "municipal_26_plus_5": existing + additions[scenario],
        }
        for scenario in ("uniform", "commuter_proxy")
    }


def _example_paths(graph: Any, prepared: list[dict[str, Any]], decisions: list[Any]) -> list[dict[str, Any]]:
    found = []
    for item, decision in zip(prepared, decisions, strict=True):
        if decision.status != "changed" or decision.detour is None or decision.detour < 0.05:
            continue
        found.append(
            {
                "label": item["route_id"],
                "detour": decision.detour,
                "original": _coordinates(graph, item["path"].edges),
                "alternative": _coordinates(graph, decision.path.edges),
            }
        )
        if len(found) == 3:
            break
    return found


def _coordinates(graph: Any, edges: Any) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for u_node, v_node, _key in edges:
        if not points:
            points.append((float(graph.nodes[u_node]["x"]), float(graph.nodes[u_node]["y"])))
        points.append((float(graph.nodes[v_node]["x"]), float(graph.nodes[v_node]["y"])))
    return points


def _status_counts(decisions: list[Any]) -> dict[str, int]:
    counts = {"n": len(decisions), "changed": 0, "unchanged": 0, "rejected_detour": 0, "failed": 0}
    for decision in decisions:
        counts[decision.status] += 1
    return counts


def _aggregate(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in seed_rows:
        grouped[(row["scenario"], row["method"], row["k"], row["detour_limit"])].append(row)
    records = []
    for key, rows in sorted(grouped.items()):
        coverage = sample_summary([float(row["coverage"]) for row in rows])
        difference = sample_summary([float(row["difference"]) for row in rows])
        fraction = sample_summary([float(row["fraction_changed"]) for row in rows])
        records.append(
            {
                "scenario": key[0],
                "method": key[1],
                "k": key[2],
                "detour_limit": key[3],
                "n_seeds": coverage["n"],
                "coverage_mean": coverage["mean"],
                "coverage_std": coverage["std"],
                "coverage_median": coverage["p50"],
                "coverage_p05": coverage["p05"],
                "coverage_p95": coverage["p95"],
                "shortest_coverage": rows[0]["shortest_coverage"],
                "difference_mean": difference["mean"],
                "difference_min": difference["min"],
                "difference_max": difference["max"],
                "fraction_changed_mean": fraction["mean"],
            }
        )
    return records


def _ranking(seed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in seed_rows:
        grouped[(row["scenario"], row["k"], row["detour_limit"])][row["method"]].append(row)
    records = []
    for key, methods in sorted(grouped.items()):
        greedy = sorted(methods["greedy"], key=lambda row: int(row["seed"]))
        balanced = sorted(methods["balanced"], key=lambda row: int(row["seed"]))
        shortest_order = _order(float(greedy[0]["shortest_coverage"]), float(balanced[0]["shortest_coverage"]))
        changes = 0
        gaps = []
        for left, right in zip(greedy, balanced, strict=True):
            gap = float(left["coverage"]) - float(right["coverage"])
            gaps.append(gap)
            if _order(float(left["coverage"]), float(right["coverage"])) != shortest_order:
                changes += 1
        records.append(
            {
                "scenario": key[0],
                "k": key[1],
                "detour_limit": key[2],
                "shortest_order": shortest_order,
                "mean_greedy_minus_balanced": sum(gaps) / len(gaps),
                "n_seeds_order_changed": changes,
                "fraction_seeds_order_changed": changes / len(gaps),
            }
        )
    return records


def _changed_fraction_association(seed_rows: list[dict[str, Any]]) -> list[dict[str, float | str]]:
    grouped: dict[tuple[str, float], list[dict[str, Any]]] = defaultdict(list)
    for row in seed_rows:
        if row["method"] == "greedy" and int(row["k"]) == 10:
            grouped[(row["scenario"], float(row["detour_limit"]))].append(row)
    records = []
    for key, rows in sorted(grouped.items()):
        records.append(
            {
                "scenario": key[0],
                "detour_limit": key[1],
                "pearson_fraction_changed_vs_absolute_coverage_difference": _pearson(
                    [float(row["fraction_changed"]) for row in rows],
                    [abs(float(row["difference"])) for row in rows],
                ),
            }
        )
    return records


def _shortest_matches(seed_rows: list[dict[str, Any]], path: Path, threshold: float) -> list[dict[str, Any]]:
    saved = {}
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["source"] == "louvain" and float(row["threshold"]) == threshold and float(row["lambda"]) in {0.0, 0.25}:
                method = "greedy" if float(row["lambda"]) == 0.0 else "balanced"
                if int(row["k"]) in {10, 20}:
                    saved[(row["scenario"], method, int(row["k"]))] = float(row["heldout_coverage"])
    checks = []
    seen = set()
    for row in seed_rows:
        key = (row["scenario"], row["method"], int(row["k"]))
        if key in seen:
            continue
        seen.add(key)
        checks.append(
            {
                "scenario": key[0],
                "method": key[1],
                "k": key[2],
                "recomputed": float(row["shortest_coverage"]),
                "saved": saved[key],
                "matches": abs(float(row["shortest_coverage"]) - saved[key]) < 5e-4,
            }
        )
    return checks


def _order(left: float, right: float) -> str:
    if abs(left - right) <= 1e-12:
        return "tie"
    return "greedy_higher" if left > right else "balanced_higher"


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) < 3 or len(set(left)) == 1 or len(set(right)) == 1:
        return None
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True))
    left_scale = math_sqrt(sum((a - mean_left) ** 2 for a in left))
    right_scale = math_sqrt(sum((b - mean_right) ** 2 for b in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def math_sqrt(value: float) -> float:
    return value**0.5


def _blank(value: float | None) -> float | str:
    return "" if value is None else round(value, 6)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fingerprint() -> dict[str, str]:
    found = {}
    for relative in CANONICAL:
        path = ROOT / relative
        if path.is_file():
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


if __name__ == "__main__":
    main()
