# Municipal counting-site redundancy

The question is how much unique and shared modeled-route coverage each of the 26 name-verified counting locations contributes, and how the saved addition sets complement those locations.

This is a retrospective analysis of simulated routes. It is not a recommendation to remove a municipal counting site. The 26 locations are a recurring count programme, not confirmed permanent sensors. A route counts once if it traverses any selected physical segment. Published bicycle AADT is a separate measurement and is not route-level ground truth.

The site ids are the saved name-verified alignment. Street names were not matched again, and no new Trafiktal file was downloaded. All 26 ids are in the eligible candidate universe. Three of them are distinct segments of Gothersgade; they are never merged.

## Coverage of the 26 sites

The recomputed coverage matches the saved municipal results.

| Scenario | Split | Routes | Coverage | Zero sites | Exactly one | Two or more |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Uniform | Calibration | 500 | 71.4% | 143 (28.6%) | 192 (38.4%) | 165 (33.0%) |
| Uniform | Held-out | 250 | 73.6% | 66 (26.4%) | 108 (43.2%) | 76 (30.4%) |
| Commuter proxy | Calibration | 500 | 71.2% | 144 (28.8%) | 209 (41.8%) | 147 (29.4%) |
| Commuter proxy | Held-out | 250 | 72.4% | 69 (27.6%) | 101 (40.4%) | 80 (32.0%) |

About three in ten simulated routes miss every municipal segment. Among the covered routes, the largest group touches exactly one site. The maximum is five municipal segments on one route.

## Unique contribution and Shapley attribution

Leave-one-out contribution is the coverage that becomes uncovered when one site is removed. For this coverage rule it equals the share of routes that touch that site and no other municipal site. The study checks that equality on every site.

Shapley attribution gives each site on a covered route an equal share of that route, `1 / m_r`. With equal route weights, the 26 Shapley values sum to the coverage of the full set. A site on no simulated route gets zero. Shapley credit is an allocation of shared modeled coverage. It is not observed traffic, installation cost, or evidence that a site is unnecessary.

Calibration routes are the ranking sample. Held-out values are descriptive.

| Site | Uniform traversal | Uniform unique | Uniform Shapley | Commuter unique | Commuter Shapley |
| --- | ---: | ---: | ---: | ---: | ---: |
| Knippelsbro, nord for Torvegade | 20.0% | 7.40 pp | 12.89 pp | 7.60 pp | 12.18 pp |
| Lille Langebro | 5.0% | 4.60 pp | 4.80 pp | 5.60 pp | 6.15 pp |
| Bredgade, nord for Kongens Nytorv | 6.6% | 3.80 pp | 5.08 pp | 0.40 pp | 0.82 pp |
| Nyhavnsbroen | 7.6% | 3.40 pp | 5.25 pp | 5.20 pp | 6.40 pp |
| Gothersgade, øst for Nørre Voldgade | 11.0% | 3.20 pp | 6.35 pp | 1.80 pp | 4.00 pp |
| Kristen Bernikows Gade | 9.0% | 0.60 pp | 3.86 pp | 0.20 pp | 3.05 pp |

Knippelsbro has the largest unique contribution in both scenarios, and its Shapley value is higher still because many of its routes also pass another counting segment. Lille Langebro is close to a unique screen: on the uniform calibration routes, 23 of its 25 traversed routes touch no other municipal site.

Kristen Bernikows Gade shows the other pattern. It lies on 9.0% of uniform calibration routes, but only 0.60 points of coverage would be lost if it were removed from the modeled set. Its Shapley value, 3.86 points, assigns it a share of the routes it shares with Knippelsbro, Højbro, and the other inner-harbour segments. High overlap here means shared modeled routes, not a useless counter.

Six uniform calibration sites have zero unique contribution. Two of them, Dronning Louises Bro (published AADT 33,000) and Hovedvagtsgade (AADT 500), lie on no simulated route in either scenario. Dronning Louises Bro sits on the west edge of the pilot rectangle, so trips that start and end inside the clipped graph do not cross it. Vognmagergade, Amaliegade, Gothersgade sydøst for Søtorvet, and Nørre Søgade are traversed, including by routes that also touch another municipal segment, and their Shapley values are small but positive. A zero leave-one-out value does not say the city can stop counting there.

The largest calibration route-incidence overlaps, counted by routes that traverse both segments, are two distinct Gothersgade segments (21 uniform routes, Jaccard 0.31) and Knippelsbro with Kristen Bernikows Gade (19 routes, Jaccard 0.15). Overlap is co-traversal of simulated routes, not geometric overlap of the streets.

Leave-one-out ranks agree across the two scenarios (Spearman 0.82), and so do Shapley ranks (0.82). Bredgade is the main exception: third by unique contribution on uniform routes (3.80 points) and 17th on commuter routes (0.40 points). Landemærket moves the other way, from 1.80 to 3.20 points. Direct traversal and unique contribution are related (Spearman 0.79 uniform, 0.70 commuter) and are not the same ranking.

## Saved additions

Every compared set keeps the same 26 ids. Additions are distinct from those ids and from each other. Gains below are percentage points of modeled-route coverage above the 26. The route-choice additions were selected with a pooled objective, so their unweighted coverage is descriptive and is not interchangeable with the unweighted calibration objective. Held-out scores were not used to choose a method.

| Addition set | Training | Uniform calibration | Uniform held-out | Commuter calibration | Commuter held-out |
| --- | --- | ---: | ---: | ---: | ---: |
| 26 sites | Published | 71.4% | 73.6% | 71.2% | 72.4% |
| +5 greedy | Uniform | 85.6% (+14.2) | 83.6% (+10.0) | 85.8% | 82.0% |
| +10 greedy | Uniform | 90.6% (+19.2) | 87.2% (+13.6) | 90.2% | 85.2% |
| +5 certified MILP | Uniform | 86.0% (+14.6) | 84.4% (+10.8) | 85.6% | 84.4% |
| +5 route-choice | Pooled | 83.2% | 83.2% | 87.8% | 82.8% |
| +5 explicit-facility greedy | Uniform | 85.6% (+14.2) | 83.6% (+10.0) | 85.8% | 82.0% |
| +5 dedicated-cycleway greedy | Uniform | 83.2% (+11.8) | 80.4% (+6.8) | 84.4% | 81.6% |
| +5 greedy | Commuter proxy | 80.8% | 82.0% | 89.4% (+18.2) | 82.8% (+10.4) |
| +10 greedy | Commuter proxy | 85.0% | 86.4% | 94.6% (+23.4) | 85.2% (+12.8) |
| +5 certified MILP | Commuter proxy | 80.2% | 82.0% | 89.6% (+18.4) | 81.2% (+8.8) |

On the uniform calibration routes, the first greedy addition (Rigsdagsgården) adds 5.2 points, and the next four add 3.4, 2.6, 1.8, and 1.2. The tenth adds 0.8. The commuter calibration gains fall from 7.6 points for the first addition to 0.8 for the tenth. Held-out marginals along that same order are not monotone: one later uniform addition adds no held-out routes. Those held-out increments were not the quantity being optimized.

The five uniform greedy additions cover 71 calibration routes that miss all 26 sites. All five also lie on at least one route the 26 already cover. The additions complement the municipal set by reaching missed routes; they are not placed on a disjoint part of the graph.

The certified MILP improves the unweighted calibration objective by 0.4 points in the uniform training and 0.2 points in the commuter training. That is a small gap over greedy. The commuter MILP held-out coverage is 81.2%, below the greedy held-out coverage of 82.8%. A higher calibration value is not a higher held-out value.

## Published AADT

Spearman rank association on the 26 sites, calibration metrics against published bicycle AADT, with 2,000 permutations and seed 14014:

| Scenario | Metric | Spearman | Permutation p |
| --- | --- | ---: | ---: |
| Uniform | Traversal | 0.26 | 0.21 |
| Uniform | Unique coverage | 0.16 | 0.44 |
| Uniform | Shapley | 0.24 | 0.25 |
| Commuter proxy | Traversal | 0.23 | 0.25 |
| Commuter proxy | Unique coverage | 0.07 | 0.73 |
| Commuter proxy | Shapley | 0.14 | 0.52 |

No AADT value is missing. Unique coverage and Shapley do not agree with the published counts more closely than raw traversal does. The original weak alignment stands. Knippelsbro combines a high published count (21,400) with high modeled traversal. Dronning Louises Bro combines the highest published count in this set (33,000) with zero simulated traversals, which is the pilot-boundary effect rather than a measured absence of cyclists.

## What this cannot answer

A counting programme can serve screenline totals, before-and-after studies, and locations the simulated trips never reach. Those purposes are outside the coverage game. Assessing whether a site is useful to the city would need the programme's own objectives, a count series that is not collapsed to one AADT, and routes that are not clipped by the study rectangle.

The exact Shapley calculation is a single pass over the routes. It does not enumerate the 26-factorial coalition order. The script finishes in a few seconds.

## Reproduce

```bash
python scripts/run_municipal_redundancy.py
```

Outputs are written to `outputs/municipal_redundancy/`. Smoke mode does not run this step.
