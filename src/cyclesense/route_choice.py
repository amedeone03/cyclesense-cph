"""Alternative routes from seeded edge-cost perturbations.

The original evaluation origin and destination stay fixed. One draw assigns
every directed edge a positive multiplier, ``exp(sigma * Z)`` with ``Z``
standard normal. The alternative is the shortest path under length times that
multiplier. Its detour uses the original edge lengths:

    detour = alternative_length / shortest_length - 1

A path is kept only when it uses a different physical-edge sequence and the
detour is within the cap. Otherwise the recorded route is the original
shortest path and the status says why. These paths are simulated. They are
not observed cycling journeys.
"""

from __future__ import annotations

import heapq
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from statistics import median, quantiles
from typing import Any

from cyclesense.coverage import evaluate_coverage
from cyclesense.routes import lightest_edge

RouteId = str


@dataclass(frozen=True)
class Adjacency:
    """Outgoing directed edges, including parallel-edge keys."""

    nodes: tuple[tuple[int, int, Any, float, str], ...]
    by_source: dict[int, tuple[tuple[int, int, Any, float, str], ...]]


@dataclass(frozen=True)
class RoutedPath:
    origin: int
    destination: int
    edges: tuple[tuple[int, int, Any], ...]
    physical_edge_ids: tuple[str, ...]
    length_m: float


@dataclass(frozen=True)
class AlternativeRoute:
    status: str
    path: RoutedPath
    detour: float | None
    proposed_detour: float | None
    proposed_physical_edge_ids: tuple[str, ...]


def build_adjacency(graph: Any) -> Adjacency:
    """Copy directed edges so later routing cannot rewrite the graph."""
    rows: list[tuple[int, int, Any, float, str]] = []
    for u_node, v_node, key, data in graph.edges(keys=True, data=True):
        if "physical_edge_id" not in data or "length" not in data:
            raise ValueError(f"edge {u_node}->{v_node} key {key} lacks length or physical id")
        length = float(data["length"])
        if length <= 0:
            raise ValueError(f"edge {u_node}->{v_node} key {key} has non-positive length")
        rows.append((int(u_node), int(v_node), key, length, str(data["physical_edge_id"])))
    by_source: dict[int, list[tuple[int, int, Any, float, str]]] = {}
    for row in rows:
        by_source.setdefault(row[0], []).append(row)
    return Adjacency(
        nodes=tuple(rows),
        by_source={source: tuple(items) for source, items in by_source.items()},
    )


def edge_cost_factors(adjacency: Adjacency, seed: int, sigma: float) -> dict[tuple[int, int, Any], float]:
    """Positive multipliers in sorted edge order, so the draw does not follow graph order."""
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    generator = random.Random(seed)
    factors: dict[tuple[int, int, Any], float] = {}
    for u_node, v_node, key, _length, _edge_id in sorted(
        adjacency.nodes, key=lambda row: (row[0], row[1], str(row[2]))
    ):
        factors[(u_node, v_node, key)] = math.exp(sigma * generator.gauss(0.0, 1.0))
    return factors


def shortest_path_from_nodes(graph: Any, node_ids: Sequence[int]) -> RoutedPath:
    """Rebuild the M1 path by the same lightest-parallel-edge rule."""
    nodes = [int(node) for node in node_ids]
    if len(nodes) < 2:
        raise ValueError("a route needs an origin and a destination")
    edges: list[tuple[int, int, Any]] = []
    for u_node, v_node in pairwise(nodes):
        chosen = lightest_edge(graph, u_node, v_node)
        key = next(key for key, data in graph[u_node][v_node].items() if data is chosen)
        edges.append((u_node, v_node, key))
    return _path_from_edges(graph, edges)


def proposed_shortest(
    adjacency: Adjacency,
    origin: int,
    destination: int,
    factors: Mapping[tuple[int, int, Any], float],
) -> RoutedPath | None:
    """Shortest path under perturbed costs, measured later on original lengths."""
    edges = _dijkstra_edges(adjacency, origin, destination, factors)
    if not edges:
        return None
    proposed = _path_from_adjacency(adjacency, edges)
    _validate_path(adjacency, proposed)
    if proposed.origin != origin or proposed.destination != destination:
        raise RuntimeError("alternative route changed the origin or destination")
    return proposed


def classify_proposal(
    original: RoutedPath,
    proposed: RoutedPath | None,
    max_detour: float,
) -> AlternativeRoute:
    """Accept a different physical path inside the detour cap, or record the fallback."""
    if max_detour < 0:
        raise ValueError("max_detour must be non-negative")
    if original.length_m <= 0:
        raise ValueError("original route length must be positive")
    if proposed is None:
        return AlternativeRoute("failed", original, None, None, ())
    detour = proposed.length_m / original.length_m - 1.0
    if detour < -1e-6:
        raise RuntimeError("perturbed path is shorter on the original lengths than the recorded shortest path")
    if proposed.physical_edge_ids == original.physical_edge_ids:
        return AlternativeRoute("unchanged", original, 0.0, detour, proposed.physical_edge_ids)
    if detour > max_detour + 1e-9:
        return AlternativeRoute("rejected_detour", original, None, detour, proposed.physical_edge_ids)
    return AlternativeRoute("changed", proposed, detour, detour, proposed.physical_edge_ids)


def alternative_route(
    adjacency: Adjacency,
    original: RoutedPath,
    factors: Mapping[tuple[int, int, Any], float],
    max_detour: float,
) -> AlternativeRoute:
    """One perturbed shortest path, or an explicit fallback to ``original``."""
    proposed = proposed_shortest(adjacency, original.origin, original.destination, factors)
    return classify_proposal(original, proposed, max_detour)


def eligible_ids(physical_edge_ids: Sequence[str], candidate_ids: set[str]) -> tuple[str, ...]:
    """Eligible counter sites along a physical path, in traversal order."""
    return tuple(edge_id for edge_id in physical_edge_ids if edge_id in candidate_ids)


def set_jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    """Jaccard similarity of two physical-edge sets."""
    first, second = set(left), set(right)
    if not first and not second:
        return 1.0
    return len(first & second) / len(first | second)


def coverage_transition(
    original: Mapping[RouteId, set[str]],
    alternative: Mapping[RouteId, set[str]],
    selected: Sequence[str],
) -> dict[str, float | int]:
    """Paired coverage change for one fixed counter set.

    Lost routes were covered by the shortest path and missed by the
    alternative. Gained routes are the opposite. The net change divided by
    the number of routes is the coverage difference.
    """
    if set(original) != set(alternative):
        raise ValueError("original and alternative routes must be the same OD observations")
    chosen = set(selected)
    lost = gained = stayed_covered = stayed_uncovered = 0
    for route_id, before_edges in original.items():
        before = bool(before_edges & chosen)
        after = bool(alternative[route_id] & chosen)
        if before and after:
            stayed_covered += 1
        elif before and not after:
            lost += 1
        elif after and not before:
            gained += 1
        else:
            stayed_uncovered += 1
    total = len(original)
    shortest = (stayed_covered + lost) / total if total else 0.0
    perturbed = (stayed_covered + gained) / total if total else 0.0
    direct_shortest = evaluate_coverage(original, selected).coverage_fraction
    direct_perturbed = evaluate_coverage(alternative, selected).coverage_fraction
    if abs(direct_shortest - shortest) > 1e-12 or abs(direct_perturbed - perturbed) > 1e-12:
        raise RuntimeError("transition counts do not match coverage")
    return {
        "n_routes": total,
        "shortest_coverage": shortest,
        "alternative_coverage": perturbed,
        "difference": perturbed - shortest,
        "n_lost": lost,
        "n_gained": gained,
        "n_net": gained - lost,
        "n_stayed_covered": stayed_covered,
        "n_stayed_uncovered": stayed_uncovered,
    }


def detour_summary(values: Sequence[float]) -> dict[str, float | None]:
    """Mean, median, 90th percentile, and maximum of accepted detours."""
    if not values:
        return {"mean": None, "median": None, "p90": None, "max": None}
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        only = ordered[0]
        return {"mean": only, "median": only, "p90": only, "max": only}
    return {
        "mean": sum(ordered) / len(ordered),
        "median": float(median(ordered)),
        "p90": float(quantiles(ordered, n=10, method="inclusive")[8]),
        "max": ordered[-1],
    }


def _dijkstra_edges(
    adjacency: Adjacency,
    source: int,
    target: int,
    factors: Mapping[tuple[int, int, Any], float],
) -> list[tuple[int, int, Any]] | None:
    if source == target:
        return []
    distance = {source: 0.0}
    previous: dict[int, tuple[int, Any]] = {}
    heap = [(0.0, source)]
    settled: set[int] = set()
    while heap:
        current, node = heapq.heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        if node == target:
            break
        for _u_node, v_node, key, length, _edge_id in adjacency.by_source.get(node, ()):
            step = length * factors[(node, v_node, key)]
            if step <= 0:
                raise ValueError("perturbed routing cost must be positive")
            updated = current + step
            if updated < distance.get(v_node, math.inf):
                distance[v_node] = updated
                previous[v_node] = (node, key)
                heapq.heappush(heap, (updated, v_node))
    if target not in distance:
        return None
    edges: list[tuple[int, int, Any]] = []
    node = target
    while node != source:
        previous_node, key = previous[node]
        edges.append((previous_node, node, key))
        node = previous_node
    edges.reverse()
    return edges


def _path_from_edges(graph: Any, edges: Sequence[tuple[int, int, Any]]) -> RoutedPath:
    if not edges:
        raise ValueError("path has no edges")
    physical: list[str] = []
    length = 0.0
    for u_node, v_node, key in edges:
        data = graph[u_node][v_node][key]
        length += float(data["length"])
        edge_id = str(data["physical_edge_id"])
        if not physical or physical[-1] != edge_id:
            physical.append(edge_id)
    return RoutedPath(edges[0][0], edges[-1][1], tuple(edges), tuple(physical), length)


def _path_from_adjacency(
    adjacency: Adjacency, edges: Sequence[tuple[int, int, Any]]
) -> RoutedPath:
    lookup = {(u_node, v_node, key): (length, edge_id) for u_node, v_node, key, length, edge_id in adjacency.nodes}
    physical: list[str] = []
    length = 0.0
    for u_node, v_node, key in edges:
        step, edge_id = lookup[(u_node, v_node, key)]
        length += step
        if not physical or physical[-1] != edge_id:
            physical.append(edge_id)
    return RoutedPath(edges[0][0], edges[-1][1], tuple(edges), tuple(physical), length)


def _validate_path(adjacency: Adjacency, path: RoutedPath) -> None:
    if not path.edges:
        raise ValueError("alternative path is empty")
    if path.edges[0][0] != path.origin or path.edges[-1][1] != path.destination:
        raise ValueError("path endpoints do not match the recorded path")
    known = {(u_node, v_node, key) for u_node, v_node, key, _length, _edge_id in adjacency.nodes}
    for u_node, v_node, key in path.edges:
        if (u_node, v_node, key) not in known:
            raise ValueError(f"path uses a missing directed edge {u_node}->{v_node} key {key}")
    for left, right in pairwise(path.edges):
        if left[1] != right[0]:
            raise ValueError("path is disconnected")
