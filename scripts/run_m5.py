"""Final validation of the saved M2–M4 results.

Reads the canonical route file and the M4 placements. Writes only under
outputs/m5/. Does not refit Louvain on evaluation routes and does not change
the selected counters.
"""

import csv
import hashlib
import json
import time
import tracemalloc
from pathlib import Path

import yaml

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.balanced import community_weights, represented_communities, shuffle_labels
from cyclesense.communities import detect_communities, similarity_graph
from cyclesense.m5_plots import (
    plot_coverage_vs_budget,
    plot_coverage_vs_lambda,
    plot_cross_scenario,
    plot_paired_differences,
    plot_scalability,
    plot_shuffle_controls,
)
from cyclesense.minhash import (
    build_lsh_buckets,
    build_signatures,
    query_lsh_pairs,
    verify_candidates,
)
from cyclesense.network import node_coordinates, project_lonlat
from cyclesense.placement import select_greedy
from cyclesense.retrieval_benchmark import exact_similar_pairs, lsh_verified_pairs
from cyclesense.routes import generate_modeled_routes
from cyclesense.similarity import pairwise_jaccard
from cyclesense.validation_stats import outside_central_90, paired_differences, sample_summary

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "m5"
SCENARIOS = ("uniform", "commuter_proxy")
GUARDED = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m2/summary.json",
    "outputs/m3/summary.json",
    "outputs/m4/summary.json",
    "outputs/m4/placements.csv",
)


def _fingerprint(root: Path) -> dict[str, str]:
    hashes = {}
    for relative in GUARDED:
        path = root / relative
        if not path.is_file():
            raise SystemExit(f"missing canonical artifact {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _timed(function, *args):
    tracemalloc.start()
    started = time.perf_counter()
    value = function(*args)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, elapsed, peak / (1024 * 1024)


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise SystemExit(f"no rows for {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_routes(path: Path) -> tuple[dict, dict, set, set]:
    physical: dict = {}
    eligible: dict = {}
    blocked_od: set[tuple[int, int]] = set()
    blocked_paths: set[tuple[str, ...]] = set()
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            physical_ids = tuple(edge for edge in row["physical_edge_ids"].split("|") if edge)
            eligible_ids = {edge for edge in row["eligible_edge_ids"].split("|") if edge}
            physical.setdefault(row["scenario"], {}).setdefault(row["split"], {})[row["route_id"]] = set(physical_ids)
            eligible.setdefault(row["scenario"], {}).setdefault(row["split"], {})[row["route_id"]] = eligible_ids
            blocked_od.add((int(row["origin_node"]), int(row["destination_node"])))
            blocked_paths.add(physical_ids)
    return physical, eligible, blocked_od, blocked_paths


def _coverage(routes: list[set[str]], selected: list[str]) -> float:
    chosen = set(selected)
    if not routes:
        raise ValueError("evaluation sample is empty")
    return sum(1 for edges in routes if edges & chosen) / len(routes)


def main() -> None:
    before = _fingerprint(ROOT)
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    settings = config["validation"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("Validated M1 artifacts are missing.")
    physical, eligible, blocked_od, blocked_paths = _load_routes(artifacts["routes"])
    candidate_rows = list(csv.DictReader(artifacts["candidates"].open(encoding="utf-8")))
    eligible_ids = [row["physical_edge_id"] for row in candidate_rows]
    placements = [
        row for row in csv.DictReader((ROOT / "outputs" / "m4" / "placements.csv").open(encoding="utf-8"))
        if row["source"] == "louvain" and float(row["threshold"]) == float(settings["jaccard_threshold"])
    ]
    m4_summary = json.loads((ROOT / "outputs" / "m4" / "summary.json").read_text(encoding="utf-8"))
    OUTPUT.mkdir(parents=True, exist_ok=True)

    labels = _communities(physical, settings, m4_summary)
    seed_rows, summary_rows = _shuffle_study(eligible, eligible_ids, labels, placements, settings)
    _write_csv(OUTPUT / "ablation_seeds.csv", seed_rows)
    _write_csv(OUTPUT / "ablation_summary.csv", summary_rows)

    sample_rows = _new_samples(
        artifacts, config, eligible_ids, placements, blocked_od, blocked_paths, settings
    )
    _write_csv(OUTPUT / "evaluation_samples.csv", sample_rows)
    budget_rows, paired_rows, cross_rows = _evaluation_summaries(sample_rows)
    _write_csv(OUTPUT / "evaluation_summary.csv", budget_rows)
    _write_csv(OUTPUT / "paired_differences.csv", paired_rows)

    scaling_rows = _scalability(artifacts, config, settings)
    _write_csv(OUTPUT / "scalability.csv", scaling_rows)
    consolidated = _consolidated(summary_rows, budget_rows, cross_rows)
    _write_csv(OUTPUT / "consolidated_k10.csv", consolidated)

    lambda_rows = [
        row for row in placements if float(row["lambda"]) in {0.0, 0.1, 0.25, 0.5, 0.75}
    ]
    plot_coverage_vs_budget(budget_rows, OUTPUT / "coverage_vs_budget.png")
    plot_coverage_vs_lambda(lambda_rows, OUTPUT / "coverage_vs_lambda.png")
    plot_shuffle_controls(seed_rows, OUTPUT / "shuffle_controls.png")
    plot_cross_scenario(cross_rows, OUTPUT / "cross_scenario.png")
    plot_paired_differences(paired_rows, OUTPUT / "evaluation_variability.png")
    plot_scalability(scaling_rows, OUTPUT / "scalability.png")

    after = _fingerprint(ROOT)
    if after != before:
        raise SystemExit("a canonical M1–M4 artifact changed during validation")
    summary = {
        "acceptance": {
            "canonical_artifacts_unchanged": True,
            "shuffle_seeds": int(settings["n_shuffle_seeds"]),
            "evaluation_samples": int(settings["n_evaluation_samples"]),
            "scalability_sizes": [int(row["n_routes"]) for row in scaling_rows],
            "passed": True,
        },
        "ablation_k10": [
            row for row in summary_rows if int(row["k"]) == 10 and row["metric"] == "heldout_coverage"
        ],
        "evaluation_k10": [row for row in budget_rows if int(row["k"]) == 10],
        "paired_k10": [row for row in paired_rows if int(row["k"]) == 10],
        "cross_k10": [row for row in cross_rows if int(row["k"]) == 10],
        "scalability": scaling_rows,
        "consolidated_k10": consolidated,
    }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"acceptance": summary["acceptance"], "output": str(OUTPUT)}, indent=2))


def _communities(physical, settings, m4_summary) -> dict[str, dict[str, int]]:
    threshold = float(settings["jaccard_threshold"])
    labels = {}
    for scenario in SCENARIOS:
        calibration = physical[scenario]["calibration"]
        print(f"{scenario}: calibration communities", flush=True)
        pairs = pairwise_jaccard(calibration)
        graph = similarity_graph(calibration, pairs, threshold)
        found, _modularity, sizes = detect_communities(graph, 42)
        record = m4_summary["communities"][f"{scenario}:{threshold}"]
        if len(sizes) != int(record["n_communities"]) or sum(size == 1 for size in sizes) != int(record["n_singletons"]):
            raise SystemExit(f"{scenario} communities do not match the saved M4 partition")
        labels[scenario] = found
    return labels


def _placement_edges(placements, scenario, lam, budget) -> list[str]:
    row = next(
        item for item in placements
        if item["scenario"] == scenario and float(item["lambda"]) == lam and int(item["k"]) == budget
    )
    return row["selected_edges"].split("|")


def _shuffle_study(eligible, eligible_ids, labels, placements, settings) -> tuple[list[dict], list[dict]]:
    seeds = [int(settings["shuffle_seed_start"]) + index for index in range(int(settings["n_shuffle_seeds"]))]
    lambdas = [float(value) for value in settings["comparison_lambdas"]]
    budgets = [5, 10, 20, 30]
    seed_rows = []
    for scenario in SCENARIOS:
        calibration = eligible[scenario]["calibration"]
        evaluation = list(eligible[scenario]["evaluation"].values())
        reference = labels[scenario]
        for lam in lambdas:
            for budget in budgets:
                saved = _placement_edges(placements, scenario, lam, budget)
                louvain_coverage = _coverage(evaluation, saved)
                community = represented_communities(calibration, reference, saved, large_min_size=2)
                louvain_representation = float(community["large_represented_fraction"])
                for seed in seeds:
                    shuffled = shuffle_labels(reference, seed)
                    weights, _info = community_weights(shuffled, lam)
                    selected = select_greedy(eligible_ids, calibration, budget, weights)
                    seed_rows.append(
                        {
                            "scenario": scenario,
                            "lambda": lam,
                            "k": budget,
                            "seed": seed,
                            "metric": "heldout_coverage",
                            "shuffle_value": _coverage(evaluation, selected),
                            "louvain_value": louvain_coverage,
                        }
                    )
                    seed_rows.append(
                        {
                            "scenario": scenario,
                            "lambda": lam,
                            "k": budget,
                            "seed": seed,
                            "metric": "large_represented_fraction",
                            "shuffle_value": represented_communities(
                                calibration, reference, selected, large_min_size=2
                            )["large_represented_fraction"],
                            "louvain_value": louvain_representation,
                        }
                    )
                print(f"shuffle {scenario} λ={lam} K={budget}", flush=True)
    summary_rows = []
    groups: dict[tuple, list[dict]] = {}
    for row in seed_rows:
        groups.setdefault((row["scenario"], row["lambda"], row["k"], row["metric"]), []).append(row)
    for key, group in groups.items():
        values = [float(row["shuffle_value"]) for row in group]
        summary = sample_summary(values)
        louvain = float(group[0]["louvain_value"])
        summary_rows.append(
            {
                "scenario": key[0],
                "lambda": key[1],
                "k": key[2],
                "metric": key[3],
                "louvain": louvain,
                "shuffle_mean": summary["mean"],
                "shuffle_std": summary["std"],
                "p05": summary["p05"],
                "p25": summary["p25"],
                "p50": summary["p50"],
                "p75": summary["p75"],
                "p95": summary["p95"],
                "louvain_minus_mean": louvain - float(summary["mean"]),
                "n_shuffles_below": sum(value < louvain for value in values),
                "outside_central_90": outside_central_90(louvain, summary),
            }
        )
    return seed_rows, summary_rows


def _new_samples(artifacts, config, eligible_ids, placements, blocked_od, blocked_paths, settings):
    import osmnx as ox

    simulation = config["simulation"]
    anchor_cfg = simulation["commuter_proxy"]
    routing = ox.load_graphml(artifacts["routing_wgs84"])
    projected = ox.load_graphml(artifacts["routing_projected"])
    coordinates = node_coordinates(projected)
    anchor_xy = project_lonlat(
        float(anchor_cfg["anchor_lon"]), float(anchor_cfg["anchor_lat"]), projected.graph["crs"]
    )
    candidate_ids = set(eligible_ids)
    n_samples = int(settings["n_evaluation_samples"])
    n_routes = int(settings["evaluation_routes"])
    rows = []
    methods = [(0.0, "greedy"), (0.25, "balanced"), (0.5, "balanced")]
    for scenario in SCENARIOS:
        for index in range(n_samples):
            seed = int(settings["evaluation_seed_start"]) + index
            generated, stats = generate_modeled_routes(
                routing,
                coordinates,
                candidate_ids,
                scenario=scenario,
                n_calibration=0,
                n_evaluation=n_routes,
                calibration_seed=seed + 1,
                evaluation_seed=seed,
                min_distance_m=float(simulation["min_od_distance_m"]),
                max_distance_m=float(simulation["max_od_distance_m"]),
                min_eligible_edges=int(simulation["min_eligible_edges"]),
                anchor_xy=anchor_xy if scenario == "commuter_proxy" else None,
                distance_floor_m=float(anchor_cfg.get("distance_floor_m", 50)),
                max_attempts_factor=int(simulation.get("max_attempts_factor", 80)),
                blocked_od=blocked_od,
                blocked_paths=blocked_paths,
            )
            kept = int(stats["evaluation"]["kept"])
            if kept != n_routes:
                raise SystemExit(f"{scenario} sample {seed} kept {kept} of {n_routes}")
            routes = [set(route.eligible_edge_ids) for route in generated]
            fresh_paths = {route.physical_edge_ids for route in generated}
            if not fresh_paths.isdisjoint(blocked_paths):
                raise SystemExit("a new evaluation route repeats a canonical path")
            for train in SCENARIOS:
                for lam, method in methods:
                    for budget in (5, 10, 20, 30):
                        selected = _placement_edges(placements, train, lam, budget)
                        rows.append(
                            {
                                "sample_scenario": scenario,
                                "sample_seed": seed,
                                "train_scenario": train,
                                "method": method,
                                "lambda": lam,
                                "k": budget,
                                "role": "matched" if train == scenario else "shifted",
                                "coverage": _coverage(routes, selected),
                            }
                        )
            print(f"evaluation sample {scenario} seed {seed}", flush=True)
    return rows


def _evaluation_summaries(rows):
    budget_rows = []
    paired_rows = []
    cross_rows = []
    for scenario in SCENARIOS:
        for lam in (0.0, 0.25, 0.5):
            for budget in (5, 10, 20, 30):
                matched = [
                    float(row["coverage"]) for row in rows
                    if row["sample_scenario"] == scenario
                    and row["train_scenario"] == scenario
                    and float(row["lambda"]) == lam
                    and int(row["k"]) == budget
                ]
                summary = sample_summary(matched)
                budget_rows.append(
                    {
                        "scenario": scenario,
                        "lambda": lam,
                        "k": budget,
                        "role": "matched",
                        "mean": summary["mean"],
                        "std": summary["std"],
                        "p05": summary["p05"],
                        "p50": summary["p50"],
                        "p95": summary["p95"],
                    }
                )
                if lam == 0.0:
                    continue
                baseline = [
                    float(row["coverage"]) for row in rows
                    if row["sample_scenario"] == scenario
                    and row["train_scenario"] == scenario
                    and float(row["lambda"]) == 0.0
                    and int(row["k"]) == budget
                ]
                delta = sample_summary(paired_differences(baseline, matched))
                paired_rows.append(
                    {
                        "scenario": scenario,
                        "lambda": lam,
                        "k": budget,
                        "mean": delta["mean"],
                        "std": delta["std"],
                        "p05": delta["p05"],
                        "p50": delta["p50"],
                        "p95": delta["p95"],
                    }
                )
    for train in SCENARIOS:
        other = "commuter_proxy" if train == "uniform" else "uniform"
        for lam in (0.0, 0.25, 0.5):
            for budget in (5, 10, 20, 30):
                matched = [
                    float(row["coverage"]) for row in rows
                    if row["sample_scenario"] == train
                    and row["train_scenario"] == train
                    and float(row["lambda"]) == lam
                    and int(row["k"]) == budget
                ]
                shifted = [
                    float(row["coverage"]) for row in rows
                    if row["sample_scenario"] == other
                    and row["train_scenario"] == train
                    and float(row["lambda"]) == lam
                    and int(row["k"]) == budget
                ]
                matched_summary = sample_summary(matched)
                shifted_summary = sample_summary(shifted)
                cross_rows.append(
                    {
                        "train_scenario": train,
                        "lambda": lam,
                        "k": budget,
                        "matched_mean": matched_summary["mean"],
                        "matched_std": matched_summary["std"],
                        "shifted_mean": shifted_summary["mean"],
                        "shifted_std": shifted_summary["std"],
                        "worst_mean": min(float(matched_summary["mean"]), float(shifted_summary["mean"])),
                    }
                )
    return budget_rows, paired_rows, cross_rows


def _verified(route_sets, num_perm, bands, rows, threshold):
    return lsh_verified_pairs(
        route_sets,
        num_perm=num_perm,
        bands=bands,
        rows=rows,
        threshold=threshold,
        seed=42,
    )


def _scalability(artifacts, config, settings):
    import osmnx as ox

    simulation = config["simulation"]
    routing = ox.load_graphml(artifacts["routing_wgs84"])
    projected = ox.load_graphml(artifacts["routing_projected"])
    coordinates = node_coordinates(projected)
    candidate_ids = {
        row["physical_edge_id"]
        for row in csv.DictReader(artifacts["candidates"].open(encoding="utf-8"))
    }
    sizes = [int(size) for size in settings["scalability_sizes"]]
    seed = int(settings["scalability_seed"])
    started = time.perf_counter()
    generated, _stats = generate_modeled_routes(
        routing,
        coordinates,
        candidate_ids,
        scenario="uniform",
        n_calibration=max(sizes),
        n_evaluation=0,
        calibration_seed=seed,
        evaluation_seed=seed + 1,
        min_distance_m=float(simulation["min_od_distance_m"]),
        max_distance_m=float(simulation["max_od_distance_m"]),
        min_eligible_edges=int(simulation["min_eligible_edges"]),
        max_attempts_factor=int(simulation.get("max_attempts_factor", 80)),
    )
    generation_seconds = time.perf_counter() - started
    route_sets = [set(route.physical_edge_ids) for route in generated if route.physical_edge_ids]
    print(f"scalability routes {len(route_sets)} generated in {generation_seconds:.1f}s", flush=True)
    num_perm = int(settings["lsh_num_perm"])
    bands = int(settings["lsh_bands"])
    rows = int(settings["lsh_rows"])
    threshold = float(settings["jaccard_threshold"])
    measured = []
    for size in sizes:
        subset = route_sets[:size]
        exact, exact_seconds, exact_mb = _timed(exact_similar_pairs, subset, threshold)
        verified_bundle, lsh_seconds, lsh_mb = _timed(
            _verified,
            subset,
            num_perm,
            bands,
            rows,
            threshold,
        )
        candidates, verified = verified_bundle
        signatures, signature_seconds, _signature_mb = _timed(build_signatures, subset, num_perm, 42)
        buckets, index_seconds, _index_mb = _timed(build_lsh_buckets, signatures, bands, rows)
        queried, query_seconds, _query_mb = _timed(query_lsh_pairs, signatures, buckets, bands, rows)
        _checked, verify_seconds, _verify_mb = _timed(verify_candidates, queried, subset, threshold)
        possible = size * (size - 1) // 2
        recall = (len(verified & exact) / len(exact)) if exact else None
        measured.append(
            {
                "n_routes": size,
                "generation_seconds": generation_seconds,
                "exact_seconds": exact_seconds,
                "exact_peak_mb": exact_mb,
                "n_exact_pairs": len(exact),
                "lsh_seconds": lsh_seconds,
                "lsh_peak_mb": lsh_mb,
                "preprocess_seconds": signature_seconds + index_seconds,
                "query_seconds": query_seconds,
                "verify_seconds": verify_seconds,
                "n_candidates": len(candidates),
                "n_verified": len(verified),
                "recall": recall,
                "candidate_reduction": 1 - (len(candidates) / possible),
                "exact_faster": exact_seconds < lsh_seconds,
                "num_perm": num_perm,
                "bands": bands,
                "rows": rows,
                "threshold": threshold,
            }
        )
        print(
            f"  n={size} exact={exact_seconds:.3f}s lsh={lsh_seconds:.3f}s "
            f"recall={recall} reduction={measured[-1]['candidate_reduction']:.3f}",
            flush=True,
        )
    return measured


def _consolidated(summary_rows, budget_rows, cross_rows) -> list[dict]:
    table = []
    for scenario in SCENARIOS:
        for lam in (0.0, 0.25, 0.5):
            matched = next(
                row for row in budget_rows
                if row["scenario"] == scenario and float(row["lambda"]) == lam and int(row["k"]) == 10
            )
            cross = next(
                row for row in cross_rows
                if row["train_scenario"] == scenario and float(row["lambda"]) == lam and int(row["k"]) == 10
            )
            record = {
                "scenario": scenario,
                "lambda": lam,
                "k": 10,
                "new_sample_mean": matched["mean"],
                "new_sample_std": matched["std"],
                "new_sample_p05": matched["p05"],
                "new_sample_p95": matched["p95"],
                "shifted_mean": cross["shifted_mean"],
                "shifted_std": cross["shifted_std"],
                "worst_mean": cross["worst_mean"],
            }
            if lam != 0.0:
                ablation = next(
                    row for row in summary_rows
                    if row["scenario"] == scenario
                    and float(row["lambda"]) == lam
                    and int(row["k"]) == 10
                    and row["metric"] == "heldout_coverage"
                )
                record["original_heldout"] = ablation["louvain"]
                record["shuffle_mean"] = ablation["shuffle_mean"]
                record["shuffle_std"] = ablation["shuffle_std"]
                record["louvain_minus_shuffle"] = ablation["louvain_minus_mean"]
                record["outside_central_90"] = ablation["outside_central_90"]
            else:
                record["original_heldout"] = ""
                record["shuffle_mean"] = ""
                record["shuffle_std"] = ""
                record["louvain_minus_shuffle"] = ""
                record["outside_central_90"] = ""
            table.append(record)
    return table


if __name__ == "__main__":
    main()
