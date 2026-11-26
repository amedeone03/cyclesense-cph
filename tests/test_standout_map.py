import re
from pathlib import Path

import pytest

pytest.importorskip("folium")

from cyclesense.standout_map import (
    EXISTING_COLOR,
    FIRST_COLOR,
    NEXT_COLOR,
    addition_tranches,
    default_addition_visible,
    write_standout_map,
)


def test_tranches_keep_the_greedy_prefix_and_drop_duplicates() -> None:
    first, nxt = addition_tranches({5: ["a", "b"], 10: ["a", "b", "c"]})
    assert first == ("a", "b")
    assert nxt == ("c",)
    first, nxt = addition_tranches({5: ["a", "b"], 10: ["b", "c", "d"]})
    assert first == ("a", "b")
    assert nxt == ("c", "d")
    assert default_addition_visible("uniform", "first")
    assert not default_addition_visible("uniform", "next")
    assert not default_addition_visible("commuter_proxy", "first")


def test_map_draws_municipal_aadt_and_hides_optional_additions(tmp_path: Path) -> None:
    output = tmp_path / "standout.html"
    write_standout_map(
        [
            {
                "edge_id": "pe:existing",
                "line": [(55.6760, 12.5700), (55.6762, 12.5704)],
                "street": "Knippelsbro",
                "osm_name": "Knippelsbro",
                "aadt": 21400,
                "year": 2025,
                "count_type": "Søsnittet",
                "latitude": 55.6761,
                "longitude": 12.5702,
                "snap_m": 0.18,
            }
        ],
        [
            {
                "name": "Additional 5 — uniform",
                "show": True,
                "color": FIRST_COLOR,
                "sites": [
                    {
                        "edge_id": "pe:added",
                        "line": [(55.6770, 12.5800), (55.6772, 12.5805)],
                        "osm_name": "Vester Voldgade",
                        "scenario": "uniform",
                        "rank": 1,
                    }
                ],
            },
            {
                "name": "Next 5 — uniform",
                "show": False,
                "color": NEXT_COLOR,
                "sites": [
                    {
                        "edge_id": "pe:later",
                        "line": [(55.6780, 12.5900), (55.6782, 12.5904)],
                        "osm_name": "Nørre Voldgade",
                        "scenario": "uniform",
                        "rank": 6,
                    }
                ],
            },
        ],
        [{"scenario": "uniform", "existing": 0.736, "plus_5": 0.836, "plus_10": 0.872}],
        output,
        boundary=(12.5630, 55.6705, 12.5965, 55.6880),
        basemap={
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
        notes=["Dronning Louises Bro lies on the west edge of the study rectangle."],
    )
    text = output.read_text(encoding="utf-8")
    assert "pe:existing" in text
    assert "pe:added" in text
    assert "pe:later" in text
    assert "21,400" in text
    assert "55.676100" in text
    assert "12.570200" in text
    assert "Knippelsbro" in text
    assert EXISTING_COLOR in text
    assert FIRST_COLOR in text
    assert NEXT_COLOR in text
    assert "73.6%" in text
    assert "83.6%" in text
    assert "87.2%" in text
    assert "+10.0 pp" in text
    assert "Not a confirmed permanently installed sensor" in text
    assert "Not approved for installation" in text
    assert "Not observed cyclist capture" in text
    assert "study rectangle" in text
    assert "tile.openstreetmap.org" not in text
    assert '"pane": "markerPane"' in text or '"pane":"markerPane"' in text
    assert "street-label" not in text
    assert "Hovergade" in text
    assert _layer_added(text, "Name-verified counting locations (1)")
    assert _layer_added(text, "Additional 5 — uniform")
    assert not _layer_added(text, "Next 5 — uniform")


def test_map_rejects_a_duplicate_or_a_missing_segment(tmp_path: Path) -> None:
    existing = [{"edge_id": "pe:existing", "line": [(55.67, 12.57), (55.68, 12.58)]}]
    with pytest.raises(ValueError, match="repeats a municipal segment"):
        write_standout_map(
            existing,
            [
                {
                    "name": "Additional 5 — uniform",
                    "show": True,
                    "sites": [{"edge_id": "pe:existing", "line": [(55.67, 12.57), (55.68, 12.58)]}],
                }
            ],
            [],
            tmp_path / "dup.html",
        )
    with pytest.raises(ValueError, match="missing an eligible-segment geometry"):
        write_standout_map(
            [{"edge_id": "pe:existing", "line": [(55.67, 12.57)]}],
            [],
            [],
            tmp_path / "short.html",
        )


def _layer_added(text: str, layer_name: str) -> bool:
    escaped = layer_name.replace("—", r"\u2014")
    match = re.search(rf'"{re.escape(escaped)}" : (feature_group_[0-9a-f]+)', text)
    if match is None:
        return False
    return f"{match.group(1)}.addTo(" in text
