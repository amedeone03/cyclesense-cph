"""Draw the municipal counting locations and the complementary greedy sites.

This reads the canonical M1 graph and routes, plus the cached municipal CSV.
It writes only ``outputs/standout/standout_counters.html``,
``outputs/standout/standout_counters.png``, and, when the local
PBF can be read, a display-basemap cache beside that file. It does not modify
M1–M5 artifacts and it does not refresh the municipal download.

    python scripts/map_standout.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from run_external_validation import load_segments

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.basemap import load_context_basemap
from cyclesense.coverage import evaluate_coverage
from cyclesense.external_validation import (
    PRIMARY_SAMPLE,
    evaluate_extension,
    load_count_sites,
    load_route_records,
)
from cyclesense.standout_map import (
    FIRST_COLOR,
    NEXT_COLOR,
    addition_tranches,
    default_addition_visible,
    write_standout_map,
    write_standout_static,
)

COUNTS_PATH = REPO_ROOT / "data" / "external" / "trafiktal.csv"
OUTPUT_DIR = REPO_ROOT / "outputs" / "standout"
MAP_PATH = OUTPUT_DIR / "standout_counters.html"
SUMMARY_PATH = OUTPUT_DIR / "summary.json"


def main() -> None:
    artifacts = validated_m1_artifacts(REPO_ROOT)
    if artifacts is None:
        raise SystemExit(
            "M1 artifacts are missing or incomplete. Run python scripts/run_m1.py first. "
            "This map does not rebuild them."
        )
    if not COUNTS_PATH.is_file():
        raise SystemExit(
            "Municipal CSV is missing. Run python scripts/run_external_validation.py first. "
            "This map does not download a new file."
        )
    config = _load_config(REPO_ROOT / "configs" / "pilot.yaml")
    sites = load_count_sites(COUNTS_PATH)
    routes = load_route_records(artifacts["routes"])
    segments = load_segments(artifacts["routing_wgs84"], artifacts["candidates"])
    study = config["study_area"]
    anchor_cfg = config["simulation"]["commuter_proxy"]
    bbox = (float(study["west"]), float(study["south"]), float(study["east"]), float(study["north"]))
    result = evaluate_extension(
        sites,
        segments,
        routes,
        bbox=bbox,
        anchor=(float(anchor_cfg["anchor_lon"]), float(anchor_cfg["anchor_lat"])),
        anchor_name=str(anchor_cfg["anchor_name"]),
        budgets=(5, 10),
    )
    _check_recorded_edges(result)
    geometry = {segment.physical_edge_id: segment for segment in segments}
    primary = result["samples"][PRIMARY_SAMPLE]["alignment_rows"]
    existing = [_existing_site(row, geometry) for row in primary]
    layers = []
    coverage = []
    for scenario in result["coverage"]:
        by_budget = {int(row["budget_new"]): list(row["added_edges"]) for row in scenario["budgets"]}
        first, nxt = addition_tranches(by_budget)
        name = str(scenario["scenario"])
        gains = _calibration_gains(
            routes,
            name,
            [row["physical_edge_id"] for row in primary],
            list(by_budget[10]),
        )
        layers.append(_addition_layer(name, "first", first, geometry, gains, start_rank=1))
        layers.append(_addition_layer(name, "next", nxt, geometry, gains, start_rank=len(first) + 1))
        plus = {int(row["budget_new"]): float(row["held_out_existing_plus_new"]) for row in scenario["budgets"]}
        coverage.append(
            {
                "scenario": name,
                "existing": float(scenario["held_out_existing_coverage"]),
                "plus_5": plus[5],
                "plus_10": plus[10],
            }
        )
    metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))
    basemap = _basemap(metadata, bbox)
    output = write_standout_map(
        existing,
        layers,
        coverage,
        MAP_PATH,
        boundary=bbox,
        basemap=basemap,
        notes=_notes(primary, result),
    )
    static = write_standout_static(
        existing,
        layers,
        OUTPUT_DIR / "standout_counters.png",
        context=[segment.polyline for segment in segments],
        boundary=bbox,
    )
    print(f"Wrote {output.relative_to(REPO_ROOT)}", flush=True)
    print(f"Wrote {static.relative_to(REPO_ROOT)}", flush=True)
    print(f"Name-verified locations: {len(existing)}", flush=True)
    for row in coverage:
        print(
            f"{row['scenario']}: existing {row['existing']:.3f}, "
            f"+5 {row['plus_5']:.3f}, +10 {row['plus_10']:.3f}",
            flush=True,
        )


def _existing_site(row: dict[str, Any], geometry: dict[str, Any]) -> dict[str, Any]:
    edge_id = str(row["physical_edge_id"])
    segment = geometry.get(edge_id)
    if segment is None:
        raise SystemExit(f"No M1 geometry for municipal segment {edge_id}")
    return {
        "edge_id": edge_id,
        "line": _latlon(segment.polyline),
        "street": row.get("street") or "",
        "osm_name": segment.name,
        "aadt": row.get("bike_aadt"),
        "year": row.get("year"),
        "count_type": row.get("count_type") or "",
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "snap_m": row.get("distance_m"),
    }


def _calibration_gains(routes, scenario: str, existing: list[str], ordered: list[str]) -> dict[str, float]:
    """Marginal calibration coverage of each added segment, in greedy order."""
    calibration = {
        route.route_id: set(route.physical_edge_ids)
        for route in routes
        if route.scenario == scenario and route.split == "calibration"
    }
    previous = evaluate_coverage(calibration, existing).coverage_fraction
    chosen = list(existing)
    gains: dict[str, float] = {}
    for edge in ordered:
        chosen.append(edge)
        current = evaluate_coverage(calibration, chosen).coverage_fraction
        gains[edge] = current - previous
        previous = current
    return gains


def _addition_layer(
    scenario: str,
    tranche: str,
    edge_ids: tuple[str, ...],
    geometry: dict[str, Any],
    gains: dict[str, float],
    *,
    start_rank: int,
) -> dict[str, Any]:
    label = "Additional 5" if tranche == "first" else "Next 5"
    pretty = "uniform" if scenario == "uniform" else "commuter proxy"
    sites = []
    for rank, edge_id in enumerate(edge_ids, start=start_rank):
        segment = geometry.get(edge_id)
        if segment is None:
            raise SystemExit(f"No M1 geometry for additional segment {edge_id}")
        sites.append(
            {
                "edge_id": edge_id,
                "line": _latlon(segment.polyline),
                "osm_name": segment.name,
                "scenario": scenario,
                "rank": rank,
                "calibration_gain": gains.get(edge_id),
            }
        )
    return {
        "name": f"{label} — {pretty}",
        "show": default_addition_visible(scenario, tranche),
        "color": FIRST_COLOR if tranche == "first" else NEXT_COLOR,
        "dash": "7 5" if scenario == "commuter_proxy" else "",
        "sites": sites,
    }


def _latlon(polyline: tuple[tuple[float, float], ...]) -> list[tuple[float, float]]:
    return [(float(lat), float(lon)) for lon, lat in polyline]


def _notes(rows: list[dict[str, Any]], result: dict[str, Any]) -> list[str]:
    notes = []
    tests = {
        (test.get("scenario"), test.get("comparison")): test
        for test in result["samples"][PRIMARY_SAMPLE]["rank_tests"]
    }
    for scenario, label in (("uniform", "uniform"), ("commuter_proxy", "commuter proxy")):
        test = tests.get((scenario, "modeled_traversals_vs_bike_aadt"))
        if test is None:
            continue
        notes.append(
            f"Primary Spearman, {label} calibration traversals vs published bicycle AADT: "
            f"rho {float(test['spearman_rho']):.3f}, "
            f"permutation p {float(test['permutation_p']):.3f}, n {test['n']}."
        )
    boundary = [
        row
        for row in rows
        if "dronning louises bro" in str(row.get("street") or "").casefold()
        and int(row.get("uniform_calibration_traversals") or 0) == 0
        and int(row.get("commuter_proxy_calibration_traversals") or 0) == 0
    ]
    if boundary:
        site = boundary[0]
        notes.append(
            f"{site['street']} published bicycle AADT {int(site['bike_aadt']):,} and has zero "
            "simulated traversals in both scenarios. It lies on the west edge of the study "
            "rectangle, so routes that start and end inside the clipped graph do not cross it."
        )
    notes.append("The default additions are the uniform scenario. Switch layers for the commuter proxy.")
    return notes


def _check_recorded_edges(result: dict[str, Any]) -> None:
    """Stop if a saved summary disagrees about which edges were added."""
    if not SUMMARY_PATH.is_file():
        return
    saved = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    saved_rows = {row["scenario"]: row for row in saved.get("coverage") or []}
    for scenario in result["coverage"]:
        previous = saved_rows.get(scenario["scenario"])
        if previous is None:
            continue
        fresh = {int(row["budget_new"]): list(row["added_edges"]) for row in scenario["budgets"]}
        recorded = {int(row["budget_new"]): list(row["added_edges"]) for row in previous["budgets"]}
        for budget in (5, 10):
            if recorded.get(budget) != fresh.get(budget):
                raise SystemExit(
                    f"Complementary edges for {scenario['scenario']} K={budget} "
                    "do not match outputs/standout/summary.json. The map was not written."
                )


def _basemap(metadata: dict[str, Any], bbox: tuple[float, float, float, float]) -> dict[str, Any] | None:
    pbf = Path(str(metadata.get("pbf_path") or REPO_ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"))
    if not pbf.is_file():
        pbf = REPO_ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"
    if not pbf.is_file():
        print("Local basemap unavailable. Writing the segment view without context geometry.", flush=True)
        return None
    print(f"Reading geographical context from {pbf}", flush=True)
    return load_context_basemap(pbf, bbox, OUTPUT_DIR / "context_basemap.json")


def _load_config(path: Path) -> dict[str, Any]:
    import yaml

    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path} did not contain a mapping")
    return loaded


if __name__ == "__main__":
    main()
