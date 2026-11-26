"""Synthetic checks for the municipal-count comparison.

These tests do not read the Copenhagen extract and do not claim a traffic result.
"""

import pytest

from cyclesense.external_validation import (
    GEOMETRY_SAMPLE,
    PRIMARY_SAMPLE,
    SENSITIVITY_SAMPLE,
    CountSite,
    SegmentGeometry,
    additional_counters,
    collapse_duplicate_edges,
    distance_to_polyline_m,
    evaluate_extension,
    match_sites,
    parse_danish_float,
    parse_trafiktal_csv,
    select_sites,
    spearman_rho,
    street_names_agree,
)

BBOX = (12.5630, 55.6705, 12.5965, 55.6880)
ANCHOR = (12.5689, 55.6761)
CSV_HEADER = (
    "t_nr,vejnavn,beskrivelse,taelling_type,aadt_cykler,aar,taelle_dato,wkb_geometry\n"
)


def _site(
    place_id: str,
    street: str,
    longitude: float,
    latitude: float,
    aadt: float | None,
    *,
    year: int = 2024,
    count_type: str = "Andre faste tællinger",
    count_date: int = 20240601,
) -> CountSite:
    return CountSite(
        place_id=place_id,
        street=street,
        description="",
        count_type=count_type,
        year=year,
        count_date=count_date,
        bike_aadt=aadt,
        longitude=longitude,
        latitude=latitude,
        source_row_id=place_id,
    )


def _segment(edge_id: str, lon1: float, lat1: float, lon2: float, lat2: float, name: str) -> SegmentGeometry:
    return SegmentGeometry(
        physical_edge_id=edge_id,
        polyline=((lon1, lat1), (lon2, lat2)),
        name=name,
    )


def _route(route_id: str, scenario: str, split: str, *edges: str):
    from cyclesense.external_validation import RouteRecord

    return RouteRecord(route_id, scenario, split, frozenset(edges))


def test_parser_keeps_latest_positive_count_inside_the_rectangle() -> None:
    text = (
        CSV_HEADER
        + '7,Gothersgade,east,Andre faste tællinger,100,2020,20200601,"POINT (12.571 55.676)"\n'
        + '7,Gothersgade,east,Andre faste tællinger,18000,2024,20240901,"POINT (12.571 55.676)"\n'
        + '8,Nørregade,south,Andre faste tællinger,0,2024,20240101,"POINT (12.580 55.680)"\n'
        + '9,Far Street,x,Andre faste tællinger,500,2024,20240101,"POINT (13.100 55.700)"\n'
        + '10,Knippelsbro,bridge,Krydstællinger,9000,2024,20240101,"POINT (12.587 55.675)"\n'
        + "11,Broken,x,Andre faste tællinger,10,2024,20240101,POINT\n"
    )
    sites = parse_trafiktal_csv(text)
    assert parse_danish_float("1,25") == pytest.approx(1.25)
    assert parse_danish_float("16200") == 16200
    selected = select_sites(
        sites,
        bbox=BBOX,
        count_types=frozenset({"Andre faste tællinger"}),
        min_year=2019,
    )
    assert [site.place_id for site in selected] == ["7"]
    assert selected[0].bike_aadt == 18000
    assert selected[0].year == 2024


def test_parser_rejects_a_file_without_the_bicycle_column() -> None:
    with pytest.raises(ValueError, match="aadt_cykler"):
        parse_trafiktal_csv("t_nr,vejnavn\n1,Gothersgade\n")


def test_street_name_agreement_ignores_punctuation_and_short_fragments() -> None:
    assert street_names_agree("H.C. Andersens Boulevard", "HC Andersens Boulevard")
    assert street_names_agree("Cykelsti over Rådhuspladsen", "Rådhuspladsen")
    assert street_names_agree("Gothersgade", "Nørregade / Gothersgade")
    assert not street_names_agree("Gothersgade", "Nørregade")
    assert not street_names_agree("Gade", "Gothersgade")
    assert not street_names_agree("Nyhavn", "")


def test_point_to_segment_distance_is_in_metres() -> None:
    segment = ((12.57, 55.68), (12.58, 55.68))
    distance = distance_to_polyline_m(12.575, 55.6803, segment)
    assert distance == pytest.approx(0.0003 * 110_540, abs=0.05)


def test_parallel_segments_are_ambiguous_and_not_assigned() -> None:
    offset = 8 / 110_540
    segments = [
        _segment("a", 12.570, 55.680, 12.572, 55.680, "Gothersgade"),
        _segment("b", 12.570, 55.680 + offset, 12.572, 55.680 + offset, "Other Street"),
    ]
    site = _site("1", "Gothersgade", 12.571, 55.680 + offset / 2, 100)
    match = match_sites([site], segments, max_distance_m=35, ambiguity_gap_m=12)[0]
    assert match.status == "ambiguous"
    assert match.physical_edge_id is None


def test_a_far_site_is_unmatched() -> None:
    segments = [_segment("a", 12.570, 55.680, 12.572, 55.680, "Gothersgade")]
    site = _site("1", "Gothersgade", 12.571, 55.680 + 100 / 110_540, 100)
    match = match_sites([site], segments, max_distance_m=35, ambiguity_gap_m=12)[0]
    assert match.status == "unmatched"


def test_duplicate_edge_keeps_the_latest_count() -> None:
    segment = _segment("a", 12.570, 55.676, 12.572, 55.676, "Gothersgade")
    older = _site("1", "Gothersgade", 12.571, 55.676, 100, year=2020)
    newer = _site("2", "Gothersgade", 12.571, 55.676, 200, year=2024)
    matches = match_sites([older, newer], [segment], max_distance_m=35, ambiguity_gap_m=12)
    collapsed = collapse_duplicate_edges(matches)
    kept = [match for match in collapsed if match.status == "matched"]
    dropped = [match for match in collapsed if match.status == "collapsed_duplicate_edge"]
    assert len(kept) == 1
    assert kept[0].site.place_id == "2"
    assert len(dropped) == 1
    assert dropped[0].physical_edge_id is None


def test_spearman_handles_perfect_ranks_and_constant_columns() -> None:
    assert spearman_rho([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1)
    assert spearman_rho([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1)
    assert spearman_rho([1, 1, 1], [1, 2, 3]) is None


def test_additional_counters_skip_routes_already_intercepted() -> None:
    routes = {"r1": {"a", "b"}, "r2": {"c"}}
    added = additional_counters(routes, existing_edges=["a"], eligible_edges=["a", "b", "c"], budget=1)
    assert added == ("c",)
    assert additional_counters(routes, existing_edges=["a", "c"], eligible_edges=["b"], budget=2) == ()


def test_extension_separates_verified_sites_from_simulated_coverage() -> None:
    segments = [
        _segment("a", 12.570, 55.676, 12.572, 55.676, "Gothersgade"),
        _segment("b", 12.580, 55.680, 12.582, 55.680, "Nørregade"),
        _segment("c", 12.590, 55.682, 12.592, 55.682, "Vestergade"),
    ]
    sites = [
        _site("1", "Gothersgade", 12.571, 55.676, 300),
        _site("2", "Nørregade", 12.581, 55.680, 100),
        _site("3", "Vestergade", 12.591, 55.682, 50, count_type="Øvrige tællinger"),
        _site("4", "Gothersgade", 12.571, 55.676, 999, count_type="Krydstællinger"),
        _site("5", "Somewhere", 13.1, 55.7, 999),
    ]
    routes = [
        _route("c1", "uniform", "calibration", "a"),
        _route("c2", "uniform", "calibration", "a"),
        _route("c3", "uniform", "calibration", "a"),
        _route("c4", "uniform", "calibration", "b"),
        _route("c5", "uniform", "calibration", "c"),
        _route("e1", "uniform", "evaluation", "a"),
        _route("e2", "uniform", "evaluation", "a"),
        _route("e3", "uniform", "evaluation", "b"),
        _route("e4", "uniform", "evaluation", "c"),
    ]
    result = evaluate_extension(
        sites,
        segments,
        routes,
        bbox=BBOX,
        anchor=ANCHOR,
        anchor_name="Rådhuspladsen",
        budgets=(1,),
        permutations=30,
        seed=42,
    )
    primary = result["samples"][PRIMARY_SAMPLE]
    assert primary["n_analysis_edges"] == 2
    assert {row["physical_edge_id"] for row in primary["alignment_rows"]} == {"a", "b"}
    geometric = result["samples"][GEOMETRY_SAMPLE]
    assert geometric["n_analysis_edges"] == 2
    sensitivity = result["samples"][SENSITIVITY_SAMPLE]
    assert {row["physical_edge_id"] for row in sensitivity["alignment_rows"]} == {"a", "b", "c"}
    rank = next(
        test
        for test in primary["rank_tests"]
        if test["comparison"] == "modeled_traversals_vs_bike_aadt"
    )
    assert rank["n"] == 2
    assert rank["spearman_rho"] == pytest.approx(1)
    assert rank["interpretable"] is False
    coverage = result["coverage"][0]
    assert coverage["n_existing"] == 2
    assert coverage["held_out_existing_coverage"] == pytest.approx(0.75)
    assert coverage["budgets"][0]["added_edges"] == ["c"]
    assert coverage["budgets"][0]["held_out_marginal_gain"] == pytest.approx(0.25)
    assert "c" not in coverage["existing_edges"]
    assert result["interpretation"]["rank_correlation_reported"] is False
