"""Run the M1 central-Copenhagen pilot: graph, candidates, and two route scenarios.

From the repository root, with analysis dependencies installed:

    python scripts/run_m1.py

The OpenStreetMap download is cached. Generated graphs, routes, and maps are
written under data/ and outputs/, which Git ignores. Re-running reuses a
matching graph snapshot unless --force-download is set.

This does not place counters and it does not estimate bicycle traffic.
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from cyclesense.assumptions import (
    BIDIRECTIONAL_COUNTING,
    ELIGIBILITY_IS_A_PROXY,
    NOT_OBSERVED_DEMAND,
)
from cyclesense.network import (
    PIPELINE_VERSION,
    add_contraflow_edges,
    assign_physical_edge_ids,
    audit_topology,
    bbox_polygon,
    bike_graph_from_pbf,
    build_candidates,
    collect_quality_issues,
    configure_osmnx,
    drop_unroutable_edges,
    largest_strong_subgraph,
    nearest_node,
    node_coordinates,
    project_lonlat,
    project_to_metres,
    routing_feasibility,
)
from cyclesense.plotting import plot_study_maps
from cyclesense.routes import generate_modeled_routes, shared_route_keys
from cyclesense.sampling import IMPLEMENTED_OD_SCENARIOS
from cyclesense.validation import validate_m1_summary

CANDIDATE_FIELDS = [
    "physical_edge_id",
    "u",
    "v",
    "length_m",
    "highway",
    "name",
    "service",
    "bicycle",
    "n_directed",
    "oneway",
    "added_contraflow",
    "midpoint_lon",
    "midpoint_lat",
]


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Install analysis dependencies: pip install -e '.[analysis]'") from exc
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path} did not contain a mapping")
    return loaded


def _boundary_matches(metadata: dict[str, Any], study_area: dict[str, Any]) -> bool:
    boundary = metadata.get("boundary") or {}
    keys = ("west", "south", "east", "north")
    return all(boundary.get(key) == study_area[key] for key in keys)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _candidate_rows(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        row = dict(candidate)
        row["midpoint_lon"] = round(float(candidate["midpoint_x"]), 6)
        row["midpoint_lat"] = round(float(candidate["midpoint_y"]), 6)
        row.pop("midpoint_x", None)
        row.pop("midpoint_y", None)
        rows.append({key: row.get(key, "") for key in CANDIDATE_FIELDS})
    return rows


def run(config_path: Path, *, force_download: bool) -> dict[str, Any]:
    started = time.perf_counter()
    config = _load_config(config_path)
    study = config["study_area"]
    simulation = config["simulation"]
    candidate_cfg = config["candidates"]
    if not candidate_cfg.get("bidirectional_counting", False):
        raise SystemExit("M1 only implements bidirectional counting on physical segments.")
    scenarios = list(simulation["scenarios"])
    unsupported = [name for name in scenarios if name not in IMPLEMENTED_OD_SCENARIOS]
    if unsupported:
        raise SystemExit(
            f"M1 does not implement scenarios {unsupported}. Implemented: {IMPLEMENTED_OD_SCENARIOS}."
        )
    for key in ("west", "south", "east", "north"):
        if key not in study:
            raise SystemExit(f"study_area.{key} is required")

    data_dir = REPO_ROOT / "data" / "processed" / "m1"
    output_dir = REPO_ROOT / "outputs" / "m1"
    cache_dir = REPO_ROOT / "cache" / "osmnx"
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    full_path = data_dir / "copenhagen_bike_full.graphml"
    routing_path = data_dir / "copenhagen_bike_routing_wgs84.graphml"
    projected_path = data_dir / "copenhagen_bike_routing_projected.graphml"
    metadata_path = data_dir / "extraction_metadata.json"

    download_started = time.perf_counter()
    reused = False
    ox = configure_osmnx(str(cache_dir))
    if full_path.exists() and metadata_path.exists() and not force_download:
        stored = json.loads(metadata_path.read_text(encoding="utf-8"))
        if stored.get("pipeline_version") == PIPELINE_VERSION and _boundary_matches(stored, study):
            full_graph = ox.load_graphml(full_path)
            metadata = stored
            reused = True
    if not reused:
        polygon = bbox_polygon(study["west"], study["south"], study["east"], study["north"])
        print("Building the bike graph with OSMnx from the Copenhagen OSM extract...", flush=True)
        full_graph, metadata = bike_graph_from_pbf(
            polygon,
            cache_folder=str(cache_dir),
            pbf_cache=REPO_ROOT / "cache" / "osm",
            simplify=bool(study.get("simplify", True)),
            retain_all=bool(study.get("retain_all", True)),
            truncate_by_edge=bool(study.get("truncate_by_edge", False)),
            force_download=force_download,
        )
        print(
            "Clipped extract before contraflow: "
            f"nodes={metadata['raw_nodes']} directed edges={metadata['raw_directed_edges']}",
            flush=True,
        )
    download_seconds = time.perf_counter() - download_started

    contraflow_added = add_contraflow_edges(full_graph)
    metadata["contraflow_edges_added"] = int(metadata.get("contraflow_edges_added") or 0) + contraflow_added
    assign_physical_edge_ids(full_graph)
    full_audit = audit_topology(full_graph)
    full_paths = routing_feasibility(full_graph, n_pairs=40, seed=0)

    routing = full_graph.copy()
    edges_removed = drop_unroutable_edges(routing)
    routing, scc_info = largest_strong_subgraph(routing)
    routing_audit = audit_topology(routing)
    routing_paths = routing_feasibility(routing, n_pairs=20, seed=1)
    candidates, candidate_stats = build_candidates(
        routing,
        min_length_m=float(candidate_cfg["min_length_m"]),
    )
    sample_node = next(iter(routing.nodes))
    longitude_before = float(routing.nodes[sample_node]["x"])
    projected, projected_crs = project_to_metres(routing)
    if abs(float(routing.nodes[sample_node]["x"]) - longitude_before) > 1e-7:
        raise RuntimeError("projecting the routing graph changed its WGS84 coordinates")
    coordinates = node_coordinates(projected)
    if set(coordinates) != {int(node) for node in routing.nodes}:
        raise RuntimeError("projected node ids do not match the WGS84 routing graph")
    if not coordinates or max(abs(point[0]) for point in coordinates.values()) < 10000:
        raise RuntimeError("projected coordinates do not look like metres; OD sampling was not run")

    anchor_cfg = simulation["commuter_proxy"]
    anchor_xy = project_lonlat(float(anchor_cfg["anchor_lon"]), float(anchor_cfg["anchor_lat"]), projected.graph["crs"])
    snap_node, snap_m = nearest_node(coordinates, anchor_xy)
    issues = [
        (
            "The study graph is an OSMnx bike network built from the BBBike Copenhagen "
            "OpenStreetMap PBF "
            f"({metadata.get('osm_data_timestamp')}, sha256 {metadata.get('pbf_sha256')}) "
            "and then clipped to the study rectangle. It is not a live Overpass query."
        )
    ]
    issues.extend(
        collect_quality_issues(
        full_audit=full_audit,
        edges_removed=edges_removed,
        scc_info=scc_info,
        full_feasibility=full_paths,
        routing_feasibility_stats=routing_paths,
        anchor_snap_m=snap_m,
        )
    )

    route_started = time.perf_counter()
    calibration_seed = int(simulation["random_seed"])
    evaluation_seed = calibration_seed + int(simulation["evaluation_seed_offset"])
    all_routes = []
    generation: list[dict[str, Any]] = []
    candidate_ids = {row["physical_edge_id"] for row in candidates}
    for scenario in scenarios:
        routes, stats = generate_modeled_routes(
            routing,
            coordinates,
            candidate_ids,
            scenario=scenario,
            n_calibration=int(simulation["calibration_routes"]),
            n_evaluation=int(simulation["held_out_routes"]),
            calibration_seed=calibration_seed,
            evaluation_seed=evaluation_seed,
            min_distance_m=float(simulation["min_od_distance_m"]),
            max_distance_m=float(simulation["max_od_distance_m"]),
            min_eligible_edges=int(simulation["min_eligible_edges"]),
            anchor_xy=anchor_xy if scenario == "commuter_proxy" else None,
            distance_floor_m=float(anchor_cfg.get("distance_floor_m", 50)),
            max_attempts_factor=int(simulation.get("max_attempts_factor", 60)),
        )
        all_routes.extend(routes)
        generation.append(stats)
        for split_name, split_stats in (("calibration", stats["calibration"]), ("evaluation", stats["evaluation"])):
            kept = int(split_stats["kept"])
            requested = int(split_stats["requested"])
            if kept < requested:
                issues.append(
                    f"{scenario} {split_name} kept {kept} of {requested} requested routes "
                    f"after distance, path, and eligibility filters."
                )
    route_seconds = time.perf_counter() - route_started
    overlap = shared_route_keys(all_routes)

    metadata.update(
        {
            "pipeline_version": PIPELINE_VERSION,
            "study_area_name": study["name"],
            "place_label": study.get("place_label"),
            "boundary": {
                "type": "bbox",
                "crs": study.get("crs", "EPSG:4326"),
                "west": study["west"],
                "south": study["south"],
                "east": study["east"],
                "north": study["north"],
            },
            "polygon_wkt": bbox_polygon(study["west"], study["south"], study["east"], study["north"]).wkt,
            "projected_crs": projected_crs,
            "preserve_oneway": bool(study.get("preserve_oneway", True)),
            "historical_osm_date": study.get("graph_snapshot_date"),
            "snapshot_note": (
                "graph_snapshot_date null means the live OpenStreetMap database at "
                "extraction_utc. Reuse the saved GraphML files rather than expecting "
                "a later Overpass query to match exactly."
            ),
            "commuter_proxy": {
                "anchor_name": anchor_cfg["anchor_name"],
                "anchor_lat": anchor_cfg["anchor_lat"],
                "anchor_lon": anchor_cfg["anchor_lon"],
                "anchor_easting_m": anchor_xy[0],
                "anchor_northing_m": anchor_xy[1],
                "snapped_node": snap_node,
                "snap_distance_m": round(snap_m, 2),
                "distance_floor_m": anchor_cfg.get("distance_floor_m", 50),
                "definition": (
                    "Origin weight is distance to the anchor plus a floor. "
                    "Destination weight is the reciprocal. This is a spatial proxy, "
                    "not observed commuting demand."
                ),
            },
            "assumptions": [NOT_OBSERVED_DEMAND, BIDIRECTIONAL_COUNTING, ELIGIBILITY_IS_A_PROXY],
        }
    )

    counts: dict[tuple[str, str], int] = {}
    for route in all_routes:
        counts[(route.split, route.scenario)] = counts.get((route.split, route.scenario), 0) + 1
    summary = {
        "boundary": metadata["boundary"],
        "extraction_utc": metadata.get("extraction_utc"),
        "source": {
            "provider": metadata.get("provider", "OpenStreetMap"),
            "access": metadata.get("access"),
            "license": metadata.get("license"),
            "attribution": metadata.get("attribution"),
            "osmnx_version": metadata.get("osmnx_version"),
            "networkx_version": metadata.get("networkx_version"),
            "overpass_url": metadata.get("overpass_url"),
            "overpass_filter": metadata.get("overpass_filter"),
            "network_type": metadata.get("network_type", "bike"),
            "bidirectional_network_types": metadata.get("bidirectional_network_types"),
        },
        "projected_crs": projected_crs,
        "graph_reused": reused,
        "graph": {
            "raw_nodes": int(full_audit["n_nodes"]),
            "raw_edges": int(full_audit["n_directed_edges"]),
            "routing_nodes": int(routing_audit["n_nodes"]),
            "routing_edges": int(routing_audit["n_directed_edges"]),
            "physical_segments": int(candidate_stats["n_physical_segments"]),
            "candidates": int(candidate_stats["n_candidates"]),
            "contraflow_edges_added": int(metadata["contraflow_edges_added"]),
            "edges_removed_before_routing": edges_removed,
            "scc": scc_info,
        },
        "routes": {
            "calibration": {scenario: counts.get(("calibration", scenario), 0) for scenario in scenarios},
            "evaluation": {scenario: counts.get(("evaluation", scenario), 0) for scenario in scenarios},
            "valid_total": len(all_routes),
            "seeds": {"calibration": calibration_seed, "evaluation": evaluation_seed},
            "shared_od_pairs": overlap["shared_od_pairs"],
            "shared_paths": overlap["shared_paths"],
            "scenario_weight": 1,
            "scenario_weight_meaning": "one accepted simulated draw, not a bicycle count",
            "generation": generation,
        },
        "audit": {
            "full": full_audit,
            "routing": routing_audit,
            "full_graph_path_sample": full_paths,
            "routing_graph_path_sample": routing_paths,
            "candidate_rejections": candidate_stats["rejection_counts"],
        },
        "data_quality_issues": issues,
        "assumptions": metadata["assumptions"],
        "runtime_seconds": {},
    }
    errors = validate_m1_summary(summary, min_routes_per_split=50)
    if candidate_stats["n_candidates"] < 30:
        errors.append("fewer than 30 candidate segments; the study area or eligibility rule is too tight")

    ox.save_graphml(full_graph, full_path)
    ox.save_graphml(routing, routing_path)
    ox.save_graphml(projected, projected_path)
    route_rows = [route.as_csv_row() for route in all_routes]
    route_fields = list(route_rows[0]) if route_rows else ["route_id"]
    _write_csv(data_dir / "candidates.csv", _candidate_rows(candidates), CANDIDATE_FIELDS)
    _write_csv(data_dir / "routes.csv", route_rows, route_fields)

    map_started = time.perf_counter()
    map_paths = plot_study_maps(
        routing,
        candidates,
        all_routes,
        output_dir,
        title_suffix=f"{study['name']} · extracted {metadata.get('extraction_utc')}",
        coordinate_note="WGS84 longitude (x) and latitude (y)",
    )
    map_seconds = time.perf_counter() - map_started
    for label, map_path in map_paths.items():
        if Path(map_path).stat().st_size < 1000:
            errors.append(f"{label} map is unexpectedly small")

    total_seconds = time.perf_counter() - started
    summary["runtime_seconds"] = {
        "download_or_load": round(download_seconds, 3),
        "routes": round(route_seconds, 3),
        "maps": round(map_seconds, 3),
        "total": round(total_seconds, 3),
    }
    summary["map_paths"] = map_paths
    summary["artifacts"] = {
        "full_graph": str(full_path.relative_to(REPO_ROOT)),
        "routing_graph_wgs84": str(routing_path.relative_to(REPO_ROOT)),
        "routing_graph_projected": str(projected_path.relative_to(REPO_ROOT)),
        "candidates": "data/processed/m1/candidates.csv",
        "routes": "data/processed/m1/routes.csv",
    }
    metadata["graph"] = summary["graph"]
    metadata["runtime_seconds"] = summary["runtime_seconds"]
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (data_dir / "audit.json").write_text(json.dumps(summary["audit"], indent=2), encoding="utf-8")
    (data_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if errors:
        summary["acceptance_errors"] = errors
        (data_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        raise SystemExit("M1 acceptance checks failed:\n- " + "\n- ".join(errors))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the CycleSense M1 network and route pilot")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "pilot.yaml")
    parser.add_argument("--force-download", action="store_true", help="Ignore a saved graph and query Overpass again")
    args = parser.parse_args()
    summary = run(args.config, force_download=args.force_download)
    graph = summary["graph"]
    routes = summary["routes"]
    print("CycleSense M1 pilot")
    print(f"Boundary WGS84: {summary['boundary']}")
    print(f"Extracted: {summary['extraction_utc']} · CRS {summary['projected_crs']}")
    print(
        f"Nodes {graph['routing_nodes']} (raw {graph['raw_nodes']}) · "
        f"directed edges {graph['routing_edges']} (raw {graph['raw_edges']}) · "
        f"physical segments {graph['physical_segments']} · candidates {graph['candidates']}"
    )
    print(
        f"Valid modeled routes: {routes['valid_total']} · "
        f"calibration {routes['calibration']} · evaluation {routes['evaluation']}"
    )
    print(f"Runtime seconds: {summary['runtime_seconds']}")
    if summary["data_quality_issues"]:
        print("Data-quality issues:")
        for issue in summary["data_quality_issues"]:
            print(f"- {issue}")
    else:
        print("Data-quality issues: none recorded")
    print(NOT_OBSERVED_DEMAND)
    print("M1 acceptance checks passed. Placement (M2) was not run.")


if __name__ == "__main__":
    main()
