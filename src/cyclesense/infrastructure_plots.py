"""Figures for the mapped-infrastructure placement study.

Coverage in these figures is a share of simulated routes. The classes describe
OpenStreetMap tags, not a field survey of installed cycling facilities.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

COLORS = {
    "dedicated": "#0b6e4f",
    "explicit_facility": "#2457a6",
    "other_routable": "#c8c2b6",
    "unknown": "#e09a3e",
    "ambiguous": "#7a2e2e",
}
LABELS = {
    "dedicated": "Dedicated cycleway",
    "explicit_facility": "Tagged cycling facility",
    "other_routable": "Other bicycle-routable",
    "unknown": "Unknown facility",
    "ambiguous": "Ambiguous tags",
    "unrestricted": "Unrestricted",
    "explicit_facility_policy": "Explicit facilities",
}
NOTE = "Simulated routes on mapped streets. Tags do not certify an installation site."


def figure_classification(
    lines: Mapping[str, Sequence[tuple[float, float]]],
    categories: Mapping[str, str],
    streets: Sequence[Sequence[Sequence[float]]],
    path: Path,
) -> None:
    """Color every eligible segment by its infrastructure class."""
    fig, axis = plt.subplots(figsize=(7.4, 7.2))
    _streets(axis, streets)
    _network(axis, lines, "#eceae4", 0.35)
    for category in ("other_routable", "unknown", "ambiguous", "explicit_facility", "dedicated"):
        _class_lines(axis, lines, categories, category, 1.3 if category != "other_routable" else 0.7)
    _legend(axis, ("dedicated", "explicit_facility", "other_routable", "unknown", "ambiguous"))
    axis.set_title("Mapped infrastructure class of eligible segments")
    _finish(fig, axis, path)


def figure_placements(
    lines: Mapping[str, Sequence[tuple[float, float]]],
    panels: Sequence[tuple[str, Sequence[str], Sequence[str]]],
    streets: Sequence[Sequence[Sequence[float]]],
    path: Path,
) -> None:
    """Shared and unique K=10 counters for unrestricted and restricted placements."""
    fig, axes = plt.subplots(2, 2, figsize=(8.6, 8.2))
    for axis, (title, left, right) in zip(axes.ravel(), panels, strict=True):
        _streets(axis, streets)
        _network(axis, lines, "#eceae4", 0.3)
        shared = set(left) & set(right)
        _draw(axis, lines, set(left) - shared, "#4daf4a", 2.0)
        _draw(axis, lines, set(right) - shared, "#2457a6", 2.0)
        _draw(axis, lines, shared, "#6a3d9a", 2.4)
        axis.set_title(title, fontsize=10)
        axis.set_axis_off()
        axis.set_aspect("equal")
    axes[0, 0].plot([], [], color="#4daf4a", linewidth=2, label="Unrestricted only")
    axes[0, 0].plot([], [], color="#2457a6", linewidth=2, label="Restricted only")
    axes[0, 0].plot([], [], color="#6a3d9a", linewidth=2, label="Shared")
    axes[0, 0].legend(frameon=False, fontsize=8, loc="lower left")
    fig.suptitle("K = 10 greedy placements")
    fig.text(0.02, 0.01, NOTE, fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.03, 1, 0.97))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_coverage(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Held-out modeled-route coverage against budget for each feasible policy."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), sharey=True)
    colors = {"unrestricted": "#4daf4a", "explicit_facility": "#2457a6", "dedicated": "#0b6e4f"}
    for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy"), strict=True):
        for policy, label in (
            ("unrestricted", "Unrestricted"),
            ("explicit_facility", "Explicit facilities"),
            ("dedicated", "Dedicated cycleways"),
        ):
            subset = [
                row
                for row in rows
                if row["scenario"] == scenario and row["policy"] == policy and row["status"] == "feasible"
            ]
            axis.plot(
                [int(row["k"]) for row in subset],
                [100 * float(row["heldout_coverage"]) for row in subset],
                "o-",
                color=colors[policy],
                label=label,
            )
        axis.set_title(title)
        axis.set_xlabel("Counter budget K")
        axis.set_xticks([5, 10, 20])
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Held-out modeled-route coverage (%)")
    axes[1].legend(frameon=False, fontsize=8)
    fig.suptitle("Coverage of simulated held-out routes")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_availability(
    categories: Mapping[str, int],
    policies: Sequence[Mapping[str, object]],
    total: int,
    path: Path,
) -> None:
    """Tag classes and the number of candidates each policy keeps."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8))
    names = ["dedicated", "explicit_facility", "other_routable", "unknown", "ambiguous"]
    axes[0].barh(
        [LABELS[name] for name in names],
        [100 * categories.get(name, 0) / total for name in names],
        color=[COLORS[name] for name in names],
    )
    axes[0].set_xlabel("Share of 1,047 eligible segments (%)")
    axes[0].set_xlim(0, 100)
    axes[1].bar(
        ["Unrestricted", "Explicit\nfacilities", "Dedicated\ncycleways"],
        [int(row["n_permitted"]) for row in policies],
        color=["#4daf4a", "#2457a6", "#0b6e4f"],
    )
    axes[1].set_ylabel("Permitted candidates")
    fig.suptitle("Infrastructure tags and candidate policies")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_municipal(rows: Sequence[Mapping[str, object]], path: Path) -> None:
    """Held-out coverage of the 26 sites and each five-site addition."""
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.8), sharey=True)
    labels = ["26 sites", "26 + unrestricted", "26 + explicit", "26 + dedicated"]
    keys = ("existing", "unrestricted", "explicit_facility", "dedicated")
    for axis, scenario, field, title in zip(
        axes,
        ("uniform", "commuter_proxy"),
        ("heldout_uniform", "heldout_commuter"),
        ("Trained on uniform", "Trained on commuter proxy"),
        strict=True,
    ):
        values = []
        for key in keys:
            match = next(row for row in rows if row["training_scenario"] == scenario and row["policy"] == key)
            values.append(100 * float(match[field]))
        axis.bar(labels, values, color=["#163e72", "#4daf4a", "#2457a6", "#0b6e4f"])
        axis.tick_params(axis="x", labelrotation=20)
        axis.set_title(title)
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Held-out coverage in the training scenario (%)")
    fig.suptitle("Published sites plus five proposed segments")
    fig.text(0.02, 0.01, "Proposed segments are not approved installation sites. " + NOTE, fontsize=8, color="#444444")
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    fig.savefig(path, dpi=160)
    plt.close(fig)


def _streets(axis, streets: Sequence[Sequence[Sequence[float]]]) -> None:
    for line in streets:
        if len(line) < 2:
            continue
        axis.plot([point[0] for point in line], [point[1] for point in line], color="#e4e0d8", linewidth=0.4, zorder=0)


def _network(axis, lines, color: str, width: float) -> None:
    for line in lines.values():
        if len(line) < 2:
            continue
        axis.plot([point[1] for point in line], [point[0] for point in line], color=color, linewidth=width, solid_capstyle="round", zorder=1)


def _class_lines(axis, lines, categories, category: str, width: float) -> None:
    chosen = [edge_id for edge_id, label in categories.items() if label == category]
    _draw(axis, lines, chosen, COLORS[category], width)


def _draw(axis, lines, edge_ids, color: str, width: float) -> None:
    for edge_id in edge_ids:
        line = lines.get(edge_id)
        if not line or len(line) < 2:
            continue
        axis.plot(
            [point[1] for point in line],
            [point[0] for point in line],
            color=color,
            linewidth=width,
            solid_capstyle="round",
            zorder=2,
        )


def _legend(axis, categories: Sequence[str]) -> None:
    for category in categories:
        axis.plot([], [], color=COLORS[category], linewidth=2, label=LABELS[category])
    axis.legend(frameon=False, fontsize=8, loc="lower left")


def _finish(fig, axis, path: Path) -> None:
    axis.set_axis_off()
    axis.set_aspect("equal")
    fig.text(0.02, 0.02, NOTE, fontsize=8, color="#444444")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
