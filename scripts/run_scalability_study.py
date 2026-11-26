"""Scalability of streaming exact and verified LSH on nested simulated samples.

Route generation is timed separately. Pipeline repeats use perf_counter only.
Peak memory uses tracemalloc on later calls and is not reported as runtime.
"""

from __future__ import annotations

import csv
import gc
import hashlib
import json
import platform
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.communities import detect_communities
from cyclesense.integrated import (
    balanced_selection,
    check_banding,
    elapsed_call,
    tracked_call,
    verified_lsh_graph,
)
from cyclesense.network import node_coordinates
from cyclesense.routes import generate_modeled_routes
from cyclesense.scalability import (
    OUTPUT_DIRNAME,
    ResourceLimit,
    allow_streaming_extension,
    assert_no_evaluation_leakage,
    assert_physical_ids,
    candidate_statistics,
    community_structure,
    dataset_diagnostics,
    exact_agreement,
    graph_structure,
    lsh_stage_profile,
    nested_prefixes,
    placement_record,
    run_streaming,
    streaming_stage_profile,
    subset_edge_recall,
    subset_indexes,
    summarize_times,
)
from cyclesense.scalability_plots import (
    plot_agreement,
    plot_candidates,
    plot_graph_growth,
    plot_memory,
    plot_runtime,
    plot_stages,
)

PROTECTED = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "data/external/trafiktal.csv",
    "outputs/m2/results.csv",
    "outputs/m2/summary.json",
    "outputs/m3/summary.json",
    "outputs/m3/communities.csv",
    "outputs/m4/summary.json",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
    "outputs/integrated/summary.json",
    "outputs/route_choice/summary.json",
    "outputs/standout/summary.json",
    "outputs/standout/coverage.csv",
)


def main() -> None:
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text())
    settings = config["scalability_study"]
    simulation = config["simulation"]
    artifacts = validated_m1_artifacts(ROOT)
    if artifacts is None:
        raise SystemExit("M1 artifacts are missing. No benchmark routes were invented.")
    before = _fingerprint()
    output = ROOT / OUTPUT_DIRNAME
    output.mkdir(parents=True, exist_ok=True)
    (output / "mplconfig").mkdir(exist_ok=True)

    eligible_ids = _candidate_ids(artifacts["candidates"])
    routing = ox.load_graphml(artifacts["routing_wgs84"])
    projected = ox.load_graphml(artifacts["routing_projected"])
    known_ids = {
        str(data["physical_edge_id"])
        for _u, _v, _key, data in routing.edges(keys=True, data=True)
        if data.get("physical_edge_id")
    }
    sizes = [int(size) for size in settings["sizes"]]
    started = time.perf_counter()
    generated, generation_stats = generate_modeled_routes(
        routing,
        node_coordinates(projected),
        set(eligible_ids),
        scenario=str(settings["scenario"]),
        n_calibration=max(sizes),
        n_evaluation=0,
        calibration_seed=int(settings["seed"]),
        evaluation_seed=int(settings["evaluation_seed"]),
        min_distance_m=float(simulation["min_od_distance_m"]),
        max_distance_m=float(simulation["max_od_distance_m"]),
        min_eligible_edges=int(simulation["min_eligible_edges"]),
        max_attempts_factor=int(simulation.get("max_attempts_factor", 80)),
    )
    generation_seconds = time.perf_counter() - started
    assert_physical_ids(generated, known_ids)
    runnable = [size for size in sizes if size <= len(generated)]
    if not runnable:
        raise SystemExit("route generation kept no benchmark routes")
    prefixes = nested_prefixes(generated, runnable)
    blocked_od = {(route.origin_node, route.destination_node) for route in generated}
    blocked_paths = {route.physical_edge_ids for route in generated}
    evaluation, _evaluation_stats = generate_modeled_routes(
        routing,
        node_coordinates(projected),
        set(eligible_ids),
        scenario=str(settings["scenario"]),
        n_calibration=0,
        n_evaluation=int(settings["evaluation_routes"]),
        calibration_seed=int(settings["seed"]),
        evaluation_seed=int(settings["evaluation_seed"]),
        min_distance_m=float(simulation["min_od_distance_m"]),
        max_distance_m=float(simulation["max_od_distance_m"]),
        min_eligible_edges=int(simulation["min_eligible_edges"]),
        max_attempts_factor=int(simulation.get("max_attempts_factor", 80)),
        blocked_od=blocked_od,
        blocked_paths=blocked_paths,
    )
    assert_physical_ids(evaluation, known_ids)
    assert_no_evaluation_leakage(
        {route.route_id for route in generated},
        {route.route_id for route in evaluation},
    )
    heldout = {route.route_id: set(route.eligible_edge_ids) for route in evaluation}
    print(
        f"generated {len(generated)} unique simulated routes in {generation_seconds:.1f}s; "
        f"held-out {len(evaluation)}; running sizes {runnable}",
        flush=True,
    )

    threshold = float(settings["jaccard_threshold"])
    louvain_seed = int(settings["louvain_seed"])
    signature_seed = int(settings["signature_seed"])
    lam = float(settings["lambda"])
    budget = int(settings["budget_k"])
    bandings = [settings["primary_banding"], *settings["comparison_bandings"]]
    for banding in bandings:
        check_banding(int(banding["num_perm"]), int(banding["bands"]), int(banding["rows"]))

    dataset_rows = []
    timing_runs: list[dict[str, Any]] = []
    timing_summary: list[dict[str, Any]] = []
    memory_rows: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    graph_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    placement_rows: list[dict[str, Any]] = []
    stage_rows: list[dict[str, Any]] = []
    previous_streaming: dict[str, Any] | None = None
    previous_primary: tuple[str, ...] | None = None

    for size, subset in zip(runnable, prefixes, strict=True):
        diagnostics = dataset_diagnostics(subset, generation_seconds=generation_seconds, requested=max(sizes))
        diagnostics["rejected_seen_path"] = int(generation_stats["calibration"].get("rejected_seen_path", 0))
        diagnostics["generation_attempts"] = int(generation_stats["calibration"].get("attempts", 0))
        diagnostics["generation_kept"] = int(generation_stats["calibration"].get("kept", 0))
        dataset_rows.append(diagnostics)
        physical = {route.route_id: set(route.physical_edge_ids) for route in subset}
        eligible = {route.route_id: set(route.eligible_edge_ids) for route in subset}
        print(f"n={size}", flush=True)
        streaming = _run_streaming(
            size,
            physical,
            eligible,
            eligible_ids,
            heldout,
            settings,
            previous_streaming,
            threshold,
            louvain_seed,
            lam,
            budget,
            timing_runs,
            memory_rows,
        )
        timing_summary.append(streaming["summary"])
        if streaming["summary"]["status"] == "measured":
            previous_streaming = streaming["summary"]
            graph_rows.append(streaming["graph"])
            stage_rows.append(streaming["stages"])
            placement_rows.append(streaming["placement"])
        reference = streaming.get("reference")

        for banding in bandings:
            method = str(banding["method"])
            print(f"  {method}", flush=True)
            lsh = _run_lsh(
                size,
                method,
                banding,
                physical,
                eligible,
                eligible_ids,
                heldout,
                settings,
                threshold,
                louvain_seed,
                signature_seed,
                lam,
                budget,
                reference,
                timing_runs,
                memory_rows,
            )
            timing_summary.append(lsh["summary"])
            if lsh.get("candidates"):
                candidate_rows.append(lsh["candidates"])
            if lsh.get("graph"):
                graph_rows.append(lsh["graph"])
            if lsh.get("stages"):
                stage_rows.append(lsh["stages"])
            if lsh.get("validation"):
                validation_rows.append(lsh["validation"])
            if lsh.get("placement"):
                placement = lsh["placement"]
                if method == "verified_lsh" and placement.get("selected"):
                    current = tuple(part for part in str(placement["selected"]).split("|") if part)
                    if previous_primary is not None:
                        shared = len(set(current) & set(previous_primary))
                        union = len(set(current) | set(previous_primary))
                        placement["jaccard_vs_previous_size"] = shared / union if union else 1.0
                    previous_primary = current
                placement_rows.append(placement)

        if reference is not None:
            del reference
        gc.collect()

    _write_csv(output / "dataset_diagnostics.csv", dataset_rows)
    _write_csv(output / "timing_runs.csv", timing_runs)
    _write_csv(output / "timing_summary.csv", timing_summary)
    _write_csv(output / "memory_results.csv", memory_rows)
    _write_csv(output / "candidate_statistics.csv", candidate_rows)
    _write_csv(output / "graph_statistics.csv", graph_rows)
    _write_csv(output / "validation_results.csv", validation_rows)
    _write_csv(output / "selected_placements.csv", placement_rows)
    _write_csv(output / "stage_times.csv", stage_rows)
    plot_runtime(timing_summary, output / "runtime.png")
    plot_memory(timing_summary, output / "memory.png")
    plot_candidates(candidate_rows, output / "candidates.png")
    plot_stages(stage_rows, output / "stages.png")
    plot_graph_growth(graph_rows, output / "graph_growth.png")
    plot_agreement(validation_rows, output / "agreement.png")
    summary = {
        "scenario": settings["scenario"],
        "seed": int(settings["seed"]),
        "evaluation_seed": int(settings["evaluation_seed"]),
        "sizes_requested": sizes,
        "sizes_run": runnable,
        "n_generated": len(generated),
        "n_heldout": len(evaluation),
        "generation_seconds": generation_seconds,
        "generation_stats": generation_stats["calibration"],
        "routes_are_simulated": True,
        "duplicate_physical_sets_in_kept_sample": dataset_rows[-1]["duplicate_fraction"] if dataset_rows else None,
        "timing_excludes_tracemalloc": True,
        "memory_measurement": "tracemalloc peak MB, separate from timing repeats",
        "python": sys.version,
        "platform": platform.platform(),
        "networkx": version("networkx"),
        "primary_banding": settings["primary_banding"],
        "comparison_bandings": settings["comparison_bandings"],
        "output_dir": OUTPUT_DIRNAME,
    }
    (output / "benchmark_config.json").write_text(json.dumps(settings, indent=2) + "\n")
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    after = _fingerprint()
    if before != after:
        changed = [path for path in PROTECTED if before.get(path) != after.get(path)]
        raise SystemExit(f"canonical artifacts changed: {changed}")
    print(f"Wrote {output}", flush=True)


def _run_streaming(
    size,
    physical,
    eligible,
    eligible_ids,
    heldout,
    settings,
    previous,
    threshold,
    louvain_seed,
    lam,
    budget,
    timing_runs,
    memory_rows,
) -> dict[str, Any]:
    through = int(settings["streaming_exact_through"])
    probe_sizes = {int(value) for value in settings["streaming_probe_sizes"]}
    if size <= through or size in probe_sizes:
        repeats = _count(settings["timing_repeats"], size)
        memory_repeats = _count(settings["memory_repeats"], size)
        budget_s = (
            float(settings["streaming_probe_budget_seconds"])
            if size in probe_sizes
            else float(settings["repeat_budget_seconds"])
        )
    elif previous is not None and allow_streaming_extension(previous, settings):
        repeats = int(settings["streaming_extended_timing_repeats"])
        memory_repeats = int(settings["streaming_extended_memory_repeats"])
        budget_s = float(settings["repeat_budget_seconds"])
    else:
        reason = "streaming exact was not extended: the pre-specified time or edge rule was not met"
        if previous is None:
            reason = "streaming exact was not run at this size"
        return {
            "summary": _blank_summary(size, "streaming_exact", "not_run", reason),
            "reference": None,
        }

    def pipeline(routes=physical, placement_routes=eligible):
        graph = run_streaming(routes, threshold)
        labels, selected = _place(eligible_ids, placement_routes, graph, louvain_seed, lam, budget)
        return graph, labels, selected

    values, first, stopped = _repeats(pipeline, repeats, budget_s, size, "streaming_exact", "timing", timing_runs)
    summary = _time_summary(size, "streaming_exact", values, stopped)
    graph, labels, selected = first
    structure = graph_structure(graph)
    communities = community_structure(labels, _sizes_from_labels(labels))
    summary["n_edges"] = structure["n_edges"]
    peaks = _memory(pipeline, memory_repeats, size, "streaming_exact", memory_rows)
    if peaks:
        summary["median_peak_mb"] = summarize_times(peaks).median
    stages = streaming_stage_profile(
        physical,
        eligible,
        eligible_ids,
        threshold=threshold,
        louvain_seed=louvain_seed,
        lam=lam,
        k=budget,
    )
    stages.update({"n_routes": size, "method": "streaming_exact", "status": "measured"})
    graph_row = {"n_routes": size, "method": "streaming_exact", "status": "measured", **structure, **communities}
    reference = {"graph": graph, "labels": labels, "selected": selected}
    own = placement_record(selected, labels, eligible, heldout)
    placement = {
        "n_routes": size,
        "method": "streaming_exact",
        "status": "measured",
        "selected": "|".join(selected),
        "calibration_coverage": own["calibration_coverage"],
        "heldout_coverage": own["heldout_coverage"],
        "jaccard_vs_previous_size": "",
    }
    return {
        "summary": summary,
        "reference": reference,
        "graph": graph_row,
        "stages": stages,
        "placement": placement,
    }


def _run_lsh(
    size,
    method,
    banding,
    physical,
    eligible,
    eligible_ids,
    heldout,
    settings,
    threshold,
    louvain_seed,
    signature_seed,
    lam,
    budget,
    reference,
    timing_runs,
    memory_rows,
) -> dict[str, Any]:
    num_perm = int(banding["num_perm"])
    bands = int(banding["bands"])
    rows = int(banding["rows"])
    try:
        stages = lsh_stage_profile(
            physical,
            eligible,
            eligible_ids,
            num_perm=num_perm,
            bands=bands,
            rows=rows,
            threshold=threshold,
            seed=signature_seed,
            louvain_seed=louvain_seed,
            lam=lam,
            k=budget,
            max_pairs=int(settings["max_candidate_pairs"]),
            max_bucket_size=int(settings["max_bucket_size"]),
        )
    except ResourceLimit as exc:
        summary = _blank_summary(size, method, "resource_limit", exc.reason)
        summary.update(exc.observed)
        return {"summary": summary, "candidates": {**summary, "status": "resource_limit"}}

    def pipeline(routes=physical, placement_routes=eligible):
        graph, candidates, _verified = verified_lsh_graph(
            routes,
            num_perm=num_perm,
            bands=bands,
            rows=rows,
            threshold=threshold,
            seed=signature_seed,
        )
        labels, selected = _place(eligible_ids, placement_routes, graph, louvain_seed, lam, budget)
        return graph, labels, selected, candidates

    repeats = _count(settings["timing_repeats"], size)
    values, first, stopped = _repeats(
        pipeline,
        repeats,
        float(settings["repeat_budget_seconds"]),
        size,
        method,
        "timing",
        timing_runs,
    )
    graph, labels, selected, candidates = first
    if len(candidates) != int(stages["n_candidates"]):
        raise SystemExit(f"{method} candidate count changed between the stage pass and the timed pipeline at n={size}")
    summary = _time_summary(size, method, values, stopped)
    peaks = _memory(
        pipeline,
        _count(settings["memory_repeats"], size),
        size,
        method,
        memory_rows,
    )
    if peaks:
        summary["median_peak_mb"] = summarize_times(peaks).median
    structure = graph_structure(graph)
    communities = community_structure(labels, _sizes_from_labels(labels))
    summary["n_edges"] = structure["n_edges"]
    stages.update({"n_routes": size, "method": method, "status": "measured"})
    candidate_row = {
        "n_routes": size,
        "method": method,
        "status": "measured",
        **candidate_statistics(len(candidates), len(physical)),
        "n_buckets": stages["n_buckets"],
        "n_bucket_entries": stages["n_bucket_entries"],
        "largest_bucket": stages["largest_bucket"],
        "query_s": stages["query_s"],
        "verify_s": stages["verify_s"],
        "signatures_s": stages["signatures_s"],
    }
    graph_row = {"n_routes": size, "method": method, "status": "measured", **structure, **communities}
    validation = _validate(
        size,
        method,
        graph,
        labels,
        selected,
        physical,
        eligible,
        heldout,
        reference,
        settings,
        threshold,
    )
    placement = {
        "n_routes": size,
        "method": method,
        "status": "measured",
        "selected": "|".join(selected),
        "calibration_coverage": validation["calibration_coverage"],
        "heldout_coverage": validation.get("heldout_coverage", ""),
        "jaccard_vs_previous_size": "",
    }
    return {
        "summary": summary,
        "candidates": candidate_row,
        "graph": graph_row,
        "stages": stages,
        "validation": validation,
        "placement": placement,
    }


def _validate(size, method, graph, labels, selected, physical, eligible, heldout, reference, settings, threshold):
    record = {
        "n_routes": size,
        "method": method,
        "full_exact_available": 0,
        "subset_only": 0,
        **placement_record(selected, labels, eligible, heldout),
    }
    if reference is not None:
        record.update(exact_agreement(reference["graph"], graph, reference["labels"], labels))
        exact_place = placement_record(
            reference["selected"],
            reference["labels"],
            eligible,
            heldout,
        )
        lsh_on_exact = placement_record(
            selected,
            labels,
            eligible,
            heldout,
            reference_labels=reference["labels"],
            reference_selected=reference["selected"],
        )
        record["exact_calibration_coverage"] = exact_place["calibration_coverage"]
        record["exact_heldout_coverage"] = exact_place["heldout_coverage"]
        record["calibration_coverage_difference"] = (
            float(record["calibration_coverage"]) - float(exact_place["calibration_coverage"])
        )
        record["heldout_coverage_difference"] = (
            None
            if record["heldout_coverage"] is None or exact_place["heldout_coverage"] is None
            else float(record["heldout_coverage"]) - float(exact_place["heldout_coverage"])
        )
        record["n_shared_with_exact"] = lsh_on_exact["n_shared_with_exact"]
        record["selected_jaccard_vs_exact"] = lsh_on_exact["selected_jaccard_vs_exact"]
        record["large_represented_fraction_on_exact_partition"] = lsh_on_exact["large_represented_fraction"]
        record["exact_large_represented_fraction"] = exact_place["large_represented_fraction"]
        return record
    route_ids = list(physical)
    subset_n = min(int(settings["subset_recall_routes"]), len(route_ids))
    if subset_n >= 2 and method == "verified_lsh":
        indexes = subset_indexes(len(route_ids), subset_n, int(settings["subset_recall_seed"]))
        record.update(subset_edge_recall(graph, route_ids, physical, indexes, threshold))
        record["subset_seed"] = int(settings["subset_recall_seed"])
        record["subset_only"] = 1
        record["full_exact_available"] = 0
    return record


def _count(table: dict, size: int) -> int:
    if size in table:
        return int(table[size])
    return int(table[str(size)])


def _place(eligible_ids, routes, graph, louvain_seed, lam, budget):
    labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
    selected, _weights = balanced_selection(eligible_ids, routes, labels, lam, budget)
    if len(selected) != budget or len(set(selected)) != budget:
        raise RuntimeError("placement did not return K distinct counters")
    return labels, selected


def _sizes_from_labels(labels: dict[str, int]) -> list[int]:
    counts: dict[int, int] = {}
    for label in labels.values():
        counts[label] = counts.get(label, 0) + 1
    return list(counts.values())


def _repeats(pipeline, repeats, budget_s, size, method, measurement, sink):
    values = []
    first = None
    stopped = False
    for repeat in range(repeats):
        value, elapsed = elapsed_call(pipeline)
        values.append(elapsed)
        sink.append(
            {
                "n_routes": size,
                "method": method,
                "repeat": repeat,
                "measurement": measurement,
                "seconds": elapsed,
                "status": "measured",
            }
        )
        if first is None:
            first = value
        else:
            del value
        print(f"    {method} repeat {repeat + 1}/{repeats}: {elapsed:.3f}s", flush=True)
        if elapsed > budget_s and repeat + 1 < repeats:
            stopped = True
            break
    if first is None:
        raise RuntimeError("pipeline produced no repeat")
    return values, first, stopped


def _memory(pipeline, repeats, size, method, sink) -> list[float]:
    peaks = []
    for repeat in range(repeats):
        gc.collect()
        _value, elapsed, peak = tracked_call(pipeline)
        del _value
        peaks.append(peak)
        sink.append(
            {
                "n_routes": size,
                "method": method,
                "repeat": repeat,
                "measurement": "tracemalloc_peak_mb",
                "value": peak,
                "traced_seconds_not_for_runtime": elapsed,
                "status": "measured",
            }
        )
    return peaks


def _time_summary(size, method, values, stopped) -> dict[str, Any]:
    summary = summarize_times(values, stopped_early=stopped)
    return {
        "n_routes": size,
        "method": method,
        "status": "measured",
        "n_timing_repeats": len(values),
        "median_seconds": summary.median,
        "min_seconds": summary.minimum,
        "max_seconds": summary.maximum,
        "stdev_seconds": "" if summary.stdev is None else summary.stdev,
        "stopped_early": int(stopped),
        "reason": "repeat budget reached" if stopped else "",
    }


def _blank_summary(size, method, status, reason) -> dict[str, Any]:
    return {
        "n_routes": size,
        "method": method,
        "status": status,
        "reason": reason,
        "n_timing_repeats": 0,
        "median_seconds": "",
        "min_seconds": "",
        "max_seconds": "",
        "stdev_seconds": "",
        "stopped_early": "",
        "median_peak_mb": "",
        "n_edges": "",
    }


def _candidate_ids(path: Path) -> list[str]:
    with path.open(newline="") as handle:
        return [row["physical_edge_id"] for row in csv.DictReader(handle)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if row.get(key) is None else row.get(key, "") for key in fields})


def _fingerprint() -> dict[str, str]:
    found = {}
    for relative in PROTECTED:
        path = ROOT / relative
        if path.is_file():
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


if __name__ == "__main__":
    main()
