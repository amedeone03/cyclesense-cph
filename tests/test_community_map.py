from pathlib import Path

import pytest

pytest.importorskip("folium")

from cyclesense.community_map import write_community_map


def test_community_map_names_the_route_and_skips_public_tiles(tmp_path: Path) -> None:
    output = tmp_path / "communities.html"
    write_community_map(
        [
            {
                "scenario": "uniform",
                "community": 0,
                "size": 4,
                "route_id": "uniform:calibration:0001",
                "mean_similarity": 0.42,
                "line": [(55.676, 12.57), (55.677, 12.58)],
            },
            {
                "scenario": "uniform",
                "community": 1,
                "size": 2,
                "route_id": "uniform:calibration:0002",
                "mean_similarity": 0.2,
                "line": [(55.675, 12.56), (55.676, 12.57)],
            },
        ],
        output,
        boundary=(12.5, 55.6, 12.6, 55.7),
        basemap={
            "labels": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "Labelvej"},
                        "geometry": {"type": "Point", "coordinates": [12.57, 55.676]},
                    }
                ],
            },
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
        },
    )
    text = output.read_text(encoding="utf-8")
    assert "uniform:calibration:0001" in text
    assert "Hovergade" in text
    assert "street-label" not in text
    assert "tile.openstreetmap.org" not in text
    assert "community 1" not in text
