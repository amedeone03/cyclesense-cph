"""Figures for the M2 placement comparison.

The curves are coverage of simulated routes. They are not observed bicycle volumes.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from cyclesense.placement import METHOD_LABELS, METHODS

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "m2" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")

_COLORS = {
    "random": "#7f7f7f",
    "geographical_kmeans": "#e41a1c",
    "route_frequency": "#377eb8",
    "greedy": "#4daf4a",
}


def _grouped(
    records: Sequence[Mapping[str, object]],
    scenario: str,
    method: str,
) -> dict[int, list[float]]:
    grouped: dict[int, list[float]] = {}
    for record in records:
        if record["scenario"] != scenario or record["method"] != method:
            continue
        grouped.setdefault(int(record["k"]), []).append(float(record["heldout_coverage"]))
    return grouped


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def plot_coverage(records: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.2), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios):
        for method in METHODS:
            grouped = _grouped(records, scenario, method)
            budgets = sorted(grouped)
            means = [_mean(grouped[budget]) for budget in budgets]
            axis.plot(
                budgets,
                means,
                marker="o",
                color=_COLORS[method],
                label=METHOD_LABELS[method],
            )
            if any(len(grouped[budget]) > 1 for budget in budgets):
                lows = [min(grouped[budget]) for budget in budgets]
                highs = [max(grouped[budget]) for budget in budgets]
                axis.fill_between(budgets, lows, highs, color=_COLORS[method], alpha=0.15)
        axis.set_title(scenario)
        axis.set_xlabel("Counter budget K")
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Held-out modeled-route coverage")
    axes[-1].legend(fontsize=8, loc="lower right")
    figure.suptitle("Held-out coverage versus budget (simulated routes, not observed trips)")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_runtime(records: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.2), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios):
        for method in METHODS:
            grouped: dict[int, list[float]] = {}
            for record in records:
                if record["scenario"] == scenario and record["method"] == method:
                    grouped.setdefault(int(record["k"]), []).append(float(record["runtime_s"]))
            budgets = sorted(grouped)
            axis.plot(
                budgets,
                [_mean(grouped[budget]) for budget in budgets],
                marker="o",
                color=_COLORS[method],
                label=METHOD_LABELS[method],
            )
        axis.set_title(scenario)
        axis.set_xlabel("Counter budget K")
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Selection time (seconds)")
    axes[-1].legend(fontsize=8, loc="upper left")
    figure.suptitle("Selection runtime (evaluation time excluded)")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_saturation(records: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    """Marginal held-out coverage gained at each budget after the smallest K."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.2), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios):
        for method in METHODS:
            grouped = _grouped(records, scenario, method)
            budgets = sorted(grouped)
            means = [_mean(grouped[budget]) for budget in budgets]
            steps = budgets[1:]
            gains = [means[index] - means[index - 1] for index in range(1, len(means))]
            axis.plot(steps, gains, marker="o", color=_COLORS[method], label=METHOD_LABELS[method])
        axis.axhline(0, color="#bbbbbb", linewidth=0.8)
        axis.set_title(scenario)
        axis.set_xlabel("Counter budget K")
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Gain in held-out coverage from the previous K")
    axes[-1].legend(fontsize=8, loc="upper right")
    figure.suptitle("Coverage saturation: marginal held-out gain")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)
