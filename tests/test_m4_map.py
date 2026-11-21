import re
from pathlib import Path

from cyclesense.m4_map import write_balanced_map


def test_map_opens_only_the_uniform_greedy_layer(tmp_path: Path) -> None:
    selections = [
        {
            "method": "greedy",
            "scenario": "uniform",
            "sites": [{"edge_id": "pe:1:2:3", "lat": 55.67, "lon": 12.57, "name": "Alpha"}],
        },
        {
            "method": "balanced",
            "scenario": "uniform",
            "sites": [{"edge_id": "pe:4:5:6", "lat": 55.671, "lon": 12.58, "name": "Beta"}],
        },
        {
            "method": "greedy",
            "scenario": "commuter_proxy",
            "sites": [{"edge_id": "pe:7:8:9", "lat": 55.672, "lon": 12.59, "name": "Gamma"}],
        },
    ]
    path = write_balanced_map(
        selections,
        tmp_path / "map.html",
        boundary=(12.56, 55.67, 12.60, 55.68),
    )
    text = path.read_text(encoding="utf-8")
    assert "tile.openstreetmap.org" not in text
    assert "pe:1:2:3" in text
    assert "Alpha" in text
    added = re.findall(r"(feature_group_[0-9a-f]+)\.addTo\(map_", text)
    assert len(added) == 1
    assert f'"Standard greedy \\u2014 uniform (K=10)" : {added[0]}' in text
