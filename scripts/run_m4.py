"""Community-balanced counter placement on the saved M1 routes.

Reads data/processed/m1/ and outputs/m2/results.csv. Does not rewrite either.
"""

import csv
import json
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

import yaml

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.balanced import (
    community_size_counts,
    community_weights,
    represented_communities,
    shuffle_labels,
    status_coverage,
)
from cyclesense.basemap import load_context_basemap
from cyclesense.communities import assign_heldout, detect_communities, similarity_graph
from cyclesense.m4_map import write_balanced_map
from cyclesense.m4_plots import (
    plot_ablation,
    plot_coverage_vs_lambda,
    plot_representation_vs_lambda,
    plot_robustness,
    plot_tradeoff,
)
from cyclesense.placement import (
    assert_selection,
    candidate_sites,
    mean_pairwise_distance_m,
    multi_counter_fraction,
    score_split,
    select_greedy,
)
from cyclesense.similarity import pairwise_jaccard

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "m4"
SCENARIOS = ("uniform", "commuter_proxy")


def _timed(function):
    tracemalloc.start()
    started = time.perf_counter()
    value = function()
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, elapsed, peak / (1024 * 1024)


def _load_routes(path: Path) -> tuple[dict, dict]:
    physical: dict = {}
    eligible: dict = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            physical.setdefault(row["scenario"], {}).setdefault(row["split"], {})[row["route_id"]] = {
                edge for edge in row["physical_edge_ids"].split("|") if edge
            }
            eligible.setdefault(row["scenario"], {}).setdefault(row["split"], {})[row["route_id"]] = {
                edge for edge in row["eligible_edge_ids"].split("|") if edge
            }
    return physical, eligible


def _m2_greedy(path: Path) -> dict[tuple[str, int], dict[str, str]]:
    saved: dict[tuple[str, int], dict[str, str]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "greedy":
                saved[(row["scenario"], int(row["k"]))] = row
    return saved


def _mean(rows: list[dict], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows)


def main() -> None:
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    settings = config["optimization"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("Validated M1 artifacts are missing. Run scripts/run_m1.py first.")
    physical, eligible = _load_routes(artifacts["routes"])
    candidate_rows = list(csv.DictReader(artifacts["candidates"].open(encoding="utf-8")))
    sites = candidate_sites(candidate_rows)
    eligible_ids = [site.edge_id for site in sites]
    by_edge = {site.edge_id: site for site in sites}
    m2 = _m2_greedy(ROOT / "outputs" / "m2" / "results.csv")
    budgets = [int(value) for value in config["placement"]["counter_budgets"]]
    lambdas = [float(value) for value in settings["lambdas"]]
    thresholds = [float(value) for value in settings["community_thresholds"]]
    primary_threshold = float(settings["primary_threshold"])
    louvain_seed = int(settings["louvain_seed"])
    shuffle_seeds = [int(value) for value in settings["shuffle_seeds"]]
    large_min = int(settings["large_community_min_size"])
    map_lambda = float(settings["map_lambda"])
    map_budget = int(settings["map_budget"])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    placements: list[dict] = []
    shuffle_rows: list[dict] = []
    communities: dict[tuple[str, float], dict] = {}
    assignments: dict[tuple[str, str, float], list[dict]] = {}

    for scenario in SCENARIOS:
        calibration_physical = physical[scenario]["calibration"]
        print(f"{scenario}: exact pairs", flush=True)
        pairs = pairwise_jaccard(calibration_physical)
        for threshold in thresholds:
            graph = similarity_graph(calibration_physical, pairs, threshold)
            labels, modularity, sizes = detect_communities(graph, louvain_seed)
            if set(labels) != set(calibration_physical):
                raise SystemExit("Louvain labels do not cover the calibration routes")
            communities[(scenario, threshold)] = {
                "labels": labels,
                "modularity": modularity,
                "sizes": sizes,
                "n_singletons": sum(1 for size in sizes if size == 1),
            }
            for eval_scenario in SCENARIOS:
                assignments[(scenario, eval_scenario, threshold)] = assign_heldout(
                    physical[eval_scenario]["evaluation"],
                    calibration_physical,
                    labels,
                    threshold,
                )

    for scenario in SCENARIOS:
        calibration = eligible[scenario]["calibration"]
        for threshold in thresholds:
            labels = communities[(scenario, threshold)]["labels"]
            for lam in lambdas:
                weights, weight_info = community_weights(labels, lam)
                for budget in budgets:
                    selected, elapsed, peak = _timed(
                        lambda routes=calibration, k=budget, route_weights=weights: select_greedy(
                            eligible_ids, routes, k, route_weights
                        )
                    )
                    assert_selection(selected, eligible_ids, budget)
                    row = _score_row(
                        scenario=scenario,
                        threshold=threshold,
                        lam=lam,
                        budget=budget,
                        source="louvain",
                        seed=louvain_seed,
                        selected=selected,
                        elapsed=elapsed,
                        peak=peak,
                        weights=weights,
                        weight_info=weight_info,
                        labels=labels,
                        calibration=calibration,
                        eligible=eligible,
                        assignments=assignments,
                        by_edge=by_edge,
                        large_min=large_min,
                    )
                    if lam == 0.0 and threshold == primary_threshold:
                        saved = m2[(scenario, budget)]
                        if "|".join(selected) != saved["selected_edges"]:
                            raise SystemExit(
                                f"lambda 0 does not match M2 greedy for {scenario} K={budget}"
                            )
                        if abs(row["calibration_coverage"] - float(saved["calibration_coverage"])) > 1e-9:
                            raise SystemExit("lambda 0 calibration coverage does not match M2")
                        if abs(row["heldout_coverage"] - float(saved["heldout_coverage"])) > 1e-9:
                            raise SystemExit("lambda 0 held-out coverage does not match M2")
                        row["matches_m2_greedy"] = True
                    placements.append(row)
                    print(
                        f"{scenario} t={threshold} λ={lam} K={budget} "
                        f"held-out {row['heldout_coverage']:.3f}",
                        flush=True,
                    )
            for shuffle_seed in shuffle_seeds:
                shuffled = shuffle_labels(labels, shuffle_seed)
                if community_size_counts(shuffled) != community_size_counts(labels):
                    raise SystemExit("shuffled labels changed the community-size distribution")
                for lam in lambdas:
                    if lam == 0.0:
                        continue
                    weights, weight_info = community_weights(shuffled, lam)
                    for budget in budgets:
                        selected, elapsed, peak = _timed(
                            lambda routes=calibration, k=budget, route_weights=weights: select_greedy(
                                eligible_ids, routes, k, route_weights
                            )
                        )
                        assert_selection(selected, eligible_ids, budget)
                        row = _score_row(
                            scenario=scenario,
                            threshold=threshold,
                            lam=lam,
                            budget=budget,
                            source="shuffled",
                            seed=shuffle_seed,
                            selected=selected,
                            elapsed=elapsed,
                            peak=peak,
                            weights=weights,
                            weight_info=weight_info,
                            labels=labels,
                            calibration=calibration,
                            eligible=eligible,
                            assignments=assignments,
                            by_edge=by_edge,
                            large_min=large_min,
                        )
                        shuffle_rows.append(row)

    _write_csv(OUTPUT / "placements.csv", placements)
    _write_csv(OUTPUT / "ablation.csv", shuffle_rows)
    robustness = _robustness(placements, primary_threshold)
    _write_csv(OUTPUT / "robustness.csv", robustness)
    primary_rows = [row for row in placements if float(row["threshold"]) == primary_threshold]
    shuffle_means = _shuffle_means(shuffle_rows, primary_threshold)
    plot_coverage_vs_lambda(primary_rows, SCENARIOS, OUTPUT / "coverage_vs_lambda.png")
    plot_representation_vs_lambda(primary_rows, SCENARIOS, OUTPUT / "representation_vs_lambda.png")
    plot_tradeoff(primary_rows, SCENARIOS, OUTPUT / "coverage_diversity_tradeoff.png")
    plot_robustness(robustness, OUTPUT / "robustness.png")
    plot_ablation(primary_rows + shuffle_means, SCENARIOS, OUTPUT / "ablation.png")
    _write_map(placements, by_edge, config, artifacts, primary_threshold, map_lambda, map_budget)
    summary = _summary(
        placements, shuffle_rows, robustness, communities, primary_threshold, map_lambda
    )
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"acceptance": summary["acceptance"], "output": str(OUTPUT)}, indent=2))


def _score_row(
    *,
    scenario,
    threshold,
    lam,
    budget,
    source,
    seed,
    selected,
    elapsed,
    peak,
    weights,
    weight_info,
    labels,
    calibration,
    eligible,
    assignments,
    by_edge,
    large_min,
) -> dict:
    points = [(by_edge[edge].x_m, by_edge[edge].y_m) for edge in selected]
    community = represented_communities(
        calibration, labels, selected, large_min_size=large_min
    )
    matched = status_coverage(
        eligible[scenario]["evaluation"],
        assignments[(scenario, scenario, threshold)],
        selected,
    )
    other = "commuter_proxy" if scenario == "uniform" else "uniform"
    shifted = status_coverage(
        eligible[other]["evaluation"],
        assignments[(scenario, other, threshold)],
        selected,
    )
    return {
        "scenario": scenario,
        "threshold": threshold,
        "lambda": lam,
        "k": budget,
        "source": source,
        "seed": seed,
        "n_selected": len(selected),
        "calibration_coverage": score_split(calibration, selected),
        "heldout_coverage": matched["overall_coverage"],
        "assigned_coverage": matched["assigned_coverage"],
        "ambiguous_coverage": matched["ambiguous_coverage"],
        "unassigned_coverage": matched["unassigned_coverage"],
        "n_assigned": matched["n_assigned"],
        "n_ambiguous": matched["n_ambiguous"],
        "n_unassigned": matched["n_unassigned"],
        "shifted_scenario": other,
        "shifted_coverage": shifted["overall_coverage"],
        "n_represented": community["n_represented"],
        "represented_fraction": community["represented_fraction"],
        "n_large": community["n_large"],
        "n_large_represented": community["n_large_represented"],
        "large_represented_fraction": community["large_represented_fraction"],
        "large_member_coverage_mean": community["large_member_coverage_mean"],
        "large_member_coverage_min": community["large_member_coverage_min"],
        "dispersion_m": mean_pairwise_distance_m(points),
        "calibration_multi_counter_fraction": multi_counter_fraction(calibration, selected),
        "heldout_multi_counter_fraction": multi_counter_fraction(
            eligible[scenario]["evaluation"], selected
        ),
        "runtime_s": elapsed,
        "peak_memory_mb": peak,
        "fallback_uniform": weight_info["fallback_uniform"],
        "weight_sum": weight_info["weight_sum"],
        "weight_min": min(weights.values()),
        "matches_m2_greedy": False,
        "selected_edges": "|".join(selected),
    }


def _robustness(rows: list[dict], threshold: float) -> list[dict]:
    table = []
    for row in rows:
        if row["source"] != "louvain" or float(row["threshold"]) != threshold:
            continue
        matched = float(row["heldout_coverage"])
        shifted = float(row["shifted_coverage"])
        table.append(
            {
                "train_scenario": row["scenario"],
                "lambda": row["lambda"],
                "k": row["k"],
                "source": "louvain",
                "matched_coverage": matched,
                "shifted_coverage": shifted,
                "mean_coverage": (matched + shifted) / 2,
                "worst_coverage": min(matched, shifted),
                "matched_minus_shifted": matched - shifted,
            }
        )
    return table


def _shuffle_means(rows: list[dict], threshold: float) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        if float(row["threshold"]) != threshold:
            continue
        groups[(row["scenario"], float(row["lambda"]), int(row["k"]))].append(row)
    means = []
    for (scenario, lam, budget), group in sorted(groups.items()):
        means.append(
            {
                "scenario": scenario,
                "lambda": lam,
                "k": budget,
                "source": "shuffled",
                "heldout_coverage": _mean(group, "heldout_coverage"),
                "large_represented_fraction": _mean(group, "large_represented_fraction"),
            }
        )
    return means


def _write_map(rows, by_edge, config, artifacts, threshold, map_lambda, budget) -> None:
    selections = []
    for row in rows:
        if (
            row["source"] != "louvain"
            or float(row["threshold"]) != threshold
            or int(row["k"]) != budget
            or float(row["lambda"]) not in {0.0, map_lambda}
        ):
            continue
        method = "greedy" if float(row["lambda"]) == 0.0 else "balanced"
        selections.append(
            {
                "method": method,
                "scenario": row["scenario"],
                "sites": [
                    {
                        "edge_id": edge,
                        "lat": by_edge[edge].lat,
                        "lon": by_edge[edge].lon,
                        "name": by_edge[edge].name,
                    }
                    for edge in row["selected_edges"].split("|")
                ],
            }
        )
    selections.sort(key=lambda item: (item["scenario"] != "uniform", item["method"] != "greedy"))
    area = config["study_area"]
    boundary = (float(area["west"]), float(area["south"]), float(area["east"]), float(area["north"]))
    basemap = load_context_basemap(
        ROOT / "cache" / "osm" / "Copenhagen.osm.pbf",
        boundary,
        artifacts["metadata"].parent / "context_basemap.json",
    )
    write_balanced_map(
        selections,
        OUTPUT / "placements_k10.html",
        boundary=boundary,
        basemap=basemap,
        budget=budget,
    )


def _summary(rows, shuffle_rows, robustness, communities, threshold, map_lambda) -> dict:
    primary = [row for row in rows if float(row["threshold"]) == threshold and row["source"] == "louvain"]
    lambda_zero = [row for row in primary if float(row["lambda"]) == 0.0]
    acceptance = {
        "lambda_zero_matches_m2": all(row["matches_m2_greedy"] for row in lambda_zero) and len(lambda_zero) == 8,
        "exactly_k_distinct": all(
            row["n_selected"] == int(row["k"]) and len(set(row["selected_edges"].split("|"))) == int(row["k"])
            for row in rows + shuffle_rows
        ),
        "weights_sum_to_one": all(abs(float(row["weight_sum"]) - 1.0) < 1e-9 for row in rows + shuffle_rows),
        "weights_nonnegative": all(float(row["weight_min"]) >= 0 for row in rows + shuffle_rows),
        "no_fallback_on_primary": all(not row["fallback_uniform"] for row in primary),
        "shuffle_ran": len(shuffle_rows) > 0,
        "cross_scenario_ran": len(robustness) > 0,
    }
    acceptance["passed"] = all(acceptance.values())
    highlight = []
    for row in primary:
        if int(row["k"]) == 10 and float(row["lambda"]) in {0.0, 0.1, 0.25, 0.5, 0.75}:
            highlight.append(
                {
                    "scenario": row["scenario"],
                    "lambda": row["lambda"],
                    "calibration_coverage": row["calibration_coverage"],
                    "heldout_coverage": row["heldout_coverage"],
                    "assigned_coverage": row["assigned_coverage"],
                    "ambiguous_coverage": row["ambiguous_coverage"],
                    "unassigned_coverage": row["unassigned_coverage"],
                    "large_represented_fraction": row["large_represented_fraction"],
                    "large_member_coverage_mean": row["large_member_coverage_mean"],
                    "shifted_coverage": row["shifted_coverage"],
                    "dispersion_m": row["dispersion_m"],
                    "heldout_multi_counter_fraction": row["heldout_multi_counter_fraction"],
                    "runtime_s": row["runtime_s"],
                    "peak_memory_mb": row["peak_memory_mb"],
                }
            )
    community_record = {
        f"{scenario}:{threshold_value}": {
            "n_communities": len(record["sizes"]),
            "n_singletons": record["n_singletons"],
            "largest": max(record["sizes"]),
            "modularity": record["modularity"],
        }
        for (scenario, threshold_value), record in communities.items()
    }
    return {
        "primary_threshold": threshold,
        "map_lambda": map_lambda,
        "acceptance": acceptance,
        "communities": community_record,
        "k10": highlight,
        "robustness_k10": [
            row for row in robustness if int(row["k"]) == 10 and float(row["lambda"]) in {0.0, 0.25, 0.5}
        ],
        "ablation_k10": _ablation_record(rows, shuffle_rows, threshold),
    }


def _ablation_record(rows, shuffle_rows, threshold) -> list[dict]:
    record = []
    for scenario in SCENARIOS:
        for lam in sorted({float(row["lambda"]) for row in rows if float(row["threshold"]) == threshold}):
            if lam == 0.0:
                continue
            louvain = next(
                row for row in rows
                if row["scenario"] == scenario
                and float(row["threshold"]) == threshold
                and float(row["lambda"]) == lam
                and int(row["k"]) == 10
                and row["source"] == "louvain"
            )
            group = [
                row for row in shuffle_rows
                if row["scenario"] == scenario
                and float(row["threshold"]) == threshold
                and float(row["lambda"]) == lam
                and int(row["k"]) == 10
            ]
            record.append(
                {
                    "scenario": scenario,
                    "lambda": lam,
                    "louvain_heldout": louvain["heldout_coverage"],
                    "louvain_large_represented": louvain["large_represented_fraction"],
                    "shuffled_heldout_mean": _mean(group, "heldout_coverage"),
                    "shuffled_large_represented_mean": _mean(group, "large_represented_fraction"),
                }
            )
    return record


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise SystemExit(f"no rows for {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
