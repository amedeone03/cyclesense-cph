"""Compare modeled counter placement with Copenhagen's published bicycle counts.

The counts are municipal screenline observations (daytime bicycle counts expanded
to annual average daily traffic). They are not GPS trips and not a proof that a
simulated route was ridden. Modeled-route coverage stays a property of the
project's simulated paths.

Matching uses the published point, the study rectangle, the street name, and the
eligible-segment geometry. Thresholds below are fixed before looking at any
rank correlation.
"""

from __future__ import annotations

import csv
import math
import random
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path
from statistics import median

from cyclesense.coverage import evaluate_coverage, greedy_max_coverage

TRAFIKTAL_INFO_URL = "https://www.opendata.dk/city-of-copenhagen/trafiktal"
TRAFIKTAL_CSV_URL = (
    "https://wfs-kbhkort.kk.dk/k101/ows?service=WFS&version=1.0.0"
    "&request=GetFeature&typeName=k101:trafiktaelling&outputFormat=csv&SRSNAME=EPSG:4326"
)
TRAFIKTAL_COLUMNS_URL = (
    "https://admin.opendata.dk/dataset/a8816a15-0609-4e3b-baca-897aedcbc9ac/resource/"
    "3a91cf0c-8366-404b-9e76-36f9ba769988/download/kolonner_dansk_english.xlsx"
)
TRAFIKTAL_LICENSE = "CC0"
TRAFIKTAL_PUBLISHER = "Københavns Kommune, Bydata"

# Recurring programme: Søsnittet is counted every year; "Andre faste tællinger"
# are repeated on a 10-year cycle. Project counts and junction counts are separate.
RECURRING_COUNT_TYPES = frozenset({"Søsnittet", "Andre faste tællinger"})
PROJECT_COUNT_TYPES = frozenset({"Øvrige tællinger"})
SENSITIVITY_COUNT_TYPES = RECURRING_COUNT_TYPES | PROJECT_COUNT_TYPES

# Municipal column note: since 2009, bicycle AADT = 07:00–19:00 count, both
# directions, multiplied by 1.03. This module reads the published AADT field
# and does not apply that factor again.
AADT_DEFINITION = (
    "Published aadt_cykler: bicycles counted 07:00-19:00 in both directions, "
    "times 1.03 since 2009. Not a continuous automatic counter."
)

PRIMARY_MIN_YEAR = 2019
MAX_SNAP_DISTANCE_M = 35.0
AMBIGUITY_GAP_M = 12.0
MIN_NAME_COMPACT_LENGTH = 5
MIN_PAIRS_FOR_CORRELATION = 8
PRIMARY_SAMPLE = "recurring_name_agree"
GEOMETRY_SAMPLE = "recurring_geometric"
SENSITIVITY_SAMPLE = "recurring_plus_project_geometric"

_POINT_RE = re.compile(
    r"POINT\s*\(\s*([+-]?\d+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)\s*\)",
    re.IGNORECASE,
)
_LINE_FLOAT_RE = re.compile(
    r"([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\s+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"
)
_REQUIRED_COLUMNS = (
    "t_nr",
    "vejnavn",
    "taelling_type",
    "aadt_cykler",
    "aar",
    "taelle_dato",
    "wkb_geometry",
)


@dataclass(frozen=True)
class CountSite:
    """One published counting place after a single CSV row has been parsed."""

    place_id: str
    street: str
    description: str
    count_type: str
    year: int
    count_date: int
    bike_aadt: float | None
    longitude: float
    latitude: float
    source_row_id: str


@dataclass(frozen=True)
class SegmentGeometry:
    """Eligible physical segment as a longitude/latitude polyline."""

    physical_edge_id: str
    polyline: tuple[tuple[float, float], ...]
    highway: str = ""
    name: str = ""


@dataclass(frozen=True)
class RouteRecord:
    route_id: str
    scenario: str
    split: str
    physical_edge_ids: frozenset[str]


@dataclass(frozen=True)
class SiteMatch:
    site: CountSite
    status: str
    nearest_edge_id: str | None
    distance_m: float | None
    second_edge_id: str | None
    second_distance_m: float | None
    physical_edge_id: str | None
    osm_name: str
    name_status: str


def parse_danish_float(value: str) -> float | None:
    """Parse a municipal number. Bicycle AADT values in this feed are plain integers."""
    text = value.strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_point(geometry: str) -> tuple[float, float] | None:
    """Return longitude, latitude from a WKT point. Empty geometries are skipped."""
    match = _POINT_RE.search(geometry or "")
    if match is None:
        return None
    return float(match.group(1)), float(match.group(2))


def parse_linestring(geometry: object) -> tuple[tuple[float, float], ...] | None:
    """Read a LINESTRING or a shapely-like coordinate sequence as lon/lat pairs."""
    if geometry is None:
        return None
    if hasattr(geometry, "coords"):
        points = tuple((float(xy[0]), float(xy[1])) for xy in geometry.coords)
        return points if len(points) >= 2 else None
    text = str(geometry).strip()
    if "LINESTRING" not in text.upper():
        return None
    points = tuple((float(lon), float(lat)) for lon, lat in _LINE_FLOAT_RE.findall(text))
    return points if len(points) >= 2 else None


def parse_trafiktal_csv(text: str) -> list[CountSite]:
    """Parse the municipal traffic-count CSV. Rows without a point or year are omitted."""
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ValueError("traffic-count CSV has no header")
    missing = [name for name in _REQUIRED_COLUMNS if name not in reader.fieldnames]
    if missing:
        raise ValueError(f"traffic-count CSV is missing columns: {', '.join(missing)}")
    sites: list[CountSite] = []
    for index, row in enumerate(reader, start=2):
        point = parse_point(row.get("wkb_geometry", ""))
        year = _parse_year(row.get("aar", ""))
        if point is None or year is None:
            continue
        place = (row.get("t_nr") or "").strip() or f"row-{index}"
        source = (row.get("ogc_fid") or row.get("FID") or str(index)).strip()
        sites.append(
            CountSite(
                place_id=place,
                street=(row.get("vejnavn") or "").strip(),
                description=(row.get("beskrivelse") or "").strip(),
                count_type=(row.get("taelling_type") or "").strip(),
                year=year,
                count_date=_parse_date(row.get("taelle_dato", "")),
                bike_aadt=parse_danish_float(row.get("aadt_cykler", "")),
                longitude=point[0],
                latitude=point[1],
                source_row_id=source,
            )
        )
    return sites


def load_count_sites(path: Path) -> list[CountSite]:
    return parse_trafiktal_csv(path.read_text(encoding="utf-8-sig"))


def load_route_records(path: Path) -> list[RouteRecord]:
    """Read modeled routes. ``scenario_weight`` is ignored because M1 stores 1 per draw."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "physical_edge_ids" not in reader.fieldnames:
            raise ValueError("routes CSV has no physical_edge_ids column")
        records: list[RouteRecord] = []
        for row in reader:
            edge_ids = frozenset(part for part in (row.get("physical_edge_ids") or "").split("|") if part)
            records.append(
                RouteRecord(
                    route_id=row["route_id"],
                    scenario=row["scenario"],
                    split=row["split"],
                    physical_edge_ids=edge_ids,
                )
            )
    if not records:
        raise ValueError("routes CSV has no modeled routes")
    return records


def select_sites(
    sites: Sequence[CountSite],
    *,
    bbox: tuple[float, float, float, float],
    count_types: frozenset[str],
    min_year: int,
) -> list[CountSite]:
    """Keep the latest positive bicycle AADT for each place inside the rectangle.

    ``bbox`` is west, south, east, north in WGS84 degrees. Junction counts stay
    out because the caller does not put them in ``count_types``.
    """
    west, south, east, north = bbox
    latest: dict[str, CountSite] = {}
    for site in sites:
        if site.count_type not in count_types:
            continue
        if site.year < min_year or site.bike_aadt is None or site.bike_aadt <= 0:
            continue
        if not (west <= site.longitude <= east and south <= site.latitude <= north):
            continue
        current = latest.get(site.place_id)
        ranking = (site.year, site.count_date, site.source_row_id)
        if current is None or ranking > (current.year, current.count_date, current.source_row_id):
            latest[site.place_id] = site
    return sorted(latest.values(), key=lambda site: site.place_id)


def street_names_agree(municipal: str, osm: str) -> bool:
    """Whether the published street name and the OSM name refer to the same road.

    Short fragments such as ``gade`` do not count as a match. Punctuation is
    ignored, so ``H.C. Andersens Boulevard`` agrees with ``HC Andersens Boulevard``.
    """
    if not osm.strip():
        return False
    parts = [part.strip() for part in osm.split("/")] or [osm]
    return any(_one_name_agrees(municipal, part) for part in parts if part)


def distance_to_polyline_m(
    longitude: float,
    latitude: float,
    polyline: Sequence[tuple[float, float]],
) -> float:
    """Metres from a WGS84 point to a polyline, using a local equirectangular plane."""
    if not polyline:
        raise ValueError("polyline must contain at least one point")
    origin = latitude
    point_x, point_y = _xy(longitude, latitude, origin)
    if len(polyline) == 1:
        other_x, other_y = _xy(polyline[0][0], polyline[0][1], origin)
        return math.hypot(point_x - other_x, point_y - other_y)
    best = math.inf
    for start, end in pairwise(polyline):
        best = min(best, _segment_distance(point_x, point_y, start, end, origin))
    return best


def distance_between_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    origin = (lat1 + lat2) / 2
    x1, y1 = _xy(lon1, lat1, origin)
    x2, y2 = _xy(lon2, lat2, origin)
    return math.hypot(x1 - x2, y1 - y2)


def segments_from_directed_edges(edges: Iterable[Mapping[str, object]]) -> list[SegmentGeometry]:
    """Collapse directed edges that share a physical id. The richer polyline is kept."""
    grouped: dict[str, SegmentGeometry] = {}
    for edge in edges:
        edge_id = str(edge["physical_edge_id"])
        raw = edge["polyline"]
        if not isinstance(raw, (list, tuple)):
            raise TypeError(f"polyline for {edge_id} is not a sequence")
        polyline = tuple((float(point[0]), float(point[1])) for point in raw)
        if len(polyline) < 2:
            continue
        candidate = SegmentGeometry(
            physical_edge_id=edge_id,
            polyline=polyline,
            highway=str(edge.get("highway") or ""),
            name=str(edge.get("name") or ""),
        )
        current = grouped.get(edge_id)
        if current is None or _polyline_rank(candidate) > _polyline_rank(current):
            grouped[edge_id] = candidate
    return [grouped[edge_id] for edge_id in sorted(grouped)]


def match_sites(
    sites: Sequence[CountSite],
    segments: Sequence[SegmentGeometry],
    *,
    max_distance_m: float,
    ambiguity_gap_m: float,
) -> list[SiteMatch]:
    """Snap each site to an eligible segment, or mark it unmatched or ambiguous.

    A site is ambiguous when two segments are both inside ``max_distance_m`` and
    less than ``ambiguity_gap_m`` apart in distance. Ambiguous sites are not
    assigned an edge.
    """
    if max_distance_m <= 0 or ambiguity_gap_m < 0:
        raise ValueError("distance thresholds must be positive")
    names = {segment.physical_edge_id: segment.name for segment in segments}
    matches: list[SiteMatch] = []
    for site in sites:
        ranked = sorted(
            (
                (
                    distance_to_polyline_m(site.longitude, site.latitude, segment.polyline),
                    segment.physical_edge_id,
                )
                for segment in segments
            ),
            key=lambda item: (item[0], item[1]),
        )
        matches.append(_classify_match(site, ranked, names, max_distance_m, ambiguity_gap_m))
    return matches


def collapse_duplicate_edges(matches: Sequence[SiteMatch]) -> list[SiteMatch]:
    """Keep one accepted site per physical edge: latest year, then latest date."""
    groups: dict[str, list[SiteMatch]] = {}
    passthrough: list[SiteMatch] = []
    for match in matches:
        if match.status != "matched" or not match.physical_edge_id:
            passthrough.append(match)
            continue
        groups.setdefault(match.physical_edge_id, []).append(match)
    collapsed: list[SiteMatch] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda match: _site_rank(match.site))
        collapsed.append(ordered[-1])
        collapsed.extend(
            replace(match, status="collapsed_duplicate_edge", physical_edge_id=None)
            for match in ordered[:-1]
        )
    return passthrough + collapsed


def modeled_traversal_counts(routes: Sequence[RouteRecord], *, scenario: str, split: str) -> dict[str, int]:
    """Count modeled routes in one split that traverse each physical edge once."""
    counts: dict[str, int] = {}
    for record in routes:
        if record.scenario != scenario or record.split != split:
            continue
        for edge_id in record.physical_edge_ids:
            counts[edge_id] = counts.get(edge_id, 0) + 1
    return counts


def spearman_rho(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation with average ranks for ties. Undefined if either side is constant."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("spearman_rho needs two equal columns of length at least 2")
    rank_x = _average_ranks(xs)
    rank_y = _average_ranks(ys)
    return _pearson(rank_x, rank_y)


def permutation_pvalue(
    xs: Sequence[float],
    ys: Sequence[float],
    observed: float,
    *,
    draws: int,
    seed: int,
) -> float:
    """Two-sided permutation p-value, with the +1 correction."""
    if draws < 1:
        raise ValueError("permutation draws must be positive")
    pooled = list(ys)
    generator = random.Random(seed)
    extreme = 0
    threshold = abs(observed) - 1e-12
    for _ in range(draws):
        generator.shuffle(pooled)
        rho = spearman_rho(xs, pooled)
        if rho is not None and abs(rho) + 1e-12 >= threshold:
            extreme += 1
    return (1 + extreme) / (draws + 1)


def top_quartile_overlap(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Share of the top quarter of ``xs`` that is also in the top quarter of ``ys``."""
    n_pairs = len(xs)
    if n_pairs != len(ys) or n_pairs < 4:
        return None
    quartile = max(1, n_pairs // 4)
    return len(_top_indices(xs, quartile) & _top_indices(ys, quartile)) / quartile


def additional_counters(
    routes: Mapping[str, Iterable[str]],
    existing_edges: Iterable[str],
    eligible_edges: Iterable[str],
    budget: int,
    weights: Mapping[str, float] | None = None,
) -> tuple[str, ...]:
    """Greedy edges that add modeled-route coverage beyond ``existing_edges``.

    Selection uses only routes the existing set does not already intercept.
    The existing edges are not eligible to be chosen again.
    """
    if budget <= 0:
        return ()
    installed = set(existing_edges)
    residual = {
        route_id: set(edges)
        for route_id, edges in routes.items()
        if not set(edges) & installed
    }
    if not residual:
        return ()
    result = greedy_max_coverage(
        residual,
        budget,
        eligible_edges=set(eligible_edges) - installed,
        weights=weights,
    )
    return result.selected_edges


def evaluate_extension(
    sites: Sequence[CountSite],
    segments: Sequence[SegmentGeometry],
    routes: Sequence[RouteRecord],
    *,
    bbox: tuple[float, float, float, float],
    anchor: tuple[float, float],
    anchor_name: str,
    min_year: int = PRIMARY_MIN_YEAR,
    max_distance_m: float = MAX_SNAP_DISTANCE_M,
    ambiguity_gap_m: float = AMBIGUITY_GAP_M,
    budgets: Sequence[int] = (5, 10, 20),
    permutations: int = 2000,
    seed: int = 42,
) -> dict[str, object]:
    """Run the pre-specified samples, rank comparisons, and complementary placement.

    The primary sample is recurring counting places whose street name agrees with
    the matched OpenStreetMap segment. Geometric matches without that agreement
    are reported separately and are not treated as verified existing counters.
    """
    recurring = select_sites(
        sites, bbox=bbox, count_types=RECURRING_COUNT_TYPES, min_year=min_year
    )
    broader = select_sites(
        sites, bbox=bbox, count_types=SENSITIVITY_COUNT_TYPES, min_year=min_year
    )
    recurring_matches = collapse_duplicate_edges(
        match_sites(
            recurring,
            segments,
            max_distance_m=max_distance_m,
            ambiguity_gap_m=ambiguity_gap_m,
        )
    )
    broader_matches = collapse_duplicate_edges(
        match_sites(
            broader,
            segments,
            max_distance_m=max_distance_m,
            ambiguity_gap_m=ambiguity_gap_m,
        )
    )
    samples = {
        PRIMARY_SAMPLE: _sample_payload(recurring_matches, routes, anchor, name_status="agree"),
        GEOMETRY_SAMPLE: _sample_payload(recurring_matches, routes, anchor, name_status=None),
        SENSITIVITY_SAMPLE: _sample_payload(broader_matches, routes, anchor, name_status=None),
    }
    for offset, sample in enumerate(samples.values()):
        sample["rank_tests"] = _rank_tests(
            sample["alignment_rows"],
            permutations=permutations,
            seed=seed + offset,
        )
    primary_edges = [row["physical_edge_id"] for row in samples[PRIMARY_SAMPLE]["alignment_rows"]]
    eligible = [segment.physical_edge_id for segment in segments]
    coverage = _coverage_by_scenario(routes, primary_edges, eligible, budgets)
    primary_tests = samples[PRIMARY_SAMPLE]["rank_tests"]
    return {
        "filters": {
            "bbox_west_south_east_north": list(bbox),
            "min_year": min_year,
            "max_snap_distance_m": max_distance_m,
            "ambiguity_gap_m": ambiguity_gap_m,
            "anchor_name": anchor_name,
            "anchor_lon_lat": list(anchor),
            "recurring_count_types": sorted(RECURRING_COUNT_TYPES),
            "excluded_from_primary": [
                "Krydstællinger",
                "Øvrige tællinger",
                "sites farther than the snap distance",
                "ambiguous snaps",
                "snaps whose street name does not agree",
            ],
            "aadt_definition": AADT_DEFINITION,
            "correlation_minimum_pairs": MIN_PAIRS_FOR_CORRELATION,
            "permutations": permutations,
            "seed": seed,
        },
        "samples": samples,
        "coverage": coverage,
        "interpretation": _interpretation(samples[PRIMARY_SAMPLE], primary_tests),
    }


def match_record(match: SiteMatch) -> dict[str, object]:
    """Flat row for the match table."""
    site = match.site
    return {
        "place_id": site.place_id,
        "street": site.street,
        "description": site.description,
        "count_type": site.count_type,
        "year": site.year,
        "count_date": site.count_date,
        "bike_aadt": site.bike_aadt,
        "longitude": site.longitude,
        "latitude": site.latitude,
        "status": match.status,
        "nearest_edge_id": match.nearest_edge_id,
        "distance_m": None if match.distance_m is None else round(match.distance_m, 2),
        "second_edge_id": match.second_edge_id,
        "second_distance_m": None
        if match.second_distance_m is None
        else round(match.second_distance_m, 2),
        "physical_edge_id": match.physical_edge_id,
        "osm_name": match.osm_name,
        "name_status": match.name_status,
    }


def _sample_payload(
    matches: Sequence[SiteMatch],
    routes: Sequence[RouteRecord],
    anchor: tuple[float, float],
    *,
    name_status: str | None,
) -> dict[str, object]:
    accepted = [
        match
        for match in matches
        if match.status == "matched"
        and match.physical_edge_id
        and (name_status is None or match.name_status == name_status)
    ]
    scenarios = _scenario_names(routes)
    rows: list[dict[str, object]] = []
    for match in sorted(accepted, key=lambda item: item.physical_edge_id or ""):
        site = match.site
        row: dict[str, object] = {
            "place_id": site.place_id,
            "street": site.street,
            "description": site.description,
            "count_type": site.count_type,
            "year": site.year,
            "bike_aadt": site.bike_aadt,
            "longitude": site.longitude,
            "latitude": site.latitude,
            "physical_edge_id": match.physical_edge_id,
            "distance_m": None if match.distance_m is None else round(match.distance_m, 2),
            "osm_name": match.osm_name,
            "name_status": match.name_status,
            "distance_to_anchor_m": round(
                distance_between_m(site.longitude, site.latitude, anchor[0], anchor[1]),
                1,
            ),
        }
        for scenario in scenarios:
            counts = modeled_traversal_counts(routes, scenario=scenario, split="calibration")
            row[f"{scenario}_calibration_traversals"] = counts.get(match.physical_edge_id or "", 0)
        rows.append(row)
    distances = [match.distance_m for match in accepted if match.distance_m is not None]
    return {
        "n_input_sites": len({match.site.place_id for match in matches}),
        "status_counts": _status_counts(matches),
        "n_analysis_edges": len(rows),
        "median_snap_distance_m": None if not distances else round(float(median(distances)), 2),
        "name_counts": _name_counts(matches),
        "alignment_rows": rows,
        "match_rows": [match_record(match) for match in matches],
    }


def _rank_tests(
    rows: Sequence[Mapping[str, object]],
    *,
    permutations: int,
    seed: int,
) -> list[dict[str, object]]:
    if len(rows) < 2:
        return []
    aadt = [float(row["bike_aadt"]) for row in rows]
    distance = [float(row["distance_to_anchor_m"]) for row in rows]
    tests = [
        _one_test(
            "bike_aadt_vs_distance_to_anchor",
            aadt,
            distance,
            permutations=permutations,
            seed=seed,
            scenario=None,
        )
    ]
    scenarios = []
    for key in rows[0]:
        if key.endswith("_calibration_traversals"):
            scenarios.append(key.removesuffix("_calibration_traversals"))
    for index, scenario in enumerate(scenarios):
        column = f"{scenario}_calibration_traversals"
        traversals = [float(row[column]) for row in rows]
        tests.append(
            _one_test(
                "modeled_traversals_vs_bike_aadt",
                traversals,
                aadt,
                permutations=permutations,
                seed=seed + 1 + index,
                scenario=scenario,
            )
        )
        tests.append(
            _one_test(
                "modeled_traversals_vs_distance_to_anchor",
                traversals,
                distance,
                permutations=permutations,
                seed=seed + 100 + index,
                scenario=scenario,
            )
        )
    return tests


def _one_test(
    comparison: str,
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    permutations: int,
    seed: int,
    scenario: str | None,
) -> dict[str, object]:
    rho = spearman_rho(xs, ys) if len(xs) >= 2 else None
    p_value = None if rho is None else permutation_pvalue(xs, ys, rho, draws=permutations, seed=seed)
    overlap = top_quartile_overlap(xs, ys)
    return {
        "comparison": comparison,
        "scenario": scenario,
        "n": len(xs),
        "spearman_rho": None if rho is None else round(rho, 4),
        "permutation_p": None if p_value is None else round(p_value, 4),
        "top_quartile_overlap": None if overlap is None else round(overlap, 4),
        "interpretable": rho is not None and len(xs) >= MIN_PAIRS_FOR_CORRELATION,
    }


def _coverage_by_scenario(
    routes: Sequence[RouteRecord],
    existing_edges: Sequence[str],
    eligible_edges: Sequence[str],
    budgets: Sequence[int],
) -> list[dict[str, object]]:
    installed = tuple(sorted(set(existing_edges), key=repr))
    results = []
    for scenario in _scenario_names(routes):
        calibration = _route_map(routes, scenario, "calibration")
        evaluation = _route_map(routes, scenario, "evaluation")
        if not calibration or not evaluation:
            continue
        same_size = greedy_max_coverage(calibration, len(installed), eligible_edges=eligible_edges)
        existing_eval = evaluate_coverage(evaluation, installed)
        existing_cal = evaluate_coverage(calibration, installed)
        same_eval = evaluate_coverage(evaluation, same_size.selected_edges)
        same_cal = evaluate_coverage(calibration, same_size.selected_edges)
        budget_rows = []
        for budget in budgets:
            added = additional_counters(calibration, installed, eligible_edges, budget)
            expanded_eval = evaluate_coverage(evaluation, list(installed) + list(added))
            expanded_cal = evaluate_coverage(calibration, list(installed) + list(added))
            scratch = greedy_max_coverage(calibration, budget, eligible_edges=eligible_edges)
            scratch_eval = evaluate_coverage(evaluation, scratch.selected_edges)
            scratch_cal = evaluate_coverage(calibration, scratch.selected_edges)
            budget_rows.append(
                {
                    "budget_new": budget,
                    "added_edges": list(added),
                    "n_added": len(added),
                    "held_out_existing_plus_new": round(expanded_eval.coverage_fraction, 4),
                    "calibration_existing_plus_new": round(expanded_cal.coverage_fraction, 4),
                    "held_out_marginal_gain": round(
                        expanded_eval.coverage_fraction - existing_eval.coverage_fraction,
                        4,
                    ),
                    "held_out_greedy_new_only": round(scratch_eval.coverage_fraction, 4),
                    "calibration_greedy_new_only": round(scratch_cal.coverage_fraction, 4),
                }
            )
        results.append(
            {
                "scenario": scenario,
                "n_routes_calibration": len(calibration),
                "n_routes_evaluation": len(evaluation),
                "n_existing": len(installed),
                "existing_edges": list(installed),
                "held_out_existing_coverage": round(existing_eval.coverage_fraction, 4),
                "calibration_existing_coverage": round(existing_cal.coverage_fraction, 4),
                "same_size_greedy_edges": list(same_size.selected_edges),
                "held_out_same_size_greedy_coverage": round(same_eval.coverage_fraction, 4),
                "calibration_same_size_greedy_coverage": round(same_cal.coverage_fraction, 4),
                "edge_jaccard_existing_vs_same_size_greedy": _jaccard(installed, same_size.selected_edges),
                "budgets": budget_rows,
            }
        )
    return results


def _interpretation(sample: Mapping[str, object], tests: Sequence[Mapping[str, object]]) -> dict[str, object]:
    usable = [
        test
        for test in tests
        if test["comparison"] == "modeled_traversals_vs_bike_aadt" and test["interpretable"]
    ]
    return {
        "primary_sample": PRIMARY_SAMPLE,
        "n_primary_edges": sample["n_analysis_edges"],
        "rank_correlation_reported": bool(usable),
        "reason": (
            "At least 8 name-agreeing recurring sites support a descriptive Spearman comparison."
            if usable
            else (
                "Fewer than 8 name-agreeing recurring sites. "
                "Do not interpret a rank correlation as evidence about the simulator."
            )
        ),
    }


def _classify_match(
    site: CountSite,
    ranked: list[tuple[float, str]],
    names: Mapping[str, str],
    max_distance_m: float,
    ambiguity_gap_m: float,
) -> SiteMatch:
    if not ranked:
        return _empty_match(site, "unmatched")
    best_distance, best_edge = ranked[0]
    second_edge = ranked[1][1] if len(ranked) > 1 else None
    second_distance = ranked[1][0] if len(ranked) > 1 else None
    ambiguous = (
        second_distance is not None
        and best_distance <= max_distance_m
        and second_distance <= max_distance_m
        and (second_distance - best_distance) < ambiguity_gap_m
    )
    if best_distance > max_distance_m:
        status = "unmatched"
        accepted = None
        osm_name = ""
        name_status = "not_applicable"
    elif ambiguous:
        status = "ambiguous"
        accepted = None
        osm_name = names.get(best_edge, "")
        name_status = _name_status(site.street, osm_name)
    else:
        status = "matched"
        accepted = best_edge
        osm_name = names.get(best_edge, "")
        name_status = _name_status(site.street, osm_name)
    return SiteMatch(
        site=site,
        status=status,
        nearest_edge_id=best_edge,
        distance_m=best_distance,
        second_edge_id=second_edge,
        second_distance_m=second_distance,
        physical_edge_id=accepted,
        osm_name=osm_name,
        name_status=name_status,
    )


def _empty_match(site: CountSite, status: str) -> SiteMatch:
    return SiteMatch(
        site=site,
        status=status,
        nearest_edge_id=None,
        distance_m=None,
        second_edge_id=None,
        second_distance_m=None,
        physical_edge_id=None,
        osm_name="",
        name_status="not_applicable",
    )


def _name_status(municipal: str, osm: str) -> str:
    if not osm.strip():
        return "unknown"
    if street_names_agree(municipal, osm):
        return "agree"
    return "disagree"


def _one_name_agrees(left: str, right: str) -> bool:
    compact_left = _compact(left)
    compact_right = _compact(right)
    if not compact_left or not compact_right:
        return False
    if min(len(compact_left), len(compact_right)) < MIN_NAME_COMPACT_LENGTH:
        return compact_left == compact_right
    return compact_left in compact_right or compact_right in compact_left


def _compact(name: str) -> str:
    return "".join(character for character in name.casefold() if character.isalnum())


def _xy(longitude: float, latitude: float, origin_latitude: float) -> tuple[float, float]:
    scale = 111_320.0 * math.cos(math.radians(origin_latitude))
    return longitude * scale, latitude * 110_540.0


def _segment_distance(
    point_x: float,
    point_y: float,
    start: tuple[float, float],
    end: tuple[float, float],
    origin_latitude: float,
) -> float:
    start_x, start_y = _xy(start[0], start[1], origin_latitude)
    end_x, end_y = _xy(end[0], end[1], origin_latitude)
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length_sq = delta_x * delta_x + delta_y * delta_y
    if length_sq == 0:
        return math.hypot(point_x - start_x, point_y - start_y)
    step = ((point_x - start_x) * delta_x + (point_y - start_y) * delta_y) / length_sq
    step = max(0.0, min(1.0, step))
    return math.hypot(point_x - (start_x + step * delta_x), point_y - (start_y + step * delta_y))


def _polyline_rank(segment: SegmentGeometry) -> tuple[int, float]:
    length = 0.0
    points = segment.polyline
    for start, end in pairwise(points):
        length += distance_between_m(start[0], start[1], end[0], end[1])
    return len(points), length


def _average_ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(order):
        end = cursor
        while end + 1 < len(order) and values[order[end + 1]] == values[order[cursor]]:
            end += 1
        average = (cursor + 1 + end + 1) / 2
        for position in range(cursor, end + 1):
            ranks[order[position]] = average
        cursor = end + 1
    return ranks


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n_pairs = len(xs)
    mean_x = sum(xs) / n_pairs
    mean_y = sum(ys) / n_pairs
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    scale_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    scale_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if scale_x == 0 or scale_y == 0:
        return None
    return covariance / (scale_x * scale_y)


def _top_indices(values: Sequence[float], count: int) -> set[int]:
    order = sorted(range(len(values)), key=lambda index: (-values[index], index))
    return set(order[:count])


def _jaccard(left: Iterable[str], right: Iterable[str]) -> float | None:
    first, second = set(left), set(right)
    if not first and not second:
        return None
    return round(len(first & second) / len(first | second), 4)


def _route_map(routes: Sequence[RouteRecord], scenario: str, split: str) -> dict[str, set[str]]:
    return {
        record.route_id: set(record.physical_edge_ids)
        for record in routes
        if record.scenario == scenario and record.split == split
    }


def _scenario_names(routes: Sequence[RouteRecord]) -> list[str]:
    names: list[str] = []
    for record in routes:
        if record.scenario not in names:
            names.append(record.scenario)
    return names


def _status_counts(matches: Sequence[SiteMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.status] = counts.get(match.status, 0) + 1
    return counts


def _name_counts(matches: Sequence[SiteMatch]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        if match.status != "matched":
            continue
        counts[match.name_status] = counts.get(match.name_status, 0) + 1
    return counts


def _site_rank(site: CountSite) -> tuple[int, int, str]:
    return site.year, site.count_date, site.source_row_id


def _parse_year(value: str) -> int | None:
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 4:
        return None
    return int(digits[:4])


def _parse_date(value: str) -> int:
    digits = "".join(character for character in (value or "") if character.isdigit())
    return int(digits) if digits else 0
