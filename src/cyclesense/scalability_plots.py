"""Figures for the scalability study.

Only rows with status ``measured`` are drawn. A missing size is left blank.
No line is extended through a size that was not run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "outputs/scalability/mplconfig")
os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt

STREAMING = "#377eb8"
PRIMARY = "#e41a1c"
OTHER = {
    "lsh_64_32x2": "#984ea3",
    "lsh_64_16x4": "#ff7f00",
    "lsh_128_32x4": "#4daf4a",
}
LABELS = {
    "streaming_exact": "Streaming exact",
    "verified_lsh": "Verified LSH 32×16×2",
    "lsh_64_32x2": "LSH 64×32×2",
    "lsh_64_16x4": "LSH 64×16×4",
    "lsh_128_32x4": "LSH 128×32×4",
}


def plot_runtime(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Median end-to-end seconds. Whiskers are the minimum and maximum repeat."""
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    for method, color in _colors(rows):
        chosen = _method(rows, method)
        if not chosen:
            continue
        xs = [int(row["n_routes"]) for row in chosen]
        ys = [float(row["median_seconds"]) for row in chosen]
        low = [float(row["median_seconds"]) - float(row["min_seconds"]) for row in chosen]
        high = [float(row["max_seconds"]) - float(row["median_seconds"]) for row in chosen]
        axis.errorbar(xs, ys, yerr=[low, high], marker="o", color=color, label=LABELS.get(method, method))
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Simulated routes")
    axis.set_ylabel("Median end-to-end seconds")
    axis.set_title("Pipeline runtime, route generation excluded")
    axis.legend(fontsize=7)
    axis.grid(True, which="both", color="#eeeeee")
    _save(figure, output)


def plot_memory(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Median tracemalloc peak. This is not process RSS."""
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    for method, color in _colors(rows):
        chosen = [row for row in _method(rows, method) if row.get("median_peak_mb") not in ("", None)]
        if not chosen:
            continue
        xs = [int(row["n_routes"]) for row in chosen]
        ys = [float(row["median_peak_mb"]) for row in chosen]
        axis.plot(xs, ys, marker="o", color=color, label=LABELS.get(method, method))
    axis.set_xscale("log")
    axis.set_yscale("log")
    axis.set_xlabel("Simulated routes")
    axis.set_ylabel("Median tracemalloc peak (MB)")
    axis.set_title("Python-tracked peak allocation, measured apart from timing")
    axis.legend(fontsize=7)
    axis.grid(True, which="both", color="#eeeeee")
    _save(figure, output)


def plot_candidates(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Candidate pairs against the quadratic number of possible pairs."""
    figure, axes = plt.subplots(1, 2, figsize=(9.6, 4.2))
    methods = []
    for row in rows:
        method = str(row["method"])
        if method != "streaming_exact" and method not in methods and row.get("status") == "measured":
            methods.append(method)
    for method in methods:
        chosen = [
            row
            for row in rows
            if row["method"] == method and row.get("status") == "measured" and row.get("n_candidates") not in ("", None)
        ]
        color = PRIMARY if method == "verified_lsh" else OTHER.get(method, "#777777")
        xs = [int(row["n_possible_pairs"]) for row in chosen]
        axes[0].plot(xs, [int(row["n_candidates"]) for row in chosen], marker="o", color=color, label=LABELS.get(method, method))
        axes[1].plot(
            [int(row["n_routes"]) for row in chosen],
            [float(row["candidate_fraction"]) for row in chosen],
            marker="o",
            color=color,
            label=LABELS.get(method, method),
        )
    axes[0].set_xscale("log")
    axes[0].set_yscale("log")
    axes[0].set_xlabel("Possible route pairs")
    axes[0].set_ylabel("Candidate pairs")
    axes[0].set_title("Candidates versus all pairs")
    axes[1].set_xscale("log")
    axes[1].set_xlabel("Simulated routes")
    axes[1].set_ylabel("Candidate fraction of all pairs")
    axes[1].set_title("Share of pairs retrieved")
    axes[1].legend(fontsize=7)
    for axis in axes:
        axis.grid(True, which="both", color="#eeeeee")
    figure.suptitle("LSH candidate growth. Unmeasured sizes are omitted.", fontsize=10)
    _save(figure, output)


def plot_stages(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """One additional stage pass for the primary LSH banding and streaming exact."""
    figure, axes = plt.subplots(1, 2, figsize=(10.2, 4.4))
    panels = (
        ("verified_lsh", ("signatures_s", "buckets_s", "query_s", "verify_s", "graph_s", "louvain_s", "weights_s", "greedy_s")),
        ("streaming_exact", ("jaccard_s", "louvain_s", "weights_s", "greedy_s")),
    )
    names = {
        "signatures_s": "Signatures",
        "buckets_s": "Buckets",
        "query_s": "Query",
        "verify_s": "Verify",
        "graph_s": "Graph",
        "jaccard_s": "Thresholded Jaccard",
        "louvain_s": "Louvain",
        "weights_s": "Weights",
        "greedy_s": "Greedy",
    }
    palette = ["#e41a1c", "#984ea3", "#ff7f00", "#4daf4a", "#377eb8", "#a65628", "#f781bf", "#999999"]
    for axis, (method, keys) in zip(axes, panels, strict=True):
        chosen = [row for row in rows if row["method"] == method and row.get("status") == "measured"]
        if not chosen:
            axis.set_title(LABELS.get(method, method))
            continue
        bottoms = [0.0] * len(chosen)
        xs = list(range(len(chosen)))
        for index, key in enumerate(keys):
            heights = [float(row[key]) for row in chosen if row.get(key) not in ("", None)]
            if len(heights) != len(chosen):
                continue
            axis.bar(xs, heights, bottom=bottoms, color=palette[index], label=names[key], width=0.7)
            bottoms = [base + height for base, height in zip(bottoms, heights, strict=True)]
        axis.set_xticks(xs)
        axis.set_xticklabels([str(int(row["n_routes"])) for row in chosen], fontsize=8)
        axis.set_title(LABELS.get(method, method))
        axis.set_xlabel("Simulated routes")
        axis.legend(fontsize=6)
    axes[0].set_ylabel("Seconds in one stage pass")
    axes[1].set_ylabel("Seconds in one stage pass")
    figure.suptitle("Separate stage pass. The two panels do not share a scale.", fontsize=10)
    _save(figure, output)


def plot_graph_growth(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Edges, isolate share, and community count for measured graphs."""
    figure, axes = plt.subplots(1, 3, figsize=(10.6, 3.8))
    fields = (
        ("n_edges", "Similarity-graph edges"),
        ("isolate_fraction", "Isolate fraction"),
        ("n_communities", "Louvain communities"),
    )
    for axis, (field, title) in zip(axes, fields, strict=True):
        for method, color in (("streaming_exact", STREAMING), ("verified_lsh", PRIMARY)):
            chosen = [
                row
                for row in rows
                if row["method"] == method and row.get("status") == "measured" and row.get(field) not in ("", None)
            ]
            if not chosen:
                continue
            axis.plot(
                [int(row["n_routes"]) for row in chosen],
                [float(row[field]) for row in chosen],
                marker="o",
                color=color,
                label=LABELS[method],
            )
        axis.set_xscale("log")
        axis.set_title(title, fontsize=9)
        axis.set_xlabel("Simulated routes")
        axis.grid(True, color="#eeeeee")
    axes[0].legend(fontsize=7)
    figure.suptitle("Measured graphs only. Simulated routes on one fixed network.", fontsize=10)
    _save(figure, output)


def plot_agreement(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Full-graph recall and counter overlap where an exact graph was computed."""
    full = [
        row
        for row in rows
        if row.get("method") == "verified_lsh"
        and str(row.get("full_exact_available")) in {"1", "1.0"}
        and row.get("graph_edge_recall") not in ("", None)
    ]
    subset = [
        row
        for row in rows
        if row.get("method") == "verified_lsh" and str(row.get("subset_only")) in {"1", "1.0"} and row.get("subset_recall") not in ("", None)
    ]
    if not full and not subset:
        return
    figure, axes = plt.subplots(1, 2, figsize=(9.2, 4.0))
    if full:
        axes[0].plot(
            [int(row["n_routes"]) for row in full],
            [float(row["graph_edge_recall"]) for row in full],
            marker="o",
            color=PRIMARY,
            label="Full exact graph",
        )
        axes[1].plot(
            [int(row["n_routes"]) for row in full],
            [float(row["selected_jaccard_vs_exact"]) for row in full],
            marker="o",
            color=PRIMARY,
            label="Full exact graph",
        )
    if subset:
        axes[0].scatter(
            [int(row["n_routes"]) for row in subset],
            [float(row["subset_recall"]) for row in subset],
            marker="D",
            color="#999999",
            label="Subset only",
            zorder=3,
        )
    axes[0].set_ylim(0, 1.05)
    axes[1].set_ylim(0, 1.05)
    axes[0].set_ylabel("Graph-edge recall")
    axes[1].set_ylabel("Selected-counter Jaccard")
    for axis in axes:
        axis.set_xscale("log")
        axis.set_xlabel("Simulated routes")
        axis.grid(True, color="#eeeeee")
        axis.legend(fontsize=7)
    figure.suptitle("Agreement with streaming exact. Diamonds are subset checks, not full recall.", fontsize=10)
    _save(figure, output)


def _method(rows: Sequence[Mapping[str, object]], method: str) -> list[Mapping[str, object]]:
    return [row for row in rows if row.get("method") == method and row.get("status") == "measured"]


def _colors(rows: Sequence[Mapping[str, object]]) -> list[tuple[str, str]]:
    present = []
    for method, color in (
        ("streaming_exact", STREAMING),
        ("verified_lsh", PRIMARY),
        ("lsh_64_32x2", OTHER["lsh_64_32x2"]),
        ("lsh_64_16x4", OTHER["lsh_64_16x4"]),
        ("lsh_128_32x4", OTHER["lsh_128_32x4"]),
    ):
        if any(row.get("method") == method and row.get("status") == "measured" for row in rows):
            present.append((method, color))
    return present


def _save(figure, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)
