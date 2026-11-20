"""Exact similarity baseline; MinHash + LSH will be implemented and tested later."""

from typing import Hashable, Iterable


def jaccard_similarity(a: Iterable[Hashable], b: Iterable[Hashable]) -> float:
    """Jaccard overlap of two sets of physical cycling-network edge IDs.

    Empty/empty overlap is defined as 1.0 for this helper; empty routes should
    be excluded from the real route-similarity experiment.
    """
    left, right = set(a), set(b)
    union = left | right
    return len(left & right) / len(union) if union else 1.0
