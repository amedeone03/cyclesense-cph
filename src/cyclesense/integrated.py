"""Exact and verified-LSH routes from similarity through balanced placement.

Pair retrieval is the only approximate step. An accepted graph edge carries
the exact Jaccard of the two calibration routes. Held-out routes are not
nodes of either graph. Coverage is a share of simulated routes.
"""

from __future__ import annotations

import math
import time
import tracemalloc
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from itertools import combinations

import networkx as nx

from cyclesense.balanced import community_weights
from cyclesense.communities import graph_statistics, similarity_graph
from cyclesense.minhash import BANDINGS
from cyclesense.placement import select_greedy
from cyclesense.retrieval_benchmark import lsh_verified_pairs
from cyclesense.similarity import jaccard_similarity, pairwise_jaccard

RouteSets = Mapping[str, set[str]]

CANONICAL_ARTIFACTS = (
    "data/processed/m1/routes.csv",
    "data/processed/m1/candidates.csv",
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m2/summary.json",
    "outputs/m3/summary.json",
    "outputs/m3/communities.csv",
    "outputs/m4/summary.json",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
)
OUTPUT_DIRNAME = "outputs/integrated"


def tracked_call(function: Callable, *args):
    """Run ``function`` and return its value, seconds, and peak Python-tracked MB.

    The peak is ``tracemalloc`` memory, not the operating-system process size.
    """
    tracemalloc.start()
    started = time.perf_counter()
    try:
        value = function(*args)
        elapsed = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return value, elapsed, peak / (1024 * 1024)


def adjusted_rand_index(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    """Hubert–Arabie adjusted Rand index. Community ids are arbitrary labels."""
    ids = sorted(set(left) & set(right))
    if set(left) != set(right):
        raise ValueError("partitions do not cover the same routes")
    if len(ids) < 2:
        return 1.0
    table = Counter((left[route_id], right[route_id]) for route_id in ids)
    row_sums = Counter(left[route_id] for route_id in ids)
    column_sums = Counter(right[route_id] for route_id in ids)
    sum_cells = sum(_choose_two(count) for count in table.values())
    sum_rows = sum(_choose_two(count) for count in row_sums.values())
    sum_columns = sum(_choose_two(count) for count in column_sums.values())
    total = _choose_two(len(ids))
    expected = (sum_rows * sum_columns / total) if total else 0.0
    maximum = 0.5 * (sum_rows + sum_columns)
    denominator = maximum - expected
    if denominator == 0.0:
        return 1.0
    return (sum_cells - expected) / denominator


def normalized_mutual_information(left: Mapping[str, int], right: Mapping[str, int]) -> float:
    """Arithmetic-mean normalized mutual information. Labels are arbitrary."""
    ids = sorted(set(left) & set(right))
    if set(left) != set(right):
        raise ValueError("partitions do not cover the same routes")
    count = len(ids)
    if count < 2:
        return 1.0
    table = Counter((left[route_id], right[route_id]) for route_id in ids)
    row_sums = Counter(left[route_id] for route_id in ids)
    column_sums = Counter(right[route_id] for route_id in ids)
    mutual = 0.0
    for (row_label, column_label), observed in table.items():
        mutual += (observed / count) * math.log(
            (observed * count) / (row_sums[row_label] * column_sums[column_label])
        )
    entropy_left = _entropy(row_sums, count)
    entropy_right = _entropy(column_sums, count)
    if entropy_left + entropy_right == 0.0:
        return 1.0
    return 2.0 * mutual / (entropy_left + entropy_right)


def check_banding(num_perm: int, bands: int, rows: int) -> None:
    """Reject a banding that is not one of the implemented MinHash layouts."""
    allowed = BANDINGS.get(num_perm, ())
    if (bands, rows) not in allowed:
        raise ValueError(f"{num_perm} permutations have no {bands}x{rows} banding")


def exact_similarity_graph(
    routes: RouteSets,
    threshold: float,
) -> tuple[nx.Graph, tuple[tuple[str, str, float], ...]]:
    """All-pairs Jaccard graph. Every calibration route remains a node.

    The returned pair tuple keeps every comparison, including pairs below
    ``threshold``. ``streaming_exact_graph`` is the separate baseline that
    does not retain that list.
    """
    pairs = pairwise_jaccard(routes)
    return similarity_graph(routes, pairs, threshold), pairs


def streaming_exact_graph(routes: RouteSets, threshold: float) -> nx.Graph:
    """Exact Jaccard graph that stores only pairs at or above ``threshold``.

    Each comparison is discarded as soon as it falls below the threshold.
    No complete pairwise list is built. Every route remains a node, including
    routes with no qualifying neighbor. Edge order matches the materialized
    exact graph, so Louvain sees the same weighted graph.
    """
    graph = nx.Graph()
    graph.add_nodes_from(routes)
    usable = sorted(route_id for route_id, edges in routes.items() if edges)
    sets = {route_id: set(routes[route_id]) for route_id in usable}
    for left_id, right_id in combinations(usable, 2):
        similarity = jaccard_similarity(sets[left_id], sets[right_id])
        if similarity < threshold:
            continue
        graph.add_edge(left_id, right_id, weight=float(similarity))
    return graph


def same_weighted_graph(left: nx.Graph, right: nx.Graph) -> bool:
    """Node order and undirected weighted edges, with exact stored weights."""
    if list(left.nodes) != list(right.nodes):
        return False

    def packed(graph: nx.Graph) -> list[tuple[str, str, float]]:
        rows = []
        for first, second, data in graph.edges(data=True):
            left_id, right_id = (first, second) if first <= second else (second, first)
            rows.append((left_id, right_id, float(data["weight"])))
        return sorted(rows)

    return packed(left) == packed(right)


def elapsed_call(function: Callable, *args):
    """Seconds for one call, without tracemalloc.

    Timing runs use this. Peak-memory runs use ``tracked_call`` and are not
    reported as runtimes.
    """
    started = time.perf_counter()
    value = function(*args)
    return value, time.perf_counter() - started


def verified_lsh_graph(
    routes: RouteSets,
    *,
    num_perm: int,
    bands: int,
    rows: int,
    threshold: float,
    seed: int,
) -> tuple[nx.Graph, set[tuple[int, int]], set[tuple[int, int]]]:
    """LSH candidates, exact verification, then the thresholded graph.

    Empty routes are nodes and are not signed. A kept edge weight is the
    exact Jaccard, recomputed after verification.
    """
    check_banding(num_perm, bands, rows)
    usable = sorted(route_id for route_id, edges in routes.items() if edges)
    route_sets = [set(routes[route_id]) for route_id in usable]
    candidates, verified = lsh_verified_pairs(
        route_sets,
        num_perm=num_perm,
        bands=bands,
        rows=rows,
        threshold=threshold,
        seed=seed,
    )
    weighted: list[tuple[str, str, float]] = []
    for left, right in verified:
        similarity = jaccard_similarity(route_sets[left], route_sets[right])
        first, second = usable[left], usable[right]
        if first > second:
            first, second = second, first
        weighted.append((first, second, similarity))
    weighted.sort()
    return similarity_graph(routes, weighted, threshold), candidates, verified


def compare_similarity_graphs(
    exact: nx.Graph, approximate: nx.Graph
) -> dict[str, float | int | None]:
    """Compare two graphs that must share nodes, with approximate edges inside the exact graph."""
    if set(exact.nodes) != set(approximate.nodes):
        raise ValueError("exact and approximate graphs do not have the same routes")
    exact_edges = {tuple(sorted(edge)) for edge in exact.edges}
    approximate_edges = {tuple(sorted(edge)) for edge in approximate.edges}
    invented = approximate_edges - exact_edges
    if invented:
        raise ValueError(f"approximate graph invented {len(invented)} edges")
    for left, right in approximate_edges:
        exact_weight = float(exact[left][right]["weight"])
        approximate_weight = float(approximate[left][right]["weight"])
        if abs(exact_weight - approximate_weight) > 1e-12:
            raise ValueError(f"edge {left}--{right} does not carry the exact Jaccard")
    exact_stats = graph_statistics(exact)
    approximate_stats = graph_statistics(approximate)
    retained = len(approximate_edges)
    n_exact = len(exact_edges)
    return {
        "n_nodes": int(exact_stats["n_nodes"]),
        "n_exact_edges": n_exact,
        "n_approximate_edges": retained,
        "n_edges_retained": retained,
        "n_edges_missed": n_exact - retained,
        "graph_edge_recall": (retained / n_exact) if n_exact else None,
        "exact_components": int(exact_stats["n_components"]),
        "approximate_components": int(approximate_stats["n_components"]),
        "exact_isolates": int(exact_stats["n_isolates"]),
        "approximate_isolates": int(approximate_stats["n_isolates"]),
        "exact_density": float(exact_stats["density"]),
        "approximate_density": float(approximate_stats["density"]),
    }


def community_report(
    labels: Mapping[str, int], modularity: float, sizes: Sequence[int]
) -> dict[str, float | int]:
    """Size summary of one Louvain partition. Modularity belongs to its own graph."""
    if sum(sizes) != len(labels):
        raise ValueError("community sizes do not cover the labeled routes")
    return {
        "n_communities": len(sizes),
        "n_singletons": sum(1 for size in sizes if size == 1),
        "n_non_singletons": sum(1 for size in sizes if size >= 2),
        "largest": max(sizes) if sizes else 0,
        "modularity": modularity,
    }


def placement_overlap(exact: Sequence[str], approximate: Sequence[str]) -> dict[str, float | int]:
    """Shared counter locations and the Jaccard similarity of the two selections."""
    exact_ids = set(exact)
    approximate_ids = set(approximate)
    if len(exact_ids) != len(exact) or len(approximate_ids) != len(approximate):
        raise ValueError("a placement contains a repeated counter id")
    shared = exact_ids & approximate_ids
    union = exact_ids | approximate_ids
    return {
        "n_exact": len(exact_ids),
        "n_approximate": len(approximate_ids),
        "n_shared": len(shared),
        "selected_jaccard": (len(shared) / len(union)) if union else 1.0,
    }


def balanced_selection(
    eligible_ids: Sequence[str],
    routes: RouteSets,
    labels: Mapping[str, int],
    lam: float,
    k: int,
) -> tuple[tuple[str, ...], dict[str, float]]:
    """Existing community weights and the existing weighted greedy selector."""
    weights, _info = community_weights(labels, lam)
    if set(weights) != set(routes):
        raise ValueError("community labels do not match the calibration routes used for placement")
    selected = select_greedy(eligible_ids, routes, k, weights)
    return selected, weights


def _choose_two(count: int) -> float:
    return count * (count - 1) / 2.0


def _entropy(counts: Mapping[int, int], total: int) -> float:
    return -sum((count / total) * math.log(count / total) for count in counts.values() if count)
