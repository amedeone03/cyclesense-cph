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
    assert "tile.openstreetmap.org" not in text
    assert "55.6" in text and "12.5" in text
