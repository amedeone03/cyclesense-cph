"""M2 counter-placement baselines on eligible physical segments.

Selection uses calibration routes only. Held-out routes are scored afterwards
with ``evaluate_coverage``, which counts each route at most once. Random and
geographic K-Means are the stochastic methods. Route frequency and greedy
maximum coverage are deterministic.

Nothing here is an observed bicycle count.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from math import cos, hypot, radians
from typing import Any

from cyclesense.coverage import evaluate_coverage, greedy_max_coverage

Edge = str
RouteId = str

METHODS = ("random", "geographical_kmeans", "route_frequency", "greedy")
STOCHASTIC_METHODS = frozenset({"random", "geographical_kmeans"})
METHOD_LABELS = {
    "random": "Random",
    "geographical_kmeans": "Geographic K-Means",
    "route_frequency": "Route frequency",
    "greedy": "Greedy maximum coverage",
}

# Metres per degree. Used only to place geographic K-Means in a local plane.
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_EQUATOR = 111_320.0


@dataclass(frozen=True)
class CandidateSite:
    edge_id: str
    lon: float
    lat: float
    x_m: float
    y_m: float
    name: str = ""
    highway: str = ""


def local_metres(lon: float, lat: float, lon0: float, lat0: float) -> tuple[float, float]:
    """Equirectangular metres relative to a reference longitude and latitude."""
    x_m = (lon - lon0) * _M_PER_DEG_LON_EQUATOR * cos(radians(lat0))
    y_m = (lat - lat0) * _M_PER_DEG_LAT
    return x_m, y_m


def candidate_sites(rows: Sequence[Mapping[str, Any]]) -> tuple[CandidateSite, ...]:
    """Project eligible-segment midpoints. Row order does not affect later sorts."""
    if not rows:
        raise ValueError("candidate table is empty")
    lon0 = sum(float(row["midpoint_lon"]) for row in rows) / len(rows)
    lat0 = sum(float(row["midpoint_lat"]) for row in rows) / len(rows)
    sites = []
    for row in rows:
        lon = float(row["midpoint_lon"])
        lat = float(row["midpoint_lat"])
        x_m, y_m = local_metres(lon, lat, lon0, lat0)
        sites.append(
            CandidateSite(
                edge_id=str(row["physical_edge_id"]),
                lon=lon,
                lat=lat,
                x_m=x_m,
                y_m=y_m,
                name=str(row.get("name") or ""),
                highway=str(row.get("highway") or ""),
            )
        )
    return tuple(sorted(sites, key=lambda site: site.edge_id))


def fill_to_k(selected: Sequence[Edge], eligible_ids: Iterable[Edge], k: int) -> tuple[Edge, ...]:
    """Keep selection order, then add unused eligible ids until the set has size K.

    Greedy stops when every remaining segment adds zero uncovered calibration
    weight. Those extra segments do not change coverage. They keep every
    reported placement at exactly K distinct eligible ids.
    """
    if k < 0:
        raise ValueError("budget must be nonnegative")
    chosen: list[Edge] = []
    seen: set[Edge] = set()
    for edge in selected:
        if edge in seen:
            continue
        chosen.append(edge)
        seen.add(edge)
        if len(chosen) == k:
            return tuple(chosen)
    for edge in sorted(eligible_ids):
        if edge in seen:
            continue
        chosen.append(edge)
        seen.add(edge)
        if len(chosen) == k:
            return tuple(chosen)
    raise ValueError(f"needed {k} eligible segments, found {len(chosen)}")


def assert_selection(selected: Sequence[Edge], eligible_ids: Iterable[Edge], k: int) -> None:
    eligible = set(eligible_ids)
    if len(selected) != k or len(set(selected)) != k:
        raise ValueError(f"selection is not exactly {k} distinct segments: {selected!r}")
    if not set(selected) <= eligible:
        raise ValueError("selection includes a segment outside the eligible candidate set")


def select_random(eligible_ids: Iterable[Edge], k: int, seed: int) -> tuple[Edge, ...]:
    """Sample K eligible ids. The population is sorted before sampling."""
    import random

    population = sorted(set(eligible_ids))
    if k > len(population):
        raise ValueError("budget exceeds the eligible candidate set")
    if k == 0:
        return ()
    drawn = random.Random(seed).sample(population, k)
    return tuple(sorted(drawn))


def snap_centroids(
    centroids: Sequence[Sequence[float]],
    sites: Sequence[CandidateSite],
) -> tuple[Edge, ...]:
    """Assign each centroid to the nearest still-unused candidate, in given order.

    Distance is squared Euclidean metres. An exact tie uses the smaller edge id.
    """
    chosen: list[Edge] = []
    used: set[Edge] = set()
    for centroid in centroids:
        best: CandidateSite | None = None
        best_distance = float("inf")
        cx, cy = float(centroid[0]), float(centroid[1])
        for site in sites:
            if site.edge_id in used:
                continue
            distance = (site.x_m - cx) ** 2 + (site.y_m - cy) ** 2
            if distance < best_distance or (
                distance == best_distance and (best is None or site.edge_id < best.edge_id)
            ):
                best = site
                best_distance = distance
        if best is None:
            break
        used.add(best.edge_id)
        chosen.append(best.edge_id)
    return tuple(chosen)


def select_kmeans(sites: Sequence[CandidateSite], k: int, seed: int) -> tuple[Edge, ...]:
    """Lloyd K-Means in local metres, then snap centroids onto eligible segments."""
    import numpy as np
    from sklearn.cluster import KMeans

    ordered = tuple(sorted(sites, key=lambda site: site.edge_id))
    if k > len(ordered):
        raise ValueError("budget exceeds the eligible candidate set")
    if k == 0:
        return ()
    coordinates = np.array([[site.x_m, site.y_m] for site in ordered], dtype=float)
    model = KMeans(n_clusters=k, random_state=seed, n_init=10, algorithm="lloyd")
    model.fit(coordinates)
    selected = snap_centroids(model.cluster_centers_, ordered)
    return fill_to_k(selected, [site.edge_id for site in ordered], k)


def select_frequency(
    eligible_ids: Iterable[Edge],
    routes: Mapping[RouteId, Iterable[Edge]],
    k: int,
    weights: Mapping[RouteId, float] | None = None,
) -> tuple[Edge, ...]:
    """Rank eligible segments by calibration route weight, then by edge id."""
    eligible = set(eligible_ids)
    if k > len(eligible):
        raise ValueError("budget exceeds the eligible candidate set")
    counts = dict.fromkeys(eligible, 0.0)
    for route_id, edges in routes.items():
        weight = 1.0 if weights is None else float(weights.get(route_id, 1.0))
        for edge in set(edges):
            if edge in counts:
                counts[edge] += weight
    ranked = sorted(eligible, key=lambda edge: (-counts[edge], edge))
    return tuple(ranked[:k])


def select_greedy(
    eligible_ids: Iterable[Edge],
    routes: Mapping[RouteId, Iterable[Edge]],
    k: int,
    weights: Mapping[RouteId, float] | None = None,
) -> tuple[Edge, ...]:
    """Greedy maximum coverage on calibration routes, filled out to exactly K."""
    eligible = sorted(set(eligible_ids))
    if k > len(eligible):
        raise ValueError("budget exceeds the eligible candidate set")
    result = greedy_max_coverage(routes, k, eligible_edges=eligible, weights=weights)
    return fill_to_k(result.selected_edges, eligible, k)


def select_counters(
    method: str,
    sites: Sequence[CandidateSite],
    routes: Mapping[RouteId, Iterable[Edge]],
    k: int,
    *,
    seed: int | None = None,
    weights: Mapping[RouteId, float] | None = None,
) -> tuple[Edge, ...]:
    """Choose K eligible segments. ``routes`` must be the calibration split."""
    if method not in METHODS:
        raise ValueError(f"unknown placement method {method!r}")
    eligible_ids = [site.edge_id for site in sites]
    if method == "random":
        if seed is None:
            raise ValueError("random placement requires a seed")
        selected = select_random(eligible_ids, k, seed)
    elif method == "geographical_kmeans":
        if seed is None:
            raise ValueError("geographic K-Means requires a seed")
        selected = select_kmeans(sites, k, seed)
    elif method == "route_frequency":
        selected = select_frequency(eligible_ids, routes, k, weights)
    else:
        selected = select_greedy(eligible_ids, routes, k, weights)
    assert_selection(selected, eligible_ids, k)
    return selected


def mean_pairwise_distance_m(points: Sequence[tuple[float, float]]) -> float:
    """Mean Euclidean distance, in metres, between selected counter coordinates."""
    if len(points) < 2:
        return 0.0
    total = 0.0
    count = 0
    for (x1, y1), (x2, y2) in combinations(points, 2):
        total += hypot(x1 - x2, y1 - y2)
        count += 1
    return total / count


def multi_counter_fraction(
    routes: Mapping[RouteId, Iterable[Edge]],
    selected: Sequence[Edge],
) -> float:
    """Share of routes whose edge set meets at least two selected counters."""
    if not routes:
        return 0.0
    chosen = set(selected)
    hits = sum(1 for edges in routes.values() if len(set(edges) & chosen) >= 2)
    return hits / len(routes)


def score_split(
    routes: Mapping[RouteId, Iterable[Edge]],
    selected: Sequence[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> float:
    """Held-out or calibration coverage. Each route contributes its weight once."""
    return evaluate_coverage(routes, selected, weights).coverage_fraction
