"""Final validation figures.

Coverage is a share of simulated routes. Whiskers are percentiles of those
simulations, not a confidence interval for observed cyclists.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "m5" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")

GREEDY = "#4daf4a"
BALANCED_025 = "#984ea3"
BALANCED_050 = "#377eb8"
SHUFFLE = "#bdbdbd"
EXACT = "#4daf4a"
LSH = "#e41a1c"
SCENARIO_COLOR = {"uniform": "#4daf4a", "commuter_proxy": "#377eb8"}


def _save(figure, output: Path, plt) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_coverage_vs_budget(rows: Sequence[Mapping[str, float | str]], output: Path) -> None:
    """Independent-sample mean held-out coverage against counter budget."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.2), sharey=True)
    styles = {
        0.0: (GREEDY, "Standard greedy"),
        0.25: (BALANCED_025, "Balanced λ=0.25"),
        0.5: (BALANCED_050, "Balanced λ=0.5"),
    }
    for axis, scenario in zip(axes, ("uniform", "commuter_proxy"), strict=True):
        for lam, (color, label) in styles.items():
            selected = sorted(
                (
                    row for row in rows
                    if row["scenario"] == scenario and float(row["lambda"]) == lam and row["role"] == "matched"
                ),
                key=lambda row: int(row["k"]),
            )
            axis.errorbar(
                [int(row["k"]) for row in selected],
                [float(row["mean"]) for row in selected],
                yerr=[
                    [float(row["mean"]) - float(row["p05"]) for row in selected],
                    [float(row["p95"]) - float(row["mean"]) for row in selected],
                ],
                marker="o",
                color=color,
                label=label,
                capsize=3,
            )
        axis.set_title(scenario)
        axis.set_xlabel("Counter budget K")
        axis.set_ylim(0, 1)
        axis.set_xticks([5, 10, 20, 30])
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Held-out coverage on new samples")
    axes[1].legend(fontsize=8)
    figure.suptitle("Simulated coverage versus budget (whiskers: 5th–95th percentile)")
    _save(figure, output, plt)


def plot_coverage_vs_lambda(rows: Sequence[Mapping[str, float | str]], output: Path) -> None:
    """Original M4 held-out and calibration coverage against lambda."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.2), sharey=True)
    colors = {5: "#7f7f7f", 10: "#377eb8", 20: "#4daf4a", 30: "#e41a1c"}
    for axis, scenario in zip(axes, ("uniform", "commuter_proxy"), strict=True):
        for budget, color in colors.items():
            selected = sorted(
                (row for row in rows if row["scenario"] == scenario and int(row["k"]) == budget),
                key=lambda row: float(row["lambda"]),
            )
            axis.plot(
                [float(row["lambda"]) for row in selected],
                [float(row["heldout_coverage"]) for row in selected],
                marker="o",
                color=color,
                label=f"Held-out K={budget}",
            )
            axis.plot(
                [float(row["lambda"]) for row in selected],
                [float(row["calibration_coverage"]) for row in selected],
                marker=".",
                linestyle=":",
                color=color,
            )
        axis.set_title(scenario)
        axis.set_xlabel("Community weight λ")
        axis.set_ylim(0, 1)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Simulated route coverage")
    axes[1].legend(fontsize=7)
    figure.suptitle("Solid lines are held-out coverage. Dotted lines are calibration coverage.")
    _save(figure, output, plt)


def plot_shuffle_controls(rows: Sequence[Mapping[str, float | str]], output: Path) -> None:
    """Thirty shuffle draws against the saved Louvain placement, at K=10."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.2), sharey=True)
    for axis, metric, title in zip(
        axes,
        ("heldout_coverage", "large_represented_fraction"),
        ("Held-out coverage", "Calibration communities represented"),
        strict=True,
    ):
        position = 0
        labels = []
        for scenario in ("uniform", "commuter_proxy"):
            for lam in (0.25, 0.5):
                group = [
                    row for row in rows
                    if row["scenario"] == scenario
                    and float(row["lambda"]) == lam
                    and int(row["k"]) == 10
                    and row["metric"] == metric
                ]
                if not group:
                    continue
                values = [float(row["shuffle_value"]) for row in group]
                louvain = float(group[0]["louvain_value"])
                axis.boxplot(
                    [values],
                    positions=[position],
                    widths=0.6,
                    patch_artist=True,
                    boxprops={"facecolor": SHUFFLE},
                    medianprops={"color": "black"},
                    flierprops={"marker": "o", "markersize": 3},
                )
                axis.scatter([position], [louvain], color=BALANCED_025, zorder=3, s=28)
                labels.append(f"{scenario[:3]}\nλ={lam}")
                position += 1
        axis.set_xticks(range(len(labels)), labels)
        axis.set_ylim(0, 1)
        axis.set_title(title)
        axis.grid(True, axis="y", linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Share of simulated routes or communities")
    figure.suptitle("Boxes are 30 shuffled labels. Points are the Louvain weights.")
    _save(figure, output, plt)


def plot_cross_scenario(rows: Sequence[Mapping[str, float | str]], output: Path) -> None:
    """Matched and shifted coverage on the new samples, at K=10."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8.2, 4.4))
    labels = []
    matched = []
    shifted = []
    matched_err = []
    shifted_err = []
    for scenario in ("uniform", "commuter_proxy"):
        for lam, name in ((0.0, "greedy"), (0.25, "λ=0.25"), (0.5, "λ=0.5")):
            row = next(
                item for item in rows
                if item["train_scenario"] == scenario and float(item["lambda"]) == lam and int(item["k"]) == 10
            )
            labels.append(f"{scenario[:3]}\n{name}")
            matched.append(float(row["matched_mean"]))
            shifted.append(float(row["shifted_mean"]))
            matched_err.append(float(row["matched_std"]))
            shifted_err.append(float(row["shifted_std"]))
    positions = list(range(len(labels)))
    axis.bar(
        [pos - 0.16 for pos in positions],
        matched,
        width=0.32,
        yerr=matched_err,
        color=GREEDY,
        label="Matched scenario",
        capsize=2,
    )
    axis.bar(
        [pos + 0.16 for pos in positions],
        shifted,
        width=0.32,
        yerr=shifted_err,
        color=BALANCED_050,
        label="Other scenario",
        capsize=2,
    )
    axis.set_xticks(positions, labels)
    axis.set_ylim(0, 1)
    axis.set_ylabel("Mean coverage on new samples")
    axis.legend(fontsize=8)
    axis.grid(True, axis="y", linewidth=0.4, alpha=0.5)
    figure.suptitle("Cross-scenario coverage at K=10 (error bars: sample standard deviation)")
    _save(figure, output, plt)


def plot_paired_differences(rows: Sequence[Mapping[str, float | str]], output: Path) -> None:
    """Paired coverage difference from standard greedy on the same new samples."""
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.2), sharey=True)
    for axis, scenario in zip(axes, ("uniform", "commuter_proxy"), strict=True):
        for lam, color, label in (
            (0.25, BALANCED_025, "λ=0.25 − greedy"),
            (0.5, BALANCED_050, "λ=0.5 − greedy"),
        ):
            selected = sorted(
                (
                    row for row in rows
                    if row["scenario"] == scenario and float(row["lambda"]) == lam
                ),
                key=lambda row: int(row["k"]),
            )
            axis.errorbar(
                [int(row["k"]) for row in selected],
                [float(row["mean"]) for row in selected],
                yerr=[
                    [float(row["mean"]) - float(row["p05"]) for row in selected],
                    [float(row["p95"]) - float(row["mean"]) for row in selected],
                ],
                marker="o",
                color=color,
                label=label,
                capsize=3,
            )
        axis.axhline(0, color="black", linewidth=0.8)
        axis.set_title(scenario)
        axis.set_xlabel("Counter budget K")
        axis.set_xticks([5, 10, 20, 30])
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Held-out coverage difference")
    axes[1].legend(fontsize=8)
    figure.suptitle("Same new sample for both methods (whiskers: 5th–95th percentile)")
    _save(figure, output, plt)


def plot_scalability(rows: Sequence[Mapping[str, float | int]], output: Path) -> None:
    """End-to-end time for returning pairs at the Jaccard threshold."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 4.2))
    sizes = [int(row["n_routes"]) for row in rows]
    positions = list(range(len(sizes)))
    width = 0.36
    axis.bar(
        [pos - width / 2 for pos in positions],
        [float(row["exact_seconds"]) for row in rows],
        width=width,
        color=EXACT,
        label="Exact Jaccard",
    )
    axis.bar(
        [pos + width / 2 for pos in positions],
        [float(row["lsh_seconds"]) for row in rows],
        width=width,
        color=LSH,
        label="MinHash/LSH + verification",
    )
    axis.set_xticks(positions, [str(size) for size in sizes])
    axis.set_xlabel("Simulated routes")
    axis.set_ylabel("End-to-end seconds")
    axis.set_ylim(0, max(float(row["exact_seconds"]) for row in rows) * 1.25)
    axis.legend(fontsize=8)
    axis.grid(True, axis="y", linewidth=0.4, alpha=0.5)
    figure.suptitle("Time to return pairs with Jaccard at least 0.5")
    _save(figure, output, plt)
