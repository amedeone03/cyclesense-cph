"""Figures for modeled-route coverage attribution at the published counting sites.

The colors are simulated-route quantities. They are not published bicycle AADT
and they are not a recommendation to remove a counting site.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

NOTE = "Simulated routes. Not observed traffic and not a reason to remove a counting site."


def figure_site_values(
    lines: Mapping[str, Sequence[tuple[float, float]]],
    streets: Sequence[Sequence[Sequence[float]]],
    panels: Sequence[tuple[str, Mapping[str, float]]],
    path: Path,
    *,
    colorbar: str,
    title: str,
) -> None:
    """Color the 26 municipal segments on a shared scale."""
    vmax = max((max(values.values()) if values else 0.0) for _title, values in panels)
    fig, axes = plt.subplots(1, len(panels), figsize=(8.4, 4.6), squeeze=False)
    for axis, (panel_title, values) in zip(axes[0], panels, strict=True):
        _base(axis, lines, streets)
        for edge_id, value in values.items():
            _segment(axis, lines.get(edge_id), value, vmax)
        axis.set_title(panel_title, fontsize=10)
        axis.set_axis_off()
        axis.set_aspect("equal")
    scalar = ScalarMappable(norm=Normalize(vmin=0, vmax=max(vmax, 1e-6)), cmap="YlOrRd")
    fig.colorbar(scalar, ax=axes[0], fraction=0.03, pad=0.02, label=colorbar)
    fig.suptitle(title)
    fig.text(0.02, 0.01, NOTE, fontsize=8, color="#444444")
    fig.subplots_adjust(left=0.02, right=0.90, bottom=0.08, top=0.88, wspace=0.08)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_multiplicity(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Routes touching zero, one, two, or three or more municipal segments."""
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.6), sharey=True)
    buckets = ("0", "1", "2", "3+")
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        for split, color, label in (("calibration", "#2457a6", "Calibration"), ("evaluation", "#e09a3e", "Held-out")):
            subset = {
                str(row["bucket"]): float(row["share"])
                for row in rows
                if row["scenario"] == scenario and row["split"] == split
            }
            axis.plot(buckets, [100 * subset[bucket] for bucket in buckets], "o-", color=color, label=label)
        axis.set_title(title)
        axis.set_xlabel("Municipal segments on a simulated route")
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Share of simulated routes (%)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Coverage multiplicity")
    fig.text(0.02, 0.01, NOTE, fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.05, 1, 0.94))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_three_metrics(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Traversal, unique coverage, and Shapley on the calibration routes."""
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.8), sharex=True, sharey=True)
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        subset = [row for row in rows if row["scenario"] == scenario and row["split"] == "calibration"]
        points = axis.scatter(
            [100 * float(row["traversal_fraction"]) for row in subset],
            [100 * float(row["unique_fraction"]) for row in subset],
            s=[40 + 18 * float(row["shapley_pp"]) for row in subset],
            c=[float(row["shapley_pp"]) for row in subset],
            cmap="YlOrRd",
            edgecolor="#333333",
            linewidth=0.3,
        )
        if scenario == "commuter_proxy":
            fig.colorbar(points, ax=axes, fraction=0.03, pad=0.02, label="Shapley (percentage points)")
        axis.plot([0, 24], [0, 24], color="#bbbbbb", linewidth=0.6)
        axis.set_xlim(0, 24)
        axis.set_ylim(0, 24)
        axis.set_title(title)
        axis.set_xlabel("Direct traversal (%)")
    axes[0].set_ylabel("Unique coverage (%)")
    fig.suptitle("Traversal, unique coverage, and Shapley (marker color)")
    fig.text(0.02, 0.01, "Calibration routes. A point below the line shares routes with other sites.", fontsize=8, color="#444444")
    fig.subplots_adjust(left=0.08, right=0.88, bottom=0.14, top=0.86, wspace=0.16)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_cumulative(series: Sequence[Mapping[str, object]], path: Path) -> None:
    """Ordered greedy coverage, with unordered five-site sets marked at step 5."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), sharey=True)
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Trained on uniform", "Trained on commuter proxy"), strict=True):
        for split, color, label in (("calibration", "#163e72", "Calibration"), ("evaluation", "#e09a3e", "Held-out")):
            points = [
                row
                for row in series
                if row["training_scenario"] == scenario
                and row["evaluation_scenario"] == scenario
                and row["evaluation_split"] == split
                and row["method"] == "greedy"
                and row["attribution"] == "ordered"
            ]
            axis.plot(
                [int(row["step"]) for row in points],
                [100 * float(row["coverage"]) for row in points],
                "o-",
                color=color,
                label=label,
                markersize=3.5,
            )
        axis.set_title(title)
        axis.set_xlabel("Added segments, greedy order")
        axis.set_xlim(-0.3, 10.3)
    axes[0].set_ylabel("Modeled-route coverage (%)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Coverage as greedy segments are added to the 26 sites")
    fig.text(0.02, 0.01, "Held-out gains were not optimized. " + NOTE, fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_overlap(
    labels: Sequence[str],
    matrices: Sequence[tuple[str, Sequence[Sequence[float]]]],
    path: Path,
) -> None:
    """Jaccard overlap of calibration route-incidence sets."""
    fig, axes = plt.subplots(1, len(matrices), figsize=(11.2, 5.6))
    image = None
    cmap = plt.get_cmap("Blues").copy()
    cmap.set_bad("#f4f4f4")
    for axis, (title, matrix) in zip(axes, matrices, strict=True):
        image = axis.imshow(np.ma.masked_invalid(np.asarray(matrix, dtype=float)), cmap=cmap, vmin=0, vmax=1, interpolation="nearest")
        axis.set_title(title, fontsize=10)
        axis.set_xticks(range(len(labels)), labels, rotation=90, fontsize=5.5)
        axis.set_yticks(range(len(labels)), labels, fontsize=5.5)
    if image is not None:
        fig.colorbar(image, ax=axes, fraction=0.03, pad=0.02, label="Jaccard of simulated routes")
    fig.suptitle("Pairwise modeled-route overlap")
    fig.text(0.02, 0.005, "Route incidence, not street geometry. " + NOTE, fontsize=8, color="#444444")
    fig.subplots_adjust(left=0.16, right=0.90, bottom=0.28, top=0.88, wspace=0.35)
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _base(axis, lines, streets) -> None:
    for line in streets:
        if len(line) < 2:
            continue
        axis.plot([point[0] for point in line], [point[1] for point in line], color="#e4e0d8", linewidth=0.35, zorder=0)
    for line in lines.values():
        if len(line) < 2:
            continue
        axis.plot([point[1] for point in line], [point[0] for point in line], color="#eceae4", linewidth=0.45, zorder=1)


def _segment(axis, line, value: float, vmax: float) -> None:
    if not line or len(line) < 2:
        return
    color = "#bdbdbd" if value <= 0 else plt.get_cmap("YlOrRd")(0.15 + 0.85 * (value / vmax if vmax else 0))
    axis.plot(
        [point[1] for point in line],
        [point[0] for point in line],
        color=color,
        linewidth=2.4,
        solid_capstyle="round",
        zorder=2,
    )
