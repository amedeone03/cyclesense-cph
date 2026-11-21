from cyclesense.similarity import jaccard_similarity, pairwise_jaccard, similarity_distribution


def test_jaccard_identical() -> None:
    assert jaccard_similarity({1, 2}, {2, 1}) == 1.0


def test_jaccard_partial() -> None:
    assert jaccard_similarity({1, 2}, {2, 3}) == 1 / 3


def test_jaccard_disjoint() -> None:
    assert jaccard_similarity({1}, {2}) == 0.0


def test_pairwise_jaccard_is_upper_triangle_and_skips_empty_routes() -> None:
    pairs = pairwise_jaccard({"b": {2, 3}, "a": {1, 2}, "empty": set()})
    assert pairs == (("a", "b", 1 / 3),)
    summary = similarity_distribution(pairs, bin_width=0.5, thresholds=(1 / 3,))
    assert summary["n_pairs"] == 1
    assert summary["threshold_counts"][1 / 3] == 1
