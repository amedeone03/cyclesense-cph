"""Draw the report figures from saved results. This does not refit any placement."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "notebooks" / "assets"
OUT = ROOT / "report" / "figures"
NAVY = "#163e72"
ORANGE = "#c47b2b"
GREEN = "#5f8f6a"
GRAY = "#8d8d8d"
GOLD = "#e09a3e"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.labelsize": 10,
            "figure.dpi": 160,
            "savefig.bbox": "tight",
            "pdf.fonttype": 42,
        }
    )
    sources = {
        "fig1_network.pdf": _map(),
        "fig2_baselines.pdf": _baselines(),
        "fig3_lsh.pdf": _lsh(),
        "fig4_stability.pdf": _stability(),
        "fig5_municipal.pdf": _municipal(),
    }
    (OUT / "sources.json").write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(sources)} figures to {OUT.relative_to(ROOT)}")


def _map() -> list[str]:
    graph_path = ROOT / "data/processed/m1/copenhagen_bike_routing_wgs84.graphml"
    results = ROOT / "outputs/m2/results.csv"
    summary_path = ROOT / "outputs/standout/summary.json"
    for path in (graph_path, results, summary_path):
        if not path.is_file():
            raise FileNotFoundError(f"Map figure needs the saved file {path}")
    import osmnx as ox

    from cyclesense.placement_stability_plots import physical_lines

    ox.settings.use_cache = True
    ox.settings.log_console = False
    lines = physical_lines(ox.load_graphml(graph_path))
    greedy = set()
    for row in csv.DictReader(results.open(newline="", encoding="utf-8")):
        if row["scenario"] == "uniform" and row["method"] == "greedy" and row["k"] == "10" and row["seed"] == "":
            greedy = set(row["selected_edges"].split("|"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rows = summary["samples"]["recurring_name_agree"]["alignment_rows"]
    municipal = {row["physical_edge_id"] for row in rows if row["name_status"] == "agree"}
    if len(greedy) != 10 or len(municipal) != 26:
        raise RuntimeError(f"Expected 10 greedy and 26 municipal segments, found {len(greedy)} and {len(municipal)}")
    missing = (greedy | municipal) - set(lines)
    if missing:
        raise RuntimeError(f"Selected segments have no saved geometry: {sorted(missing)[:3]}")

    figure, axis = plt.subplots(figsize=(6.4, 6.1))
    for edge_id, line in lines.items():
        if edge_id in greedy or edge_id in municipal or len(line) < 2:
            continue
        axis.plot([point[1] for point in line], [point[0] for point in line], color="#d5d1c8", linewidth=0.45, solid_capstyle="round", zorder=1)
    _draw(axis, lines, municipal - greedy, ORANGE, 2.3, 3)
    _draw(axis, lines, greedy - municipal, NAVY, 2.5, 4)
    _draw(axis, lines, greedy & municipal, "#6b3fa0", 2.8, 5)
    axis.plot([], [], color=NAVY, linewidth=2.5, label="Greedy, uniform, K = 10")
    axis.plot([], [], color=ORANGE, linewidth=2.3, label="Municipal counting location")
    axis.plot([], [], color="#6b3fa0", linewidth=2.8, label="In both sets")
    axis.set_aspect("equal")
    axis.set_axis_off()
    axis.legend(frameon=False, loc="lower left", fontsize=8)
    figure.savefig(OUT / "fig1_network.pdf")
    plt.close(figure)
    return [
        "data/processed/m1/copenhagen_bike_routing_wgs84.graphml",
        "outputs/m2/results.csv",
        "outputs/standout/summary.json",
    ]


def _draw(axis, lines, edge_ids, color, width, zorder) -> None:
    for edge_id in edge_ids:
        line = lines[edge_id]
        axis.plot([point[1] for point in line], [point[0] for point in line], color=color, linewidth=width, solid_capstyle="round", zorder=zorder)


def _baselines() -> list[str]:
    rows = list(csv.DictReader((ASSETS / "baselines.csv").open(newline="", encoding="utf-8")))
    figure, axes = plt.subplots(1, 2, figsize=(7.4, 3.25), sharey=True)
    styles = {
        "random": (GRAY, "Random"),
        "geographical_kmeans": (GOLD, "Geographic K-means"),
        "route_frequency": (GREEN, "Route frequency"),
        "greedy": (NAVY, "Greedy"),
    }
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        for method, (color, label) in styles.items():
            subset = sorted(
                (int(row["k"]), 100 * float(row["heldout_coverage"]))
                for row in rows
                if row["scenario"] == scenario and row["method"] == method
            )
            axis.plot([item[0] for item in subset], [item[1] for item in subset], "o-", color=color, label=label, markersize=4.5)
        axis.set_title(title)
        axis.set_xlabel("Counter budget K")
        axis.set_xticks([5, 10, 20, 30])
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Held-out coverage (%)")
    axes[1].legend(frameon=False, fontsize=8)
    figure.savefig(OUT / "fig2_baselines.pdf")
    plt.close(figure)
    return ["notebooks/assets/baselines.csv"]


def _lsh() -> list[str]:
    rows = list(csv.DictReader((ASSETS / "fair_timing.csv").open(newline="", encoding="utf-8")))
    figure, axes = plt.subplots(1, 2, figsize=(7.4, 3.15))
    for method, color, label in (
        ("streaming_exact", NAVY, "Streaming exact"),
        ("verified_lsh", ORANGE, "Verified LSH"),
    ):
        subset = sorted(
            (
                int(row["n_routes"]),
                float(row["median_seconds"]),
                float(row["median_peak_mb"]),
            )
            for row in rows
            if row["method"] == method
        )
        axes[0].plot([item[0] for item in subset], [item[1] for item in subset], "o-", color=color, label=label)
        axes[1].plot([item[0] for item in subset], [item[2] for item in subset], "o-", color=color, label=label)
    axes[0].set_ylabel("Median seconds")
    axes[1].set_ylabel("Peak tracked memory (MB)")
    axes[1].set_ylim(0, 400)
    for axis in axes:
        axis.set_xlabel("Routes")
        axis.set_xscale("log")
    axes[0].legend(frameon=False, fontsize=8)
    figure.savefig(OUT / "fig3_lsh.pdf")
    plt.close(figure)
    return ["notebooks/assets/fair_timing.csv"]


def _stability() -> list[str]:
    payload = json.loads((ASSETS / "stability.json").read_text(encoding="utf-8"))
    top = list(reversed(payload["uniform_k10_top"][:8]))
    figure, axis = plt.subplots(figsize=(7.2, 3.45))
    axis.barh([row["street_name"] for row in top], [100 * row["selection_frequency"] for row in top], color=NAVY)
    axis.set_xlabel("Selection frequency across 30 uniform draws (%)")
    axis.set_xlim(0, 100)
    figure.savefig(OUT / "fig4_stability.pdf")
    plt.close(figure)
    return ["notebooks/assets/stability.json"]


def _municipal() -> list[str]:
    rows = list(csv.DictReader((ASSETS / "municipal_coverage.csv").open(newline="", encoding="utf-8")))
    figure, axes = plt.subplots(1, 2, figsize=(7.2, 3.2), sharey=True)
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        subset = sorted((int(row["budget_new"]), row) for row in rows if row["scenario"] == scenario)
        existing = 100 * float(subset[0][1]["held_out_existing_coverage"])
        added = [100 * float(row["held_out_existing_plus_new"]) for _, row in subset]
        axis.bar(["26 sites", "+5 greedy", "+10 greedy"], [existing, *added], color=[NAVY, GREEN, "#2457a6"])
        axis.set_title(title)
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Held-out coverage (%)")
    figure.savefig(OUT / "fig5_municipal.pdf")
    plt.close(figure)
    return ["notebooks/assets/municipal_coverage.csv"]


if __name__ == "__main__":
    main()
