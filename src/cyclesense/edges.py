"""Physical cycling segments and counter-eligibility rules.

A modeled route is a directed path. A bicycle counter is not a directed graph
edge and not a point with a capture radius. It is one physical street segment
between two intersections. Both travel directions of the same OpenStreetMap
carriageway share one identifier so later coverage math cannot place two
counters on the two orientations of one street and count them as different sites.

These helpers are pure. They do not download data and they do not treat any
weight as a measured bicycle count.
"""

from typing import Any

# Highway classes accepted as counting-line proxies. The routing graph may
# contain a wider set; trunks and footways are left out of the candidate set.
ALLOWED_HIGHWAYS = frozenset(
    {
        "cycleway",
        "residential",
        "living_street",
        "unclassified",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "path",
        "track",
        "pedestrian",
        "service",
        "road",
    }
)

# Service ways that are in the bike graph but are poor counting sites.
BAD_SERVICE = frozenset(
    {
        "alley",
        "driveway",
        "parking",
        "parking_aisle",
        "emergency",
        "drive-through",
        "slipway",
    }
)

INELIGIBLE_BICYCLE = frozenset({"no", "dismount", "private", "use_sidepath"})
INELIGIBLE_ACCESS = frozenset({"private", "no"})
PEDESTRIAN_BICYCLE_OK = frozenset({"yes", "designated", "permissive"})

CONTRAFLOW_BICYCLE = frozenset({"no", "false", "0"})
CONTRAFLOW_CYCLEWAY = frozenset({"opposite", "opposite_lane", "opposite_track"})
CONTRAFLOW_CYCLEWAY_KEYS = (
    "cycleway",
    "cycleway:left",
    "cycleway:right",
    "cycleway:both",
)


def as_list(value: Any) -> list[str]:
    """Flatten a scalar or nested OSM tag into display strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        flattened: list[str] = []
        for item in value:
            flattened.extend(as_list(item))
        return flattened
    text = str(value).strip()
    return [text] if text else []


def as_tokens(value: Any) -> list[str]:
    """Lower-case tag tokens used by eligibility and contraflow rules."""
    return [item.lower() for item in as_list(value)]


def normalize_osmid(osmid: Any) -> tuple[int, ...]:
    """Return OSM way ids in traversal order.

    Simplified OSMnx edges store one id or a list of ids. Missing ids become
    an empty tuple so the caller can fall back to the graph edge key.
    """
    if osmid is None:
        return ()
    if isinstance(osmid, (list, tuple)):
        values: list[int] = []
        for item in osmid:
            values.extend(normalize_osmid(item))
        return tuple(values)
    if isinstance(osmid, str):
        text = osmid.strip()
        if not text or text.lower() == "none":
            return ()
        return (int(text),)
    return (int(osmid),)


def physical_edge_id(u: Any, v: Any, osmid: Any, key: Any = None) -> str:
    """Stable id for the undirected physical segment between two intersections.

    Opposite directions share an id when they carry the same OSM way ids.
    The way-id sequence and its reverse are treated as the same carriageway,
    because OSMnx may store the reverse edge's merged ways in reverse order.
    Distinct parallel ways between the same intersections keep distinct ids.
    A self-loop is marked so it cannot collide with a non-loop segment.
    """
    start, end = int(u), int(v)
    ways = normalize_osmid(osmid)
    if ways:
        reversed_ways = tuple(reversed(ways))
        canonical = min(ways, reversed_ways)
        token = "-".join(str(part) for part in canonical)
    else:
        token = f"nokey-{0 if key is None else key}"
    if start == end:
        return f"pe:loop:{start}:{token}"
    left, right = (start, end) if start < end else (end, start)
    return f"pe:{left}:{right}:{token}"


def _tokens_are(value: Any, accepted: frozenset[str]) -> bool:
    tokens = as_tokens(value)
    return bool(tokens) and set(tokens) <= accepted


def indicates_contraflow(edge: dict[str, Any]) -> bool:
    """Whether tags say bicycles may travel against a one-way carriageway.

    OSMnx builds bike direction from the generic ``oneway`` tag. Copenhagen
    streets often add ``oneway:bicycle=no`` or ``cycleway:*=opposite*``.
    Mixed tag lists are not treated as contraflow: every value must agree.
    """
    if _tokens_are(edge.get("oneway:bicycle"), CONTRAFLOW_BICYCLE):
        return True
    return any(_tokens_are(edge.get(key), CONTRAFLOW_CYCLEWAY) for key in CONTRAFLOW_CYCLEWAY_KEYS)


def eligibility_decision(segment: dict[str, Any], *, min_length_m: float) -> str | None:
    """Return a rejection reason, or None when the segment is a candidate.

    ``segment`` uses already-normalized tokens: ``highway``, ``service``,
    ``bicycle`` and ``access`` are iterables of lower-case strings, and
    ``length_m`` is a float. ``u`` and ``v`` are the endpoint node ids.
    """
    if int(segment["u"]) == int(segment["v"]):
        return "self_loop"
    length = float(segment["length_m"])
    if length <= 0:
        return "missing_or_nonpositive_length"
    if length < min_length_m:
        return "shorter_than_minimum"
    highways = set(as_tokens(segment.get("highway")))
    if not highways:
        return "missing_highway"
    if not highways <= ALLOWED_HIGHWAYS:
        return "highway_not_a_counting_site"
    services = set(as_tokens(segment.get("service")))
    if services & BAD_SERVICE:
        return "service_not_a_counting_site"
    bicycles = set(as_tokens(segment.get("bicycle")))
    if bicycles & INELIGIBLE_BICYCLE:
        return "bicycle_tag_excludes_counting"
    access = set(as_tokens(segment.get("access")))
    if access & INELIGIBLE_ACCESS:
        return "access_not_public"
    if "pedestrian" in highways and not (bicycles & PEDESTRIAN_BICYCLE_OK):
        return "pedestrian_without_bicycle_permission"
    return None


def is_eligible_physical(segment: dict[str, Any], *, min_length_m: float) -> bool:
    """True when ``eligibility_decision`` accepts the segment."""
    return eligibility_decision(segment, min_length_m=min_length_m) is None
