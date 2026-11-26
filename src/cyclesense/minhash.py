"""Reproducible MinHash signatures and banded locality-sensitive hashing.

Signatures use one fixed family of 64-bit hash functions for a seed. A
candidate pair shares at least one band. Exact Jaccard, not the signature
estimate, decides whether a candidate is truly similar.
"""

import hashlib
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence

from cyclesense.similarity import jaccard_similarity

_MASK = (1 << 64) - 1

# Signature length -> (bands, rows per band). Each product equals the length.
BANDINGS: dict[int, tuple[tuple[int, int], ...]] = {
    32: ((16, 2), (8, 4), (4, 8)),
    64: ((32, 2), (16, 4), (8, 8)),
    128: ((64, 2), (32, 4), (16, 8), (8, 16)),
}


def minhash_coefficients(num_perm: int, seed: int) -> tuple[tuple[int, int], ...]:
    """Odd multipliers and offsets for ``num_perm`` MinHash rows."""
    if num_perm < 1:
        raise ValueError("num_perm must be positive")
    generator = random.Random(seed)
    coefficients = []
    for _ in range(num_perm):
        multiplier = generator.randrange(0, 2**32) * 2 + 1
        offset = generator.randrange(0, 2**32)
        coefficients.append((multiplier, offset))
    return tuple(coefficients)


def _item_hash(item: str) -> int:
    digest = hashlib.blake2s(item.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def minhash_signature(
    items: Iterable[str],
    coefficients: Sequence[tuple[int, int]],
    *,
    cache: dict[str, int] | None = None,
) -> tuple[int, ...]:
    """MinHash signature of one non-empty route edge set."""
    hashed: list[int] = []
    for item in set(items):
        if cache is not None and item in cache:
            hashed.append(cache[item])
            continue
        value = _item_hash(item)
        if cache is not None:
            cache[item] = value
        hashed.append(value)
    if not hashed:
        raise ValueError("MinHash requires a non-empty route")
    signature = []
    for multiplier, offset in coefficients:
        signature.append(min((multiplier * value + offset) & _MASK for value in hashed))
    return tuple(signature)


def build_signatures(
    route_sets: Sequence[Iterable[str]],
    num_perm: int,
    seed: int,
) -> list[tuple[int, ...]]:
    """Signatures in the same order as ``route_sets``."""
    coefficients = minhash_coefficients(num_perm, seed)
    cache: dict[str, int] = {}
    return [minhash_signature(items, coefficients, cache=cache) for items in route_sets]


def signature_jaccard(left: Sequence[int], right: Sequence[int]) -> float:
    """Fraction of equal MinHash rows. This is an estimate, not exact Jaccard."""
    if len(left) != len(right) or not left:
        raise ValueError("signatures must be non-empty and the same length")
    return sum(item == other for item, other in zip(left, right, strict=True)) / len(left)


def build_lsh_buckets(
    signatures: Sequence[Sequence[int]],
    bands: int,
    rows: int,
) -> dict[tuple[int, tuple[int, ...]], list[int]]:
    """Map each band key to the route indexes that share it."""
    _check_banding(signatures, bands, rows)
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = defaultdict(list)
    for index, signature in enumerate(signatures):
        for band in range(bands):
            start = band * rows
            key = (band, tuple(signature[start : start + rows]))
            buckets[key].append(index)
    return buckets


def query_lsh_pairs(
    signatures: Sequence[Sequence[int]],
    buckets: Mapping[tuple[int, tuple[int, ...]], Sequence[int]],
    bands: int,
    rows: int,
) -> set[tuple[int, int]]:
    """Candidate index pairs. Querying probes an index that was already built."""
    _check_banding(signatures, bands, rows)
    pairs: set[tuple[int, int]] = set()
    for index, signature in enumerate(signatures):
        found: list[int] = []
        for band in range(bands):
            start = band * rows
            key = (band, tuple(signature[start : start + rows]))
            found.extend(buckets.get(key, ()))
        for other in found:
            if other == index:
                continue
            pair = (index, other) if index < other else (other, index)
            pairs.add(pair)
    return pairs


def retrieval_metrics(
    candidates: set[tuple[int, int]],
    exact: Mapping[tuple[int, int], float],
    threshold: float,
    n_routes: int,
) -> dict[str, float | int | None]:
    """Recall and precision of LSH candidates against exact pairs at ``threshold``."""
    truth = {pair for pair, similarity in exact.items() if similarity >= threshold}
    matched = len(truth & candidates)
    n_possible = n_routes * (n_routes - 1) // 2
    recall = matched / len(truth) if truth else None
    precision = matched / len(candidates) if candidates else None
    return {
        "n_true_pairs": len(truth),
        "n_candidates": len(candidates),
        "n_possible_pairs": n_possible,
        "recall": recall,
        "precision": precision,
        "candidate_fraction": (len(candidates) / n_possible) if n_possible else 0.0,
        "candidate_reduction": (1 - len(candidates) / n_possible) if n_possible else 0.0,
    }


def verify_candidates(
    candidates: set[tuple[int, int]],
    route_sets: Sequence[set[str]],
    threshold: float,
) -> set[tuple[int, int]]:
    """Keep candidates whose exact Jaccard meets ``threshold``."""
    kept: set[tuple[int, int]] = set()
    for left, right in candidates:
        if jaccard_similarity(route_sets[left], route_sets[right]) >= threshold:
            kept.add((left, right))
    return kept


def choose_operating_point(
    records: Sequence[Mapping[str, object]],
    *,
    threshold: float = 0.5,
    minimum_recall: float = 0.95,
) -> Mapping[str, object]:
    """Pick a banding from calibration retrieval records.

    Prefer recall of at least ``minimum_recall`` and then the smallest
    candidate set. This uses the exact calibration reference, not held-out
    routes, and it does not change the Louvain graph.
    """
    at_threshold = [
        record
        for record in records
        if float(record["threshold"]) == threshold and record.get("recall") is not None
    ]
    if not at_threshold:
        raise ValueError("no LSH records at the requested threshold")
    eligible = [record for record in at_threshold if float(record["recall"]) >= minimum_recall]
    if eligible:
        return min(eligible, key=lambda record: (int(record["n_candidates"]), int(record["num_perm"]), int(record["bands"])))
    return min(
        at_threshold,
        key=lambda record: (
            -float(record["recall"]),
            int(record["n_candidates"]),
            int(record["num_perm"]),
            int(record["bands"]),
        ),
    )


def _check_banding(signatures: Sequence[Sequence[int]], bands: int, rows: int) -> None:
    if bands < 1 or rows < 1:
        raise ValueError("bands and rows must be positive")
    if not signatures:
        raise ValueError("signatures are empty")
    width = len(signatures[0])
    if bands * rows != width:
        raise ValueError(f"{bands} bands of {rows} rows do not cover {width} permutations")
    if any(len(signature) != width for signature in signatures):
        raise ValueError("signatures have different lengths")
