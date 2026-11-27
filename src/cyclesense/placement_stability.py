"""Selection stability of simulated counter placements.

Frequencies describe how often the existing greedy rule picks a physical
segment when the calibration sample changes. They are not probabilities that
a street should receive a real counter, and the replicates share a design,
so pairwise overlaps are not independent observations.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import combinations

from cyclesense.placement import assert_selection

CANONICAL_OUTPUTS = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
    "outputs/robust_placement/summary.json",
    "outputs/exact_optimization/summary.json",
    "outputs/standout/summary.json",
    "data/external/trafiktal.csv",
)


def replicate_seeds(start: int, count: int) -> tuple[int, ...]:
    """Inclusive start and the next ``count`` distinct integers."""
    if count < 2:
        raise ValueError("stability needs at least two replicates")
    seeds = tuple(range(int(start), int(start) + int(count)))
    if len(set(seeds)) != count:
        raise ValueError("replicate seeds are not distinct")
    return seeds


def assert_disjoint_seed_blocks(*blocks: Sequence[int]) -> None:
    """Reject a seed that appears in two roles."""
    seen: dict[int, int] = {}
    for block in blocks:
        for seed in block:
            if seed in seen:
                raise ValueError(f"seed {seed} is used in more than one block")
            seen[int(seed)] = int(seed)


def assert_calibration_only(splits: Sequence[str]) -> None:
    """Placement inputs must not contain a held-out split."""
    if not splits:
        raise ValueError("a replicate has no routes")
    found = set(splits)
    if found != {"calibration"}:
        raise ValueError(f"placement saw a non-calibration split: {sorted(found)}")


def selection_frequencies(selections: Sequence[Sequence[str]], eligible_ids: Sequence[str]) -> dict[str, float]:
    """Share of replicates that contain each selected physical id.

    The denominator is the number of replicates. Segments that are never
    selected are omitted. Every id must be eligible, and each replicate must
    already contain distinct ids.
    """
    if not selections:
        raise ValueError("frequency needs at least one replicate")
    eligible = set(eligible_ids)
    counts: Counter[str] = Counter()
    width = None
    for selected in selections:
        ids = tuple(selected)
        if len(ids) != len(set(ids)):
            raise ValueError("a replicate repeats a physical segment")
        if not set(ids) <= eligible:
            raise ValueError("a replicate contains an ineligible segment")
        if width is None:
            width = len(ids)
        elif len(ids) != width:
            raise ValueError("replicates do not share a budget")
        counts.update(ids)
    total = len(selections)
    return {edge: counts[edge] / total for edge in sorted(counts)}


def frequency_counts(frequencies: Mapping[str, float], n_candidates: int) -> dict[str, int]:
    """How many segments fall into the stated frequency bands."""
    if n_candidates < len(frequencies):
        raise ValueError("more selected segments than candidates")
    values = list(frequencies.values())
    if any(value < 0 or value > 1 for value in values):
        raise ValueError("a selection frequency is outside 0 to 1")
    return {
        "n_candidates": n_candidates,
        "n_ever_selected": len(values),
        "n_never_selected": n_candidates - len(values),
        "n_always": sum(value == 1 for value in values),
        "n_at_least_80": sum(value >= 0.8 for value in values),
        "n_at_least_50": sum(value >= 0.5 for value in values),
    }


def pairwise_overlaps(selections: Sequence[Sequence[str]]) -> list[dict[str, float | int]]:
    """Shared ids and Jaccard similarity for every replicate pair.

    Pairs overlap in the replicates, so these rows are not an independent
    sample. Percentiles below are descriptive.
    """
    rows = []
    sets = [set(selected) for selected in selections]
    for left, right in combinations(range(len(sets)), 2):
        shared = len(sets[left] & sets[right])
        union = len(sets[left] | sets[right])
        rows.append({
            "replicate_a": left,
            "replicate_b": right,
            "shared": shared,
            "union": union,
            "jaccard": shared / union if union else 1.0,
        })
    return rows


def overlap_summary(rows: Sequence[Mapping[str, float | int]]) -> dict[str, float]:
    """Mean, median, and empirical percentiles of pairwise Jaccard and overlap."""
    if not rows:
        raise ValueError("overlap summary needs at least one pair")
    jaccard = [float(row["jaccard"]) for row in rows]
    shared = [float(row["shared"]) for row in rows]
    return {
        "mean_jaccard": _mean(jaccard),
        "median_jaccard": _median(jaccard),
        "p05_jaccard": empirical_percentile(jaccard, 0.05),
        "p95_jaccard": empirical_percentile(jaccard, 0.95),
        "min_jaccard": min(jaccard),
        "max_jaccard": max(jaccard),
        "min_shared": min(shared),
        "max_shared": max(shared),
        "mean_shared": _mean(shared),
    }


def empirical_percentile(values: Sequence[float], probability: float) -> float:
    """Linear percentile. ``probability`` is between 0 and 1."""
    if not 0 <= probability <= 1:
        raise ValueError("percentile probability must be between 0 and 1")
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile of an empty sample")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def rank_summaries(orders: Sequence[Sequence[str]]) -> dict[str, dict[str, float]]:
    """Mean and sample standard deviation of 1-based selection rank.

    Rank is recorded only in replicates that selected the segment. A segment
    selected once has no standard deviation.
    """
    ranks: dict[str, list[int]] = {}
    for order in orders:
        for position, edge in enumerate(order, start=1):
            ranks.setdefault(edge, []).append(position)
    summary = {}
    for edge, values in ranks.items():
        summary[edge] = {
            "mean_rank": _mean(values),
            "rank_std": _sample_std(values),
            "times_first": sum(value == 1 for value in values),
        }
    return summary


def selection_entropy(frequencies: Mapping[str, float], budget: int) -> float:
    """Normalized entropy of the selection-slot distribution.

    Each replicate contributes ``budget`` slots, so ``frequency / budget``
    sums to 1 over the selected segments. The result is entropy divided by
    ``log(number of distinct selected segments)``. Zero means one segment
    pattern; one means the selected segments share the slots equally.
    """
    if budget < 1:
        raise ValueError("entropy needs a positive budget")
    positive = [float(value) / budget for value in frequencies.values() if value > 0]
    if not positive:
        raise ValueError("entropy needs a selected segment")
    total = sum(positive)
    if abs(total - 1.0) > 1e-6:
        raise ValueError(f"selection frequencies sum to {total * budget}, not the budget")
    if len(positive) == 1:
        return 0.0
    entropy = -sum(value * math.log(value) for value in positive)
    return entropy / math.log(len(positive))


def sample_dispersion(values: Sequence[float]) -> dict[str, float]:
    """Mean, sample standard deviation, minimum, and maximum."""
    if not values:
        raise ValueError("dispersion needs at least one value")
    return {
        "mean": _mean(values),
        "std": _sample_std(values),
        "min": min(values),
        "max": max(values),
    }


def descriptive_correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation. Pairs of replicates are not independent."""
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = _mean(xs)
    mean_y = _mean(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    scale_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    scale_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if scale_x == 0 or scale_y == 0:
        return None
    return covariance / (scale_x * scale_y)


def jaccard(left: Sequence[str], right: Sequence[str]) -> float:
    """Jaccard similarity of two id sets. Two empty sets have similarity 1."""
    first, second = set(left), set(right)
    union = first | second
    if not union:
        return 1.0
    return len(first & second) / len(union)


def require_saved_selection(selected: Sequence[str], eligible_ids: Sequence[str], budget: int) -> None:
    """The saved canonical placement must itself be a valid K-set."""
    assert_selection(tuple(selected), eligible_ids, budget)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[midpoint])
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _sample_std(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    center = _mean(values)
    return math.sqrt(sum((value - center) ** 2 for value in values) / (len(values) - 1))
