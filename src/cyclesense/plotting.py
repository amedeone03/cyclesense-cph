"""Static maps of the pilot graph, candidate segments, and example routes.

Figures are methodological illustrations of the extracted network and the
simulated paths. They are not maps of observed bicycle volumes.
"""

import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "m1" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")

_ROUTE_COLORS = (
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#a65628",
    "#f781bf",
    "#666666",
)


def select_example_routes(routes: Sequence[Any], *, per_scenario: int = 4) -> list[Any]:
    """Pick a deterministic spread of calibration routes from each scenario."""
    chosen: list[Any] = []
    scenarios = []
    for route in routes:
        if route.scenario not in scenarios:
            scenarios.append(route.scenario)
    for scenario in scenarios:
        pool = [route for route in routes if route.scenario == scenario and route.split == "calibration"]
        if not pool:
            continue
        if len(pool) <= per_scenario:
            chosen.extend(pool)
            continue
        for index in range(per_scenario):
            position = round(index * (len(pool) - 1) / max(per_scenario - 1, 1))
            chosen.append(pool[position])
    return chosen


def _edge_xy(graph: Any, u_node: Any, v_node: Any, data: dict[str, Any]) -> tuple[list[float], list[float]] | None:
    geometry = data.get("geometry")
    if geometry is not None and hasattr(geometry, "xy"):
        x_coords, y_coords = geometry.xy
        return list(x_coords), list(y_coords)
    if u_node in graph.nodes and v_node in graph.nodes:
        return (
            [float(graph.nodes[u_node]["x"]), float(graph.nodes[v_node]["x"])],
            [float(graph.nodes[u_node]["y"]), float(graph.nodes[v_node]["y"])],
        )
    return None


def _draw_graph(ax: Any, graph: Any, *, candidate_ids: set[str] | None, linewidth: float) -> None:
    for u_node, v_node, data in graph.edges(data=True):
        coords = _edge_xy(graph, u_node, v_node, data)
        if coords is None:
            continue
        edge_id = str(data.get("physical_edge_id", ""))
        is_candidate = candidate_ids is not None and edge_id in candidate_ids
        if candidate_ids is not None and not is_candidate:
            color, width, alpha, zorder = "#d0d0d0", 0.4, 0.8, 1
        elif candidate_ids is not None:
            color, width, alpha, zorder = "#08519c", 1.2, 0.9, 2
        else:
            color, width, alpha, zorder = "#d0d0d0", linewidth, 0.9, 1
        ax.plot(coords[0], coords[1], color=color, linewidth=width, alpha=alpha, zorder=zorder, solid_capstyle="round")


def _draw_route(ax: Any, graph: Any, route: Any, color: str) -> None:
    xs: list[float] = []
    ys: list[float] = []
    for node in route.node_ids:
        if node not in graph.nodes:
            continue
        xs.append(float(graph.nodes[node]["x"]))
        ys.append(float(graph.nodes[node]["y"]))
    if len(xs) >= 2:
        ax.plot(xs, ys, color=color, linewidth=2.0, alpha=0.9, zorder=3, solid_capstyle="round")


def plot_study_maps(
    graph: Any,
    candidates: Sequence[dict[str, Any]],
    routes: Sequence[Any],
    output_dir: Path,
    *,
    title_suffix: str,
    coordinate_note: str,
) -> dict[str, str]:
    """Write the candidate map and an example-route map. Return their paths."""
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_ids = {str(row["physical_edge_id"]) for row in candidates}
    examples = select_example_routes(routes)

    candidate_path = output_dir / "graph_candidates.png"
    figure, axis = plt.subplots(figsize=(8.2, 8.2))
    _draw_graph(axis, graph, candidate_ids=candidate_ids, linewidth=0.4)
    axis.set_aspect("equal")
    axis.set_title(f"Bicycle graph and eligible counter segments\n{title_suffix}", fontsize=11)
    axis.set_xlabel(coordinate_note)
    axis.set_ylabel("")
    axis.tick_params(labelsize=8)
    figure.text(
        0.01,
        0.01,
        "Blue: eligible physical segments. Grey: other routing edges. "
        "© OpenStreetMap contributors (ODbL). Not an installation plan.",
        fontsize=7,
    )
    figure.tight_layout()
    figure.savefig(candidate_path, dpi=140)
    plt.close(figure)

    route_path = output_dir / "example_routes.png"
    figure, axis = plt.subplots(figsize=(8.2, 8.2))
    _draw_graph(axis, graph, candidate_ids=None, linewidth=0.4)
    for index, route in enumerate(examples):
        color = _ROUTE_COLORS[index % len(_ROUTE_COLORS)]
        _draw_route(axis, graph, route, color)
        axis.plot([], [], color=color, linewidth=2.0, label=f"{route.scenario} {route.route_id.split(':')[-1]}")
    axis.set_aspect("equal")
    axis.set_title(f"Example modeled routes (not observed trips)\n{title_suffix}", fontsize=11)
    axis.set_xlabel(coordinate_note)
    axis.tick_params(labelsize=8)
    if examples:
        axis.legend(loc="upper left", fontsize=7, frameon=True)
    figure.text(
        0.01,
        0.01,
        "Shortest paths on the directed bike graph. Colors distinguish samples, not demand. "
        "© OpenStreetMap contributors (ODbL).",
        fontsize=7,
    )
    figure.tight_layout()
    figure.savefig(route_path, dpi=140)
    plt.close(figure)
    return {"candidates": str(candidate_path), "routes": str(route_path)}
