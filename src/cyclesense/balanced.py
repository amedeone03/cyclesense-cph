"""Community-balanced weights for the existing greedy coverage selector.

Lambda 0 gives every calibration route the same weight. Positive lambda moves
weight toward non-singleton Louvain communities, with each such community
receiving the same total balancing weight. Singleton routes keep only the
uniform coverage term, so they drop out of the objective only at lambda 1.
"""

import random
from collections import Counter
from collections.abc import Mapping, Sequence

RouteId = str


def community_weights(
    labels: Mapping[RouteId, int],
    lam: float,
) -> tuple[dict[RouteId, float], dict[str, object]]:
    """Return weights that sum to 1, plus a short description of the construction.

    ``g_r`` is ``1/|c|`` when route ``r`` sits in a community of size at least 2,
    and 0 for a singleton. If every community is a singleton, the balancing
    term is undefined and the result falls back to uniform weights.
    """
    if not labels:
        raise ValueError("community weights need at least one calibration route")
    if not 0.0 <= lam <= 1.0:
        raise ValueError("lambda must be between 0 and 1")
    sizes = Counter(labels.values())
    raw = {
        route_id: (1.0 / sizes[community] if sizes[community] >= 2 else 0.0)
        for route_id, community in labels.items()
    }
    total_raw = sum(raw.values())
    n_routes = len(labels)
    fallback = total_raw == 0.0 and lam > 0.0
    effective = 0.0 if fallback else lam
    balance = {route_id: (value / total_raw if total_raw else 0.0) for route_id, value in raw.items()}
    weights = {
        route_id: (1.0 - effective) / n_routes + effective * balance[route_id]
        for route_id in labels
    }
    return weights, {
        "lambda": lam,
        "effective_lambda": effective,
        "fallback_uniform": fallback,
        "n_routes": n_routes,
        "n_non_singleton_communities": sum(1 for size in sizes.values() if size >= 2),
        "weight_sum": sum(weights.values()),
    }


def shuffle_labels(labels: Mapping[RouteId, int], seed: int) -> dict[RouteId, int]:
    """Reassign the existing labels without changing the multiset of community sizes."""
    route_ids = sorted(labels)
    values = [labels[route_id] for route_id in route_ids]
    random.Random(seed).shuffle(values)
    return dict(zip(route_ids, values, strict=True))


def community_size_counts(labels: Mapping[RouteId, int]) -> tuple[int, ...]:
    """Sorted community sizes, including singletons."""
    return tuple(sorted(Counter(labels.values()).values()))


def represented_communities(
    routes: Mapping[RouteId, set[str]],
    labels: Mapping[RouteId, int],
    selected: Sequence[str],
    *,
    large_min_size: int = 2,
) -> dict[str, float | int]:
    """Training-set community coverage.

    A community is represented when at least one of its member routes intersects
    the selected counters. Large communities are those with size at least
    ``large_min_size``. Within-community coverage is the share of member routes
    that intersect the counters.
    """
    chosen = set(selected)
    members: dict[int, list[RouteId]] = {}
    for route_id, community in labels.items():
        members.setdefault(community, []).append(route_id)
    represented = 0
    large_represented = 0
    large_fractions: list[float] = []
    for group in members.values():
        covered = sum(1 for route_id in group if routes[route_id] & chosen)
        if covered:
            represented += 1
        if len(group) >= large_min_size:
            if covered:
                large_represented += 1
            large_fractions.append(covered / len(group))
    n_large = len(large_fractions)
    return {
        "n_communities": len(members),
        "n_represented": represented,
        "represented_fraction": represented / len(members) if members else 0.0,
        "n_large": n_large,
        "n_large_represented": large_represented,
        "large_represented_fraction": large_represented / n_large if n_large else 0.0,
        "large_member_coverage_mean": (sum(large_fractions) / n_large) if n_large else 0.0,
        "large_member_coverage_min": min(large_fractions) if large_fractions else 0.0,
    }


def status_coverage(
    routes: Mapping[RouteId, set[str]],
    assignments: Sequence[Mapping[str, object]],
    selected: Sequence[str],
) -> dict[str, float | int]:
    """Unweighted coverage inside each held-out assignment status.

    Assigned, ambiguous, and unassigned routes are all retained. A missing
    status contributes a count of zero and a coverage of 0.
    """
    chosen = set(selected)
    grouped: dict[str, list[bool]] = {"assigned": [], "ambiguous": [], "unassigned": []}
    for row in assignments:
        status = str(row["status"])
        if status not in grouped:
            raise ValueError(f"unknown assignment status {status}")
        route_id = str(row["route_id"])
        grouped[status].append(bool(routes[route_id] & chosen))
    covered_all = sum(sum(flags) for flags in grouped.values())
    total = sum(len(flags) for flags in grouped.values())
    report: dict[str, float | int] = {
        "n_evaluation": total,
        "overall_coverage": covered_all / total if total else 0.0,
    }
    for status, flags in grouped.items():
        report[f"n_{status}"] = len(flags)
        report[f"{status}_coverage"] = (sum(flags) / len(flags)) if flags else 0.0
    return report
