"""Checks that an M1 summary has the fields the pilot must record.

A passing summary is not a claim about real cyclist flows. It only says the
extraction, candidate set, and two route splits were produced and separated.
"""

from typing import Any


def validate_m1_summary(summary: dict[str, Any], *, min_routes_per_split: int = 1) -> list[str]:
    """Return human-readable errors. An empty list means the summary is complete."""
    errors: list[str] = []
    boundary = summary.get("boundary") or {}
    for key in ("west", "south", "east", "north", "crs"):
        if boundary.get(key) is None:
            errors.append(f"boundary missing {key}")
    west, east = boundary.get("west"), boundary.get("east")
    south, north = boundary.get("south"), boundary.get("north")
    if isinstance(west, (int, float)) and isinstance(east, (int, float)) and west >= east:
        errors.append("boundary west must be less than east")
    if isinstance(south, (int, float)) and isinstance(north, (int, float)) and south >= north:
        errors.append("boundary south must be less than north")
    if not summary.get("extraction_utc"):
        errors.append("missing extraction timestamp")
    source = summary.get("source") or {}
    if "OpenStreetMap" not in str(source.get("provider", "")):
        errors.append("source provider must name OpenStreetMap")
    if not source.get("osmnx_version"):
        errors.append("missing OSMnx version")
    if not summary.get("projected_crs"):
        errors.append("missing projected CRS")
    graph = summary.get("graph") or {}
    if int(graph.get("routing_nodes") or 0) < 2:
        errors.append("routing graph needs at least two nodes")
    if int(graph.get("routing_edges") or 0) < 1:
        errors.append("routing graph has no edges")
    if int(graph.get("candidates") or 0) < 1:
        errors.append("no candidate segments")
    routes = summary.get("routes") or {}
    calibration = routes.get("calibration") or {}
    evaluation = routes.get("evaluation") or {}
    for scenario in ("uniform", "commuter_proxy"):
        if int(calibration.get(scenario) or 0) < min_routes_per_split:
            errors.append(f"too few calibration routes for {scenario}")
        if int(evaluation.get(scenario) or 0) < min_routes_per_split:
            errors.append(f"too few evaluation routes for {scenario}")
    seeds = routes.get("seeds") or {}
    if seeds.get("calibration") is None or seeds.get("evaluation") is None:
        errors.append("missing calibration or evaluation seed")
    elif seeds.get("calibration") == seeds.get("evaluation"):
        errors.append("calibration and evaluation seeds must differ")
    if int(routes.get("shared_od_pairs") or 0) != 0:
        errors.append("calibration and evaluation share origin-destination pairs")
    if int(routes.get("shared_paths") or 0) != 0:
        errors.append("calibration and evaluation share identical physical paths")
    if not isinstance(summary.get("data_quality_issues"), list):
        errors.append("data_quality_issues must be a list")
    return errors
