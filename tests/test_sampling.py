from cyclesense.sampling import commuter_weights, sample_od_pairs

NODES = list(range(21))
COORDS = {node: (node * 100.0, 0.0) for node in NODES}
ANCHOR = (0.0, 0.0)


def test_uniform_draws_are_reproducible_and_inside_the_band() -> None:
    first, _stats = sample_od_pairs(
        NODES,
        COORDS,
        n_pairs=25,
        seed=42,
        mode="uniform",
        min_distance_m=400,
        max_distance_m=1800,
    )
    second, _stats = sample_od_pairs(
        NODES,
        COORDS,
        n_pairs=25,
        seed=42,
        mode="uniform",
        min_distance_m=400,
        max_distance_m=1800,
    )
    other, _stats = sample_od_pairs(
        NODES,
        COORDS,
        n_pairs=25,
        seed=43,
        mode="uniform",
        min_distance_m=400,
        max_distance_m=1800,
    )
    assert first == second
    assert first != other
    assert len(first) == 25
    assert len(set(first)) == 25
    for origin, destination in first:
        distance = abs(COORDS[origin][0] - COORDS[destination][0])
        assert 400 <= distance <= 1800


def test_commuter_proxy_sends_destinations_toward_the_anchor() -> None:
    pairs, _stats = sample_od_pairs(
        NODES,
        COORDS,
        n_pairs=400,
        seed=7,
        mode="commuter_proxy",
        min_distance_m=100,
        max_distance_m=2000,
        anchor_xy=ANCHOR,
        max_attempts=5000,
    )
    mean_origin = sum(COORDS[origin][0] for origin, _destination in pairs) / len(pairs)
    mean_destination = sum(COORDS[destination][0] for _origin, destination in pairs) / len(pairs)
    assert mean_origin > mean_destination
    origin_weights, destination_weights = commuter_weights(NODES, COORDS, ANCHOR)
    assert origin_weights[-1] > origin_weights[0]
    assert destination_weights[0] > destination_weights[-1]


def test_excluded_pairs_are_not_repeated() -> None:
    pairs, stats = sample_od_pairs(
        [1, 2, 3],
        {1: (0.0, 0.0), 2: (500.0, 0.0), 3: (1000.0, 0.0)},
        n_pairs=4,
        seed=1,
        mode="uniform",
        min_distance_m=100,
        max_distance_m=2000,
        excluded_pairs=[(1, 2), (2, 1), (1, 3), (3, 1), (2, 3), (3, 2)],
        max_attempts=30,
    )
    assert pairs == []
    assert stats["rejected_duplicate"] > 0
