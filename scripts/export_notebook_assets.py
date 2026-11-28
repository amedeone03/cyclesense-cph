"""Copy compact validated tables into notebooks/assets.

The notebook reads these files. It does not rerun the studies. Run this
script from a checkout that already contains the saved outputs. It does
not modify those outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

ASSETS = ROOT / "notebooks" / "assets"
SOURCES: list[tuple[str, str]] = []


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    dataset = _dataset()
    _write_json("dataset.json", dataset)
    _write_rows("baselines.csv", _baselines())
    _write_rows("exact_comparison.csv", _exact())
    _write_rows("fair_timing.csv", _csv("outputs/scalability/timing_summary.csv"))
    _write_rows(
        "lsh_candidates.csv",
        [row for row in _csv("outputs/scalability/candidate_statistics.csv") if row["method"] == "verified_lsh"],
    )
    _write_json("similarity_graph.json", _similarity())
    _write_rows("community_placement.csv", _community_placement())
    _write_rows("lsh_communities.csv", _lsh_communities())
    _write_rows("integrated_timing.csv", _integrated_timing())
    _write_rows("route_choice.csv", _csv("outputs/route_choice/aggregate_coverage.csv"))
    _write_rows("robust_fresh.csv", _robust())
    _write_json("stability.json", _stability())
    _write_rows("municipal_coverage.csv", _municipal())
    _write_rows("infrastructure_coverage.csv", _csv("outputs/infrastructure/coverage_comparison.csv"))
    _write_rows("infrastructure_policies.csv", _csv("outputs/infrastructure/candidate_policy_summary.csv"))
    _write_rows("redundancy_sites.csv", _redundancy_sites())
    _write_rows("redundancy_multiplicity.csv", _csv("outputs/municipal_redundancy/coverage_multiplicity.csv"))
    _write_rows("aadt_association.csv", _csv("outputs/municipal_redundancy/aadt_comparison.csv"))
    _write_rows("community_ablation.csv", _ablation())
    provenance = {
        "exported_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "note": "Copied or aggregated from saved CycleSense outputs. Numbers were not typed by hand.",
        "sources": [
            {"path": path, "sha256": _sha(ROOT / path)}
            for path in dict.fromkeys(path for _name, path in SOURCES)
        ],
    }
    (ASSETS / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {ASSETS.relative_to(ROOT)}")


def _dataset() -> dict:
    summary = _json("data/processed/m1/summary.json")
    lengths = []
    with (ROOT / "data/processed/m1/routes.csv").open(newline="", encoding="utf-8") as handle:
        SOURCES.append(("route_lengths", "data/processed/m1/routes.csv"))
        for row in csv.DictReader(handle):
            n_edges = len([part for part in row["physical_edge_ids"].split("|") if part])
            lengths.append({"scenario": row["scenario"], "split": row["split"], "n_edges": n_edges})
    _write_rows("route_lengths.csv", lengths)
    graph = summary["graph"]
    routes = summary["routes"]
    return {
        "boundary": summary["boundary"],
        "extraction_utc": summary["extraction_utc"],
        "source": {
            "provider": summary["source"]["provider"],
            "access": summary["source"]["access"],
            "license": summary["source"]["license"],
            "attribution": summary["source"]["attribution"],
            "osmnx_version": summary["source"]["osmnx_version"],
        },
        "projected_crs": summary["projected_crs"],
        "graph": {
            "routing_nodes": graph["routing_nodes"],
            "routing_edges": graph["routing_edges"],
            "physical_segments": graph["physical_segments"],
            "candidates": graph["candidates"],
        },
        "routes": {
            "calibration": routes["calibration"],
            "evaluation": routes["evaluation"],
            "valid_total": routes["valid_total"],
            "seeds": routes["seeds"],
            "scenario_weight_meaning": routes["scenario_weight_meaning"],
        },
        "osm_pbf_sha256": _manifest()["osm"]["sha256"],
        "municipal_snapshot_sha256": _manifest()["municipal"]["sha256"],
    }


def _baselines() -> list[dict]:
    kept = []
    for row in _csv("outputs/m2/results.csv"):
        if row["k"] not in {"5", "10", "20", "30"}:
            continue
        if row["method"] == "random" and row["seed"] != "42":
            continue
        if row["method"] == "geographical_kmeans" and row["seed"] != "42":
            continue
        if row["method"] in {"greedy", "route_frequency"} and row["seed"] != "":
            continue
        kept.append({key: row[key] for key in ("scenario", "method", "k", "seed", "calibration_coverage", "heldout_coverage")})
    return kept


def _exact() -> list[dict]:
    fields = (
        "scenario", "k", "status", "proven_optimal", "exact_coverage", "greedy_coverage",
        "absolute_gap", "relative_gap", "n_shared", "jaccard", "heldout_greedy", "heldout_exact", "milp_seconds",
    )
    return [
        {key: row[key] for key in fields}
        for row in _csv("outputs/exact_optimization/greedy_comparison.csv")
        if row["objective"] == "unweighted"
    ]


def _similarity() -> dict:
    summary = _json("outputs/m3/summary.json")
    m4 = _json("outputs/m4/summary.json")
    return {
        "primary_threshold": summary["primary_threshold"],
        "operating_points": summary["operating_points"],
        "graph_threshold_0_5": [row for row in summary["graph"] if row["threshold"] == 0.5],
        "communities_threshold_0_5": m4["communities"],
    }


def _community_placement() -> list[dict]:
    fields = (
        "scenario", "threshold", "lambda", "k", "calibration_coverage", "heldout_coverage",
        "represented_fraction", "matches_m2_greedy",
    )
    rows = []
    for row in _csv("outputs/m4/placements.csv"):
        if row["source"] != "louvain" or row["threshold"] != "0.5" or row["lambda"] not in {"0.0", "0.25"}:
            continue
        if row["k"] not in {"5", "10", "20"}:
            continue
        rows.append({key: row[key] for key in fields})
    return rows


def _lsh_communities() -> list[dict]:
    summary = _json("outputs/integrated/summary.json")
    fields = (
        "scenario", "role", "num_perm", "bands", "rows", "graph_edge_recall", "n_edges_missed",
        "adjusted_rand_index", "exact_communities", "approximate_communities", "exact_singletons",
        "approximate_singletons",
    )
    return [{key: row[key] for key in fields} for row in summary["communities"]]


def _integrated_timing() -> list[dict]:
    summary = _json("outputs/integrated/summary.json")
    fields = (
        "n_routes", "method", "label", "n_edges", "adjusted_rand_index", "n_shared",
        "selected_jaccard", "median_seconds", "n_timing_repeats", "median_peak_mb",
    )
    return [{key: row[key] for key in fields} for row in summary["fair_timing_summary"]]


def _robust() -> list[dict]:
    summary = _json("outputs/robust_placement/summary.json")
    rows = []
    for row in summary["fresh_results"]:
        if row["k"] != 10 or row["condition"] not in {"0.15", "shortest"}:
            continue
        rows.append({
            "scenario": row["scenario"],
            "method": row["method"],
            "k": row["k"],
            "condition": row["condition"],
            "n_seeds": row["n_seeds"],
            "coverage_mean": row["coverage_mean"],
            "shortest_coverage": row["shortest_coverage"],
            "loss_percentage_points": row["loss_percentage_points"],
        })
    return rows


def _stability() -> dict:
    summary = _json("outputs/placement_stability/summary.json")
    groups = [
        {
            "method": row["method"],
            "scenario": row["scenario"],
            "k": row["k"],
            "n_ever_selected": row["n_ever_selected"],
            "n_always": row["n_always"],
            "mean_jaccard": row["mean_jaccard"],
            "median_jaccard": row["median_jaccard"],
            "p05_jaccard": row["p05_jaccard"],
            "p95_jaccard": row["p95_jaccard"],
            "mean_shared": row["mean_shared"],
            "calibration_mean": row["calibration_mean"],
            "heldout_mean": row["heldout_mean"],
            "heldout_min": row["heldout_min"],
            "heldout_max": row["heldout_max"],
        }
        for row in summary["groups"]
        if row["method"] == "greedy" and row["k"] == 10
    ]
    tops = []
    for block in summary["top_segments"]:
        if block["method"] == "greedy" and block["k"] == 10 and block["scenario"] == "uniform":
            tops = block["segments"][:8]
    return {
        "headline": summary["headline"],
        "n_replicates": summary["n_replicates"],
        "calibration_routes": summary["calibration_routes"],
        "selection_frequency_is_not_cyclist_demand": summary["selection_frequency_is_not_cyclist_demand"],
        "groups": groups,
        "uniform_k10_top": [
            {
                "street_name": row["street_name"],
                "physical_edge_id": row["physical_edge_id"],
                "selection_frequency": row["selection_frequency"],
            }
            for row in tops
        ],
    }


def _municipal() -> list[dict]:
    fields = (
        "scenario", "budget_new", "held_out_existing_coverage", "calibration_existing_coverage",
        "held_out_existing_plus_new", "calibration_existing_plus_new", "held_out_marginal_gain", "n_added",
    )
    return [
        {key: row[key] for key in fields}
        for row in _csv("outputs/standout/coverage.csv")
        if row["budget_new"] in {"5", "10"}
    ]


def _redundancy_sites() -> list[dict]:
    fields = (
        "scenario", "split", "street", "description", "physical_edge_id", "bike_aadt",
        "traversal_fraction", "unique_fraction", "leave_one_out_pp", "shapley_pp", "shared_routes",
    )
    return [
        {key: row[key] for key in fields}
        for row in _csv("outputs/municipal_redundancy/site_contributions.csv")
        if row["split"] == "calibration"
    ]


def _ablation() -> list[dict]:
    summary = _json("outputs/m5/summary.json")
    return [
        row for row in summary["ablation_k10"]
        if row["lambda"] == 0.25 and row["metric"] == "heldout_coverage"
    ]


def _manifest() -> dict:
    return yaml.safe_load((ROOT / "configs/reproducibility.yaml").read_text(encoding="utf-8"))


def _csv(relative: str) -> list[dict]:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"Missing source artifact: {relative}")
    SOURCES.append((Path(relative).name, relative))
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _json(relative: str) -> dict:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"Missing source artifact: {relative}")
    SOURCES.append((Path(relative).name, relative))
    return json.loads(path.read_text(encoding="utf-8"))


def _write_rows(name: str, rows: list[dict]) -> None:
    if not rows:
        raise SystemExit(f"{name} would be empty")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with (ASSETS / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(name: str, payload: dict) -> None:
    (ASSETS / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
