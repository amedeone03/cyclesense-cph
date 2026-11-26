"""Map of standard greedy and one community-balanced placement.

The default layer is standard greedy on the uniform scenario. Balanced
placements stay in the layer control. Street names are hover text.
"""

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyclesense.interactive import _add_basemap

_COLORS = {
    "greedy": "#4daf4a",
    "balanced": "#984ea3",
}
_LABELS = {
    "greedy": "Standard greedy",
    "balanced": "Community-balanced",
}


def write_balanced_map(
    selections: Sequence[Mapping[str, Any]],
    output: Path,
    *,
    boundary: Sequence[float] | None = None,
    basemap: Mapping[str, Any] | None = None,
    budget: int = 10,
) -> Path:
    """Write the K=10 comparison map. ``selections`` need method, scenario, and sites."""
    import folium

    latitudes = [float(site["lat"]) for selection in selections for site in selection["sites"]]
    longitudes = [float(site["lon"]) for selection in selections for site in selection["sites"]]
    if not latitudes:
        raise ValueError("balanced map needs at least one counter")
    center = [sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)]
    fmap = folium.Map(location=center, zoom_start=15, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False)
    legend = []
    for selection in selections:
        method = str(selection["method"])
        scenario = str(selection.get("scenario") or "")
        color = _COLORS.get(method, "#333333")
        title = _LABELS.get(method, method)
        if scenario:
            title = f"{title} — {scenario}"
        show = method == "greedy" and scenario == "uniform"
        layer = folium.FeatureGroup(name=f"{title} (K={budget})", show=show)
        for site in selection["sites"]:
            edge_id = str(site["edge_id"])
            name = str(site.get("name") or "(unnamed)")
            popup = folium.Popup(
                "<br>".join(
                    [
                        f"<b>{html.escape(_LABELS.get(method, method))}</b>",
                        "<b>Physical edge ID</b>",
                        f"<code>{html.escape(edge_id)}</code>",
                        f"Name: {html.escape(name)}",
                        f"Scenario: {html.escape(scenario)}",
                        f"K={budget}",
                        "Modeled counter site. Not an installed counter.",
                    ]
                ),
                max_width=420,
            )
            folium.CircleMarker(
                location=[float(site["lat"]), float(site["lon"])],
                radius=12,
                color="#ffffff",
                weight=3,
                fill=True,
                fill_color=color,
                fill_opacity=1,
                tooltip=folium.Tooltip(f"{_LABELS.get(method, method)}: {name}", sticky=True),
                popup=popup,
            ).add_to(layer)
        layer.add_to(fmap)
        if show:
            legend.append((color, title))
    folium.LayerControl(collapsed=True).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
    rows = "".join(
        "<div class='m4-legend-row'>"
        f"<span class='m4-swatch' style='background:{html.escape(color)}'></span>"
        f"{html.escape(name)}</div>"
        for color, name in legend
    )
    fmap.get_root().html.add_child(
        folium.Element(
            f"""
            <div class="m4-legend">
              <div class="m4-legend-title">Shown on open</div>
              {rows}
              <div class="m4-legend-row"><span class="m4-swatch" style="background:#984ea3"></span>Community-balanced is in the layer control</div>
            </div>
            <div class="m4-note">
              Geometry © OpenStreetMap contributors, ODbL.
              Local BBBike extract. No public map tiles.
              Hover a street or a marker for its name.
            </div>
            <style>
              .leaflet-container {{ background: #ffffff; }}
              .m4-legend, .m4-note {{
                position: fixed; z-index: 9999; background: rgba(255,255,255,0.96);
                border: 1px solid #bbb; font: 12px/1.4 sans-serif;
              }}
              .m4-legend {{ bottom: 54px; left: 12px; padding: 8px 10px; max-width: 280px; }}
              .m4-note {{ bottom: 12px; right: 12px; padding: 6px 10px; max-width: 320px; }}
              .m4-legend-title {{ font-weight: 700; margin-bottom: 4px; }}
              .m4-legend-row {{ display: flex; align-items: center; gap: 6px; }}
              .m4-swatch {{
                width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff;
                box-shadow: 0 0 0 1px #555; flex: none;
              }}
            </style>
            """
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output
