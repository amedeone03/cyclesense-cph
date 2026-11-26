from cyclesense.minhash import (
    build_lsh_buckets,
    build_signatures,
    choose_operating_point,
    minhash_coefficients,
    minhash_signature,
    query_lsh_pairs,
    retrieval_metrics,
    signature_jaccard,
    verify_candidates,
)


def test_minhash_is_reproducible_and_identical_sets_match() -> None:
    coefficients = minhash_coefficients(32, seed=42)
    first = minhash_signature(["e2", "e1"], coefficients)
    second = minhash_signature(["e1", "e2"], coefficients)
    other_seed = minhash_signature(["e1", "e2"], minhash_coefficients(32, seed=7))
    assert first == second
    assert signature_jaccard(first, second) == 1.0
    assert first != other_seed
    again = build_signatures([{"e1", "e2"}, {"e1", "e2"}], 32, seed=42)
    assert again[0] == again[1] == first


def test_lsh_retrieves_identical_routes_and_reports_recall() -> None:
    routes = [{"a", "b", "c", "d"}, {"a", "b", "c", "d"}, {"z", "y", "x", "w"}]
    signatures = build_signatures(routes, 32, seed=1)
    buckets = build_lsh_buckets(signatures, bands=8, rows=4)
    candidates = query_lsh_pairs(signatures, buckets, bands=8, rows=4)
    assert (0, 1) in candidates
    verified = verify_candidates(candidates, [set(route) for route in routes], 0.9)
    assert verified == {(0, 1)}
    exact = {(0, 1): 1.0, (0, 2): 0.0, (1, 2): 0.0}
    metrics = retrieval_metrics(candidates, exact, 0.5, n_routes=3)
    assert metrics["recall"] == 1.0
    assert metrics["n_true_pairs"] == 1


def test_operating_point_prefers_high_recall_then_fewer_candidates() -> None:
    records = [
        {"threshold": 0.5, "recall": 0.99, "n_candidates": 50, "num_perm": 128, "bands": 16},
        {"threshold": 0.5, "recall": 0.96, "n_candidates": 10, "num_perm": 64, "bands": 16},
        {"threshold": 0.5, "recall": 0.50, "n_candidates": 1, "num_perm": 32, "bands": 4},
        {"threshold": 0.3, "recall": 1.0, "n_candidates": 1, "num_perm": 32, "bands": 4},
    ]
    chosen = choose_operating_point(records)
    assert chosen["n_candidates"] == 10
    assert chosen["num_perm"] == 64