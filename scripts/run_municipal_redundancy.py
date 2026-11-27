"""Attribute modeled-route coverage across the 26 name-verified counting sites.

Selection of the published sites and of the saved additions is not repeated.
Held-out routes are scored after the sets are read. Nothing here is a
recommendation to remove a municipal counting location.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.coverage import evaluate_coverage
from cyclesense.external_validation import permutation_pvalue, spearman_rho
from cyclesense.municipal_redundancy import (
    attribute_sites,
    complement_counts,
    cumulative_coverage,
    incremental_shapley,
    pairwise_overlap,
    validate_additions,
)
from cyclesense.municipal_redundancy_plots import (
    figure_cumulative,
    figure_multiplicity,
    figure_overlap,
    figure_site_values,
    figure_three_metrics,
)
from cyclesense.placement_stability_plots import physical_lines

OUTPUT = ROOT / "outputs" / "municipal_redundancy"
SCENARIOS = ("uniform", "commuter_proxy")
SPLITS = ("calibration", "evaluation")


def main() -> None:
    started = time.perf_counter()
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit("Saved M1 artifacts are missing or failed validation. Run scripts/run_m1.py.")
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))["municipal_redundancy"]
    sites = _sites()
    names = _candidate_names(paths["candidates"])
    if not {row["physical_edge_id"] for row in sites} <= set(names):
        raise SystemExit("a name-verified municipal segment is outside the eligible candidate universe")
    routes = _routes(paths["routes"])
    saved = _saved_coverage()
    attributions = {}
    for scenario in SCENARIOS:
        for split in SPLITS:
            result = attribute_sites(routes[(scenario, split)], [row["physical_edge_id"] for row in sites])
            field = "calibration_existing_coverage" if split == "calibration" else "held_out_existing_coverage"
            if abs(result["coverage"] - float(saved[scenario][field])) > 1e-9:
                raise SystemExit(f"{scenario} {split} coverage does not match the saved municipal baseline")
            attributions[(scenario, split)] = result
    pairs = {
        (scenario, split): pairwise_overlap(routes[(scenario, split)], [row["physical_edge_id"] for row in sites])
        for scenario in SCENARIOS
        for split in SPLITS
    }
    additions = _addition_sets()
    addition_rows, cumulative_rows = _score_additions(routes, sites, additions, names)
    aadt_rows = _aadt(sites, attributions, config)
    graph = ox.load_graphml(paths["routing_wgs84"])
    lines = physical_lines(graph)
    missing = [row["physical_edge_id"] for row in sites if row["physical_edge_id"] not in lines]
    if missing:
        raise SystemExit(f"municipal segments have no saved geometry: {missing[:3]}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_sites(sites, attributions, names)
    _write_multiplicity(attributions)
    _write_pairs(pairs, sites)
    _write_scenario(sites, attributions)
    _write_dicts("addition_comparison.csv", addition_rows)
    _write_dicts("cumulative_additions.csv", cumulative_rows)
    _write_dicts("aadt_comparison.csv", aadt_rows)
    summary = _summary(sites, attributions, pairs, addition_rows, aadt_rows, time.perf_counter() - started)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "experiment_config.json").write_text(
        json.dumps(
            {
                "sites": "outputs/standout/summary.json recurring_name_agree.alignment_rows",
                "n_sites": 26,
                "routes": "data/processed/m1/routes.csv physical_edge_ids",
                "coverage": "a route counts once if it traverses any selected physical segment",
                "shapley": "exact 1/m_r credit on each covered route",
                "held_out_used_for_selection": False,
                "removal_recommendation": False,
                "aadt_permutation_seed": int(config["aadt_permutation_seed"]),
                "aadt_permutation_draws": int(config["aadt_permutation_draws"]),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _figures(lines, sites, attributions, pairs, cumulative_rows)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


def _sites() -> list[dict]:
    path = ROOT / "outputs/standout/summary.json"
    if not path.is_file():
        raise SystemExit("Municipal alignment is missing. Run scripts/run_external_validation.py.")
    summary = json.loads(path.read_text(encoding="utf-8"))
    rows = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    sites = [row for row in rows if row.get("physical_edge_id")]
    ids = [row["physical_edge_id"] for row in sites]
    if len(ids) != len(set(ids)) or len(ids) != 26:
        raise SystemExit(f"expected 26 distinct municipal segments, found {len(set(ids))}")
    return sites


def _candidate_names(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["physical_edge_id"]: row.get("name") or "" for row in csv.DictReader(handle)}


def _routes(path: Path) -> dict[tuple[str, str], dict[str, set[str]]]:
    stored: dict[tuple[str, str], dict[str, set[str]]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "physical_edge_ids" not in reader.fieldnames:
            raise SystemExit("routes CSV has no physical_edge_ids column")
        for row in reader:
            key = (row["scenario"], row["split"])
            stored.setdefault(key, {})[row["route_id"]] = {part for part in row["physical_edge_ids"].split("|") if part}
    expected = {("uniform", "calibration"): 500, ("uniform", "evaluation"): 250, ("commuter_proxy", "calibration"): 500, ("commuter_proxy", "evaluation"): 250}
    for key, count in expected.items():
        if len(stored.get(key, {})) != count:
            raise SystemExit(f"{key[0]} {key[1]} has {len(stored.get(key, {}))} routes, expected {count}")
    return stored


def _saved_coverage() -> dict[str, dict[str, str]]:
    path = ROOT / "outputs/standout/coverage.csv"
    if not path.is_file():
        raise SystemExit("Saved municipal coverage is missing. Run scripts/run_external_validation.py.")
    saved = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["budget_new"] == "5":
                saved[row["scenario"]] = row
    if set(saved) != set(SCENARIOS):
        raise SystemExit("saved municipal coverage is missing a scenario")
    return saved


def _addition_sets() -> list[dict]:
    sets = []
    coverage_path = ROOT / "outputs/standout/coverage.csv"
    with coverage_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for scenario in SCENARIOS:
        five = next(row for row in rows if row["scenario"] == scenario and row["budget_new"] == "5")
        ten = next(row for row in rows if row["scenario"] == scenario and row["budget_new"] == "10")
        five_edges = [part for part in five["added_edges"].split("|") if part]
        ten_edges = [part for part in ten["added_edges"].split("|") if part]
        if ten_edges[:5] != five_edges:
            raise SystemExit(f"{scenario} greedy additions of 5 are not the prefix of the 10")
        sets.append(_method("greedy", scenario, "unweighted_calibration_coverage", five_edges, "ordered"))
        sets.append(_method("greedy", scenario, "unweighted_calibration_coverage", ten_edges, "ordered"))
    exact_path = ROOT / "outputs/exact_optimization/municipal_additions.csv"
    if not exact_path.is_file():
        raise SystemExit("Certified municipal additions are missing. Run scripts/run_exact_optimization.py.")
    with exact_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] != "milp":
                continue
            if row["proven_optimal"] != "True":
                raise SystemExit(f"{row['scenario']} municipal MILP additions are not certified")
            edges = [part for part in row["added_edges"].split("|") if part]
            sets.append(_method("milp", row["scenario"], "unweighted_calibration_coverage", edges, "unordered"))
    robust_path = ROOT / "outputs/robust_placement/municipal_additions.csv"
    if not robust_path.is_file():
        raise SystemExit("Route-choice municipal additions are missing. Run scripts/run_robust_placement.py.")
    robust = []
    with robust_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "municipal_robust_plus5":
                robust.append(row["physical_edge_id"])
    if len(robust) != 5:
        raise SystemExit(f"expected 5 route-choice additions, found {len(robust)}")
    sets.append(_method("robust", "pooled", "route_choice_pooled_objective", robust, "unordered"))
    infra_path = ROOT / "outputs/infrastructure/municipal_additions.csv"
    if infra_path.is_file():
        grouped: dict[tuple[str, str, str], list[str]] = {}
        with infra_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["policy"] == "unrestricted":
                    continue
                grouped.setdefault((row["training_scenario"], row["policy"], row["method"]), []).append(row["physical_edge_id"])
        for (scenario, policy, method), edges in sorted(grouped.items()):
            kind = "ordered" if method == "greedy" else "unordered"
            objective = "unweighted_calibration_coverage_on_permitted_segments"
            sets.append(_method(f"infrastructure_{policy}_{method}", scenario, objective, edges, kind))
    return sets


def _method(name: str, scenario: str, objective: str, edges: list[str], order: str) -> dict:
    return {"method": name, "training_scenario": scenario, "objective": objective, "edges": edges, "order": order}


def _score_additions(routes, sites, additions, names):
    existing = [row["physical_edge_id"] for row in sites]
    comparison = []
    cumulative = []
    baselines = {
        (scenario, split): evaluate_coverage(routes[(scenario, split)], existing).coverage_fraction
        for scenario in SCENARIOS
        for split in SPLITS
    }
    comparison.append(_comparison_row("municipal_26", "published", "not_an_optimized_objective", [], existing, routes, baselines, names))
    for item in additions:
        validate_additions(existing, item["edges"])
        comparison.append(
            _comparison_row(item["method"], item["training_scenario"], item["objective"], item["edges"], existing, routes, baselines, names)
        )
        training = item["training_scenario"]
        scenarios = SCENARIOS if training == "pooled" else (training,)
        for scenario in scenarios:
            if item["order"] == "ordered" and not (item["method"] == "greedy" and len(item["edges"]) == 5):
                for split in SPLITS:
                    for row in cumulative_coverage(routes[(scenario, split)], existing, item["edges"]):
                        cumulative.append(
                            {
                                "training_scenario": training,
                                "evaluation_scenario": scenario,
                                "evaluation_split": split,
                                "method": "greedy" if item["method"] == "greedy" else item["method"],
                                "attribution": "ordered",
                                "step": row["step"],
                                "physical_edge_id": row["physical_edge_id"],
                                "street_name": names.get(row["physical_edge_id"], ""),
                                "coverage": row["coverage"],
                                "gain": row["gain"],
                            }
                        )
            else:
                shares = incremental_shapley(routes[(scenario, "calibration")], existing, item["edges"])
                full = evaluate_coverage(routes[(scenario, "calibration")], existing + item["edges"]).coverage_fraction
                base = baselines[(scenario, "calibration")]
                if abs(sum(shares.values()) - (full - base)) > 1e-8:
                    raise RuntimeError(f"{item['method']} incremental Shapley does not sum to the added coverage")
                for edge, share in shares.items():
                    cumulative.append(
                        {
                            "training_scenario": training,
                            "evaluation_scenario": scenario,
                            "evaluation_split": "calibration",
                            "method": item["method"],
                            "attribution": "incremental_shapley",
                            "step": "",
                            "physical_edge_id": edge,
                            "street_name": names.get(edge, ""),
                            "coverage": full,
                            "gain": share,
                        }
                    )
    return comparison, cumulative


def _comparison_row(method, training, objective, edges, existing, routes, baselines, names):
    chosen = list(existing) + list(edges)
    row = {
        "method": method,
        "training_scenario": training,
        "objective": objective,
        "n_sites": len(existing),
        "n_added": len(edges),
        "added_edges": "|".join(edges),
        "added_streets": "|".join(names.get(edge, "") for edge in edges),
    }
    for scenario in SCENARIOS:
        for split, label in (("calibration", "calibration"), ("evaluation", "heldout")):
            coverage = evaluate_coverage(routes[(scenario, split)], chosen).coverage_fraction
            base = baselines[(scenario, split)]
            row[f"{scenario}_{label}"] = coverage
            row[f"{scenario}_{label}_gain_pp"] = (coverage - base) * 100
        for split, label in (("calibration", "calibration"), ("evaluation", "heldout")):
            counts = complement_counts(routes[(scenario, split)], existing, edges) if edges else {
                "n_newly_covered_routes": 0,
                "n_additions_on_already_covered_routes": 0,
            }
            row[f"{scenario}_{label}_newly_covered_routes"] = counts["n_newly_covered_routes"]
            row[f"{scenario}_{label}_additions_on_already_covered_routes"] = counts["n_additions_on_already_covered_routes"]
    return row


def _aadt(sites, attributions, config):
    rows = []
    draws = int(config["aadt_permutation_draws"])
    seed = int(config["aadt_permutation_seed"])
    for scenario in SCENARIOS:
        result = attributions[(scenario, "calibration")]
        by_id = {row["physical_edge_id"]: row for row in result["sites"]}
        usable = [site for site in sites if site.get("bike_aadt") is not None]
        aadt = [float(site["bike_aadt"]) for site in usable]
        for metric in ("traversal_fraction", "unique_fraction", "shapley"):
            values = [float(by_id[site["physical_edge_id"]][metric]) for site in usable]
            rho = spearman_rho(aadt, values) if len(set(aadt)) > 1 and len(set(values)) > 1 else None
            p_value = None if rho is None else permutation_pvalue(aadt, values, rho, draws=draws, seed=seed)
            rows.append(
                {
                    "scenario": scenario,
                    "split": "calibration",
                    "metric": metric,
                    "n": len(usable),
                    "n_missing_aadt": len(sites) - len(usable),
                    "spearman_rho": rho,
                    "permutation_p": p_value,
                }
            )
    return rows


def _write_sites(sites, attributions, names) -> None:
    rows = []
    for site in sites:
        for scenario in SCENARIOS:
            for split in SPLITS:
                metrics = next(
                    row
                    for row in attributions[(scenario, split)]["sites"]
                    if row["physical_edge_id"] == site["physical_edge_id"]
                )
                rows.append(
                    {
                        "scenario": scenario,
                        "split": split,
                        "physical_edge_id": site["physical_edge_id"],
                        "street": site.get("street") or "",
                        "description": site.get("description") or "",
                        "osm_name": names.get(site["physical_edge_id"], ""),
                        "count_type": site.get("count_type") or "",
                        "year": site.get("year") or "",
                        "bike_aadt": site.get("bike_aadt"),
                        **metrics,
                    }
                )
    _write_dicts("site_contributions.csv", rows)


def _write_multiplicity(attributions) -> None:
    rows = []
    for (scenario, split), result in attributions.items():
        histogram = result["multiplicity"]
        n_routes = result["n_routes"]
        buckets = {
            "0": histogram.get(0, 0),
            "1": histogram.get(1, 0),
            "2": histogram.get(2, 0),
            "3+": sum(count for size, count in histogram.items() if size >= 3),
        }
        for bucket, count in buckets.items():
            rows.append(
                {
                    "scenario": scenario,
                    "split": split,
                    "bucket": bucket,
                    "n_routes": count,
                    "share": count / n_routes,
                    "coverage": result["coverage"],
                    "n_routes_total": n_routes,
                }
            )
    _write_dicts("coverage_multiplicity.csv", rows)


def _write_pairs(pairs, sites) -> None:
    labels = {row["physical_edge_id"]: row.get("street") or "" for row in sites}
    rows = []
    for (scenario, split), pair_rows in pairs.items():
        for pair in pair_rows:
            rows.append(
                {
                    "scenario": scenario,
                    "split": split,
                    "street_a": labels[pair["site_a"]],
                    "street_b": labels[pair["site_b"]],
                    **pair,
                }
            )
    _write_dicts("pairwise_overlap.csv", rows)


def _write_scenario(sites, attributions) -> None:
    rows = []
    for site in sites:
        row = {
            "physical_edge_id": site["physical_edge_id"],
            "street": site.get("street") or "",
            "description": site.get("description") or "",
            "bike_aadt": site.get("bike_aadt"),
        }
        for scenario in SCENARIOS:
            for split in SPLITS:
                metrics = next(
                    item
                    for item in attributions[(scenario, split)]["sites"]
                    if item["physical_edge_id"] == site["physical_edge_id"]
                )
                prefix = f"{scenario}_{split}"
                row[f"{prefix}_traversal_fraction"] = metrics["traversal_fraction"]
                row[f"{prefix}_unique_fraction"] = metrics["unique_fraction"]
                row[f"{prefix}_leave_one_out_pp"] = metrics["leave_one_out_pp"]
                row[f"{prefix}_shapley_pp"] = metrics["shapley_pp"]
                row[f"{prefix}_shared_routes"] = metrics["shared_routes"]
        rows.append(row)
    _rank(rows, "uniform_calibration_leave_one_out_pp", "uniform_calibration_unique_rank")
    _rank(rows, "commuter_proxy_calibration_leave_one_out_pp", "commuter_proxy_calibration_unique_rank")
    for row in rows:
        row["calibration_unique_rank_change"] = (
            row["commuter_proxy_calibration_unique_rank"] - row["uniform_calibration_unique_rank"]
        )
    _write_dicts("scenario_comparison.csv", rows)


def _rank(rows, source, target) -> None:
    ordered = sorted(rows, key=lambda row: (-float(row[source]), row["physical_edge_id"]))
    for rank, row in enumerate(ordered, start=1):
        row[target] = rank


def _summary(sites, attributions, pairs, addition_rows, aadt_rows, runtime) -> dict:
    highlights = {}
    for scenario in SCENARIOS:
        calibration = attributions[(scenario, "calibration")]
        ordered = sorted(calibration["sites"], key=lambda row: (-row["leave_one_out"], row["physical_edge_id"]))
        labels = {row["physical_edge_id"]: row.get("street") or "" for row in sites}
        top_pairs = sorted(
            pairs[(scenario, "calibration")],
            key=lambda row: (-row["n_both"], -(row["jaccard"] or 0), row["site_a"], row["site_b"]),
        )[:8]
        highlights[scenario] = {
            "coverage_calibration": calibration["coverage"],
            "coverage_heldout": attributions[(scenario, "evaluation")]["coverage"],
            "multiplicity_calibration": attributions[(scenario, "calibration")]["multiplicity"],
            "multiplicity_heldout": attributions[(scenario, "evaluation")]["multiplicity"],
            "highest_unique": [
                {"street": labels[row["physical_edge_id"]], "id": row["physical_edge_id"], "leave_one_out_pp": row["leave_one_out_pp"], "shapley_pp": row["shapley_pp"], "traversal_fraction": row["traversal_fraction"]}
                for row in ordered[:5]
            ],
            "zero_unique": [
                {"street": labels[row["physical_edge_id"]], "id": row["physical_edge_id"], "traversal_fraction": row["traversal_fraction"], "shapley_pp": row["shapley_pp"]}
                for row in ordered
                if row["leave_one_out"] == 0
            ],
            "top_pairs": [
                {"street_a": labels[row["site_a"]], "street_b": labels[row["site_b"]], "n_both": row["n_both"], "jaccard": row["jaccard"]}
                for row in top_pairs
            ],
        }
    return {
        "routes_are_simulated": True,
        "held_out_used_for_selection": False,
        "removal_recommendation": False,
        "n_sites": 26,
        "baseline_matches_saved": True,
        "shapley_sums_to_coverage": True,
        "unique_equals_leave_one_out": True,
        "sites_in_candidate_universe": True,
        "runtime_seconds": runtime,
        "rank_association": _rank_association(attributions),
        "scenarios": highlights,
        "additions": addition_rows,
        "aadt": aadt_rows,
    }


def _rank_association(attributions) -> dict[str, float | None]:
    def column(scenario, field):
        return [float(row[field]) for row in attributions[(scenario, "calibration")]["sites"]]

    uniform_loo = column("uniform", "leave_one_out")
    commuter_loo = column("commuter_proxy", "leave_one_out")
    return {
        "leave_one_out_between_scenarios": spearman_rho(uniform_loo, commuter_loo),
        "shapley_between_scenarios": spearman_rho(column("uniform", "shapley"), column("commuter_proxy", "shapley")),
        "uniform_traversal_vs_unique": spearman_rho(column("uniform", "traversal_fraction"), column("uniform", "unique_fraction")),
        "commuter_traversal_vs_unique": spearman_rho(
            column("commuter_proxy", "traversal_fraction"), column("commuter_proxy", "unique_fraction")
        ),
    }


def _figures(lines, sites, attributions, pairs, cumulative_rows) -> None:
    streets = _streets()
    ids = [row["physical_edge_id"] for row in sites]
    labels = _labels(sites)

    def values(scenario, field):
        by_id = {row["physical_edge_id"]: row for row in attributions[(scenario, "calibration")]["sites"]}
        return {edge_id: float(by_id[edge_id][field]) for edge_id in ids}

    figure_site_values(
        lines,
        streets,
        (("Uniform calibration", values("uniform", "leave_one_out_pp")), ("Commuter proxy calibration", values("commuter_proxy", "leave_one_out_pp"))),
        OUTPUT / "figure1_leave_one_out.png",
        colorbar="Leave-one-out (percentage points)",
        title="Unique modeled-route contribution of the 26 sites",
    )
    figure_site_values(
        lines,
        streets,
        (("Uniform calibration", values("uniform", "shapley_pp")), ("Commuter proxy calibration", values("commuter_proxy", "shapley_pp"))),
        OUTPUT / "figure2_shapley.png",
        colorbar="Shapley attribution (percentage points)",
        title="Shapley modeled-route attribution",
    )
    multiplicity = []
    for (scenario, split), result in attributions.items():
        histogram = result["multiplicity"]
        buckets = {"0": histogram.get(0, 0), "1": histogram.get(1, 0), "2": histogram.get(2, 0), "3+": sum(count for size, count in histogram.items() if size >= 3)}
        for bucket, count in buckets.items():
            multiplicity.append({"scenario": scenario, "split": split, "bucket": bucket, "share": count / result["n_routes"]})
    figure_multiplicity(multiplicity, OUTPUT / "figure3_multiplicity.png")
    flat = []
    for (scenario, split), result in attributions.items():
        for row in result["sites"]:
            flat.append({"scenario": scenario, "split": split, **row})
    figure_three_metrics(flat, OUTPUT / "figure4_three_metrics.png")
    figure_cumulative(cumulative_rows, OUTPUT / "figure5_cumulative.png")
    matrices = []
    for scenario, title in (("uniform", "Uniform calibration"), ("commuter_proxy", "Commuter proxy calibration")):
        lookup = {(row["site_a"], row["site_b"]): row["jaccard"] for row in pairs[(scenario, "calibration")]}
        matrix = []
        for left in ids:
            matrix.append([
                float("nan") if left == right else float(lookup.get((left, right), lookup.get((right, left))) or 0.0)
                for right in ids
            ])
        matrices.append((title, matrix))
    figure_overlap([labels[edge_id] for edge_id in ids], matrices, OUTPUT / "figure6_overlap.png")


def _labels(sites) -> dict[str, str]:
    counts: dict[str, int] = {}
    for site in sites:
        name = site.get("street") or site["physical_edge_id"]
        counts[name] = counts.get(name, 0) + 1
    labels = {}
    for site in sites:
        name = site.get("street") or site["physical_edge_id"]
        if counts[name] > 1:
            detail = site.get("description") or site["physical_edge_id"][-12:]
            labels[site["physical_edge_id"]] = f"{name} ({detail})"[:42]
        else:
            labels[site["physical_edge_id"]] = name
    return labels


def _streets() -> list:
    path = ROOT / "outputs/standout/context_basemap.json"
    if not path.is_file():
        return []
    layer = json.loads(path.read_text(encoding="utf-8"))["layers"].get("streets") or {}
    lines = []
    for feature in layer.get("features") or []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "LineString":
            lines.append(coordinates)
        elif geometry.get("type") == "MultiLineString":
            lines.extend(coordinates)
    return lines


def _write_dicts(name: str, rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError(f"{name} has no rows")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with (OUTPUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
