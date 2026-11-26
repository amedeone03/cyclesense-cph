"""Run the M2 counter-placement baselines on the saved M1 pilot.

From the repository root, with the analysis extra installed:

    python scripts/run_m2.py
    python scripts/run_m2.py --map-only

Selection uses each scenario's calibration routes. Held-out routes are scored
after the counters are chosen. The script does not regenerate routes.
``--map-only`` rewrites the placement HTML from ``outputs/m2/selected_k10.csv``
and does not recompute coverage.

Outputs are written under outputs/m2/. Modeled-route coverage is not an
observed bicycle count.
"""

import csv
import json
import sys
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.assumptions import NOT_OBSERVED_DEMAND
from cyclesense.basemap import load_context_basemap
from cyclesense.placement import (
    METHODS,
    STOCHASTIC_METHODS,
    candidate_sites,
    mean_pairwise_distance_m,
    multi_counter_fraction,
    score_split,
    select_counters,
)
from cyclesense.placement_map import write_placement_map
from cyclesense.placement_plots import plot_coverage, plot_runtime, plot_saturation


def _routes_for(
    rows: list[dict[str, str]],
    scenario: str,
    split: str,
    eligible: set[str],
) -> tuple[dict[str, set[str]], dict[str, float], int]:
    routes: dict[str, set[str]] = {}
    weights: dict[str, float] = {}
    empty = 0
    for row in rows:
        if row["scenario"] != scenario or row["split"] != split:
            continue
        edges = {edge for edge in row["eligible_edge_ids"].split("|") if edge and edge in eligible}
        if not edges:
            empty += 1
        routes[row["route_id"]] = edges
        weights[row["route_id"]] = float(row["scenario_weight"])
    return routes, weights, empty


def _mean_std(values: list[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    if len(values) == 1:
        return mean, 0.0
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return mean, variance**0.5


def _comparison(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["scenario"], record["method"], record["k"])].append(record)
    rows = []
    for (scenario, method, budget), items in sorted(groups.items()):
        heldout = [float(item["heldout_coverage"]) for item in items]
        calibration = [float(item["calibration_coverage"]) for item in items]
        runtime = [float(item["runtime_s"]) for item in items]
        memory = [float(item["peak_memory_mb"]) for item in items]
        dispersion = [float(item["dispersion_m"]) for item in items]
        multi = [float(item["heldout_multi_counter_fraction"]) for item in items]
        heldout_mean, heldout_std = _mean_std(heldout)
        calibration_mean, _calibration_std = _mean_std(calibration)
        runtime_mean, _runtime_std = _mean_std(runtime)
        memory_mean, _memory_std = _mean_std(memory)
        dispersion_mean, _dispersion_std = _mean_std(dispersion)
        multi_mean, _multi_std = _mean_std(multi)
        rows.append(
            {
                "scenario": scenario,
                "method": method,
                "k": budget,
                "n_seeds": len(items),
                "heldout_coverage_mean": heldout_mean,
                "heldout_coverage_std": heldout_std,
                "heldout_coverage_min": min(heldout),
                "heldout_coverage_max": max(heldout),
                "calibration_coverage_mean": calibration_mean,
                "runtime_s_mean": runtime_mean,
                "peak_memory_mb_mean": memory_mean,
                "dispersion_m_mean": dispersion_mean,
                "heldout_multi_counter_fraction_mean": multi_mean,
            }
        )
    return rows


def _saturates_early(coverage_at: dict[int, float]) -> bool:
    """Descriptive rule fixed before reading the pilot numbers.

    Early saturation means K=5 already covers at least 85% of held-out
    routes, or K=10 covers at least 75% and the step from 20 to 30 adds
    less than 2 percentage points.
    """
    gain_20_30 = coverage_at[30] - coverage_at[20]
    return coverage_at[5] >= 0.85 or (coverage_at[10] >= 0.75 and gain_20_30 < 0.02)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _warm_kmeans() -> None:
    """Import scikit-learn before the timed loop.

    The first ``KMeans.fit`` otherwise spends its time on import and allocator
    startup. That cost is not part of selecting counters.
    """
    import numpy as np
    from sklearn.cluster import KMeans

    KMeans(n_clusters=1, random_state=0, n_init=1, algorithm="lloyd").fit(np.array([[0.0, 0.0]]))


def main() -> None:
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit("No validated M1 artifacts. Run python scripts/run_m1.py first.")
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    placement = config["placement"]
    budgets = [int(budget) for budget in placement["counter_budgets"]]
    seeds = [int(seed) for seed in placement["stochastic_seeds"]]
    map_budget = int(placement.get("map_budget", 10))
    map_seed = int(placement.get("map_seed", seeds[0]))
    methods = [str(method) for method in placement["methods"]]
    unknown = [method for method in methods if method not in METHODS]
    if unknown:
        raise SystemExit(f"Unsupported M2 methods: {unknown}. Community-aware placement is deferred.")

    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    box = metadata["boundary"]
    boundary = (float(box["west"]), float(box["south"]), float(box["east"]), float(box["north"]))
    candidate_rows = list(csv.DictReader(paths["candidates"].open(encoding="utf-8")))
    route_rows = list(csv.DictReader(paths["routes"].open(encoding="utf-8")))
    sites = candidate_sites(candidate_rows)
    eligible = {site.edge_id for site in sites}
    by_id = {site.edge_id: site for site in sites}
    scenarios = list(config["simulation"]["scenarios"])
    output_dir = ROOT / "outputs" / "m2"
    output_dir.mkdir(parents=True, exist_ok=True)

    _warm_kmeans()
    records: list[dict[str, Any]] = []
    for scenario in scenarios:
        calibration, calibration_weights, empty_calibration = _routes_for(
            route_rows, scenario, "calibration", eligible
        )
        evaluation, evaluation_weights, empty_evaluation = _routes_for(
            route_rows, scenario, "evaluation", eligible
        )
        if set(calibration) & set(evaluation):
            raise SystemExit(f"{scenario} reuses a route id across the calibration split")
        print(
            f"{scenario}: calibration={len(calibration)} evaluation={len(evaluation)} "
            f"empty_eligible={empty_calibration + empty_evaluation}",
            flush=True,
        )
        for method in methods:
            method_seeds: list[int | None] = list(seeds) if method in STOCHASTIC_METHODS else [None]
            for seed in method_seeds:
                for budget in budgets:
                    tracemalloc.start()
                    started = time.perf_counter()
                    selected = select_counters(
                        method,
                        sites,
                        calibration,
                        budget,
                        seed=seed,
                        weights=calibration_weights,
                    )
                    runtime_s = time.perf_counter() - started
                    _current, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    points = [(by_id[edge].x_m, by_id[edge].y_m) for edge in selected]
                    record = {
                        "scenario": scenario,
                        "method": method,
                        "k": budget,
                        "seed": "" if seed is None else seed,
                        "n_selected": len(selected),
                        "calibration_coverage": score_split(calibration, selected, calibration_weights),
                        "heldout_coverage": score_split(evaluation, selected, evaluation_weights),
                        "calibration_multi_counter_fraction": multi_counter_fraction(calibration, selected),
                        "heldout_multi_counter_fraction": multi_counter_fraction(evaluation, selected),
                        "dispersion_m": mean_pairwise_distance_m(points),
                        "runtime_s": runtime_s,
                        "peak_memory_mb": peak / 1_000_000,
                        "selected_edges": "|".join(selected),
                    }
                    records.append(record)
                    print(
                        f"  {method} K={budget} seed={record['seed'] or '-'} "
                        f"heldout={record['heldout_coverage']:.3f} "
                        f"time={runtime_s:.3f}s",
                        flush=True,
                    )

    _write_csv(output_dir / "results.csv", records)
    comparison = _comparison(records)
    _write_csv(output_dir / "comparison.csv", comparison)

    selected_rows = []
    map_selections = []
    for record in records:
        if int(record["k"]) != map_budget:
            continue
        seed_value = record["seed"]
        if seed_value not in {"", map_seed}:
            continue
        sites_for_map = []
        for edge in str(record["selected_edges"]).split("|"):
            site = by_id[edge]
            selected_rows.append(
                {
                    "scenario": record["scenario"],
                    "method": record["method"],
                    "seed": seed_value,
                    "physical_edge_id": edge,
                    "lon": site.lon,
                    "lat": site.lat,
                    "name": site.name,
                    "highway": site.highway,
                }
            )
            sites_for_map.append(
                {
                    "edge_id": edge,
                    "lon": site.lon,
                    "lat": site.lat,
                    "name": site.name,
                    "highway": site.highway,
                }
            )
        map_selections.append(
            {
                "method": record["method"],
                "scenario": record["scenario"],
                "seed": None if seed_value == "" else seed_value,
                "sites": sites_for_map,
            }
        )
    _write_csv(output_dir / "selected_k10.csv", selected_rows)

    plot_coverage(records, scenarios, output_dir / "coverage_vs_budget.png")
    plot_runtime(records, scenarios, output_dir / "runtime.png")
    plot_saturation(records, scenarios, output_dir / "saturation.png")

    pbf = Path(str(metadata.get("pbf_path") or ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"))
    if not pbf.is_file():
        pbf = ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"
    basemap = load_context_basemap(pbf, boundary, paths["summary"].parent / "context_basemap.json")
    map_path = write_placement_map(
        [
            {
                "method": selection["method"],
                "seed": selection["seed"],
                "sites": selection["sites"],
                "scenario": selection["scenario"],
            }
            for selection in map_selections
        ],
        output_dir / "placements_k10.html",
        boundary=boundary,
        basemap=basemap,
        budget=map_budget,
    )

    saturation = []
    for scenario in scenarios:
        for method in methods:
            coverage_at = {
                int(row["k"]): float(row["heldout_coverage_mean"])
                for row in comparison
                if row["scenario"] == scenario and row["method"] == method
            }
            saturation.append(
                {
                    "scenario": scenario,
                    "method": method,
                    "heldout_coverage": coverage_at,
                    "gain_5_to_10": coverage_at[10] - coverage_at[5],
                    "gain_10_to_20": coverage_at[20] - coverage_at[10],
                    "gain_20_to_30": coverage_at[30] - coverage_at[20],
                    "saturates_early": _saturates_early(coverage_at),
                }
            )

    acceptance_errors = []
    for record in records:
        edges = [edge for edge in str(record["selected_edges"]).split("|") if edge]
        if len(edges) != int(record["k"]) or len(set(edges)) != len(edges):
            acceptance_errors.append(f"{record['method']} {record['scenario']} K={record['k']} is not exactly K")
        if not set(edges) <= eligible:
            acceptance_errors.append(f"{record['method']} selected an ineligible segment")
        if not 0.0 <= float(record["heldout_coverage"]) <= 1.0:
            acceptance_errors.append("held-out coverage outside [0, 1]")
    if acceptance_errors:
        raise SystemExit("M2 acceptance failed: " + "; ".join(acceptance_errors))

    summary = {
        "note": NOT_OBSERVED_DEMAND,
        "budgets": budgets,
        "stochastic_seeds": seeds,
        "map_budget": map_budget,
        "map_seed": map_seed,
        "n_candidates": len(sites),
        "scenarios": scenarios,
        "comparison": comparison,
        "saturation": saturation,
        "acceptance_passed": True,
        "outputs": {
            "results": "outputs/m2/results.csv",
            "comparison": "outputs/m2/comparison.csv",
            "selected_k10": "outputs/m2/selected_k10.csv",
            "coverage_plot": "outputs/m2/coverage_vs_budget.png",
            "runtime_plot": "outputs/m2/runtime.png",
            "saturation_plot": "outputs/m2/saturation.png",
            "map": "outputs/m2/placements_k10.html",
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {map_path.relative_to(ROOT)}", flush=True)
    print("M2 acceptance checks passed.", flush=True)


def rebuild_placement_map() -> Path:
    """Rewrite the K=10 HTML from the saved counter list.

    This does not select counters again and does not rewrite the result tables.
    """
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit("No validated M1 artifacts. Run python scripts/run_m1.py first.")
    selected_path = ROOT / "outputs" / "m2" / "selected_k10.csv"
    if not selected_path.is_file():
        raise SystemExit("No outputs/m2/selected_k10.csv. Run python scripts/run_m2.py first.")
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    budget = int(config["placement"].get("map_budget", 10))
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    box = metadata["boundary"]
    boundary = (float(box["west"]), float(box["south"]), float(box["east"]), float(box["north"]))
    selections: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    with selected_path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["scenario"], row["method"], row["seed"])
            selection = grouped.get(key)
            if selection is None:
                seed = None if row["seed"] == "" else int(row["seed"])
                selection = {
                    "method": row["method"],
                    "scenario": row["scenario"],
                    "seed": seed,
                    "sites": [],
                }
                grouped[key] = selection
                selections.append(selection)
            selection["sites"].append(
                {
                    "edge_id": row["physical_edge_id"],
                    "lon": float(row["lon"]),
                    "lat": float(row["lat"]),
                    "name": row["name"],
                    "highway": row["highway"],
                }
            )
    pbf = Path(str(metadata.get("pbf_path") or ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"))
    if not pbf.is_file():
        pbf = ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"
    basemap = load_context_basemap(pbf, boundary, paths["summary"].parent / "context_basemap.json")
    return write_placement_map(
        selections,
        ROOT / "outputs" / "m2" / "placements_k10.html",
        boundary=boundary,
        basemap=basemap,
        budget=budget,
    )


if __name__ == "__main__":
    if "--map-only" in sys.argv:
        written = rebuild_placement_map()
        print(f"Wrote {written.relative_to(ROOT)}", flush=True)
    else:
        main()
