"""Copenhagen bicycle-graph extraction, direction audit, and candidates.

The download keeps OSMnx's directed bike graph: ``bike`` is not added to
``bidirectional_network_types``, so a one-way tag stays one-way. A small
post-process adds the reverse edge only when bicycle contraflow tags agree.
Routing then uses the largest strongly connected component with positive
edge lengths. Candidates are eligible physical segments inside that component.

OpenStreetMap geometry is infrastructure. Nothing in this module is a
bicycle count.
"""

import hashlib
from collections import Counter, defaultdict
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from math import isfinite
from pathlib import Path
from statistics import median
from typing import Any
from urllib.request import urlretrieve

from cyclesense.edges import (
    as_list,
    as_tokens,
    eligibility_decision,
    indicates_contraflow,
    physical_edge_id,
)

# Way tags the bike filter does not store unless we ask OSMnx to keep them.
BICYCLE_WAY_TAGS = (
    "bicycle",
    "cycleway",
    "cycleway:left",
    "cycleway:right",
    "cycleway:both",
    "oneway:bicycle",
    "foot",
    "motor_vehicle",
    "surface",
)

PIPELINE_VERSION = "m1.2"

# Dated city extract used when the public Overpass interpreter is unreachable.
# OSMnx still builds and clips the bike graph. The file is OpenStreetMap data.
COPENHAGEN_PBF_URL = "https://download.bbbike.org/osm/bbbike/Copenhagen/Copenhagen.osm.pbf"
COPENHAGEN_PBF_LAST_MODIFIED = "2026-11-14T16:51:56Z"


def _nx():
    import networkx as nx

    return nx


def package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"


def configure_osmnx(cache_folder: str) -> Any:
    """Set cache, one-way policy, and bicycle tags before a download.

    ``bike`` is removed from the bidirectional-network list when present.
    OSMnx 2.2 already defaults that list to walk only; the removal makes the
    direction policy explicit if a later release changes the default.
    """
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = cache_folder
    ox.settings.log_console = False
    current = list(ox.settings.bidirectional_network_types)
    ox.settings.bidirectional_network_types = [name for name in current if name != "bike"]
    tags = list(ox.settings.useful_tags_way)
    for tag in BICYCLE_WAY_TAGS:
        if tag not in tags:
            tags.append(tag)
    ox.settings.useful_tags_way = tags
    return ox


def bike_overpass_filter() -> str:
    """Return the OSMnx bike Overpass filter active in this process."""
    try:
        from osmnx._overpass import _get_network_filter

        return _get_network_filter("bike")
    except (ImportError, AttributeError, ValueError) as exc:  # pragma: no cover - OSMnx internals
        return f"unavailable ({exc.__class__.__name__})"


def bbox_polygon(west: float, south: float, east: float, north: float) -> Any:
    """Exact WGS84 rectangle. Axis order is west, south, east, north."""
    if west >= east or south >= north:
        raise ValueError("bbox must have west < east and south < north")
    from shapely.geometry import box

    return box(west, south, east, north)


def download_bike_graph(
    polygon: Any,
    *,
    cache_folder: str,
    retain_all: bool = True,
    simplify: bool = True,
    truncate_by_edge: bool = False,
    attempts: int = 3,
) -> tuple[Any, dict[str, Any]]:
    """Download a directed bike graph and the provenance needed to describe it.

    ``retain_all`` keeps disconnected fragments so the audit can see them.
    The caller, not this function, drops those fragments before routing.
    """
    import time

    ox = configure_osmnx(cache_folder)
    last_error: Exception | None = None
    graph = None
    for attempt in range(1, attempts + 1):
        try:
            graph = ox.graph_from_polygon(
                polygon,
                network_type="bike",
                simplify=simplify,
                retain_all=retain_all,
                truncate_by_edge=truncate_by_edge,
            )
            break
        except Exception as exc:  # noqa: BLE001 - Overpass clients raise a wide set of errors
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(5 * attempt)
    if graph is None:
        raise RuntimeError(f"OSMnx bike download failed after {attempts} attempts") from last_error
    metadata = {
        "pipeline_version": PIPELINE_VERSION,
        "extraction_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": "OpenStreetMap",
        "access": "OSMnx Overpass API",
        "license": "ODbL",
        "attribution": "© OpenStreetMap contributors",
        "overpass_url": getattr(ox.settings, "overpass_url", None),
        "overpass_filter": bike_overpass_filter(),
        "network_type": "bike",
        "simplify": simplify,
        "retain_all": retain_all,
        "truncate_by_edge": truncate_by_edge,
        "bidirectional_network_types": list(ox.settings.bidirectional_network_types),
        "useful_tags_way": list(ox.settings.useful_tags_way),
        "osmnx_version": package_version("osmnx"),
        "networkx_version": package_version("networkx"),
        "shapely_version": package_version("shapely"),
        "pyproj_version": package_version("pyproj"),
        "input_crs": str(graph.graph.get("crs", "EPSG:4326")),
        "polygon_wkt": polygon.wkt,
        "raw_nodes": int(graph.number_of_nodes()),
        "raw_directed_edges": int(graph.number_of_edges()),
    }
    graph.graph["cyclesense_pipeline"] = PIPELINE_VERSION
    graph.graph["cyclesense_extraction_utc"] = metadata["extraction_utc"]
    return graph, metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_copenhagen_pbf(cache_dir: Path, *, force: bool = False) -> tuple[Path, dict[str, Any]]:
    """Download the BBBike Copenhagen OSM PBF into the local cache if needed."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    destination = cache_dir / "Copenhagen.osm.pbf"
    downloaded = False
    if force or not destination.exists() or destination.stat().st_size < 1_000_000:
        temporary = destination.with_suffix(".pbf.part")
        urlretrieve(COPENHAGEN_PBF_URL, temporary)
        temporary.replace(destination)
        downloaded = True
    info = {
        "pbf_url": COPENHAGEN_PBF_URL,
        "pbf_last_modified": COPENHAGEN_PBF_LAST_MODIFIED,
        "pbf_bytes": destination.stat().st_size,
        "pbf_sha256": _sha256(destination),
        "pbf_downloaded_this_run": downloaded,
        "pbf_path": str(destination),
    }
    return destination, info


def bike_graph_from_pbf(
    polygon: Any,
    *,
    cache_folder: str,
    pbf_cache: Path,
    simplify: bool = True,
    retain_all: bool = True,
    truncate_by_edge: bool = False,
    force_download: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """Build a directed bike graph with OSMnx from the Copenhagen PBF and clip it.

    The public Overpass interpreter refused connections from this network
    (one advertised address rejects TCP/443). The PBF is a dated OpenStreetMap
    extract of Copenhagen. Clipping with ``truncate_graph_polygon`` is what
    fixes the study boundary to the pilot rectangle.
    """
    import osmnx as ox

    configure_osmnx(cache_folder)
    pbf_path, pbf_info = ensure_copenhagen_pbf(pbf_cache, force=force_download)
    city = ox.graph.graph_from_pbf(
        pbf_path,
        network_type="bike",
        simplify=simplify,
        retain_all=True,
    )
    city_nodes = int(city.number_of_nodes())
    city_edges = int(city.number_of_edges())
    clipped = ox.truncate.truncate_graph_polygon(
        city,
        polygon,
        truncate_by_edge=truncate_by_edge,
    )
    # retain_all on the city graph keeps fragments there. Truncation can split
    # the study rectangle into several components; keep them for the audit.
    if not retain_all and clipped.number_of_nodes():
        clipped, _info = largest_strong_subgraph(clipped)
    metadata = {
        "pipeline_version": PIPELINE_VERSION,
        "extraction_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": "OpenStreetMap",
        "access": (
            "OSMnx graph_from_pbf on the BBBike Copenhagen extract, "
            "then truncate_graph_polygon to the study rectangle"
        ),
        "license": "ODbL",
        "attribution": "© OpenStreetMap contributors",
        "overpass_url": None,
        "overpass_filter": bike_overpass_filter(),
        "overpass_note": (
            "The filter string is the OSMnx bike preset. The PBF loader applies "
            "that preset in Python, including the default private-access exclusion. "
            "It is not an Overpass response."
        ),
        "network_type": "bike",
        "simplify": simplify,
        "retain_all": retain_all,
        "truncate_by_edge": truncate_by_edge,
        "bidirectional_network_types": list(ox.settings.bidirectional_network_types),
        "useful_tags_way": list(ox.settings.useful_tags_way),
        "osmnx_version": package_version("osmnx"),
        "networkx_version": package_version("networkx"),
        "shapely_version": package_version("shapely"),
        "pyproj_version": package_version("pyproj"),
        "input_crs": str(clipped.graph.get("crs", "EPSG:4326")),
        "polygon_wkt": polygon.wkt,
        "raw_nodes": int(clipped.number_of_nodes()),
        "raw_directed_edges": int(clipped.number_of_edges()),
        "city_extract_nodes": city_nodes,
        "city_extract_directed_edges": city_edges,
        "osm_data_timestamp": COPENHAGEN_PBF_LAST_MODIFIED,
        **pbf_info,
    }
    clipped.graph["cyclesense_pipeline"] = PIPELINE_VERSION
    clipped.graph["cyclesense_extraction_utc"] = metadata["extraction_utc"]
    clipped.graph["cyclesense_osm_data_timestamp"] = COPENHAGEN_PBF_LAST_MODIFIED
    return clipped, metadata


def add_contraflow_edges(graph: Any) -> int:
    """Add a reverse edge where bicycle tags unambiguously allow contraflow.

    Existing reverse edges are left untouched. The new edge copies length,
    OSM ids, and highway tags, and reverses a LineString when one is present.
    """
    pending: list[tuple[int, int, dict[str, Any]]] = []
    for u_node, v_node, _key, data in graph.edges(keys=True, data=True):
        if u_node == v_node or graph.has_edge(v_node, u_node):
            continue
        if indicates_contraflow(data):
            pending.append((u_node, v_node, data))
    added = 0
    for u_node, v_node, data in pending:
        if graph.has_edge(v_node, u_node):
            continue
        attributes = dict(data)
        attributes["added_contraflow"] = True
        geometry = attributes.get("geometry")
        if geometry is not None and hasattr(geometry, "reverse"):
            attributes["geometry"] = geometry.reverse()
        graph.add_edge(v_node, u_node, **attributes)
        added += 1
    return added


def assign_physical_edge_ids(graph: Any) -> int:
    """Write ``physical_edge_id`` on every directed edge. Return the unique count."""
    seen: set[str] = set()
    for u_node, v_node, key, data in graph.edges(keys=True, data=True):
        edge_id = physical_edge_id(u_node, v_node, data.get("osmid"), key=key)
        data["physical_edge_id"] = edge_id
        seen.add(edge_id)
    return len(seen)


def _length_m(data: dict[str, Any]) -> float | None:
    raw = data.get("length")
    try:
        length = float(raw)
    except (TypeError, ValueError):
        return None
    if not isfinite(length):
        return None
    return length


def drop_unroutable_edges(graph: Any) -> int:
    """Remove self-loops and edges without a positive finite length. Return the count."""
    remove = []
    for u_node, v_node, key, data in graph.edges(keys=True, data=True):
        length = _length_m(data)
        if u_node == v_node or length is None or length <= 0:
            remove.append((u_node, v_node, key))
    graph.remove_edges_from(remove)
    return len(remove)


def largest_strong_subgraph(graph: Any) -> tuple[Any, dict[str, int]]:
    """Copy the largest strongly connected component."""
    nx = _nx()
    components = list(nx.strongly_connected_components(graph))
    if not components:
        raise ValueError("graph has no nodes")
    largest = max(components, key=len)
    routing = graph.subgraph(largest).copy()
    info = {
        "strong_components_before": len(components),
        "largest_scc_nodes": len(largest),
        "nodes_dropped": int(graph.number_of_nodes()) - len(largest),
    }
    return routing, info


def node_coordinates(graph: Any) -> dict[int, tuple[float, float]]:
    """Return node id -> (x, y) using the graph's current coordinate units."""
    coordinates: dict[int, tuple[float, float]] = {}
    for node, data in graph.nodes(data=True):
        coordinates[int(node)] = (float(data["x"]), float(data["y"]))
    return coordinates


def project_to_metres(graph: Any) -> tuple[Any, str]:
    """Project to the UTM zone OSMnx selects for this graph."""
    import osmnx as ox

    projected = ox.project_graph(graph)
    crs = projected.graph.get("crs")
    return projected, str(crs)


def project_lonlat(lon: float, lat: float, crs: Any) -> tuple[float, float]:
    """Project one WGS84 point into ``crs``."""
    from pyproj import Transformer

    transformer = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    easting, northing = transformer.transform(lon, lat)
    return float(easting), float(northing)


def nearest_node(
    coordinates_m: dict[int, tuple[float, float]],
    xy: tuple[float, float],
) -> tuple[int, float]:
    """Return the closest node id and its distance in metres."""
    best_node = None
    best_distance = float("inf")
    for node, (x_coord, y_coord) in coordinates_m.items():
        distance = (x_coord - xy[0]) ** 2 + (y_coord - xy[1]) ** 2
        if distance < best_distance:
            best_node = node
            best_distance = distance
    if best_node is None:
        raise ValueError("no nodes to snap to")
    return best_node, best_distance**0.5


def _group_physical_edges(graph: Any) -> dict[str, list[tuple[Any, Any, Any, dict[str, Any]]]]:
    grouped: dict[str, list[tuple[Any, Any, Any, dict[str, Any]]]] = defaultdict(list)
    for u_node, v_node, key, data in graph.edges(keys=True, data=True):
        edge_id = data.get("physical_edge_id")
        if not edge_id:
            edge_id = physical_edge_id(u_node, v_node, data.get("osmid"), key=key)
            data["physical_edge_id"] = edge_id
        grouped[str(edge_id)].append((u_node, v_node, key, data))
    return grouped


def build_candidates(
    graph: Any,
    *,
    min_length_m: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Aggregate directed edges into physical segments and keep the eligible ones.

    Midpoints use the graph's node coordinates. Pass the WGS84 routing graph
    when lon/lat midpoints are required.
    """
    grouped = _group_physical_edges(graph)
    candidates: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for edge_id in sorted(grouped):
        records = grouped[edge_id]
        lengths = [length for _u, _v, _k, data in records if (length := _length_m(data)) and length > 0]
        highways: list[str] = []
        services: list[str] = []
        bicycles: list[str] = []
        accesses: list[str] = []
        names: list[str] = []
        contraflow = False
        for _u, _v, _k, data in records:
            highways.extend(as_tokens(data.get("highway")))
            services.extend(as_tokens(data.get("service")))
            bicycles.extend(as_tokens(data.get("bicycle")))
            accesses.extend(as_tokens(data.get("access")))
            names.extend(as_list(data.get("name")))
            contraflow = contraflow or str(data.get("added_contraflow")).lower() == "true"
        endpoints = {int(records[0][0]), int(records[0][1])}
        if len(endpoints) != 2:
            reasons["not_a_single_segment"] += 1
            continue
        u_node, v_node = sorted(endpoints)
        u_xy = graph.nodes[u_node]
        v_xy = graph.nodes[v_node]
        segment = {
            "u": u_node,
            "v": v_node,
            "length_m": max(lengths) if lengths else 0.0,
            "highway": highways,
            "service": services,
            "bicycle": bicycles,
            "access": accesses,
        }
        reason = eligibility_decision(segment, min_length_m=min_length_m)
        if reason is not None:
            reasons[reason] += 1
            continue
        unique_names: list[str] = []
        for name in names:
            if name not in unique_names:
                unique_names.append(name)
        candidates.append(
            {
                "physical_edge_id": edge_id,
                "u": u_node,
                "v": v_node,
                "length_m": round(float(segment["length_m"]), 2),
                "highway": "|".join(sorted(set(highways))),
                "name": " / ".join(unique_names)[:80],
                "service": "|".join(sorted(set(services))),
                "bicycle": "|".join(sorted(set(bicycles))),
                "n_directed": len(records),
                "oneway": len(records) == 1,
                "added_contraflow": contraflow,
                "midpoint_x": (float(u_xy["x"]) + float(v_xy["x"])) / 2,
                "midpoint_y": (float(u_xy["y"]) + float(v_xy["y"])) / 2,
            }
        )
    stats = {
        "n_physical_segments": len(grouped),
        "n_candidates": len(candidates),
        "rejection_counts": dict(reasons),
    }
    return candidates, stats


def audit_topology(graph: Any) -> dict[str, Any]:
    """Component, length, and highway-tag audit of a directed graph."""
    nx = _nx()
    weak = sorted((len(component) for component in nx.weakly_connected_components(graph)), reverse=True)
    strong = sorted((len(component) for component in nx.strongly_connected_components(graph)), reverse=True)
    lengths = []
    bad_lengths = 0
    highways: Counter[str] = Counter()
    for _u, _v, data in graph.edges(data=True):
        length = _length_m(data)
        if length is None or length <= 0:
            bad_lengths += 1
        else:
            lengths.append(length)
        tokens = as_tokens(data.get("highway")) or ["(missing)"]
        highways[tokens[0]] += 1
    n_nodes = int(graph.number_of_nodes())
    largest_strong = strong[0] if strong else 0
    return {
        "n_nodes": n_nodes,
        "n_directed_edges": int(graph.number_of_edges()),
        "n_weak_components": len(weak),
        "weak_component_sizes_top5": weak[:5],
        "n_strong_components": len(strong),
        "strong_component_sizes_top5": strong[:5],
        "largest_scc_fraction": (largest_strong / n_nodes) if n_nodes else 0.0,
        "length_m": {
            "min": min(lengths) if lengths else None,
            "median": float(median(lengths)) if lengths else None,
            "max": max(lengths) if lengths else None,
            "missing_or_nonpositive": bad_lengths,
        },
        "highway_counts": dict(highways),
    }


def routing_feasibility(
    graph: Any,
    *,
    n_pairs: int,
    seed: int,
) -> dict[str, float | int]:
    """Fraction of random ordered node pairs that have a positive-length path.

    In a strongly connected component with usable lengths this should be 1.
    On the unfiltered download it measures one-way traps and fragments.
    """
    nx = _nx()
    nodes = sorted(int(node) for node in graph.nodes)
    if len(nodes) < 2 or n_pairs <= 0:
        return {"pairs": 0, "paths_found": 0, "success_fraction": 0.0}
    rng_seed = seed
    import random

    rng = random.Random(rng_seed)
    found = 0
    tried = 0
    seen: set[tuple[int, int]] = set()
    guard = 0
    while tried < n_pairs and guard < n_pairs * 30:
        guard += 1
        origin = rng.choice(nodes)
        destination = rng.choice(nodes)
        pair = (origin, destination)
        if origin == destination or pair in seen:
            continue
        seen.add(pair)
        tried += 1
        try:
            path = nx.shortest_path(graph, origin, destination, weight="length")
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        if len(path) >= 2:
            found += 1
    return {
        "pairs": tried,
        "paths_found": found,
        "success_fraction": (found / tried) if tried else 0.0,
    }


def collect_quality_issues(
    *,
    full_audit: dict[str, Any],
    edges_removed: int,
    scc_info: dict[str, int],
    full_feasibility: dict[str, Any],
    routing_feasibility_stats: dict[str, Any],
    anchor_snap_m: float | None,
) -> list[str]:
    """Data-quality notes that should travel with the pilot. Not traffic findings."""
    issues: list[str] = []
    if edges_removed:
        issues.append(
            f"Removed {edges_removed} directed edges with a self-loop or a missing/non-positive "
            "length before building the routing component."
        )
    fraction = float(full_audit.get("largest_scc_fraction") or 0)
    strong_sizes = full_audit.get("strong_component_sizes_top5") or [0]
    if fraction < 0.95:
        issues.append(
            "Largest strongly connected component holds "
            f"{fraction:.1%} of downloaded nodes "
            f"({strong_sizes[0]} of {full_audit.get('n_nodes')} nodes; "
            f"{scc_info.get('nodes_dropped')} nodes dropped when the routing "
            "graph was cut to that component). Routes never start or end outside it."
        )
    weak_components = int(full_audit.get("n_weak_components") or 0)
    if weak_components > 1:
        sizes = full_audit.get("weak_component_sizes_top5")
        issues.append(
            f"Downloaded graph has {weak_components} weakly connected components; "
            f"the largest sizes are {sizes}. Border cuts and disconnected cycleways "
            "are the usual cause."
        )
    full_rate = float(full_feasibility.get("success_fraction") or 0)
    if full_rate < 0.9:
        issues.append(
            "On the full directed graph, "
            f"{full_feasibility.get('paths_found')} of {full_feasibility.get('pairs')} "
            f"random node pairs have a path ({full_rate:.1%}). Pairs outside one "
            "strong component are not routable."
        )
    routing_rate = float(routing_feasibility_stats.get("success_fraction") or 0)
    if routing_rate < 1:
        issues.append(
            "Routing component still failed "
            f"{routing_feasibility_stats.get('pairs', 0) - routing_feasibility_stats.get('paths_found', 0)} "
            "sampled shortest paths. Length attributes or a component bug need another look."
        )
    if anchor_snap_m is not None and anchor_snap_m > 300:
        issues.append(
            f"Commuter-proxy anchor snapped to a node {anchor_snap_m:.0f} m away. "
            "The kernel still uses the anchor coordinates, but the study rectangle "
            "may not contain that place."
        )
    return issues
