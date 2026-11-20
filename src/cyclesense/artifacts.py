"""Locations of the files the M1 pilot already wrote.

The canonical graph is the clipped study extract under ``data/processed/m1/``.
``data/processed/copenhagen_bike.graphml`` is not one of those files. Callers
that only need to inspect the network should reuse this directory instead of
starting another download.
"""

import json
from pathlib import Path
from typing import Any

from cyclesense.network import PIPELINE_VERSION
from cyclesense.validation import validate_m1_summary

M1_DIRNAME = Path("data") / "processed" / "m1"


def m1_paths(root: Path) -> dict[str, Path]:
    """Return the canonical M1 artifact paths for a repository root."""
    directory = root / M1_DIRNAME
    return {
        "full_graph": directory / "copenhagen_bike_full.graphml",
        "routing_wgs84": directory / "copenhagen_bike_routing_wgs84.graphml",
        "routing_projected": directory / "copenhagen_bike_routing_projected.graphml",
        "candidates": directory / "candidates.csv",
        "routes": directory / "routes.csv",
        "metadata": directory / "extraction_metadata.json",
        "audit": directory / "audit.json",
        "summary": directory / "summary.json",
        "interactive_map": root / "outputs" / "m1" / "m1_network.html",
    }


def validated_m1_artifacts(root: Path) -> dict[str, Path] | None:
    """Return canonical paths when the saved M1 summary is complete.

    A match means the pilot files are present and ``summary.json`` passes the
    same completeness check as ``scripts/run_m1.py``. It does not re-parse the
    OpenStreetMap extract and it does not claim the files are observed counts.
    """
    paths = m1_paths(root)
    required = (
        "full_graph",
        "routing_wgs84",
        "routing_projected",
        "candidates",
        "routes",
        "metadata",
        "summary",
    )
    if any(not paths[name].is_file() or paths[name].stat().st_size == 0 for name in required):
        return None
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    if metadata.get("pipeline_version") != PIPELINE_VERSION:
        return None
    boundary = metadata.get("boundary") or {}
    if not all(boundary.get(key) is not None for key in ("west", "south", "east", "north")):
        return None
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))
    if validate_m1_summary(summary, min_routes_per_split=1):
        return None
    return paths


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
