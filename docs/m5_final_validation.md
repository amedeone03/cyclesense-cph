# M5 final experimental validation

M5 checks the M2–M4 conclusions without fitting a new placement rule. The counters stay the ones already chosen on the calibration routes. New simulated routes are used only for scoring.

The street graph is the saved OpenStreetMap extract. The journeys are simulated. Similarities are exact or approximate Jaccard values on those simulated routes. Counter sites are eligible physical segments selected by an algorithm. None of the percentages below are observed cyclist volumes. M5 does not score municipal bicycle counts. That comparison is separate, in `docs/standout_extension.md`, and the count file is not stored in Git.

## Questions

1. Is the Louvain weighting unusual, on held-out coverage or on calibration-community representation, relative to 30 size-matched shuffles of the same labels?
2. Do the fixed greedy and balanced placements keep their coverage ordering on new simulated samples drawn with the M1 generator?
3. When exact Jaccard and MinHash/LSH are asked to return the same kind of result, the pairs at or above Jaccard 0.5, which one is faster and which one uses less memory?

Lambdas, seeds, sample counts, and the LSH banding were fixed before this run. No lambda or shuffle was kept because it scored well on the new samples.

## Design

The primary communities are the saved M4 Louvain partitions at exact Jaccard 0.5 and seed 42. Recomputing them reproduced 241 uniform communities, 178 of them singletons, and 191 commuter communities, 127 of them singletons. A large community has size at least 2. Representation is the share of those communities with at least one member route crossing the selected counters. That share is always computed on the real Louvain labels, including for a shuffled placement. It is a training metric.

Shuffle seeds are 0 through 29. Each shuffle permutes the calibration labels and keeps the multiset of community sizes, including the singleton count. The weight formula is the M4 formula. Budgets are K = 5, 10, 20, and 30. Lambdas are 0.1, 0.25, 0.5, and 0.75. The held-out routes in this comparison are the original 250 evaluation routes. A Louvain result is described as outside the central 90% of the shuffles when it is strictly below the inclusive 5th percentile or strictly above the 95th percentile of those 30 draws. That is a description of this finite set, not a significance test.

The new evaluation samples use `generate_modeled_routes` with the same boundary, candidate set, distance band, and scenario rules as M1. Each sample has 250 routes. Seeds are 81000 through 81019, twenty samples for each scenario. Canonical origin–destination pairs and physical paths are blocked, so a new route does not repeat a saved one. Calibration count is zero: the samples are not used to move a counter. The placements scored are standard greedy and community-balanced greedy at lambda 0.25 and 0.5, for K = 5, 10, 20, and 30. Methods are compared on the same sample. The reported percentiles are the 5th, 50th, and 95th percentiles of these twenty coverages.

The scalability collection is a separate uniform draw of 2,000 routes, seed 24242, the M3 scalability seed. Route generation is timed and then left out of the method comparison. Exact search returns every pair with Jaccard at least 0.5. LSH uses the frozen uniform operating point from M3: 32 permutations, 16 bands of 2 rows, threshold 0.5. It builds signatures, builds the index, retrieves candidates, verifies them with exact Jaccard, and returns the verified pairs. Recall is the share of the exact pairs that verification also returns.

`scripts/run_m5.py` hashes the canonical M1–M4 files before and after the run. The hashes matched.

## Thirty-seed ablation at K = 10

Held-out coverage on the original evaluation routes:

| Scenario | λ | Louvain | Shuffle mean | Shuffle SD | 5th–95th | Louvain − mean | Shuffles below | Outside central 90% |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| uniform | 0.25 | 72.4% | 71.8% | 1.1 pp | 69.4–73.2% | +0.6 pp | 15/30 | no |
| uniform | 0.50 | 71.2% | 70.6% | 1.7 pp | 68.2–72.8% | +0.6 pp | 17/30 | no |
| uniform | 0.75 | 71.6% | 69.3% | 1.6 pp | 67.0–71.8% | +2.3 pp | 26/30 | no |
| commuter_proxy | 0.10 | 66.8% | 70.2% | 0.9 pp | 69.2–71.6% | −3.4 pp | 0/30 | yes, low |
| commuter_proxy | 0.25 | 66.8% | 69.5% | 1.6 pp | 66.8–71.2% | −2.7 pp | 2/30 | no |
| commuter_proxy | 0.50 | 68.4% | 68.6% | 2.3 pp | 64.4–71.2% | −0.2 pp | 13/30 | no |
| commuter_proxy | 0.75 | 68.0% | 68.0% | 2.7 pp | 63.5–71.4% | 0.0 pp | 17/30 | no |

On held-out coverage, the uniform Louvain placements sit inside the shuffle distribution. The commuter lambda 0.1 placement is the one that is unusual, and it is unusual because it covers less than every shuffle. Lambda 0.25 on that scenario is 2.7 percentage points below the shuffle mean and only two shuffles are lower.

Calibration-community representation at the same budget:

| Scenario | λ | Louvain | Shuffle mean | Shuffle SD | Louvain − mean | Shuffles below | Outside central 90% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| uniform | 0.25 | 54/63 | 84.6% | 1.4 pp | +1.1 pp | 14/30 | no |
| uniform | 0.50 | 54/63 | 82.7% | 2.5 pp | +3.0 pp | 22/30 | no |
| commuter_proxy | 0.25 | 56/64 | 83.0% | 2.7 pp | +4.5 pp | 26/30 | no |
| commuter_proxy | 0.50 | 58/64 | 82.7% | 2.6 pp | +8.0 pp | 30/30 | yes, high |
| commuter_proxy | 0.75 | 57/64 | 81.8% | 3.9 pp | +7.3 pp | 30/30 | yes, high |

The commuter representation gain is the part of the M4 claim that survives a 30-seed control. At lambda 0.5 and 0.75, every shuffle represents fewer of the real large communities than the Louvain weights. The uniform representation gain is smaller and stays inside the central 90%. Standard greedy already represents 54 of 63 uniform communities at K = 10, which is the same count the balanced placements reach, so there is no additional uniform representation to explain.

At K = 20 and K = 30, several uniform Louvain coverages fall at or below the bottom of the shuffle distribution. The full grid is in `outputs/m5/ablation_summary.csv`. Higher budgets do not turn the Louvain labels into a coverage advantage.

## New evaluation samples

Mean coverage on the twenty new samples. The interval is the 5th to 95th percentile of those samples.

| Scenario | K | Greedy | λ = 0.25 | λ = 0.5 | Paired λ = 0.25 − greedy |
| --- | ---: | --- | --- | --- | --- |
| uniform | 5 | 51.7% (SD 2.9) | 51.3% | 51.3% | −0.4 pp |
| uniform | 10 | 69.3% (SD 2.0) | 68.7% | 68.1% | −0.6 pp |
| uniform | 20 | 82.5% (SD 1.8) | 80.7% | 80.7% | −1.8 pp |
| uniform | 30 | 87.1% (SD 1.9) | 88.0% | 88.0% | +0.8 pp |
| commuter_proxy | 5 | 47.8% (SD 3.1) | 48.3% | 48.3% | +0.5 pp |
| commuter_proxy | 10 | 68.8% (SD 2.9) | 67.2% | 68.8% | −1.6 pp |
| commuter_proxy | 20 | 86.9% (SD 2.2) | 86.7% | 85.0% | −0.2 pp |
| commuter_proxy | 30 | 91.1% (SD 1.6) | 90.6% | 90.9% | −0.5 pp |

The original uniform greedy result at K = 10 was 72.8%. The new-sample mean is 69.3%, and the new-sample 95th percentile is 71.7%. That original evaluation draw was a high one relative to these twenty repeats. The commuter original result, 69.2%, is close to the new mean of 68.8%.

The paired differences at K = 10 have sample standard deviations of 1.2 to 3.0 percentage points, and their 5th–95th percentile intervals include both small losses and small gains. The uniform K = 30 mean difference is positive, and its 5th percentile is still negative. Nothing in this table is a demonstrated coverage improvement for community balancing.

Cross-scenario means at K = 10, with the sample standard deviation of the twenty target samples:

| Trained on | λ | Matched | Other scenario | Lower of the two means |
| --- | ---: | --- | --- | ---: |
| uniform | 0 | 69.3% (2.0) | 69.6% (2.7) | 69.3% |
| uniform | 0.25 | 68.7% (2.3) | 69.5% (3.1) | 68.7% |
| uniform | 0.5 | 68.1% (2.3) | 69.5% (3.2) | 68.1% |
| commuter_proxy | 0 | 68.8% (2.9) | 62.6% (3.0) | 62.6% |
| commuter_proxy | 0.25 | 67.2% (2.4) | 59.3% (2.7) | 59.3% |
| commuter_proxy | 0.5 | 68.8% (2.8) | 58.7% (2.8) | 58.7% |

A uniform-trained placement transfers to the new commuter samples. A commuter-trained placement loses about 6 to 10 percentage points on the new uniform samples, and that gap is larger than the sample standard deviation. Balancing does not shrink it. These two scenarios are still the only shift under test.

## Exact Jaccard and MinHash/LSH

Generation of the 2,000 routes took 1.05 seconds and is excluded below. Both methods return pairs with Jaccard at least 0.5. The split times are a second timing of the same steps, so they do not add up exactly to the single end-to-end call.

| Routes | Exact time | Exact peak memory | Exact pairs | LSH end-to-end | LSH peak memory | Preprocess | Query | Verify | Candidates | Recall | Candidate reduction |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 0.382 s | 0.06 MB | 508 | 0.266 s | 2.71 MB | 0.225 s | 0.008 s | 0.019 s | 5,220 | 0.998 | 95.8% |
| 1,000 | 1.385 s | 0.32 MB | 1,909 | 0.574 s | 7.08 MB | 0.449 s | 0.022 s | 0.080 s | 20,317 | 0.997 | 95.9% |
| 2,000 | 5.629 s | 1.24 MB | 8,024 | 1.383 s | 16.8 MB | 0.896 s | 0.090 s | 0.341 s | 82,806 | 0.995 | 95.9% |

At every size in this table, verified LSH is faster and exact search uses less memory. The speedup at 2,000 routes is about four to one. Most of the LSH time is signature construction. Recall stays above 0.994, and about 96% of all pairs are never verified. Exact search is the preferable method when the memory of the band index matters more than the runtime. It is not the faster method at 500 routes or above under this matched output. The M3 note that exact search was faster below a few hundred routes used a count of pairs rather than this return-the-pairs protocol, so those two timings are not one speedup series.

## Consolidated K = 10 table

| Scenario | Method | New-sample coverage | Original held-out | Shuffle mean | Lower cross-scenario mean |
| --- | --- | --- | ---: | ---: | ---: |
| uniform | Greedy | 69.3% ± 2.0 | 72.8% | — | 69.3% |
| uniform | λ = 0.25 | 68.7% ± 2.3 | 72.4% | 71.8% ± 1.1 | 68.7% |
| uniform | λ = 0.50 | 68.1% ± 2.3 | 71.2% | 70.6% ± 1.7 | 68.1% |
| commuter_proxy | Greedy | 68.8% ± 2.9 | 69.2% | — | 62.6% |
| commuter_proxy | λ = 0.25 | 67.2% ± 2.4 | 66.8% | 69.5% ± 1.6 | 59.3% |
| commuter_proxy | λ = 0.50 | 68.8% ± 2.8 | 68.4% | 68.6% ± 2.3 | 58.7% |

The shuffle columns describe the original evaluation routes. The new-sample and cross-scenario columns describe the twenty fresh samples. The ± values are sample standard deviations.

## What the study can support

Greedy maximum coverage remains the strongest of the placement rules that were tested for overall modeled-route coverage. Community-balanced greedy, on the commuter partition, represents more of its own non-singleton communities than size-matched shuffles. That gain does not show up as higher held-out coverage, on the original routes or on the new samples, and it does not improve the worse of the two simulated scenarios.

MinHash with the frozen 32-by-16-by-2 banding, followed by exact verification, returns nearly the same pairs as a full exact scan and is faster from 500 routes to 2,000. It spends more memory than the scan.

## What it cannot support

- No percentage here is a measured bicycle volume. M5 did not score the municipal counting programme.
- The robustness claim covers two simulated demand rules on one small street graph.
- The outside-central-90% flag is a percentile statement about 30 shuffles or 20 samples. It is not a hypothesis test, and the intervals are wide.
- Most calibration routes are singletons at Jaccard 0.5, and only about 55–57% of the original held-out routes received an unambiguous community in M3. Balancing cannot represent a route the assignment leaves unnamed.
- The LSH operating point was chosen on the calibration routes for recall. It was not retuned on the 2,000-route sample, and a different banding could trade recall for a smaller candidate set.
- This document is the validation record. It is not the graded course report.

## Reproduce

```bash
python scripts/run_m5.py
```

Figures and tables are written to `outputs/m5/`. The figures are `coverage_vs_budget.png`, `coverage_vs_lambda.png`, `shuffle_controls.png`, `cross_scenario.png`, `evaluation_variability.png`, and `scalability.png`.
