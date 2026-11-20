from cyclesense.similarity import jaccard_similarity


def test_jaccard_identical() -> None:
    assert jaccard_similarity({1, 2}, {2, 1}) == 1.0


def test_jaccard_partial() -> None:
    assert jaccard_similarity({1, 2}, {2, 3}) == 1 / 3


def test_jaccard_disjoint() -> None:
    assert jaccard_similarity({1}, {2}) == 0.0
