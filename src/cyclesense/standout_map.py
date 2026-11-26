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
_NOT_A_SENSOR = "Recurring municipal counting location. Not a confirmed permanently installed sensor."
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
        overlap = existing_ids & _require_edges(layer["sites"], str(layer.get("name") or "addition"))
        if overlap:
            raise ValueError(f"an additional site repeats a municipal segment: {sorted(overlap)[:3]}")

    center = _center(existing)
    fmap = folium.Map(location=center, zoom_start=15, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False)

    municipal = folium.FeatureGroup(name=f"Name-verified counting locations ({len(existing)})", show=True)
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
                weight=5,
                popup_lines=_proposed_popup(site),
                tooltip=f"{layer['name']}: {site.get('osm_name') or site['edge_id']}",
            )
        group.add_to(fmap)

    folium.LayerControl(collapsed=False).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
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


def _draw_site(group: Any, site: Mapping[str, Any], *, color: str, weight: int, popup_lines: list[str], tooltip: str) -> None:
    import folium

    folium.PolyLine(
        [(float(lat), float(lon)) for lat, lon in site["line"]],
        color=color,
        weight=weight,
        opacity=0.95,
        pane="markerPane",
        tooltip=folium.Tooltip(str(tooltip), sticky=True),
        popup=folium.Popup("<br>".join(popup_lines), max_width=460),
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
    return [
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


def _chrome(existing: Sequence[Mapping[str, Any]], coverage: Sequence[Mapping[str, Any]], notes: Sequence[str]) -> str:
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
    note_html = "".join(f"{html.escape(note)}<br>" for note in notes)
    return f"""
    <div class="standout-legend">
      <div class="standout-legend-title">Counter role</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{EXISTING_COLOR}"></span>Name-verified counting location</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{FIRST_COLOR}"></span>Additional 5, marginal coverage</div>
      <div class="standout-legend-row"><span class="standout-swatch" style="background:{NEXT_COLOR}"></span>Next 5 additions</div>
    </div>
    <div class="standout-panel">
      <b>Municipal counts and complementary placement</b><br>
      {len(existing)} name-verified locations, drawn on their matched eligible segments.<br>
      {_NOT_A_SENSOR}<br>
      {_NOT_CAPTURE}<br>
      <table>
        <tr><th>Scenario</th><th>Existing</th><th>Existing + 5</th><th>Existing + 10</th></tr>
        {''.join(rows)}
      </table>
      Differences are from the existing set. The layer control separates uniform and commuter-proxy additions.<br>
      {note_html}
      {html.escape(_ATTRIBUTION)}
    </div>
    <style>
      .leaflet-container {{ background: #ffffff; }}
      .standout-legend {{
        position: fixed; bottom: 48px; left: 12px; z-index: 9999;
        background: rgba(255,255,255,0.96); padding: 8px 10px;
        border: 1px solid #bbb; font: 12px/1.4 sans-serif;
      }}
      .standout-legend-title {{ font-weight: 700; margin-bottom: 4px; }}
      .standout-legend-row {{ display: flex; align-items: center; gap: 6px; }}
      .standout-swatch {{ width: 18px; height: 4px; flex: none; }}
      .standout-panel {{
        position: fixed; top: 12px; left: 54px; z-index: 9999;
        background: rgba(255,255,255,0.96); padding: 8px 12px;
        border: 1px solid #bbb; font: 13px/1.45 sans-serif; max-width: 460px;
        max-height: 280px; overflow-y: auto;
      }}
      .standout-panel table {{ border-collapse: collapse; margin: 6px 0; }}
      .standout-panel th, .standout-panel td {{
        border-bottom: 1px solid #ddd; padding: 2px 8px 2px 0; text-align: left;
      }}
    </style>
    """


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
