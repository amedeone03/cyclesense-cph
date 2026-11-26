"""Compare simulated routes with Copenhagen's published bicycle counts.

From the repository root, after the M1 pilot has been generated:

    python scripts/run_external_validation.py

The municipal CSV is cached under gitignored ``data/external/``. Figures and
tables go to gitignored ``outputs/standout/``. This does not modify M1 files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.external_validation import (
    AADT_DEFINITION,
    GEOMETRY_SAMPLE,
    PRIMARY_SAMPLE,
    SENSITIVITY_SAMPLE,
    TRAFIKTAL_COLUMNS_URL,
    TRAFIKTAL_CSV_URL,
    TRAFIKTAL_INFO_URL,
    TRAFIKTAL_LICENSE,
    TRAFIKTAL_PUBLISHER,
    evaluate_extension,
    load_count_sites,
    load_route_records,
    parse_linestring,
    segments_from_directed_edges,
)

COUNTS_NAME = "trafiktal.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="External check against Copenhagen bicycle counts")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "configs" / "pilot.yaml")
    parser.add_argument("--counts", type=Path, default=REPO_ROOT / "data" / "external" / COUNTS_NAME)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "outputs" / "standout")
    parser.add_argument("--refresh-counts", action="store_true")
    args = parser.parse_args()

    artifacts = validated_m1_artifacts(REPO_ROOT)
    if artifacts is None:
        raise SystemExit(
            "M1 artifacts are missing or incomplete. From the repository root run "
            "python scripts/run_m1.py, then rerun this script. M2 placement outputs "
            "are not required and are not read."
        )
    config = _load_config(args.config)
    ensure_counts(args.counts, refresh=args.refresh_counts)
    sites = load_count_sites(args.counts)
    routes = load_route_records(artifacts["routes"])
    segments = load_segments(artifacts["routing_wgs84"], artifacts["candidates"])
    study = config["study_area"]
    anchor_cfg = config["simulation"]["commuter_proxy"]
    result = evaluate_extension(
        sites,
        segments,
        routes,
        bbox=(float(study["west"]), float(study["south"]), float(study["east"]), float(study["north"])),
        anchor=(float(anchor_cfg["anchor_lon"]), float(anchor_cfg["anchor_lat"])),
        anchor_name=str(anchor_cfg["anchor_name"]),
        budgets=tuple(int(budget) for budget in config["placement"]["counter_budgets"]),
    )
    result["provenance"] = {
        "publisher": TRAFIKTAL_PUBLISHER,
        "license": TRAFIKTAL_LICENSE,
        "dataset_url": TRAFIKTAL_INFO_URL,
        "csv_url": TRAFIKTAL_CSV_URL,
        "column_documentation_url": TRAFIKTAL_COLUMNS_URL,
        "local_csv": str(args.counts),
        "sha256": sha256(args.counts),
        "n_csv_rows_with_coordinates": len(sites),
        "aadt_definition": AADT_DEFINITION,
        "m1_routes": str(artifacts["routes"]),
        "m1_routing_graph": str(artifacts["routing_wgs84"]),
        "m1_candidates": str(artifacts["candidates"]),
        "note": (
            "Observed bicycle AADT and simulated route traversals are different "
            "quantities. A rank correlation is not a causal validation."
        ),
    }
    args.output.mkdir(parents=True, exist_ok=True)
    write_tables(args.output, result)
    write_plots(args.output, result, segments)
    (args.output / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print_summary(result, args.output)


def ensure_counts(path: Path, *, refresh: bool) -> None:
    if path.is_file() and path.stat().st_size > 0 and not refresh:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(TRAFIKTAL_CSV_URL, path)
    except OSError as exc:
        raise SystemExit(f"Could not download municipal counts from {TRAFIKTAL_CSV_URL}: {exc}") from exc


def load_segments(graph_path: Path, candidates_path: Path):
    import networkx as nx

    graph = nx.read_graphml(graph_path)
    candidates: dict[str, dict[str, str]] = {}
    with candidates_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            candidates[row["physical_edge_id"]] = row
    if not candidates:
        raise SystemExit(f"{candidates_path} has no candidate segments")
    stored_ids = _stored_physical_ids(graph)
    use_stored = bool(stored_ids & set(candidates))
    edges = []
    for u_node, v_node, data in _edge_items(graph):
        if use_stored:
            edge_id = str(data.get("physical_edge_id") or "")
        else:
            edge_id = _recomputed_id(u_node, v_node, data)
        row = candidates.get(edge_id)
        if row is None:
            continue
        polyline = parse_linestring(data.get("geometry"))
        if polyline is None:
            polyline = (_node_lonlat(graph, u_node), _node_lonlat(graph, v_node))
        edges.append(
            {
                "physical_edge_id": edge_id,
                "polyline": polyline,
                "highway": row.get("highway", ""),
                "name": row.get("name", ""),
            }
        )
    segments = segments_from_directed_edges(edges)
    if not segments:
        sample = next(iter(graph.edges(data=True)))
        raise SystemExit(
            "No candidate geometry could be read from the M1 graph. "
            f"Example edge attributes: {sorted(sample[2].keys())[:12]}"
        )
    return segments


def write_tables(output: Path, result: dict[str, Any]) -> None:
    samples = result["samples"]
    _write_csv(output / "matches_recurring.csv", samples[GEOMETRY_SAMPLE]["match_rows"])
    _write_csv(output / "matches_sensitivity.csv", samples[SENSITIVITY_SAMPLE]["match_rows"])
    _write_csv(output / "alignment_primary.csv", samples[PRIMARY_SAMPLE]["alignment_rows"])
    _write_csv(output / "alignment_geometric.csv", samples[GEOMETRY_SAMPLE]["alignment_rows"])
    _write_csv(output / "alignment_sensitivity.csv", samples[SENSITIVITY_SAMPLE]["alignment_rows"])
    coverage_rows = []
    for scenario in result["coverage"]:
        shared = {
            "scenario": scenario["scenario"],
            "n_existing": scenario["n_existing"],
            "held_out_existing_coverage": scenario["held_out_existing_coverage"],
            "calibration_existing_coverage": scenario["calibration_existing_coverage"],
            "held_out_same_size_greedy_coverage": scenario["held_out_same_size_greedy_coverage"],
            "edge_jaccard_existing_vs_same_size_greedy": scenario[
                "edge_jaccard_existing_vs_same_size_greedy"
            ],
        }
        for budget in scenario["budgets"]:
            coverage_rows.append({**shared, **budget, "added_edges": "|".join(budget["added_edges"])})
    _write_csv(output / "coverage.csv", coverage_rows)


def write_plots(output: Path, result: dict[str, Any], segments) -> None:
    import os

    mpl_dir = output / "mplconfig"
    mpl_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    os.environ.setdefault("MPLBACKEND", "Agg")
    primary = result["samples"][PRIMARY_SAMPLE]["alignment_rows"]
    geometric = result["samples"][GEOMETRY_SAMPLE]["alignment_rows"]
    plot_rows = primary or geometric
    plot_label = (
        "Name-agreeing recurring counts"
        if primary
        else "Geometric matches (street name not confirmed)"
    )
    if plot_rows:
        scenarios = [
            key.removesuffix("_calibration_traversals")
            for key in plot_rows[0]
            if key.endswith("_calibration_traversals")
        ]
        plot_alignment(
            plot_rows,
            scenarios,
            output / "alignment_scatter.png",
            f"{plot_label} and simulated route frequency",
        )
        plot_sites(
            segments,
            plot_rows,
            output / "matched_sites.png",
            f"{plot_label} inside the M1 rectangle",
        )
    if result["coverage"]:
        plot_coverage(result["coverage"], output / "coverage_comparison.png")


def plot_alignment(rows, scenarios, path: Path, title: str) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.2), squeeze=False)
    for axis, scenario in zip(axes[0], scenarios, strict=True):
        column = f"{scenario}_calibration_traversals"
        axis.scatter(
            [row[column] for row in rows],
            [row["bike_aadt"] for row in rows],
            c="#0072B2",
            alpha=0.85,
            s=28,
        )
        axis.set_xlabel("Calibration routes on the matched segment")
        axis.set_ylabel("Observed bicycle AADT")
        axis.set_title(scenario.replace("_", " "))
    fig.suptitle(title)
    fig.text(
        0.01,
        0.01,
        "AADT is a municipal daytime count. Route counts are simulated shortest paths.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_coverage(coverage, path: Path) -> None:
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(coverage), figsize=(5.4 * len(coverage), 4.2), squeeze=False)
    for axis, scenario in zip(axes[0], coverage, strict=True):
        labels = ["Existing"]
        values = [scenario["held_out_existing_coverage"]]
        for budget in scenario["budgets"]:
            labels.append(f"+{budget['budget_new']}")
            values.append(budget["held_out_existing_plus_new"])
        labels.append("Greedy, same count")
        values.append(scenario["held_out_same_size_greedy_coverage"])
        axis.bar(labels, values, color="#0072B2")
        axis.set_ylim(0, 1)
        axis.tick_params(axis="x", labelrotation=30)
        axis.set_ylabel("Held-out modeled-route coverage")
        axis.set_title(scenario["scenario"].replace("_", " "))
    fig.suptitle("Existing counting sites and additional greedy sites")
    fig.text(
        0.01,
        0.01,
        "Coverage is the share of simulated routes that touch a selected segment.",
        fontsize=8,
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_sites(segments, rows, path: Path, title: str) -> None:
    import matplotlib.pyplot as plt

    matched = {row["physical_edge_id"] for row in rows}
    fig, axis = plt.subplots(figsize=(7.2, 7.2))
    for segment in segments:
        xs = [point[0] for point in segment.polyline]
        ys = [point[1] for point in segment.polyline]
        if segment.physical_edge_id in matched:
            axis.plot(xs, ys, color="#0072B2", linewidth=1.6, zorder=2)
        else:
            axis.plot(xs, ys, color="#d0d0d0", linewidth=0.35, zorder=1)
    points = axis.scatter(
        [row["longitude"] for row in rows],
        [row["latitude"] for row in rows],
        c=[row["bike_aadt"] for row in rows],
        cmap="viridis",
        s=32,
        zorder=3,
    )
    fig.colorbar(points, ax=axis, fraction=0.046, pad=0.04, label="Observed bicycle AADT")
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title(title)
    axis.set_aspect("equal", adjustable="box")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def print_summary(result: dict[str, Any], output: Path) -> None:
    primary = result["samples"][PRIMARY_SAMPLE]
    geometric = result["samples"][GEOMETRY_SAMPLE]
    print("CycleSense external count check")
    print(AADT_DEFINITION)
    print(
        f"Recurring sites considered: {geometric['n_input_sites']} · "
        f"status {geometric['status_counts']} · name check {geometric['name_counts']}"
    )
    print(
        f"Primary name-agreeing edges: {primary['n_analysis_edges']} · "
        f"median snap {primary['median_snap_distance_m']} m"
    )
    print(result["interpretation"]["reason"])
    for label, sample_name in (
        ("Primary", PRIMARY_SAMPLE),
        ("Geometric", GEOMETRY_SAMPLE),
        ("Sensitivity", SENSITIVITY_SAMPLE),
    ):
        sample = result["samples"][sample_name]
        print(f"{label} edges: {sample['n_analysis_edges']}")
        for test in sample["rank_tests"]:
            print(
                f"  {test['comparison']} [{test['scenario']}]: "
                f"n={test['n']} rho={test['spearman_rho']} p={test['permutation_p']} "
                f"top-quartile overlap={test['top_quartile_overlap']}"
            )
    for scenario in result["coverage"]:
        print(
            f"Held-out {scenario['scenario']}: existing {scenario['held_out_existing_coverage']} "
            f"on {scenario['n_existing']} edges; "
            f"same-size greedy {scenario['held_out_same_size_greedy_coverage']}; "
            f"Jaccard {scenario['edge_jaccard_existing_vs_same_size_greedy']}"
        )
        for budget in scenario["budgets"]:
            print(
                f"  +{budget['budget_new']}: held-out {budget['held_out_existing_plus_new']} "
                f"(marginal {budget['held_out_marginal_gain']}); "
                f"greedy of {budget['budget_new']} alone {budget['held_out_greedy_new_only']}"
            )
    print(f"Wrote {output / 'summary.json'}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 16), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise SystemExit("Install analysis dependencies: pip install -e '.[analysis]'") from exc
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit(f"{path} did not contain a mapping")
    return loaded


def _edge_items(graph):
    if graph.is_multigraph():
        for u_node, v_node, _key, data in graph.edges(keys=True, data=True):
            yield u_node, v_node, data
    else:
        yield from graph.edges(data=True)


def _stored_physical_ids(graph) -> set[str]:
    found = set()
    for _u, _v, data in _edge_items(graph):
        edge_id = data.get("physical_edge_id")
        if edge_id:
            found.add(str(edge_id))
    return found


def _recomputed_id(u_node, v_node, data) -> str:
    from cyclesense.edges import physical_edge_id

    return physical_edge_id(u_node, v_node, _osmid(data.get("osmid")))


def _osmid(raw: object):
    if isinstance(raw, (list, tuple)):
        return list(raw)
    text = str(raw or "").strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    values = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(float(part)))
        except ValueError:
            return raw
    if not values:
        return None
    return values[0] if len(values) == 1 else values


def _node_lonlat(graph, node) -> tuple[float, float]:
    attributes = graph.nodes[node]
    longitude = attributes.get("x", attributes.get("lon"))
    latitude = attributes.get("y", attributes.get("lat"))
    if longitude is None or latitude is None:
        raise SystemExit(f"Node {node} has no x/y coordinates: {sorted(attributes)[:8]}")
    return float(longitude), float(latitude)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames and not isinstance(row[key], (list, dict)):
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


if __name__ == "__main__":
    main()
