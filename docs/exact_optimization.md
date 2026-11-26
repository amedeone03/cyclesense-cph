# Exact maximum-coverage benchmark

The question is how close the existing greedy placements are to the optimum of the mathematical coverage objective, and whether a higher calibration value improves held-out coverage. The greedy algorithms are unchanged. This benchmark scores them.

Routes are simulated. Coverage is the share of simulated-route weight that touches at least one selected segment. It is not an observed cyclist count, and a small optimality gap does not say that a segment should be equipped in the street.

## Formulation

Let `E` be the 1,047 eligible physical segments and `R` the calibration routes used by that instance. A segment is one physical id. The two directed OSM edges of a street share that id, so the model cannot select both directions as two counters.

Binary `x_e` selects a segment. Binary `y_r` says route `r` is covered. With nonnegative weights `w_r` that sum to 1:

```text
maximize  sum_r w_r y_r
subject to  y_r <= sum_{e in E(r)} x_e    for every route r
            sum_e x_e <= K
            x_e, y_r in {0, 1}
```

`E(r)` is the eligible segments on route `r`. A route with no eligible segment has an empty sum, so `y_r` is forced to 0. A route is counted once no matter how many selected segments it crosses. Duplicate route sets are separate terms only when they have their own weights.

HiGHS minimizes, so the implemented cost is the negation of `w_r` on each `y_r`. The coverage incumbent is the negation of the solver objective. The HiGHS dual bound is a lower bound on that minimized value, so its negation is an upper bound on coverage. If a bound comes back slightly below the incumbent, it is raised to the incumbent.

The cardinality constraint is at most `K`. Every reported placement is then passed through the existing `fill_to_k` rule, which appends unused eligible ids in sorted order until the set has size exactly `K`. On a certified optimum those extra segments have zero marginal coverage, so the fill does not change the objective. In this study the solver support already had size `K` on every primary instance, so the fill added nothing. The distinction still matters: the proof is for the `<= K` model, and the published set has size `K` only after the deterministic fill.

Reported coverage is recomputed by `evaluate_coverage` from the selected physical ids. The solver's `y` values are not the published coverage. The recomputed weight matched the negated solver objective on every run.

## Greedy guarantee

For nonnegative weights the coverage function is nonnegative, monotone, and submodular: adding a segment never hurts, and its gain falls as the selected set grows. Under a cardinality limit, the standard greedy algorithm reaches at least `1 - 1/e`, about 63.2%, of the optimal calibration value. The implemented selector is that algorithm. It adds the eligible segment with the largest marginal weight, breaks ties by sorted id, and stops when every remaining gain is zero. The guarantee is only about this calibration objective. It says nothing about held-out routes, municipal counts, community balance, or route-choice stability.

Every certified instance in this study satisfies the bound, and by a wide margin. The largest relative gap is 2.0% of the optimum, on the uniform community-balanced objective at `K = 20`. A high coverage number is not itself a proof of optimality. The proof here is the HiGHS status.

## Solver

The solver is `scipy.optimize.milp` 1.18.1, backend HiGHS. SciPy is already an analysis dependency. It is also declared in the `dev` extra so the unit tests can run the same solver. There is no commercial license and no new solver package.

Settings, fixed before any held-out score was inspected:

- time limit: 120 seconds per instance
- relative MIP gap: `1e-6`
- presolve left on
- display off

A run is called optimal only when HiGHS returns status 0. A time limit would keep the incumbent, the upper bound, and the remaining gap, and would be labeled time-limited. That label was not needed. All 18 instances returned status 0 with a recorded bound gap of 0. None were infeasible, unbounded, or missing an incumbent.

The constraint matrix is sparse. Each route contributes one row, `sum_{e in E(r)} x_e - y_r >= 0`, plus one budget row. Uniform calibration has 9,613 nonzeros. Commuter calibration has 10,192. The route-choice instance has 221,952.

## Primary comparison

Calibration routes are the canonical M1 calibration split: 500 uniform and 500 commuter-proxy routes, equal weight `1/500`. The candidate set is the full eligible list. Greedy sets are the saved M2 placements. Recomputing greedy on the same routes reproduced those sets before the comparison. Held-out scores use the saved M1 evaluation routes and were not shown to the solver.

| Scenario | K | Greedy | MILP | Absolute gap | Relative gap | Shared | Jaccard | Held-out greedy | Held-out MILP | MILP time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform | 5 | 55.2% | 55.2% | 0 | 0 | 4 | 0.67 | 52.4% | 53.2% | 0.07 s |
| Uniform | 10 | 74.0% | 74.0% | 0 | 0 | 8 | 0.67 | 72.8% | 68.8% | 0.07 s |
| Uniform | 20 | 90.4% | 91.0% | 0.6 pp | 0.66% | 17 | 0.74 | 84.0% | 82.8% | 0.23 s |
| Uniform | 30 | 96.8% | 97.2% | 0.4 pp | 0.41% | 18 | 0.43 | 89.6% | 89.2% | 0.89 s |
| Commuter | 5 | 51.6% | 51.6% | 0 | 0 | 4 | 0.67 | 53.2% | 52.0% | 0.22 s |
| Commuter | 10 | 75.4% | 75.4% | 0 | 0 | 7 | 0.54 | 69.2% | 70.4% | 0.69 s |
| Commuter | 20 | 94.0% | 94.8% | 0.8 pp | 0.84% | 9 | 0.29 | 86.8% | 84.8% | 0.96 s |
| Commuter | 30 | 99.0% | 99.4% | 0.4 pp | 0.40% | 14 | 0.30 | 88.8% | 88.8% | 3.92 s |

Greedy selection on these instances took 0.005–0.020 seconds.

At `K = 5` and `K = 10` in both scenarios, greedy matches the certified optimum exactly. The selected streets still differ. Uniform `K = 10` shares 8 of 10 segments. Greedy alone uses Øster Voldgade (`pe:698019:1330937536:938826162`) and one Gothersgade segment (`pe:706815:300094223:36522887`). The MILP alone uses Børsgade (`pe:8078470:6943466010:36072374`) and a different Gothersgade segment (`pe:706815:9197599042:660124255`). Same calibration coverage, different locations. On the uniform held-out routes the greedy set covers 72.8% and the MILP set covers 68.8%.

The largest certified gap is 0.8 percentage points, commuter `K = 20`. That MILP set is 2.0 points lower on its own held-out routes (84.8% against 86.8%). Higher calibration coverage did not produce higher held-out coverage in that instance, or in uniform `K = 20` and `K = 30`. Commuter `K = 10` is the other way around: equal calibration coverage, and the MILP set is 1.2 points higher on held-out routes. The differences are a few points on 250 simulated routes. They do not support a claim that exact calibration optimization generalizes better.

## Weighted objectives

Each comparison uses the same weights on both sides. A weighted optimum is not compared with unweighted greedy.

Community weights are the M4 construction: exact Jaccard on physical calibration edges, threshold 0.5, Louvain with seed 42, lambda 0.25. The recomputed greedy sets match the saved M4 placements. Pooled and route-choice weights are the M5.9 assignments. The route-choice routes are the frozen 11,000 training realizations, not a new draw.

| Objective | K | Greedy | MILP | Relative gap | Shared | MILP time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform community balance | 10 | 75.11% | 75.87% | 0.99% | 7 | 0.06 s |
| Uniform community balance | 20 | 91.15% | 93.02% | 2.01% | 10 | 0.16 s |
| Commuter community balance | 10 | 76.56% | 76.59% | 0.05% | 4 | 0.88 s |
| Commuter community balance | 20 | 95.00% | 95.80% | 0.83% | 11 | 1.72 s |
| Pooled shortest paths | 10 | 72.90% | 73.10% | 0.27% | 7 | 0.22 s |
| Route-choice augmented | 10 | 69.37% | 69.87% | 0.71% | 7 | 15.16 s |

The weighted gaps are still small. The largest, 2.0% of the uniform balanced optimum at `K = 20`, is larger than any unweighted gap in the table above. Commuter balanced `K = 10` is almost equal in value (a 0.05% relative gap) while sharing only 4 of 10 segments. On that scenario's held-out routes the greedy set covers 66.8% and the MILP set covers 64.0%. Matching the weighted calibration objective more closely did not raise held-out coverage there.

Pooled held-out coverage is 72.0% greedy and 71.6% MILP on uniform routes, and 73.2% greedy and 74.0% MILP on commuter routes. Route-choice held-out coverage is 69.6% greedy and 71.2% MILP on uniform routes, and 72.4% greedy and 71.6% MILP on commuter routes. These are shortest-path evaluation routes. The MILP sets were not rescored on the 15% and 30% detours.

Greedy took 0.012 seconds for the pooled objective and 0.122 seconds for the route-choice objective.

## Runtime

The controlled timing series uses the full 1,047 candidates and `K = 10`. The 100, 250, and 500 route instances are prefixes of the sorted uniform calibration ids. The 1,000 route instance is all 500 uniform plus all 500 commuter calibration routes with equal weight per route, which is the same model as the pooled comparison.

| Routes | Nonzeros | Status | MILP time | Greedy time |
| --- | ---: | --- | ---: | ---: |
| 100 | 1,998 | optimal | 0.021 s | 0.005 s |
| 250 | 4,889 | optimal | 0.036 s | 0.006 s |
| 500 | 9,613 | optimal | 0.066 s | 0.008 s |
| 1,000 | 19,805 | optimal | 0.218 s | 0.013 s |

Runtime grows with the route count and with `K` in this sample. Commuter `K = 30` took 3.9 seconds. The 11,000-route route-choice model took 15.2 seconds. That is not evidence of exponential scaling. The 120 second limit was not reached, so it was not increased.

The study process peaked at about 607 MB resident memory on this Mac. That figure is the whole process, including Python route tables and HiGHS, not a separate solver-only measurement.

## Municipal additions

The 26 name-verified segments in `outputs/standout/summary.json` stay fixed. The MILP may add 5 other eligible segments. It cannot reselect the 26. The objective is unweighted coverage of the same calibration routes. The saved greedy additions were recomputed and matched the published standout sets.

| Scenario | 26 + greedy 5 | 26 + MILP 5 | Held-out greedy | Held-out MILP |
| --- | ---: | ---: | ---: | ---: |
| Uniform | 85.6% | 86.0% | 83.6% | 84.4% |
| Commuter | 89.4% | 89.6% | 82.8% | 81.2% |

Both MILPs were certified. The published greedy additions are therefore not optimal for this incremental objective. The shortfalls are 0.4 and 0.2 percentage points. On commuter held-out routes the certified additions cover less than the greedy additions (81.2% against 82.8%). These sites are algorithmic suggestions on simulated routes. They are not an installation plan, and the municipal file was not modified.

## What this does and does not show

Greedy is at the certified optimum for the unweighted objective at `K = 5` and `K = 10`, and within 0.8 percentage points at `K = 20` and `K = 30`. Several of those optima are not unique: equal coverage can come from different segments. Exact calibration optimization does not consistently raise held-out coverage. In the clearest case, uniform `K = 10`, the two sets tie on calibration and the greedy set is 4 points higher on held-out routes.

The weighted greedy rules are also close to the optima of their own objectives. The route-choice model, which was the expensive case, still finished with a 0.7% relative gap in 15 seconds. That does not revise the M5.9 finding. Training on perturbed calibration routes still has to be judged on held-out routes, and a 0.5 point calibration gain is the scale of the exact gap found here.

## Limitations

The optimum is for a simulated-route objective with fixed nonnegative weights. It is not a prediction of bicycle counts. Held-out evaluation here is the saved shortest-path split. The MILP sets were not run through the detour model. Community labels were recomputed with the M4 settings and matched the saved placements in this environment; a different Louvain implementation could change those weights. The time limit and gap tolerance were not searched, because every instance was certified on the first setting. No result in this file is a reason to replace the greedy selector.
