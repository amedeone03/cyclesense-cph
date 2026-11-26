"""Interactive map of municipal counting locations and complementary greedy sites.

The caller supplies the matched segments, the published AADT, and the coverage
figures. This module does not download counts, does not place counters, and
does not request public map tiles.
"""

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyclesense.interactive import _ATTRIBUTION, _add_basemap

EXISTING_COLOR = "#08306b"
FIRST_COLOR = "#238b45"
NEXT_COLOR = "#6a3d9a"
_NOT_A_SENSOR = (
    "Recurring municipal counting location. Not a confirmed permanently installed sensor."
)
_NOT_APPROVED = "Proposed under the modeled scenario. Not approved for installation."
_NOT_CAPTURE = "Held-out modeled-route coverage. Not observed cyclist capture."


def default_addition_visible(scenario: str, tranche: str) -> bool:
    """The default view is the first five uniform additions. Other groups stay optional."""
    return scenario == "uniform" and tranche == "first"


def addition_tranches(
    added_by_budget: Mapping[int, Sequence[str]],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split the K=5 and K=10 greedy lists into the first five and the next five.

    When K=10 begins with the K=5 edges, the next group is the remainder.
    Otherwise the next group is every K=10 edge that is not already in K=5.
    """
    if 5 not in added_by_budget or 10 not in added_by_budget:
        raise ValueError("addition tranches need the K=5 and K=10 edge lists")
    first = tuple(added_by_budget[5])
    ten = tuple(added_by_budget[10])
    if len(first) > 5 or len(ten) > 10:
        raise ValueError("K=5 and K=10 lists are longer than their budgets")
    if ten[: len(first)] == first:
        return first, ten[len(first) :]
    first_ids = set(first)
    return first, tuple(edge for edge in ten if edge not in first_ids)


def write_standout_map(
    existing: Sequence[Mapping[str, Any]],
    addition_layers: Sequence[Mapping[str, Any]],
    coverage: Sequence[Mapping[str, Any]],
    output: Path,
    *,
    boundary: Sequence[float] | None = None,
    basemap: Mapping[str, Any] | None = None,
    notes: Sequence[str] = (),
) -> Path:
    """Write the HTML map. Each site needs ``edge_id`` and a lat/lon ``line``."""
    import folium

    if not existing:
        raise ValueError("standout map needs at least one municipal counting location")
    existing_ids = _require_edges(existing, "municipal")
    for layer in addition_layers:
        overlap = existing_ids & _require_edges(
            layer["sites"], str(layer.get("name") or "addition")
        )
        if overlap:
            raise ValueError(
                f"an additional site repeats a municipal segment: {sorted(overlap)[:3]}"
            )

    center = _center(existing)
    fmap = folium.Map(
        location=center, zoom_start=15, tiles=None, control_scale=True, zoom_control=True
    )
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False, street_contrast="quiet")

    municipal = folium.FeatureGroup(
        name=f"Name-verified counting locations ({len(existing)})", show=True
    )
    for site in existing:
        _draw_site(
            municipal,
            site,
            color=EXISTING_COLOR,
            weight=6,
            popup_lines=_existing_popup(site),
            tooltip=(
                f"{site.get('street') or site.get('osm_name') or site['edge_id']}: "
                f"AADT {_format_aadt(site.get('aadt'))}"
            ),
        )
    municipal.add_to(fmap)

    for layer in addition_layers:
        group = folium.FeatureGroup(name=str(layer["name"]), show=bool(layer.get("show")))
        for site in layer["sites"]:
            _draw_site(
                group,
                site,
                color=str(layer.get("color") or FIRST_COLOR),
                weight=6,
                popup_lines=_proposed_popup(site),
                tooltip=f"{layer['name']}: {site.get('osm_name') or site['edge_id']}",
                dash=str(layer.get("dash") or ""),
            )
        group.add_to(fmap)

    folium.LayerControl(collapsed=True).add_to(fmap)
    _fit(fmap, existing, addition_layers, boundary)
    fmap.get_root().html.add_child(folium.Element(_chrome(existing, coverage, notes)))
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output


def _require_edges(sites: Sequence[Mapping[str, Any]], label: str) -> set[str]:
    edge_ids: set[str] = set()
    for site in sites:
        edge_id = str(site.get("edge_id") or "")
        line = list(site.get("line") or [])
        if not edge_id or len(line) < 2:
            raise ValueError(f"{label} site is missing an eligible-segment geometry")
        edge_ids.add(edge_id)
    return edge_ids


def _draw_site(
    group: Any,
    site: Mapping[str, Any],
    *,
    color: str,
    weight: int,
    popup_lines: list[str],
    tooltip: str,
    dash: str = "",
) -> None:
    import folium

    options: dict[str, Any] = {
        "color": color,
        "weight": weight,
        "opacity": 0.95,
        "pane": "markerPane",
    }
    if dash:
        options["dashArray"] = dash
    folium.PolyLine(
        [(float(lat), float(lon)) for lat, lon in site["line"]],
        tooltip=folium.Tooltip(str(tooltip), sticky=True),
        popup=folium.Popup("<br>".join(popup_lines), max_width=420),
        **options,
    ).add_to(group)


def _existing_popup(site: Mapping[str, Any]) -> list[str]:
    return [
        "<b>Name-verified municipal counting location</b>",
        html.escape(_NOT_A_SENSOR),
        f"Street: {html.escape(str(site.get('street') or ''))}",
        f"Count type: {html.escape(str(site.get('count_type') or ''))}",
        f"Year: {html.escape(str(site.get('year') or ''))}",
        f"Published bicycle AADT: {html.escape(_format_aadt(site.get('aadt')))}",
        (
            "Published coordinate: "
            f"{html.escape(_format_coord(site.get('latitude')))}, "
            f"{html.escape(_format_coord(site.get('longitude')))}"
        ),
        "<b>Physical edge ID</b>",
        f"<code>{html.escape(str(site['edge_id']))}</code>",
        f"OpenStreetMap name: {html.escape(str(site.get('osm_name') or '(unnamed)'))}",
        f"Snap distance: {html.escape(str(site.get('snap_m') if site.get('snap_m') is not None else ''))} m",
    ]


def _proposed_popup(site: Mapping[str, Any]) -> list[str]:
    lines = [
        "<b>Additional greedy segment</b>",
        html.escape(_NOT_APPROVED),
        f"Scenario: {html.escape(str(site.get('scenario') or ''))}",
        f"Order in the greedy list: {html.escape(str(site.get('rank') or ''))}",
        "<b>Physical edge ID</b>",
        f"<code>{html.escape(str(site['edge_id']))}</code>",
        f"OpenStreetMap name: {html.escape(str(site.get('osm_name') or '(unnamed)'))}",
        "Chosen on calibration routes after the municipal segments were treated as already covered.",
        "Held-out routes were not used to choose this segment.",
    ]
    gain = site.get("calibration_gain")
    if gain is not None:
        lines.append(
            "Calibration-route coverage added by this segment, after the municipal "
            f"segments and the earlier additions: {html.escape(_signed_points(float(gain)))}."
        )
        lines.append(
            "This increment is calibration coverage, not held-out coverage and not observed cyclists."
        )
    return lines


def _chrome(
    existing: Sequence[Mapping[str, Any]],
    coverage: Sequence[Mapping[str, Any]],
    notes: Sequence[str],
) -> str:
    rows = []
    for row in coverage:
        existing_coverage = float(row["existing"])
        plus_5 = float(row["plus_5"])
        plus_10 = float(row["plus_10"])
        label = html.escape(str(row["scenario"]))
        rows.append(
            "<tr>"
            f"<td>{label}</td>"
            f"<td>{_percent(existing_coverage)}</td>"
            f"<td>{_percent(plus_5)} ({_signed_points(plus_5 - existing_coverage)})</td>"
            f"<td>{_percent(plus_10)} ({_signed_points(plus_10 - existing_coverage)})</td>"
            "</tr>"
        )
    note_html = "".join(f"<p>{html.escape(note)}</p>" for note in notes)
    return f"""
    <div class="standout-legend">
      <div class="standout-legend-title">Shown by role</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{EXISTING_COLOR}"></span>Counting location</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{FIRST_COLOR}"></span>First five additions</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{NEXT_COLOR}"></span>Next five additions</div>
      <div class="standout-legend-note">Dashed lines are the commuter-proxy scenario.</div>
    </div>
    <div class="standout-panel">
      <b>Held-out modeled-route coverage</b>
      <div class="standout-panel-note">{len(existing)} name-verified segments. {_NOT_CAPTURE}</div>
      <table>
        <tr><th>Scenario</th><th>Existing</th><th>+ 5</th><th>+ 10</th></tr>
        {"".join(rows)}
      </table>
      <details>
        <summary>How to read this map</summary>
        <p>{html.escape(_NOT_A_SENSOR)} {_NOT_APPROVED}</p>
        <p>The table is held-out coverage of simulated routes. A popup increment, when shown, is the calibration-route coverage added by that one segment. The two numbers are not interchangeable.</p>
        <p>Open the layer control to switch uniform and commuter-proxy additions. Only the first five uniform additions are drawn at the start.</p>
        {note_html}
        <p>{html.escape(_ATTRIBUTION)}</p>
      </details>
    </div>
    <style>
      .leaflet-container {{ background: #ffffff; }}
      .leaflet-top.leaflet-left {{ z-index: 1000; }}
      .standout-legend, .standout-panel {{
        position: fixed; z-index: 900; background: rgba(255,255,255,0.96);
        border: 1px solid #bbb; font: 12px/1.4 sans-serif;
      }}
      .standout-legend {{
        right: 12px; bottom: 18px; padding: 8px 10px; max-width: min(240px, 46vw);
      }}
      .standout-legend-title {{ font-weight: 700; margin-bottom: 4px; }}
      .standout-legend-row {{ display: flex; align-items: center; gap: 6px; }}
      .standout-legend-note {{ margin-top: 4px; color: #333; }}
      .standout-swatch {{ width: 18px; height: 4px; flex: none; }}
      .standout-panel {{
        top: 10px; left: 52px; padding: 8px 10px;
        max-width: min(380px, calc(100vw - 70px));
        max-height: min(46vh, 320px); overflow: auto;
      }}
      .standout-panel-note {{ margin: 4px 0; }}
      .standout-panel table {{ border-collapse: collapse; margin: 4px 0 6px; width: 100%; }}
      .standout-panel th, .standout-panel td {{
        border-bottom: 1px solid #ddd; padding: 2px 6px 2px 0; text-align: left;
      }}
      .standout-panel details p {{ margin: 6px 0; }}
      @media (max-width: 720px) {{
        .standout-panel {{
          left: 46px; top: 8px; max-height: 32vh; max-width: calc(100vw - 120px);
        }}
        .standout-legend {{ right: 8px; left: auto; bottom: 28px; max-width: min(180px, 52vw); }}
      }}
    </style>
    """


def _fit(
    fmap: Any,
    existing: Sequence[Mapping[str, Any]],
    layers: Sequence[Mapping[str, Any]],
    boundary: Sequence[float] | None,
) -> None:
    points = [point for site in existing for point in site["line"]]
    for layer in layers:
        if not layer.get("show"):
            continue
        points.extend(point for site in layer["sites"] for point in site["line"])
    if points:
        latitudes = [float(point[0]) for point in points]
        longitudes = [float(point[1]) for point in points]
        fmap.fit_bounds(
            [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]],
            padding=(28, 28),
        )
        return
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))


def write_standout_static(
    existing: Sequence[Mapping[str, Any]],
    addition_layers: Sequence[Mapping[str, Any]],
    output: Path,
    *,
    context: Sequence[Sequence[tuple[float, float]]] = (),
    boundary: Sequence[float] | None = None,
) -> Path:
    """Write a static view of the same segment geometries used by the HTML map."""
    import os

    os.environ.setdefault("MPLBACKEND", "Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(9.2, 7.2))
    for line in context:
        if len(line) < 2:
            continue
        axis.plot(
            [float(point[0]) for point in line],
            [float(point[1]) for point in line],
            color="#d0d0d0",
            linewidth=0.4,
            solid_capstyle="round",
            zorder=1,
        )
    _plot_sites(axis, existing, EXISTING_COLOR, 2.2, "Counting location")
    for layer in addition_layers:
        _plot_sites(
            axis,
            layer["sites"],
            str(layer.get("color") or FIRST_COLOR),
            2.4,
            str(layer["name"]),
            dashed="commuter" in str(layer["name"]).casefold(),
        )
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        axis.set_xlim(west, east)
        axis.set_ylim(south, north)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("Longitude")
    axis.set_ylabel("Latitude")
    axis.set_title("Eligible segments, counting locations, and proposed additions", pad=10)
    axis.legend(fontsize=8, loc="lower right")
    axis.grid(True, linewidth=0.3, alpha=0.4)
    figure.text(
        0.01,
        0.01,
        "Street lines are OpenStreetMap geometries. Proposed sites are modeled selections, not approved installations.",
        fontsize=8,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output, dpi=140)
    plt.close(figure)
    return output


def _plot_sites(
    axis: Any,
    sites: Sequence[Mapping[str, Any]],
    color: str,
    width: float,
    label: str | None,
    dashed: bool = False,
) -> None:
    style = (0, (2, 1.5)) if dashed else "solid"
    labeled = False
    for site in sites:
        longitudes = [float(point[1]) for point in site["line"]]
        latitudes = [float(point[0]) for point in site["line"]]
        axis.plot(
            longitudes,
            latitudes,
            color=color,
            linewidth=width,
            linestyle=style,
            solid_capstyle="round",
            label=label if label and not labeled else None,
            zorder=2,
        )
        labeled = True


def _center(sites: Sequence[Mapping[str, Any]]) -> list[float]:
    points = [point for site in sites for point in site["line"]]
    return [
        sum(float(point[0]) for point in points) / len(points),
        sum(float(point[1]) for point in points) / len(points),
    ]


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed_points(value: float) -> str:
    points = value * 100
    return f"{points:+.1f} pp"


def _format_aadt(value: object) -> str:
    if value is None or value == "":
        return ""
    number = float(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}"


def _format_coord(value: object) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.6f}"
