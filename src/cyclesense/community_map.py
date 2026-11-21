"""Interactive map of representative routes from Louvain communities.

Street names stay on hover. Only the largest communities are drawn on
open. The other communities remain in the layer control.
"""

import html
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cyclesense.interactive import _add_basemap

_COLORS = (
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#a65628",
    "#f781bf",
    "#999999",
    "#66c2a5",
    "#fc8d62",
    "#8da0cb",
    "#e78ac3",
)


def write_community_map(
    communities: Sequence[Mapping[str, Any]],
    output: Path,
    *,
    boundary: Sequence[float] | None = None,
    basemap: Mapping[str, Any] | None = None,
    default_visible: int = 5,
    minimum_size: int = 3,
) -> Path:
    """Draw one representative route per community of at least ``minimum_size``."""
    import folium

    drawable = [item for item in communities if int(item["size"]) >= minimum_size and item.get("line")]
    if not drawable:
        drawable = [item for item in communities if item.get("line")][:1]
    if not drawable:
        raise ValueError("community map needs at least one route line")
    ranked = sorted(drawable, key=lambda item: (-int(item["size"]), str(item["scenario"]), int(item["community"])))
    visible_keys = _uniform_visible(ranked, default_visible)
    latitudes = [point[0] for item in drawable for point in item["line"]]
    longitudes = [point[1] for item in drawable for point in item["line"]]
    center = [sum(latitudes) / len(latitudes), sum(longitudes) / len(longitudes)]
    fmap = folium.Map(location=center, zoom_start=15, tiles=None, control_scale=True, zoom_control=True)
    if basemap:
        _add_basemap(fmap, basemap, permanent_labels=False)
    legend_rows = []
    for item in ranked:
        scenario = str(item["scenario"])
        community = int(item["community"])
        color = _COLORS[community % len(_COLORS)]
        show = (scenario, community) in visible_keys
        name = f"{scenario} · community {community} (n={int(item['size'])})"
        layer = folium.FeatureGroup(name=name, show=show)
        route_id = str(item["route_id"])
        popup = folium.Popup(
            "<br>".join(
                [
                    f"<b>{html.escape(name)}</b>",
                    f"Route: {html.escape(route_id)}",
                    f"Mean Jaccard to other members: {float(item['mean_similarity']):.3f}",
                    "Representative simulated route. Not an observed trip.",
                ]
            ),
            max_width=420,
        )
        folium.PolyLine(
            item["line"],
            color=color,
            weight=5,
            opacity=0.9,
            tooltip=folium.Tooltip(f"{name}: {route_id}", sticky=True),
            popup=popup,
        ).add_to(layer)
        layer.add_to(fmap)
        if show:
            legend_rows.append((color, name))
    folium.LayerControl(collapsed=True).add_to(fmap)
    if boundary is not None:
        west, south, east, north = (float(value) for value in boundary)
        fmap.fit_bounds([[south, west], [north, east]], padding=(8, 8))
    fmap.get_root().html.add_child(folium.Element(_legend_markup(legend_rows)))
    output.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(output))
    return output


def _uniform_visible(ranked: Sequence[Mapping[str, Any]], default_visible: int) -> set[tuple[str, int]]:
    chosen = [
        (str(item["scenario"]), int(item["community"]))
        for item in ranked
        if str(item["scenario"]) == "uniform"
    ][:default_visible]
    if chosen:
        return set(chosen)
    return {(str(ranked[0]["scenario"]), int(ranked[0]["community"]))}


def _legend_markup(rows: Sequence[tuple[str, str]]) -> str:
    body = []
    for color, name in rows:
        body.append(
            "<div class='community-legend-row'>"
            f"<span class='community-swatch' style='background:{html.escape(color)}'></span>"
            f"{html.escape(name)}</div>"
        )
    return f"""
        <div class="community-legend">
          <div class="community-legend-title">Shown on open</div>
          {''.join(body)}
        </div>
        <div class="community-note">
          Geometry © OpenStreetMap contributors, ODbL.
          Local BBBike extract. No public map tiles.
          Lines are representative simulated routes.
          Hover a street for its name.
        </div>
        <style>
          .leaflet-container {{ background: #ffffff; }}
          .community-legend {{
            position: fixed; bottom: 54px; left: 12px; z-index: 9999;
            background: rgba(255,255,255,0.96); padding: 8px 10px;
            border: 1px solid #bbb; font: 12px/1.4 sans-serif; max-width: 280px;
          }}
          .community-legend-title {{ font-weight: 700; margin-bottom: 4px; }}
          .community-legend-row {{ display: flex; align-items: center; gap: 6px; }}
          .community-swatch {{ width: 18px; height: 4px; flex: none; }}
          .community-note {{
            position: fixed; bottom: 12px; right: 12px; z-index: 9999;
            background: rgba(255,255,255,0.95); padding: 6px 10px;
            border: 1px solid #bbb; font: 12px/1.4 sans-serif; max-width: 320px;
          }}
        </style>
    """
