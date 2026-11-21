"""Interactive map of M2 counter sets on the saved M1 basemap.

One layer per algorithm. Markers are modeled counter sites for a single
budget and, for stochastic methods, a single documented seed.
"""

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyclesense.interactive import _add_basemap
from cyclesense.placement import METHOD_LABELS

_COLORS = {
    "random": "#7f7f7f",
    "geographical_kmeans": "#e41a1c",
    "route_frequency": "#377eb8",
    "greedy": "#4daf4a",
}


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
    fmap = folium.Map(location=center, zoom_start=14, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap)
    for selection in selections:
        method = str(selection["method"])
        seed = selection.get("seed")
        scenario = selection.get("scenario")
        seed_label = "deterministic" if seed is None else f"seed {seed}"
        title = METHOD_LABELS.get(method, method)
        if scenario:
            title = f"{title} — {scenario}"
        layer = folium.FeatureGroup(name=f"{title} (K={budget})", show=True)
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
            folium.CircleMarker(
                location=[float(site["lat"]), float(site["lon"])],
                radius=7,
                color=color,
                weight=2,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                tooltip=f"{METHOD_LABELS.get(method, method)}: {edge_id}",
                popup=popup,
            ).add_to(layer)
        layer.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
    fmap.get_root().html.add_child(
        folium.Element(
            """
            <div style="position: fixed; bottom: 12px; right: 12px; z-index: 9999;
                        background: rgba(255,255,255,0.95); padding: 6px 10px;
                        border: 1px solid #bbb; font: 12px/1.4 sans-serif; max-width: 380px;">
              Geometry © OpenStreetMap contributors, ODbL.
              Local BBBike extract. No public map tiles.
              Markers are modeled counter sites.
            </div>
            <style>.leaflet-container { background: #ffffff; }</style>
            """
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output
