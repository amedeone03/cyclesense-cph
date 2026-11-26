"""Figures for community-balanced placement.

Coverage is a share of simulated routes. It is not an observed bicycle count.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "m4" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")

_K_COLORS = {5: "#7f7f7f", 10: "#377eb8", 20: "#4daf4a", 30: "#e41a1c"}


def _axes(scenarios: Sequence[str]):
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.4 * len(scenarios), 4.2), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    return figure, axes, plt


def plot_coverage_vs_lambda(rows: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    figure, axes, plt = _axes(scenarios)
    for axis, scenario in zip(axes, scenarios, strict=True):
        for budget, color in _K_COLORS.items():
            selected = [
                row for row in rows
                if row["scenario"] == scenario and int(row["k"]) == budget and row["source"] == "louvain"
            ]
            selected = sorted(selected, key=lambda row: float(row["lambda"]))
            axis.plot(
                [float(row["lambda"]) for row in selected],
                [float(row["heldout_coverage"]) for row in selected],
                marker="o",
                color=color,
                label=f"K={budget}",
            )
        axis.set_title(scenario)
        axis.set_xlabel("Community weight λ")
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Held-out modeled-route coverage")
    axes[-1].legend(fontsize=8)
    figure.suptitle("Held-out coverage versus community balancing")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_representation_vs_lambda(rows: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    figure, axes, plt = _axes(scenarios)
    for axis, scenario in zip(axes, scenarios, strict=True):
        for budget, color in _K_COLORS.items():
            selected = sorted(
                (
                    row for row in rows
                    if row["scenario"] == scenario and int(row["k"]) == budget and row["source"] == "louvain"
                ),
                key=lambda row: float(row["lambda"]),
            )
            axis.plot(
                [float(row["lambda"]) for row in selected],
                [float(row["large_represented_fraction"]) for row in selected],
                marker="o",
                color=color,
                label=f"K={budget}",
            )
        axis.set_title(scenario)
        axis.set_xlabel("Community weight λ")
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Share of size≥2 communities represented")
    axes[-1].legend(fontsize=8)
    figure.suptitle("Calibration community representation versus λ")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_tradeoff(rows: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    figure, axes, plt = _axes(scenarios)
    for axis, scenario in zip(axes, scenarios, strict=True):
        for row in rows:
            if row["scenario"] != scenario or row["source"] != "louvain":
                continue
            axis.scatter(
                float(row["heldout_coverage"]),
                float(row["large_represented_fraction"]),
                color=_K_COLORS[int(row["k"])],
                s=28 + 40 * float(row["lambda"]),
            )
        axis.set_title(scenario)
        axis.set_xlabel("Held-out coverage")
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Large-community representation")
    handles = [
        plt.Line2D([0], [0], marker="o", color=color, linestyle="", label=f"K={budget}")
        for budget, color in _K_COLORS.items()
    ]
    axes[-1].legend(handles=handles, fontsize=8)
    figure.suptitle("Coverage and community representation (marker size grows with λ)")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_robustness(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    labels = []
    matched = []
    shifted = []
    for row in rows:
        if int(row["k"]) != 10 or row["source"] != "louvain":
            continue
        if float(row["lambda"]) not in {0.0, 0.25, 0.5}:
            continue
        labels.append(f"{row['train_scenario'][:3]} λ={row['lambda']}")
        matched.append(float(row["matched_coverage"]))
        shifted.append(float(row["shifted_coverage"]))
    positions = list(range(len(labels)))
    axis.bar([pos - 0.18 for pos in positions], matched, width=0.36, label="Matched scenario", color="#4daf4a")
    axis.bar([pos + 0.18 for pos in positions], shifted, width=0.36, label="Other scenario", color="#377eb8")
    axis.set_xticks(positions, labels, rotation=30, ha="right")
    axis.set_ylim(0, 1)
    axis.set_ylabel("Held-out modeled-route coverage")
    axis.legend(fontsize=8)
    axis.grid(True, axis="y", linewidth=0.4, alpha=0.5)
    figure.suptitle("Cross-scenario coverage at K=10")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_ablation(rows: Sequence[Mapping[str, object]], scenarios: Sequence[str], output: Path) -> None:
    figure, axes, plt = _axes(scenarios)
    for axis, scenario in zip(axes, scenarios, strict=True):
        for source, color, label in (
            ("louvain", "#4daf4a", "Louvain weights"),
            ("shuffled", "#e41a1c", "Shuffled labels"),
        ):
            selected = sorted(
                (
                    row for row in rows
                    if row["scenario"] == scenario and int(row["k"]) == 10 and row["source"] == source
                ),
                key=lambda row: float(row["lambda"]),
            )
            axis.plot(
                [float(row["lambda"]) for row in selected],
                [float(row["heldout_coverage"]) for row in selected],
                marker="o",
                color=color,
                label=label,
            )
        axis.set_title(scenario)
        axis.set_xlabel("Community weight λ")
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Held-out coverage at K=10")
    axes[-1].legend(fontsize=8)
    figure.suptitle("Louvain communities versus size-matched shuffled labels")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)
