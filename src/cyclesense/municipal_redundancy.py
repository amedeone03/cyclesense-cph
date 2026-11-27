"""Attribution of modeled-route coverage across a fixed set of counting sites.

A route is covered once when it traverses any selected physical segment.
Leave-one-out contribution is the coverage that disappears when one site is
removed. Shapley attribution divides each covered route evenly across the
sites that traverse it. Neither quantity is observed traffic, and neither
is a reason to remove a municipal counting site.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from itertools import permutations

from cyclesense.coverage import evaluate_coverage

RouteId = str
Edge = str


def attribute_sites(
    routes: Mapping[RouteId, Iterable[Edge]],
    sites: Sequence[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> dict[str, object]:
    """Per-site traversal, unique coverage, leave-one-out, and exact Shapley."""
    prepared, site_ids, total = _prepare(routes, sites, weights)
    coverage = _covered_weight(prepared, None) / total
    reference = evaluate_coverage(routes, site_ids, weights).coverage_fraction
    if abs(coverage - reference) > 1e-9:
        raise RuntimeError("attribution coverage differs from evaluate_coverage")
    shapley = {site: 0.0 for site in site_ids}
    unique_weight = {site: 0.0 for site in site_ids}
    unique_routes = {site: 0 for site in site_ids}
    shared = {site: 0 for site in site_ids}
    traversal_weight = {site: 0.0 for site in site_ids}
    traversal_routes = {site: 0 for site in site_ids}
    partners: dict[Edge, set[Edge]] = {site: set() for site in site_ids}
    histogram: Counter[int] = Counter()
    for _route_id, weight, hits in prepared:
        histogram[len(hits)] += 1
        if not hits:
            continue
        share = weight / len(hits)
        for site in hits:
            shapley[site] += share
            traversal_weight[site] += weight
            traversal_routes[site] += 1
            if len(hits) == 1:
                unique_weight[site] += weight
                unique_routes[site] += 1
            else:
                shared[site] += 1
                partners[site].update(hit for hit in hits if hit != site)
    rows = []
    for site in site_ids:
        unique_fraction = unique_weight[site] / total
        leave = coverage - (_covered_weight(prepared, site) / total)
        if abs(unique_fraction - leave) > 1e-9:
            raise RuntimeError(f"unique coverage and leave-one-out differ for {site}")
        rows.append(
            {
                "physical_edge_id": site,
                "traversal_routes": traversal_routes[site],
                "traversal_fraction": traversal_weight[site] / total,
                "unique_routes": unique_routes[site],
                "unique_fraction": unique_fraction,
                "leave_one_out": leave,
                "leave_one_out_pp": leave * 100,
                "shared_routes": shared[site],
                "n_cotraversed_sites": len(partners[site]),
                "shapley": shapley[site] / total,
                "shapley_pp": shapley[site] / total * 100,
            }
        )
    shapley_total = sum(row["shapley"] for row in rows)
    if abs(shapley_total - coverage) > 1e-9:
        raise RuntimeError("Shapley contributions do not sum to coverage")
    return {
        "n_routes": len(prepared),
        "total_weight": total,
        "coverage": coverage,
        "n_uncovered": histogram[0],
        "n_exactly_one": histogram[1],
        "n_two_or_more": sum(count for size, count in histogram.items() if size >= 2),
        "multiplicity": dict(sorted(histogram.items())),
        "sites": rows,
        "shapley_total": shapley_total,
    }


def brute_force_shapley(
    routes: Mapping[RouteId, Iterable[Edge]],
    sites: Sequence[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> dict[Edge, float]:
    """Average marginal coverage over every site order. Only for tiny tests."""
    prepared, site_ids, total = _prepare(routes, sites, weights)
    if len(site_ids) > 7:
        raise ValueError("brute-force Shapley is limited to 7 sites")
    accumulated = {site: 0.0 for site in site_ids}
    n_orders = 0
    for order in permutations(site_ids):
        n_orders += 1
        chosen: set[Edge] = set()
        previous = 0.0
        for site in order:
            chosen.add(site)
            covered = sum(weight for _route_id, weight, hits in prepared if hits & chosen)
            accumulated[site] += covered - previous
            previous = covered
    return {site: (accumulated[site] / n_orders) / total for site in site_ids}


def pairwise_overlap(
    routes: Mapping[RouteId, Iterable[Edge]],
    sites: Sequence[Edge],
) -> list[dict[str, object]]:
    """Route-incidence overlap for each unordered pair. This is not geometry overlap."""
    prepared, site_ids, _total = _prepare(routes, sites, None)
    incidence = {site: set() for site in site_ids}
    for index, (_route_id, _weight, hits) in enumerate(prepared):
        for site in hits:
            incidence[site].add(index)
    rows = []
    for left_index, left in enumerate(site_ids):
        for right in site_ids[left_index + 1 :]:
            both = incidence[left] & incidence[right]
            either = incidence[left] | incidence[right]
            rows.append(
                {
                    "site_a": left,
                    "site_b": right,
                    "n_both": len(both),
                    "n_either": len(either),
                    "n_only_a": len(incidence[left] - incidence[right]),
                    "n_only_b": len(incidence[right] - incidence[left]),
                    "jaccard": (len(both) / len(either)) if either else None,
                    "conditional_a": (len(both) / len(incidence[left])) if incidence[left] else None,
                    "conditional_b": (len(both) / len(incidence[right])) if incidence[right] else None,
                }
            )
    return rows


def validate_additions(existing: Sequence[Edge], additions: Sequence[Edge]) -> None:
    """The published sites stay fixed and every addition is a new physical id."""
    if len(existing) != len(set(existing)):
        raise ValueError("the municipal sites contain a duplicate physical id")
    if len(additions) != len(set(additions)):
        raise ValueError("the additions contain a duplicate physical id")
    overlap = set(existing) & set(additions)
    if overlap:
        raise ValueError(f"an addition repeats a municipal site: {sorted(overlap)[:3]}")


def cumulative_coverage(
    routes: Mapping[RouteId, Iterable[Edge]],
    existing: Sequence[Edge],
    ordered_additions: Sequence[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> list[dict[str, object]]:
    """Coverage after each addition, in the saved selection order."""
    validate_additions(existing, ordered_additions)
    chosen = list(existing)
    previous = evaluate_coverage(routes, chosen, weights).coverage_fraction
    rows = [{"step": 0, "physical_edge_id": "", "coverage": previous, "gain": 0.0}]
    for step, edge in enumerate(ordered_additions, start=1):
        chosen.append(edge)
        coverage = evaluate_coverage(routes, chosen, weights).coverage_fraction
        if coverage + 1e-12 < previous:
            raise RuntimeError("cumulative coverage decreased")
        rows.append(
            {
                "step": step,
                "physical_edge_id": edge,
                "coverage": coverage,
                "gain": coverage - previous,
            }
        )
        previous = coverage
    return rows


def incremental_shapley(
    routes: Mapping[RouteId, Iterable[Edge]],
    existing: Sequence[Edge],
    additions: Sequence[Edge],
    weights: Mapping[RouteId, float] | None = None,
) -> dict[Edge, float]:
    """Exact Shapley shares of the coverage the additions add beyond the fixed sites.

    Routes already covered by the fixed sites receive no credit. The order of
    ``additions`` is ignored.
    """
    validate_additions(existing, additions)
    prepared, _sites, total = _prepare(routes, list(existing) + list(additions), weights)
    installed = set(existing)
    added = tuple(additions)
    credit = {edge: 0.0 for edge in added}
    for _route_id, weight, hits in prepared:
        if hits & installed:
            continue
        fresh = [edge for edge in added if edge in hits]
        if not fresh:
            continue
        share = weight / len(fresh)
        for edge in fresh:
            credit[edge] += share
    return {edge: credit[edge] / total for edge in added}


def complement_counts(
    routes: Mapping[RouteId, Iterable[Edge]],
    existing: Sequence[Edge],
    additions: Sequence[Edge],
) -> dict[str, int]:
    """How many uncovered routes the additions reach, and which additions also sit on covered routes."""
    validate_additions(existing, additions)
    installed = set(existing)
    added = tuple(additions)
    newly_covered = 0
    overlapping_sites = 0
    touched_covered = {edge: False for edge in added}
    for edges in routes.values():
        edge_set = set(edges)
        if edge_set & installed:
            for edge in added:
                if edge in edge_set:
                    touched_covered[edge] = True
        elif any(edge in edge_set for edge in added):
            newly_covered += 1
    overlapping_sites = sum(touched_covered.values())
    return {
        "n_newly_covered_routes": newly_covered,
        "n_additions_on_already_covered_routes": overlapping_sites,
    }


def _prepare(routes, sites, weights):
    site_ids = tuple(sites)
    if not site_ids:
        raise ValueError("coverage attribution needs at least one site")
    if len(site_ids) != len(set(site_ids)):
        raise ValueError("coverage attribution received duplicate site ids")
    if not routes:
        raise ValueError("coverage attribution needs at least one route")
    if weights is None:
        weights = {route_id: 1.0 for route_id in routes}
    missing = set(routes) - set(weights)
    if missing:
        raise ValueError("every route needs a weight")
    site_set = set(site_ids)
    prepared = []
    total = 0.0
    for route_id, edges in routes.items():
        weight = float(weights[route_id])
        if weight < 0:
            raise ValueError("route weights must be nonnegative")
        total += weight
        prepared.append((route_id, weight, frozenset(edge for edge in set(edges) if edge in site_set)))
    if total <= 0:
        raise ValueError("route weights sum to zero")
    return prepared, site_ids, total


def _covered_weight(prepared, excluded: str | None) -> float:
    covered = 0.0
    for _route_id, weight, hits in prepared:
        if excluded is None:
            active = hits
        else:
            active = hits - {excluded}
        if active:
            covered += weight
    return covered

