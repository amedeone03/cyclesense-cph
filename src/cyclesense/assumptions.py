"""Scope limits copied into M1 summaries.

The long-form discussion lives in ``docs/m1_assumptions.md``. These sentences
are the claims the extraction pipeline is allowed to attach to its outputs.
"""

NOT_OBSERVED_DEMAND = (
    "Uniform and commuter-proxy routes are simulated shortest paths on the "
    "mapped bicycle network. They are not observed Copenhagen bicycle trips, "
    "and their frequencies are not traffic counts."
)

BIDIRECTIONAL_COUNTING = (
    "Each candidate is one physical street segment between intersections. "
    "A counter on that segment is assumed to observe every modeled traversal "
    "in either direction that uses the segment."
)

ELIGIBILITY_IS_A_PROXY = (
    "Eligibility is a length and OpenStreetMap-tag proxy for a counting line. "
    "It is not an engineering, legal, or municipal installation assessment."
)
