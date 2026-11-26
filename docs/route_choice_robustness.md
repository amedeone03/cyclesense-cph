# M5.6 route-choice robustness

The placements in M2 and M4 were chosen and scored on shortest paths. This check keeps those OD pairs and those counter IDs fixed, then asks how modeled-route coverage changes when the same trips follow a different connected path. The alternative paths are simulated. They are not estimated cyclist choices and they are not observed journeys.

## Algorithm

One seed draws a positive multiplier for every directed edge of the M1 routing graph:

```text
cost = length * exp(0.35 * Z),  Z ~ Normal(0, 1)
```

Edges are visited in sorted `(u, v, key)` order, so the draw does not depend on graph iteration order. The alternative is the shortest path under those costs. Dijkstra stores the directed edge key, so a parallel edge is the one with the lower perturbed cost, not whichever edge happens to share the same endpoints.

The detour uses the original lengths of the chosen edges:

```text
detour = alternative_length / shortest_length - 1
```

A route is `changed` only when the physical-edge sequence differs and the detour is within the cap. If the physical sequence is the same, the status is `unchanged`. If a different path exceeds the cap, the status is `rejected_detour` and the scored route stays the original shortest path. A missing path would be `failed`; none occurred. Observations are not dropped.

The same cost field is accepted at 15% and at 30%. The wider cap is a relaxation of the narrower one, not a new random network. Sigma and the seed list were written in `configs/pilot.yaml` before the coverage tables were read. They were not changed after the results.

## Controls

- Evaluation OD pairs from `data/processed/m1/routes.csv`: 250 uniform and 250 commuter-proxy routes. Calibration routes are not rescored and are not used to choose the perturbation.
- Placements from `outputs/m4/placements.csv`, threshold 0.5. Greedy is lambda 0, which matches the M2 greedy edges. Balanced is Louvain lambda 0.25. Budgets are K = 10 and K = 20. The optimization is not rerun.
- Seeds `91000` through `91019`, twenty seeds for every scenario and detour cap.
- Coverage is the existing unweighted definition: a simulated route is covered when one of its eligible physical edges is selected.
- Recomputed shortest-path coverage matches the saved M4 held-out values on all eight placements.

The network is the saved directed bike graph. Routing uses only edges that exist, in their stored direction. Physical ids come from the selected edge, including its key. Both detour limits are enforced on original length.

## Route generation

Counts below pool 20 seeds and 250 routes (5,000 route-seeds). No attempt failed.

| Scenario | Cap | Changed | Unchanged | Rejected | Mean detour | Median | 90th | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform | 15% | 82.5% | 12.4% | 5.0% | 4.2% | 3.1% | 10.1% | 15.0% |
| Uniform | 30% | 87.3% | 12.4% | 0.2% | 5.1% | 3.5% | 12.0% | 29.7% |
| Commuter proxy | 15% | 84.6% | 11.0% | 4.5% | 4.3% | 3.4% | 9.8% | 15.0% |
| Commuter proxy | 30% | 88.8% | 11.0% | 0.3% | 5.1% | 3.7% | 11.6% | 29.9% |

Detour summaries use accepted changed routes only. The cap is a maximum. The typical accepted detour is about 3–5%, because the perturbed shortest path is often only a little longer than the original. Raising the cap from 15% to 30% accepts the paths that had been rejected, about 4–5% of route-seeds, and leaves the unchanged share fixed.

Mean set Jaccard of all routes, with unchanged routes counted as 1, is 0.56 at the 15% cap and 0.52 at the 30% cap in the uniform scenario, and 0.54 and 0.51 in the commuter scenario. Among changed routes the mean set Jaccard is about 0.45–0.47. Length detour, segment overlap, and coverage are different quantities: most accepted paths are short detours that still replace about half of their physical segments.

## Coverage

Mean alternative coverage across the 20 seeds. The 5th and 95th percentiles are empirical percentiles of those seeds, not confidence intervals. The seeds share OD pairs, so they are not independent samples of cyclists. Difference is alternative minus shortest, in percentage points.

| Scenario | Method | K | Shortest | 15% mean (SD) | 15% p05–p95 | 15% diff (min, max) | 30% mean (SD) | 30% diff (min, max) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform | Greedy | 10 | 72.8% | 65.7% (2.8) | 61.1–69.2 | −7.1 (−14.0, −2.8) | 65.3% (2.9) | −7.5 (−14.8, −3.2) |
| Uniform | Balanced | 10 | 72.4% | 64.6% (3.5) | 58.3–68.4 | −7.8 (−16.4, −3.2) | 64.1% (3.8) | −8.3 (−17.2, −2.4) |
| Uniform | Greedy | 20 | 84.0% | 79.5% (2.5) | 75.5–82.8 | −4.5 (−10.0, −0.8) | 79.2% (2.5) | −4.8 (−10.8, −2.0) |
| Uniform | Balanced | 20 | 81.2% | 76.5% (2.2) | 74.5–79.6 | −4.7 (−11.6, −1.6) | 76.6% (2.1) | −4.6 (−12.0, −2.4) |
| Commuter | Greedy | 10 | 69.2% | 65.9% (2.0) | 63.2–69.2 | −3.3 (−6.4, +0.8) | 65.6% (2.6) | −3.6 (−8.4, +1.6) |
| Commuter | Balanced | 10 | 66.8% | 63.3% (2.4) | 59.9–66.1 | −3.5 (−8.4, +1.6) | 63.1% (2.7) | −3.7 (−8.8, +2.8) |
| Commuter | Greedy | 20 | 86.8% | 81.7% (1.6) | 79.6–84.1 | −5.1 (−7.2, −1.6) | 81.7% (1.7) | −5.1 (−8.0, −1.6) |
| Commuter | Balanced | 20 | 84.0% | 79.8% (2.0) | 76.7–81.7 | −4.2 (−8.4, 0.0) | 79.9% (2.0) | −4.1 (−8.4, +0.4) |

For uniform greedy at K = 10 and the 15% cap, the average route loses coverage more often than it gains it: 22.3 routes become uncovered and 4.4 become covered, a net loss of 17.9 routes out of 250. The commuter greedy K = 10 loss is smaller, 16.5 lost and 8.2 gained. The transition counts match the coverage difference on every seed.

## Method comparison

On the shortest paths, greedy covers more routes than balanced placement in every cell. The mean gap stays positive under both caps: about 1.0–1.2 percentage points for uniform K = 10, 2.6–3.0 for uniform K = 20, 2.6 for commuter K = 10, and 1.7–1.9 for commuter K = 20.

The seed-level order is less stable. The share of seeds in which balanced coverage exceeds greedy coverage is 30% and 25% for uniform K = 10, 0% and 5% for uniform K = 20, and 15% and 20% for both commuter budgets. Greedy keeps the lead on average. It does not keep it in every perturbation.

## Municipal sites, reported separately

The 26 name-verified segments and the first five greedy additions were read from the saved standout files and were not rematched. This block is not part of the M2 or M4 comparison.

| Scenario | Placement | Shortest | 15% mean | 30% mean | 15% diff | 30% diff |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Uniform | 26 sites | 73.6% | 74.4% | 73.8% | +0.8 | +0.2 |
| Uniform | 26 + 5 | 83.6% | 82.0% | 81.4% | −1.6 | −2.2 |
| Commuter | 26 sites | 72.4% | 72.0% | 71.9% | −0.4 | −0.5 |
| Commuter | 26 + 5 | 82.8% | 80.4% | 80.2% | −2.4 | −2.6 |

The mean for the 26 sites barely moves, but individual seeds do. Uniform coverage at 15% ranges from 70.4% to 81.2%. Commuter coverage ranges from 64.0% to 80.4%. The five added segments still raise mean coverage by about eight percentage points under the alternative paths. That is a statement about simulated routes. It does not explain the weak rank agreement with published AADT.

## Answers

1. Greedy coverage falls. At K = 10 the mean drop is 7.1–7.5 percentage points in the uniform scenario and 3.3–3.6 in the commuter scenario. At K = 20 the drops are about 4.5–5.1 points. Every uniform seed is below its shortest-path coverage. Some commuter seeds at K = 10 are slightly above it.
2. Balanced coverage falls by a similar amount, 7.8–8.3 points for uniform K = 10 and 3.5–3.7 for commuter K = 10.
3. The 30% cap changes a few more routes and lowers mean coverage by only a few tenths of a point beyond the 15% cap. In two balanced cells the 30% mean is slightly higher. A wider maximum detour does not, by itself, produce a much larger coverage gap, because most accepted detours were already under 15%.
4. Greedy remains ahead on average in every cell. The ranking reverses in up to 6 of 20 seeds, mostly at K = 10.
5. The uniform scenario is more sensitive at K = 10. At K = 20 the two scenarios lose a similar number of percentage points, and the commuter greedy loss is slightly larger.
6. For uniform greedy at K = 10, the Pearson correlation between the fraction of routes changed and the absolute coverage change is 0.68 at 15% and 0.51 at 30%. For commuter greedy at K = 10 it is −0.02 and 0.20. The changed fraction is already high in every seed, so it explains little of the commuter variation. These are descriptions of 20 dependent seeds, not a population test.
7. The municipal-plus-five set still covers more simulated routes than the 26 sites alone, by roughly eight to ten points, after a small drop from its shortest-path score.
8. M5 redrew OD pairs and kept shortest paths. Its uniform greedy K = 10 new-sample mean was 69.3%, with a 95th percentile of 71.7%. This experiment keeps the OD pairs and changes the path. The same placement then averages 65.7% (15% cap), and its 95th percentile is 69.2%. Route choice moves this coverage figure further than that OD redraw did. The conclusions are not robust to route choice in the same way they were to a new OD sample. Greedy’s average advantage does survive both checks.

## Limitations

The multiplier scale, 0.35, was pre-specified and produces a high share of changed routes. It was not retuned, including not retuned downward to make the placements look more stable. The resulting detours cluster well below the cap, so this is not a test of riders who regularly accept a 30% longer trip. The search returns one perturbed shortest path. It does not hunt for a different path inside the cap when the first candidate is too long. The twenty seeds share OD pairs and a single network, so percentile ranges are descriptive. Nothing here is an observed cyclist decision, a sensor measurement, or an explanation of the municipal AADT mismatch.

## Report use

The final report can say that the saved counters were optimized for shortest paths, that plausible short detours remove about three to eight percentage points of simulated coverage, and that greedy usually remains ahead of the lambda 0.25 placement without winning every seed. It should keep the municipal comparison in its own paragraph and should not treat these paths as behavior.

## Files

`src/cyclesense/route_choice.py`, `src/cyclesense/route_choice_plots.py`, `scripts/run_route_choice_study.py`, and `tests/test_route_choice.py`. Tables and figures are under `outputs/route_choice/`: `route_diagnostics.csv`, `seed_coverage.csv`, `aggregate_coverage.csv`, `ranking.csv`, `municipal_coverage.csv`, `summary.json`, `coverage_comparison.png`, `coverage_differences.png`, `route_generation.png`, `method_gap.png`, and `example_routes.png`.
