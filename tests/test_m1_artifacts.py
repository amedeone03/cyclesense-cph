import json
from pathlib import Path

from cyclesense.artifacts import m1_paths, validated_m1_artifacts
from cyclesense.network import PIPELINE_VERSION


def _summary() -> dict:
    return {
        "boundary": {"west": 12.5, "south": 55.6, "east": 12.6, "north": 55.7, "crs": "EPSG:4326"},
        "extraction_utc": "2026-11-20T20:00:00+00:00",
        "source": {"provider": "OpenStreetMap", "osmnx_version": "2.2.0"},
        "projected_crs": "EPSG:32633",
        "graph": {"routing_nodes": 10, "routing_edges": 20, "candidates": 8},
        "routes": {
            "calibration": {"uniform": 2, "commuter_proxy": 2},
            "evaluation": {"uniform": 2, "commuter_proxy": 2},
            "seeds": {"calibration": 42, "evaluation": 10049},
            "shared_od_pairs": 0,
            "shared_paths": 0,
        },
        "data_quality_issues": [],
    }


def _write_pilot(root: Path, *, pipeline_version: str = PIPELINE_VERSION) -> None:
    paths = m1_paths(root)
    for name in ("full_graph", "routing_wgs84", "routing_projected", "candidates", "routes", "audit"):
        paths[name].parent.mkdir(parents=True, exist_ok=True)
        paths[name].write_text("placeholder\n", encoding="utf-8")
    paths["metadata"].write_text(
        json.dumps(
            {
                "pipeline_version": pipeline_version,
                "boundary": {"west": 12.563, "south": 55.6705, "east": 12.5965, "north": 55.688},
            }
        ),
        encoding="utf-8",
    )
    paths["summary"].write_text(json.dumps(_summary()), encoding="utf-8")


def test_missing_pilot_is_not_reused(tmp_path: Path) -> None:
    assert validated_m1_artifacts(tmp_path) is None


def test_validated_pilot_is_reused_without_a_second_graph(tmp_path: Path) -> None:
    _write_pilot(tmp_path)
    found = validated_m1_artifacts(tmp_path)
    assert found is not None
    assert found["routing_wgs84"] == tmp_path / "data/processed/m1/copenhagen_bike_routing_wgs84.graphml"
    assert not (tmp_path / "data/processed/copenhagen_bike.graphml").exists()


def test_stale_pipeline_version_is_not_reused(tmp_path: Path) -> None:
    _write_pilot(tmp_path, pipeline_version="m0")
    assert validated_m1_artifacts(tmp_path) is None
