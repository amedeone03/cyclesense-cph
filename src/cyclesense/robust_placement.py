"""Route-choice-aware counter placement on simulated calibration routes.

The objective is expected modeled-route coverage. A route realization is
covered when its eligible physical-edge set meets the selected counters.
Weights are nonnegative and sum to one. The selector is the existing
weighted greedy in ``placement.select_greedy``. This is not a worst-case
optimizer, and the routes are not observed cyclist trips.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from cyclesense.coverage import evaluate_coverage
from cyclesense.placement import assert_selection, select_greedy


def require_calibration(rows: Sequence[Mapping[str, str]]) -> None:
    """Reject a training table that contains a held-out route."""
    if not rows:
        raise ValueError("training routes are empty")
    found = {row["split"] for row in rows}
    if found != {"calibration"}:
        raise ValueError(f"robust training must use calibration routes only, found {sorted(found)}")


def assert_disjoint_seeds(*blocks: Sequence[int]) -> None:
    """Training and evaluation draws must not share a seed."""
    seen: set[int] = set()
    for block in blocks:
        ids = {int(seed) for seed in block}
        if len(ids) != len(list(block)):
            raise ValueError("a seed block contains a duplicate")
        overlap = seen & ids
        if overlap:
            raise ValueError(f"seed ranges overlap at {sorted(overlap)}")
        seen |= ids


def assign_weights(
    records: Sequence[Mapping[str, Any]],
    *,
    scenarios: Sequence[str],
    include_alternatives: bool,
) -> dict[str, float]:
    """Give every scenario the same total weight, and every OD the same weight inside its pool.

    With alternatives, half of a scenario's weight sits on the shortest paths
    and half on the alternative realizations. Extra realizations of one OD
    split that OD's share. They do not increase it. Without alternatives,
    the whole scenario weight sits on the shortest paths.
    """
    scenario_names = tuple(scenarios)
    if not scenario_names or len(set(scenario_names)) != len(scenario_names):
        raise ValueError("scenarios must be a non-empty list of unique names")
    alpha = 1.0 / len(scenario_names)
    grouped: dict[str, list[Mapping[str, Any]]] = {name: [] for name in scenario_names}
    for record in records:
        scenario = str(record["scenario"])
        if scenario not in grouped:
            raise ValueError(f"unexpected scenario {scenario}")
        grouped[scenario].append(record)
    weights: dict[str, float] = {}
    for scenario in scenario_names:
        rows = grouped[scenario]
        shortest = [row for row in rows if row["role"] == "shortest"]
        alternatives = [row for row in rows if row["role"] == "alternative"]
        other = [row for row in rows if row["role"] not in {"shortest", "alternative"}]
        if other:
            raise ValueError(f"unknown route role {other[0]['role']}")
        if not shortest:
            raise ValueError(f"{scenario} has no shortest calibration routes")
        od_ids = [str(row["od_id"]) for row in shortest]
        if len(od_ids) != len(set(od_ids)):
            raise ValueError(f"{scenario} has more than one shortest route for an OD")
        pool_count = 2 if include_alternatives else 1
        per_od = (alpha / pool_count) / len(od_ids)
        for row in shortest:
            _add_weight(weights, str(row["route_key"]), per_od)
        if not include_alternatives:
            if alternatives:
                raise ValueError("shortest-only weights were given alternative routes")
            continue
        by_od: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in alternatives:
            by_od[str(row["od_id"])].append(row)
        if set(by_od) != set(od_ids):
            raise ValueError(f"{scenario} alternative OD pairs do not match the shortest OD pairs")
        for od_id in od_ids:
            share = per_od / len(by_od[od_id])
            for row in by_od[od_id]:
                _add_weight(weights, str(row["route_key"]), share)
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-9:
        raise RuntimeError(f"route weights sum to {total}, not 1")
    return weights


def _add_weight(weights: dict[str, float], route_key: str, weight: float) -> None:
    if route_key in weights:
        raise ValueError(f"duplicate route key {route_key}")
    if weight < 0:
        raise ValueError(f"negative weight for {route_key}")
    weights[route_key] = weight


def select_weighted(
    eligible_ids: Iterable[str],
    routes: Mapping[str, Iterable[str]],
    weights: Mapping[str, float],
    k: int,
) -> tuple[str, ...]:
    """Existing weighted greedy, checked to be K distinct eligible ids."""
    eligible = sorted(set(eligible_ids))
    selected = tuple(str(edge) for edge in select_greedy(eligible, routes, k, weights))
    assert_selection(selected, eligible, k)
    return selected


def calibration_marginal_gains(
    routes: Mapping[str, Iterable[str]],
    weights: Mapping[str, float],
    selected: Sequence[str],
) -> list[dict[str, float | int | str]]:
    """Coverage added by each counter on the objective that was optimized.

    The gain is calibration weight newly covered, divided by the total
    training weight. It is not a held-out gain.
    """
    route_sets = {route_id: set(edges) for route_id, edges in routes.items()}
    total = sum(float(weights[route_id]) for route_id in route_sets)
    if total <= 0:
        raise ValueError("training weight must be positive")
    covered: set[str] = set()
    rows = []
    cumulative = 0.0
    for rank, edge in enumerate(selected, start=1):
        new_ids = [
            route_id
            for route_id, edges in route_sets.items()
            if route_id not in covered and edge in edges
        ]
        gain = sum(float(weights[route_id]) for route_id in new_ids) / total
        cumulative += gain
        covered.update(new_ids)
        by_scenario: dict[str, float] = defaultdict(float)
        for route_id in new_ids:
            by_scenario[_scenario_of(route_id)] += float(weights[route_id]) / total
        rows.append(
            {
                "rank": rank,
                "physical_edge_id": edge,
                "calibration_marginal_gain": gain,
                "cumulative_calibration_coverage": cumulative,
                "uniform_new_weight": by_scenario.get("uniform", 0.0),
                "commuter_new_weight": by_scenario.get("commuter_proxy", 0.0),
            }
        )
    scored = evaluate_coverage(route_sets, selected, weights)
    if abs(scored.coverage_fraction - cumulative) > 1e-9:
        raise RuntimeError("marginal gains do not add up to weighted coverage")
    return rows


def _scenario_of(route_key: str) -> str:
    if route_key.startswith("commuter_proxy:"):
        return "commuter_proxy"
    if route_key.startswith("uniform:"):
        return "uniform"
    raise ValueError(f"route key {route_key} has no scenario prefix")


def summarize_alternative(
    coverages: Sequence[float],
    shortest_coverage: float,
    changed_fractions: Sequence[float],
) -> dict[str, float | int]:
    """Mean, spread, and loss of one placement under seeded alternative routes.

    The minimum is the lowest draw in this sample. It is not a worst-case
    bound. Percentiles are empirical cut points of these seeds, not
    confidence intervals. The seeds share OD pairs.
    """
    from cyclesense.validation_stats import sample_summary

    values = [float(value) for value in coverages]
    fractions = [float(value) for value in changed_fractions]
    if len(values) < 2:
        raise ValueError("an alternative summary needs at least two seeds")
    if len(values) != len(fractions):
        raise ValueError("each seed needs a coverage and a changed-route fraction")
    summary = sample_summary(values)
    changed = sample_summary(fractions)
    differences = [value - shortest_coverage for value in values]
    return {
        "n_seeds": int(summary["n"]),
        "coverage_mean": float(summary["mean"]),
        "coverage_median": float(summary["p50"]),
        "coverage_std": float(summary["std"]),
        "coverage_p05": float(summary["p05"]),
        "coverage_p95": float(summary["p95"]),
        "coverage_min": float(summary["min"]),
        "shortest_coverage": float(shortest_coverage),
        "difference_mean": sum(differences) / len(differences),
        "loss_percentage_points": (float(shortest_coverage) - float(summary["mean"])) * 100.0,
        "fraction_changed_mean": float(changed["mean"]),
    }


def paired_comparison(
    left_by_seed: Mapping[int, float],
    right_by_seed: Mapping[int, float],
    *,
    shortest_left: float,
    shortest_right: float,
) -> dict[str, float | int | str]:
    """Paired seed comparison. ``left`` is the robust placement when that is the question."""
    if set(left_by_seed) != set(right_by_seed) or not left_by_seed:
        raise ValueError("paired methods need the same non-empty seed set")
    gaps = [left_by_seed[seed] - right_by_seed[seed] for seed in sorted(left_by_seed)]
    shortest_order = _order(shortest_left, shortest_right)
    reversals = 0
    left_better = 0
    for seed in sorted(left_by_seed):
        if left_by_seed[seed] > right_by_seed[seed]:
            left_better += 1
        if _order(left_by_seed[seed], right_by_seed[seed]) != shortest_order:
            reversals += 1
    return {
        "n_seeds": len(gaps),
        "mean_left_minus_right": sum(gaps) / len(gaps),
        "fraction_left_beats_right": left_better / len(gaps),
        "fraction_order_reversed": reversals / len(gaps),
        "shortest_order": shortest_order,
    }


def _order(left: float, right: float) -> str:
    if abs(left - right) <= 1e-12:
        return "tie"
    return "left_higher" if left > right else "right_higher"


def scenario_tradeoff(uniform_coverage: float, commuter_coverage: float) -> dict[str, float]:
    """Mean and minimum of the two scenario scores. The minimum is not a guarantee."""
    return {
        "uniform_coverage": float(uniform_coverage),
        "commuter_coverage": float(commuter_coverage),
        "mean_coverage": (float(uniform_coverage) + float(commuter_coverage)) / 2.0,
        "min_coverage": min(float(uniform_coverage), float(commuter_coverage)),
    }
