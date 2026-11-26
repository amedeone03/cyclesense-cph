import csv
from pathlib import Path

import pytest

from cyclesense.balanced import community_weights
from cyclesense.placement import score_split, select_greedy

ROOT = Path(__file__).resolve().parents[1]
M2_RESULTS = ROOT / "outputs" / "m2" / "results.csv"
ROUTES = ROOT / "data" / "processed" / "m1" / "routes.csv"
CANDIDATES = ROOT / "data" / "processed" / "m1" / "candidates.csv"


@pytest.mark.skipif(
    not (M2_RESULTS.is_file() and ROUTES.is_file() and CANDIDATES.is_file()),
    reason="canonical M1 routes and M2 results are not in this checkout",
)
def test_lambda_zero_reproduces_saved_m2_greedy() -> None:
    eligible = [row["physical_edge_id"] for row in csv.DictReader(CANDIDATES.open(encoding="utf-8"))]
    routes: dict[str, dict[str, set[str]]] = {}
    with ROUTES.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            edges = {edge for edge in row["eligible_edge_ids"].split("|") if edge}
            routes.setdefault(row["scenario"], {}).setdefault(row["split"], {})[row["route_id"]] = edges
    matched = 0
    with M2_RESULTS.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] != "greedy":
                continue
            calibration = routes[row["scenario"]]["calibration"]
            evaluation = routes[row["scenario"]]["evaluation"]
            labels = {route_id: 0 for route_id in calibration}
            weights, info = community_weights(labels, 0.0)
            assert info["fallback_uniform"] is False
            selected = select_greedy(eligible, calibration, int(row["k"]), weights)
            assert "|".join(selected) == row["selected_edges"]
            assert score_split(calibration, selected) == pytest.approx(float(row["calibration_coverage"]))
            assert score_split(evaluation, selected) == pytest.approx(float(row["heldout_coverage"]))
            assert set(calibration).isdisjoint(evaluation)
            matched += 1
    assert matched == 8
