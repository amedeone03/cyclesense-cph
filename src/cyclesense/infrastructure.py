"""Mapped-infrastructure classes for the saved bicycle-candidate segments.

The classes use tags that the M1 graph actually stored. A missing cycleway
tag is not evidence that a facility is absent. Bicycle access and a tagged
cycling facility are different properties. Street names are never used.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from cyclesense.edges import as_tokens

CYCLEWAY_KEYS = ("cycleway", "cycleway:left", "cycleway:right", "cycleway:both")
POSITIVE_FACILITY = frozenset(
    {
        "lane",
        "track",
        "shared_lane",
        "opposite",
        "opposite_lane",
        "opposite_track",
        "share_busway",
        "shoulder",
    }
)
POLICIES = ("unrestricted", "explicit_facility", "dedicated")
POLICY_CATEGORIES = {
    "unrestricted": None,
    "explicit_facility": frozenset({"dedicated", "explicit_facility"}),
    "dedicated": frozenset({"dedicated"}),
}


def tag_record(edge: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Copy the infrastructure tags used for classification."""
    return {
        "highway": tuple(as_tokens(edge.get("highway"))),
        "bicycle": tuple(as_tokens(edge.get("bicycle"))),
        **{key: tuple(as_tokens(edge.get(key))) for key in CYCLEWAY_KEYS},
    }


def classify_physical_edge(
    physical_edge_id: str,
    directed: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Classify one physical segment from its directed OSM representations."""
    if not physical_edge_id:
        raise ValueError("a physical edge id is required")
    if not directed:
        raise ValueError(f"{physical_edge_id} has no directed representations")
    records = [tag_record(edge) for edge in directed]
    highways = [frozenset(record["highway"]) for record in records]
    facilities = [frozenset(_facility_tokens(record)) for record in records]
    cycleway_tokens = [frozenset(_cycleway_tokens(record)) for record in records]
    directional_conflict = len(set(highways)) > 1 or len(set(facilities)) > 1
    highway = set().union(*highways)
    facility = set().union(*facilities)
    cycleway = set().union(*cycleway_tokens)
    if directional_conflict:
        category, reason = "ambiguous", "directional_conflict"
    elif highway == {"cycleway"}:
        category, reason = "dedicated", "highway_cycleway"
    elif "cycleway" in highway:
        category, reason = "ambiguous", "mixed_highway"
    elif facility:
        category, reason = "explicit_facility", "positive_cycleway_tag"
    elif cycleway:
        category, reason = "other_routable", "cycleway_tag_without_facility"
    elif not highway:
        category, reason = "unknown", "missing_highway"
    else:
        category, reason = "unknown", "missing_cycleway_tags"
    return {
        "physical_edge_id": physical_edge_id,
        "category": category,
        "reason": reason,
        "highway": "|".join(sorted(highway)),
        "bicycle": "|".join(sorted(set().union(*(record["bicycle"] for record in records)))),
        "cycleway": _joined(records, "cycleway"),
        "cycleway_left": _joined(records, "cycleway:left"),
        "cycleway_right": _joined(records, "cycleway:right"),
        "cycleway_both": _joined(records, "cycleway:both"),
        "missing_cycleway_tags": not cycleway,
        "directional_conflict": directional_conflict,
        "n_directed": len(records),
    }


def permitted_ids(classified: Sequence[Mapping[str, Any]], policy: str) -> tuple[str, ...]:
    """Eligible ids allowed by a mapped-infrastructure policy."""
    if policy not in POLICY_CATEGORIES:
        raise ValueError(f"unknown infrastructure policy: {policy}")
    allowed = POLICY_CATEGORIES[policy]
    chosen = [
        str(row["physical_edge_id"])
        for row in classified
        if allowed is None or row["category"] in allowed
    ]
    if len(chosen) != len(set(chosen)):
        raise ValueError("a physical edge was classified more than once")
    return tuple(sorted(chosen))


def assert_selection_split(split: str) -> None:
    """Placement may read the calibration routes only."""
    if split != "calibration":
        raise ValueError("counter selection reads the calibration split only")


def feasibility(n_permitted: int, budget: int) -> str:
    """A budget is infeasible when the policy retains fewer than K segments."""
    if budget < 0:
        raise ValueError("budget must be nonnegative")
    if n_permitted < budget:
        return "infeasible"
    return "feasible"


def attribute_audit(classified: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Candidate counts, missing-tag rate, and conflicting-tag rate."""
    total = len(classified)
    if total == 0:
        raise ValueError("the audit needs at least one classified segment")
    categories = Counter(str(row["category"]) for row in classified)
    reasons = Counter(str(row["reason"]) for row in classified)
    missing = sum(1 for row in classified if row["missing_cycleway_tags"])
    conflicts = sum(1 for row in classified if row["directional_conflict"])
    ambiguous = categories["ambiguous"]
    rows = []
    for category in ("dedicated", "explicit_facility", "other_routable", "unknown", "ambiguous"):
        count = categories[category]
        rows.append(
            {
                "measure": "category",
                "name": category,
                "count": count,
                "share_of_eligible": count / total,
            }
        )
    rows.extend(
        [
            {"measure": "missing_cycleway_tags", "name": "missing_cycleway_tags", "count": missing, "share_of_eligible": missing / total},
            {"measure": "directional_conflict", "name": "directional_conflict", "count": conflicts, "share_of_eligible": conflicts / total},
            {"measure": "ambiguous", "name": "ambiguous", "count": ambiguous, "share_of_eligible": ambiguous / total},
            {"measure": "eligible", "name": "eligible", "count": total, "share_of_eligible": 1.0},
        ]
    )
    for reason, count in sorted(reasons.items()):
        rows.append({"measure": "reason", "name": reason, "count": count, "share_of_eligible": count / total})
    return rows


def policy_summary(classified: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """How many eligible segments each policy retains."""
    total = len(classified)
    rows = []
    for policy in POLICIES:
        permitted = permitted_ids(classified, policy)
        rows.append(
            {
                "policy": policy,
                "n_permitted": len(permitted),
                "share_of_eligible": len(permitted) / total if total else 0.0,
                "reduction_share": 1.0 - (len(permitted) / total if total else 0.0),
            }
        )
    return rows


def _facility_tokens(record: Mapping[str, Sequence[str]]) -> set[str]:
    return _cycleway_tokens(record) & POSITIVE_FACILITY


def _cycleway_tokens(record: Mapping[str, Sequence[str]]) -> set[str]:
    values: set[str] = set()
    for key in CYCLEWAY_KEYS:
        values.update(record.get(key) or ())
    return values


def _joined(records: Sequence[Mapping[str, Sequence[str]]], key: str) -> str:
    values: set[str] = set()
    for record in records:
        values.update(record.get(key) or ())
    return "|".join(sorted(values))
