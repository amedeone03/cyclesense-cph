"""Run M3 route similarity, LSH, and Louvain on the saved M1 routes.

From the repository root, with the analysis extra installed:

    python scripts/run_m3.py

Calibration routes form the similarity graph. Held-out routes are assigned
afterwards and are not used to build signatures, choose bands, or refit
Louvain. Canonical M1 and M2 files are only read.

Outputs are written under outputs/m3/. Similarities are properties of
simulated routes, not observed bicycle trips.
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
from cyclesense.communities import (
    assign_heldout,
    community_medoid,
    detect_communities,
    graph_statistics,
    grouped_pair_recall,
    pair_agreement,
    shared_edges,
    similarity_graph,
)
from cyclesense.community_map import write_community_map
from cyclesense.community_plots import (
    plot_community_sizes,
    plot_graph_statistics,
    plot_lsh_tradeoff,
    plot_scalability,
    plot_similarity_distribution,
)
from cyclesense.interactive import _latlon
from cyclesense.minhash import (
    BANDINGS,
    build_lsh_buckets,
    build_signatures,
    choose_operating_point,
    query_lsh_pairs,
    retrieval_metrics,
)
from cyclesense.similarity import jaccard_similarity, pairwise_jaccard, similarity_distribution


def _timed(function: Any, *args: Any) -> tuple[Any, float, float]:
    tracemalloc.start()
    started = time.perf_counter()
    value = function(*args)
    elapsed = time.perf_counter() - started
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, elapsed, peak / 1_000_000


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _load_splits(path: Path) -> tuple[dict[str, dict[str, dict[str, set[str]]]], dict[str, list[int]]]:
    grouped: dict[str, dict[str, dict[str, set[str]]]] = defaultdict(lambda: defaultdict(dict))
    nodes: dict[str, list[int]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            edges = {edge for edge in row["physical_edge_ids"].split("|") if edge}
            grouped[row["scenario"]][row["split"]][row["route_id"]] = edges
            if row["split"] == "calibration" and row["node_ids"]:
                nodes[row["route_id"]] = [int(node) for node in row["node_ids"].split("|") if node]
    return grouped, nodes


def _candidate_similarities(
    candidates: set[tuple[int, int]],
    route_sets: list[set[str]],
) -> dict[tuple[int, int], float]:
    return {
        pair: jaccard_similarity(route_sets[pair[0]], route_sets[pair[1]])
        for pair in candidates
    }


def _exact_above(route_sets: list[set[str]], threshold: float) -> tuple[int, int]:
    pairs = 0
    above = 0
    for index, left in enumerate(route_sets):
        for right in route_sets[index + 1 :]:
            pairs += 1
            if jaccard_similarity(left, right) >= threshold:
                above += 1
    return pairs, above


def _route_line(graph: Any, node_ids: list[int]) -> list[tuple[float, float]]:
    line: list[tuple[float, float]] = []
    for node_id in node_ids:
        point = _latlon(graph, node_id)
        if point is None:
            return []
        if not line or line[-1] != point:
            line.append(point)
    return line


def _shape(sizes: list[int], n_routes: int) -> str:
    if not sizes or n_routes == 0:
        return "no communities"
    largest = max(sizes)
    singletons = sum(1 for size in sizes if size == 1)
    if largest >= 0.8 * n_routes:
        return "collapsed"
    if largest < 0.05 * n_routes or singletons >= 0.8 * n_routes:
        return "fragmented"
    return "mixed"


def _scalability(paths: dict[str, Path], config: dict[str, Any], operating: dict[str, Any]) -> list[dict[str, Any]]:
    import osmnx as ox

    from cyclesense.network import node_coordinates
    from cyclesense.routes import generate_modeled_routes

    simulation = config["simulation"]
    similarity = config["similarity"]
    sizes = [int(size) for size in similarity["scalability_sizes"]]
    seed = int(similarity["scalability_seed"])
    requested = max(sizes)
    routing = ox.load_graphml(paths["routing_wgs84"])
    projected = ox.load_graphml(paths["routing_projected"])
    coordinates = node_coordinates(projected)
    candidate_ids = {
        row["physical_edge_id"]
        for row in csv.DictReader(paths["candidates"].open(encoding="utf-8"))
    }
    started = time.perf_counter()
    generated, stats = generate_modeled_routes(
        routing,
        coordinates,
        candidate_ids,
        scenario=str(similarity.get("scalability_scenario", "uniform")),
        n_calibration=requested,
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
    print(
        f"scalability sample kept {len(route_sets)} of {requested} "
        f"in {generation_seconds:.1f}s (routing excluded from the comparison)",
        flush=True,
    )
    num_perm = int(operating["num_perm"])
    bands = int(operating["bands"])
    rows_per_band = int(operating["rows_per_band"])
    threshold = float(operating["threshold"])
    measured = []
    for size in sizes:
        if size > len(route_sets):
            continue
        subset = route_sets[:size]
        (_counts, exact_seconds, exact_mb) = _timed(_exact_above, subset, threshold)
        signatures, signature_seconds, signature_mb = _timed(build_signatures, subset, num_perm, seed)
        buckets, index_seconds, index_mb = _timed(build_lsh_buckets, signatures, bands, rows_per_band)
        candidates, query_seconds, query_mb = _timed(
            query_lsh_pairs, signatures, buckets, bands, rows_per_band
        )
        verified, verify_seconds, verify_mb = _timed(_candidate_similarities, candidates, subset)
        n_above = _counts[1]
        n_verified = sum(1 for similarity in verified.values() if similarity >= threshold)
        measured.append(
            {
                "n_routes": size,
                "n_generated": len(route_sets),
                "generation_seconds": generation_seconds,
                "generation_kept": int(stats["calibration"]["kept"]),
                "exact_seconds": exact_seconds,
                "exact_peak_mb": exact_mb,
                "n_pairs_at_or_above_threshold": n_above,
                "lsh_preprocess_seconds": signature_seconds + index_seconds,
                "lsh_query_seconds": query_seconds,
                "lsh_verify_seconds": verify_seconds,
                "lsh_preprocess_peak_mb": max(signature_mb, index_mb),
                "lsh_query_peak_mb": query_mb,
                "n_candidates": len(candidates),
                "recall": (n_verified / n_above) if n_above else None,
                "precision": (n_verified / len(candidates)) if candidates else None,
                "num_perm": num_perm,
                "bands": bands,
                "rows_per_band": rows_per_band,
                "threshold": threshold,
                "verify_peak_mb": verify_mb,
            }
        )
        print(
            f"  n={size} exact={exact_seconds:.3f}s "
            f"lsh={signature_seconds + index_seconds + query_seconds:.3f}s "
            f"candidates={len(candidates)} recall={measured[-1]['recall']}",
            flush=True,
        )
    return measured


def main() -> None:
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit("No validated M1 artifacts. Run python scripts/run_m1.py first.")
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    similarity_cfg = config["similarity"]
    graph_thresholds = [float(value) for value in similarity_cfg["graph_thresholds"]]
    retrieval_thresholds = [float(value) for value in similarity_cfg["retrieval_thresholds"]]
    primary = float(similarity_cfg["approximate_jaccard_threshold"])
    seeds = [int(seed) for seed in similarity_cfg["louvain_seeds"]]
    primary_seed = seeds[0]
    output_dir = ROOT / "outputs" / "m3"
    output_dir.mkdir(parents=True, exist_ok=True)

    grouped, node_paths = _load_splits(paths["routes"])
    names = {
        row["physical_edge_id"]: row.get("name") or ""
        for row in csv.DictReader(paths["candidates"].open(encoding="utf-8"))
    }
    scenarios = [scenario for scenario in config["simulation"]["scenarios"] if scenario in grouped]

    distribution_rows = []
    threshold_rows = []
    lsh_rows = []
    graph_rows = []
    community_rows = []
    stability_rows = []
    heldout_rows = []
    assignment_rows = []
    corridor_rows = []
    distributions: dict[str, dict[str, Any]] = {}
    labels_by_key: dict[tuple[str, float, int], dict[str, int]] = {}
    sizes_primary: dict[str, list[int]] = {}
    operating_by_scenario: dict[str, dict[str, Any]] = {}
    acceptance: list[str] = []

    for scenario in scenarios:
        calibration = grouped[scenario]["calibration"]
        evaluation = grouped[scenario]["evaluation"]
        if set(calibration) & set(evaluation):
            acceptance.append(f"{scenario} reuses a route id across splits")
        ids = sorted(route_id for route_id, edges in calibration.items() if edges)
        route_sets = [calibration[route_id] for route_id in ids]
        print(f"{scenario}: calibration={len(ids)} evaluation={len(evaluation)}", flush=True)
        pairs, exact_seconds, exact_mb = _timed(pairwise_jaccard, {route_id: calibration[route_id] for route_id in ids})
        expected_pairs = len(ids) * (len(ids) - 1) // 2
        if len(pairs) != expected_pairs:
            acceptance.append(f"{scenario} pair count {len(pairs)} != {expected_pairs}")
        distribution = similarity_distribution(pairs, thresholds=tuple(sorted(set(graph_thresholds + [0.1, 0.2, 0.8, 0.9]))))
        distributions[scenario] = distribution
        distribution["runtime_s"] = exact_seconds
        distribution["peak_memory_mb"] = exact_mb
        print(
            f"  exact pairs={distribution['n_pairs']} mean={distribution['mean']:.4f} "
            f"time={exact_seconds:.3f}s memory={exact_mb:.2f}MB",
            flush=True,
        )
        width = float(distribution["bin_width"])
        for index, count in enumerate(distribution["bin_counts"]):
            distribution_rows.append(
                {"scenario": scenario, "bin_start": index * width, "bin_count": count}
            )
        for threshold, count in distribution["threshold_counts"].items():
            threshold_rows.append({"scenario": scenario, "threshold": threshold, "n_pairs": count})

        index_of = {route_id: index for index, route_id in enumerate(ids)}
        exact_lookup: dict[tuple[int, int], float] = {}
        for left, right, similarity in pairs:
            i_left, i_right = index_of[left], index_of[right]
            if i_left > i_right:
                i_left, i_right = i_right, i_left
            exact_lookup[(i_left, i_right)] = similarity

        scenario_lsh = []
        for num_perm, bandings in BANDINGS.items():
            signatures, signature_seconds, signature_mb = _timed(build_signatures, route_sets, num_perm, primary_seed)
            for bands, rows_per_band in bandings:
                buckets, index_seconds, index_mb = _timed(build_lsh_buckets, signatures, bands, rows_per_band)
                candidates, query_seconds, query_mb = _timed(
                    query_lsh_pairs, signatures, buckets, bands, rows_per_band
                )
                _checked, verify_seconds, _verify_mb = _timed(
                    _candidate_similarities, candidates, route_sets
                )
                del _checked, _verify_mb
                for threshold in retrieval_thresholds:
                    raw_metrics = retrieval_metrics(candidates, exact_lookup, threshold, len(ids))
                    row = {
                        "scenario": scenario,
                        "num_perm": num_perm,
                        "bands": bands,
                        "rows_per_band": rows_per_band,
                        "threshold": threshold,
                        "recall": raw_metrics["recall"],
                        "precision": raw_metrics["precision"],
                        "n_true_pairs": raw_metrics["n_true_pairs"],
                        "n_candidates": raw_metrics["n_candidates"],
                        "candidate_fraction": raw_metrics["candidate_fraction"],
                        "candidate_reduction": raw_metrics["candidate_reduction"],
                        "preprocess_seconds": signature_seconds + index_seconds,
                        "query_seconds": query_seconds,
                        "verify_seconds": verify_seconds,
                        "preprocess_peak_mb": max(signature_mb, index_mb),
                        "query_peak_mb": query_mb,
                    }
                    scenario_lsh.append(row)
                    lsh_rows.append(row)
                    print(
                        f"  lsh p={num_perm} b={bands} r={rows_per_band} t={threshold} "
                        f"recall={row['recall']} precision={row['precision']} "
                        f"candidates={row['n_candidates']}",
                        flush=True,
                    )
        operating = choose_operating_point(scenario_lsh, threshold=primary)
        operating_by_scenario[scenario] = {
            "num_perm": int(operating["num_perm"]),
            "bands": int(operating["bands"]),
            "rows_per_band": int(operating["rows_per_band"]),
            "threshold": primary,
            "recall": operating["recall"],
            "n_candidates": int(operating["n_candidates"]),
        }

        for threshold in graph_thresholds:
            graph = similarity_graph(ids, pairs, threshold)
            if set(graph.nodes) & set(evaluation):
                acceptance.append(f"{scenario} graph contains an evaluation route")
            stats = graph_statistics(graph)
            graph_rows.append({"scenario": scenario, "threshold": threshold, **stats})
            seed_labels = []
            for seed in seeds:
                labels, score, sizes = detect_communities(graph, seed)
                if set(labels) != set(ids):
                    acceptance.append(f"{scenario} Louvain missed a calibration route")
                labels_by_key[(scenario, threshold, seed)] = labels
                seed_labels.append(labels)
                community_rows.append(
                    {
                        "scenario": scenario,
                        "threshold": threshold,
                        "seed": seed,
                        "n_communities": len(sizes),
                        "n_communities_size_at_least_2": sum(1 for size in sizes if size >= 2),
                        "n_singletons": sum(1 for size in sizes if size == 1),
                        "largest": max(sizes) if sizes else 0,
                        "modularity": score,
                        "shape": _shape(sizes, len(ids)),
                    }
                )
                if threshold == primary and seed == primary_seed:
                    sizes_primary[scenario] = sizes
            for left_index, left_labels in enumerate(seed_labels):
                for right_index in range(left_index + 1, len(seed_labels)):
                    right_labels = seed_labels[right_index]
                    stability_rows.append(
                        {
                            "scenario": scenario,
                            "threshold": threshold,
                            "seed_a": seeds[left_index],
                            "seed_b": seeds[right_index],
                            "pair_agreement": pair_agreement(left_labels, right_labels),
                            "grouped_pair_recall_a_to_b": grouped_pair_recall(left_labels, right_labels),
                            "grouped_pair_recall_b_to_a": grouped_pair_recall(right_labels, left_labels),
                        }
                    )
            labels = labels_by_key[(scenario, threshold, primary_seed)]
            assignments = assign_heldout(evaluation, {route_id: calibration[route_id] for route_id in ids}, labels, threshold)
            counts = {status: sum(1 for row in assignments if row["status"] == status) for status in ("assigned", "ambiguous", "unassigned")}
            heldout_rows.append(
                {
                    "scenario": scenario,
                    "threshold": threshold,
                    "seed": primary_seed,
                    "n_evaluation": len(assignments),
                    **counts,
                    "assigned_fraction": counts["assigned"] / len(assignments) if assignments else 0.0,
                    "ambiguous_fraction": counts["ambiguous"] / len(assignments) if assignments else 0.0,
                }
            )
            if threshold == primary:
                for row in assignments:
                    assignment_rows.append({"scenario": scenario, "threshold": threshold, **row})
                members: dict[int, list[str]] = defaultdict(list)
                for route_id, community in labels.items():
                    members[community].append(route_id)
                for community, member_ids in members.items():
                    if len(member_ids) < 3:
                        continue
                    for edge_id, support in shared_edges(member_ids, calibration, minimum_support=0.5)[:8]:
                        corridor_rows.append(
                            {
                                "scenario": scenario,
                                "community": community,
                                "community_size": len(member_ids),
                                "physical_edge_id": edge_id,
                                "support": support,
                                "name": names.get(edge_id, ""),
                            }
                        )

    _write_csv(output_dir / "exact_distribution.csv", distribution_rows)
    _write_csv(output_dir / "exact_thresholds.csv", threshold_rows)
    _write_csv(output_dir / "lsh.csv", lsh_rows)
    _write_csv(output_dir / "graph_stats.csv", graph_rows)
    _write_csv(output_dir / "communities.csv", community_rows)
    _write_csv(output_dir / "stability.csv", stability_rows)
    _write_csv(output_dir / "heldout.csv", heldout_rows)
    _write_csv(output_dir / "heldout_routes.csv", assignment_rows)
    _write_csv(output_dir / "corridors.csv", corridor_rows)

    import osmnx as ox

    routing = ox.load_graphml(paths["routing_wgs84"])
    map_items = []
    for scenario in scenarios:
        labels = labels_by_key[(scenario, primary, primary_seed)]
        calibration = grouped[scenario]["calibration"]
        members = defaultdict(list)
        for route_id, community in labels.items():
            members[community].append(route_id)
        for community, member_ids in members.items():
            if len(member_ids) < 2:
                continue
            medoid, mean_similarity = community_medoid(member_ids, calibration)
            line = _route_line(routing, node_paths.get(medoid, []))
            if len(line) < 2:
                continue
            map_items.append(
                {
                    "scenario": scenario,
                    "community": community,
                    "size": len(member_ids),
                    "route_id": medoid,
                    "mean_similarity": mean_similarity,
                    "line": line,
                }
            )
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    box = metadata["boundary"]
    boundary = (float(box["west"]), float(box["south"]), float(box["east"]), float(box["north"]))
    pbf = Path(str(metadata.get("pbf_path") or ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"))
    if not pbf.is_file():
        pbf = ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"
    basemap = load_context_basemap(pbf, boundary, paths["summary"].parent / "context_basemap.json")
    map_path = output_dir / "communities.html"
    if map_items:
        map_path = write_community_map(
            map_items,
            map_path,
            boundary=boundary,
            basemap=basemap,
        )
    else:
        print("No community had a drawable representative route.", flush=True)

    uniform_operating = operating_by_scenario.get("uniform") or next(iter(operating_by_scenario.values()))
    print("scalability benchmark", flush=True)
    scaling_rows = _scalability(paths, config, uniform_operating)

    plot_similarity_distribution(distributions, output_dir / "similarity_distribution.png")
    plot_lsh_tradeoff(lsh_rows, output_dir / "lsh_tradeoff.png")
    plot_graph_statistics(graph_rows, output_dir / "graph_statistics.png")
    plot_community_sizes(sizes_primary, output_dir / "community_sizes.png")
    if scaling_rows:
        plot_scalability(scaling_rows, output_dir / "scalability.png")
    _write_csv(output_dir / "scalability.csv", scaling_rows)

    if acceptance:
        raise SystemExit("M3 acceptance failed: " + "; ".join(acceptance))
    summary = {
        "note": NOT_OBSERVED_DEMAND,
        "primary_threshold": primary,
        "louvain_seeds": seeds,
        "primary_seed": primary_seed,
        "distributions": {
            scenario: {
                **summary_row,
                "threshold_counts": {
                    str(threshold): count
                    for threshold, count in summary_row["threshold_counts"].items()
                },
            }
            for scenario, summary_row in distributions.items()
        },
        "operating_points": operating_by_scenario,
        "graph": graph_rows,
        "communities": community_rows,
        "stability": stability_rows,
        "heldout": heldout_rows,
        "scalability": scaling_rows,
        "acceptance_passed": True,
        "outputs": {
            "map": "outputs/m3/communities.html",
            "similarity_plot": "outputs/m3/similarity_distribution.png",
            "lsh_plot": "outputs/m3/lsh_tradeoff.png",
            "graph_plot": "outputs/m3/graph_statistics.png",
            "community_plot": "outputs/m3/community_sizes.png",
            "scalability_plot": "outputs/m3/scalability.png",
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote {map_path.relative_to(ROOT)}", flush=True)
    print("M3 acceptance checks passed.", flush=True)


if __name__ == "__main__":
    main()
