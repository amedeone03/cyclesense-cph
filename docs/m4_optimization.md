# M4 community-balanced counter placement

M4 asks whether Louvain route communities can improve corridor representation or cross-scenario robustness relative to standard greedy maximum coverage, without a large loss of modeled-route coverage.

The counters are eligible physical street segments from the saved M1 graph. The routes are simulated. A coverage percentage is a share of those simulated routes. It is not an observed bicycle count, and a community is not a measured cyclist type.

`scripts/run_m4.py` reads `data/processed/m1/` and `outputs/m2/results.csv`. It does not rewrite those files or the M3 outputs. Communities are recomputed with the M3 functions: exact Jaccard on calibration physical-edge sets, then Louvain with resolution 1 and seed 42.

## Hypotheses

The lambdas, thresholds, budgets, and shuffle seeds below were fixed before the held-out comparison. None of them was chosen because it won on the evaluation routes.

1. A positive lambda increases the share of non-singleton calibration communities that touch the selected counters.
2. The loss in overall held-out route coverage stays within a few percentage points of standard greedy on the primary threshold.
3. A positive lambda raises the worse of the two simulated evaluation scenarios.
4. Weights from the real Louvain partition beat the same weights after the community labels are shuffled.

## Objective

For a set of counters `S` and calibration routes with nonnegative weights `w_r`,

```text
F(S) = sum_r w_r * I(route r intersects S)
```

`S` contains only eligible physical-edge IDs, `|S| = K`, and each route is counted once. The selector is the existing `greedy_max_coverage`, followed by the same `fill_to_k` step used in M2. Ties keep the M2 rule: the edge with the smaller `repr` wins. Zero-weight routes add no marginal gain. When the remaining gain is zero, `fill_to_k` still returns exactly `K` distinct eligible IDs. Those extra edges do not change coverage.

Lambda 0 gives every calibration route weight `1/N`. That placement matches the saved M2 greedy edge lists and the saved calibration and held-out coverage for both scenarios and for `K = 5, 10, 20, 30`.

## Community weights

Louvain is fit on the calibration routes only. For a route in community `c`,

```text
g_r = 1 / |c|    if |c| >= 2
g_r = 0          if |c| = 1
b_r = g_r / sum_j g_j
w_r(λ) = (1 - λ) / N + λ * b_r
```

`N` is the number of calibration routes, 500 in each scenario. The weights are nonnegative and sum to 1. Every non-singleton community receives the same total balancing weight, because its members contribute `1` in total to `sum g_j`. A singleton keeps only the uniform term `(1-λ)/N`. At lambda 1 a singleton has weight 0, so it cannot change the greedy choice. It can still appear in the final set through `fill_to_k`, which does not change coverage.

If every community were a singleton, `sum g_j` would be 0 and the function would fall back to uniform weights. Both scenarios have non-singleton communities, so that fallback was not used.

Excluding singletons from the balancing term has a direct consequence. At Jaccard 0.5 the uniform partition has 178 singletons out of 500 routes, and the commuter partition has 127. Those routes are the majority of the uniform communities and a large share of the commuter communities. They remain in the coverage term for every lambda below 1, but they do not pull the balancing term. The balancing mass is split across 63 uniform and 64 commuter communities of size at least 2. A route in a community of size 2 is therefore upweighted much more than a route in the largest community. At lambda 0.25 the uniform weights are about 0.00150 for a singleton, 0.00165 for a member of the size-27 community, and 0.00348 for a member of a size-2 community. The objective favors small corridors. It does not treat the largest overlapping bundle as more important per route than a singleton.

The primary graph uses exact Jaccard 0.5. Jaccard 0.3 is a sensitivity setting. The Louvain seed is 42. Lambdas are 0, 0.1, 0.25, 0.5, and 0.75. The map displays lambda 0.25 because that value sits in the middle of the grid, not because of the held-out scores.

## Protocol

Scenarios are `uniform` and `commuter_proxy`. Budgets are `K = 5, 10, 20, 30`. The candidate set is the 1,047 eligible segments from M1.

A calibration community is represented when at least one of its member routes intersects the selected counters. A large community has size at least 2, which is exactly the set that receives balancing weight. Within-community coverage is the share of that community's calibration routes that intersect the counters. These are training metrics. They are not treated as held-out validation.

Held-out routes are assigned with the M3 neighbor-consensus rule at the same threshold. Louvain is not refit. Assigned, ambiguous, and unassigned routes are scored separately and are all included in the overall coverage. Overall coverage is the unweighted share of evaluation routes, the same quantity as M2.

Cross-scenario scoring trains on one scenario's calibration routes and communities, then scores both evaluation sets. The shifted assignment uses the training communities. Nothing is refit on held-out routes. Robustness here means these two simulated scenarios only.

The ablation shuffles the calibration community labels with seeds 42, 43, and 44. The shuffle preserves the multiset of community sizes, including the singleton count, and then uses the same weight formula. Reported community representation for the shuffled placements is measured against the real Louvain labels.

## Communities

The recomputed partitions match the M3 seed-42 record.

| Scenario | Threshold | Communities | Size ≥ 2 | Singletons | Largest |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform | 0.5 | 241 | 63 | 178 | 27 |
| uniform | 0.3 | 62 | 19 | 43 | 79 |
| commuter_proxy | 0.5 | 191 | 64 | 127 | 23 |
| commuter_proxy | 0.3 | 55 | 26 | 29 | 76 |

Held-out assignment at threshold 0.5 is unchanged from M3: uniform 138 assigned, 33 ambiguous, 79 unassigned; commuter 142 assigned, 43 ambiguous, 65 unassigned. About 55–57% of evaluation routes receive an unambiguous community.

## Comparison with M2 greedy

Primary threshold 0.5. Coverage is the share of simulated routes. Large-community representation is the training metric defined above.

### Uniform

| K | λ | Calibration | Held-out | Assigned | Ambiguous | Unassigned | Large communities |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 0 | 55.2% | 52.4% | 60.1% | 75.8% | 29.1% | 37/63 |
| 5 | 0.25 | 55.2% | 52.4% | 60.9% | 72.7% | 29.1% | 38/63 |
| 5 | 0.5 | 55.2% | 52.4% | 60.9% | 72.7% | 29.1% | 38/63 |
| 5 | 0.75 | 53.4% | 52.8% | 58.7% | 72.7% | 34.2% | 41/63 |
| 10 | 0 | 74.0% | 72.8% | 83.3% | 90.9% | 46.8% | 54/63 |
| 10 | 0.25 | 73.6% | 72.4% | 83.3% | 87.9% | 46.8% | 54/63 |
| 10 | 0.5 | 73.0% | 71.2% | 81.2% | 84.8% | 48.1% | 54/63 |
| 10 | 0.75 | 73.8% | 71.6% | 81.2% | 87.9% | 48.1% | 54/63 |
| 20 | 0 | 90.4% | 84.0% | 90.6% | 97.0% | 67.1% | 61/63 |
| 20 | 0.25 | 88.6% | 81.2% | 90.6% | 97.0% | 58.2% | 63/63 |
| 20 | 0.5 | 88.6% | 81.2% | 90.6% | 97.0% | 58.2% | 63/63 |
| 20 | 0.75 | 88.2% | 80.0% | 89.9% | 97.0% | 55.7% | 63/63 |
| 30 | 0 | 96.8% | 89.6% | 95.7% | 97.0% | 75.9% | 63/63 |
| 30 | 0.25 | 96.0% | 88.0% | 94.9% | 97.0% | 72.2% | 63/63 |
| 30 | 0.5 | 96.0% | 88.0% | 94.9% | 97.0% | 72.2% | 63/63 |
| 30 | 0.75 | 96.4% | 87.2% | 94.2% | 97.0% | 70.9% | 63/63 |

Lambda 0.1 matches lambda 0.25 exactly at `K = 5` and selects the same ten edges at `K = 10`, so the held-out coverage is the same 72.4%. At `K = 20` and `K = 30`, lambda 0.1 sits between lambda 0 and lambda 0.25. The full rows are in `outputs/m4/placements.csv`.

At `K = 10` the uniform balanced placement changes one counter relative to greedy. Held-out coverage falls by one evaluation route, from 72.8% to 72.4%, and the number of represented large communities stays 54. At `K = 20` the last two large communities become represented and held-out coverage falls from 84.0% to 81.2%. At `K = 30` every large community is already represented by standard greedy, and balancing lowers held-out coverage from 89.6% to 88.0%.

Unassigned evaluation routes stay near 47% coverage at `K = 10` for every lambda. They are dissimilar to the calibration corridors, and the balancing term does not pull counters toward them. Ambiguous routes remain highly covered because they overlap several calibration communities.

### Commuter proxy

| K | λ | Calibration | Held-out | Assigned | Ambiguous | Unassigned | Large communities |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 0 | 51.6% | 53.2% | 61.3% | 72.1% | 23.1% | 37/64 |
| 5 | 0.25 | 51.4% | 52.4% | 60.6% | 74.4% | 20.0% | 38/64 |
| 5 | 0.5 | 51.4% | 52.4% | 60.6% | 74.4% | 20.0% | 38/64 |
| 5 | 0.75 | 48.8% | 50.4% | 56.3% | 65.1% | 27.7% | 41/64 |
| 10 | 0 | 75.4% | 69.2% | 78.2% | 88.4% | 36.9% | 51/64 |
| 10 | 0.25 | 74.8% | 66.8% | 77.5% | 86.0% | 30.8% | 56/64 |
| 10 | 0.5 | 73.0% | 68.4% | 78.2% | 83.7% | 36.9% | 58/64 |
| 10 | 0.75 | 73.2% | 68.0% | 77.5% | 83.7% | 36.9% | 57/64 |
| 20 | 0 | 94.0% | 86.8% | 95.1% | 97.7% | 61.5% | 63/64 |
| 20 | 0.25 | 93.6% | 84.0% | 95.1% | 95.3% | 52.3% | 64/64 |
| 20 | 0.5 | 91.6% | 83.6% | 93.0% | 97.7% | 53.8% | 64/64 |
| 20 | 0.75 | 92.2% | 83.6% | 93.7% | 97.7% | 52.3% | 64/64 |
| 30 | 0 | 99.0% | 88.8% | 95.1% | 97.7% | 69.2% | 64/64 |
| 30 | 0.25 | 98.8% | 88.8% | 95.8% | 97.7% | 67.7% | 64/64 |
| 30 | 0.5 | 98.0% | 88.0% | 95.8% | 97.7% | 64.6% | 64/64 |
| 30 | 0.75 | 98.2% | 88.4% | 95.8% | 97.7% | 66.2% | 64/64 |

The clearest commuter change is at `K = 10`. Lambda 0.25 represents 56 of 64 large communities instead of 51, and held-out coverage falls from 69.2% to 66.8%. Five of the ten counters differ from standard greedy. Unassigned-route coverage falls from 36.9% to 30.8%. The gain is in the training communities, and the routes with no agreed calibration community are covered less often.

Mean within-community coverage of the large communities moves with the same pattern. At `K = 10` it goes from 80.1% to 79.7% on uniform and from 73.4% to 81.8% on the commuter scenario at lambda 0.25. At `K = 30` it is already 100% or 99.2% under standard greedy.

Geographic dispersion does not increase. Uniform `K = 10` mean pairwise distance goes from 854 m at lambda 0 to 845 m at lambda 0.25 and 711 m at lambda 0.5. The commuter distances stay between 866 m and 934 m. The share of held-out routes that cross at least two counters stays at 10.0% for uniform lambda 0 and 0.25, and falls from 24.0% to 18.8% on the commuter scenario.

Selection time is about 14–78 ms. One commuter `K = 30` call took 110 ms. Peak traced memory during selection is 1.41–1.47 MB. The whole script, including exact pairs, held-out assignment, and the shuffle grid, finished in about 16 seconds.

## Cross-scenario robustness

Each row trains on one calibration set and scores both held-out sets. Worst-case is the lower of the two coverages. The difference is matched coverage minus shifted coverage.

| Train | K | λ | Matched | Shifted | Worst | Mean | Matched − shifted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform | 5 | 0 | 52.4% | 53.6% | 52.4% | 53.0% | −1.2 pp |
| uniform | 5 | 0.25 | 52.4% | 53.6% | 52.4% | 53.0% | −1.2 pp |
| uniform | 10 | 0 | 72.8% | 70.0% | 70.0% | 71.4% | +2.8 pp |
| uniform | 10 | 0.25 | 72.4% | 70.0% | 70.0% | 71.2% | +2.4 pp |
| uniform | 10 | 0.5 | 71.2% | 69.2% | 69.2% | 70.2% | +2.0 pp |
| uniform | 20 | 0 | 84.0% | 83.6% | 83.6% | 83.8% | +0.4 pp |
| uniform | 20 | 0.25 | 81.2% | 83.6% | 81.2% | 82.4% | −2.4 pp |
| uniform | 30 | 0 | 89.6% | 91.2% | 89.6% | 90.4% | −1.6 pp |
| uniform | 30 | 0.25 | 88.0% | 89.2% | 88.0% | 88.6% | −1.2 pp |
| commuter_proxy | 5 | 0 | 53.2% | 46.0% | 46.0% | 49.6% | +7.2 pp |
| commuter_proxy | 5 | 0.25 | 52.4% | 45.2% | 45.2% | 48.8% | +7.2 pp |
| commuter_proxy | 10 | 0 | 69.2% | 62.4% | 62.4% | 65.8% | +6.8 pp |
| commuter_proxy | 10 | 0.25 | 66.8% | 58.4% | 58.4% | 62.6% | +8.4 pp |
| commuter_proxy | 10 | 0.5 | 68.4% | 59.2% | 59.2% | 63.8% | +9.2 pp |
| commuter_proxy | 20 | 0 | 86.8% | 80.8% | 80.8% | 83.8% | +6.0 pp |
| commuter_proxy | 20 | 0.25 | 84.0% | 79.6% | 79.6% | 81.8% | +4.4 pp |
| commuter_proxy | 30 | 0 | 88.8% | 85.2% | 85.2% | 87.0% | +3.6 pp |
| commuter_proxy | 30 | 0.25 | 88.8% | 84.4% | 84.4% | 86.6% | +4.4 pp |

Community balancing does not raise the worse of the two scenarios. The uniform-trained `K = 10` worst case stays at 70.0% for lambda 0 and 0.25, then falls to 69.2% at lambda 0.5. The commuter-trained `K = 10` worst case falls from 62.4% to 58.4% at lambda 0.25. The commuter placement is the more brittle of the two under this shift, with or without balancing. This comparison cannot speak to demand shifts outside these two simulated scenarios.

## Shuffled-community ablation

Shuffle seeds 42, 43, and 44. Held-out coverage is the overall unweighted share. Representation is still scored on the real Louvain communities. Primary threshold 0.5, `K = 10`.

| Scenario | λ | Louvain held-out | Shuffle mean (three seeds) | Louvain large communities | Shuffle mean |
| --- | ---: | ---: | --- | ---: | ---: |
| uniform | 0.1 | 72.4% | 71.7% | 85.7% | 84.7% |
| uniform | 0.25 | 72.4% | 72.0% (70.0, 73.6, 72.4) | 85.7% | 85.2% |
| uniform | 0.5 | 71.2% | 70.0% (70.0, 71.6, 68.4) | 85.7% | 83.6% |
| uniform | 0.75 | 71.6% | 69.1% | 85.7% | 81.5% |
| commuter_proxy | 0.1 | 66.8% | 70.5% | 87.5% | 79.7% |
| commuter_proxy | 0.25 | 66.8% | 66.5% (62.0, 69.6, 68.0) | 87.5% | 83.3% |
| commuter_proxy | 0.5 | 68.4% | 65.6% (64.0, 66.0, 66.8) | 90.6% | 84.9% |
| commuter_proxy | 0.75 | 68.0% | 67.7% | 89.1% | 82.3% |

The uniform held-out numbers overlap the shuffle seeds. One shuffled partition at lambda 0.25 reaches 73.6%, above the Louvain placement. On the commuter scenario the real partition does represent more of its own large communities than the shuffle mean, by about 4–6 percentage points at lambda 0.25 and 0.5. That is the quantity the weights were built to move. It is a training result. On held-out coverage the shuffle mean is higher than Louvain at lambda 0.1 (70.5% versus 66.8%) and two of the three seeds are higher at lambda 0.25. The coverage movement is therefore not evidence that the Louvain partition is a better coverage model than a size-matched random partition.

## Sensitivity

Threshold 0.3 was not used to pick lambda. At `K = 10` the coarser communities move more, because there are 19 and 26 of them rather than 63 and 64.

| Scenario | λ | Held-out | Large communities | Shifted coverage |
| --- | ---: | ---: | ---: | ---: |
| uniform | 0 | 72.8% | 16/19 | 70.0% |
| uniform | 0.25 | 71.6% | 18/19 | 69.6% |
| uniform | 0.5 | 68.8% | 19/19 | 66.8% |
| uniform | 0.75 | 67.2% | 19/19 | 66.8% |
| commuter_proxy | 0 | 69.2% | 19/26 | 62.4% |
| commuter_proxy | 0.25 | 68.8% | 24/26 | 67.2% |
| commuter_proxy | 0.5 | 66.8% | 25/26 | 66.4% |
| commuter_proxy | 0.75 | 67.6% | 25/26 | 64.4% |

At this threshold, lambda 0.5 buys complete uniform large-community representation and costs 4.0 percentage points of held-out coverage. The shuffle mean at lambda 0.5 has almost the same held-out coverage, 68.9%, and represents about 80.7% of the real large communities. The partition is doing the representation work. It is not improving coverage beyond the reweighting itself. The commuter lambda 0.1 row is the sharp version of the same finding: Louvain held-out coverage is 65.6%, and the shuffle mean is 70.0%.

## What the run supports

Hypothesis 1 holds in a limited way. On the primary threshold the uniform `K = 10` community count does not move, the commuter `K = 10` count rises from 51 to 56 of 64 at lambda 0.25, and `K = 20` is where both scenarios first reach every large community. `K = 30` was already saturated under standard greedy.

Hypothesis 2 holds on the primary threshold. The held-out losses at lambda 0.25 are 0.0, 0.4, 2.8, and 1.6 percentage points on uniform for `K = 5, 10, 20, 30`, and 0.8, 2.4, 2.8, and 0.0 points on the commuter scenario. The larger loss is in the sensitivity grid, not in the primary one.

Hypothesis 3 does not hold. Worst-case coverage across the two scenarios is unchanged or lower.

Hypothesis 4 holds for the training representation metric on the commuter partition and on the threshold-0.3 graph. It does not hold for held-out coverage. Shuffled labels with the same size distribution produce similar, and sometimes higher, held-out coverage.

## Limitations

- The two scenarios are simulated draws on one street graph. A robust result against both of them is not a result against measured demand.
- Most calibration routes are singletons at the primary threshold, and only about 55–57% of held-out routes receive an unambiguous community. The balancing term ignores the singletons and cannot represent a community that the assignment refuses to name.
- Equal community weight upweights pairs more than the largest corridors. A different aggregation, such as a weight proportional to community size, would be a different experiment. It was not run.
- Training community counts are the objective's own target. The held-out evidence is the unweighted coverage, including ambiguous and unassigned routes, plus the shuffle control.
- Greedy is an approximation. A different selector could use the same weights and choose different edges.
- Lambda 0.75 was a sensitivity value. It was not promoted to a preferred setting after seeing the evaluation numbers.
