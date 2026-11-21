# M2 counter-placement baselines

M2 chooses modeled counter sites on the M1 eligible physical segments. A selected site is a graph edge. It is not an installed counter, and a coverage fraction is not an observed bicycle count.

The route generator, study rectangle, candidate rule, and scenario definitions stay as they were in M1. `scripts/run_m2.py` reads `data/processed/m1/` and does not rewrite those files.

## Methods

All four methods use the same eligible candidate set: every eligible physical segment in `candidates.csv`.

| Method | What it optimizes | Stochastic |
| --- | --- | --- |
| `random` | Uniform sample of eligible ids | Yes |
| `geographical_kmeans` | Lloyd K-Means on local midpoint metres, snapped to distinct eligible segments | Yes |
| `route_frequency` | Calibration route weight on each eligible segment | No |
| `greedy` | Marginal uncovered calibration route weight | No |

Random sampling sorts the candidate ids before drawing, then sorts the sample for reporting. Geographic K-Means uses an equirectangular metre plane around the mean candidate midpoint, `n_init=10`, and the documented seed. Each centroid, in `cluster_centers_` order, snaps to the nearest unused candidate. A distance tie uses the smaller edge id.

Route frequency counts each eligible edge once per calibration route, weighted by `scenario_weight`. The rank is descending weight, then ascending edge id.

Greedy calls the existing `greedy_max_coverage`. That function stops when every remaining segment adds zero uncovered calibration weight. M2 then fills the set to exactly K with the lexicographically first unused eligible ids. Those extra segments do not change coverage.

`community_aware_greedy` is listed as deferred in `configs/pilot.yaml`. This milestone does not run MinHash, LSH, or Louvain.

## Experiment

- Budgets: K = 5, 10, 20, 30.
- Scenarios, scored separately: `uniform` and `commuter_proxy`.
- Selection routes: the calibration split only.
- Evaluation routes: the held-out split, scored with `evaluate_coverage` after selection.
- Stochastic seeds: 42, 43, 44, 45, 46. Deterministic methods record an empty seed.
- The candidate set and the held-out route ids are identical across algorithms.
- Held-out coverage is not used to choose a site, a seed, or a budget.

## Metrics

- Calibration coverage and held-out coverage. A route contributes its weight once, even if it crosses several selected segments.
- Held-out coverage variation across seeds: sample standard deviation, minimum, and maximum. A single deterministic run has standard deviation 0.
- Selection runtime, measured around the selection call only.
- Peak memory during that same call, from `tracemalloc`. The reported runtime includes that tracing.
- Geographic dispersion: mean pairwise Euclidean distance of the selected midpoints, in local metres.
- Percentage of routes that cross at least two selected counters, reported as a fraction.

## Figures

`scripts/run_m2.py` writes:

- `outputs/m2/coverage_vs_budget.png`
- `outputs/m2/runtime.png`
- `outputs/m2/saturation.png`
- `outputs/m2/placements_k10.html`
- `outputs/m2/results.csv`
- `outputs/m2/comparison.csv`
- `outputs/m2/selected_k10.csv`
- `outputs/m2/summary.json`

The map uses K = 10. Stochastic layers use seed 42. Each algorithm and scenario is its own layer on the M1 geographical basemap. The page opens with Greedy on the uniform scenario. The other layers stay in the layer control. Street names appear when the pointer is over a named street or a selected counter. A marker popup shows the algorithm name, the street name, and `physical_edge_id`. The page does not request public map tiles. `python scripts/run_m2.py --map-only` rewrites this HTML from `outputs/m2/selected_k10.csv` and leaves the result tables unchanged.

## Saturation reading

The reading below was fixed before the pilot numbers were computed. It describes the curve. It is not a threshold used to pick a winner on held-out data.

A method saturates early on a scenario when its mean held-out coverage at K = 5 is at least 0.85, or when coverage at K = 10 is at least 0.75 and the gain from K = 20 to K = 30 is below 0.02.

## Acceptance checks

Every result row must contain exactly K distinct eligible segment ids. Coverage must stay in [0, 1]. Calibration and evaluation route ids must be disjoint. The numeric record is appended to this file only after `scripts/run_m2.py` finishes.

## Execution record

`scripts/run_m2.py` completed on the saved M1 pilot: 1,047 eligible segments, 500 calibration routes and 250 held-out routes in each scenario, and no route with an empty eligible-edge set. The run wrote 96 result rows. Every row has exactly K distinct eligible ids. Acceptance checks passed.

Coverage below is the share of simulated-route weight intercepted at least once. It is not an observed bicycle count. Stochastic rows are means over seeds 42–46. Sample standard deviation is in parentheses. Runtime is selection only, after scikit-learn has already been imported, and it includes `tracemalloc`.

### Held-out coverage

| Scenario | Method | K=5 | K=10 | K=20 | K=30 |
| --- | --- | ---: | ---: | ---: | ---: |
| uniform | random | 6.6% (5.5) | 14.3% (11.2) | 28.7% (12.4) | 41.1% (10.9) |
| uniform | geographical K-Means | 16.8% (2.2) | 14.2% (3.3) | 32.5% (10.2) | 47.4% (4.8) |
| uniform | route frequency | 27.2% | 40.4% | 52.4% | 60.4% |
| uniform | greedy | 52.4% | 72.8% | 84.0% | 89.6% |
| commuter_proxy | random | 8.0% (7.7) | 16.4% (12.1) | 29.8% (15.4) | 43.8% (9.1) |
| commuter_proxy | geographical K-Means | 17.5% (0.7) | 17.6% (4.2) | 30.3% (11.7) | 47.0% (6.5) |
| commuter_proxy | route frequency | 39.6% | 49.6% | 60.0% | 61.6% |
| commuter_proxy | greedy | 53.2% | 69.2% | 86.8% | 88.8% |

Calibration coverage for the same placements, same rounding:

| Scenario | Method | K=5 | K=10 | K=20 | K=30 |
| --- | --- | ---: | ---: | ---: | ---: |
| uniform | random | 6.6% | 13.4% | 27.3% | 41.0% |
| uniform | geographical K-Means | 19.2% | 14.0% | 30.7% | 43.3% |
| uniform | route frequency | 23.8% | 36.8% | 52.4% | 64.8% |
| uniform | greedy | 55.2% | 74.0% | 90.4% | 96.8% |
| commuter_proxy | random | 8.1% | 17.5% | 31.7% | 43.9% |
| commuter_proxy | geographical K-Means | 20.6% | 17.2% | 30.8% | 42.3% |
| commuter_proxy | route frequency | 37.4% | 51.8% | 62.4% | 64.4% |
| commuter_proxy | greedy | 51.6% | 75.4% | 94.0% | 99.0% |

K-Means placements at different budgets are different partitions, so coverage need not rise with K. On the uniform scenario the mean held-out coverage falls from 16.8% at K=5 to 14.2% at K=10.

### Other metrics

Mean selection time is under 0.2 ms for random, about 3 ms for route frequency, 16–80 ms for greedy, and 18–56 ms for K-Means. Peak traced memory stays under 2 MB: about 0.05 MB for random, 0.15–0.22 MB for frequency, 0.17–0.22 MB for K-Means, and 1.49–1.55 MB for greedy.

Mean pairwise dispersion of the selected midpoints is about 1,025–1,100 m for random and about 1,073–1,096 m for K-Means. Route frequency is tighter: 189 m at uniform K=5, then about 540–550 m, and 516–711 m on the commuter scenario. Greedy sits between them, about 690–930 m.

The share of held-out routes that cross at least two selected counters is under 3% for random and K-Means at K=5 or 10. At K=30 it is about 10% for those two methods, 46–53% for route frequency, and 49% (uniform) or 58% (commuter_proxy) for greedy.

### Saturation

The pre-specified rule does not flag early saturation for any method. The highest held-out coverage at K=5 is 53.2%. Gains continue through K=30 for random, K-Means, and uniform route frequency and greedy.

Two curves flatten late. On commuter_proxy, route frequency gains 1.6 percentage points from K=20 to K=30 (60.0% to 61.6%), and greedy gains 2.0 points (86.8% to 88.8%). Greedy calibration coverage at K=30 is 96.8% on uniform routes and 99.0% on commuter_proxy routes, so the calibration objective is nearly exhausted while held-out coverage is still 89.6% and 88.8%.

### K=10 locations

Seed 42 for random and K-Means. Frequency and greedy have no seed. Random and K-Means ignore route weights, so those two sets are the same in both scenarios. The full table, with coordinates, is `outputs/m2/selected_k10.csv`.

Random, both scenarios: Asiatisk Plads (two segments), Sankt Annæ Plads (two), Lille Strandstræde, Sølvgade (two), Bernstorffsgade, Wilders Plads, Sofiegade.

Geographic K-Means, both scenarios: Wildersgade, Gothersgade, H.C. Andersens Boulevard (two), Klerkegade, Frederiksborggade, an unnamed service segment, Skindergade, an unnamed service segment, an unnamed cycleway.

Uniform route frequency: Knippelsbro / Børsgade, Knippelsbro / Torvegade, Havnegade (two), Havnegade / Børsbroen, Gothersgade (four), Børsgade.

Uniform greedy: Knippelsbro / Børsgade, Gothersgade, Rigsdagsgården, Lille Kongensgade, Nørregade, Gammel Mønt, Lille Langebro, Niels Juels Gade / Christian D. IV's Bro, Nørre Farimagsgade, Øster Voldgade.

Commuter-proxy route frequency: Knippelsbro / Børsgade, Knippelsbro / Torvegade, Børsgade, Store Kongensgade, Gammeltorv, Gothersgade (three), Havnegade / Børsbroen, Kongens Nytorv.

Commuter-proxy greedy: Knippelsbro / Børsgade, Kongens Nytorv, Store Kongensgade, Lille Langebro, Nørregade, Holbergsgade, Gammel Mønt, Nørre Farimagsgade, Vestergade / Gammeltorv, Vindebrogade.
