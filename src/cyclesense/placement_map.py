"""Interactive map of M2 counter sets on the saved M1 basemap.

One layer per algorithm and scenario. The default view shows greedy
placement on the uniform scenario. Other layers stay in the control.
Street names are hover text on named streets, not permanent labels.
"""

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyclesense.interactive import _add_basemap
from cyclesense.placement import METHOD_LABELS, METHODS

_COLORS = {
    "random": "#7f7f7f",
    "geographical_kmeans": "#e41a1c",
    "route_frequency": "#377eb8",
    "greedy": "#4daf4a",
}


def _default_layer_indexes(selections: Sequence[Mapping[str, Any]]) -> set[int]:
    """Indexes of the greedy uniform layer, when that layer is present."""
    uniform = [
        index
        for index, selection in enumerate(selections)
        if str(selection["method"]) == "greedy" and str(selection.get("scenario") or "") == "uniform"
    ]
    if uniform:
        return set(uniform)
    greedy = [index for index, selection in enumerate(selections) if str(selection["method"]) == "greedy"]
    if greedy:
        return {greedy[0]}
    return set(range(len(selections)))


def _legend_html() -> str:
    rows = []
    for method in METHODS:
        color = _COLORS[method]
        label = html.escape(METHOD_LABELS[method])
        rows.append(
            "<div class='placement-legend-row'>"
            f"<span class='placement-swatch' style='background:{color}'></span>"
            f"{label}</div>"
        )
    return (
        "<div class='placement-legend'>"
        "<div class='placement-legend-title'>Algorithm</div>"
        + "".join(rows)
        + "</div>"
    )


def write_placement_map(
    selections: Sequence[Mapping[str, Any]],
    output: Path,
    *,
    boundary: Sequence[float] | None = None,
    basemap: Mapping[str, Any] | None = None,
    budget: int = 10,
) -> Path:
    """Write an HTML map. ``selections`` items need method, seed, and sites."""
    import folium

    latitudes = [float(site["lat"]) for selection in selections for site in selection["sites"]]
    longitudes = [float(site["lon"]) for selection in selections for site in selection["sites"]]
    if not latitudes:
        raise ValueError("placement map needs at least one selected counter")
    center = [sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)]
    fmap = folium.Map(location=center, zoom_start=15, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False)
    visible = _default_layer_indexes(selections)
    for index, selection in enumerate(selections):
        method = str(selection["method"])
        seed = selection.get("seed")
        scenario = selection.get("scenario")
        seed_label = "deterministic" if seed is None else f"seed {seed}"
        title = METHOD_LABELS.get(method, method)
        if scenario:
            title = f"{title} — {scenario}"
        layer = folium.FeatureGroup(name=f"{title} (K={budget})", show=index in visible)
        color = _COLORS.get(method, "#333333")
        for site in selection["sites"]:
            edge_id = str(site["edge_id"])
            name = str(site.get("name") or "(unnamed)")
            popup = folium.Popup(
                "<br>".join(
                    [
                        f"<b>{html.escape(METHOD_LABELS.get(method, method))}</b>",
                        "<b>Physical edge ID</b>",
                        f"<code>{html.escape(edge_id)}</code>",
                        f"Name: {html.escape(name)}",
                        f"Highway: {html.escape(str(site.get('highway') or ''))}",
                        f"Scenario: {html.escape(str(scenario or ''))}",
                        f"K={budget}, {html.escape(seed_label)}",
                        "Modeled counter site. Not an installed counter.",
                    ]
                ),
                max_width=420,
            )
            location = [float(site["lat"]), float(site["lon"])]
            folium.CircleMarker(
                location=location,
                radius=14,
                color="#ffffff",
                weight=4,
                fill=True,
                fill_color=color,
                fill_opacity=1,
                tooltip=folium.Tooltip(f"{METHOD_LABELS.get(method, method)}: {name}", sticky=True),
                popup=popup,
            ).add_to(layer)
        layer.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
    fmap.get_root().html.add_child(
        folium.Element(
            f"""
            {_legend_html()}
            <div class="placement-note">
              Geometry © OpenStreetMap contributors, ODbL.
              Local BBBike extract. No public map tiles.
              Markers are modeled counter sites.
              Hover a street or a marker for its name.
            </div>
            <style>
              .leaflet-container {{ background: #ffffff; }}
              .placement-legend {{
                position: fixed; bottom: 54px; left: 12px; z-index: 9999;
                background: rgba(255,255,255,0.96); padding: 8px 10px;
                border: 1px solid #bbb; font: 12px/1.4 sans-serif;
              }}
              .placement-legend-title {{ font-weight: 700; margin-bottom: 4px; }}
              .placement-legend-row {{ display: flex; align-items: center; gap: 6px; }}
              .placement-swatch {{
                width: 12px; height: 12px; border-radius: 50%;
                border: 2px solid #fff; box-shadow: 0 0 0 1px #555; flex: none;
              }}
              .placement-note {{
                position: fixed; bottom: 12px; right: 12px; z-index: 9999;
                background: rgba(255,255,255,0.95); padding: 6px 10px;
                border: 1px solid #bbb; font: 12px/1.4 sans-serif; max-width: 320px;
              }}
            </style>
            """
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output
