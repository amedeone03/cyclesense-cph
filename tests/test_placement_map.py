from pathlib import Path

import pytest

pytest.importorskip("folium")

from cyclesense.placement_map import write_placement_map


def test_placement_map_names_the_algorithm_and_edge(tmp_path: Path) -> None:
    output = tmp_path / "placements.html"
    write_placement_map(
        [
            {
                "method": "greedy",
                "seed": None,
                "sites": [
                    {
                        "edge_id": "pe:1:2:99",
                        "lon": 12.57,
                        "lat": 55.676,
                        "name": "Testvej",
                        "highway": "tertiary",
                    }
                ],
            }
        ],
        output,
        boundary=(12.5, 55.6, 12.6, 55.7),
        budget=10,
    )
    text = output.read_text(encoding="utf-8")
    assert "pe:1:2:99" in text
    assert "Greedy maximum coverage" in text
    assert "Testvej" in text
    assert "tile.openstreetmap.org" not in text
    assert "55.6" in text and "12.5" in text
    for color in ("#7f7f7f", "#e41a1c", "#377eb8", "#4daf4a"):
        assert color in text


def test_default_layer_is_greedy_uniform_and_labels_are_hover_only(tmp_path: Path) -> None:
    output = tmp_path / "placements.html"
    write_placement_map(
        [
            {
                "method": "random",
                "seed": 42,
                "scenario": "uniform",
                "sites": [
                    {
                        "edge_id": "pe:random",
                        "lon": 12.57,
                        "lat": 55.676,
                        "name": "Randomvej",
                        "highway": "residential",
                    }
                ],
            },
            {
                "method": "greedy",
                "seed": None,
                "scenario": "uniform",
                "sites": [
                    {
                        "edge_id": "pe:greedy",
                        "lon": 12.58,
                        "lat": 55.677,
                        "name": "Greedyvej",
                        "highway": "tertiary",
                    }
                ],
            },
            {
                "method": "greedy",
                "seed": None,
                "scenario": "commuter_proxy",
                "sites": [
                    {
                        "edge_id": "pe:commuter",
                        "lon": 12.59,
                        "lat": 55.678,
                        "name": "Commutervej",
                        "highway": "primary",
                    }
                ],
            },
        ],
        output,
        basemap={
            "streets": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Hovergade", "rank": "major"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[12.57, 55.676], [12.58, 55.677]],
                        },
                    }
                ],
            },
            "labels": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Hovergade"},
                        "geometry": {"type": "Point", "coordinates": [12.575, 55.6765]},
                    }
                ],
            },
        },
    )
    text = output.read_text(encoding="utf-8")
    assert "street-label" not in text
    assert "Hovergade" in text
    assert _layer_added(text, "Greedy maximum coverage — uniform (K=10)")
    assert not _layer_added(text, "Random — uniform (K=10)")
    assert not _layer_added(text, "Greedy maximum coverage — commuter_proxy (K=10)")


def _layer_added(text: str, layer_name: str) -> bool:
    import re

    escaped = layer_name.replace("—", r"\u2014")
    match = re.search(rf'"{re.escape(escaped)}" : (feature_group_[0-9a-f]+)', text)
    if match is None:
        return False
    return f"{match.group(1)}.addTo(" in text
