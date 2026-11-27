# Mapped infrastructure constraints

The question is how restrictions based on mapped bicycle infrastructure change the coverage, location, and optimality of proposed counting sites.

The restrictions are hypothetical policies on the saved OpenStreetMap tags. They are not municipal installation rules, and a selected segment is not an approved site. Coverage is a share of simulated routes.

## What the saved graph contains

Classification uses the saved M1 routing graph. M1 preprocessing was not changed, and no newer extract was downloaded. `segregated=*` was not retained. The graph does store `highway`, `bicycle`, `cycleway`, `cycleway:left`, `cycleway:right`, `cycleway:both`, and `oneway:bicycle`.

The reference universe is the existing 1,047 eligible physical segments. A physical id is `pe:{min node}:{max node}:{way ids}`. Parallel ways between the same corners keep different ids. Street names are never used to merge segments.

Of those 1,047 segments:

| Record | Count | Share |
| --- | ---: | ---: |
| Any `cycleway*` key | 653 | 62.4% |
| No `cycleway*` key | 394 | 37.6% |
| `bicycle=*` present | 170 | 16.2% |
| Opposing directions disagree on highway or facility tokens | 0 | 0% |
| Same simplified edge mixes `highway=cycleway` with another class | 10 | 1.0% |

A missing `cycleway*` key does not show that a facility is absent. `bicycle=yes` or `bicycle=designated` records access, not a lane. `oneway:bicycle` records contraflow access. Only three of the 107 `highway=cycleway` segments also carry a `cycleway*` key, so the dedicated class comes from the highway tag.

## Classes

Positive facility tokens are `lane`, `track`, `shared_lane`, `opposite`, `opposite_lane`, `opposite_track`, `share_busway`, and `shoulder`. Token sets are compared across the directed representations of one physical id. Order inside a tag does not count as a conflict.

1. If the highway sets differ across directions, or the positive-facility sets differ, the segment is **ambiguous**.
2. If the highway set is exactly `{cycleway}`, the segment is **dedicated**.
3. If `cycleway` is mixed with another highway class on the same simplified edge, the segment is **ambiguous**. It is not treated as a dedicated facility.
4. Otherwise, any positive facility token makes the segment an **explicit facility** on a shared roadway.
5. Otherwise, any other `cycleway*` token, including `no`, `separate`, and `crossing`, makes it **other bicycle-routable**. `cycleway=no` is an explicit negative tag, not missing information. `separate` means the facility is a different way.
6. Otherwise the segment is **unknown**.

| Class | Count | Share of 1,047 |
| --- | ---: | ---: |
| Dedicated cycleway | 107 | 10.2% |
| Explicit cycling facility | 274 | 26.2% |
| Other bicycle-routable | 369 | 35.2% |
| Unknown | 287 | 27.4% |
| Ambiguous | 10 | 1.0% |

The ten ambiguous segments are mixed highway values: `cycleway` with `service` (3), `residential` (2), `unclassified` (2), `path` (1), `tertiary` (1), or `primary` (1). None of the 1,047 candidates had a directional facility conflict.

## Policies

| Policy | Permitted segments | Share | Reduction |
| --- | ---: | ---: | ---: |
| Unrestricted | 1,047 | 100% | 0% |
| Explicit facilities (dedicated or explicit facility) | 381 | 36.4% | 63.6% |
| Dedicated cycleways only | 107 | 10.2% | 89.8% |

Unknown, other-routable, and ambiguous segments are excluded from both restricted policies. Every budget K = 5, 10, and 20 remains feasible. The study does not relax a policy that falls short of K.

Unrestricted greedy reproduces the saved M2 edge sets for both scenarios at K = 5, 10, and 20. Selection uses the original calibration routes. Held-out routes are scored afterwards.

## Greedy coverage

Differences are percentage points against unrestricted greedy in the same scenario. Held-out is the original same-scenario evaluation split.

| Scenario | Policy | K | Calibration | Held-out | Calibration change | Held-out change | Shared | Jaccard |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform | Unrestricted | 5 | 55.2% | 52.4% | 0 | 0 | 5 | 1.00 |
| Uniform | Explicit facilities | 5 | 53.4% | 52.8% | −1.8 | +0.4 | 4 | 0.67 |
| Uniform | Dedicated | 5 | 26.6% | 20.4% | −28.6 | −32.0 | 1 | 0.11 |
| Uniform | Unrestricted | 10 | 74.0% | 72.8% | 0 | 0 | 10 | 1.00 |
| Uniform | Explicit facilities | 10 | 71.0% | 68.4% | −3.0 | −4.4 | 7 | 0.54 |
| Uniform | Dedicated | 10 | 37.4% | 30.0% | −36.6 | −42.8 | 1 | 0.05 |
| Uniform | Unrestricted | 20 | 90.4% | 84.0% | 0 | 0 | 20 | 1.00 |
| Uniform | Explicit facilities | 20 | 86.8% | 80.8% | −3.6 | −3.2 | 15 | 0.60 |
| Uniform | Dedicated | 20 | 47.2% | 37.2% | −43.2 | −46.8 | 1 | 0.03 |
| Commuter proxy | Unrestricted | 5 | 51.6% | 53.2% | 0 | 0 | 5 | 1.00 |
| Commuter proxy | Explicit facilities | 5 | 50.8% | 47.2% | −0.8 | −6.0 | 3 | 0.43 |
| Commuter proxy | Dedicated | 5 | 32.8% | 23.6% | −18.8 | −29.6 | 0 | 0.00 |
| Commuter proxy | Unrestricted | 10 | 75.4% | 69.2% | 0 | 0 | 10 | 1.00 |
| Commuter proxy | Explicit facilities | 10 | 73.2% | 62.8% | −2.2 | −6.4 | 6 | 0.43 |
| Commuter proxy | Dedicated | 10 | 44.8% | 32.8% | −30.6 | −36.4 | 0 | 0.00 |
| Commuter proxy | Unrestricted | 20 | 94.0% | 86.8% | 0 | 0 | 20 | 1.00 |
| Commuter proxy | Explicit facilities | 20 | 92.4% | 82.8% | −1.6 | −4.0 | 12 | 0.43 |
| Commuter proxy | Dedicated | 20 | 53.8% | 42.4% | −40.2 | −44.4 | 1 | 0.03 |

Requiring an explicit mapped facility moves some counters and costs a few points of held-out coverage. Restricting the search to dedicated cycleways removes most of the corridors the unrestricted greedy uses. Held-out coverage falls by about 30 to 47 percentage points. That is a property of this candidate filter, not evidence that dedicated cycleways are poor counting sites.

Unrestricted greedy still selects one ambiguous segment, Lille Langebro, because the simplified edge mixes a cycleway with another highway class. At K = 20 it also selects one unknown segment in each scenario. Those segments are unavailable under both restrictions.

## Certified MILP at K = 10

Each solve uses the existing SciPy/HiGHS maximum-coverage model, a 120-second limit, and a relative gap of 1e-6. All six solves returned status `optimal`. A different optimal set can tie on calibration coverage, so overlap below 10 does not by itself mean a suboptimal greedy set.

| Scenario | Policy | Greedy calibration | Certified calibration | Absolute gap | Held-out greedy | Held-out MILP | Shared with policy greedy | Runtime |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform | Unrestricted | 74.0% | 74.0% | 0 | 72.8% | 68.8% | 8 | 0.09 s |
| Uniform | Explicit facilities | 71.0% | 71.0% | 0 | 68.4% | 69.2% | 6 | 0.09 s |
| Uniform | Dedicated | 37.4% | 37.4% | 0 | 30.0% | 30.0% | 9 | <0.01 s |
| Commuter proxy | Unrestricted | 75.4% | 75.4% | 0 | 69.2% | 66.8% | 5 | 1.35 s |
| Commuter proxy | Explicit facilities | 73.2% | 73.8% | 0.6 pp | 62.8% | 63.6% | 5 | 0.04 s |
| Commuter proxy | Dedicated | 44.8% | 44.8% | 0 | 32.8% | 35.6% | 9 | <0.01 s |

The certified optimum does not recover the coverage lost by the dedicated-cycleway filter. The one nonzero calibration gap is 0.6 percentage points, on the commuter explicit-facility policy. The uniform unrestricted result matches the earlier benchmark: calibration 74.0% and held-out 68.8%.

## Municipal sites plus five segments

The 26 name-verified sites stay fixed. Five further segments are chosen from the calibration routes that those 26 do not already intercept. Additions stay inside the eligible universe, stay off the 26 sites, and obey the policy. Each residual MILP at K = 5 was certified optimal. The reported five can include zero-gain ids from the existing fill rule, so certification applies to the coverage value.

| Training | Placement | Calibration | Uniform held-out | Commuter held-out | Uniform held-out gain |
| --- | --- | ---: | ---: | ---: | ---: |
| Uniform | 26 sites | 71.4% | 73.6% | 72.4% | 0 |
| Uniform | 26 + unrestricted five | 85.6% | 83.6% | 82.0% | +10.0 |
| Uniform | 26 + explicit five | 85.6% | 83.6% | 82.0% | +10.0 |
| Uniform | 26 + dedicated five | 83.2% | 80.4% | 81.6% | +6.8 |
| Commuter proxy | 26 sites | 71.2% | 73.6% | 72.4% | 0 |
| Commuter proxy | 26 + unrestricted five | 89.4% | 82.0% | 82.8% | +8.4 |
| Commuter proxy | 26 + explicit five | 89.2% | 81.2% | 83.2% | +7.6 |
| Commuter proxy | 26 + dedicated five | 86.4% | 82.0% | 82.8% | +8.4 |

On the uniform calibration routes, the explicit-facility additions are the same five segments as the unrestricted additions: three dedicated and two explicit facilities. The dedicated-only additions share 3 of those 5 (Jaccard 0.43) and lower uniform held-out coverage by 3.2 percentage points relative to the unrestricted additions.

On the commuter routes, explicit-facility additions share 4 of 5 with the unrestricted set (Jaccard 0.67). The dedicated-only additions share none of them. Their held-out coverage still matches the unrestricted additions, while calibration is 3.0 percentage points lower. A matching held-out score is not the same recommendation.

The certified residual MILP overlaps the greedy additions in 2 to 4 of the five segments. All six residual solves were certified optimal.

## Spacing

A 50-metre separation was not implemented. The validated model has no pairwise geometry constraint, and distance between segment midpoints is not the distance between the street geometries. Adding that constraint would be a different optimizer.

## What these policies can and cannot support

Explicit mapped facilities are common enough to be a sensitivity filter: they keep 381 candidates and cost a few points of simulated coverage. Dedicated cycleways are a much narrower filter. Using only those 107 segments changes the chosen corridors and roughly halves held-out coverage at K = 10.

Neither filter is an installation-feasibility rule. The tags do not record ownership, width, clearance, power, sight lines, or permission to install a counter. `segregated` is absent from this graph. A street with no cycleway tag may still have a facility that this extract did not encode. Assessing installation feasibility would need a maintained infrastructure inventory, site geometry sufficient for a counter, and the municipal siting constraints that this study does not have.

## Reproduce

```bash
python scripts/run_infrastructure_study.py
```

Outputs are written to `outputs/infrastructure/`. Smoke mode does not run this step. Full reproduction runs it when `summary.json` is absent.
