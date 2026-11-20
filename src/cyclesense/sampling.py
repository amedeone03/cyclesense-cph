"""Reproducible origin-destination draws for modeled routes.

Two scenarios are implemented:

* ``uniform`` draws endpoints uniformly from the routing nodes.
* ``commuter_proxy`` is a spatial kernel around a documented anchor. Origins
  are more likely far from the anchor and destinations are more likely near
  it. This is not an employment model and not an observed commute matrix.

The random stream is ``random.Random`` (Mersenne Twister). Coordinates must
already be in metres. The sampler never sees the street graph.
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from math import hypot
from random import Random

IMPLEMENTED_OD_SCENARIOS = ("uniform", "commuter_proxy")


def euclidean_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    """Euclidean distance in the projected metre plane."""
    return hypot(left[0] - right[0], left[1] - right[1])


def commuter_weights(
    nodes: Sequence[int],
    coordinates_m: Mapping[int, tuple[float, float]],
    anchor_xy: tuple[float, float],
    *,
    distance_floor_m: float = 50.0,
) -> tuple[list[float], list[float]]:
    """Origin and destination weights for the spatial commuter proxy.

    With distance ``d`` from the anchor and floor ``f`` (metres):

    * origin weight = ``d + f``
    * destination weight = ``1 / (d + f)``

    The floor keeps the anchor node itself from taking infinite destination
    weight. Larger origin weights sit farther from the anchor.
    """
    if distance_floor_m <= 0:
        raise ValueError("distance_floor_m must be positive")
    origin: list[float] = []
    destination: list[float] = []
    for node in nodes:
        x_coord, y_coord = coordinates_m[node]
        distance = hypot(x_coord - anchor_xy[0], y_coord - anchor_xy[1])
        origin.append(distance + distance_floor_m)
        destination.append(1.0 / (distance + distance_floor_m))
    return origin, destination


class OdSampler:
    """One seeded stream of origin-destination attempts.

    Rejected attempts return None. Accepted pairs are not remembered until
    ``exclude`` is called, so a caller can drop a pair after a routing check
    without losing the random stream.
    """

    def __init__(
        self,
        nodes: Sequence[int],
        coordinates_m: Mapping[int, tuple[float, float]],
        *,
        seed: int,
        mode: str,
        min_distance_m: float,
        max_distance_m: float,
        anchor_xy: tuple[float, float] | None = None,
        distance_floor_m: float = 50.0,
        excluded_pairs: Iterable[tuple[int, int]] = (),
    ) -> None:
        if mode not in IMPLEMENTED_OD_SCENARIOS:
            raise ValueError(f"unsupported OD scenario {mode!r}")
        if min_distance_m < 0 or max_distance_m <= min_distance_m:
            raise ValueError("distance band must satisfy 0 <= min < max")
        self.mode = mode
        self.nodes = tuple(sorted({int(node) for node in nodes}))
        missing = [node for node in self.nodes if node not in coordinates_m]
        if missing:
            raise KeyError(f"missing coordinates for node {missing[0]}")
        self.coordinates_m = coordinates_m
        self.min_distance_m = float(min_distance_m)
        self.max_distance_m = float(max_distance_m)
        self.anchor_xy = anchor_xy
        self.rng = Random(seed)
        self.excluded = {(int(origin), int(dest)) for origin, dest in excluded_pairs}
        self.stats: Counter[str] = Counter()
        self._origin_w: list[float] | None = None
        self._dest_w: list[float] | None = None
        if mode == "commuter_proxy":
            if anchor_xy is None:
                raise ValueError("commuter_proxy requires anchor_xy in metres")
            self._origin_w, self._dest_w = commuter_weights(
                self.nodes,
                coordinates_m,
                anchor_xy,
                distance_floor_m=distance_floor_m,
            )

    def exclude(self, pair: tuple[int, int]) -> None:
        self.excluded.add((int(pair[0]), int(pair[1])))

    def draw(self) -> tuple[int, int] | None:
        """Try once. None means the attempt was rejected."""
        self.stats["attempts"] += 1
        if len(self.nodes) < 2:
            self.stats["rejected_too_few_nodes"] += 1
            return None
        if self.mode == "uniform":
            origin = self.rng.choice(self.nodes)
            destination = self.rng.choice(self.nodes)
        else:
            assert self._origin_w is not None and self._dest_w is not None
            origin = self.rng.choices(self.nodes, weights=self._origin_w, k=1)[0]
            destination = self.rng.choices(self.nodes, weights=self._dest_w, k=1)[0]
        pair = (int(origin), int(destination))
        if pair[0] == pair[1]:
            self.stats["rejected_same_node"] += 1
            return None
        if pair in self.excluded:
            self.stats["rejected_duplicate"] += 1
            return None
        distance = euclidean_m(self.coordinates_m[pair[0]], self.coordinates_m[pair[1]])
        if distance < self.min_distance_m or distance > self.max_distance_m:
            self.stats["rejected_distance"] += 1
            return None
        self.stats["accepted"] += 1
        return pair


def sample_od_pairs(
    nodes: Sequence[int],
    coordinates_m: Mapping[int, tuple[float, float]],
    *,
    n_pairs: int,
    seed: int,
    mode: str,
    min_distance_m: float,
    max_distance_m: float,
    anchor_xy: tuple[float, float] | None = None,
    distance_floor_m: float = 50.0,
    excluded_pairs: Iterable[tuple[int, int]] = (),
    max_attempts: int | None = None,
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    """Draw up to ``n_pairs`` distance-valid OD pairs.

    Pairs accepted here are excluded from the rest of the same call so the
    returned list contains no repeated ordered pair.
    """
    if n_pairs < 0:
        raise ValueError("n_pairs must be nonnegative")
    sampler = OdSampler(
        nodes,
        coordinates_m,
        seed=seed,
        mode=mode,
        min_distance_m=min_distance_m,
        max_distance_m=max_distance_m,
        anchor_xy=anchor_xy,
        distance_floor_m=distance_floor_m,
        excluded_pairs=excluded_pairs,
    )
    limit = n_pairs * 50 if max_attempts is None else max_attempts
    pairs: list[tuple[int, int]] = []
    while len(pairs) < n_pairs and sampler.stats["attempts"] < limit:
        pair = sampler.draw()
        if pair is None:
            continue
        pairs.append(pair)
        sampler.exclude(pair)
    return pairs, dict(sampler.stats)
