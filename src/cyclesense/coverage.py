"""Exact weighted route coverage and deterministic greedy maximum-coverage baseline.

The routes are synthetic or otherwise explicitly documented. A counter sits on an
eligible route edge, not inside a geographic detection radius. This module does
not model real Copenhagen traffic.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass
from math import isfinite

Edge = Hashable
RouteId = str


@dataclass(frozen=True)
class PlacementResult:
    selected_edges: tuple[Edge, ...]
    covered_weight: float
    total_weight: float

    @property
    def coverage_fraction(self) -> float:
        """Fraction of route weight intercepted at least once."""
        return self.covered_weight / self.total_weight if self.total_weight else 0.0


def _normalize_routes(
    routes: Mapping[RouteId, Iterable[Edge]],
    weights: Mapping[RouteId, float] | None,
) -> tuple[dict[RouteId, set[Edge]], dict[RouteId, float]]:
    if not routes:
        raise ValueError("routes must contain at least one modeled journey")
    normalized = {route_id: set(edges) for route_id, edges in routes.items()}
    effective_weights: dict[RouteId, float] = {}
    for route_id in normalized:
        weight = float(weights[route_id]) if weights and route_id in weights else 1.0
        if not isfinite(weight) or weight < 0:
            raise ValueError(f"invalid route weight for {route_id!r}")
        effective_weights[route_id] = weight
    if sum(effective_weights.values()) <= 0:
        raise ValueError("total modeled-route weight must be positive")
    return normalized, effective_weights


def evaluate_coverage(
    routes: Mapping[RouteId, Iterable[Edge]],
    selected_edges: Iterable[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> PlacementResult:
    """Score any counter set without counting a route twice."""
    route_sets, effective_weights = _normalize_routes(routes, weights)
    selected = set(selected_edges)
    covered_weight = sum(
        effective_weights[route_id]
        for route_id, edges in route_sets.items()
        if edges.intersection(selected)
    )
    return PlacementResult(
        selected_edges=tuple(sorted(selected, key=repr)),
        covered_weight=covered_weight,
        total_weight=sum(effective_weights.values()),
    )


def greedy_max_coverage(
    routes: Mapping[RouteId, Iterable[Edge]],
    budget: int,
    eligible_edges: Iterable[Edge] | None = None,
    weights: Mapping[RouteId, float] | None = None,
) -> PlacementResult:
    """Select up to K edges by the largest additional uncovered route weight.

    Tie-breaking is deterministic, sorted by repr(edge). This is an exact
    marginal-gain greedy baseline, not a global optimum solver. The standard
    approximation guarantee applies only to the unmodified coverage objective.
    """
    if budget < 0:
        raise ValueError("budget must be nonnegative")
    route_sets, effective_weights = _normalize_routes(routes, weights)
    incidence: dict[Edge, set[RouteId]] = defaultdict(set)
    for route_id, edges in route_sets.items():
        for edge in edges:
            incidence[edge].add(route_id)
    candidates = set(incidence) if eligible_edges is None else set(eligible_edges)
    selected: list[Edge] = []
    covered_routes: set[RouteId] = set()
    for _ in range(min(budget, len(candidates))):
        best_edge = None
        best_gain = 0.0
        for edge in sorted(candidates, key=repr):
            if edge in selected:
                continue
            gain = sum(
                effective_weights[rid] for rid in incidence.get(edge, set())
                if rid not in covered_routes
            )
            if gain > best_gain:
                best_edge, best_gain = edge, gain
        if best_edge is None:
            break
        selected.append(best_edge)
        covered_routes.update(incidence[best_edge])
    return PlacementResult(
        selected_edges=tuple(selected),
        covered_weight=sum(effective_weights[rid] for rid in covered_routes),
        total_weight=sum(effective_weights.values()),
    )
