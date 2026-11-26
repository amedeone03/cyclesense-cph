"""Figures for the route-choice sensitivity experiment.

Coverage in every title is modeled-route coverage. The curves describe
simulated shortest paths and simulated detours, not observed cyclists.
"""

from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "outputs/route_choice/mplconfig")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt

GREEDY = "#4daf4a"
BALANCED = "#984ea3"
SHORTEST = "#4d4d4d"
DETOUR_15 = "#377eb8"
DETOUR_30 = "#ff7f00"
METHOD_COLOR = {"greedy": GREEDY, "balanced": BALANCED}
DETOUR_COLOR = {0.15: DETOUR_15, 0.30: DETOUR_30}


def plot_coverage_comparison(seed_rows: Sequence[dict[str, Any]], output: Path) -> None:
    """Mean alternative coverage beside the fixed shortest-path coverage."""
    figure, axes = plt.subplots(1, 2, figsize=(10.4, 4.4), sharey=True)
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        groups = _groups(seed_rows, scenario)
        labels = []
        x_positions = []
        cursor = 0.0
        for method, k in (("greedy", 10), ("balanced", 10), ("greedy", 20), ("balanced", 20)):
            labels.append(f"{method}\nK={k}")
            x_positions.append(cursor)
            rows = groups[(method, k)]
            shortest = rows[0]["shortest_coverage"]
            axis.scatter([cursor - 0.22], [shortest], color=SHORTEST, marker="D", s=28, zorder=3)
            for offset, limit in ((0.0, 0.15), (0.22, 0.30)):
                chosen = [row for row in rows if float(row["detour_limit"]) == limit]
                values = [float(row["coverage"]) for row in chosen]
                center = sum(values) / len(values)
                low, high = min(values), max(values)
                axis.errorbar(
                    cursor + offset,
                    center,
                    yerr=[[center - low], [high - center]],
                    fmt="o",
                    color=DETOUR_COLOR[limit],
                    capsize=3,
                    markersize=5,
                )
            cursor += 1.0
        axis.set_xticks(x_positions)
        axis.set_xticklabels(labels, fontsize=8)
        axis.set_title(title)
        axis.set_ylabel("Simulated-route coverage" if scenario == "uniform" else "")
        axis.set_ylim(0, 1)
        axis.grid(axis="y", color="#eeeeee")
    _legend(
        axes[1],
        [
            plt.Line2D([0], [0], marker="D", color=SHORTEST, linestyle="None", label="Shortest path"),
            plt.Line2D([0], [0], marker="o", color=DETOUR_15, linestyle="None", label="15% detour, mean and range"),
            plt.Line2D([0], [0], marker="o", color=DETOUR_30, linestyle="None", label="30% detour, mean and range"),
        ],
    )
    figure.suptitle("Fixed counter placements on simulated shortest and alternative routes", fontsize=11)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def plot_difference_distribution(seed_rows: Sequence[dict[str, Any]], output: Path) -> None:
    """Paired coverage change, alternative minus shortest, across 20 seeds."""
    figure, axes = plt.subplots(1, 2, figsize=(13.6, 5.0), sharey=True)
    positions = list(range(1, 9))
    tick_labels = [
        "Greedy\nK=10, 15%",
        "Greedy\nK=10, 30%",
        "Balanced\nK=10, 15%",
        "Balanced\nK=10, 30%",
        "Greedy\nK=20, 15%",
        "Greedy\nK=20, 30%",
        "Balanced\nK=20, 15%",
        "Balanced\nK=20, 30%",
    ]
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        groups = _groups(seed_rows, scenario)
        series = []
        colors = []
        for method, k in (("greedy", 10), ("balanced", 10), ("greedy", 20), ("balanced", 20)):
            for limit in (0.15, 0.30):
                rows = [row for row in groups[(method, k)] if float(row["detour_limit"]) == limit]
                series.append([100 * float(row["difference"]) for row in rows])
                colors.append(METHOD_COLOR[method] if limit == 0.15 else "#b2df8a" if method == "greedy" else "#c9b3de")
        box = axis.boxplot(series, positions=positions, widths=0.6, patch_artist=True, showfliers=True)
        for patch, color in zip(box["boxes"], colors, strict=True):
            patch.set_facecolor(color)
        axis.axhline(0, color="#666666", linewidth=0.8)
        axis.set_xticks(positions)
        axis.set_xticklabels(tick_labels, fontsize=7)
        axis.set_title(title)
        axis.set_ylabel("Coverage change, percentage points" if scenario == "uniform" else "")
        axis.grid(axis="y", color="#eeeeee")
    figure.suptitle(
        "Each box is 20 seeds. Darker is the 15% cap; lighter is the 30% cap. Simulated routes.",
        fontsize=10,
    )
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def plot_route_generation(route_rows: Sequence[dict[str, Any]], output: Path) -> None:
    """Share of routes that changed, and the detours of those that did."""
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.3))
    labels = []
    fractions = []
    colors = []
    for scenario, scenario_color in (("uniform", GREEDY), ("commuter_proxy", DETOUR_15)):
        for limit, hatch in ((0.15, ""), (0.30, "//")):
            chosen = [
                row
                for row in route_rows
                if row["scenario"] == scenario and float(row["detour_limit"]) == limit
            ]
            by_seed: dict[int, list[str]] = defaultdict(list)
            for row in chosen:
                by_seed[int(row["seed"])].append(row["status"])
            seed_fractions = [
                sum(status == "changed" for status in statuses) / len(statuses) for statuses in by_seed.values()
            ]
            labels.append(f"{'Uniform' if scenario == 'uniform' else 'Commuter'}\n{int(limit * 100)}%")
            fractions.append(sum(seed_fractions) / len(seed_fractions))
            colors.append(scenario_color)
            axes[0].bar(len(labels) - 1, fractions[-1], color=scenario_color, hatch=hatch, edgecolor="white")
    axes[0].set_xticks(range(len(labels)))
    axes[0].set_xticklabels(labels, fontsize=8)
    axes[0].set_ylim(0, 1)
    axes[0].set_ylabel("Mean fraction of routes changed")
    axes[0].set_title("Routes with a different physical path")
    for scenario in ("uniform", "commuter_proxy"):
        for limit in (0.15, 0.30):
            detours = [
                100 * float(row["detour"])
                for row in route_rows
                if row["scenario"] == scenario
                and float(row["detour_limit"]) == limit
                and row["status"] == "changed"
                and row["detour"] != ""
            ]
            if detours:
                axes[1].hist(
                    detours,
                    bins=15,
                    histtype="step",
                    linewidth=1.6,
                    label=f"{'Uniform' if scenario == 'uniform' else 'Commuter'} {int(limit * 100)}%",
                    color=GREEDY if scenario == "uniform" else DETOUR_15,
                    linestyle="-" if limit == 0.15 else "--",
                )
    axes[1].set_xlabel("Detour of changed routes (%)")
    axes[1].set_ylabel("Changed route-seeds")
    axes[1].set_title("Original-length detour, accepted routes only")
    axes[1].legend(fontsize=7)
    figure.suptitle("Alternative-route generation on the fixed evaluation OD pairs", fontsize=11)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def plot_method_gap(seed_rows: Sequence[dict[str, Any]], output: Path) -> None:
    """Greedy coverage minus balanced coverage. A sign change reverses the ranking."""
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.3), sharey=True)
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        for index, (k, limit) in enumerate(((10, 0.15), (10, 0.30), (20, 0.15), (20, 0.30))):
            greedy = _aligned(seed_rows, scenario, "greedy", k, limit)
            balanced = _aligned(seed_rows, scenario, "balanced", k, limit)
            gaps = [100 * (left - right) for left, right in zip(greedy, balanced, strict=True)]
            shortest_gap = 100 * (
                float(_one(seed_rows, scenario, "greedy", k, limit)["shortest_coverage"])
                - float(_one(seed_rows, scenario, "balanced", k, limit)["shortest_coverage"])
            )
            axis.scatter([index] * len(gaps), gaps, color=DETOUR_COLOR[limit], s=18, alpha=0.85)
            axis.scatter([index], [shortest_gap], marker="D", color=SHORTEST, s=28, zorder=3)
        axis.axhline(0, color="#666666", linewidth=0.8)
        axis.set_xticks([0, 1, 2, 3])
        axis.set_xticklabels(["K=10\n15%", "K=10\n30%", "K=20\n15%", "K=20\n30%"], fontsize=8)
        axis.set_title(title)
        axis.set_ylabel("Greedy minus balanced, percentage points" if scenario == "uniform" else "")
        axis.grid(axis="y", color="#eeeeee")
    figure.suptitle(
        "Positive means greedy covers more simulated routes. Diamonds are the shortest-path gap.",
        fontsize=10,
    )
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def plot_examples(examples: Sequence[dict[str, Any]], output: Path) -> None:
    """A few shortest paths and one accepted alternative, in WGS84 coordinates."""
    if not examples:
        return
    figure, axes = plt.subplots(1, len(examples), figsize=(3.3 * len(examples), 3.6), squeeze=False)
    for axis, example in zip(axes[0], examples, strict=True):
        _draw(axis, example["original"], SHORTEST, "Shortest")
        _draw(axis, example["alternative"], DETOUR_30, "Alternative")
        axis.set_title(f"{example['label']}\ndetour {100 * example['detour']:.1f}%", fontsize=8)
        axis.set_aspect("equal")
        axis.ticklabel_format(useOffset=False, style="plain")
        axis.tick_params(labelsize=7)
        axis.legend(fontsize=7)
    figure.suptitle("Examples use graph geometry. They are simulated routes.", fontsize=10)
    figure.tight_layout()
    figure.savefig(output, dpi=160)
    plt.close(figure)


def _groups(rows: Sequence[dict[str, Any]], scenario: str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["scenario"] == scenario:
            grouped[(str(row["method"]), int(row["k"]))].append(row)
    return grouped


def _aligned(
    rows: Sequence[dict[str, Any]], scenario: str, method: str, k: int, limit: float
) -> list[float]:
    chosen = [
        row
        for row in rows
        if row["scenario"] == scenario
        and row["method"] == method
        and int(row["k"]) == k
        and float(row["detour_limit"]) == limit
    ]
    return [float(row["coverage"]) for row in sorted(chosen, key=lambda row: int(row["seed"]))]


def _one(rows: Sequence[dict[str, Any]], scenario: str, method: str, k: int, limit: float) -> dict[str, Any]:
    return next(
        row
        for row in rows
        if row["scenario"] == scenario
        and row["method"] == method
        and int(row["k"]) == k
        and float(row["detour_limit"]) == limit
    )


def _legend(axis: Any, handles: list[Any]) -> None:
    axis.legend(handles=handles, fontsize=7, loc="lower right")


def _draw(axis: Any, coordinates: Sequence[tuple[float, float]], color: str, label: str) -> None:
    xs = [item[0] for item in coordinates]
    ys = [item[1] for item in coordinates]
    axis.plot(xs, ys, color=color, linewidth=1.8, label=label)
    axis.scatter([xs[0], xs[-1]], [ys[0], ys[-1]], color=color, s=16)
