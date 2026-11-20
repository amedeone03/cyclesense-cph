"""Interactive Folium map of the saved M1 network and a route sample.

The map reads files that ``scripts/run_m1.py`` already wrote. It does not
download OpenStreetMap data and it does not generate routes.
"""

import csv
import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cyclesense.plotting import select_example_routes

_ROUTE_COLORS = ("#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00", "#a65628")
_NETWORK_COLOR = "#5f6b76"
_CANDIDATE_COLOR = "#08519c"
_ATTRIBUTION = (
    "Geometry © OpenStreetMap contributors, ODbL. "
    "Context is drawn from the local BBBike Copenhagen extract. No public map tiles."
)


def read_table(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _node_key(graph: Any, node_id: Any) -> Any | None:
    if node_id in graph.nodes:
        return node_id
    text = str(node_id)
    if text in graph.nodes:
        return text
    try:
        number = int(text)
    except (TypeError, ValueError):
        return None
    if number in graph.nodes:
        return number
    return None


def _latlon(graph: Any, node_id: Any) -> tuple[float, float] | None:
    key = _node_key(graph, node_id)
    if key is None:
        return None
    node = graph.nodes[key]
    return float(node["y"]), float(node["x"])


def _linestring(graph: Any, u_node: Any, v_node: Any, data: Mapping[str, Any]) -> list[tuple[float, float]] | None:
    geometry = data.get("geometry")
    coords = getattr(geometry, "coords", None)
    if coords is not None:
        return [(float(lat), float(lon)) for lon, lat, *_rest in coords]
    start = _latlon(graph, u_node)
    end = _latlon(graph, v_node)
    if start is None or end is None:
        return None
    return [start, end]


def _edge_index(graph: Any) -> dict[str, tuple[Any, Any, dict[str, Any]]]:
    index: dict[str, tuple[Any, Any, dict[str, Any]]] = {}
    for u_node, v_node, data in graph.edges(data=True):
        edge_id = str(data.get("physical_edge_id", ""))
        if edge_id and edge_id not in index:
            index[edge_id] = (u_node, v_node, data)
    return index


def _network_lines(graph: Any) -> list[list[tuple[float, float]]]:
    """One line per physical segment, plus any routing edge that has no id."""
    seen: set[str] = set()
    lines: list[list[tuple[float, float]]] = []
    for u_node, v_node, data in graph.edges(data=True):
        edge_id = str(data.get("physical_edge_id") or "")
        token = edge_id or f"{u_node}\0{v_node}\0{data.get('key', '')}"
        if token in seen:
            continue
        seen.add(token)
        line = _linestring(graph, u_node, v_node, data)
        if line:
            lines.append(line)
    return lines


def _bounds(lines: Sequence[Sequence[tuple[float, float]]]) -> list[list[float]]:
    latitudes = [point[0] for line in lines for point in line]
    longitudes = [point[1] for line in lines for point in line]
    return [
        [min(latitudes), min(longitudes)],
        [max(latitudes), max(longitudes)],
    ]


def _sample_rows(routes: Sequence[Mapping[str, str]], *, per_scenario: int) -> list[Mapping[str, str]]:
    wrapped = [
        SimpleNamespace(scenario=row.get("scenario", ""), split=row.get("split", ""), row=row) for row in routes
    ]
    return [item.row for item in select_example_routes(wrapped, per_scenario=per_scenario)]


def _collection_features(basemap: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
    collection = basemap.get(key) or {}
    features = collection.get("features") or []
    return [feature for feature in features if feature.get("geometry")]


def _add_geojson(group: Any, features: Sequence[Mapping[str, Any]], style: dict[str, Any], *, tooltip: bool) -> None:
    import folium

    if not features:
        return
    collection = {"type": "FeatureCollection", "features": list(features)}
    kwargs: dict[str, Any] = {
        "style_function": lambda _feature, style=style: style,
        "control": False,
        "overlay": True,
    }
    if tooltip:
        kwargs["tooltip"] = folium.GeoJsonTooltip(fields=["name"], aliases=[""], labels=False)
    folium.GeoJson(collection, **kwargs).add_to(group)


def _add_basemap(fmap: Any, basemap: Mapping[str, Any]) -> bool:
    """Add one switchable context layer. Return False when it has no features."""
    import folium

    streets = _collection_features(basemap, "streets")
    major = [feature for feature in streets if feature.get("properties", {}).get("rank") == "major"]
    minor = [feature for feature in streets if feature.get("properties", {}).get("rank") != "major"]
    groups = [
        (
            "water",
            _collection_features(basemap, "water"),
            {"color": "#7eb6d6", "weight": 1, "fillColor": "#b9d7f5", "fillOpacity": 0.9},
            True,
        ),
        (
            "green",
            _collection_features(basemap, "green"),
            {"color": "#8fbf7a", "weight": 1, "fillColor": "#c6e2b5", "fillOpacity": 0.85},
            True,
        ),
        (
            "buildings",
            _collection_features(basemap, "buildings"),
            {"color": "#d0cbc4", "weight": 0.4, "fillColor": "#f3efe9", "fillOpacity": 0.95},
            False,
        ),
        (
            "waterways",
            _collection_features(basemap, "waterways"),
            {"color": "#5aa0d6", "weight": 2, "opacity": 0.9, "fillOpacity": 0},
            True,
        ),
        (
            "minor streets",
            minor,
            {"color": "#8d8d8d", "weight": 1.1, "opacity": 0.85, "fillOpacity": 0},
            True,
        ),
        (
            "major streets",
            major,
            {"color": "#3d3d3d", "weight": 2.4, "opacity": 0.9, "fillOpacity": 0},
            True,
        ),
    ]
    labels = _collection_features(basemap, "labels")
    if not any(features for _name, features, _style, _tip in groups) and not labels:
        return False
    layer = folium.FeatureGroup(name="Geographical basemap", show=True)
    for _name, features, style, tooltip in groups:
        _add_geojson(layer, features, style, tooltip=tooltip)
    for feature in labels:
        coordinates = feature["geometry"].get("coordinates") or []
        if len(coordinates) < 2:
            continue
        name = str(feature.get("properties", {}).get("name") or "")
        if not name:
            continue
        folium.Marker(
            [coordinates[1], coordinates[0]],
            interactive=False,
            keyboard=False,
            icon=folium.DivIcon(
                class_name="street-label",
                icon_size=(140, 16),
                icon_anchor=(70, 8),
                html=f'<div class="street-label-text">{html.escape(name)}</div>',
            ),
        ).add_to(layer)
    layer.add_to(fmap)
    return True


def write_interactive_map(
    graph: Any,
    candidates: Sequence[Mapping[str, str]],
    routes: Sequence[Mapping[str, str]],
    output: Path,
    *,
    routes_per_scenario: int = 3,
    boundary: Sequence[float] | None = None,
    basemap: Mapping[str, Any] | None = None,
) -> Path:
    """Write an HTML map of eligible segments and a small modeled-route sample."""
    import folium

    index = _edge_index(graph)
    segments: list[tuple[Mapping[str, str], list[tuple[float, float]]]] = []
    for row in candidates:
        found = index.get(row.get("physical_edge_id", ""))
        if found is None:
            continue
        line = _linestring(graph, found[0], found[1], found[2])
        if line:
            segments.append((row, line))
    if not segments:
        raise ValueError("No eligible segments could be drawn from the routing graph.")

    network = _network_lines(graph)
    drawn = [line for _row, line in segments]
    drawn.extend(network)
    center_line = network or drawn
    center = [
        sum(point[0] for line in center_line for point in line) / sum(len(line) for line in center_line),
        sum(point[1] for line in center_line for point in line) / sum(len(line) for line in center_line),
    ]
    # tiles=None keeps the page from requesting tile.openstreetmap.org.
    fmap = folium.Map(
        location=center,
        zoom_start=14,
        tiles=None,
        control_scale=True,
        zoom_control=True,
    )
    has_basemap = bool(basemap) and _add_basemap(fmap, basemap)
    streets = folium.FeatureGroup(name="Bicycle routing network", show=True)
    for line in network:
        folium.PolyLine(
            line,
            color=_NETWORK_COLOR,
            weight=2,
            opacity=0.95,
            interactive=False,
        ).add_to(streets)
    streets.add_to(fmap)
    counters = folium.FeatureGroup(name="Eligible counter segments", show=True)
    for row, line in segments:
        edge_id = row.get("physical_edge_id", "")
        name = row.get("name") or "(unnamed)"
        popup = folium.Popup(
            "<br>".join(
                [
                    "<b>Physical edge ID</b>",
                    f"<code>{html.escape(edge_id)}</code>",
                    f"Highway: {html.escape(row.get('highway') or '')}",
                    f"Name: {html.escape(name)}",
                    f"Length: {html.escape(row.get('length_m') or '')} m",
                    "Eligible modeled counter site. Not an installed counter.",
                ]
            ),
            max_width=460,
        )
        folium.PolyLine(
            line,
            color=_CANDIDATE_COLOR,
            weight=4,
            opacity=0.85,
            tooltip=folium.Tooltip(edge_id),
            popup=popup,
        ).add_to(counters)
    counters.add_to(fmap)

    route_layer = folium.FeatureGroup(name="Simulated routes", show=True)
    for index_number, row in enumerate(_sample_rows(routes, per_scenario=routes_per_scenario)):
        points: list[tuple[float, float]] = []
        for node_id in str(row.get("node_ids", "")).split("|"):
            if not node_id:
                continue
            point = _latlon(graph, node_id)
            if point is not None:
                points.append(point)
        if len(points) < 2:
            continue
        drawn.append(points)
        color = _ROUTE_COLORS[index_number % len(_ROUTE_COLORS)]
        label = f"{row.get('route_id', '')} ({row.get('scenario', '')}, {row.get('split', '')})"
        folium.PolyLine(
            points,
            color=color,
            weight=3,
            opacity=0.9,
            tooltip=folium.Tooltip(label),
            popup=folium.Popup(
                "<br>".join(
                    [
                        f"<b>{html.escape(label)}</b>",
                        "Modeled shortest path. Not an observed bicycle trip.",
                        f"Length: {html.escape(row.get('length_m') or '')} m",
                    ]
                )
            ),
        ).add_to(route_layer)
    route_layer.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
    else:
        fmap.fit_bounds(_bounds(drawn), padding=(24, 24))
    context_line = (
        "Geographical basemap shows streets, buildings, parks, and water from the local extract.<br>"
        "Uncheck that layer for the tile-free network view.<br>"
        if has_basemap
        else "Tile-free network view. No geographical basemap is loaded.<br>"
    )
    fmap.get_root().html.add_child(
        folium.Element(
            f"""
            <div style="position: fixed; top: 12px; left: 54px; z-index: 9999;
                        background: white; padding: 8px 12px; border: 1px solid #bbb;
                        font: 13px/1.4 sans-serif; max-width: 460px;">
              <b>M1 pilot — Indre By study area</b><br>
              {context_line}
              Gray: bicycle routing network. Blue: eligible counter segments.<br>
              Click a blue segment to inspect its physical-edge ID.<br>
              Colored lines are a sample of modeled routes, not observed trips.
            </div>
            <div style="position: fixed; bottom: 12px; right: 12px; z-index: 9999;
                        background: rgba(255,255,255,0.95); padding: 6px 10px;
                        border: 1px solid #bbb; font: 12px/1.4 sans-serif; max-width: 360px;">
              {html.escape(_ATTRIBUTION)}
            </div>
            <style>
              .leaflet-container {{ background: #ffffff; }}
              .leaflet-marker-icon.street-label,
              .leaflet-marker-icon.street-label .street-label-text {{
                background: transparent; border: none; pointer-events: none !important;
              }}
              .street-label-text {{
                font: 11px/1.2 sans-serif; color: #222; white-space: nowrap;
                text-shadow: 0 0 3px #fff, 0 0 3px #fff, 0 0 3px #fff;
              }}
            </style>
            """
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output


def local_map_server(directory: Path, *, host: str = "127.0.0.1", port: int = 8765) -> Any:
    """Serve a directory so the map page has an HTTP origin.

    ``http://127.0.0.1:<port>/`` is a normal browser origin. A ``file://``
    page is not, which is why tile servers answered 403 when the map still
    requested them.
    """
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    return ThreadingHTTPServer((host, port), handler)
