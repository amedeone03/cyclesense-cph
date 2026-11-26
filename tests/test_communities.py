import networkx as nx

from cyclesense.communities import (
    assign_heldout,
    community_medoid,
    detect_communities,
    graph_statistics,
    grouped_pair_recall,
    pair_agreement,
    shared_edges,
    similarity_graph,
)


def test_similarity_graph_keeps_isolated_routes() -> None:
    graph = similarity_graph(["a", "b", "c"], [("a", "b", 0.8), ("a", "c", 0.2)], threshold=0.5)
    assert set(graph.nodes) == {"a", "b", "c"}
    assert list(graph.edges) == [("a", "b")]
    stats = graph_statistics(graph)
    assert stats["n_isolates"] == 1
    assert stats["n_edges"] == 1
    assert stats["weight_min"] == 0.8


def test_louvain_separates_two_disconnected_cliques() -> None:
    graph = nx.Graph()
    graph.add_nodes_from(range(8))
    for group in (range(4), range(4, 8)):
        for left in group:
            for right in group:
                if left < right:
                    graph.add_edge(left, right, weight=1.0)
    labels, score, sizes = detect_communities(graph, seed=0)
    assert score > 0
    assert labels[0] == labels[1]
    assert labels[0] != labels[4]
    assert sorted(sizes) == [4, 4]


def test_heldout_assignment_allows_unassigned_and_ambiguous_routes() -> None:
    calibration = {
        "a": {"1", "2", "3", "4"},
        "b": {"1", "2", "3", "5"},
        "c": {"10", "11", "12", "13"},
    }
    labels = {"a": 0, "b": 0, "c": 1}
    rows = assign_heldout(
        {
            "near": {"1", "2", "3", "4", "5"},
            "split": {"1", "2", "10", "11"},
            "far": {"20", "21", "22", "23"},
        },
        calibration,
        labels,
        threshold=0.3,
    )
    by_id = {row["route_id"]: row for row in rows}
    assert by_id["near"]["status"] == "assigned"
    assert by_id["near"]["community"] == 0
    assert by_id["split"]["status"] == "ambiguous"
    assert by_id["split"]["community"] is None
    assert by_id["far"]["status"] == "unassigned"
    assert set(labels) == {"a", "b", "c"}


def test_medoid_and_shared_edges_use_exact_overlap() -> None:
    routes = {"a": {"1", "2", "3"}, "b": {"1", "2", "4"}, "c": {"8", "9"}}
    medoid, score = community_medoid(["a", "b"], routes)
    assert medoid in {"a", "b"}
    assert score == 0.5
    shared = shared_edges(["a", "b", "c"], routes, minimum_support=0.5)
    assert ("1", 2 / 3) in shared
    assert {edge for edge, _support in shared} == {"1", "2"}


def test_grouped_pair_recall_drops_when_a_community_splits() -> None:
    together = {"a": 0, "b": 0, "c": 0}
    split = {"a": 0, "b": 0, "c": 1}
    assert grouped_pair_recall(together, split) == 1 / 3
    assert grouped_pair_recall(split, together) == 1.0


def test_pair_agreement_is_one_for_the_same_partition() -> None:
    labels = {"a": 0, "b": 0, "c": 1}
    assert pair_agreement(labels, labels) == 1.0
    swapped = {"a": 1, "b": 1, "c": 0}
    assert pair_agreement(labels, swapped) == 1.0
