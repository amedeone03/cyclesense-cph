"""Resample simulated calibration routes and record which counters stay selected.

The draws use the saved M1 network and the existing route generator. They are
not written back into the canonical route file. Held-out routes are scored
after selection.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from pathlib import Path

import yaml

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.coverage import evaluate_coverage
from cyclesense.network import node_coordinates, project_lonlat
from cyclesense.placement import select_greedy
from cyclesense.placement_stability import (
    CANONICAL_OUTPUTS,
    assert_calibration_only,
    assert_disjoint_seed_blocks,
    descriptive_correlation,
    frequency_counts,
    jaccard,
    overlap_summary,
    pairwise_overlaps,
    rank_summaries,
    replicate_seeds,
    require_saved_selection,
    sample_dispersion,
    selection_entropy,
    selection_frequencies,
)
from cyclesense.placement_stability_plots import (
    figure_canonical,
    figure_coverage,
    figure_frequency_histograms,
    figure_heatmap,
    figure_jaccard,
    figure_overlap_vs_heldout,
    physical_lines,
    write_frequency_map,
)
from cyclesense.robust_placement import assign_weights
from cyclesense.route_choice import (
    alternative_route,
    build_adjacency,
    edge_cost_factors,
    eligible_ids,
    shortest_path_from_nodes,
)
from cyclesense.routes import generate_modeled_routes

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "placement_stability"


def main() -> None:
    before = _fingerprint()
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))
    study = config["placement_stability"]
    simulation = config["simulation"]
    seeds = replicate_seeds(int(study["replicate_seed_start"]), int(study["n_replicates"]))
    perturbation = _perturbation_seeds(study, config["robust_placement"], len(seeds))
    assert_disjoint_seed_blocks(seeds, perturbation)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_config(study, seeds, perturbation)
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("M1 artifacts are missing. This study does not rebuild them.")
    eligible, names = _candidates(artifacts["candidates"])
    heldout = _heldout(artifacts["routes"])
    print("Loading the saved routing graph", flush=True)
    graph, coordinates, anchor_xy = _network(artifacts, config)
    adjacency = build_adjacency(graph) if perturbation else None
    draws: dict[str, list[dict[str, set[str]]]] = {scenario: [] for scenario in study["scenarios"]}
    paths: dict[str, list[list[dict]]] = {scenario: [] for scenario in study["scenarios"]}
    diagnostics = []
    for index, seed in enumerate(seeds):
        print(f"Replicate {index + 1}/{len(seeds)} seed {seed}", flush=True)
        for scenario in study["scenarios"]:
            started = time.perf_counter()
            routes, stats = generate_modeled_routes(
                graph,
                coordinates,
                set(eligible),
                scenario=scenario,
                n_calibration=int(study["calibration_routes"]),
                n_evaluation=0,
                calibration_seed=seed,
                evaluation_seed=seed + int(study["unused_evaluation_offset"]),
                min_distance_m=float(simulation["min_od_distance_m"]),
                max_distance_m=float(simulation["max_od_distance_m"]),
                min_eligible_edges=int(simulation["min_eligible_edges"]),
                anchor_xy=anchor_xy if scenario == "commuter_proxy" else None,
                distance_floor_m=float(simulation["commuter_proxy"]["distance_floor_m"]),
                max_attempts_factor=int(simulation["max_attempts_factor"]),
            )
            assert_calibration_only([route.split for route in routes])
            if len(routes) != int(study["calibration_routes"]):
                raise SystemExit(f"{scenario} seed {seed} kept {len(routes)} routes")
            draws[scenario].append({route.route_id: set(route.eligible_edge_ids) for route in routes})
            paths[scenario].append([
                {
                    "route_id": route.route_id,
                    "od_id": f"{route.origin_node}:{route.destination_node}",
                    "node_ids": route.node_ids,
                    "eligible": set(route.eligible_edge_ids),
                }
                for route in routes
            ])
            kept = stats["calibration"]
            diagnostics.append({
                "scenario": scenario,
                "replicate": index,
                "seed": seed,
                "n_routes": len(routes),
                "n_unique_od": len({(route.origin_node, route.destination_node) for route in routes}),
                "n_unique_paths": len({route.physical_edge_ids for route in routes}),
                "attempts": kept["attempts"],
                "seconds": time.perf_counter() - started,
            })
    placements, coverage_rows = _place(study, draws, paths, eligible, heldout, graph, adjacency, perturbation, config)
    frequencies = _frequencies(placements, eligible)
    overlaps = _overlaps(placements, coverage_rows)
    _write_tables(diagnostics, placements, frequencies, overlaps, coverage_rows, names)
    _figures(study, graph, names, frequencies, overlaps, coverage_rows, eligible)
    summary = _summary(study, seeds, frequencies, overlaps, coverage_rows, len(eligible), names)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if _fingerprint() != before:
        raise SystemExit("placement stability changed a canonical artifact")
    print(summary["headline"], flush=True)


def _place(study, draws, paths, eligible, heldout, graph, adjacency, perturbation, config):
    placements = []
    coverage_rows = []
    scenarios = list(study["scenarios"])
    for scenario in scenarios:
        canonical = {
            budget: _saved_edges(ROOT / "outputs/m2/results.csv", scenario=scenario, method="greedy", k=budget)
            for budget in study["budgets"]
        }
        for budget, edges in canonical.items():
            require_saved_selection(edges, eligible, int(budget))
        for index, routes in enumerate(draws[scenario]):
            weights = _equal(routes)
            for budget in study["budgets"]:
                _one_placement(
                    placements, coverage_rows, "greedy", scenario, index, int(study["replicate_seed_start"]) + index,
                    int(budget), eligible, routes, weights, heldout, canonical[int(budget)],
                )
    pooled_canonical = _robust_edges("pooled_shortest", int(study["pooled_k"]))
    require_saved_selection(pooled_canonical, eligible, int(study["pooled_k"]))
    for index in range(len(draws[scenarios[0]])):
        routes, weights = _pooled(draws, scenarios, index)
        _one_placement(
            placements, coverage_rows, "pooled_shortest", "pooled", index,
            int(study["replicate_seed_start"]) + index, int(study["pooled_k"]),
            eligible, routes, weights, heldout, pooled_canonical,
        )
    if perturbation and adjacency is not None:
        robust_cfg = config["robust_placement"]
        route_canonical = _robust_edges("robust_pooled", int(study["pooled_k"]))
        require_saved_selection(route_canonical, eligible, int(study["pooled_k"]))
        width = int(robust_cfg["training_n_seeds"])
        for index in range(len(paths[scenarios[0]])):
            print(f"  route-choice replicate {index + 1}", flush=True)
            routes, weights = _route_choice(
                paths, scenarios, index, graph, adjacency, set(eligible),
                perturbation[index * width:(index + 1) * width],
                float(robust_cfg["sigma"]),
                float(robust_cfg["training_detour_limit"]),
            )
            _one_placement(
                placements, coverage_rows, "route_choice", "pooled", index,
                int(study["replicate_seed_start"]) + index, int(study["pooled_k"]),
                eligible, routes, weights, heldout, route_canonical,
            )
    return placements, coverage_rows


def _one_placement(placements, coverage_rows, method, scenario, index, seed, budget, eligible, routes, weights, heldout, canonical):
    started = time.perf_counter()
    selected = tuple(select_greedy(eligible, routes, budget, weights))
    seconds = time.perf_counter() - started
    require_saved_selection(selected, eligible, budget)
    for rank, edge in enumerate(selected, start=1):
        placements.append({
            "method": method,
            "scenario": scenario,
            "replicate": index,
            "seed": seed,
            "k": budget,
            "rank": rank,
            "physical_edge_id": edge,
        })
    uniform = evaluate_coverage(heldout["uniform"], selected).coverage_fraction
    commuter = evaluate_coverage(heldout["commuter_proxy"], selected).coverage_fraction
    own = uniform if scenario == "uniform" else commuter if scenario == "commuter_proxy" else (uniform + commuter) / 2
    coverage_rows.append({
        "method": method,
        "scenario": scenario,
        "replicate": index,
        "seed": seed,
        "k": budget,
        "calibration_coverage": evaluate_coverage(routes, selected, weights).coverage_fraction,
        "heldout_coverage": own,
        "heldout_uniform": uniform,
        "heldout_commuter": commuter,
        "jaccard_with_canonical": jaccard(selected, canonical),
        "seconds": seconds,
        "n_routes": len(routes),
    })


def _pooled(draws, scenarios, index):
    routes = {}
    records = []
    for scenario in scenarios:
        for route_id, edges in draws[scenario][index].items():
            routes[route_id] = edges
            records.append({"scenario": scenario, "od_id": route_id, "role": "shortest", "route_key": route_id})
    return routes, assign_weights(records, scenarios=scenarios, include_alternatives=False)


def _route_choice(paths, scenarios, index, graph, adjacency, candidates, seeds, sigma, limit):
    grouped = {scenario: paths[scenario][index] for scenario in scenarios}
    records = []
    routes = {}
    for scenario, items in grouped.items():
        for item in items:
            key = f"{scenario}:{item['od_id']}:shortest"
            routes[key] = set(item["eligible"])
            records.append({"scenario": scenario, "od_id": item["od_id"], "role": "shortest", "route_key": key})
    prepared = {
        scenario: [(item, shortest_path_from_nodes(graph, item["node_ids"])) for item in items]
        for scenario, items in grouped.items()
    }
    for seed in seeds:
        factors = edge_cost_factors(adjacency, seed, sigma)
        for scenario, items in prepared.items():
            for item, original in items:
                decision = alternative_route(adjacency, original, factors, limit)
                key = f"{scenario}:{item['od_id']}:alternative:{seed}"
                routes[key] = set(eligible_ids(decision.path.physical_edge_ids, candidates))
                records.append({"scenario": scenario, "od_id": item["od_id"], "role": "alternative", "route_key": key})
    return routes, assign_weights(records, scenarios=scenarios, include_alternatives=True)


def _frequencies(placements, eligible):
    grouped: dict[tuple, list[list[str]]] = {}
    for row in placements:
        key = (row["method"], row["scenario"], row["k"])
        grouped.setdefault(key, {})
        grouped[key].setdefault(row["replicate"], []).append(row["physical_edge_id"])
    rows = []
    for (method, scenario, budget), replicates in grouped.items():
        orders = [replicates[index] for index in sorted(replicates)]
        frequencies = selection_frequencies(orders, eligible)
        ranks = rank_summaries(orders)
        for edge, frequency in frequencies.items():
            rank = ranks[edge]
            rows.append({
                "method": method,
                "scenario": scenario,
                "k": budget,
                "physical_edge_id": edge,
                "selection_count": round(frequency * len(orders)),
                "selection_frequency": frequency,
                "mean_rank": rank["mean_rank"],
                "rank_std": "" if rank["rank_std"] is None else rank["rank_std"],
                "times_first": rank["times_first"],
            })
    return rows


def _overlaps(placements, coverage_rows):
    grouped: dict[tuple, dict[int, list[str]]] = {}
    for row in placements:
        key = (row["method"], row["scenario"], row["k"])
        grouped.setdefault(key, {}).setdefault(row["replicate"], []).append(row["physical_edge_id"])
    heldout = {
        (row["method"], row["scenario"], row["k"], row["replicate"]): row["heldout_coverage"]
        for row in coverage_rows
    }
    rows = []
    for key, replicates in grouped.items():
        orders = [replicates[index] for index in sorted(replicates)]
        for pair in pairwise_overlaps(orders):
            left = heldout[(*key, pair["replicate_a"])]
            right = heldout[(*key, pair["replicate_b"])]
            rows.append({
                "method": key[0],
                "scenario": key[1],
                "k": key[2],
                "replicate_a": pair["replicate_a"],
                "replicate_b": pair["replicate_b"],
                "shared": pair["shared"],
                "union": pair["union"],
                "jaccard": pair["jaccard"],
                "heldout_abs_diff": abs(left - right),
            })
    return rows


def _figures(study, graph, names, frequencies, overlaps, coverage_rows, eligible):
    lines = physical_lines(graph)
    basemap = _basemap()
    n_replicates = int(study["n_replicates"])
    for method, scenario, budget, stem, title in (
        ("greedy", "uniform", 10, "figure1_uniform_k10", "Uniform greedy, K=10"),
        ("greedy", "commuter_proxy", 10, "figure1_commuter_k10", "Commuter-proxy greedy, K=10"),
        ("pooled_shortest", "pooled", 10, "figure1_pooled_k10", "Pooled shortest-path greedy, K=10"),
    ):
        subset = _freq_map(frequencies, method, scenario, budget)
        counts = {edge: round(value * n_replicates) for edge, value in subset.items()}
        figure_heatmap(lines, subset, OUTPUT / f"{stem}.png", title)
        write_frequency_map(graph, names, subset, counts, n_replicates, OUTPUT / f"{stem}.html", title, basemap)
    histogram_groups = []
    for scenario, budget in (("uniform", 10), ("uniform", 20), ("commuter_proxy", 10), ("commuter_proxy", 20)):
        values = list(_freq_map(frequencies, "greedy", scenario, budget).values())
        label = f"{'Uniform' if scenario == 'uniform' else 'Commuter'} K={budget}"
        histogram_groups.append((label, values, len(eligible) - len(values)))
    figure_frequency_histograms(histogram_groups, n_replicates, OUTPUT / "figure2_frequency_distribution.png")
    jaccard_groups = []
    scatter_groups = []
    for method, scenario, budget, label in _group_labels():
        pairs = [row for row in overlaps if row["method"] == method and row["scenario"] == scenario and int(row["k"]) == budget]
        if not pairs:
            continue
        jaccard_groups.append((label, [float(row["jaccard"]) for row in pairs]))
        if budget == 10:
            scatter_groups.append((label, [float(row["jaccard"]) for row in pairs], [float(row["heldout_abs_diff"]) for row in pairs]))
    figure_jaccard(jaccard_groups, OUTPUT / "figure3_pairwise_jaccard.png")
    coverage_plot = []
    for row in coverage_rows:
        coverage_plot.append({
            "label": _label(row["method"], row["scenario"], int(row["k"])),
            "calibration": row["calibration_coverage"],
            "heldout": row["heldout_coverage"],
        })
    figure_coverage(coverage_plot, OUTPUT / "figure4_coverage_variation.png")
    canonical_groups = []
    for scenario, title in (("uniform", "Uniform canonical K=10"), ("commuter_proxy", "Commuter canonical K=10")):
        saved = _saved_edges(ROOT / "outputs/m2/results.csv", scenario=scenario, method="greedy", k=10)
        freqs = _freq_map(frequencies, "greedy", scenario, 10)
        labels = []
        used = {}
        for edge in saved:
            name = names.get(edge) or "(unnamed)"
            used[name] = used.get(name, 0) + 1
            labels.append((name, edge, float(freqs.get(edge, 0.0))))
        rows = []
        for name, edge, frequency in labels:
            text = name if used[name] == 1 else f"{name} ({edge.rsplit(':', 1)[-1]})"
            rows.append((text, frequency))
        canonical_groups.append((title, rows))
    figure_canonical(canonical_groups, OUTPUT / "figure5_canonical_frequency.png")
    figure_overlap_vs_heldout(scatter_groups, OUTPUT / "figure6_overlap_vs_heldout.png")


def _summary(study, seeds, frequencies, overlaps, coverage_rows, n_candidates, names):
    groups = []
    present = {(row["method"], row["scenario"], int(row["k"])) for row in coverage_rows}
    for method, scenario, budget, label in _group_labels():
        if (method, scenario, budget) not in present:
            continue
        freqs = _freq_map(frequencies, method, scenario, budget)
        bands = frequency_counts(freqs, n_candidates)
        pairs = [row for row in overlaps if row["method"] == method and row["scenario"] == scenario and int(row["k"]) == budget]
        overlap = overlap_summary(pairs)
        own = [row for row in coverage_rows if row["method"] == method and row["scenario"] == scenario and int(row["k"]) == budget]
        calibration = sample_dispersion([row["calibration_coverage"] for row in own])
        heldout = sample_dispersion([row["heldout_coverage"] for row in own])
        correlation = descriptive_correlation(
            [float(row["jaccard"]) for row in pairs],
            [float(row["heldout_abs_diff"]) for row in pairs],
        )
        groups.append({
            "label": label,
            "method": method,
            "scenario": scenario,
            "k": budget,
            **bands,
            **overlap,
            "entropy": selection_entropy(freqs, budget),
            "calibration_mean": calibration["mean"],
            "calibration_std": calibration["std"],
            "calibration_min": calibration["min"],
            "calibration_max": calibration["max"],
            "heldout_mean": heldout["mean"],
            "heldout_std": heldout["std"],
            "heldout_min": heldout["min"],
            "heldout_max": heldout["max"],
            "overlap_heldout_correlation": "" if correlation is None else correlation,
            "canonical_mean_jaccard": _mean(row["jaccard_with_canonical"] for row in own),
        })
    _csv(OUTPUT / "aggregate_summary.csv", groups)
    uniform = next(row for row in groups if row["method"] == "greedy" and row["scenario"] == "uniform" and row["k"] == 10)
    always = int(uniform["n_always"])
    word = "segment appears" if always == 1 else "segments appear"
    headline = (
        f"Uniform K=10 selects {uniform['n_ever_selected']} distinct segments across {len(seeds)} draws; "
        f"{always} {word} in every draw. Mean pairwise Jaccard is {uniform['mean_jaccard']:.2f}."
    )
    return {
        "routes_are_simulated": True,
        "held_out_used_for_selection": False,
        "replicates_are_independent_od_draws": True,
        "pairwise_overlaps_are_not_independent": True,
        "selection_frequency_is_not_cyclist_demand": True,
        "n_replicates": len(seeds),
        "calibration_routes": int(study["calibration_routes"]),
        "seeds": list(seeds),
        "top_segments": _top_segments(frequencies, names),
        "groups": groups,
        "headline": headline,
    }


def _top_segments(frequencies, names):
    rows = []
    for method, scenario, budget in (("greedy", "uniform", 10), ("greedy", "commuter_proxy", 10), ("pooled_shortest", "pooled", 10)):
        ranked = sorted(
            (row for row in frequencies if row["method"] == method and row["scenario"] == scenario and int(row["k"]) == budget),
            key=lambda row: (-float(row["selection_frequency"]), row["physical_edge_id"]),
        )
        rows.append({
            "method": method,
            "scenario": scenario,
            "k": budget,
            "segments": [
                {
                    "physical_edge_id": row["physical_edge_id"],
                    "street_name": names.get(row["physical_edge_id"], ""),
                    "selection_frequency": float(row["selection_frequency"]),
                    "mean_rank": row["mean_rank"],
                }
                for row in ranked[:12]
            ],
        })
    return rows


def _group_labels():
    return (
        ("greedy", "uniform", 10, "Uniform K=10"),
        ("greedy", "uniform", 20, "Uniform K=20"),
        ("greedy", "commuter_proxy", 10, "Commuter K=10"),
        ("greedy", "commuter_proxy", 20, "Commuter K=20"),
        ("pooled_shortest", "pooled", 10, "Pooled K=10"),
        ("route_choice", "pooled", 10, "Route choice K=10"),
    )


def _label(method, scenario, budget):
    for item in _group_labels():
        if item[0] == method and item[1] == scenario and item[2] == budget:
            return item[3]
    return f"{method} {scenario} K={budget}"


def _freq_map(rows, method, scenario, budget):
    return {
        row["physical_edge_id"]: float(row["selection_frequency"])
        for row in rows
        if row["method"] == method and row["scenario"] == scenario and int(row["k"]) == budget
    }


def _write_tables(diagnostics, placements, frequencies, overlaps, coverage_rows, names):
    for row in frequencies:
        row["street_name"] = names.get(row["physical_edge_id"], "")
    for row in placements:
        row["street_name"] = names.get(row["physical_edge_id"], "")
    _csv(OUTPUT / "sample_diagnostics.csv", diagnostics)
    _csv(OUTPUT / "replicate_placements.csv", placements)
    _csv(OUTPUT / "segment_frequencies.csv", frequencies)
    _csv(OUTPUT / "pairwise_overlap.csv", overlaps)
    _csv(OUTPUT / "replicate_coverage.csv", coverage_rows)


def _candidates(path: Path):
    names = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            names[row["physical_edge_id"]] = row.get("name") or ""
    return sorted(names), names


def _heldout(path: Path):
    routes = {"uniform": {}, "commuter_proxy": {}}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["split"] != "evaluation":
                continue
            routes[row["scenario"]][row["route_id"]] = set(filter(None, row["eligible_edge_ids"].split("|")))
    return routes


def _network(artifacts, config):
    import osmnx as ox

    routing = ox.load_graphml(artifacts["routing_wgs84"])
    projected = ox.load_graphml(artifacts["routing_projected"])
    coordinates = node_coordinates(projected)
    if set(coordinates) != {int(node) for node in routing.nodes}:
        raise SystemExit("projected node ids do not match the WGS84 routing graph")
    anchor_cfg = config["simulation"]["commuter_proxy"]
    anchor_xy = project_lonlat(float(anchor_cfg["anchor_lon"]), float(anchor_cfg["anchor_lat"]), projected.graph["crs"])
    return routing, coordinates, anchor_xy


def _basemap():
    cache = ROOT / "outputs" / "m1" / "context_basemap.json"
    if not cache.is_file():
        cache = ROOT / "outputs" / "standout" / "context_basemap.json"
    if not cache.is_file():
        return None
    return json.loads(cache.read_text(encoding="utf-8"))


def _perturbation_seeds(study, robust, n_replicates):
    if not study.get("include_route_choice", False):
        return ()
    width = int(robust["training_n_seeds"])
    start = int(study["route_choice_seed_start"])
    seeds = tuple(range(start, start + n_replicates * width))
    blocked = set(range(int(robust["training_seed_start"]), int(robust["training_seed_start"]) + int(robust["training_n_seeds"])))
    blocked.update(range(int(robust["evaluation_seed_start"]), int(robust["evaluation_seed_start"]) + int(robust["evaluation_n_seeds"])))
    blocked.update(range(int(robust["reference_seed_start"]), int(robust["reference_seed_start"]) + int(robust["reference_n_seeds"])))
    if set(seeds) & blocked:
        raise SystemExit("route-choice stability seeds collide with M5.9 seeds")
    return seeds


def _equal(routes):
    weight = 1.0 / len(routes)
    return {route_id: weight for route_id in routes}


def _saved_edges(path: Path, **filters):
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if all(str(row[key]) == str(value) for key, value in filters.items()):
                return row["selected_edges"].split("|")
    raise KeyError(filters)


def _robust_edges(method: str, budget: int):
    edges = []
    with (ROOT / "outputs/robust_placement/placements.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == method and int(row["k"]) == budget:
                edges.append((int(row["rank"]), row["physical_edge_id"]))
    if len(edges) != budget:
        raise KeyError((method, budget))
    return [edge for _rank, edge in sorted(edges)]


def _write_config(study, seeds, perturbation):
    payload = {
        "settings": study,
        "replicate_seeds": list(seeds),
        "route_choice_seeds": list(perturbation),
        "n_evaluation_routes_generated": 0,
        "held_out_used_for_selection": False,
        "canonical_m1_routes_are_not_overwritten": True,
        "replicates_are_independent_od_draws": True,
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


def _mean(values):
    values = list(values)
    return sum(values) / len(values)


def _fingerprint():
    hashes = {}
    for relative in CANONICAL_OUTPUTS:
        path = ROOT / relative
        if path.is_file():
            hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


if __name__ == "__main__":
    main()
