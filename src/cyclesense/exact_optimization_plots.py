"""Figures for the exact maximum-coverage benchmark."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

GREEDY = "#4daf4a"
EXACT = "#377eb8"
LIMITED = "#e41a1c"


def _scenario_label(scenario: str) -> str:
    return "Uniform" if scenario == "uniform" else "Commuter proxy"


def figure_calibration(rows: Sequence[dict], path: Path) -> None:
    """Greedy and MILP calibration coverage by budget."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), sharey=True)
    for axis, scenario in zip(axes, ("uniform", "commuter_proxy"), strict=True):
        subset = [row for row in rows if row["scenario"] == scenario and row["objective"] == "unweighted"]
        budgets = [row["k"] for row in subset]
        axis.plot(budgets, [100 * row["greedy_coverage"] for row in subset], "o-", color=GREEDY, label="Greedy")
        axis.plot(budgets, [100 * row["exact_coverage"] for row in subset], "s-", color=EXACT, label="MILP")
        for row in subset:
            if not row["proven_optimal"]:
                axis.scatter([row["k"]], [100 * row["exact_coverage"]], marker="x", color=LIMITED, zorder=3)
        axis.set_title(_scenario_label(scenario))
        axis.set_xlabel("Counter budget K")
        axis.set_ylim(0, 100)
        axis.set_xticks(budgets)
    axes[0].set_ylabel("Calibration coverage (%)")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_gaps(rows: Sequence[dict], path: Path) -> None:
    """Relative greedy gap for proven unweighted optima only."""
    fig, axis = plt.subplots(figsize=(6.2, 3.6))
    for scenario, marker in (("uniform", "o"), ("commuter_proxy", "s")):
        subset = [
            row
            for row in rows
            if row["scenario"] == scenario and row["objective"] == "unweighted" and row["proven_optimal"]
        ]
        axis.plot(
            [row["k"] for row in subset],
            [100 * row["relative_gap"] for row in subset],
            marker=marker,
            label=_scenario_label(scenario),
        )
    axis.set_xlabel("Counter budget K")
    axis.set_ylabel("Relative greedy gap (%)")
    axis.set_ylim(bottom=0)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_runtime(rows: Sequence[dict], path: Path) -> None:
    """MILP runtime against route count and against budget."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6))
    scale = [row for row in rows if row["objective"] == "scale"]
    axes[0].plot([row["n_routes"] for row in scale], [row["milp_seconds"] for row in scale], "o-", color=EXACT)
    axes[0].set_xlabel("Calibration routes")
    axes[0].set_ylabel("MILP runtime (seconds)")
    axes[0].set_title("Full candidate set, K = 10")
    primary = [row for row in rows if row["objective"] == "unweighted" and row["scenario"] == "uniform"]
    axes[1].plot([row["k"] for row in primary], [row["milp_seconds"] for row in primary], "o-", color=EXACT)
    axes[1].set_xlabel("Counter budget K")
    axes[1].set_title("500 uniform routes")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_heldout(rows: Sequence[dict], path: Path) -> None:
    """Held-out shortest-path coverage of the fixed sets."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), sharey=True)
    for axis, scenario in zip(axes, ("uniform", "commuter_proxy"), strict=True):
        subset = [row for row in rows if row["scenario"] == scenario and row["objective"] == "unweighted"]
        budgets = [row["k"] for row in subset]
        width = 1.6
        axis.bar([k - width / 2 for k in budgets], [100 * row["heldout_greedy"] for row in subset], width, color=GREEDY, label="Greedy")
        axis.bar([k + width / 2 for k in budgets], [100 * row["heldout_exact"] for row in subset], width, color=EXACT, label="MILP")
        axis.set_title(_scenario_label(scenario))
        axis.set_xlabel("Counter budget K")
        axis.set_ylim(0, 100)
        axis.set_xticks(budgets)
    axes[0].set_ylabel("Held-out coverage (%)")
    axes[1].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_map(segments: Sequence[tuple], greedy: Sequence[str], exact: Sequence[str], path: Path, title: str) -> None:
    """Street segments for the two K=10 sets."""
    greedy_ids = set(greedy)
    exact_ids = set(exact)
    fig, axis = plt.subplots(figsize=(6.4, 6.2))
    for edge_id, xs, ys in segments:
        if edge_id in greedy_ids and edge_id in exact_ids:
            color, width = "#984ea3", 2.6
        elif edge_id in exact_ids:
            color, width = EXACT, 2.6
        elif edge_id in greedy_ids:
            color, width = GREEDY, 2.6
        else:
            color, width = "#d0d0d0", 0.35
        axis.plot(xs, ys, color=color, linewidth=width, solid_capstyle="round")
    axis.plot([], [], color="#984ea3", linewidth=2.6, label="Both")
    axis.plot([], [], color=GREEDY, linewidth=2.6, label="Greedy only")
    axis.plot([], [], color=EXACT, linewidth=2.6, label="MILP only")
    axis.legend(frameon=False, loc="upper left")
    axis.set_aspect("equal")
    axis.set_axis_off()
    axis.set_title(title)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_weighted(rows: Sequence[dict], path: Path) -> None:
    """Greedy and MILP on the weighted objectives they actually share."""
    labels = []
    greedy_values = []
    exact_values = []
    for row in rows:
        labels.append(row["label"])
        greedy_values.append(100 * row["greedy_coverage"])
        exact_values.append(100 * row["exact_coverage"])
    fig, axis = plt.subplots(figsize=(8.6, 3.8))
    positions = list(range(len(labels)))
    axis.bar([item - 0.18 for item in positions], greedy_values, 0.36, color=GREEDY, label="Greedy")
    axis.bar([item + 0.18 for item in positions], exact_values, 0.36, color=EXACT, label="MILP")
    axis.set_xticks(positions, labels, rotation=25, ha="right")
    axis.set_ylabel("Calibration objective (%)")
    axis.set_ylim(0, 100)
    axis.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
