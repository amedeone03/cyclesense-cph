"""Compare exact Jaccard and verified MinHash/LSH through Louvain and placement.

The exact pipeline must reproduce the saved M3 communities and M4 selections.
This script writes only ``outputs/integrated/``. It does not rewrite M1–M5.

    python scripts/run_integrated_study.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.communities import detect_communities, similarity_graph
from cyclesense.integrated import (
    CANONICAL_ARTIFACTS,
    OUTPUT_DIRNAME,
    adjusted_rand_index,
    balanced_selection,
    check_banding,
    community_report,
    compare_similarity_graphs,
    elapsed_call,
    exact_similarity_graph,
    normalized_mutual_information,
    placement_overlap,
    same_weighted_graph,
    streaming_exact_graph,
    tracked_call,
    verified_lsh_graph,
)
from cyclesense.integrated_plots import (
    plot_coverage_difference,
    plot_fair_bandings,
    plot_fair_memory,
    plot_fair_runtime,
    plot_fair_stages,
    plot_graph_recall,
    plot_partition_agreement,
    plot_placement_overlap,
    plot_runtime,
    plot_stage_breakdown,
)
from cyclesense.minhash import (
    build_lsh_buckets,
    build_signatures,
    query_lsh_pairs,
    verify_candidates,
)
from cyclesense.placement import assert_selection, score_split
from cyclesense.retrieval_benchmark import exact_similar_pairs
from cyclesense.similarity import jaccard_similarity, pairwise_jaccard

OUTPUT = ROOT / OUTPUT_DIRNAME
SCENARIOS = ("uniform", "commuter_proxy")


def main() -> None:
    _preserve_first_pass()
    before = _fingerprint()
    config = yaml.safe_load((ROOT / "configs" / "pilot.yaml").read_text(encoding="utf-8"))
    settings = config["integrated"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("Validated M1 artifacts are missing. Run scripts/run_m1.py first.")
    threshold = float(settings["jaccard_threshold"])
    louvain_seed = int(settings["louvain_seed"])
    signature_seed = int(settings["signature_seed"])
    budgets = [int(value) for value in settings["budgets"]]
    lambdas = [float(value) for value in settings["lambdas"]]
    physical, eligible = _load_routes(artifacts["routes"])
    eligible_ids = [
        row["physical_edge_id"]
        for row in csv.DictReader(artifacts["candidates"].open(encoding="utf-8"))
    ]
    m3_counts = _m3_counts(ROOT / "outputs" / "m3" / "communities.csv")
    m3_operating = json.loads(
        (ROOT / "outputs" / "m3" / "summary.json").read_text(encoding="utf-8")
    )["operating_points"]
    m4_edges = _m4_edges(ROOT / "outputs" / "m4" / "placements.csv")

    graph_rows: list[dict] = []
    community_rows: list[dict] = []
    placement_rows: list[dict] = []
    canonical_timing: list[dict] = []
    equivalence_rows: list[dict] = []
    partitions: dict[tuple[str, str], dict] = {}

    for scenario in SCENARIOS:
        calibration_physical = physical[scenario]["calibration"]
        calibration_eligible = eligible[scenario]["calibration"]
        evaluation_eligible = eligible[scenario]["evaluation"]
        if set(calibration_physical) & set(physical[scenario]["evaluation"]):
            raise SystemExit(f"{scenario} repeats a route id across splits")
        print(f"{scenario}: exact graph", flush=True)
        exact_graph, _pairs = exact_similarity_graph(calibration_physical, threshold)
        exact_labels, exact_modularity, exact_sizes = detect_communities(exact_graph, louvain_seed)
        exact_summary = community_report(exact_labels, exact_modularity, exact_sizes)
        saved_counts = m3_counts[(scenario, threshold, louvain_seed)]
        if (
            exact_summary["n_communities"] != saved_counts["n_communities"]
            or exact_summary["n_singletons"] != saved_counts["n_singletons"]
            or exact_summary["n_non_singletons"] != saved_counts["n_non_singletons"]
        ):
            raise SystemExit(f"exact Louvain does not reproduce M3 for {scenario}: {exact_summary}")
        equivalence_rows.extend(
            _streaming_equivalence(
                scenario,
                calibration_physical,
                calibration_eligible,
                eligible_ids,
                exact_graph,
                exact_labels,
                threshold,
                louvain_seed,
                lambdas,
                budgets,
            )
        )
        partitions[(scenario, "exact")] = {
            "labels": exact_labels,
            "graph": exact_graph,
            "summary": exact_summary,
        }
        bandings = _bandings(scenario, settings, m3_operating)
        for banding in bandings:
            print(
                f"  {banding['role']} p={banding['num_perm']} "
                f"b={banding['bands']} r={banding['rows']}",
                flush=True,
            )
            approximate_graph, candidates, _verified = verified_lsh_graph(
                calibration_physical,
                num_perm=banding["num_perm"],
                bands=banding["bands"],
                rows=banding["rows"],
                threshold=threshold,
                seed=signature_seed,
            )
            comparison = compare_similarity_graphs(exact_graph, approximate_graph)
            labels, modularity, sizes = detect_communities(approximate_graph, louvain_seed)
            summary = community_report(labels, modularity, sizes)
            usable = sum(1 for edges in calibration_physical.values() if edges)
            possible = usable * (usable - 1) // 2
            graph_rows.append(
                {
                    "scenario": scenario,
                    "role": banding["role"],
                    "num_perm": banding["num_perm"],
                    "bands": banding["bands"],
                    "rows": banding["rows"],
                    "n_candidates": len(candidates),
                    "n_possible_pairs": possible,
                    "candidate_reduction": 1 - len(candidates) / possible,
                    **comparison,
                }
            )
            community_rows.append(
                {
                    "scenario": scenario,
                    "role": banding["role"],
                    "num_perm": banding["num_perm"],
                    "bands": banding["bands"],
                    "rows": banding["rows"],
                    "graph_edge_recall": comparison["graph_edge_recall"],
                    "n_edges_missed": comparison["n_edges_missed"],
                    "adjusted_rand_index": adjusted_rand_index(exact_labels, labels),
                    "normalized_mutual_information": normalized_mutual_information(
                        exact_labels, labels
                    ),
                    "exact_communities": exact_summary["n_communities"],
                    "approximate_communities": summary["n_communities"],
                    "exact_singletons": exact_summary["n_singletons"],
                    "approximate_singletons": summary["n_singletons"],
                    "exact_largest": exact_summary["largest"],
                    "approximate_largest": summary["largest"],
                    "exact_modularity": exact_summary["modularity"],
                    "approximate_modularity": summary["modularity"],
                    "modularity_note": "measured on different graphs; not a quality ranking",
                }
            )
            partitions[(scenario, banding["role"])] = {"labels": labels, "summary": summary}
        _time_canonical(
            canonical_timing,
            scenario,
            calibration_physical,
            calibration_eligible,
            eligible_ids,
            threshold,
            louvain_seed,
            signature_seed,
            bandings[0],
            lambdas[0],
            budgets[0],
            partitions,
        )
        for role in ("exact", *(banding["role"] for banding in bandings)):
            labels = partitions[(scenario, role)]["labels"]
            for lam in (0.0, *lambdas):
                for budget in budgets:
                    selected, _weights = balanced_selection(
                        eligible_ids, calibration_eligible, labels, lam, budget
                    )
                    assert_selection(selected, eligible_ids, budget)
                    saved = m4_edges.get((scenario, threshold, lam, budget))
                    if role == "exact":
                        if saved is None or "|".join(selected) != saved:
                            raise SystemExit(
                                f"exact placement does not match M4 for {scenario} λ={lam} K={budget}"
                            )
                    elif lam == 0.0 and "|".join(selected) != saved:
                        raise SystemExit(f"lambda 0 changed with the {role} partition")
                    exact_selected = _selection_from_saved(saved) if lam == 0.0 else None
                    if lam != 0.0:
                        exact_selected, _weights = balanced_selection(
                            eligible_ids,
                            calibration_eligible,
                            partitions[(scenario, "exact")]["labels"],
                            lam,
                            budget,
                        )
                    overlap = placement_overlap(exact_selected or selected, selected)
                    placement_rows.append(
                        _placement_row(
                            scenario=scenario,
                            role=role,
                            lam=lam,
                            budget=budget,
                            selected=selected,
                            exact_selected=exact_selected or selected,
                            overlap=overlap,
                            labels=labels,
                            exact_labels=partitions[(scenario, "exact")]["labels"],
                            calibration=calibration_eligible,
                            evaluation=evaluation_eligible,
                            graph_edge_recall=None
                            if role == "exact"
                            else _recall(graph_rows, scenario, role),
                        )
                    )

    scaling_rows, generated = _scalability(artifacts, config, settings, eligible_ids)
    fair_runs, fair_summary, fair_stages = _fair_benchmark(generated, eligible_ids, settings)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_csv(OUTPUT / "graph_comparison.csv", graph_rows)
    _write_csv(OUTPUT / "communities.csv", community_rows)
    _write_csv(OUTPUT / "placements.csv", placement_rows)
    _write_csv(OUTPUT / "canonical_timing.csv", canonical_timing)
    _write_csv(OUTPUT / "scalability.csv", scaling_rows)
    _write_csv(OUTPUT / "streaming_equivalence.csv", equivalence_rows)
    _write_csv(OUTPUT / "fair_timing_runs.csv", fair_runs)
    _write_csv(OUTPUT / "fair_timing_summary.csv", fair_summary)
    _write_csv(OUTPUT / "fair_stages.csv", fair_stages)
    focus = [
        row
        for row in placement_rows
        if row["role"] != "exact" and row["lambda"] == 0.25 and row["k"] == 10
    ]
    plot_graph_recall(graph_rows, OUTPUT / "graph_recall.png")
    plot_partition_agreement(community_rows, OUTPUT / "partition_agreement.png")
    plot_placement_overlap(focus, OUTPUT / "placement_overlap_k10.png")
    plot_coverage_difference(focus, OUTPUT / "coverage_difference_k10.png")
    plot_runtime(scaling_rows, OUTPUT / "runtime.png")
    plot_stage_breakdown(scaling_rows, OUTPUT / "stage_breakdown.png")
    headline = [
        row
        for row in fair_summary
        if row["method"] in {"materialized_exact", "streaming_exact", "verified_lsh"}
    ]
    plot_fair_runtime(headline, OUTPUT / "fair_runtime.png")
    plot_fair_memory(headline, OUTPUT / "fair_memory.png")
    plot_fair_bandings(
        [row for row in fair_summary if row["method"] != "materialized_exact"],
        OUTPUT / "fair_bandings.png",
    )
    plot_fair_stages(
        [
            row
            for row in fair_stages
            if row["method"] in {"materialized_exact", "streaming_exact", "verified_lsh"}
        ],
        OUTPUT / "fair_stages.png",
    )
    summary = {
        "threshold": threshold,
        "louvain_seed": louvain_seed,
        "signature_seed": signature_seed,
        "memory": "tracemalloc peak, Python-tracked allocations, not process RSS",
        "stage_times": "a second measurement; they do not sum exactly to the end-to-end call",
        "graphs": graph_rows,
        "communities": community_rows,
        "placements": [
            {key: value for key, value in row.items() if key != "selected_edges"}
            for row in placement_rows
        ],
        "canonical_timing": canonical_timing,
        "scalability": scaling_rows,
        "streaming_equivalence": equivalence_rows,
        "fair_timing_summary": fair_summary,
        "timing_protocol": (
            "End-to-end repeats use perf_counter and do not start tracemalloc. "
            "Peak memory is the median of separate tracemalloc runs and is not a runtime."
        ),
        "acceptance": {
            "exact_reproduces_m3_and_m4": True,
            "streaming_exact_matches_materialized_reference": all(
                row["matches_graph"] and row["matches_partition"] and row["matches_counters"]
                for row in equivalence_rows
            ),
            "approximate_edges_are_verified_subgraphs": True,
            "canonical_artifacts_unchanged": _fingerprint() == before,
        },
    }
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    if _fingerprint() != before:
        raise SystemExit("canonical M1–M5 artifacts changed")
    print(json.dumps(summary["acceptance"], indent=2), flush=True)


def _bandings(scenario: str, settings: dict, operating: dict) -> list[dict]:
    primary = dict(settings["primary_bandings"][scenario])
    saved = operating[scenario]
    if (
        int(primary["num_perm"]) != int(saved["num_perm"])
        or int(primary["bands"]) != int(saved["bands"])
        or int(primary["rows"]) != int(saved["rows_per_band"])
    ):
        raise SystemExit(f"primary banding for {scenario} is not the saved M3 operating point")
    check_banding(int(primary["num_perm"]), int(primary["bands"]), int(primary["rows"]))
    chosen = [
        {
            "role": "primary",
            "num_perm": int(primary["num_perm"]),
            "bands": int(primary["bands"]),
            "rows": int(primary["rows"]),
        }
    ]
    for row in settings["comparison_bandings"]:
        check_banding(int(row["num_perm"]), int(row["bands"]), int(row["rows"]))
        chosen.append(
            {
                "role": str(row["role"]),
                "num_perm": int(row["num_perm"]),
                "bands": int(row["bands"]),
                "rows": int(row["rows"]),
            }
        )
    return chosen


def _placement_row(
    *,
    scenario,
    role,
    lam,
    budget,
    selected,
    exact_selected,
    overlap,
    labels,
    exact_labels,
    calibration,
    evaluation,
    graph_edge_recall,
) -> dict:
    from cyclesense.balanced import represented_communities

    own = represented_communities(calibration, labels, selected)
    reference = represented_communities(calibration, exact_labels, selected)
    exact_reference = represented_communities(calibration, exact_labels, exact_selected)
    calibration_coverage = score_split(calibration, selected)
    heldout_coverage = score_split(evaluation, selected)
    exact_calibration = score_split(calibration, exact_selected)
    exact_heldout = score_split(evaluation, exact_selected)
    return {
        "scenario": scenario,
        "role": role,
        "pipeline": "exact" if role == "exact" else "lsh",
        "lambda": lam,
        "k": budget,
        "n_selected": len(selected),
        "n_shared": overlap["n_shared"] if role != "exact" else budget,
        "selected_jaccard": overlap["selected_jaccard"] if role != "exact" else 1.0,
        "calibration_coverage": calibration_coverage,
        "heldout_coverage": heldout_coverage,
        "calibration_difference": calibration_coverage - exact_calibration,
        "heldout_difference": heldout_coverage - exact_heldout,
        "reference_large_represented": reference["n_large_represented"],
        "exact_large_represented": exact_reference["n_large_represented"],
        "reference_representation_difference": (
            reference["large_represented_fraction"] - exact_reference["large_represented_fraction"]
        ),
        "own_large_represented": own["n_large_represented"],
        "own_large_representation": own["large_represented_fraction"],
        "graph_edge_recall": graph_edge_recall,
        "selected_edges": "|".join(selected),
    }


def _time_canonical(
    rows,
    scenario,
    physical,
    eligible_routes,
    eligible_ids,
    threshold,
    louvain_seed,
    signature_seed,
    primary,
    lam,
    budget,
    partitions,
) -> None:
    def exact_once():
        graph, _pairs = exact_similarity_graph(physical, threshold)
        labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
        selected, _weights = balanced_selection(eligible_ids, eligible_routes, labels, lam, budget)
        return selected

    def approximate_once():
        graph, _candidates, _verified = verified_lsh_graph(
            physical,
            num_perm=primary["num_perm"],
            bands=primary["bands"],
            rows=primary["rows"],
            threshold=threshold,
            seed=signature_seed,
        )
        labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
        selected, _weights = balanced_selection(eligible_ids, eligible_routes, labels, lam, budget)
        return selected

    exact_selected, exact_seconds, exact_mb = tracked_call(exact_once)
    approximate_selected, lsh_seconds, lsh_mb = tracked_call(approximate_once)
    if tuple(exact_selected) != _saved_selection(
        partitions, scenario, "exact", eligible_ids, eligible_routes, lam, budget
    ):
        raise SystemExit("timed exact selection does not match the study selection")
    if tuple(approximate_selected) != _saved_selection(
        partitions, scenario, primary["role"], eligible_ids, eligible_routes, lam, budget
    ):
        raise SystemExit("timed approximate selection does not match the study selection")
    stages = _stage_seconds(
        physical,
        eligible_routes,
        eligible_ids,
        threshold,
        louvain_seed,
        signature_seed,
        primary,
        lam,
        budget,
    )
    rows.append(
        {
            "scenario": scenario,
            "role": primary["role"],
            "lambda": lam,
            "k": budget,
            "exact_seconds": exact_seconds,
            "exact_peak_mb": exact_mb,
            "lsh_seconds": lsh_seconds,
            "lsh_peak_mb": lsh_mb,
            **stages,
        }
    )


def _saved_selection(partitions, scenario, role, eligible_ids, eligible_routes, lam, budget):
    selected, _weights = balanced_selection(
        eligible_ids, eligible_routes, partitions[(scenario, role)]["labels"], lam, budget
    )
    return tuple(selected)


def _stage_seconds(
    physical,
    eligible_routes,
    eligible_ids,
    threshold,
    louvain_seed,
    signature_seed,
    banding,
    lam,
    budget,
):
    pairs, pairwise_s, _pairwise_mb = tracked_call(pairwise_jaccard, physical)
    _graph, graph_s, _graph_mb = tracked_call(similarity_graph, physical, pairs, threshold)
    labels, louvain_s, _louvain_mb = tracked_call(detect_communities, _graph, louvain_seed)
    _selected, placement_s, _placement_mb = tracked_call(
        lambda: balanced_selection(eligible_ids, eligible_routes, labels[0], lam, budget)
    )
    usable = sorted(route_id for route_id, edges in physical.items() if edges)
    route_sets = [set(physical[route_id]) for route_id in usable]
    signatures, signature_s, _signature_mb = tracked_call(
        build_signatures, route_sets, banding["num_perm"], signature_seed
    )
    buckets, index_s, _index_mb = tracked_call(
        build_lsh_buckets, signatures, banding["bands"], banding["rows"]
    )
    candidates, query_s, _query_mb = tracked_call(
        query_lsh_pairs, signatures, buckets, banding["bands"], banding["rows"]
    )
    verified, verify_s, _verify_mb = tracked_call(
        verify_candidates, candidates, route_sets, threshold
    )

    def build_graph():
        weighted = []
        for left, right in verified:
            similarity = jaccard_similarity(route_sets[left], route_sets[right])
            weighted.append((usable[left], usable[right], similarity))
        return similarity_graph(physical, weighted, threshold)

    approximate_graph, approximate_graph_s, _approx_graph_mb = tracked_call(build_graph)
    approximate_labels, approximate_louvain_s, _approx_louvain_mb = tracked_call(
        detect_communities, approximate_graph, louvain_seed
    )
    _approx_selected, approximate_placement_s, _approx_place_mb = tracked_call(
        lambda: balanced_selection(
            eligible_ids, eligible_routes, approximate_labels[0], lam, budget
        )
    )
    return {
        "exact_pairwise_s": pairwise_s,
        "exact_graph_s": graph_s,
        "exact_louvain_s": louvain_s,
        "exact_placement_s": placement_s,
        "lsh_signature_s": signature_s,
        "lsh_query_s": index_s + query_s,
        "lsh_verify_s": verify_s,
        "lsh_graph_s": approximate_graph_s,
        "lsh_louvain_s": approximate_louvain_s,
        "lsh_placement_s": approximate_placement_s,
    }


def _scalability(artifacts, config, settings, eligible_ids) -> list[dict]:
    import osmnx as ox

    from cyclesense.network import node_coordinates
    from cyclesense.routes import generate_modeled_routes

    simulation = config["simulation"]
    sizes = [int(size) for size in settings["scalability_sizes"]]
    seed = int(settings["scalability_seed"])
    banding = settings["scalability_banding"]
    check_banding(int(banding["num_perm"]), int(banding["bands"]), int(banding["rows"]))
    threshold = float(settings["jaccard_threshold"])
    louvain_seed = int(settings["louvain_seed"])
    signature_seed = int(settings["signature_seed"])
    lam = float(settings["lambdas"][0])
    budget = int(settings["budgets"][0])
    routing = ox.load_graphml(artifacts["routing_wgs84"])
    projected = ox.load_graphml(artifacts["routing_projected"])
    generated, _stats = generate_modeled_routes(
        routing,
        node_coordinates(projected),
        set(eligible_ids),
        scenario=str(settings["scalability_scenario"]),
        n_calibration=max(sizes),
        n_evaluation=0,
        calibration_seed=seed,
        evaluation_seed=seed + 1,
        min_distance_m=float(simulation["min_od_distance_m"]),
        max_distance_m=float(simulation["max_od_distance_m"]),
        min_eligible_edges=int(simulation["min_eligible_edges"]),
        max_attempts_factor=int(simulation.get("max_attempts_factor", 80)),
    )
    print(f"timing collection: {len(generated)} simulated routes, generation excluded", flush=True)
    measured = []
    for size in sizes:
        subset = generated[:size]
        physical = {route.route_id: set(route.physical_edge_ids) for route in subset}
        eligible = {route.route_id: set(route.eligible_edge_ids) for route in subset}
        print(f"scalability n={size}", flush=True)

        def exact_once(routes=physical, placement_routes=eligible):
            graph, _pairs = exact_similarity_graph(routes, threshold)
            labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
            selected, _weights = balanced_selection(
                eligible_ids, placement_routes, labels, lam, budget
            )
            return graph, labels, selected

        def approximate_once(routes=physical, placement_routes=eligible):
            graph, candidates, _verified = verified_lsh_graph(
                routes,
                num_perm=int(banding["num_perm"]),
                bands=int(banding["bands"]),
                rows=int(banding["rows"]),
                threshold=threshold,
                seed=signature_seed,
            )
            labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
            selected, _weights = balanced_selection(
                eligible_ids, placement_routes, labels, lam, budget
            )
            return graph, candidates, labels, selected

        (exact_graph, exact_labels, exact_selected), exact_seconds, exact_mb = tracked_call(
            exact_once
        )
        (
            (
                approximate_graph,
                candidates,
                approximate_labels,
                approximate_selected,
            ),
            lsh_seconds,
            lsh_mb,
        ) = tracked_call(approximate_once)
        comparison = compare_similarity_graphs(exact_graph, approximate_graph)
        usable = len(physical)
        possible = usable * (usable - 1) // 2
        stages = _stage_seconds(
            physical,
            eligible,
            eligible_ids,
            threshold,
            louvain_seed,
            signature_seed,
            {
                "num_perm": int(banding["num_perm"]),
                "bands": int(banding["bands"]),
                "rows": int(banding["rows"]),
            },
            lam,
            budget,
        )
        route_sets = [set(route.physical_edge_ids) for route in subset]
        _exact_pairs, pair_only_s, pair_only_mb = tracked_call(
            exact_similar_pairs, route_sets, threshold
        )
        measured.append(
            {
                "n_routes": size,
                "scenario": settings["scalability_scenario"],
                "num_perm": int(banding["num_perm"]),
                "bands": int(banding["bands"]),
                "rows": int(banding["rows"]),
                "exact_seconds": exact_seconds,
                "exact_peak_mb": exact_mb,
                "lsh_seconds": lsh_seconds,
                "lsh_peak_mb": lsh_mb,
                "pair_retrieval_only_exact_s": pair_only_s,
                "pair_retrieval_only_exact_mb": pair_only_mb,
                "n_candidates": len(candidates),
                "candidate_reduction": 1 - len(candidates) / possible,
                "graph_edge_recall": comparison["graph_edge_recall"],
                "n_edges_missed": comparison["n_edges_missed"],
                "adjusted_rand_index": adjusted_rand_index(exact_labels, approximate_labels),
                "calibration_coverage_difference": score_split(eligible, approximate_selected)
                - score_split(eligible, exact_selected),
                "coverage_note": "difference on the timing sample, not a held-out score",
                **stages,
            }
        )
    return measured, generated


def _preserve_first_pass() -> None:
    """Keep the first single-pass timing files beside the regenerated copies."""
    if not OUTPUT.is_dir():
        return
    for name in (
        "scalability.csv",
        "canonical_timing.csv",
        "runtime.png",
        "stage_breakdown.png",
        "summary.json",
    ):
        source = OUTPUT / name
        preserved = OUTPUT / f"first_pass_{name}"
        if source.is_file() and not preserved.is_file():
            preserved.write_bytes(source.read_bytes())


def _streaming_equivalence(
    scenario,
    physical,
    eligible_routes,
    eligible_ids,
    exact_graph,
    exact_labels,
    threshold,
    louvain_seed,
    lambdas,
    budgets,
) -> list[dict]:
    streamed = streaming_exact_graph(physical, threshold)
    graph_match = same_weighted_graph(exact_graph, streamed)
    streamed_labels, _modularity, _sizes = detect_communities(streamed, louvain_seed)
    partition_match = streamed_labels == exact_labels
    counter_match = True
    checked = 0
    for lam in (0.0, *lambdas):
        for budget in budgets:
            reference, _weights = balanced_selection(
                eligible_ids, eligible_routes, exact_labels, lam, budget
            )
            other, _weights = balanced_selection(
                eligible_ids, eligible_routes, streamed_labels, lam, budget
            )
            checked += 1
            if reference != other:
                counter_match = False
    if not (graph_match and partition_match and counter_match):
        raise SystemExit(
            f"streaming exact pipeline does not match the materialized reference for {scenario}"
        )
    print(
        f"  streaming exact matches the reference graph, partition, and {checked} selections",
        flush=True,
    )
    return [
        {
            "scenario": scenario,
            "n_nodes": exact_graph.number_of_nodes(),
            "n_edges": exact_graph.number_of_edges(),
            "matches_graph": graph_match,
            "matches_partition": partition_match,
            "matches_counters": counter_match,
            "n_selections_checked": checked,
        }
    ]


def _fair_benchmark(generated, eligible_ids, settings) -> tuple[list[dict], list[dict], list[dict]]:
    sizes = [int(size) for size in settings["scalability_sizes"]]
    threshold = float(settings["jaccard_threshold"])
    louvain_seed = int(settings["louvain_seed"])
    signature_seed = int(settings["signature_seed"])
    lam = float(settings["lambdas"][0])
    budget = int(settings["budgets"][0])
    timing_repeats = int(settings["timing_repeats"])
    memory_repeats = int(settings["memory_repeats"])
    specs = _method_specs(settings)
    runs: list[dict] = []
    summary: list[dict] = []
    stages: list[dict] = []
    for size in sizes:
        subset = generated[:size]
        physical = {route.route_id: set(route.physical_edge_ids) for route in subset}
        eligible = {route.route_id: set(route.eligible_edge_ids) for route in subset}
        reference = None
        for spec in specs:
            print(f"fair n={size} {spec['method']}", flush=True)
            runner = _runner(
                spec,
                physical,
                eligible,
                eligible_ids,
                threshold,
                louvain_seed,
                signature_seed,
                lam,
                budget,
            )
            seconds = []
            first = None
            for repeat in range(timing_repeats):
                value, elapsed = elapsed_call(runner)
                seconds.append(elapsed)
                if repeat == 0:
                    first = value
                else:
                    del value
                runs.append(
                    {
                        "n_routes": size,
                        "method": spec["method"],
                        "repeat": repeat,
                        "value": elapsed,
                        "measurement": "timing",
                    }
                )
            graph, labels, selected = first[:3]
            if spec["kind"] == "materialized":
                reference = (graph, labels, selected)
            elif reference is None:
                raise SystemExit("materialized exact must be timed first")
            else:
                if spec["kind"] == "streaming" and not same_weighted_graph(reference[0], graph):
                    raise SystemExit(f"streaming graph differs at n={size}")
                if spec["kind"] == "streaming" and labels != reference[1]:
                    raise SystemExit(f"streaming Louvain differs at n={size}")
                if spec["kind"] == "streaming" and selected != reference[2]:
                    raise SystemExit(f"streaming counters differ at n={size}")
            overlap = placement_overlap(reference[2], selected)
            peaks = []
            for repeat in range(memory_repeats):
                _value, _elapsed, peak = tracked_call(runner)
                peaks.append(peak)
                del _value
                runs.append(
                    {
                        "n_routes": size,
                        "method": spec["method"],
                        "repeat": repeat,
                        "value": peak,
                        "measurement": "tracemalloc_peak_mb",
                    }
                )
            stage_names, stage_seconds = _fair_stage_seconds(
                spec,
                physical,
                eligible,
                eligible_ids,
                threshold,
                louvain_seed,
                signature_seed,
                lam,
                budget,
            )
            timing = _dispersion(seconds)
            memory = _dispersion(peaks)
            summary.append(
                {
                    "n_routes": size,
                    "method": spec["method"],
                    "label": spec["label"],
                    "n_edges": graph.number_of_edges(),
                    "adjusted_rand_index": adjusted_rand_index(reference[1], labels),
                    "n_shared": overlap["n_shared"],
                    "selected_jaccard": overlap["selected_jaccard"],
                    "median_seconds": timing["median"],
                    "stdev_seconds": timing["stdev"],
                    "min_seconds": timing["minimum"],
                    "max_seconds": timing["maximum"],
                    "n_timing_repeats": timing_repeats,
                    "median_peak_mb": memory["median"],
                    "min_peak_mb": memory["minimum"],
                    "max_peak_mb": memory["maximum"],
                    "n_memory_repeats": memory_repeats,
                }
            )
            stages.append(
                {
                    "n_routes": size,
                    "method": spec["method"],
                    "label": spec["label"],
                    "stage_names": "|".join(stage_names),
                    "stage_seconds": "|".join(f"{value:.6f}" for value in stage_seconds),
                }
            )
            del graph, labels, selected, first
    return runs, summary, stages


def _method_specs(settings) -> list[dict]:
    uniform = settings["scalability_banding"]
    commuter = settings["primary_bandings"]["commuter_proxy"]
    specs = [
        {"method": "materialized_exact", "label": "Materialized exact", "kind": "materialized"},
        {"method": "streaming_exact", "label": "Streaming exact", "kind": "streaming"},
        {
            "method": "verified_lsh",
            "label": "Verified LSH, 32×16×2",
            "kind": "lsh",
            "num_perm": int(uniform["num_perm"]),
            "bands": int(uniform["bands"]),
            "rows": int(uniform["rows"]),
        },
    ]
    for row in settings["comparison_bandings"]:
        check_banding(int(row["num_perm"]), int(row["bands"]), int(row["rows"]))
        specs.append(
            {
                "method": f"lsh_{row['role']}",
                "label": (
                    f"LSH {str(row['role']).replace('_', ' ')}, "
                    f"{int(row['num_perm'])}×{int(row['bands'])}×{int(row['rows'])}"
                ),
                "kind": "lsh",
                "num_perm": int(row["num_perm"]),
                "bands": int(row["bands"]),
                "rows": int(row["rows"]),
            }
        )
    check_banding(int(commuter["num_perm"]), int(commuter["bands"]), int(commuter["rows"]))
    specs.append(
        {
            "method": "lsh_primary_commuter",
            "label": "Verified LSH, 128×32×4",
            "kind": "lsh",
            "num_perm": int(commuter["num_perm"]),
            "bands": int(commuter["bands"]),
            "rows": int(commuter["rows"]),
        }
    )
    check_banding(int(uniform["num_perm"]), int(uniform["bands"]), int(uniform["rows"]))
    return specs


def _runner(
    spec, physical, eligible, eligible_ids, threshold, louvain_seed, signature_seed, lam, budget
):
    kind = spec["kind"]
    num_perm = int(spec.get("num_perm", 0))
    bands = int(spec.get("bands", 0))
    rows = int(spec.get("rows", 0))

    def run(routes=physical, placement_routes=eligible):
        if kind == "materialized":
            graph, _pairs = exact_similarity_graph(routes, threshold)
        elif kind == "streaming":
            graph = streaming_exact_graph(routes, threshold)
        else:
            graph, _candidates, _verified = verified_lsh_graph(
                routes,
                num_perm=num_perm,
                bands=bands,
                rows=rows,
                threshold=threshold,
                seed=signature_seed,
            )
        labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
        selected, _weights = balanced_selection(eligible_ids, placement_routes, labels, lam, budget)
        return graph, labels, selected

    return run


def _fair_stage_seconds(
    spec, physical, eligible, eligible_ids, threshold, louvain_seed, signature_seed, lam, budget
):
    if spec["kind"] == "materialized":
        pairs, pairwise_s = elapsed_call(pairwise_jaccard, physical)
        graph, graph_s = elapsed_call(similarity_graph, physical, pairs, threshold)
        labels, louvain_s = elapsed_call(detect_communities, graph, louvain_seed)
        _selected, placement_s = elapsed_call(
            lambda: balanced_selection(eligible_ids, eligible, labels[0], lam, budget)
        )
        return (
            ["All-pairs Jaccard", "Thresholded graph", "Louvain", "Weights and greedy"],
            [pairwise_s, graph_s, louvain_s, placement_s],
        )
    if spec["kind"] == "streaming":
        graph, build_s = elapsed_call(streaming_exact_graph, physical, threshold)
        labels, louvain_s = elapsed_call(detect_communities, graph, louvain_seed)
        _selected, placement_s = elapsed_call(
            lambda: balanced_selection(eligible_ids, eligible, labels[0], lam, budget)
        )
        return (
            ["Thresholded Jaccard", "Louvain", "Weights and greedy"],
            [build_s, louvain_s, placement_s],
        )
    usable = sorted(route_id for route_id, edges in physical.items() if edges)
    route_sets = [set(physical[route_id]) for route_id in usable]
    signatures, signature_s = elapsed_call(
        build_signatures, route_sets, int(spec["num_perm"]), signature_seed
    )
    buckets, index_s = elapsed_call(
        build_lsh_buckets, signatures, int(spec["bands"]), int(spec["rows"])
    )
    candidates, query_s = elapsed_call(
        query_lsh_pairs, signatures, buckets, int(spec["bands"]), int(spec["rows"])
    )
    verified, verify_s = elapsed_call(verify_candidates, candidates, route_sets, threshold)

    def build_graph():
        weighted = []
        for left, right in verified:
            similarity = jaccard_similarity(route_sets[left], route_sets[right])
            weighted.append((usable[left], usable[right], similarity))
        return similarity_graph(physical, weighted, threshold)

    graph, graph_s = elapsed_call(build_graph)
    labels, louvain_s = elapsed_call(detect_communities, graph, louvain_seed)
    _selected, placement_s = elapsed_call(
        lambda: balanced_selection(eligible_ids, eligible, labels[0], lam, budget)
    )
    return (
        ["Signatures", "Index and query", "Verify", "Graph", "Louvain", "Weights and greedy"],
        [signature_s, index_s + query_s, verify_s, graph_s, louvain_s, placement_s],
    )


def _dispersion(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "minimum": min(values),
        "maximum": max(values),
    }


def _selection_from_saved(saved: str | None) -> tuple[str, ...] | None:
    if saved is None:
        return None
    return tuple(edge for edge in saved.split("|") if edge)


def _recall(rows: list[dict], scenario: str, role: str):
    matches = [
        row["graph_edge_recall"]
        for row in rows
        if row["scenario"] == scenario and row["role"] == role
    ]
    if len(matches) != 1:
        raise SystemExit(f"missing graph recall for {scenario} {role}")
    return matches[0]


def _load_routes(path: Path):
    physical: dict = {}
    eligible: dict = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            physical.setdefault(row["scenario"], {}).setdefault(row["split"], {})[
                row["route_id"]
            ] = {edge for edge in row["physical_edge_ids"].split("|") if edge}
            eligible.setdefault(row["scenario"], {}).setdefault(row["split"], {})[
                row["route_id"]
            ] = {edge for edge in row["eligible_edge_ids"].split("|") if edge}
    return physical, eligible


def _m3_counts(path: Path) -> dict[tuple[str, float, int], dict[str, int]]:
    counts = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            counts[(row["scenario"], float(row["threshold"]), int(row["seed"]))] = {
                "n_communities": int(row["n_communities"]),
                "n_singletons": int(row["n_singletons"]),
                "n_non_singletons": int(row["n_communities_size_at_least_2"]),
            }
    return counts


def _m4_edges(path: Path) -> dict[tuple[str, float, float, int], str]:
    edges = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["source"] != "louvain":
                continue
            edges[
                (row["scenario"], float(row["threshold"]), float(row["lambda"]), int(row["k"]))
            ] = row["selected_edges"]
    return edges


def _fingerprint() -> dict[str, str]:
    hashes = {}
    for relative in CANONICAL_ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise SystemExit(f"missing canonical artifact {relative}")
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise SystemExit(f"no rows for {path.name}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
