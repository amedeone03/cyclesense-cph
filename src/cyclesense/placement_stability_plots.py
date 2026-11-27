"""Figures for simulated counter-selection stability."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize

from cyclesense.interactive import _add_basemap, _edge_index, _linestring

_NOTE = "Simulated calibration draws. Not observed cyclist demand."


def frequency_color(frequency: float) -> str:
    """Gray at zero. YlOrRd darkens as frequency approaches 1."""
    if frequency <= 0:
        return "#d0d0d0"
    red, green, blue, _alpha = plt.get_cmap("YlOrRd")(0.12 + 0.88 * min(frequency, 1.0))
    return f"#{int(red * 255):02x}{int(green * 255):02x}{int(blue * 255):02x}"


def physical_lines(graph: object) -> dict[str, list[tuple[float, float]]]:
    """One lat/lon line per physical id. Opposite directions are not redrawn."""
    lines = {}
    for edge_id, (u_node, v_node, data) in _edge_index(graph).items():
        line = _linestring(graph, u_node, v_node, data)
        if line:
            lines[edge_id] = line
    return lines


def figure_heatmap(
    lines: Mapping[str, Sequence[tuple[float, float]]],
    frequencies: Mapping[str, float],
    path: Path,
    title: str,
) -> None:
    """Gray network with selected segments colored by selection frequency."""
    fig, axis = plt.subplots(figsize=(7.2, 7.0))
    for edge_id, line in lines.items():
        if edge_id in frequencies:
            continue
        lons = [point[1] for point in line]
        lats = [point[0] for point in line]
        axis.plot(lons, lats, color="#d9d9d9", linewidth=0.35, solid_capstyle="round", zorder=1)
    for edge_id, frequency in sorted(frequencies.items(), key=lambda item: item[1]):
        line = lines.get(edge_id)
        if not line:
            continue
        lons = [point[1] for point in line]
        lats = [point[0] for point in line]
        axis.plot(
            lons,
            lats,
            color=frequency_color(frequency),
            linewidth=0.8 + 2.4 * frequency,
            solid_capstyle="round",
            zorder=2,
        )
    axis.set_aspect("equal")
    axis.set_axis_off()
    axis.set_title(title)
    mappable = ScalarMappable(norm=Normalize(0, 1), cmap=plt.get_cmap("YlOrRd"))
    colorbar = fig.colorbar(mappable, ax=axis, fraction=0.035, pad=0.02)
    colorbar.set_label("Selection frequency")
    fig.text(0.02, 0.02, _NOTE + " Gray segments were never selected.", fontsize=8, color="#444444")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_frequency_histograms(
    groups: Sequence[tuple[str, Sequence[float], int]],
    n_replicates: int,
    path: Path,
) -> None:
    """Histograms of positive frequencies. The zero count is annotated."""
    bins = [index / n_replicates for index in range(1, n_replicates + 2)]
    fig, axes = plt.subplots(2, 2, figsize=(8.4, 6.2), sharex=True)
    for axis, (label, values, n_zero) in zip(axes.ravel(), groups, strict=False):
        axis.hist(values, bins=bins, color="#fd8d3c", edgecolor="white")
        axis.set_title(f"{label}\n{n_zero} segments never selected", fontsize=9)
        axis.set_xlim(0, 1)
    for axis in axes[1]:
        axis.set_xlabel("Selection frequency")
    axes[0, 0].set_ylabel("Segments")
    axes[1, 0].set_ylabel("Segments")
    fig.suptitle(_NOTE, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_jaccard(groups: Sequence[tuple[str, Sequence[float]]], path: Path) -> None:
    """Pairwise Jaccard similarity. The pairs are not independent."""
    fig, axis = plt.subplots(figsize=(8.6, 4.2))
    axis.boxplot(
        [values for _label, values in groups],
        tick_labels=[label for label, _values in groups],
        showfliers=False,
    )
    axis.set_ylabel("Pairwise Jaccard similarity")
    axis.set_ylim(0, 1)
    axis.tick_params(axis="x", rotation=25)
    axis.set_title("Each pair reuses replicates, so the boxes are descriptive")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_coverage(rows: Sequence[Mapping[str, float | str]], path: Path) -> None:
    """Calibration and held-out coverage of each fixed replicate set."""
    labels = list(dict.fromkeys(str(row["label"]) for row in rows))
    fig, axes = plt.subplots(1, 2, figsize=(9.2, 4.0), sharey=True)
    for axis, field, title in (
        (axes[0], "calibration", "Calibration"),
        (axes[1], "heldout", "Held-out"),
    ):
        data = [[100 * float(row[field]) for row in rows if row["label"] == label] for label in labels]
        axis.boxplot(data, tick_labels=labels, showfliers=False)
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=25)
        axis.set_ylim(0, 100)
    axes[0].set_ylabel("Modeled-route coverage (%)")
    fig.suptitle(_NOTE, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_canonical(groups: Sequence[tuple[str, Sequence[tuple[str, float]]]], path: Path) -> None:
    """Selection frequency of the saved canonical K=10 segments."""
    fig, axes = plt.subplots(1, len(groups), figsize=(4.2 * len(groups), 5.4), sharex=True)
    if len(groups) == 1:
        axes = [axes]
    for axis, (title, rows) in zip(axes, groups, strict=True):
        ordered = sorted(rows, key=lambda item: item[1])
        axis.barh(
            [label for label, _frequency in ordered],
            [100 * frequency for _label, frequency in ordered],
            color="#fd8d3c",
        )
        axis.set_xlim(0, 100)
        axis.set_title(title, fontsize=10)
        axis.set_xlabel("Selection frequency (%)")
    fig.suptitle(_NOTE, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def figure_overlap_vs_heldout(groups: Sequence[tuple[str, Sequence[float], Sequence[float]]], path: Path) -> None:
    """Descriptive scatter. Each point is a pair of replicates."""
    fig, axis = plt.subplots(figsize=(6.6, 4.2))
    for label, jaccard, difference in groups:
        axis.scatter(jaccard, [100 * value for value in difference], s=12, alpha=0.45, label=label)
    axis.set_xlabel("Pairwise Jaccard similarity")
    axis.set_ylabel("Absolute held-out difference (pp)")
    axis.set_xlim(0, 1)
    axis.legend(frameon=False, fontsize=8)
    axis.set_title("Pairs are not an independent sample")
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def write_frequency_map(
    graph: object,
    names: Mapping[str, str],
    frequencies: Mapping[str, float],
    counts: Mapping[str, int],
    n_replicates: int,
    path: Path,
    title: str,
    basemap: Mapping[str, object] | None,
) -> None:
    """Tile-free Folium map. Hover shows the physical id and the frequency."""
    import folium

    lines = physical_lines(graph)
    if not lines:
        raise ValueError("the routing graph has no drawable physical segments")
    points = [point for line in lines.values() for point in line]
    center = (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))
    fmap = folium.Map(location=center, zoom_start=14, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False, street_contrast="quiet")
    layer = folium.FeatureGroup(name=title, show=True)
    for edge_id, line in lines.items():
        frequency = float(frequencies.get(edge_id, 0.0))
        count = int(counts.get(edge_id, 0))
        name = names.get(edge_id) or "(unnamed)"
        folium.PolyLine(
            line,
            color=frequency_color(frequency),
            weight=1.2 + 4.0 * frequency,
            opacity=0.95,
            tooltip=folium.Tooltip(
                f"{html.escape(name)}<br>{html.escape(edge_id)}<br>{count} of {n_replicates} draws, {100 * frequency:.1f}%",
                sticky=True,
            ),
        ).add_to(layer)
    layer.add_to(fmap)
    fmap.get_root().html.add_child(
        folium.Element(
            "<div style='position:fixed;left:12px;bottom:12px;z-index:500;background:#fff;padding:8px 10px;"
            "border:1px solid #ccc;font:13px sans-serif;max-width:280px'>"
            f"<b>{html.escape(title)}</b><br>{html.escape(_NOTE)} "
            "Gray segments were not selected. Color darkens with selection frequency."
            "</div>"
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(path)
