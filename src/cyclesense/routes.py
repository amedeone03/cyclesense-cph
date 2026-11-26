"""Modeled shortest-path routes on physical edge identifiers.

Each accepted journey stores the ordered physical segments it traverses and
the subset that are eligible counter sites. Overlap and coverage must use
those identifiers, not node radii. Calibration and evaluation are separate
random streams. Evaluation drops an origin-destination pair, or an identical
physical path, that calibration already produced in the same scenario.

All scenario weights are 1. That records one accepted draw, not a cyclist count.
"""

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from cyclesense.sampling import OdSampler


@dataclass(frozen=True)
class ModeledRoute:
    route_id: str
    scenario: str
    split: str
    seed: int
    origin_node: int
    destination_node: int
    length_m: float
    node_ids: tuple[int, ...]
    physical_edge_ids: tuple[str, ...]
    eligible_edge_ids: tuple[str, ...]
    scenario_weight: float = 1.0

    def as_csv_row(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "scenario": self.scenario,
            "split": self.split,
            "seed": self.seed,
            "origin_node": self.origin_node,
            "destination_node": self.destination_node,
            "length_m": round(self.length_m, 1),
            "n_physical_edges": len(self.physical_edge_ids),
            "n_eligible_edges": len(self.eligible_edge_ids),
            "scenario_weight": self.scenario_weight,
            "physical_edge_ids": "|".join(self.physical_edge_ids),
            "eligible_edge_ids": "|".join(self.eligible_edge_ids),
            "node_ids": "|".join(str(node) for node in self.node_ids),
        }


def lightest_edge(graph: Any, u_node: int, v_node: int) -> dict[str, Any]:
    """Choose the parallel directed edge Dijkstra would prefer.

    NetworkX shortest paths return nodes only. Among parallel edges the
    smallest length wins, then the key, so the stored identifier matches the
    path cost.
    """
    _key, data = min(
        graph[u_node][v_node].items(),
        key=lambda item: (float(item[1]["length"]), str(item[0])),
    )
    return data


def path_edge_ids(graph: Any, node_path: list[int]) -> tuple[tuple[str, ...], float]:
    """Ordered physical ids and total length along a node path."""
    edge_ids: list[str] = []
    length = 0.0
    for u_node, v_node in pairwise(node_path):
        data = lightest_edge(graph, u_node, v_node)
        length += float(data["length"])
        edge_id = str(data["physical_edge_id"])
        if not edge_ids or edge_ids[-1] != edge_id:
            edge_ids.append(edge_id)
    return tuple(edge_ids), length


def generate_modeled_routes(
    graph: Any,
    coordinates_m: Mapping[int, tuple[float, float]],
    candidate_ids: set[str],
    *,
    scenario: str,
    n_calibration: int,
    n_evaluation: int,
    calibration_seed: int,
    evaluation_seed: int,
    min_distance_m: float,
    max_distance_m: float,
    min_eligible_edges: int,
    anchor_xy: tuple[float, float] | None = None,
    distance_floor_m: float = 50.0,
    max_attempts_factor: int = 60,
    blocked_od: Iterable[tuple[int, int]] | None = None,
    blocked_paths: Iterable[tuple[str, ...]] | None = None,
) -> tuple[list[ModeledRoute], dict[str, Any]]:
    """Build independent calibration and evaluation samples for one scenario.

    ``coordinates_m`` must be projected metres for the same node ids as
    ``graph``. The graph itself can stay in WGS84; only its topology and
    ``length`` attributes are used for routing. ``blocked_od`` and
    ``blocked_paths`` are additional pairs and physical paths that neither
    split may repeat. Callers that omit them keep the original behavior.
    """
    import networkx as nx

    if calibration_seed == evaluation_seed:
        raise ValueError("calibration and evaluation seeds must differ")
    if min_eligible_edges < 1:
        raise ValueError("min_eligible_edges must be positive")

    def build_split(
        *,
        split: str,
        count: int,
        seed: int,
        excluded_od: set[tuple[int, int]],
        excluded_paths: set[tuple[str, ...]],
    ) -> tuple[list[ModeledRoute], dict[str, int]]:
        sampler = OdSampler(
            list(coordinates_m),
            coordinates_m,
            seed=seed,
            mode=scenario,
            min_distance_m=min_distance_m,
            max_distance_m=max_distance_m,
            anchor_xy=anchor_xy,
            distance_floor_m=distance_floor_m,
            excluded_pairs=excluded_od,
        )
        routes: list[ModeledRoute] = []
        rejections: Counter[str] = Counter()
        limit = count * max_attempts_factor
        while len(routes) < count and sampler.stats["attempts"] < limit:
            pair = sampler.draw()
            if pair is None:
                continue
            origin, destination = pair
            try:
                node_path = nx.shortest_path(graph, origin, destination, weight="length")
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                rejections["rejected_no_path"] += 1
                sampler.exclude(pair)
                continue
            physical_ids, length = path_edge_ids(graph, node_path)
            eligible_ids = tuple(edge_id for edge_id in physical_ids if edge_id in candidate_ids)
            if len(eligible_ids) < min_eligible_edges:
                rejections["rejected_short_or_no_candidate"] += 1
                sampler.exclude(pair)
                continue
            if physical_ids in excluded_paths:
                rejections["rejected_seen_path"] += 1
                sampler.exclude(pair)
                continue
            sampler.exclude(pair)
            excluded_paths.add(physical_ids)
            excluded_od.add(pair)
            index = len(routes)
            routes.append(
                ModeledRoute(
                    route_id=f"{scenario}:{split}:{index:04d}",
                    scenario=scenario,
                    split=split,
                    seed=seed,
                    origin_node=origin,
                    destination_node=destination,
                    length_m=length,
                    node_ids=tuple(int(node) for node in node_path),
                    physical_edge_ids=physical_ids,
                    eligible_edge_ids=eligible_ids,
                )
            )
        stats = dict(sampler.stats)
        stats.update(rejections)
        stats["kept"] = len(routes)
        stats["requested"] = count
        return routes, stats

    calibration, calibration_stats = build_split(
        split="calibration",
        count=n_calibration,
        seed=calibration_seed,
        excluded_od=set(blocked_od or ()),
        excluded_paths=set(blocked_paths or ()),
    )
    calibration_od = {(route.origin_node, route.destination_node) for route in calibration}
    calibration_paths = {route.physical_edge_ids for route in calibration}
    evaluation_od = set(blocked_od or ())
    evaluation_od.update(calibration_od)
    evaluation_paths = set(blocked_paths or ())
    evaluation_paths.update(calibration_paths)
    evaluation, evaluation_stats = build_split(
        split="evaluation",
        count=n_evaluation,
        seed=evaluation_seed,
        excluded_od=evaluation_od,
        excluded_paths=evaluation_paths,
    )
    return calibration + evaluation, {
        "scenario": scenario,
        "calibration": calibration_stats,
        "evaluation": evaluation_stats,
    }


def shared_route_keys(routes: list[ModeledRoute]) -> dict[str, int]:
    """Count OD pairs and physical paths that appear in both splits of one scenario."""
    calibration_od = {
        (route.scenario, route.origin_node, route.destination_node)
        for route in routes
        if route.split == "calibration"
    }
    evaluation_od = {
        (route.scenario, route.origin_node, route.destination_node)
        for route in routes
        if route.split == "evaluation"
    }
    calibration_paths = {
        (route.scenario, route.physical_edge_ids)
        for route in routes
        if route.split == "calibration"
    }
    evaluation_paths = {
        (route.scenario, route.physical_edge_ids)
        for route in routes
        if route.split == "evaluation"
    }
    return {
        "shared_od_pairs": len(calibration_od & evaluation_od),
        "shared_paths": len(calibration_paths & evaluation_paths),
    }
