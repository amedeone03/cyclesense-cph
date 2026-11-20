from cyclesense.validation import validate_m1_summary


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


def test_complete_summary_passes() -> None:
    assert validate_m1_summary(_summary()) == []


def test_summary_rejects_shared_routes_and_missing_provenance() -> None:
    summary = _summary()
    summary["routes"]["shared_od_pairs"] = 3
    summary["routes"]["seeds"]["evaluation"] = 42
    summary["extraction_utc"] = ""
    summary["source"]["provider"] = "synthetic"
    errors = validate_m1_summary(summary)
    assert any("share origin-destination" in error for error in errors)
    assert any("seeds must differ" in error for error in errors)
    assert any("timestamp" in error for error in errors)
    assert any("OpenStreetMap" in error for error in errors)
