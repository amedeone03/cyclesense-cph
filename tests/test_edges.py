from cyclesense.edges import (
    eligibility_decision,
    indicates_contraflow,
    physical_edge_id,
)


def _segment(**overrides: object) -> dict:
    segment = {
        "u": 1,
        "v": 2,
        "length_m": 40.0,
        "highway": ["residential"],
        "service": [],
        "bicycle": [],
        "access": [],
    }
    segment.update(overrides)
    return segment


def test_physical_id_merges_opposite_directions_and_reversed_way_lists() -> None:
    assert physical_edge_id(1, 2, 10) == physical_edge_id(2, 1, 10)
    assert physical_edge_id(1, 2, [10, 11]) == physical_edge_id(2, 1, [11, 10])


def test_physical_id_keeps_parallel_ways_and_blocks_distinct() -> None:
    assert physical_edge_id(1, 2, 10) != physical_edge_id(1, 2, 11)
    assert physical_edge_id(1, 2, 10) != physical_edge_id(2, 3, 10)
    assert physical_edge_id(5, 5, 10).startswith("pe:loop:")


def test_contraflow_requires_unambiguous_bicycle_tags() -> None:
    assert indicates_contraflow({"oneway:bicycle": "no"})
    assert indicates_contraflow({"cycleway:left": "opposite_lane"})
    assert not indicates_contraflow({"cycleway": "lane"})
    assert not indicates_contraflow({"oneway:bicycle": ["no", "yes"]})
    assert not indicates_contraflow({"highway": "residential"})


def test_eligibility_accepts_a_residential_block_and_rejects_proxies() -> None:
    assert eligibility_decision(_segment(), min_length_m=15) is None
    assert eligibility_decision(_segment(length_m=10), min_length_m=15) == "shorter_than_minimum"
    assert eligibility_decision(_segment(service=["driveway"]), min_length_m=15) == "service_not_a_counting_site"
    assert eligibility_decision(_segment(highway=["trunk"]), min_length_m=15) == "highway_not_a_counting_site"
    assert (
        eligibility_decision(_segment(highway=["pedestrian"]), min_length_m=15)
        == "pedestrian_without_bicycle_permission"
    )
    assert eligibility_decision(_segment(highway=["pedestrian"], bicycle=["yes"]), min_length_m=15) is None
    assert eligibility_decision(_segment(bicycle=["use_sidepath"]), min_length_m=15) == "bicycle_tag_excludes_counting"
    assert eligibility_decision(_segment(u=4, v=4), min_length_m=15) == "self_loop"
