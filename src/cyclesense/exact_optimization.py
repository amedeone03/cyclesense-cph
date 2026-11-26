"""Exact maximum coverage for simulated bicycle-counter placement.

The model maximizes the same weighted coverage as ``greedy_max_coverage``.
HiGHS, through ``scipy.optimize.milp``, minimizes the negative of that
objective. A run is optimal only when the solver status says so. The
reported coverage is recomputed from the selected physical-edge IDs.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

import numpy as np
from scipy import __version__ as SCIPY_VERSION
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import csc_array

from cyclesense.coverage import evaluate_coverage
from cyclesense.placement import assert_selection, fill_to_k

SOLVER_NAME = "scipy.optimize.milp"
SOLVER_BACKEND = "HiGHS"
SOLVER_VERSION = SCIPY_VERSION
APPROXIMATION_RATIO = 1.0 - math.exp(-1.0)
COVERAGE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class SolveResult:
    status: str
    proven_optimal: bool
    support: tuple[str, ...]
    selected: tuple[str, ...]
    coverage: float | None
    support_coverage: float | None
    solver_objective: float | None
    upper_bound: float | None
    relative_gap: float | None
    runtime_seconds: float
    message: str
    n_routes: int
    n_candidates: int
    n_nonzero: int
    k: int
    time_limit_seconds: float
    mip_rel_gap: float


def solve_maximum_coverage(
    routes: Mapping[str, Iterable[str]],
    weights: Mapping[str, float],
    eligible_ids: Iterable[str],
    k: int,
    *,
    time_limit_seconds: float = 120.0,
    mip_rel_gap: float = 1e-6,
) -> SolveResult:
    """Maximize weighted coverage with at most ``k`` eligible segments.

    The returned ``selected`` set has exactly ``k`` ids when a feasible
    incumbent exists. ``support`` is the segments the solver turned on.
    Extra ids come from the existing sorted fill rule and do not change
    coverage when the incumbent is optimal, because any unused segment
    then has zero marginal gain.
    """
    import time

    if k < 0:
        raise ValueError("budget must be nonnegative")
    if time_limit_seconds <= 0:
        raise ValueError("time limit must be positive")
    edges = tuple(sorted(set(eligible_ids)))
    if k > len(edges):
        raise ValueError("budget exceeds the eligible candidate set")
    route_ids = tuple(sorted(routes))
    if not route_ids:
        raise ValueError("maximum coverage needs at least one route")
    normalized = _weights(route_ids, weights)
    index = {edge: position for position, edge in enumerate(edges)}
    incidence = []
    n_nonzero = 0
    for route_id in route_ids:
        hits = tuple(sorted(index[edge] for edge in set(routes[route_id]) if edge in index))
        incidence.append(hits)
        n_nonzero += len(hits)
    started = time.perf_counter()
    raw = _solve_milp(edges, incidence, normalized, k, time_limit_seconds, mip_rel_gap)
    runtime = time.perf_counter() - started
    return _package(raw, edges, routes, normalized, k, runtime, n_nonzero, time_limit_seconds, mip_rel_gap)


def brute_force_maximum_coverage(
    routes: Mapping[str, Iterable[str]],
    weights: Mapping[str, float],
    eligible_ids: Iterable[str],
    k: int,
) -> tuple[tuple[str, ...], float]:
    """Best coverage over every subset of size at most ``k``.

    The search is only for tiny tests. Ties keep the lexicographic subset.
    """
    edges = tuple(sorted(set(eligible_ids)))
    if len(edges) > 12 or k > 5:
        raise ValueError("brute force is limited to 12 segments and K <= 5")
    route_ids = tuple(sorted(routes))
    normalized = _weights(route_ids, weights)
    best_set: tuple[str, ...] = ()
    best_value = -1.0
    for size in range(k + 1):
        for combo in combinations(edges, size):
            value = evaluate_coverage(routes, combo, normalized).covered_weight
            if value > best_value + 1e-12 or (abs(value - best_value) <= 1e-12 and combo < best_set):
                best_value = value
                best_set = combo
    return best_set, best_value


def greedy_optimality_gap(optimal: float, greedy: float, *, proven: bool) -> dict[str, float | None]:
    """Gap from a certified optimum. A time limit does not produce this gap."""
    if not proven:
        return {"absolute_gap": None, "relative_gap": None}
    if greedy > optimal + COVERAGE_TOLERANCE:
        raise ValueError("greedy coverage exceeds a certified optimum")
    absolute = max(0.0, optimal - greedy)
    if optimal <= COVERAGE_TOLERANCE:
        relative = 0.0 if absolute <= COVERAGE_TOLERANCE else math.inf
    else:
        relative = absolute / optimal
    return {"absolute_gap": absolute, "relative_gap": relative}


def meets_approximation_guarantee(greedy: float, optimal: float) -> bool:
    """Greedy is at least ``1 - 1/e`` of a certified nonnegative optimum."""
    if optimal < -COVERAGE_TOLERANCE or greedy < -COVERAGE_TOLERANCE:
        raise ValueError("coverage must be nonnegative")
    return greedy + 1e-8 >= APPROXIMATION_RATIO * max(optimal, 0.0)


def coverage_bounds(minimized_objective: float, dual_bound: float | None) -> tuple[float, float | None]:
    """Convert a minimized negative-coverage objective into coverage bounds.

    HiGHS minimizes, so the incumbent coverage is the negation of ``fun``.
    The dual bound is a lower bound on that minimized value and therefore
    an upper bound on coverage after negation.
    """
    incumbent = -float(minimized_objective)
    if dual_bound is None:
        return incumbent, None
    upper = -float(dual_bound)
    if upper + 1e-8 < incumbent:
        upper = incumbent
    return incumbent, upper


def _weights(route_ids: Sequence[str], weights: Mapping[str, float]) -> dict[str, float]:
    if set(weights) != set(route_ids):
        raise ValueError("weights must match the route ids exactly")
    normalized = {}
    for route_id in route_ids:
        weight = float(weights[route_id])
        if not math.isfinite(weight) or weight < 0:
            raise ValueError(f"invalid weight for {route_id}")
        normalized[route_id] = weight
    if sum(normalized.values()) <= 0:
        raise ValueError("total route weight must be positive")
    return normalized


def _solve_milp(
    edges: Sequence[str],
    incidence: Sequence[Sequence[int]],
    weights: Mapping[str, float],
    k: int,
    time_limit_seconds: float,
    mip_rel_gap: float,
) -> dict[str, object]:
    route_ids = list(weights)
    n_edges = len(edges)
    n_routes = len(route_ids)
    columns: list[int] = []
    rows: list[int] = []
    values: list[float] = []
    for route_index, hits in enumerate(incidence):
        for edge_index in hits:
            rows.append(route_index)
            columns.append(edge_index)
            values.append(1.0)
        rows.append(route_index)
        columns.append(n_edges + route_index)
        values.append(-1.0)
    for edge_index in range(n_edges):
        rows.append(n_routes)
        columns.append(edge_index)
        values.append(1.0)
    matrix = csc_array((values, (rows, columns)), shape=(n_routes + 1, n_edges + n_routes))
    lower = np.zeros(n_routes + 1)
    upper = np.full(n_routes + 1, np.inf)
    upper[-1] = k
    cost = np.zeros(n_edges + n_routes)
    for route_index, route_id in enumerate(route_ids):
        cost[n_edges + route_index] = -weights[route_id]
    result = milp(
        cost,
        integrality=np.ones(n_edges + n_routes),
        bounds=Bounds(0.0, 1.0),
        constraints=LinearConstraint(matrix, lower, upper),
        options={"time_limit": time_limit_seconds, "mip_rel_gap": mip_rel_gap, "disp": False},
    )
    return {
        "status_code": int(result.status),
        "message": str(result.message),
        "x": None if result.x is None else np.asarray(result.x, dtype=float),
        "fun": None if result.fun is None else float(result.fun),
        "dual": None if result.mip_dual_bound is None else float(result.mip_dual_bound),
        "route_ids": route_ids,
        "incidence": incidence,
    }


def _package(
    raw: dict[str, object],
    edges: Sequence[str],
    routes: Mapping[str, Iterable[str]],
    weights: Mapping[str, float],
    k: int,
    runtime: float,
    n_nonzero: int,
    time_limit_seconds: float,
    mip_rel_gap: float,
) -> SolveResult:
    status = _status(int(raw["status_code"]), raw["x"] is not None)
    proven = status == "optimal"
    incumbent = None
    upper = None
    gap = None
    support: tuple[str, ...] = ()
    selected: tuple[str, ...] = ()
    support_coverage = None
    coverage = None
    vector = raw["x"]
    if vector is not None and raw["fun"] is not None:
        chosen = _binary_support(np.asarray(vector, dtype=float), edges, k)
        support = chosen
        incumbent, upper = coverage_bounds(float(raw["fun"]), raw["dual"] if raw["dual"] is not None else None)
        gap = _bound_gap(incumbent, upper)
        recomputed = evaluate_coverage(routes, support, weights)
        if abs(recomputed.covered_weight - incumbent) > 1e-4:
            raise RuntimeError(
                f"solver objective {incumbent} does not match recomputed coverage {recomputed.covered_weight}"
            )
        support_coverage = recomputed.coverage_fraction
        selected = fill_to_k(support, edges, k)
        assert_selection(selected, edges, k)
        coverage = evaluate_coverage(routes, selected, weights).coverage_fraction
        if proven and abs(coverage - support_coverage) > 1e-8:
            raise RuntimeError("filling a certified optimum changed its coverage")
    elif status == "optimal":
        raise RuntimeError("HiGHS reported optimality without an incumbent")
    return SolveResult(
        status=status,
        proven_optimal=proven,
        support=support,
        selected=selected,
        coverage=coverage,
        support_coverage=support_coverage,
        solver_objective=incumbent,
        upper_bound=upper,
        relative_gap=gap,
        runtime_seconds=runtime,
        message=str(raw["message"]),
        n_routes=len(routes),
        n_candidates=len(edges),
        n_nonzero=n_nonzero,
        k=k,
        time_limit_seconds=time_limit_seconds,
        mip_rel_gap=mip_rel_gap,
    )


def _binary_support(values: np.ndarray, edges: Sequence[str], k: int) -> tuple[str, ...]:
    chosen = []
    for index, edge in enumerate(edges):
        value = float(values[index])
        if value > 0.5:
            if value < 1.0 - 1e-5:
                raise RuntimeError(f"solver returned a fractional counter {edge}={value}")
            chosen.append(edge)
        elif value > 1e-5:
            raise RuntimeError(f"solver returned a fractional counter {edge}={value}")
    if len(chosen) > k:
        raise RuntimeError(f"solver selected {len(chosen)} segments for budget {k}")
    return tuple(chosen)


def _status(code: int, has_incumbent: bool) -> str:
    if code == 0:
        return "optimal"
    if code == 1:
        return "time_limited" if has_incumbent else "no_incumbent"
    if code == 2:
        return "infeasible"
    if code == 3:
        return "unbounded"
    return "failed"


def _bound_gap(incumbent: float, upper: float | None) -> float | None:
    if upper is None:
        return None
    if upper <= COVERAGE_TOLERANCE:
        return 0.0 if incumbent <= COVERAGE_TOLERANCE else math.inf
    return max(0.0, (upper - incumbent) / upper)
