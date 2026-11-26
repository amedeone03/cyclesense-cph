"""Scalability measurements for streaming exact and verified LSH pipelines.

Route generation stays outside the timed section. Timing repeats do not
include tracemalloc. A row with status other than ``measured`` is a limit
or a skipped configuration, not an observed runtime or memory peak.
"""

from __future__ import annotations

import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import networkx as nx

from cyclesense.balanced import community_weights, represented_communities
from cyclesense.communities import detect_communities, graph_statistics, similarity_graph
from cyclesense.integrated import (
    adjusted_rand_index,
    check_banding,
    compare_similarity_graphs,
    streaming_exact_graph,
    verified_lsh_graph,
)
from cyclesense.minhash import build_lsh_buckets, build_signatures, verify_candidates
from cyclesense.placement import score_split, select_greedy
from cyclesense.similarity import jaccard_similarity

OUTPUT_DIRNAME = "outputs/scalability"
PROTECTED_OUTPUTS = (
    "outputs/m2",
    "outputs/m3",
    "outputs/m4",
    "outputs/m5",
    "outputs/integrated",
    "outputs/route_choice",
    "outputs/standout",
    "data/processed/m1",
    "data/external",
)


class ResourceLimit(RuntimeError):
    """A configuration was stopped before it could report a complete result."""

    def __init__(self, reason: str, **observed: object) -> None:
        super().__init__(reason)
        self.reason = reason
        self.observed = observed


@dataclass(frozen=True)
class RepeatSummary:
    values: tuple[float, ...]
    median: float
    minimum: float
    maximum: float
    stdev: float | None
    stopped_early: bool


def summarize_times(values: Sequence[float], *, stopped_early: bool = False) -> RepeatSummary:
    """Median, extremes, and sample standard deviation of completed repeats."""
    if not values:
        raise ValueError("timing summary needs at least one completed repeat")
    ordered = tuple(float(value) for value in values)
    return RepeatSummary(
        values=ordered,
        median=float(statistics.median(ordered)),
        minimum=min(ordered),
        maximum=max(ordered),
        stdev=float(statistics.stdev(ordered)) if len(ordered) > 1 else None,
        stopped_early=stopped_early,
    )


def candidate_statistics(n_candidates: int, n_routes: int) -> dict[str, float | int]:
    """Candidate count relative to the complete undirected pair set."""
    if n_routes < 0 or n_candidates < 0:
        raise ValueError("counts must be non-negative")
    possible = n_routes * (n_routes - 1) // 2
    fraction = (n_candidates / possible) if possible else 0.0
    return {
        "n_candidates": n_candidates,
        "n_possible_pairs": possible,
        "candidate_fraction": fraction,
        "candidate_reduction": 1.0 - fraction,
    }


def dataset_diagnostics(routes: Sequence[Any], *, generation_seconds: float, requested: int) -> dict[str, float | int]:
    """Diversity of one nested prefix. Identical physical sets are duplicates."""
    physical = [tuple(route.physical_edge_ids) for route in routes]
    unique_sets = set(physical)
    lengths = [len(edges) for edges in physical]
    segments: set[str] = set()
    for edges in physical:
        segments.update(edges)
    count = len(routes)
    return {
        "n_routes": count,
        "n_requested": requested,
        "n_unique_physical_sets": len(unique_sets),
        "duplicate_fraction": (1.0 - len(unique_sets) / count) if count else 0.0,
        "mean_segments": (sum(lengths) / count) if count else 0.0,
        "median_segments": float(statistics.median(lengths)) if lengths else 0.0,
        "n_unique_segments": len(segments),
        "generation_seconds": generation_seconds,
    }


def nested_prefixes(routes: Sequence[Any], sizes: Sequence[int]) -> list[list[Any]]:
    """Increasing prefixes of one generated list."""
    if list(sizes) != sorted(sizes) or len(set(sizes)) != len(sizes):
        raise ValueError("benchmark sizes must be strictly increasing")
    if any(size < 1 for size in sizes):
        raise ValueError("benchmark sizes must be positive")
    if sizes and sizes[-1] > len(routes):
        raise ValueError(f"collection has {len(routes)} routes, short of {sizes[-1]}")
    prefixes = [list(routes[:size]) for size in sizes]
    for earlier, later in pairwise(prefixes):
        if [route.route_id for route in later[: len(earlier)]] != [route.route_id for route in earlier]:
            raise ValueError("prefixes are not nested")
    return prefixes


def assert_physical_ids(routes: Sequence[Any], known_ids: set[str]) -> None:
    """Every stored physical segment must already exist on the routing graph."""
    for route in routes:
        unknown = [edge_id for edge_id in route.physical_edge_ids if edge_id not in known_ids]
        if unknown:
            raise ValueError(f"{route.route_id} uses an unknown physical edge")
        if not route.physical_edge_ids:
            raise ValueError(f"{route.route_id} has no physical edges")


def assert_no_evaluation_leakage(graph_ids: set[str], evaluation_ids: set[str]) -> None:
    """Held-out routes stay out of the similarity graph and the placement sample."""
    shared = graph_ids & evaluation_ids
    if shared:
        raise ValueError(f"{len(shared)} evaluation routes are also graph nodes")


def assert_selection(selected: Sequence[str], eligible_ids: set[str], k: int) -> None:
    """Exactly K distinct eligible counter ids."""
    if len(selected) != k or len(set(selected)) != k:
        raise ValueError(f"selection has {len(set(selected))} distinct ids, not {k}")
    if not set(selected) <= eligible_ids:
        raise ValueError("selection contains an edge that is not an eligible candidate")


def measured(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Drop limits and skipped rows so a figure cannot plot an unmeasured value."""
    return [row for row in rows if row.get("status") == "measured"]


def query_lsh_pairs_bounded(
    signatures: Sequence[Sequence[int]],
    buckets: Mapping[tuple[int, tuple[int, ...]], Sequence[int]],
    bands: int,
    rows: int,
    *,
    max_pairs: int,
    max_bucket_size: int,
) -> set[tuple[int, int]]:
    """Unique candidate pairs, stopping when a bucket or the pair set is too large."""
    if max_pairs < 1 or max_bucket_size < 1:
        raise ValueError("candidate limits must be positive")
    largest = max((len(members) for members in buckets.values()), default=0)
    if largest > max_bucket_size:
        raise ResourceLimit(
            "largest LSH bucket exceeds the pre-specified cap",
            largest_bucket=largest,
            max_bucket_size=max_bucket_size,
        )
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
            if pair not in pairs:
                pairs.add(pair)
                if len(pairs) > max_pairs:
                    raise ResourceLimit(
                        "candidate-pair cap reached before the query finished",
                        max_candidate_pairs=max_pairs,
                        largest_bucket=largest,
                    )
    return pairs


def bucket_statistics(
    buckets: Mapping[tuple[int, tuple[int, ...]], Sequence[int]],
) -> dict[str, int]:
    """Bucket count, stored entries, and the largest bucket."""
    sizes = [len(members) for members in buckets.values()]
    return {
        "n_buckets": len(sizes),
        "n_bucket_entries": sum(sizes),
        "largest_bucket": max(sizes) if sizes else 0,
    }


def graph_structure(graph: nx.Graph) -> dict[str, float | int]:
    """Connectivity beyond the shared graph summary."""
    base = graph_statistics(graph)
    nodes = graph.number_of_nodes()
    components = list(nx.connected_components(graph)) if nodes else []
    largest = max((len(component) for component in components), default=0)
    isolates = int(base["n_isolates"])
    return {
        **base,
        "average_degree": (2 * int(base["n_edges"]) / nodes) if nodes else 0.0,
        "largest_component": largest,
        "isolate_fraction": (isolates / nodes) if nodes else 0.0,
        "n_components": len(components),
    }


def community_structure(labels: Mapping[str, int], sizes: Sequence[int]) -> dict[str, float | int]:
    """Community counts for one Louvain partition."""
    ordered = sorted(int(size) for size in sizes)
    return {
        "n_communities": len(ordered),
        "n_singletons": sum(1 for size in ordered if size == 1),
        "largest_community": max(ordered) if ordered else 0,
        "median_community_size": float(statistics.median(ordered)) if ordered else 0.0,
        "n_labeled": len(labels),
    }


def subset_indexes(n_routes: int, subset_size: int, seed: int) -> tuple[int, ...]:
    """A fixed sample of route positions. This is not a full-dataset recall set."""
    if subset_size < 2 or subset_size > n_routes:
        raise ValueError("subset size must sit inside the route collection")
    generator = random.Random(seed)
    return tuple(sorted(generator.sample(range(n_routes), subset_size)))


def subset_edge_recall(
    graph: nx.Graph,
    route_ids: Sequence[str],
    physical: Mapping[str, set[str]],
    indexes: Sequence[int],
    threshold: float,
) -> dict[str, float | int]:
    """Exact recall among one route subset, using edges already kept by LSH.

    Pairs outside the subset are ignored. The result is not full-dataset recall.
    """
    chosen = [route_ids[index] for index in indexes]
    sets = [physical[route_id] for route_id in chosen]
    truth: set[tuple[str, str]] = set()
    for left in range(len(chosen)):
        for right in range(left + 1, len(chosen)):
            if jaccard_similarity(sets[left], sets[right]) >= threshold:
                pair = tuple(sorted((chosen[left], chosen[right])))
                truth.add(pair)
    retained = {
        tuple(sorted((left, right)))
        for left, right in graph.edges
        if left in chosen and right in chosen
    }
    invented = retained - truth
    if invented:
        raise ValueError("subset contains an LSH edge that is not an exact match")
    matched = len(retained & truth)
    return {
        "subset_n": len(chosen),
        "subset_true_pairs": len(truth),
        "subset_retained_pairs": matched,
        "subset_recall": (matched / len(truth)) if truth else None,
        "subset_only": 1,
    }


def placement_record(
    selected: Sequence[str],
    labels: Mapping[str, int],
    eligible_routes: Mapping[str, set[str]],
    heldout_routes: Mapping[str, set[str]],
    *,
    reference_labels: Mapping[str, int] | None = None,
    reference_selected: Sequence[str] | None = None,
) -> dict[str, float | int | None]:
    """Calibration coverage, optional held-out coverage, and exact-partition representation."""
    record: dict[str, float | int | None] = {
        "n_selected": len(selected),
        "calibration_coverage": score_split(eligible_routes, selected),
        "heldout_coverage": score_split(heldout_routes, selected) if heldout_routes else None,
    }
    labels_for_representation = reference_labels if reference_labels is not None else labels
    representation = represented_communities(eligible_routes, labels_for_representation, selected)
    record["large_represented_fraction"] = float(representation["large_represented_fraction"])
    if reference_selected is not None:
        shared = set(selected) & set(reference_selected)
        union = set(selected) | set(reference_selected)
        record["n_shared_with_exact"] = len(shared)
        record["selected_jaccard_vs_exact"] = (len(shared) / len(union)) if union else 1.0
    return record


def run_streaming(physical: Mapping[str, set[str]], threshold: float) -> nx.Graph:
    """Exact thresholded graph with no stored below-threshold pairs."""
    return streaming_exact_graph(physical, threshold)


def run_verified_lsh(
    physical: Mapping[str, set[str]],
    *,
    num_perm: int,
    bands: int,
    rows: int,
    threshold: float,
    seed: int,
    max_pairs: int,
    max_bucket_size: int,
) -> tuple[nx.Graph, set[tuple[int, int]], set[tuple[int, int]]]:
    """Verified LSH graph, or a resource-limit error before a partial graph is kept.

    The public verified pipeline is used when the bucket screen passes. The
    screen uses the same signatures and buckets, then the existing pipeline
    builds the graph whose weights are exact Jaccard values.
    """
    check_banding(num_perm, bands, rows)
    usable = sorted(route_id for route_id, edges in physical.items() if edges)
    route_sets = [set(physical[route_id]) for route_id in usable]
    signatures = build_signatures(route_sets, num_perm, seed)
    buckets = build_lsh_buckets(signatures, bands, rows)
    query_lsh_pairs_bounded(
        signatures,
        buckets,
        bands,
        rows,
        max_pairs=max_pairs,
        max_bucket_size=max_bucket_size,
    )
    graph, candidates, verified = verified_lsh_graph(
        physical,
        num_perm=num_perm,
        bands=bands,
        rows=rows,
        threshold=threshold,
        seed=seed,
    )
    for left, right, data in graph.edges(data=True):
        if float(data["weight"]) < threshold:
            raise RuntimeError(f"graph kept a below-threshold edge {left}--{right}")
    if any(left >= right for left, right in candidates):
        raise RuntimeError("candidate pairs are not ordered index pairs")
    return graph, candidates, verified


def finish_placement(
    graph: nx.Graph,
    eligible_ids: Sequence[str],
    eligible_routes: Mapping[str, set[str]],
    *,
    louvain_seed: int,
    lam: float,
    k: int,
) -> tuple[dict[str, int], tuple[str, ...], list[int]]:
    """Louvain and weighted greedy. The graph is not rebuilt."""
    labels, _modularity, sizes = detect_communities(graph, louvain_seed)
    weights, _info = community_weights(labels, lam)
    selected = select_greedy(eligible_ids, eligible_routes, k, weights)
    assert_selection(selected, set(eligible_ids), k)
    return labels, selected, sizes


def exact_agreement(
    exact: nx.Graph,
    approximate: nx.Graph,
    exact_labels: Mapping[str, int],
    approximate_labels: Mapping[str, int],
) -> dict[str, float | int | None]:
    """Full-graph recall and partition agreement. Requires a completed exact graph."""
    comparison = compare_similarity_graphs(exact, approximate)
    return {
        "full_exact_available": 1,
        "subset_only": 0,
        "n_true_pairs": comparison["n_exact_edges"],
        "n_retained_pairs": comparison["n_edges_retained"],
        "n_false_negatives": comparison["n_edges_missed"],
        "graph_edge_recall": comparison["graph_edge_recall"],
        "adjusted_rand_index": adjusted_rand_index(exact_labels, approximate_labels),
    }


def lsh_stage_profile(
    physical: Mapping[str, set[str]],
    eligible_routes: Mapping[str, set[str]],
    eligible_ids: Sequence[str],
    *,
    num_perm: int,
    bands: int,
    rows: int,
    threshold: float,
    seed: int,
    louvain_seed: int,
    lam: float,
    k: int,
    max_pairs: int,
    max_bucket_size: int,
) -> dict[str, float | int]:
    """One untimed-as-a-repeat pass that splits signature, query, verify, and placement."""
    import time

    usable = sorted(route_id for route_id, edges in physical.items() if edges)
    route_sets = [set(physical[route_id]) for route_id in usable]
    started = time.perf_counter()
    signatures = build_signatures(route_sets, num_perm, seed)
    signature_s = time.perf_counter() - started
    started = time.perf_counter()
    buckets = build_lsh_buckets(signatures, bands, rows)
    bucket_s = time.perf_counter() - started
    counts = bucket_statistics(buckets)
    started = time.perf_counter()
    candidates = query_lsh_pairs_bounded(
        signatures,
        buckets,
        bands,
        rows,
        max_pairs=max_pairs,
        max_bucket_size=max_bucket_size,
    )
    query_s = time.perf_counter() - started
    started = time.perf_counter()
    verified = verify_candidates(candidates, route_sets, threshold)
    verify_s = time.perf_counter() - started

    def build_graph() -> nx.Graph:
        weighted = []
        for left, right in verified:
            similarity = jaccard_similarity(route_sets[left], route_sets[right])
            weighted.append((usable[left], usable[right], similarity))
        return similarity_graph(physical, weighted, threshold)

    started = time.perf_counter()
    graph = build_graph()
    graph_s = time.perf_counter() - started
    started = time.perf_counter()
    labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
    louvain_s = time.perf_counter() - started
    started = time.perf_counter()
    weights, _info = community_weights(labels, lam)
    weights_s = time.perf_counter() - started
    started = time.perf_counter()
    select_greedy(eligible_ids, eligible_routes, k, weights)
    greedy_s = time.perf_counter() - started
    fractions = candidate_statistics(len(candidates), len(usable))
    return {
        "signatures_s": signature_s,
        "buckets_s": bucket_s,
        "query_s": query_s,
        "verify_s": verify_s,
        "graph_s": graph_s,
        "louvain_s": louvain_s,
        "weights_s": weights_s,
        "greedy_s": greedy_s,
        "n_verified": len(verified),
        **counts,
        **fractions,
    }


def streaming_stage_profile(
    physical: Mapping[str, set[str]],
    eligible_routes: Mapping[str, set[str]],
    eligible_ids: Sequence[str],
    *,
    threshold: float,
    louvain_seed: int,
    lam: float,
    k: int,
) -> dict[str, float]:
    """One additional streaming pass split into Jaccard, Louvain, weights, and greedy."""
    import time

    started = time.perf_counter()
    graph = streaming_exact_graph(physical, threshold)
    jaccard_s = time.perf_counter() - started
    started = time.perf_counter()
    labels, _modularity, _sizes = detect_communities(graph, louvain_seed)
    louvain_s = time.perf_counter() - started
    started = time.perf_counter()
    weights, _info = community_weights(labels, lam)
    weights_s = time.perf_counter() - started
    started = time.perf_counter()
    select_greedy(eligible_ids, eligible_routes, k, weights)
    greedy_s = time.perf_counter() - started
    return {
        "jaccard_s": jaccard_s,
        "louvain_s": louvain_s,
        "weights_s": weights_s,
        "greedy_s": greedy_s,
    }


def allow_streaming_extension(previous: Mapping[str, Any], settings: Mapping[str, Any]) -> bool:
    """Whether a measured smaller streaming run justifies one larger exact run."""
    if previous.get("status") != "measured":
        return False
    if previous.get("median_seconds") is None or previous.get("n_edges") is None:
        return False
    return float(previous["median_seconds"]) < float(settings["streaming_extend_if_median_seconds_below"]) and int(
        previous["n_edges"]
    ) < int(settings["streaming_extend_if_edges_below"])
