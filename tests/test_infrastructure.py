"""Infrastructure classes, candidate policies, and a tiny constrained MILP."""

from __future__ import annotations

import pytest

from cyclesense.coverage import evaluate_coverage
from cyclesense.exact_optimization import brute_force_maximum_coverage, solve_maximum_coverage
from cyclesense.external_validation import additional_counters
from cyclesense.infrastructure import (
    assert_selection_split,
    classify_physical_edge,
    feasibility,
    permitted_ids,
)
from cyclesense.placement import select_greedy


def _edge(**tags: str) -> dict[str, str]:
    return tags


def test_dedicated_cycleway_is_not_merged_with_another_street() -> None:
    first = classify_physical_edge("pe:a", [_edge(highway="cycleway", name="Same Street")])
    second = classify_physical_edge("pe:b", [_edge(highway="residential", name="Same Street")])
    assert first["physical_edge_id"] == "pe:a"
    assert first["category"] == "dedicated"
    assert second["physical_edge_id"] == "pe:b"
    assert second["category"] == "unknown"
    assert "name" not in first


def test_missing_cycleway_tag_is_unknown_not_absent() -> None:
    row = classify_physical_edge("pe:road", [_edge(highway="residential", bicycle="yes")])
    assert row["category"] == "unknown"
    assert row["reason"] == "missing_cycleway_tags"
    assert row["missing_cycleway_tags"] is True


def test_explicit_negative_cycleway_is_routable_without_a_facility() -> None:
    row = classify_physical_edge("pe:road", [_edge(highway="tertiary", cycleway="no")])
    assert row["category"] == "other_routable"
    assert row["reason"] == "cycleway_tag_without_facility"


def test_lane_on_a_road_is_an_explicit_facility() -> None:
    row = classify_physical_edge(
        "pe:lane",
        [_edge(highway="residential", **{"cycleway:right": "lane"})],
    )
    assert row["category"] == "explicit_facility"
    assert row["bicycle"] == ""


def test_opposing_facility_tags_are_ambiguous() -> None:
    row = classify_physical_edge(
        "pe:conflict",
        [
            _edge(highway="residential", cycleway="lane"),
            _edge(highway="residential", cycleway="track"),
        ],
    )
    assert row["category"] == "ambiguous"
    assert row["directional_conflict"] is True
    assert row["physical_edge_id"] == "pe:conflict"


def test_mixed_cycleway_and_carriageway_is_not_dedicated() -> None:
    row = classify_physical_edge("pe:mixed", [{"highway": ["cycleway", "residential"]}])
    assert row["category"] == "ambiguous"
    assert row["reason"] == "mixed_highway"


def test_classification_is_deterministic() -> None:
    edges = [_edge(highway="cycleway"), _edge(highway="cycleway", cycleway="track")]
    assert classify_physical_edge("pe:a", edges) == classify_physical_edge("pe:a", list(reversed(edges)))


def test_policies_drop_unknown_segments_and_report_an_infeasible_budget() -> None:
    classified = [
        classify_physical_edge("pe:cycle", [_edge(highway="cycleway")]),
        classify_physical_edge("pe:lane", [_edge(highway="residential", cycleway="lane")]),
        classify_physical_edge("pe:plain", [_edge(highway="residential")]),
    ]
    assert permitted_ids(classified, "unrestricted") == ("pe:cycle", "pe:lane", "pe:plain")
    assert permitted_ids(classified, "explicit_facility") == ("pe:cycle", "pe:lane")
    assert permitted_ids(classified, "dedicated") == ("pe:cycle",)
    assert feasibility(1, 1) == "feasible"
    assert feasibility(1, 5) == "infeasible"


def test_unrestricted_greedy_matches_the_existing_selector() -> None:
    classified = [
        {"physical_edge_id": edge, "category": "unknown"}
        for edge in ("a", "b", "c")
    ]
    routes = {"r1": {"a"}, "r2": {"a", "b"}, "r3": {"c"}}
    selected = select_greedy(permitted_ids(classified, "unrestricted"), routes, 2)
    assert selected == select_greedy(["a", "b", "c"], routes, 2)
    assert len(selected) == len(set(selected)) == 2


def test_constrained_milp_matches_brute_force_and_reports_status() -> None:
    routes = {"r1": {"a", "b"}, "r2": {"b"}, "r3": {"c"}}
    weights = {route_id: 1.0 for route_id in routes}
    solved = solve_maximum_coverage(routes, weights, ["a", "c"], 1, time_limit_seconds=10)
    best, _value = brute_force_maximum_coverage(routes, weights, ["a", "c"], 1)
    assert solved.proven_optimal is True
    assert solved.status == "optimal"
    assert solved.support_coverage == pytest.approx(
        evaluate_coverage(routes, best, weights).coverage_fraction
    )
    assert set(solved.selected) <= {"a", "c"}
    assert len(solved.selected) == 1


def test_selection_rejects_the_held_out_split() -> None:
    assert_selection_split("calibration")
    with pytest.raises(ValueError, match="calibration"):
        assert_selection_split("evaluation")


def test_municipal_additions_keep_the_fixed_sites_out() -> None:
    routes = {"r1": {"m", "a"}, "r2": {"b"}, "r3": {"c"}}
    added = additional_counters(routes, ["m"], ["m", "a", "b", "c"], 2)
    assert "m" not in added
    assert len(added) == len(set(added))
    assert set(added) <= {"a", "b", "c"}


def test_missing_metadata_does_not_invent_a_facility() -> None:
    row = classify_physical_edge("pe:bare", [{}])
    assert row["category"] == "unknown"
    assert row["highway"] == ""
    assert row["cycleway"] == ""
