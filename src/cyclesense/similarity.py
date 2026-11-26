"""Exact Jaccard similarity of route edge sets.

MinHash and the route-similarity graph call this function for every compared
pair. Empty/empty overlap stays 1.0 here; experiment code drops empty routes
before pairing them.
"""

from collections.abc import Hashable, Iterable, Mapping, Sequence
from itertools import combinations


def jaccard_similarity(a: Iterable[Hashable], b: Iterable[Hashable]) -> float:
    """Jaccard overlap of two sets of physical cycling-network edge IDs.

    Empty/empty overlap is defined as 1.0 for this helper; empty routes should
    be excluded from the real route-similarity experiment.
    """
    left, right = set(a), set(b)
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def pairwise_jaccard(
    routes: Mapping[str, Iterable[Hashable]],
) -> tuple[tuple[str, str, float], ...]:
    """Upper-triangle Jaccard values, with route ids in sorted order.

    Empty routes are omitted. Each remaining route is paired once.
    """
    usable = sorted(route_id for route_id, edges in routes.items() if set(edges))
    sets = {route_id: set(routes[route_id]) for route_id in usable}
    pairs: list[tuple[str, str, float]] = []
    for left_id, right_id in combinations(usable, 2):
        pairs.append((left_id, right_id, jaccard_similarity(sets[left_id], sets[right_id])))
    return tuple(pairs)


def similarity_distribution(
    pairs: Sequence[tuple[str, str, float]],
    *,
    bin_width: float = 0.05,
    thresholds: Sequence[float] = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9),
) -> dict[str, object]:
    """Bin every pair, including zeros, and count pairs at or above each threshold."""
    if bin_width <= 0 or bin_width > 1:
        raise ValueError("bin_width must be in (0, 1]")
    n_bins = round(1 / bin_width)
    if abs(n_bins * bin_width - 1) > 1e-9:
        raise ValueError("bin_width must divide 1")
    counts = [0 for _ in range(n_bins)]
    values = [sim for _left, _right, sim in pairs]
    for sim in values:
        if sim < 0 or sim > 1:
            raise ValueError(f"Jaccard value outside [0, 1]: {sim}")
        index = n_bins - 1 if sim == 1 else int(sim / bin_width)
        counts[index] += 1
    ordered = sorted(values)
    return {
        "n_pairs": len(values),
        "n_zero": sum(1 for sim in values if sim == 0),
        "mean": (sum(values) / len(values)) if values else 0.0,
        "p50": _percentile(ordered, 0.50),
        "p90": _percentile(ordered, 0.90),
        "p99": _percentile(ordered, 0.99),
        "bin_width": bin_width,
        "bin_counts": counts,
        "threshold_counts": {float(threshold): sum(1 for sim in values if sim >= threshold) for threshold in thresholds},
    }


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    if not ordered:
        return 0.0
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight
