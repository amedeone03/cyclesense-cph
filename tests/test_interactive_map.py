import threading
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import pytest

from cyclesense.interactive import (
    _NETWORK_COLOR,
    _ROUTE_COLORS,
    local_map_server,
    write_interactive_map,
)

nx = pytest.importorskip("networkx")
pytest.importorskip("folium")


def _graph() -> Any:
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=12.57, y=55.676)
    graph.add_node(2, x=12.571, y=55.677)
    graph.add_node(3, x=12.572, y=55.675)
    graph.add_edge(1, 2, physical_edge_id="pe:1:2:99", length=40)
    graph.add_edge(2, 3, physical_edge_id="pe:2:3:100", length=30)
    return graph


def _route(scenario: str, index: int) -> dict[str, str]:
    return {
        "route_id": f"{scenario}:calibration:{index:04d}",
        "scenario": scenario,
        "split": "calibration",
        "node_ids": "1|2|3",
        "length_m": "70",
    }


def test_map_exposes_physical_edge_id_and_a_modeled_route(tmp_path: Path) -> None:
    output = tmp_path / "m1_network.html"
    write_interactive_map(
        _graph(),
        [{"physical_edge_id": "pe:1:2:99", "highway": "cycleway", "name": "Testvej", "length_m": "40"}],
        [_route("uniform", 0)],
        output,
        routes_per_scenario=1,
    )
    text = output.read_text(encoding="utf-8")
    assert "pe:1:2:99" in text
    assert "Modeled shortest path" in text
    assert "Eligible counter segments" in text
    assert "Bicycle routing network" in text
    assert _NETWORK_COLOR in text
    assert "#08519c" in text
    assert "fitBounds" in text
    assert "OpenStreetMap contributors" in text
    assert "tile.openstreetmap.org" not in text
    assert "L.tileLayer" not in text


def test_map_draws_six_distinct_route_colors(tmp_path: Path) -> None:
    routes = [_route("uniform", index) for index in range(3)]
    routes.extend(_route("commuter_proxy", index) for index in range(3))
    output = tmp_path / "m1_network.html"
    write_interactive_map(
        _graph(),
        [{"physical_edge_id": "pe:1:2:99", "highway": "cycleway", "name": "Testvej", "length_m": "40"}],
        routes,
        output,
        routes_per_scenario=3,
    )
    text = output.read_text(encoding="utf-8")
    for color in _ROUTE_COLORS:
        assert color in text


def test_basemap_layer_stays_tile_free_and_fits_the_study_boundary(tmp_path: Path) -> None:
    output = tmp_path / "m1_network.html"
    basemap = {
        "water": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Test Canal", "kind": "water"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[12.57, 55.676], [12.571, 55.676], [12.571, 55.677], [12.57, 55.676]]],
                    },
                }
            ],
        },
        "green": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Test Park", "kind": "green"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[12.572, 55.675], [12.573, 55.675], [12.573, 55.676], [12.572, 55.675]]],
                    },
                }
            ],
        },
        "buildings": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Test House", "kind": "building"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[12.57, 55.676], [12.5704, 55.676], [12.5704, 55.6764], [12.57, 55.676]]],
                    },
                }
            ],
        },
        "streets": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Named Street", "kind": "street", "rank": "major"},
                    "geometry": {"type": "LineString", "coordinates": [[12.57, 55.676], [12.572, 55.675]]},
                }
            ],
        },
        "labels": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"name": "Named Street"},
                    "geometry": {"type": "Point", "coordinates": [12.571, 55.6755]},
                }
            ],
        },
    }
    write_interactive_map(
        _graph(),
        [{"physical_edge_id": "pe:1:2:99", "highway": "cycleway", "name": "Testvej", "length_m": "40"}],
        [_route("uniform", 0)],
        output,
        routes_per_scenario=1,
        boundary=(10.0, 50.0, 11.0, 51.0),
        basemap=basemap,
    )
    text = output.read_text(encoding="utf-8")
    assert "Geographical basemap" in text
    assert "Test Canal" in text
    assert "Test Park" in text
    assert "Named Street" in text
    assert "pe:1:2:99" in text
    assert "Simulated routes" in text
    assert "[[50.0, 10.0], [51.0, 11.0]]" in text
    assert "tile.openstreetmap.org" not in text
    assert "Uncheck that layer for the tile-free network view." in text


def test_local_server_returns_the_map_with_an_http_origin(tmp_path: Path) -> None:
    output = tmp_path / "m1_network.html"
    write_interactive_map(
        _graph(),
        [{"physical_edge_id": "pe:1:2:99", "highway": "cycleway", "name": "Testvej", "length_m": "40"}],
        [_route("uniform", 0)],
        output,
        routes_per_scenario=1,
    )
    server = local_map_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with urlopen(f"http://{host}:{port}/m1_network.html", timeout=5) as response:
            body = response.read().decode("utf-8")
            assert response.status == 200
        assert host == "127.0.0.1"
        assert "pe:1:2:99" in body
        assert "tile.openstreetmap.org" not in body
    finally:
        server.shutdown()
        server.server_close()
