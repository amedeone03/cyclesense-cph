"""Decision-support catalog for the saved CycleSense results.

The catalog copies measured placements, coverage, and selection frequencies.
It does not place counters, and it does not fill in a missing evaluation.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from cyclesense.placement_stability_plots import physical_lines

REQUIRED = (
    "data/processed/m1/candidates.csv",
    "data/processed/m1/copenhagen_bike_routing_wgs84.graphml",
    "outputs/m2/results.csv",
    "outputs/m4/placements.csv",
    "outputs/robust_placement/placements.csv",
    "outputs/robust_placement/aggregate_coverage.csv",
    "outputs/robust_placement/calibration_coverage.csv",
    "outputs/robust_placement/municipal_additions.csv",
    "outputs/exact_optimization/greedy_comparison.csv",
    "outputs/exact_optimization/exact_placements.csv",
    "outputs/exact_optimization/municipal_additions.csv",
    "outputs/placement_stability/segment_frequencies.csv",
    "outputs/placement_stability/summary.json",
    "outputs/standout/coverage.csv",
    "outputs/standout/summary.json",
)

SCENARIO_LABELS = {"uniform": "Uniform", "commuter_proxy": "Commuter proxy", "both": "Both scenarios"}


def set_comparison(left: Sequence[str], right: Sequence[str]) -> dict[str, object]:
    """Shared ids and Jaccard similarity of two physical-edge selections."""
    first, second = set(left), set(right)
    shared = first & second
    union = first | second
    return {
        "shared": sorted(shared),
        "only_left": sorted(first - second),
        "only_right": sorted(second - first),
        "jaccard": (len(shared) / len(union)) if union else 1.0,
    }


def require_inputs(root: Path) -> None:
    """Name every saved result the planner needs and does not recompute."""
    missing = [relative for relative in REQUIRED if not (root / relative).is_file()]
    if missing:
        lines = "\n".join(f"  {item}" for item in missing)
        raise FileNotFoundError(
            "The planner is missing saved results. Run the study that writes each file:\n" + lines
        )


def build_catalog(root: Path) -> dict[str, object]:
    """Assemble the interactive catalog from saved tables and street geometry."""
    require_inputs(root)
    names = _candidate_names(root / "data/processed/m1/candidates.csv")
    lines = _network_lines(root, names)
    placements = _research_placements(root, names)
    known = {edge["id"] for edge in lines}
    for placement in placements:
        unknown = [edge["id"] for edge in placement["edges"] if edge["id"] not in known]
        if unknown:
            raise RuntimeError(f"{placement['id']} uses a segment without saved geometry: {unknown[:3]}")
    return {
        "place_label": "Indre By core, Copenhagen",
        "network": lines,
        "basemap": _basemap(root),
        "placements": placements,
        "municipal": _municipal(root, names, known),
        "stability": _stability(root),
        "notes": [
            "OpenStreetMap supplies the street geometry. The routes are simulated.",
            "Coverage is the share of simulated routes that meet a selected segment.",
            "Municipal rows are published recurring counts, not confirmed permanent sensors.",
            "Proposed segments are not approved installation sites.",
            "A certified MILP result is optimal for its calibration objective only.",
            "Selection frequency comes from 30 simulated calibration draws. It is not cyclist demand.",
            "A 15% or 30% figure is the mean over 20 perturbed route draws, not observed traffic.",
        ],
    }


def render_planner(catalog: Mapping[str, object]) -> str:
    """Embed the catalog in the standalone planner page."""
    template = Path(__file__).with_name("planner_page.html").read_text(encoding="utf-8")
    payload = json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    token = "<!-- PLANNER_DATA -->"
    if token not in template:
        raise RuntimeError("planner page is missing its data marker")
    return template.replace(token, payload, 1)


def write_planner(root: Path, output: Path | None = None) -> Path:
    """Write the HTML catalog without touching the saved study files."""
    destination = output or (root / "outputs" / "planner" / "cyclesense_planner.html")
    catalog = build_catalog(root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_planner(catalog), encoding="utf-8")
    return destination


def _research_placements(root: Path, names: Mapping[str, str]) -> list[dict[str, object]]:
    marginals = _marginals(root / "outputs/robust_placement/placements.csv")
    fresh = _fresh_evaluations(root / "outputs/robust_placement/aggregate_coverage.csv")
    placements: list[dict[str, object]] = []
    placements.extend(_m2_placements(root, names, marginals, fresh))
    placements.extend(_m4_placements(root, names, marginals, fresh))
    placements.extend(_shared_placements(root, names, marginals, fresh))
    placements.extend(_milp_placements(root, names))
    ids = [item["id"] for item in placements]
    if len(ids) != len(set(ids)):
        raise RuntimeError("two planner records use the same id")
    return placements


def _m2_placements(root, names, marginals, fresh):
    rows = list(_rows(root / "outputs/m2/results.csv"))
    records = []
    for method, label in (
        ("greedy", "Standard greedy"),
        ("route_frequency", "Route frequency"),
        ("geographical_kmeans", "Geographic K-Means (seed 42)"),
    ):
        chosen = [
            row for row in rows
            if row["method"] == method and (method != "geographical_kmeans" or row["seed"] == "42")
        ]
        if method == "geographical_kmeans":
            chosen = [row for row in chosen if row["seed"] == "42"]
        for row in chosen:
            scenario = row["scenario"]
            budget = int(row["k"])
            edges = _edges_or_marginals(
                row["selected_edges"].split("|"),
                names,
                marginals.get((_m59_name(method, scenario), budget)),
            )
            record = _record(
                method=method,
                label=label,
                scenario=scenario,
                budget=budget,
                objective="unweighted",
                objective_label="Unweighted calibration coverage",
                source="M2 baseline placements",
                edges=edges,
                calibration=float(row["calibration_coverage"]),
                certified=False,
            )
            record["evaluations"][f"{scenario}|shortest"] = _single(
                float(row["heldout_coverage"]),
                "M2 held-out split",
                "Held-out shortest paths",
            )
            if method == "greedy":
                record["note"] = "Deterministic maximum-coverage greedy."
                _add_fresh(record, fresh, _m59_name(method, scenario), budget)
                record["heldout_baseline"] = None
            else:
                record["heldout_baseline"] = f"greedy:{scenario}:{budget}"
                record["baseline_label"] = "standard greedy, same training scenario and budget"
                if method == "geographical_kmeans":
                    record["note"] = "One of five stochastic seeds. The coverage is this seed, not an average."
                else:
                    record["note"] = "Deterministic route-frequency baseline."
            record["stability_key"] = (
                f"greedy|{scenario}|{budget}" if method == "greedy" and budget in {10, 20} else None
            )
            records.append(record)
    return records


def _m4_placements(root, names, marginals, fresh):
    records = []
    for row in _rows(root / "outputs/m4/placements.csv"):
        if row["lambda"] != "0.25" or row["threshold"] != "0.5" or row["source"] != "louvain":
            continue
        scenario = row["scenario"]
        budget = int(row["k"])
        edges = _edges_or_marginals(
            row["selected_edges"].split("|"),
            names,
            marginals.get((_balanced_name(scenario), budget)),
        )
        record = _record(
            method="balanced",
            label="Community-balanced greedy (λ = 0.25)",
            scenario=scenario,
            budget=budget,
            objective="community_balanced",
            objective_label="Community-weighted calibration coverage (λ = 0.25)",
            source="M4 community-balanced placements",
            edges=edges,
            calibration=float(row["calibration_coverage"]),
            certified=False,
        )
        record["evaluations"][f"{scenario}|shortest"] = _single(
            float(row["heldout_coverage"]),
            "M4 held-out split",
            "Held-out shortest paths",
        )
        other = row["shifted_scenario"]
        record["evaluations"][f"{other}|shortest"] = _single(
            float(row["shifted_coverage"]),
            "M4 scenario-shift held-out split",
            "Held-out shortest paths, other scenario",
        )
        record["heldout_baseline"] = f"greedy:{scenario}:{budget}"
        record["baseline_label"] = "standard greedy, same training scenario and budget"
        record["note"] = "The calibration value uses community weights. It is not the unweighted greedy objective."
        record["stability_key"] = None
        _add_fresh(record, fresh, _balanced_name(scenario), budget, skip_shortest=True)
        records.append(record)
    return records


def _shared_placements(root, names, marginals, fresh):
    records = []
    specs = (
        ("pooled_shortest", "pooled", "Pooled shortest-path greedy", "pooled_shortest", "Pooled shortest-path calibration coverage", "M5.9 pooled placement"),
        ("robust_pooled", "route_choice", "Route-choice-augmented greedy", "route_choice", "Route-choice calibration coverage", "M5.9 route-choice placement"),
    )
    calibration = {
        (row["method"], int(row["k"]), row["score"]): float(row["coverage"])
        for row in _rows(root / "outputs/robust_placement/calibration_coverage.csv")
        if row["scenario"] == "both"
    }
    for stored, method, label, objective, objective_label, source in specs:
        score = "pooled_shortest_objective" if stored == "pooled_shortest" else "robust_training_objective"
        for budget in (10, 20):
            edges = _edge_records([], names, marginals[(stored, budget)])
            record = _record(
                method=method,
                label=label,
                scenario="both",
                budget=budget,
                objective=objective,
                objective_label=objective_label,
                source=source,
                edges=edges,
                calibration=calibration[(stored, budget, score)],
                certified=False,
            )
            _add_fresh(record, fresh, stored, budget)
            stability_method = "route_choice" if stored == "robust_pooled" else stored
            record["stability_key"] = f"{stability_method}|pooled|{budget}" if budget == 10 else None
            if stored == "robust_pooled":
                record["heldout_baseline"] = f"pooled:both:{budget}"
                record["baseline_label"] = "pooled shortest-path greedy, same budget"
                record["note"] = "Trained on perturbed calibration routes. The calibration value is not the pooled shortest-path objective."
            else:
                record["heldout_baseline"] = None
                record["note"] = "One placement trained on both scenarios with equal weight."
            records.append(record)
    return records


def _milp_placements(root, names):
    grouped: dict[tuple[str, int], list[dict[str, str]]] = {}
    for row in _rows(root / "outputs/exact_optimization/exact_placements.csv"):
        if row["objective"] != "unweighted":
            continue
        grouped.setdefault((row["scenario"], int(row["k"])), []).append(row)
    metrics = {
        (row["scenario"], int(row["k"])): row
        for row in _rows(root / "outputs/exact_optimization/greedy_comparison.csv")
        if row["objective"] == "unweighted"
    }
    records = []
    for (scenario, budget), rows in sorted(grouped.items()):
        metric = metrics[(scenario, budget)]
        if metric["proven_optimal"] != "True" or metric["status"] != "optimal":
            continue
        ordered = sorted(rows, key=lambda item: int(item["rank"]))
        edges = []
        for row in ordered:
            edges.append({
                "id": row["physical_edge_id"],
                "name": names.get(row["physical_edge_id"], ""),
                "rank": int(row["rank"]),
                "marginal": None,
                "solver_support": row["in_solver_support"] == "True",
            })
        record = _record(
            method="milp",
            label="Certified MILP optimum",
            scenario=scenario,
            budget=budget,
            objective="unweighted",
            objective_label="Unweighted calibration coverage",
            source="M5.10 exact optimization",
            edges=edges,
            calibration=float(metric["exact_coverage"]),
            certified=True,
        )
        for evaluation in ("uniform", "commuter_proxy"):
            record["evaluations"][f"{evaluation}|shortest"] = _single(
                float(metric[f"heldout_{'uniform' if evaluation == 'uniform' else 'commuter'}_exact"]),
                "M5.10 held-out split",
                "Held-out shortest paths",
            )
        record["heldout_baseline"] = f"greedy:{scenario}:{budget}"
        record["baseline_label"] = "standard greedy, same training scenario and budget"
        record["note"] = "Certified optimal for the unweighted calibration objective. Held-out routes were not used in the solve."
        record["stability_key"] = None
        records.append(record)
    return records


def _municipal(root, names, known):
    summary = json.loads((root / "outputs/standout/summary.json").read_text(encoding="utf-8"))
    observed = {
        row["physical_edge_id"]: row
        for row in summary["samples"]["recurring_name_agree"]["alignment_rows"]
    }
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in _rows(root / "outputs/robust_placement/municipal_additions.csv"):
        grouped.setdefault(row["method"], []).append(row)
    existing_rows = grouped["municipal_26"]
    if len(existing_rows) != 26:
        raise RuntimeError(f"expected 26 municipal segments, found {len(existing_rows)}")
    existing = []
    for row in existing_rows:
        edge_id = row["physical_edge_id"]
        if edge_id not in known:
            raise RuntimeError(f"municipal segment {edge_id} has no saved geometry")
        info = observed.get(edge_id)
        if not info or info.get("bike_aadt") is None:
            raise RuntimeError(f"municipal segment {edge_id} has no saved published count")
        existing.append({
            "id": edge_id,
            "name": row["street_name"] or info.get("street") or names.get(edge_id, ""),
            "aadt": info.get("bike_aadt"),
            "year": info.get("year"),
            "count_type": info.get("count_type"),
            "role": "municipal",
        })
    standout = list(_rows(root / "outputs/standout/coverage.csv"))
    fresh = _fresh_evaluations(root / "outputs/robust_placement/aggregate_coverage.csv")
    exact = list(_rows(root / "outputs/exact_optimization/municipal_additions.csv"))
    plans = []
    for scenario in ("uniform", "commuter_proxy"):
        base = next(row for row in standout if row["scenario"] == scenario and row["budget_new"] == "5")
        plans.append(_municipal_plan(
            plan_id=f"municipal:{scenario}:26",
            label="26 verified counting sites",
            scenario=scenario,
            existing=existing,
            added=[],
            heldout=float(base["held_out_existing_coverage"]),
            calibration=float(base["calibration_existing_coverage"]),
            source="Municipal extension",
            fresh_method="municipal_26",
            fresh_budget=0,
            fresh=fresh,
            certified=False,
            training="Neither scenario. These sites were not chosen by the placement algorithm.",
        ))
        added = _added_from_group(grouped["municipal_original_plus5"], scenario, names, known)
        plans.append(_municipal_plan(
            plan_id=f"municipal:{scenario}:original5",
            label="26 sites + 5 greedy additions",
            scenario=scenario,
            existing=existing,
            added=added,
            heldout=float(base["held_out_existing_plus_new"]),
            calibration=float(base["calibration_existing_plus_new"]),
            source="Municipal extension",
            fresh_method="municipal_original_plus5",
            fresh_budget=5,
            fresh=fresh,
            certified=False,
            training=f"Additions trained on {SCENARIO_LABELS[scenario].lower()} calibration routes.",
        ))
        ten = next(row for row in standout if row["scenario"] == scenario and row["budget_new"] == "10")
        plans.append(_municipal_plan(
            plan_id=f"municipal:{scenario}:original10",
            label="26 sites + 10 greedy additions",
            scenario=scenario,
            existing=existing,
            added=_edge_records(ten["added_edges"].split("|"), names, None),
            heldout=float(ten["held_out_existing_plus_new"]),
            calibration=float(ten["calibration_existing_plus_new"]),
            source="Municipal extension",
            fresh_method=None,
            fresh_budget=None,
            fresh=fresh,
            certified=False,
            training=f"Additions trained on {SCENARIO_LABELS[scenario].lower()} calibration routes.",
        ))
        milp = next(row for row in exact if row["scenario"] == scenario and row["method"] == "milp")
        if milp["proven_optimal"] != "True":
            raise RuntimeError("municipal MILP additions are not certified")
        plans.append(_municipal_plan(
            plan_id=f"municipal:{scenario}:milp5",
            label="26 sites + 5 certified MILP additions",
            scenario=scenario,
            existing=existing,
            added=_edge_records(milp["added_edges"].split("|"), names, None),
            heldout=float(milp["heldout_coverage"]),
            calibration=float(milp["calibration_coverage"]),
            source="M5.10 municipal extension",
            fresh_method=None,
            fresh_budget=None,
            fresh=fresh,
            certified=True,
            training="Additions maximize unweighted calibration coverage with the 26 sites fixed.",
        ))
    robust_added = _added_from_group(grouped["municipal_robust_plus5"], "both", names, known)
    for scenario in ("uniform", "commuter_proxy"):
        metric = fresh.get(("municipal_robust_plus5", 5, scenario, "shortest"))
        if metric is None:
            raise RuntimeError(f"robust municipal additions have no {scenario} shortest-path score")
        plans.append(_municipal_plan(
            plan_id=f"municipal:{scenario}:robust5",
            label="26 sites + 5 route-choice additions",
            scenario=scenario,
            existing=existing,
            added=robust_added,
            heldout=metric["value"],
            calibration=None,
            source="M5.9 municipal additions",
            fresh_method="municipal_robust_plus5",
            fresh_budget=5,
            fresh=fresh,
            certified=False,
            training="One addition set trained on both scenarios. Calibration coverage of the full set was not saved.",
        ))
    return {"existing_ids": [edge["id"] for edge in existing], "plans": plans}


def _municipal_plan(plan_id, label, scenario, existing, added, heldout, calibration, source, fresh_method, fresh_budget, fresh, certified, training):
    evaluations = {
        f"{scenario}|shortest": _single(heldout, source, "Held-out shortest paths"),
    }
    if fresh_method is not None:
        for evaluation in ("uniform", "commuter_proxy"):
            for condition, suffix in (("shortest", "shortest"), ("0.15", "detour_15"), ("0.30", "detour_30")):
                metric = fresh.get((fresh_method, fresh_budget, evaluation, condition))
                key = f"{evaluation}|{suffix}"
                if metric is not None and key not in evaluations:
                    evaluations[key] = metric
    for edge in added:
        if edge["id"] in {item["id"] for item in existing}:
            raise RuntimeError(f"{plan_id} repeats a municipal segment")
    return {
        "id": plan_id,
        "label": label,
        "scenario": scenario,
        "scenario_label": SCENARIO_LABELS[scenario],
        "training": training,
        "source": source,
        "certified_optimal": certified,
        "existing": existing,
        "added": added,
        "calibration": None if calibration is None else {
            "value": calibration,
            "label": "Unweighted calibration coverage of the full set",
        },
        "evaluations": evaluations,
    }


def _stability(root: Path) -> dict[str, object]:
    summary = json.loads((root / "outputs/placement_stability/summary.json").read_text(encoding="utf-8"))
    replicates = int(summary["n_replicates"])
    tables: dict[str, dict[str, object]] = {}
    for row in _rows(root / "outputs/placement_stability/segment_frequencies.csv"):
        key = f"{row['method']}|{row['scenario']}|{int(row['k'])}"
        table = tables.setdefault(key, {"n_replicates": replicates, "frequencies": {}})
        table["frequencies"][row["physical_edge_id"]] = float(row["selection_frequency"])
    return tables


def _add_fresh(record, fresh, method, budget, skip_shortest=False):
    scenarios = ("uniform", "commuter_proxy")
    for scenario in scenarios:
        for condition, suffix in (("shortest", "shortest"), ("0.15", "detour_15"), ("0.30", "detour_30")):
            if skip_shortest and condition == "shortest":
                continue
            metric = fresh.get((method, budget, scenario, condition))
            key = f"{scenario}|{suffix}"
            if metric is not None and key not in record["evaluations"]:
                record["evaluations"][key] = metric


def _fresh_evaluations(path: Path) -> dict[tuple[str, str, str], dict[str, object]]:
    metrics = {}
    for row in _rows(path):
        if row["seed_block"] != "fresh":
            continue
        condition = row["condition"]
        key = (row["method"], int(row["k"]), row["scenario"], condition)
        if condition == "shortest":
            metrics[key] = _single(
                float(row["shortest_coverage"]),
                "M5.9 fresh evaluation, shortest paths",
                "Held-out shortest paths",
            )
        elif condition in {"0.15", "0.30"}:
            metrics[key] = {
                "value": float(row["coverage_mean"]),
                "kind": "seed_mean",
                "n_seeds": int(row["n_seeds"]),
                "std": float(row["coverage_std"]),
                "source": "M5.9 fresh seeds 92000–92019",
                "label": f"Alternative routes, {float(condition):.0%} detour cap",
            }
    return metrics


def _marginals(path: Path) -> dict[tuple[str, int], list[dict[str, object]]]:
    grouped: dict[tuple[str, int], list[tuple[int, dict[str, object]]]] = {}
    for row in _rows(path):
        gain = row["calibration_marginal_gain"]
        grouped.setdefault((row["method"], int(row["k"])), []).append((
            int(row["rank"]),
            {
                "id": row["physical_edge_id"],
                "name": row["street_name"],
                "rank": int(row["rank"]),
                "marginal": None if gain == "" else float(gain),
                "solver_support": None,
            },
        ))
    return {key: [edge for _rank, edge in sorted(rows)] for key, rows in grouped.items()}


def _edge_records(edge_ids, names, prepared):
    if prepared is not None:
        return prepared
    return [
        {"id": edge_id, "name": names.get(edge_id, ""), "rank": index, "marginal": None, "solver_support": None}
        for index, edge_id in enumerate((edge for edge in edge_ids if edge), start=1)
    ]


def _edges_or_marginals(edge_ids, names, prepared):
    plain = _edge_records(edge_ids, names, None)
    if prepared is None:
        return plain
    if [edge["id"] for edge in prepared] != [edge["id"] for edge in plain]:
        return plain
    return prepared


def _added_from_group(rows, scenario, names, known):
    chosen = [row for row in rows if row["scenario"] == scenario]
    ordered = sorted(chosen, key=lambda row: int(row["rank"]))
    edges = []
    for row in ordered:
        if row["physical_edge_id"] not in known:
            raise RuntimeError(f"addition {row['physical_edge_id']} has no saved geometry")
        edges.append({
            "id": row["physical_edge_id"],
            "name": row["street_name"] or names.get(row["physical_edge_id"], ""),
            "rank": int(row["rank"]),
            "marginal": None,
            "solver_support": None,
        })
    return edges


def _record(method, label, scenario, budget, objective, objective_label, source, edges, calibration, certified):
    if len(edges) != budget or len({edge["id"] for edge in edges}) != budget:
        raise RuntimeError(f"{method} {scenario} K={budget} does not contain {budget} distinct segments")
    return {
        "id": f"{method}:{scenario}:{budget}",
        "method": method,
        "method_label": label,
        "training_scenario": scenario,
        "training_label": SCENARIO_LABELS[scenario],
        "budget": budget,
        "objective": objective,
        "objective_label": objective_label,
        "source": source,
        "certified_optimal": certified,
        "edges": edges,
        "calibration": {"value": calibration, "label": objective_label},
        "evaluations": {},
        "heldout_baseline": None,
        "baseline_label": None,
        "note": "",
        "stability_key": None,
    }


def _single(value: float, source: str, label: str) -> dict[str, object]:
    return {"value": value, "kind": "single", "n_seeds": None, "std": None, "source": source, "label": label}


def _m59_name(method: str, scenario: str) -> str:
    if method == "greedy" and scenario == "uniform":
        return "uniform_greedy"
    if method == "greedy" and scenario == "commuter_proxy":
        return "commuter_greedy"
    return method


def _balanced_name(scenario: str) -> str:
    return "uniform_balanced" if scenario == "uniform" else "commuter_balanced"


def _network_lines(root: Path, names: Mapping[str, str]) -> list[dict[str, object]]:
    import osmnx as ox

    graph = ox.load_graphml(root / "data/processed/m1/copenhagen_bike_routing_wgs84.graphml")
    lines = []
    for edge_id, points in physical_lines(graph).items():
        if edge_id not in names:
            continue
        lines.append({
            "id": edge_id,
            "name": names[edge_id],
            "line": [[round(lon, 6), round(lat, 6)] for lat, lon in points],
        })
    if len(lines) != len(names):
        missing = set(names) - {edge["id"] for edge in lines}
        raise RuntimeError(f"{len(missing)} eligible segments have no saved geometry")
    return lines


def _basemap(root: Path) -> dict[str, list]:
    path = root / "outputs/standout/context_basemap.json"
    if not path.is_file():
        return {"water": [], "green": [], "streets": []}
    layers = json.loads(path.read_text(encoding="utf-8"))["layers"]
    return {
        "water": _shapes(layers.get("water"), closed=True),
        "green": _shapes(layers.get("green"), closed=True),
        "streets": _shapes(layers.get("streets"), closed=False),
    }


def _shapes(collection, closed: bool) -> list:
    if not collection:
        return []
    shapes = []
    for feature in collection.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        kind = geometry.get("type")
        if kind == "LineString":
            shapes.append(_round_line(coordinates))
        elif kind == "Polygon" and coordinates:
            shapes.append(_round_line(coordinates[0]))
        elif kind == "MultiLineString":
            shapes.extend(_round_line(line) for line in coordinates)
        elif kind == "MultiPolygon":
            shapes.extend(_round_line(polygon[0]) for polygon in coordinates if polygon)
    return [shape for shape in shapes if len(shape) >= (3 if closed else 2)]


def _round_line(coordinates) -> list[list[float]]:
    return [[round(float(lon), 6), round(float(lat), 6)] for lon, lat in coordinates]


def _candidate_names(path: Path) -> dict[str, str]:
    names = {}
    for row in _rows(path):
        names[row["physical_edge_id"]] = row.get("name") or ""
    return names


def _rows(path: Path):
    with path.open(newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)
