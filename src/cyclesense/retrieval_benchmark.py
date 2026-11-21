"""End-to-end exact Jaccard and verified MinHash/LSH retrieval.

Both functions return the pairs whose exact Jaccard meets the threshold.
Route generation is not included. The LSH banding is an argument, so a caller
can freeze the operating point chosen on the calibration routes.
"""

from collections.abc import Sequence

from cyclesense.minhash import (
    build_lsh_buckets,
    build_signatures,
    query_lsh_pairs,
    verify_candidates,
)
from cyclesense.similarity import jaccard_similarity


def exact_similar_pairs(
    route_sets: Sequence[set[str]],
    threshold: float,
) -> set[tuple[int, int]]:
    """Every index pair whose exact Jaccard is at least ``threshold``."""
    found: set[tuple[int, int]] = set()
    for left in range(len(route_sets)):
        left_set = route_sets[left]
        for right in range(left + 1, len(route_sets)):
            if jaccard_similarity(left_set, route_sets[right]) >= threshold:
                found.add((left, right))
    return found


def lsh_verified_pairs(
    route_sets: Sequence[set[str]],
    *,
    num_perm: int,
    bands: int,
    rows: int,
    threshold: float,
    seed: int,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Build signatures and an index, then return candidate and verified pairs.

    Verification uses exact Jaccard. The first set is the LSH candidate set.
    The second set is the subset that meets ``threshold``.
    """
    signatures = build_signatures(route_sets, num_perm, seed)
    buckets = build_lsh_buckets(signatures, bands, rows)
    candidates = query_lsh_pairs(signatures, buckets, bands, rows)
    verified = verify_candidates(candidates, route_sets, threshold)
    return candidates, verified
