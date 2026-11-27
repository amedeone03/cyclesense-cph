# Interactive planner

The planner is a local page over the saved CycleSense results. It does not place counters, average scenarios, or fill a missing budget.

Generate it, then open it through the local file server:

```bash
python scripts/map_planner.py
python -m http.server 8765
```

The page is `outputs/planner/cyclesense_planner.html`. It is gitignored with the rest of `outputs/`.

## What the controls can show

Research mode starts on uniform standard greedy, K = 10, scored on the uniform held-out shortest paths.

| Control | Available records |
| --- | --- |
| Standard greedy, route frequency, geographic K-Means seed 42 | K = 5, 10, 20, 30, trained on uniform or the commuter proxy |
| Community-balanced greedy, λ = 0.25 | Same budgets and training scenarios |
| Pooled shortest-path greedy and route-choice-augmented greedy | K = 10 and 20, trained on both scenarios together |
| Certified MILP | K = 5, 10, 20, 30, unweighted objective, only where the solver proved optimality |

Geographic K-Means shows seed 42, not the mean of the five seeds. Other λ values, the random baseline, and weighted MILP solutions are not controls.

Held-out shortest paths are the placement's own saved split. A 15% or 30% figure is the mean of the 20 fresh perturbed draws from the route-choice study, seeds 92000–92019. That study scored greedy, balanced, pooled, route-choice, the 26 counting sites, and the five-site additions. It did not score route frequency, K-Means, MILP, or the ten-site additions. Those choices say "Not evaluated for this combination".

K = 5 and K = 30 were not scored on the other scenario or on perturbed routes, except the certified MILP rows, which have both shortest-path held-out scenarios.

A coverage difference is shown only when both placements have that same evaluation. A calibration difference is shown only when both use the same training objective. Community-weighted, pooled, and route-choice objectives are not subtracted from one another.

## Stability

"Show selection stability" uses the 30 calibration draws. Tables exist for greedy at K = 10 and 20 in each scenario, and for pooled shortest paths and route-choice training at K = 10. A segment missing from a saved table was never selected, so its frequency is 0. Frequency is not cyclist demand.

## Municipal mode

The 26 sites are the name-verified published counting locations. The page can add the saved five greedy segments, the five route-choice segments, the five certified MILP segments, or the ten greedy segments. Published bicycle AADT is shown only for the 26 sites. The five route-choice additions have no saved calibration coverage for the full set.

## Map

Streets, water, and parks come from the local context extract. Buildings are left out so the counter lines stay readable. The drawing does not request a map-tile server.
