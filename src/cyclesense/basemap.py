"""Local geographical context for the M1 map, drawn from the BBBike PBF.

The features are display geometry for the study rectangle: water, parks,
buildings, and named streets. They are not the routing graph, not candidate
sites, and not modeled routes. The map still works with no basemap at all.
"""

import json
from collections.abc import Mapping, Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any

Coord = tuple[float, float]

GREEN_LEISURE = frozenset(
    {"park", "garden", "pitch", "playground", "nature_reserve", "common", "recreation_ground", "golf_course"}
)
GREEN_LANDUSE = frozenset(
    {"grass", "forest", "meadow", "recreation_ground", "village_green", "allotments", "orchard", "flowerbed", "cemetery"}
)
GREEN_NATURAL = frozenset({"wood", "scrub", "grassland", "heath", "wetland"})
STREET_HIGHWAYS = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "unclassified",
        "residential",
        "living_street",
        "pedestrian",
        "service",
        "road",
        "cycleway",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
    }
)
MAJOR_HIGHWAYS = frozenset(
    {
        "motorway",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "pedestrian",
        "motorway_link",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
    }
)
LABEL_HIGHWAYS = MAJOR_HIGHWAYS | {"residential", "living_street", "unclassified"}
WATERWAY_LINES = frozenset({"river", "stream", "canal", "drain", "ditch"})


def polygon_kind(tags: Mapping[str, str]) -> str | None:
    """Classify a closed way or multipolygon. Water wins over parks and buildings."""
    natural = tags.get("natural") or ""
    landuse = tags.get("landuse") or ""
    leisure = tags.get("leisure") or ""
    waterway = tags.get("waterway") or ""
    building = tags.get("building") or ""
    water = tags.get("water") or ""
    if natural == "water" or landuse in {"reservoir", "basin"} or waterway in {"riverbank", "dock"}:
        return "water"
    if water not in {"", "no"} and natural != "wetland":
        return "water"
    if leisure in GREEN_LEISURE or landuse in GREEN_LANDUSE or natural in GREEN_NATURAL:
        return "green"
    if building and building != "no":
        return "building"
    return None


def intersects_bbox(coords: Sequence[Coord], bbox: Sequence[float]) -> bool:
    """True when a lon/lat line or ring meets west, south, east, north."""
    if not coords:
        return False
    west, south, east, north = bbox
    lons = [point[0] for point in coords]
    lats = [point[1] for point in coords]
    return not (max(lons) < west or min(lons) > east or max(lats) < south or min(lats) > north)


def stitch_rings(lines: Sequence[Sequence[Coord]]) -> list[list[Coord]]:
    """Join way pieces that share endpoints. Only closed rings are returned."""
    unused = [list(line) for line in lines if len(line) >= 2]
    rings: list[list[Coord]] = []
    while unused:
        ring = unused.pop()
        progressed = True
        while progressed and ring[0] != ring[-1]:
            progressed = False
            for index, other in enumerate(unused):
                if other[0] == ring[-1]:
                    ring.extend(other[1:])
                elif other[-1] == ring[-1]:
                    ring.extend(reversed(other[:-1]))
                elif other[-1] == ring[0]:
                    ring = other[:-1] + ring
                elif other[0] == ring[0]:
                    ring = list(reversed(other[1:])) + ring
                else:
                    continue
                unused.pop(index)
                progressed = True
                break
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _feature(geometry: dict[str, Any], name: str, **properties: str) -> dict[str, Any]:
    props = {"name": name, **properties}
    return {"type": "Feature", "properties": props, "geometry": geometry}


def _collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _ring_area(ring: Sequence[Coord]) -> float:
    area = 0.0
    for (x1, y1), (x2, y2) in pairwise(ring):
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def _contains(ring: Sequence[Coord], point: Coord) -> bool:
    lon, lat = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > lat) != (y2 > lat):
            edge = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < edge:
                inside = not inside
        previous = current
    return inside


def _centroid(ring: Sequence[Coord]) -> Coord:
    points = ring[:-1] if ring[0] == ring[-1] and len(ring) > 1 else ring
    count = len(points)
    return (sum(point[0] for point in points) / count, sum(point[1] for point in points) / count)


def polygons_from_rings(outers: Sequence[Sequence[Coord]], inners: Sequence[Sequence[Coord]]) -> list[dict[str, Any]]:
    """Turn stitched rings into Polygon or MultiPolygon coordinate arrays."""
    holes: dict[int, list[list[Coord]]] = {index: [] for index in range(len(outers))}
    for inner in inners:
        if len(inner) < 4:
            continue
        center = _centroid(inner)
        candidates = [index for index, outer in enumerate(outers) if _contains(outer, center)]
        if not candidates:
            continue
        host = min(candidates, key=lambda index: _ring_area(outers[index]))
        holes[host].append(list(inner))
    geometries: list[dict[str, Any]] = []
    groups = [(list(outer), holes[index]) for index, outer in enumerate(outers) if len(outer) >= 4]
    if not groups:
        return geometries
    if len(groups) == 1:
        outer, inner_rings = groups[0]
        geometries.append({"type": "Polygon", "coordinates": [outer, *inner_rings]})
        return geometries
    geometries.append(
        {
            "type": "MultiPolygon",
            "coordinates": [[outer, *inner_rings] for outer, inner_rings in groups],
        }
    )
    return geometries


def _line_length(coords: Sequence[Coord]) -> float:
    total = 0.0
    for start, end in pairwise(coords):
        total += (start[0] - end[0]) ** 2 + (start[1] - end[1]) ** 2
    return total


def assemble_context_layers(
    ways: Sequence[Mapping[str, Any]],
    relations: Sequence[Mapping[str, Any]],
    bbox: Sequence[float],
) -> dict[str, Any]:
    """Build GeoJSON layers from already clipped way and relation records.

    Each way mapping needs ``id``, ``coords`` as lon/lat pairs, ``closed``,
    and ``tags``. Each relation needs ``tags`` and ``members`` of
    ``{"ref", "role"}``.
    """
    by_id = {int(way["id"]): way for way in ways}
    member_ids = {int(member["ref"]) for relation in relations for member in relation["members"]}
    water: list[dict[str, Any]] = []
    green: list[dict[str, Any]] = []
    buildings: list[dict[str, Any]] = []
    streets: list[dict[str, Any]] = []
    waterways: list[dict[str, Any]] = []
    buckets = {"water": water, "green": green, "building": buildings}
    labels: dict[str, tuple[float, Coord]] = {}

    def add_polygon(kind: str, geometry: dict[str, Any], name: str) -> None:
        coords = geometry["coordinates"]
        probe = coords[0][0] if geometry["type"] == "MultiPolygon" else coords[0]
        if not intersects_bbox(probe, bbox):
            return
        buckets[kind].append(_feature(geometry, name, kind=kind))

    for relation in relations:
        tags = relation["tags"]
        kind = polygon_kind(tags)
        if kind is None:
            continue
        outers: list[list[Coord]] = []
        inners: list[list[Coord]] = []
        grouped: dict[str, list[list[Coord]]] = {"outer": [], "inner": []}
        for member in relation["members"]:
            way = by_id.get(int(member["ref"]))
            if way is None:
                continue
            role = member.get("role") or "outer"
            if role not in grouped:
                role = "outer"
            grouped[role].append(list(way["coords"]))
        outers = stitch_rings(grouped["outer"])
        inners = stitch_rings(grouped["inner"])
        name = str(tags.get("name") or "")
        for geometry in polygons_from_rings(outers, inners):
            add_polygon(kind, geometry, name)

    for way in ways:
        tags = way["tags"]
        coords = list(way["coords"])
        if len(coords) < 2 or not intersects_bbox(coords, bbox):
            continue
        highway = str(tags.get("highway") or "")
        if highway in STREET_HIGHWAYS:
            rank = "major" if highway in MAJOR_HIGHWAYS else "minor"
            name = str(tags.get("name") or "")
            streets.append(
                _feature(
                    {"type": "LineString", "coordinates": coords},
                    name,
                    kind="street",
                    highway=highway,
                    rank=rank,
                )
            )
            if name and highway in LABEL_HIGHWAYS:
                length = _line_length(coords)
                current = labels.get(name)
                if current is None or length > current[0]:
                    midpoint = coords[len(coords) // 2]
                    labels[name] = (length, midpoint)
            continue
        waterway = str(tags.get("waterway") or "")
        if waterway in WATERWAY_LINES and not way["closed"]:
            waterways.append(
                _feature(
                    {"type": "LineString", "coordinates": coords},
                    str(tags.get("name") or ""),
                    kind="waterway",
                )
            )
            continue
        if not way["closed"] or int(way["id"]) in member_ids:
            continue
        kind = polygon_kind(tags)
        if kind is None:
            continue
        ring = coords if coords[0] == coords[-1] else [*coords, coords[0]]
        if len(ring) < 4:
            continue
        add_polygon(kind, {"type": "Polygon", "coordinates": [ring]}, str(tags.get("name") or ""))

    label_features = [
        _feature({"type": "Point", "coordinates": list(point)}, name, kind="label")
        for name, (_length, point) in sorted(labels.items())
    ]
    return {
        "water": _collection(water),
        "green": _collection(green),
        "buildings": _collection(buildings),
        "streets": _collection(streets),
        "waterways": _collection(waterways),
        "labels": _collection(label_features),
    }


def _tag_value(tags: Any, key: str) -> str:
    value = tags.get(key)
    return "" if value is None else str(value)


def _tag_map(tags: Any, keys: Sequence[str]) -> dict[str, str]:
    return {key: _tag_value(tags, key) for key in keys if _tag_value(tags, key)}


_AREA_KEYS = ("natural", "landuse", "leisure", "water", "waterway", "building", "name")
_WAY_KEYS = ("highway", "natural", "landuse", "leisure", "water", "waterway", "building", "name")


def _read_relations(pbf: Path) -> tuple[list[dict[str, Any]], set[int]]:
    import osmium

    relations: list[dict[str, Any]] = []
    member_ids: set[int] = set()
    processor = osmium.FileProcessor(pbf, osmium.osm.RELATION)
    for obj in processor:
        if _tag_value(obj.tags, "type") not in {"multipolygon", "boundary"}:
            continue
        tags = _tag_map(obj.tags, _AREA_KEYS)
        if polygon_kind(tags) is None:
            continue
        members = []
        for member in obj.members:
            if member.type != "w":
                continue
            members.append({"ref": int(member.ref), "role": member.role or "outer"})
            member_ids.add(int(member.ref))
        if members:
            relations.append({"tags": tags, "members": members})
    return relations, member_ids


def _read_ways(pbf: Path, bbox: Sequence[float], member_ids: set[int]) -> list[dict[str, Any]]:
    import osmium

    west, south, east, north = bbox
    expanded = (west - 0.01, south - 0.01, east + 0.01, north + 0.01)
    ways: list[dict[str, Any]] = []
    processor = osmium.FileProcessor(pbf).with_locations()
    for obj in processor:
        if not obj.is_way():
            continue
        tags = _tag_map(obj.tags, _WAY_KEYS)
        is_member = int(obj.id) in member_ids
        interesting = is_member or bool(
            tags.get("highway") or tags.get("building") or tags.get("natural") or tags.get("landuse")
            or tags.get("leisure") or tags.get("water") or tags.get("waterway")
        )
        if not interesting:
            continue
        coords: list[Coord] = []
        node_ids: list[int] = []
        valid = True
        for node in obj.nodes:
            if not node.location.valid():
                valid = False
                break
            node_ids.append(int(node.ref))
            coords.append((round(float(node.location.lon), 6), round(float(node.location.lat), 6)))
        if not valid or len(coords) < 2:
            continue
        limit = expanded if is_member else bbox
        if not intersects_bbox(coords, limit):
            continue
        ways.append(
            {
                "id": int(obj.id),
                "coords": coords,
                "closed": node_ids[0] == node_ids[-1] and len(node_ids) >= 4,
                "tags": tags,
            }
        )
    return ways


def extract_context_basemap(pbf: Path, bbox: Sequence[float]) -> dict[str, Any]:
    """Read water, parks, buildings, and streets for one rectangle from a PBF."""
    relations, member_ids = _read_relations(pbf)
    ways = _read_ways(pbf, bbox, member_ids)
    return assemble_context_layers(ways, relations, bbox)


def load_context_basemap(pbf: Path, bbox: Sequence[float], cache_path: Path) -> dict[str, Any] | None:
    """Return cached display layers, rebuilding them from ``pbf`` when needed.

    ``None`` means the local extract is missing or osmium is not installed.
    The caller then keeps the tile-free network view.
    """
    if not pbf.is_file():
        return None
    import importlib.util

    if importlib.util.find_spec("osmium") is None:
        return None
    signature = {
        "pbf_size": pbf.stat().st_size,
        "pbf_mtime_ns": pbf.stat().st_mtime_ns,
        "bbox": [round(float(value), 6) for value in bbox],
    }
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cached = None
        if cached and cached.get("signature") == signature and isinstance(cached.get("layers"), dict):
            return cached["layers"]
    layers = extract_context_basemap(pbf, bbox)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "note": "Display geometry for the interactive map. Not a routing graph or a route table.",
                "signature": signature,
                "layers": layers,
            }
        ),
        encoding="utf-8",
    )
    return layers
