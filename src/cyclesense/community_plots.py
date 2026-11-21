"""Figures for exact similarity, LSH, and Louvain communities.

The curves describe simulated routes. They are not observed bicycle volumes.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "m3" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")


def plot_similarity_distribution(
    distributions: Mapping[str, Mapping[str, object]],
    output: Path,
) -> None:
    import matplotlib.pyplot as plt

    scenarios = list(distributions)
    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.0), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios, strict=True):
        distribution = distributions[scenario]
        width = float(distribution["bin_width"])
        counts = [int(count) for count in distribution["bin_counts"]]
        centers = [(index + 0.5) * width for index in range(len(counts))]
        axis.bar(centers, counts, width=width * 0.95, color="#4c78a8")
        axis.set_title(scenario)
        axis.set_xlabel("Exact Jaccard similarity")
        axis.set_xlim(0, 1)
    axes[0].set_ylabel("Calibration route pairs")
    figure.suptitle("Exact pairwise similarity (simulated routes)")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_lsh_tradeoff(records: Sequence[Mapping[str, object]], output: Path) -> None:
    import matplotlib.pyplot as plt

    scenarios = list(dict.fromkeys(str(record["scenario"]) for record in records))
    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.2), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    colors = {32: "#7f7f7f", 64: "#377eb8", 128: "#e41a1c"}
    for axis, scenario in zip(axes, scenarios, strict=True):
        for record in records:
            if str(record["scenario"]) != scenario or float(record["threshold"]) != 0.5:
                continue
            recall = record.get("recall")
            if recall is None:
                continue
            size = int(record["num_perm"])
            axis.scatter(
                float(record["candidate_fraction"]),
                float(recall),
                color=colors.get(size, "#333333"),
                s=36,
            )
        axis.set_title(scenario)
        axis.set_xlabel("Candidate pairs / all pairs")
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1.05)
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Recall of pairs with Jaccard ≥ 0.5")
    handles = [
        plt.Line2D([0], [0], marker="o", color=color, linestyle="", label=f"{size} permutations")
        for size, color in colors.items()
    ]
    axes[-1].legend(handles=handles, fontsize=8, loc="lower left")
    figure.suptitle("LSH retrieval against the exact calibration reference")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_graph_statistics(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    import matplotlib.pyplot as plt

    scenarios = list(dict.fromkeys(str(row["scenario"]) for row in rows))
    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.0), sharey=False)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios, strict=True):
        selected = [row for row in rows if str(row["scenario"]) == scenario]
        thresholds = [float(row["threshold"]) for row in selected]
        axis.plot(thresholds, [int(row["n_edges"]) for row in selected], marker="o", label="Edges", color="#377eb8")
        axis.plot(thresholds, [int(row["n_isolates"]) for row in selected], marker="s", label="Isolates", color="#e41a1c")
        axis.set_title(scenario)
        axis.set_xlabel("Jaccard threshold")
        axis.grid(True, linewidth=0.4, alpha=0.5)
    axes[0].set_ylabel("Count")
    axes[-1].legend(fontsize=8)
    figure.suptitle("Similarity-graph edges and isolated routes")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_community_sizes(sizes_by_scenario: Mapping[str, Sequence[int]], output: Path) -> None:
    import matplotlib.pyplot as plt

    scenarios = list(sizes_by_scenario)
    figure, axes = plt.subplots(1, len(scenarios), figsize=(5.2 * len(scenarios), 4.0), sharey=True)
    if len(scenarios) == 1:
        axes = [axes]
    for axis, scenario in zip(axes, scenarios, strict=True):
        sizes = sorted((int(size) for size in sizes_by_scenario[scenario]), reverse=True)
        axis.bar(range(1, len(sizes) + 1), sizes, color="#4daf4a")
        axis.set_title(scenario)
        axis.set_xlabel("Community rank")
    axes[0].set_ylabel("Routes in the community")
    figure.suptitle("Louvain community sizes at Jaccard 0.5, seed 42")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)


def plot_scalability(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.2, 4.2))
    exact_n = [int(row["n_routes"]) for row in rows]
    exact_t = [float(row["exact_seconds"]) for row in rows]
    lsh_t = [float(row["lsh_preprocess_seconds"]) + float(row["lsh_query_seconds"]) for row in rows]
    axis.plot(exact_n, exact_t, marker="o", label="Exact all pairs", color="#4c78a8")
    axis.plot(exact_n, lsh_t, marker="s", label="MinHash + LSH query", color="#e41a1c")
    axis.set_xlabel("Routes")
    axis.set_ylabel("Seconds")
    axis.grid(True, linewidth=0.4, alpha=0.5)
    axis.legend(fontsize=8)
    figure.suptitle("Similarity time on an independent uniform sample")
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=120)
    plt.close(figure)
