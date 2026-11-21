"""Route-similarity graphs, Louvain communities, and held-out assignment.

The graph is built from exact Jaccard edges. Louvain does not choose the
number of communities. Held-out routes are never added to the graph and
Louvain is not refit on them.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

import networkx as nx
from networkx.algorithms.community import louvain_communities, modularity

from cyclesense.similarity import jaccard_similarity

RouteId = str


def similarity_graph(
    route_ids: Iterable[RouteId],
    pairs: Sequence[tuple[RouteId, RouteId, float]],
    threshold: float,
) -> nx.Graph:
    """Undirected weighted graph. Routes below the threshold stay isolated."""
    graph = nx.Graph()
    graph.add_nodes_from(route_ids)
    for left, right, similarity in pairs:
        if similarity < threshold:
            continue
        if left not in graph or right not in graph:
            raise ValueError("pair mentions a route that is not a graph node")
        graph.add_edge(left, right, weight=float(similarity))
    return graph


def graph_statistics(graph: nx.Graph) -> dict[str, float | int]:
    """Density, components, isolates, and the weights of the edges that exist."""
    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    density = (2 * n_edges) / (n_nodes * (n_nodes - 1)) if n_nodes > 1 else 0.0
    weights = [float(data["weight"]) for _left, _right, data in graph.edges(data=True)]
    return {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "density": density,
        "n_components": nx.number_connected_components(graph),
        "n_isolates": sum(1 for node in graph if graph.degree(node) == 0),
        "weight_min": min(weights) if weights else 0.0,
        "weight_mean": (sum(weights) / len(weights)) if weights else 0.0,
        "weight_max": max(weights) if weights else 0.0,
    }


def detect_communities(graph: nx.Graph, seed: int) -> tuple[dict[RouteId, int], float, list[int]]:
    """Louvain labels, modularity, and community sizes.

    Community ids are sorted by decreasing size, then by the smallest route id.
    That numbering is only a label. It is not a requested community count.
    """
    parts = louvain_communities(graph, weight="weight", resolution=1, seed=seed)
    ordered = sorted(parts, key=lambda community: (-len(community), min(community)))
    labels: dict[RouteId, int] = {}
    for index, community in enumerate(ordered):
        for route_id in community:
            labels[route_id] = index
    if set(labels) != set(graph.nodes):
        raise RuntimeError("Louvain partition does not cover the route graph")
    score = float(modularity(graph, ordered, weight="weight"))
    sizes = [len(community) for community in ordered]
    return labels, score, sizes


def grouped_pair_recall(left: Mapping[RouteId, int], right: Mapping[RouteId, int]) -> float:
    """Of the pairs that share a community in ``left``, the share that still do in ``right``."""
    ids = sorted(set(left) & set(right))
    grouped = 0
    kept = 0
    for index, route_id in enumerate(ids):
        for other in ids[index + 1 :]:
            if left[route_id] != left[other]:
                continue
            grouped += 1
            kept += int(right[route_id] == right[other])
    if grouped == 0:
        return 1.0
    return kept / grouped


def pair_agreement(left: Mapping[RouteId, int], right: Mapping[RouteId, int]) -> float:
    """Share of route pairs on which two partitions agree about co-membership."""
    ids = sorted(set(left) & set(right))
    if len(ids) < 2:
        return 1.0
    agree = 0
    total = 0
    for index, route_id in enumerate(ids):
        for other in ids[index + 1 :]:
            same_left = left[route_id] == left[other]
            same_right = right[route_id] == right[other]
            agree += int(same_left == same_right)
            total += 1
    return agree / total


def assign_heldout(
    evaluation: Mapping[RouteId, Iterable[str]],
    calibration: Mapping[RouteId, Iterable[str]],
    labels: Mapping[RouteId, int],
    threshold: float,
) -> list[dict[str, object]]:
    """Assign an evaluation route only when its similar calibration routes agree.

    Neighbors are calibration routes with exact Jaccard at least ``threshold``.
    No neighbors leaves the route unassigned. Neighbors in more than one
    community leave it ambiguous and unassigned. Louvain is not run here.
    """
    calibration_sets = {route_id: set(edges) for route_id, edges in calibration.items()}
    if set(calibration_sets) != set(labels):
        raise ValueError("community labels must match the calibration routes")
    rows: list[dict[str, object]] = []
    for route_id, edges in evaluation.items():
        route_set = set(edges)
        if route_id in labels:
            raise ValueError(f"evaluation route {route_id} is already a calibration node")
        neighbor_labels: set[int] = set()
        best = 0.0
        n_neighbors = 0
        if route_set:
            for calibration_id, calibration_set in calibration_sets.items():
                similarity = jaccard_similarity(route_set, calibration_set)
                best = max(best, similarity)
                if similarity >= threshold:
                    n_neighbors += 1
                    neighbor_labels.add(labels[calibration_id])
        if not route_set or n_neighbors == 0:
            status = "unassigned"
            community: int | None = None
        elif len(neighbor_labels) == 1:
            status = "assigned"
            community = next(iter(neighbor_labels))
        else:
            status = "ambiguous"
            community = None
        rows.append(
            {
                "route_id": route_id,
                "status": status,
                "community": community,
                "n_neighbors": n_neighbors,
                "n_neighbor_communities": len(neighbor_labels),
                "max_jaccard": best,
            }
        )
    return rows


def community_medoid(
    members: Sequence[RouteId],
    routes: Mapping[RouteId, Iterable[str]],
) -> tuple[RouteId, float]:
    """Member with the highest mean exact Jaccard to the other members."""
    if not members:
        raise ValueError("community is empty")
    sets = {route_id: set(routes[route_id]) for route_id in members}
    best_id = members[0]
    best_score = -1.0
    for route_id in members:
        others = [other for other in members if other != route_id]
        if not others:
            score = 1.0
        else:
            score = sum(jaccard_similarity(sets[route_id], sets[other]) for other in others) / len(others)
        if score > best_score or (score == best_score and route_id < best_id):
            best_id = route_id
            best_score = score
    return best_id, best_score


def shared_edges(
    members: Sequence[RouteId],
    routes: Mapping[RouteId, Iterable[str]],
    *,
    minimum_support: float = 0.5,
) -> list[tuple[str, float]]:
    """Edges present in at least ``minimum_support`` of the member routes."""
    if not members:
        return []
    counts: Counter[str] = Counter()
    for route_id in members:
        counts.update(set(routes[route_id]))
    ranked = []
    for edge_id, count in counts.items():
        support = count / len(members)
        if support >= minimum_support:
            ranked.append((edge_id, support))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked
