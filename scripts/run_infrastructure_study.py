"""Compare greedy and MILP placements under mapped-infrastructure policies.

The candidate rules use tags stored on the saved M1 graph. Selection uses
calibration routes only. Held-out routes are scored after the counters are chosen.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import osmnx as ox

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.coverage import evaluate_coverage
from cyclesense.exact_optimization import greedy_optimality_gap, solve_maximum_coverage
from cyclesense.external_validation import additional_counters
from cyclesense.infrastructure import (
    POLICIES,
    assert_selection_split,
    attribute_audit,
    classify_physical_edge,
    feasibility,
    permitted_ids,
    policy_summary,
)
from cyclesense.infrastructure_plots import (
    figure_availability,
    figure_classification,
    figure_coverage,
    figure_municipal,
    figure_placements,
)
from cyclesense.network import build_candidates
from cyclesense.placement import fill_to_k, select_greedy
from cyclesense.placement_stability import jaccard
from cyclesense.placement_stability_plots import physical_lines

OUTPUT = ROOT / "outputs" / "infrastructure"
BUDGETS = (5, 10, 20)
SCENARIOS = ("uniform", "commuter_proxy")


def main() -> None:
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit("Saved M1 artifacts are missing or failed validation. Run scripts/run_m1.py.")
    config = yaml.safe_load((ROOT / "configs/pilot.yaml").read_text(encoding="utf-8"))
    block = config["infrastructure"]
    graph = ox.load_graphml(paths["routing_wgs84"])
    candidates, _stats = build_candidates(graph, min_length_m=float(config["candidates"]["min_length_m"]))
    if len(candidates) != 1047:
        raise SystemExit(f"expected 1,047 eligible segments, found {len(candidates)}")
    classified = _classify(graph, candidates)
    names = {row["physical_edge_id"]: row["name"] for row in candidates}
    eligible = {row["physical_edge_id"] for row in candidates}
    routes = _routes(paths["routes"], eligible)
    permitted = {policy: permitted_ids(classified, policy) for policy in POLICIES}
    categories = {row["physical_edge_id"]: row["category"] for row in classified}
    placements, coverage_rows = _greedy(routes, permitted, categories, names)
    _match_m2(placements)
    milp_rows = _milp(routes, permitted, categories, block)
    municipal_edges, municipal_rows = _municipal(routes, permitted, categories, names, block)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    _write_classification(classified, names)
    _write_dicts("attribute_audit.csv", attribute_audit(classified))
    _write_dicts("candidate_policy_summary.csv", policy_summary(classified))
    _write_dicts("placements.csv", placements)
    _write_dicts("coverage_comparison.csv", coverage_rows)
    _write_dicts("constrained_milp.csv", milp_rows)
    _write_dicts("municipal_additions.csv", municipal_edges)
    summary = _summary(classified, permitted, coverage_rows, milp_rows, municipal_rows)
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    _figures(graph, categories, placements, coverage_rows, permitted, municipal_rows)
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


def _classify(graph, candidates: list[dict]) -> list[dict]:
    grouped: dict[str, list] = defaultdict(list)
    for _u, _v, _key, data in graph.edges(keys=True, data=True):
        grouped[str(data["physical_edge_id"])].append(data)
    rows = []
    for candidate in candidates:
        edge_id = candidate["physical_edge_id"]
        if edge_id not in grouped:
            raise RuntimeError(f"{edge_id} is eligible but has no saved graph edge")
        rows.append(classify_physical_edge(edge_id, grouped[edge_id]))
    if len({row["physical_edge_id"] for row in rows}) != 1047:
        raise RuntimeError("classification did not keep 1,047 distinct physical ids")
    return rows


def _routes(path: Path, eligible: set[str]) -> dict:
    stored: dict = defaultdict(lambda: defaultdict(dict))
    weights: dict = defaultdict(lambda: defaultdict(dict))
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            edges = {edge for edge in row["eligible_edge_ids"].split("|") if edge and edge in eligible}
            stored[row["scenario"]][row["split"]][row["route_id"]] = edges
            weights[row["scenario"]][row["split"]][row["route_id"]] = float(row["scenario_weight"])
    return {"edges": stored, "weights": weights}


def _greedy(routes, permitted, categories, names) -> tuple[list[dict], list[dict]]:
    placements: list[dict] = []
    coverage: list[dict] = []
    selected: dict[tuple, tuple[str, ...]] = {}
    for scenario in SCENARIOS:
        calibration = routes["edges"][scenario]["calibration"]
        weights = routes["weights"][scenario]["calibration"]
        heldout = routes["edges"][scenario]["evaluation"]
        assert_selection_split("calibration")
        for policy in POLICIES:
            allowed = permitted[policy]
            for budget in BUDGETS:
                status = feasibility(len(allowed), budget)
                chosen: tuple[str, ...] = ()
                if status == "feasible":
                    chosen = select_greedy(allowed, calibration, budget, weights)
                    if set(chosen) - set(allowed) or len(chosen) != budget:
                        raise RuntimeError(f"{policy} selected a segment outside its policy")
                selected[(scenario, policy, budget)] = chosen
                for rank, edge_id in enumerate(chosen, start=1):
                    placements.append(
                        {
                            "scenario": scenario,
                            "policy": policy,
                            "k": budget,
                            "status": status,
                            "n_permitted": len(allowed),
                            "rank": rank,
                            "physical_edge_id": edge_id,
                            "category": categories[edge_id],
                            "street_name": names.get(edge_id, ""),
                        }
                    )
                baseline = selected[(scenario, "unrestricted", budget)]
                coverage.append(
                    _coverage_row(
                        scenario, policy, budget, status, len(allowed), chosen, baseline, calibration, weights, heldout, categories
                    )
                )
    return placements, coverage


def _coverage_row(scenario, policy, budget, status, n_permitted, chosen, baseline, calibration, weights, heldout, categories):
    row = {
        "scenario": scenario,
        "policy": policy,
        "k": budget,
        "status": status,
        "n_permitted": n_permitted,
        "reduction_share": 1 - n_permitted / 1047,
        "calibration_coverage": "",
        "heldout_coverage": "",
        "calibration_difference_pp": "",
        "heldout_difference_pp": "",
        "n_shared_with_unrestricted": "",
        "jaccard_with_unrestricted": "",
        "n_dedicated": "",
        "n_explicit_facility": "",
        "n_other_routable": "",
        "n_unknown": "",
        "n_ambiguous": "",
    }
    if status != "feasible":
        return row
    calibration_coverage = evaluate_coverage(calibration, chosen, weights).coverage_fraction
    heldout_coverage = evaluate_coverage(heldout, chosen).coverage_fraction
    base_calibration = evaluate_coverage(calibration, baseline, weights).coverage_fraction
    base_heldout = evaluate_coverage(heldout, baseline).coverage_fraction
    counts = Counter(categories[edge_id] for edge_id in chosen)
    row.update(
        {
            "calibration_coverage": calibration_coverage,
            "heldout_coverage": heldout_coverage,
            "calibration_difference_pp": (calibration_coverage - base_calibration) * 100,
            "heldout_difference_pp": (heldout_coverage - base_heldout) * 100,
            "n_shared_with_unrestricted": len(set(chosen) & set(baseline)),
            "jaccard_with_unrestricted": jaccard(chosen, baseline),
            "n_dedicated": counts["dedicated"],
            "n_explicit_facility": counts["explicit_facility"],
            "n_other_routable": counts["other_routable"],
            "n_unknown": counts["unknown"],
            "n_ambiguous": counts["ambiguous"],
        }
    )
    return row


def _milp(routes, permitted, categories, block) -> list[dict]:
    rows = []
    limit = float(block["time_limit_seconds"])
    gap = float(block["mip_rel_gap"])
    for scenario in SCENARIOS:
        calibration = routes["edges"][scenario]["calibration"]
        weights = routes["weights"][scenario]["calibration"]
        heldout = routes["edges"][scenario]["evaluation"]
        assert_selection_split("calibration")
        unrestricted = select_greedy(permitted["unrestricted"], calibration, 10, weights)
        solved = {}
        for policy in POLICIES:
            allowed = permitted[policy]
            if feasibility(len(allowed), 10) != "feasible":
                rows.append({"scenario": scenario, "policy": policy, "k": 10, "status": "infeasible", "proven_optimal": False})
                continue
            result = solve_maximum_coverage(calibration, weights, allowed, 10, time_limit_seconds=limit, mip_rel_gap=gap)
            solved[policy] = result
            greedy = select_greedy(allowed, calibration, 10, weights)
            optimality = greedy_optimality_gap(
                float(result.coverage or 0.0),
                evaluate_coverage(calibration, greedy, weights).coverage_fraction,
                proven=result.proven_optimal,
            )
            rows.append(
                {
                    "scenario": scenario,
                    "policy": policy,
                    "k": 10,
                    "status": result.status,
                    "proven_optimal": result.proven_optimal,
                    "calibration_coverage": result.coverage,
                    "heldout_coverage": evaluate_coverage(heldout, result.selected).coverage_fraction,
                    "greedy_calibration": evaluate_coverage(calibration, greedy, weights).coverage_fraction,
                    "absolute_gap": optimality["absolute_gap"],
                    "relative_gap": optimality["relative_gap"],
                    "runtime_seconds": result.runtime_seconds,
                    "n_shared_with_policy_greedy": len(set(result.selected) & set(greedy)),
                    "jaccard_with_policy_greedy": jaccard(result.selected, greedy),
                    "n_shared_with_unrestricted_greedy": len(set(result.selected) & set(unrestricted)),
                    "jaccard_with_unrestricted_greedy": jaccard(result.selected, unrestricted),
                    "n_dedicated": Counter(categories[edge] for edge in result.selected)["dedicated"],
                    "n_explicit_facility": Counter(categories[edge] for edge in result.selected)["explicit_facility"],
                }
            )
        if "unrestricted" in solved and solved["unrestricted"].proven_optimal:
            for row in rows:
                if row["scenario"] != scenario or row.get("status") == "infeasible":
                    continue
                other = solved.get(row["policy"])
                if other is None or other.coverage is None:
                    continue
                row["unrestricted_milp_calibration"] = solved["unrestricted"].coverage
                row["calibration_difference_from_unrestricted_milp_pp"] = (
                    float(other.coverage) - float(solved["unrestricted"].coverage)
                ) * 100
    return rows


def _municipal(routes, permitted, categories, names, block):
    installed = _municipal_ids()
    eligible = {edge for ids in permitted.values() for edge in ids}
    missing = [edge for edge in installed if edge not in eligible]
    if missing:
        raise SystemExit(f"municipal segments are outside the eligible universe: {missing[:3]}")
    edges: list[dict] = []
    metrics: list[dict] = []
    limit = float(block["time_limit_seconds"])
    gap = float(block["mip_rel_gap"])
    for scenario in SCENARIOS:
        calibration = routes["edges"][scenario]["calibration"]
        weights = routes["weights"][scenario]["calibration"]
        assert_selection_split("calibration")
        existing_calibration = evaluate_coverage(calibration, installed, weights).coverage_fraction
        existing_uniform = evaluate_coverage(routes["edges"]["uniform"]["evaluation"], installed).coverage_fraction
        existing_commuter = evaluate_coverage(routes["edges"]["commuter_proxy"]["evaluation"], installed).coverage_fraction
        metrics.append(
            _municipal_metric(scenario, "existing", existing_calibration, existing_uniform, existing_commuter, existing_calibration, existing_uniform, ())
        )
        for policy in POLICIES:
            allowed = [edge for edge in permitted[policy] if edge not in installed]
            if feasibility(len(allowed), 5) != "feasible":
                metrics.append({"training_scenario": scenario, "policy": policy, "status": "infeasible"})
                continue
            added = fill_to_k(additional_counters(calibration, installed, allowed, 5, weights), allowed, 5)
            if set(added) & set(installed):
                raise RuntimeError("an addition repeats a municipal segment")
            full = list(installed) + list(added)
            calibration_coverage = evaluate_coverage(calibration, full, weights).coverage_fraction
            heldout_uniform = evaluate_coverage(routes["edges"]["uniform"]["evaluation"], full).coverage_fraction
            heldout_commuter = evaluate_coverage(routes["edges"]["commuter_proxy"]["evaluation"], full).coverage_fraction
            for rank, edge_id in enumerate(added, start=1):
                edges.append(
                    {
                        "training_scenario": scenario,
                        "policy": policy,
                        "method": "greedy",
                        "rank": rank,
                        "physical_edge_id": edge_id,
                        "category": categories[edge_id],
                        "street_name": names.get(edge_id, ""),
                    }
                )
            milp_status = ""
            proven = False
            residual = {
                route_id: edge_set
                for route_id, edge_set in calibration.items()
                if not edge_set & set(installed)
            }
            if residual:
                result = solve_maximum_coverage(
                    residual,
                    {route_id: weights[route_id] for route_id in residual},
                    allowed,
                    5,
                    time_limit_seconds=limit,
                    mip_rel_gap=gap,
                )
                milp_status = result.status
                proven = result.proven_optimal
                for rank, edge_id in enumerate(result.selected, start=1):
                    if edge_id in installed:
                        raise RuntimeError("MILP addition repeats a municipal segment")
                    edges.append(
                        {
                            "training_scenario": scenario,
                            "policy": policy,
                            "method": "milp",
                            "rank": rank,
                            "physical_edge_id": edge_id,
                            "category": categories[edge_id],
                            "street_name": names.get(edge_id, ""),
                            "proven_optimal": proven,
                        }
                    )
            metrics.append(
                _municipal_metric(
                    scenario,
                    policy,
                    calibration_coverage,
                    heldout_uniform,
                    heldout_commuter,
                    existing_calibration,
                    existing_uniform,
                    added,
                    milp_status,
                    proven,
                )
            )
    return edges, metrics


def _municipal_metric(scenario, policy, calibration, heldout_uniform, heldout_commuter, base_calibration, base_uniform, added, milp_status="", proven=False):
    return {
        "training_scenario": scenario,
        "policy": policy,
        "status": "feasible",
        "calibration_coverage": calibration,
        "heldout_uniform": heldout_uniform,
        "heldout_commuter": heldout_commuter,
        "calibration_gain_pp": (calibration - base_calibration) * 100,
        "heldout_uniform_gain_pp": (heldout_uniform - base_uniform) * 100,
        "n_added": len(added),
        "added": list(added),
        "milp_status": milp_status,
        "milp_proven_optimal": proven,
    }


def _municipal_ids() -> list[str]:
    path = ROOT / "outputs/standout/summary.json"
    if not path.is_file():
        raise SystemExit("Municipal alignment is missing. Run scripts/run_external_validation.py.")
    summary = json.loads(path.read_text(encoding="utf-8"))
    rows = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    edges = [row["physical_edge_id"] for row in rows if row.get("physical_edge_id")]
    if len(edges) != len(set(edges)) or len(edges) != 26:
        raise SystemExit(f"expected 26 distinct municipal segments, found {len(set(edges))}")
    return edges


def _match_m2(placements: list[dict]) -> None:
    path = ROOT / "outputs/m2/results.csv"
    if not path.is_file():
        raise SystemExit("M2 results are missing. Run scripts/run_m2.py.")
    saved = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "greedy" and row["seed"] == "" and int(row["k"]) in BUDGETS:
                saved[(row["scenario"], int(row["k"]))] = [edge for edge in row["selected_edges"].split("|") if edge]
    for scenario in SCENARIOS:
        for budget in BUDGETS:
            chosen = [
                row["physical_edge_id"]
                for row in placements
                if row["scenario"] == scenario and row["policy"] == "unrestricted" and int(row["k"]) == budget
            ]
            if set(chosen) != set(saved[(scenario, budget)]):
                raise SystemExit(f"unrestricted greedy does not reproduce M2 for {scenario} K={budget}")


def _summary(classified, permitted, coverage_rows, milp_rows, municipal_rows) -> dict:
    counts = Counter(row["category"] for row in classified)
    return {
        "routes_are_simulated": True,
        "held_out_used_for_selection": False,
        "tags_are_mapped_infrastructure": True,
        "missing_cycleway_tag_is_not_absence": True,
        "segregated_tag_in_saved_graph": False,
        "spacing_constraint": "not_implemented",
        "spacing_reason": (
            "A minimum separation needs pairwise geometry constraints during optimization. "
            "The validated maximum-coverage model does not contain that constraint, and midpoint "
            "distance would not measure separation of the street segments."
        ),
        "n_eligible_candidates": 1047,
        "category_counts": dict(counts),
        "policies": {policy: len(ids) for policy, ids in permitted.items()},
        "unrestricted_matches_m2": True,
        "coverage": coverage_rows,
        "milp": milp_rows,
        "municipal": [
            {key: value for key, value in row.items() if key != "added"} | {"added": row.get("added", [])}
            for row in municipal_rows
        ],
    }


def _figures(graph, categories, placements, coverage_rows, permitted, municipal_rows) -> None:
    lines = physical_lines(graph)
    streets = _streets()
    figure_classification(lines, categories, streets, OUTPUT / "figure1_classification.png")
    panels = []
    for scenario, title in (("uniform", "Uniform"), ("commuter_proxy", "Commuter proxy")):
        base = _ids(placements, scenario, "unrestricted", 10)
        for policy, label in (("explicit_facility", "explicit facilities"), ("dedicated", "dedicated cycleways")):
            panels.append((f"{title}, {label}", base, _ids(placements, scenario, policy, 10)))
    figure_placements(lines, panels, streets, OUTPUT / "figure2_k10_placement.png")
    figure_coverage(coverage_rows, OUTPUT / "figure3_coverage_by_budget.png")
    counts = Counter(categories.values())
    figure_availability(counts, policy_summary([{"physical_edge_id": edge, "category": category} for edge, category in categories.items()]), 1047, OUTPUT / "figure4_availability.png")
    figure_municipal(municipal_rows, OUTPUT / "figure5_municipal.png")


def _ids(placements, scenario, policy, budget) -> list[str]:
    return [
        row["physical_edge_id"]
        for row in placements
        if row["scenario"] == scenario and row["policy"] == policy and int(row["k"]) == budget
    ]


def _streets() -> list:
    path = ROOT / "outputs/standout/context_basemap.json"
    if not path.is_file():
        return []
    layer = json.loads(path.read_text(encoding="utf-8"))["layers"].get("streets") or {}
    lines = []
    for feature in layer.get("features") or []:
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "LineString":
            lines.append(coordinates)
        elif geometry.get("type") == "MultiLineString":
            lines.extend(coordinates)
    return lines


def _write_classification(rows: list[dict], names: dict[str, str]) -> None:
    payload = [row | {"street_name": names.get(row["physical_edge_id"], "")} for row in rows]
    _write_dicts("infrastructure_classification.csv", payload)


def _write_dicts(name: str, rows: list[dict]) -> None:
    if not rows:
        raise RuntimeError(f"{name} has no rows")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with (OUTPUT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    main()
