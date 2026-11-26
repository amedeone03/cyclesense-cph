"""Figures for route-choice-aware placement.

Every coverage value is modeled-route coverage of simulated paths.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "outputs/robust_placement/mplconfig")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt

UNIFORM = "#4daf4a"
COMMUTER = "#1b9e77"
POOLED = "#377eb8"
ROBUST = "#e41a1c"
BALANCED = "#984ea3"
MUNICIPAL = "#08306b"
SHORTEST = "#4d4d4d"
ALT_15 = "#377eb8"
ALT_30 = "#ff7f00"

METHOD_COLOR = {
    "uniform_greedy": UNIFORM,
    "commuter_greedy": COMMUTER,
    "pooled_shortest": POOLED,
    "robust_pooled": ROBUST,
    "uniform_balanced": BALANCED,
    "commuter_balanced": BALANCED,
}
METHOD_LABEL = {
    "uniform_greedy": "Uniform greedy",
    "commuter_greedy": "Commuter greedy",
    "pooled_shortest": "Pooled shortest",
    "robust_pooled": "Robust pooled",
    "uniform_balanced": "Uniform balanced",
    "commuter_balanced": "Commuter balanced",
}
def plot_coverage_by_method(aggregate: Sequence[Mapping[str, Any]], output: Path) -> None:
    """Shortest-path and alternative-route held-out coverage for the main methods."""
    fresh = [row for row in aggregate if row["seed_block"] == "fresh"]
    figure, axes = plt.subplots(2, 2, figsize=(11.2, 7.2), sharey=True)
    panels = (
        (axes[0, 0], "uniform", 10),
        (axes[0, 1], "commuter_proxy", 10),
        (axes[1, 0], "uniform", 20),
        (axes[1, 1], "commuter_proxy", 20),
    )
    for axis, scenario, budget in panels:
        methods = _panel_methods(scenario)
        positions = list(range(len(methods)))
        width = 0.24
        for offset, condition, color, label in (
            (-width, "shortest", SHORTEST, "Shortest path"),
            (0.0, "0.15", ALT_15, "15% alternatives"),
            (width, "0.30", ALT_30, "30% alternatives"),
        ):
            heights = [_coverage(fresh, scenario, method, budget, condition) for method in methods]
            axis.bar(
                [pos + offset for pos in positions],
                [100.0 * value for value in heights],
                width=width,
                color=color,
                label=label,
            )
        axis.set_xticks(positions, [_label(method) for method in methods], fontsize=8)
        axis.set_title(f"{_scenario_title(scenario)}, K={budget}")
        axis.set_ylabel("Held-out modeled coverage (%)")
        axis.set_ylim(0, 100)
        axis.tick_params(axis="x", labelrotation=20)
    _legend(axes[0, 0])
    figure.suptitle("Held-out coverage on fresh route-choice seeds 92000–92019", fontsize=12)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_robust_gap(seed_rows: Sequence[Mapping[str, Any]], output: Path) -> None:
    """Robust minus pooled-shortest coverage on matched evaluation seeds."""
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.4), sharey=True)
    for axis, budget in zip(axes, (10, 20), strict=True):
        labels = []
        series = []
        for scenario in ("uniform", "commuter_proxy"):
            for limit, name in ((0.15, "15%"), (0.30, "30%")):
                gaps = _gaps(seed_rows, scenario, budget, limit)
                short = "Uniform" if scenario == "uniform" else "Commuter"
                labels.append(f"{short}\n{name}")
                series.append([100.0 * gap for gap in gaps])
        axis.axhline(0.0, color="#bdbdbd", linewidth=1)
        axis.boxplot(series, tick_labels=labels, showfliers=False)
        for index, values in enumerate(series, start=1):
            axis.scatter([index] * len(values), values, s=12, color=ROBUST, zorder=3)
        axis.set_title(f"K={budget}")
        axis.set_ylabel("Robust minus pooled shortest (percentage points)")
    figure.suptitle("Paired difference on fresh seeds. Positive means robust covers more.", fontsize=11)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_scenario_tradeoff(tradeoff: Sequence[Mapping[str, Any]], output: Path) -> None:
    """Uniform coverage against commuter coverage for each fixed placement."""
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.6), sharex=True, sharey=True)
    for axis, budget in zip(axes, (10, 20), strict=True):
        axis.plot([0, 100], [0, 100], color="#bdbdbd", linewidth=1)
        for row in tradeoff:
            if row.get("kind") not in {None, "scenario_tradeoff"}:
                continue
            if int(row["k"]) != budget or row["seed_block"] != "fresh":
                continue
            if row["condition"] not in {"shortest", "0.15"}:
                continue
            color = METHOD_COLOR[str(row["method"])]
            marker = "o" if row["condition"] == "shortest" else "s"
            axis.scatter(
                100.0 * float(row["uniform_coverage"]),
                100.0 * float(row["commuter_coverage"]),
                color=color,
                marker=marker,
                s=36,
                label=_label(str(row["method"])) if row["condition"] == "shortest" else None,
            )
        axis.set_title(f"K={budget}")
        axis.set_xlabel("Uniform held-out coverage (%)")
        axis.set_ylabel("Commuter held-out coverage (%)")
        axis.set_xlim(40, 100)
        axis.set_ylim(40, 100)
        axis.ticklabel_format(useOffset=False)
    _legend(axes[0])
    figure.suptitle("Circles are shortest paths. Squares are the mean of 15% alternatives.", fontsize=11)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_placement_map(
    background: Sequence[tuple[float, float]],
    pooled: Sequence[Sequence[tuple[float, float]]],
    robust: Sequence[Sequence[tuple[float, float]]],
    shared: Sequence[Sequence[tuple[float, float]]],
    output: Path,
) -> None:
    """K=10 pooled shortest-path counters and the robust counters."""
    figure, axis = plt.subplots(figsize=(6.4, 6.2))
    if background:
        xs, ys = zip(*background, strict=True)
        axis.scatter(xs, ys, s=4, color="#d9d9d9", linewidths=0)
    _lines(axis, pooled, POOLED, "Pooled shortest only")
    _lines(axis, robust, ROBUST, "Robust only")
    _lines(axis, shared, "#6a3d9a", "Selected by both")
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title("K=10 shared placements on the study streets")
    axis.ticklabel_format(useOffset=False)
    axis.set_aspect("equal", adjustable="datalim")
    _legend(axis)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_municipal(
    aggregate: Sequence[Mapping[str, Any]],
    existing: Sequence[Sequence[tuple[float, float]]],
    original: Sequence[Sequence[tuple[float, float]]],
    robust: Sequence[Sequence[tuple[float, float]]],
    output: Path,
) -> None:
    """Coverage of the 26 published sites and two sets of five additions."""
    figure, axes = plt.subplots(1, 2, figsize=(11.0, 4.8))
    axis = axes[0]
    methods = ("municipal_26", "municipal_original_plus5", "municipal_robust_plus5")
    labels = ("26 sites", "26 + original 5", "26 + robust 5")
    positions = list(range(len(methods)))
    width = 0.12
    conditions = (
        ("uniform", "shortest", SHORTEST, "Uniform shortest"),
        ("uniform", "0.15", ALT_15, "Uniform 15%"),
        ("commuter_proxy", "shortest", COMMUTER, "Commuter shortest"),
        ("commuter_proxy", "0.15", ROBUST, "Commuter 15%"),
    )
    fresh = [row for row in aggregate if row["seed_block"] == "fresh" and str(row["method"]).startswith("municipal_")]
    for index, (scenario, condition, color, label) in enumerate(conditions):
        offset = (index - 1.5) * width
        heights = []
        for method in methods:
            match = [
                row
                for row in fresh
                if row["method"] == method and row["scenario"] == scenario and row["condition"] == condition
            ]
            heights.append(100.0 * float(match[0]["coverage_mean"]) if match else 0.0)
        axis.bar([pos + offset for pos in positions], heights, width=width, color=color, label=label)
    axis.set_xticks(positions, labels)
    axis.set_ylim(0, 100)
    axis.set_ylabel("Held-out modeled coverage (%)")
    axis.set_title("Fresh seeds")
    _legend(axis)
    map_axis = axes[1]
    _lines(map_axis, existing, MUNICIPAL, "26 published sites")
    _lines(map_axis, original, UNIFORM, "Original additions")
    _lines(map_axis, robust, ROBUST, "Robust additions")
    map_axis.set_title("Additions are proposals, not installations")
    map_axis.set_xlabel("Longitude")
    map_axis.set_ylabel("Latitude")
    map_axis.ticklabel_format(useOffset=False)
    map_axis.set_aspect("equal", adjustable="datalim")
    _legend(map_axis)
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=140)
    plt.close(figure)


def _panel_methods(scenario: str) -> tuple[str, ...]:
    balanced = "uniform_balanced" if scenario == "uniform" else "commuter_balanced"
    return ("uniform_greedy", "commuter_greedy", "pooled_shortest", "robust_pooled", balanced)


def _coverage(
    rows: Sequence[Mapping[str, Any]],
    scenario: str,
    method: str,
    budget: int,
    condition: str,
) -> float:
    match = [
        row
        for row in rows
        if row["scenario"] == scenario
        and row["method"] == method
        and int(row["k"]) == budget
        and row["condition"] == condition
    ]
    if len(match) != 1:
        raise ValueError(f"expected one aggregate row for {scenario} {method} K={budget} {condition}")
    return float(match[0]["coverage_mean"])


def _gaps(rows: Sequence[Mapping[str, Any]], scenario: str, budget: int, limit: float) -> list[float]:
    pooled: dict[int, float] = {}
    robust: dict[int, float] = {}
    for row in rows:
        if row["seed_block"] != "fresh" or row["scenario"] != scenario or int(row["k"]) != budget:
            continue
        if row["condition"] != f"{limit:.2f}":
            continue
        seed = int(row["seed"])
        if row["method"] == "pooled_shortest":
            pooled[seed] = float(row["coverage"])
        elif row["method"] == "robust_pooled":
            robust[seed] = float(row["coverage"])
    if set(pooled) != set(robust) or not pooled:
        raise ValueError(f"missing paired seeds for {scenario} K={budget} {limit}")
    return [robust[seed] - pooled[seed] for seed in sorted(pooled)]


def _lines(axis: Any, segments: Sequence[Sequence[tuple[float, float]]], color: str, label: str) -> None:
    labeled = False
    for segment in segments:
        if len(segment) < 2:
            continue
        xs, ys = zip(*segment, strict=True)
        axis.plot(xs, ys, color=color, linewidth=2.2, solid_capstyle="round", label=label if not labeled else None)
        labeled = True


def _label(method: str) -> str:
    return METHOD_LABEL.get(method, method)


def _scenario_title(scenario: str) -> str:
    return "Uniform" if scenario == "uniform" else "Commuter proxy"


def _legend(axis: Any) -> None:
    handles, labels = axis.get_legend_handles_labels()
    if handles:
        axis.legend(handles, labels, fontsize=7, frameon=False)
