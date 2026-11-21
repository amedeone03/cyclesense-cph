"""Sample summaries for the M5 shuffle and evaluation checks.

These are descriptions of a finite set of simulated draws. They are not
hypothesis tests and they do not use held-out routes to choose a method.
"""

from collections.abc import Sequence
from statistics import mean, quantiles, stdev


def sample_summary(values: Sequence[float]) -> dict[str, float | int]:
    """Mean, sample standard deviation, and inclusive percentiles.

    Percentiles use ``statistics.quantiles`` with 100 bins and the inclusive
    method. ``p05`` is the fifth of those cut points. The standard deviation
    is the sample standard deviation with divisor ``n - 1``.
    """
    if len(values) < 2:
        raise ValueError("a sample summary needs at least two values")
    ordered = sorted(float(value) for value in values)
    cuts = quantiles(ordered, n=100, method="inclusive")
    return {
        "n": len(ordered),
        "mean": mean(ordered),
        "std": stdev(ordered),
        "min": ordered[0],
        "max": ordered[-1],
        "p05": cuts[4],
        "p25": cuts[24],
        "p50": cuts[49],
        "p75": cuts[74],
        "p95": cuts[94],
    }


def paired_differences(baseline: Sequence[float], other: Sequence[float]) -> list[float]:
    """Difference ``other - baseline`` on samples that share an index."""
    if len(baseline) != len(other):
        raise ValueError("paired comparisons require the same number of samples")
    if not baseline:
        raise ValueError("paired comparisons need at least one sample")
    return [float(right) - float(left) for left, right in zip(baseline, other, strict=True)]


def outside_central_90(value: float, summary: dict[str, float | int]) -> bool:
    """True when ``value`` falls outside the samples' 5th to 95th percentiles.

    This is a description of the observed shuffle draws. It is not a p-value.
    """
    return float(value) < float(summary["p05"]) or float(value) > float(summary["p95"])
