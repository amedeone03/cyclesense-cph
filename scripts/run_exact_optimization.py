"""Compare greedy counter placements with an exact maximum-coverage MILP.

Calibration routes are the only routes the solver sees. Held-out routes
score the finished sets. A result is optimal only when HiGHS certifies it.
"""

from __future__ import annotations

import csv
import hashlib
import json
import resource
import time
from collections import defaultdict
from pathlib import Path

import yaml

from cyclesense.balanced import community_weights
from cyclesense.communities import detect_communities, similarity_graph
from cyclesense.coverage import evaluate_coverage
from cyclesense.exact_optimization import (
    SOLVER_BACKEND,
    SOLVER_NAME,
    SOLVER_VERSION,
    greedy_optimality_gap,
    meets_approximation_guarantee,
    solve_maximum_coverage,
)
from cyclesense.exact_optimization_plots import (
    figure_calibration,
    figure_gaps,
    figure_heldout,
    figure_map,
    figure_runtime,
    figure_weighted,
)
from cyclesense.external_validation import additional_counters
from cyclesense.placement import fill_to_k, select_greedy
from cyclesense.robust_placement import assign_weights
from cyclesense.similarity import pairwise_jaccard

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "exact_optimization"
CANONICAL = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m3/summary.json",
    "outputs/m4/summary.json",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
    "outputs/integrated/summary.json",
    "outputs/route_choice/summary.json",
    "outputs/scalability/summary.json",
    "outputs/robust_placement/summary.json",
    "outputs/standout/summary.json",
    "outputs/standout/coverage.csv",
    "data/external/trafiktal.csv",
    "configs/pilot.yaml",
    "configs/reproducibility.yaml",
)


def main() -> None:
    before = _fingerprint()
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))["exact_optimization"]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_config(config)
    candidates = _candidates()
    eligible = sorted(candidates)
    physical, eligible_sets, od_ids = _routes()
    rows: list[dict] = []
    placements: list[dict] = []
    print("Primary unweighted budgets")
    for scenario in config["scenarios"]:
        routes = eligible_sets[scenario]["calibration"]
        weights = _equal(routes)
        for budget in config["budgets"]:
            print(f"  {scenario} K={budget}", flush=True)
            rows.append(_compare(
                "unweighted", scenario, budget, routes, weights, eligible,
                _saved_edges(ROOT / "outputs/m2/results.csv", scenario=scenario, method="greedy", k=budget),
                config, placements, eligible_sets,
            ))
    print("Community-balanced weights")
    for scenario in config["scenarios"]:
        routes = eligible_sets[scenario]["calibration"]
        weights = _community_weights(physical[scenario]["calibration"], config)
        for budget in config["weighted_budgets"]:
            print(f"  {scenario} lambda={config['community_lambda']} K={budget}", flush=True)
            saved = _saved_m4(scenario, budget, config)
            rows.append(_compare(
                "community_balanced", scenario, budget, routes, weights, eligible,
                saved, config, placements, eligible_sets,
            ))
    print("Pooled shortest-path weights")
    pooled_routes, pooled_weights = _pooled(eligible_sets, od_ids, config["scenarios"])
    rows.append(_compare(
        "pooled_shortest", "both", config["pooled_k"], pooled_routes, pooled_weights, eligible,
        _robust_edges("pooled_shortest", config["pooled_k"]), config, placements, eligible_sets,
    ))
    robust_row = _robust(config, eligible, eligible_sets, placements)
    if robust_row is not None:
        rows.append(robust_row)
    print("Scalability prefixes")
    rows.extend(_scale(config, eligible, eligible_sets))
    print("Municipal additions")
    municipal = _municipal(config, eligible, eligible_sets, candidates)
    _write_tables(rows, placements, municipal)
    _figures(rows, placements, candidates)
    summary = _summary(config, rows, municipal)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    after = _fingerprint()
    if before != after:
        raise SystemExit("exact optimization changed a canonical artifact")
    print(f"Wrote {OUTPUT / 'summary.json'}")


def _compare(
    objective: str,
    scenario: str,
    budget: int,
    routes: dict[str, set[str]],
    weights: dict[str, float],
    eligible: list[str],
    greedy_edges: list[str],
    config: dict,
    placements: list[dict],
    heldout_sets: dict,
) -> dict:
    started = time.perf_counter()
    greedy = select_greedy(eligible, routes, budget, weights)
    greedy_seconds = time.perf_counter() - started
    if set(greedy) != set(greedy_edges):
        raise SystemExit(f"{objective} {scenario} K={budget} does not reproduce the saved greedy set")
    greedy = list(greedy_edges)
    solved = solve_maximum_coverage(
        routes, weights, eligible, budget,
        time_limit_seconds=float(config["time_limit_seconds"]),
        mip_rel_gap=float(config["mip_rel_gap"]),
    )
    greedy_value = evaluate_coverage(routes, greedy, weights).coverage_fraction
    exact_value = solved.coverage
    gap = {"absolute_gap": None, "relative_gap": None}
    guarantee = None
    if solved.proven_optimal and exact_value is not None:
        gap = greedy_optimality_gap(exact_value, greedy_value, proven=True)
        guarantee = meets_approximation_guarantee(greedy_value, exact_value)
    shared = len(set(greedy) & set(solved.selected))
    union = len(set(greedy) | set(solved.selected))
    heldout_uniform = evaluate_coverage(heldout_sets["uniform"]["evaluation"], greedy).coverage_fraction
    heldout_uniform_exact = evaluate_coverage(heldout_sets["uniform"]["evaluation"], solved.selected).coverage_fraction
    heldout_commuter = evaluate_coverage(heldout_sets["commuter_proxy"]["evaluation"], greedy).coverage_fraction
    heldout_commuter_exact = evaluate_coverage(heldout_sets["commuter_proxy"]["evaluation"], solved.selected).coverage_fraction
    for rank, edge in enumerate(solved.selected, start=1):
        placements.append({
            "objective": objective, "scenario": scenario, "k": budget, "rank": rank,
            "physical_edge_id": edge, "in_greedy": edge in set(greedy),
            "in_solver_support": edge in set(solved.support),
        })
    return {
        "objective": objective,
        "scenario": scenario,
        "k": budget,
        "n_routes": solved.n_routes,
        "n_candidates": solved.n_candidates,
        "n_nonzero": solved.n_nonzero,
        "status": solved.status,
        "proven_optimal": solved.proven_optimal,
        "solver_objective": solved.solver_objective,
        "upper_bound": solved.upper_bound,
        "solver_gap": solved.relative_gap,
        "exact_coverage": exact_value,
        "greedy_coverage": greedy_value,
        "absolute_gap": gap["absolute_gap"],
        "relative_gap": gap["relative_gap"],
        "approximation_holds": guarantee,
        "n_shared": shared,
        "jaccard": shared / union if union else None,
        "milp_seconds": solved.runtime_seconds,
        "greedy_seconds": greedy_seconds,
        "heldout_greedy": heldout_uniform if scenario == "uniform" else heldout_commuter if scenario == "commuter_proxy" else (heldout_uniform + heldout_commuter) / 2,
        "heldout_exact": heldout_uniform_exact if scenario == "uniform" else heldout_commuter_exact if scenario == "commuter_proxy" else (heldout_uniform_exact + heldout_commuter_exact) / 2,
        "heldout_uniform_greedy": heldout_uniform,
        "heldout_uniform_exact": heldout_uniform_exact,
        "heldout_commuter_greedy": heldout_commuter,
        "heldout_commuter_exact": heldout_commuter_exact,
        "greedy_source": "saved_matches_recomputed",
        "support_size": len(solved.support),
        "message": solved.message,
    }


def _community_weights(physical: dict[str, set[str]], config: dict) -> dict[str, float]:
    pairs = pairwise_jaccard(physical)
    graph = similarity_graph(physical, pairs, float(config["community_threshold"]))
    labels, _modularity, _sizes = detect_communities(graph, seed=42)
    weights, _info = community_weights(labels, lam=float(config["community_lambda"]))
    return weights


def _pooled(
    eligible_sets: dict,
    od_ids: dict[str, str],
    scenarios: list[str],
) -> tuple[dict[str, set[str]], dict[str, float]]:
    records = []
    routes = {}
    for scenario in scenarios:
        for route_id, edges in eligible_sets[scenario]["calibration"].items():
            records.append({
                "scenario": scenario,
                "od_id": od_ids[route_id],
                "role": "shortest",
                "route_key": route_id,
            })
            routes[route_id] = edges
    return routes, assign_weights(records, scenarios=scenarios, include_alternatives=False)


def _robust(config: dict, eligible: list[str], eligible_sets: dict, placements: list[dict]) -> dict | None:
    path = ROOT / "outputs/robust_placement/training_route_diagnostics.csv"
    if not path.is_file():
        print("  skipped route-choice MILP: frozen training diagnostics are absent")
        return None
    print("  route-choice-augmented K=10")
    candidate_set = set(eligible)
    routes: dict[str, set[str]] = {}
    records = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = f"{row['scenario']}:{row['od_id']}:{row['role']}:{row['seed']}"
            edges = {edge for edge in row["physical_edge_ids"].split("|") if edge in candidate_set}
            routes[key] = edges
            records.append({"scenario": row["scenario"], "od_id": row["od_id"], "role": row["role"], "route_key": key})
    weights = assign_weights(records, scenarios=tuple(config["scenarios"]), include_alternatives=True)
    return _compare(
        "route_choice", "both", int(config["robust_k"]), routes, weights, eligible,
        _robust_edges("robust_pooled", int(config["robust_k"])), config, placements, eligible_sets,
    )


def _scale(config: dict, eligible: list[str], eligible_sets: dict) -> list[dict]:
    uniform = eligible_sets["uniform"]["calibration"]
    ordered = [uniform[key] for key in sorted(uniform)]
    ids = sorted(uniform)
    rows = []
    for count in config["scale_route_counts"]:
        print(f"  {count} routes")
        if count <= len(ids):
            chosen = {ids[index]: ordered[index] for index in range(count)}
            label = "uniform_prefix"
        else:
            chosen = {}
            for scenario in config["scenarios"]:
                chosen.update(eligible_sets[scenario]["calibration"])
            label = "both_scenarios"
        weights = _equal(chosen)
        started = time.perf_counter()
        greedy = select_greedy(eligible, chosen, int(config["scale_k"]), weights)
        greedy_seconds = time.perf_counter() - started
        solved = solve_maximum_coverage(
            chosen, weights, eligible, int(config["scale_k"]),
            time_limit_seconds=float(config["time_limit_seconds"]),
            mip_rel_gap=float(config["mip_rel_gap"]),
        )
        greedy_value = evaluate_coverage(chosen, greedy, weights).coverage_fraction
        gap = {"absolute_gap": None, "relative_gap": None}
        if solved.proven_optimal and solved.coverage is not None:
            gap = greedy_optimality_gap(solved.coverage, greedy_value, proven=True)
        rows.append({
            "objective": "scale",
            "scenario": label,
            "k": int(config["scale_k"]),
            "n_routes": solved.n_routes,
            "n_candidates": solved.n_candidates,
            "n_nonzero": solved.n_nonzero,
            "status": solved.status,
            "proven_optimal": solved.proven_optimal,
            "solver_objective": solved.solver_objective,
            "upper_bound": solved.upper_bound,
            "solver_gap": solved.relative_gap,
            "exact_coverage": solved.coverage,
            "greedy_coverage": greedy_value,
            "absolute_gap": gap["absolute_gap"],
            "relative_gap": gap["relative_gap"],
            "approximation_holds": None,
            "n_shared": len(set(greedy) & set(solved.selected)),
            "jaccard": None,
            "milp_seconds": solved.runtime_seconds,
            "greedy_seconds": greedy_seconds,
            "heldout_greedy": None,
            "heldout_exact": None,
            "heldout_uniform_greedy": None,
            "heldout_uniform_exact": None,
            "heldout_commuter_greedy": None,
            "heldout_commuter_exact": None,
            "greedy_source": "prefix_greedy",
            "support_size": len(solved.support),
            "message": solved.message,
        })
    return rows


def _municipal(config: dict, eligible: list[str], eligible_sets: dict, names: dict[str, str]) -> list[dict]:
    rows = []
    budget = int(config["municipal_additions"])
    for scenario in config["scenarios"]:
        existing = _municipal_edges(scenario)
        routes = eligible_sets[scenario]["calibration"]
        weights = _equal(routes)
        uncovered = {route_id: edges for route_id, edges in routes.items() if edges.isdisjoint(existing)}
        residual_weights = {route_id: weights[route_id] for route_id in uncovered}
        choices = [edge for edge in eligible if edge not in set(existing)]
        greedy = fill_to_k(additional_counters(routes, existing, choices, budget, weights), choices, budget)
        if not uncovered:
            raise RuntimeError(f"{scenario} municipal sites already cover every calibration route")
        solved = solve_maximum_coverage(
            uncovered, residual_weights, choices, budget,
            time_limit_seconds=float(config["time_limit_seconds"]),
            mip_rel_gap=float(config["mip_rel_gap"]),
        )
        saved = _saved_additions(scenario)
        heldout = eligible_sets[scenario]["evaluation"]
        for method, added in (("greedy", greedy), ("milp", list(solved.selected)), ("saved", saved)):
            full = list(existing) + list(added)
            rows.append({
                "scenario": scenario,
                "method": method,
                "status": solved.status if method == "milp" else "not_a_milp",
                "proven_optimal": solved.proven_optimal if method == "milp" else False,
                "n_added": len(added),
                "added_edges": "|".join(added),
                "overlaps_existing": len(set(added) & set(existing)),
                "calibration_coverage": evaluate_coverage(routes, full, weights).coverage_fraction,
                "heldout_coverage": evaluate_coverage(heldout, full).coverage_fraction,
                "streets": "|".join(names.get(edge, "") for edge in added),
            })
    return rows


def _figures(rows: list[dict], placements: list[dict], names: dict[str, str]) -> None:
    figure_calibration(rows, OUTPUT / "figure1_calibration_coverage.png")
    figure_gaps(rows, OUTPUT / "figure2_greedy_gap.png")
    figure_runtime(rows, OUTPUT / "figure3_runtime.png")
    figure_heldout(rows, OUTPUT / "figure4_heldout_coverage.png")
    weighted = []
    for row in rows:
        if row["objective"] in {"community_balanced", "pooled_shortest", "route_choice"} and row["exact_coverage"] is not None:
            short = {"community_balanced": "Balanced", "pooled_shortest": "Pooled", "route_choice": "Route choice"}
            scenario = {"uniform": "U", "commuter_proxy": "C", "both": "both"}.get(row["scenario"], row["scenario"])
            weighted.append({
                "label": f"{short[row['objective']]} {scenario} K={row['k']}",
                "greedy_coverage": row["greedy_coverage"],
                "exact_coverage": row["exact_coverage"],
            })
    if weighted:
        figure_weighted(weighted, OUTPUT / "figure6_weighted_objectives.png")
    _maybe_map(placements, names)


def _maybe_map(placements: list[dict], names: dict[str, str]) -> None:
    greedy = _saved_edges(ROOT / "outputs/m2/results.csv", scenario="uniform", method="greedy", k=10)
    exact = [
        row["physical_edge_id"]
        for row in placements
        if row["objective"] == "unweighted" and row["scenario"] == "uniform" and int(row["k"]) == 10
    ]
    if set(greedy) == set(exact):
        return
    graph_path = ROOT / "data/processed/m1/copenhagen_bike_routing_wgs84.graphml"
    if not graph_path.is_file():
        return
    import osmnx as ox

    graph = ox.load_graphml(graph_path)
    segments = []
    seen = set()
    for u, v, _key, data in graph.edges(keys=True, data=True):
        edge_id = str(data.get("physical_edge_id") or "")
        if not edge_id or edge_id in seen:
            continue
        if "geometry" in data:
            xs, ys = data["geometry"].xy
            xs, ys = list(xs), list(ys)
        else:
            xs = [graph.nodes[u]["x"], graph.nodes[v]["x"]]
            ys = [graph.nodes[u]["y"], graph.nodes[v]["y"]]
        seen.add(edge_id)
        segments.append((edge_id, xs, ys))
    if segments:
        figure_map(segments, greedy, exact, OUTPUT / "figure5_k10_locations.png", "Uniform K=10, Indre By")
    del names


def _write_tables(rows: list[dict], placements: list[dict], municipal: list[dict]) -> None:
    _csv(OUTPUT / "solver_runs.csv", rows)
    _csv(OUTPUT / "exact_placements.csv", placements)
    _csv(OUTPUT / "greedy_comparison.csv", [row for row in rows if row["objective"] == "unweighted"])
    _csv(OUTPUT / "weighted_comparison.csv", [row for row in rows if row["objective"] in {"community_balanced", "pooled_shortest", "route_choice"}])
    _csv(OUTPUT / "heldout_comparison.csv", [row for row in rows if row["heldout_exact"] is not None])
    _csv(OUTPUT / "runtime_summary.csv", rows)
    _csv(OUTPUT / "instance_statistics.csv", rows)
    _csv(OUTPUT / "municipal_additions.csv", municipal)


def _summary(config: dict, rows: list[dict], municipal: list[dict]) -> dict:
    proven = [row for row in rows if row["proven_optimal"]]
    limited = [row for row in rows if row["status"] == "time_limited"]
    return {
        "routes_are_simulated": True,
        "held_out_used_for_selection": False,
        "solver": SOLVER_NAME,
        "solver_backend": SOLVER_BACKEND,
        "solver_version": SOLVER_VERSION,
        "time_limit_seconds": config["time_limit_seconds"],
        "mip_rel_gap": config["mip_rel_gap"],
        "n_runs": len(rows),
        "n_proven_optimal": len(proven),
        "n_time_limited": len(limited),
        "process_peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024),
        "primary": [row for row in rows if row["objective"] == "unweighted"],
        "weighted": [row for row in rows if row["objective"] in {"community_balanced", "pooled_shortest", "route_choice"}],
        "municipal": municipal,
        "coverage_is_modeled_route_coverage": True,
        "optimal_means_certified_by_highs": True,
    }


def _equal(routes: dict[str, set[str]]) -> dict[str, float]:
    weight = 1.0 / len(routes)
    return {route_id: weight for route_id in routes}


def _mean_scenario_coverage(eligible_sets: dict, edges: list[str]) -> float:
    values = [
        evaluate_coverage(eligible_sets[scenario]["evaluation"], edges).coverage_fraction
        for scenario in ("uniform", "commuter_proxy")
    ]
    return sum(values) / len(values)


def _routes() -> tuple[dict, dict, dict[str, str]]:
    physical: dict = defaultdict(lambda: defaultdict(dict))
    eligible: dict = defaultdict(lambda: defaultdict(dict))
    od_ids: dict[str, str] = {}
    with (ROOT / "data/processed/m1/routes.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            physical[row["scenario"]][row["split"]][row["route_id"]] = set(row["physical_edge_ids"].split("|"))
            eligible[row["scenario"]][row["split"]][row["route_id"]] = set(filter(None, row["eligible_edge_ids"].split("|")))
            od_ids[row["route_id"]] = f"{row['origin_node']}:{row['destination_node']}"
    return physical, eligible, od_ids


def _candidates() -> dict[str, str]:
    names = {}
    with (ROOT / "data/processed/m1/candidates.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            names[row["physical_edge_id"]] = row.get("name") or ""
    return names


def _saved_edges(path: Path, **filters: object) -> list[str]:
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if all(str(row[key]) == str(value) for key, value in filters.items()):
                return row["selected_edges"].split("|")
    raise KeyError(filters)


def _saved_m4(scenario: str, budget: int, config: dict) -> list[str]:
    with (ROOT / "outputs/m4/placements.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if (
                row["scenario"] == scenario
                and int(row["k"]) == budget
                and float(row["lambda"]) == float(config["community_lambda"])
                and float(row["threshold"]) == float(config["community_threshold"])
                and row["source"] == "louvain"
            ):
                return row["selected_edges"].split("|")
    raise KeyError((scenario, budget))


def _robust_edges(method: str, budget: int) -> list[str]:
    edges = []
    with (ROOT / "outputs/robust_placement/placements.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == method and int(row["k"]) == budget:
                edges.append((int(row["rank"]), row["physical_edge_id"]))
    if len(edges) != budget:
        raise KeyError((method, budget))
    return [edge for _rank, edge in sorted(edges)]


def _municipal_edges(_scenario: str) -> list[str]:
    summary = json.loads((ROOT / "outputs/standout/summary.json").read_text(encoding="utf-8"))
    rows = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    edges = sorted({row["physical_edge_id"] for row in rows if row.get("physical_edge_id")})
    if len(edges) != 26:
        raise RuntimeError(f"name-verified municipal segments are {len(edges)}, not 26")
    return edges


def _saved_additions(scenario: str) -> list[str]:
    with (ROOT / "outputs/standout/coverage.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["scenario"] == scenario:
                return row["added_edges"].split("|")
    raise KeyError(scenario)


def _write_config(config: dict) -> None:
    payload = {
        "solver": SOLVER_NAME,
        "solver_backend": SOLVER_BACKEND,
        "solver_version": SOLVER_VERSION,
        "settings": config,
        "budget_constraint": "the MILP uses at most K; the reported placement is filled to exactly K",
        "held_out_used_for_selection": False,
    }
    (OUTPUT / "experiment_config.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fingerprint() -> dict[str, str]:
    hashes = {}
    for relative in CANONICAL:
        path = ROOT / relative
        if path.is_file():
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


if __name__ == "__main__":
    main()
