# Integrated similarity-to-placement study

This is an additional experiment. M3 still builds its Louvain graph from exact all-pairs Jaccard, and M4 still places counters on those communities. The run below connects the same pieces in two pipelines and compares them. It does not replace those records.

The street graph is the saved OpenStreetMap extract. The journeys are simulated. A graph edge is a Jaccard similarity between two simulated routes. Coverage is the share of simulated routes that meet a selected segment. It is not observed cyclist capture, and the selected segments are not approved installation sites.

## Question

Can MinHash/LSH retrieve the pairs that matter for Louvain and for community-balanced placement, and what does that approximation cost in community structure, counter locations, held-out coverage, time, and memory?

The approximate pipeline is not expected to win. A higher held-out number from a damaged partition is a different weighting, not evidence that the approximation is better.

## Pipelines

Both pipelines use the canonical M1 calibration routes, physical-edge sets, Jaccard threshold 0.5, Louvain resolution 1, and Louvain seed 42. Placement uses the M4 weights and the existing weighted greedy selector, on the eligible-edge version of the same routes. Held-out coverage uses the original 250 evaluation routes. Those routes are not graph nodes.

Exact pipeline:

1. All-pairs exact Jaccard.
2. Keep pairs at or above 0.5. Every calibration route stays a node, including isolates.
3. Louvain.
4. Community-balanced weights.
5. Weighted greedy.

Approximate pipeline:

1. MinHash signatures and a banded LSH index, seed 42.
2. Candidate pairs.
3. Exact Jaccard verification. Pairs below 0.5 are dropped.
4. The same thresholded graph, Louvain, weights, and greedy.

Only retrieval is approximate. A kept edge stores the exact Jaccard, computed again after verification. A missed true pair removes an edge. Verification cannot add a pair that exact Jaccard would reject. The run checks that the node sets match, that every approximate edge is an exact edge, and that shared edges have the same weight.

Lambda 0 ignores the partition. It reproduced the saved M2/M4 greedy selections for every graph in this study.

## Configurations

The primary bandings are the M3 calibration operating points. The script aborts if they differ from `outputs/m3/summary.json`.

| Scenario | Role | Permutations | Bands × rows | Why it is here |
| --- | --- | ---: | --- | --- |
| uniform | primary | 32 | 16 × 2 | M3 operating point, calibration recall 0.998 |
| commuter_proxy | primary | 128 | 32 × 4 | M3 operating point, calibration recall 0.957 |
| both | high recall | 64 | 32 × 2 | Calibration retrieval recall 1.000 |
| both | moderate recall | 64 | 16 × 4 | Calibration retrieval recall about 0.82–0.84 |
| both | aggressive reduction | 32 | 4 × 8 | Calibration retrieval recall about 0.10–0.12 |

These three extra bandings already exist in the MinHash implementation. They were chosen from the M3 calibration retrieval table, before looking at placement. Held-out coverage was not used to pick them.

Placement settings, also fixed beforehand: K = 10 and 20, lambda 0.25, and lambda 0.5 as a sensitivity. Lambda 0 is the control.

Community agreement uses the adjusted Rand index and normalized mutual information. Both ignore the numeric community labels. Representation of large communities (size at least 2) is scored against the exact Louvain partition, so both selections are judged on the same groups. Representation of a pipeline's own communities is stored separately and is not that comparison. Modularity is computed on each graph separately. Those two numbers are not a ranking.

## Graph edges

Exact uniform graph: 500 nodes, 511 edges, 178 isolates. Exact commuter graph: 500 nodes, 691 edges, 127 isolates. The exact Louvain counts matched M3: 241 uniform communities (63 non-singletons, 178 singletons) and 191 commuter communities (64 non-singletons, 127 singletons). The exact selections matched the saved M4 edges.

| Scenario | Banding | Edges kept | Missed | Graph-edge recall | Candidates | Candidate reduction |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| uniform | primary | 510/511 | 1 | 0.9980 | 5,457 | 0.956 |
| uniform | high recall | 511/511 | 0 | 1.0000 | 7,985 | 0.936 |
| uniform | moderate | 419/511 | 92 | 0.8200 | 975 | 0.992 |
| uniform | aggressive | 53/511 | 458 | 0.1037 | 56 | 1.000 |
| commuter_proxy | primary | 661/691 | 30 | 0.9566 | 1,790 | 0.986 |
| commuter_proxy | high recall | 691/691 | 0 | 1.0000 | 8,522 | 0.932 |
| commuter_proxy | moderate | 577/691 | 114 | 0.8350 | 1,276 | 0.990 |
| commuter_proxy | aggressive | 83/691 | 608 | 0.1201 | 90 | 0.999 |

High-recall retrieval kept every exact graph edge. The primary uniform banding missed one edge. The primary commuter banding missed 30. Aggressive retrieval kept about one tenth of the edges.

## Communities

| Scenario | Banding | ARI | NMI | Communities | Singletons | Largest |
| --- | --- | ---: | ---: | --- | --- | --- |
| uniform | primary | 0.967 | 0.997 | 241 → 240 | 178 → 178 | 27 → 27 |
| uniform | high recall | 1.000 | 1.000 | 241 → 241 | 178 → 178 | 27 → 27 |
| uniform | moderate | 0.825 | 0.979 | 241 → 259 | 178 → 193 | 27 → 24 |
| uniform | aggressive | 0.088 | 0.896 | 241 → 454 | 178 → 421 | 27 → 7 |
| commuter_proxy | primary | 0.874 | 0.985 | 191 → 193 | 127 → 130 | 23 → 31 |
| commuter_proxy | high recall | 1.000 | 1.000 | 191 → 191 | 127 → 127 | 23 → 23 |
| commuter_proxy | moderate | 0.848 | 0.975 | 191 → 214 | 127 → 148 | 23 → 22 |
| commuter_proxy | aggressive | 0.112 | 0.872 | 191 → 434 | 127 → 392 | 23 → 7 |

Missing one uniform edge moves the partition slightly (ARI 0.967) and leaves the singleton count and the largest community unchanged. Missing 30 commuter edges moves it more (ARI 0.874) and changes the largest community from 23 to 31 routes. Aggressive retrieval breaks the groups: ARI falls to about 0.09 and the largest community falls to 7.

NMI stays above 0.87 even in that aggressive case. Both partitions are then mostly singletons, so NMI still sees a lot of routes that are alone in both partitions. ARI is the metric that shows the corridor groups were not preserved. A high ARI does not by itself mean the counters will match. The commuter primary partition has ARI 0.874 and, at K = 10, the counters still match.

## Placements

Held-out coverage below is the original evaluation sample. The difference is approximate minus exact. Shared locations are counted against the exact-pipeline selection. Large-community representation is scored on the exact partition.

Lambda 0 selected the same edges for every partition. Those edges are the saved greedy placements. Held-out coverage at lambda 0 is 72.8% uniform and 69.2% commuter at K = 10.

| Scenario | Banding | λ | K | Shared | Set Jaccard | Held-out | Difference | Exact-partition large communities |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| uniform | primary | 0.25 | 10 | 9/10 | 0.818 | 71.2% | −1.2 pp | 54/54, same as exact |
| uniform | primary | 0.25 | 20 | 20/20 | 1.000 | 81.2% | 0 | 63/63 |
| uniform | primary | 0.50 | 10 | 9/10 | 0.818 | 71.6% | +0.4 pp | 54/54 |
| uniform | primary | 0.50 | 20 | 19/20 | 0.905 | 81.2% | 0 | 63/63 |
| uniform | high recall | 0.25 and 0.50 | 10 and 20 | all | 1.000 | same as exact | 0 | same as exact |
| uniform | moderate | 0.25 | 10 | 9/10 | 0.818 | 71.2% | −1.2 pp | 54/54 |
| uniform | moderate | 0.50 | 10 | 10/10 | 1.000 | 71.2% | 0 | 54/54 |
| uniform | aggressive | 0.25 | 10 | 9/10 | 0.818 | 72.8% | +0.4 pp | 54/54 |
| uniform | aggressive | 0.50 | 10 | 7/10 | 0.538 | 70.8% | −0.4 pp | 54/54 |
| uniform | aggressive | 0.50 | 20 | 13/20 | 0.481 | 83.2% | +2.0 pp | 62/63 |
| commuter_proxy | primary | 0.25 | 10 | 10/10 | 1.000 | 66.8% | 0 | 56/56 |
| commuter_proxy | primary | 0.25 | 20 | 20/20 | 1.000 | 84.0% | 0 | 64/64 |
| commuter_proxy | primary | 0.50 | 10 | 10/10 | 1.000 | 68.4% | 0 | 58/58 |
| commuter_proxy | primary | 0.50 | 20 | 19/20 | 0.905 | 83.6% | 0 | 64/64 |
| commuter_proxy | high recall | 0.25 and 0.50 | 10 and 20 | all | 1.000 | same as exact | 0 | same as exact |
| commuter_proxy | moderate | 0.25 | 10 and 20 | all | 1.000 | same as exact | 0 | same as exact |
| commuter_proxy | moderate | 0.50 | 10 | 6/10 | 0.429 | 66.4% | −2.0 pp | 55/58 |
| commuter_proxy | aggressive | 0.25 | 10 | 5/10 | 0.333 | 70.4% | +3.6 pp | 50/56 |
| commuter_proxy | aggressive | 0.25 | 20 | 13/20 | 0.481 | 83.2% | −0.8 pp | 63/64 |
| commuter_proxy | aggressive | 0.50 | 10 | 5/10 | 0.333 | 70.0% | +1.6 pp | 51/58 |
| commuter_proxy | aggressive | 0.50 | 20 | 10/20 | 0.333 | 85.6% | +2.0 pp | 63/64 |

The exact held-out figures that these differences use are the M4 figures: uniform 72.4% and 81.2% at lambda 0.25 for K = 10 and 20, and 71.2% and 81.2% at lambda 0.5; commuter 66.8% and 84.0% at lambda 0.25, and 68.4% and 83.6% at lambda 0.5.

At the operating points used by M3, the placement change is small. Uniform primary K = 10 and lambda 0.25 replaces one segment and loses 1.2 percentage points of held-out coverage, without losing a large community of the exact partition. Commuter primary K = 10 keeps the same segments at both lambdas, even though 30 graph edges are missing and the ARI is 0.874. At K = 20 and lambda 0.5 it replaces one segment and the held-out coverage stays 83.6%.

The aggressive banding is the case that separates the metrics. Commuter lambda 0.25 at K = 10 shares only 5 segments and gains 3.6 percentage points of held-out coverage, while exact-partition representation falls from 56 to 50 large communities. That gain is not a better solution of the exact community objective. The weights were built from a different partition.

## Runtime and memory

Two measurements are kept separate. The first is a single pass in which `tracemalloc` and the clock ran together. That pass compares the materialized exact pipeline, which stores every pairwise similarity, with one verified-LSH banding. The second is a repeated comparison of three pipelines. Its timing repeats do not start `tracemalloc`. Its memory repeats are separate and are not used as runtimes. The first-pass files are kept as `outputs/integrated/first_pass_*`.

### First single-pass measurement

Memory is the peak reported by `tracemalloc` during one end-to-end call. It is Python-tracked allocation, not the operating-system process size. Stage times are a second pass. They do not add up exactly to the end-to-end call. This is the original benchmark. It is not the fair three-method comparison below.

On the canonical 500 calibration routes, K = 10 and lambda 0.25:

| Scenario | Banding | Exact seconds | Exact MB | LSH seconds | LSH MB |
| --- | --- | ---: | ---: | ---: | ---: |
| uniform | 32 perm, 16 × 2 | 0.500 | 14.1 | 0.427 | 3.40 |
| commuter_proxy | 128 perm, 32 × 4 | 0.512 | 14.0 | 1.100 | 7.01 |

At 500 routes the exact cost is the all-pairs table, about 0.39 seconds of the stage pass, and about 14 MB. The uniform operating point is slightly faster and uses about a quarter of that tracked memory. The commuter operating point is slower because 128 permutations take about 0.96 seconds to sign. Louvain and greedy are about 0.07 and 0.03 seconds in the stage pass, so they do not decide the comparison at this size.

The larger timing collection is a new uniform draw of 2,000 simulated routes, seed 24242, the same generator and seed family as the M5 retrieval benchmark. Generation is excluded. Both pipelines see the same prefix of 500, 1,000, and 2,000 routes. The banding is the uniform operating point, 32 × 16 × 2, not the 128-permutation commuter point. The coverage difference in this table is calibration coverage of that timing sample. It is not a held-out score.

| Routes | Exact seconds | Exact MB | LSH seconds | LSH MB | Edges missed | Recall | ARI | Calibration coverage difference |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 0.487 | 14.1 | 0.374 | 3.41 | 1 | 0.9980 | 1.000 | 0 |
| 1,000 | 1.791 | 54.9 | 0.778 | 8.50 | 6 | 0.9969 | 0.999 | 0 |
| 2,000 | 6.912 | 217 | 1.923 | 19.9 | 43 | 0.9946 | 0.974 | 0 |

At 2,000 routes the exact stage pass in that traced run spends 6.42 seconds on pairwise Jaccard. Signatures, the index query, and verification take 0.89, 0.13, and 0.33 seconds. Louvain is about 0.43 seconds for both graphs under tracing. These few sizes do not identify an asymptotic crossover. They do show that, for this 32-permutation banding, the verified pipeline is already faster than the materialized exact pipeline at 500 routes and the gap is wider at 1,000 and 2,000, while tracked memory grows much more slowly. In this traced single pass, the 128-permutation banding was not faster than materialized exact Jaccard at 500 canonical routes.

### Streaming exact baseline

The materialized pipeline keeps every pairwise similarity, then throws away the pairs below 0.5 when it builds the graph. The streaming pipeline computes the same Jaccard values and discards a pair as soon as it is below 0.5. It stores only the qualifying weighted edges, and it still adds every route as a node.

On the canonical calibration routes it reproduces the materialized graph, including edge weights, the Louvain partition at seed 42, and the selected counters. That check covers both scenarios, lambda 0, 0.25, and 0.5, and K = 10 and 20: six selections per scenario. The uniform graph has 511 edges and the commuter graph has 691. The same identity holds on the timing prefixes of 500, 1,000, and 2,000 routes for the K = 10, lambda 0.25 selection used in the benchmark. The original exact pipeline and the M3/M4 outputs were not changed.

### Repeated three-method comparison

The collection is the same seed-24242 uniform draw. Generation is excluded. Each end-to-end call includes graph construction, Louvain, weights, and greedy at K = 10 and lambda 0.25. Timing is five `perf_counter` repeats with tracemalloc off. The table reports the median, the sample standard deviation, and the minimum and maximum. Peak memory is the median of three separate tracemalloc runs. Stage times are one further elapsed-time pass, not one of the five repeats and not a memory run.

The verified-LSH column here is the uniform operating point, 32 permutations and 16 bands of 2 rows.

| Routes | Materialized median (min–max) | Streaming median (min–max) | LSH 32×16×2 median (min–max) |
| ---: | --- | --- | --- |
| 500 | 0.231 s (0.230–0.232), SD 0.001 | 0.227 s (0.225–0.227), SD 0.001 | 0.073 s (0.073–0.074), SD 0.000 |
| 1,000 | 1.018 s (0.984–1.142), SD 0.062 | 0.920 s (0.916–0.945), SD 0.015 | 0.179 s (0.177–0.196), SD 0.008 |
| 2,000 | 3.753 s (3.734–3.800), SD 0.026 | 3.633 s (3.615–3.722), SD 0.043 | 0.545 s (0.526–0.597), SD 0.027 |

Median peak tracked memory, in MB:

| Routes | Materialized exact | Streaming exact | LSH 32×16×2 |
| ---: | ---: | ---: | ---: |
| 500 | 14.0 | 1.69 | 3.41 |
| 1,000 | 54.9 | 3.30 | 8.47 |
| 2,000 | 217 | 7.25 | 19.8 |

At 2,000 routes the materialized pipeline uses about 217 MB and the streaming pipeline uses 7.25 MB for the same graph, the same partition, and the same ten counters. The 32-permutation LSH pipeline uses 19.8 MB. Most of the memory gap in the first benchmark, 217 MB against 20 MB, was the stored list of all pairwise similarities. Against the streaming baseline, LSH uses more tracked memory, not less. Signatures and candidate buckets cost more than the qualifying edge list.

LSH remains faster than that streaming baseline. At 2,000 routes the median is 0.545 s against 3.633 s. The five repeats do not overlap. Streaming is only slightly faster than materialized exact, because both still evaluate every pair. At 2,000 routes the elapsed stage pass spends 3.67 s building the full pair list and 3.73 s in the streaming thresholded scan. Louvain is about 0.05 s and greedy about 0.02 s in that untraced pass. The traced stage times in the first benchmark are slower and should not be added to these figures.

The other pre-specified bandings were timed the same way. None was chosen or dropped because of held-out coverage.

| Routes | 32×16×2 | 64×32×2 high recall | 64×16×4 moderate | 32×4×8 aggressive | 128×32×4 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 0.073 s, 10/10 counters | 0.120 s, 10/10 | 0.097 s, 8/10 | 0.053 s, 5/10 | 0.176 s, 10/10 |
| 1,000 | 0.179 s, 10/10 | 0.286 s, 10/10 | 0.201 s, 7/10 | 0.105 s, 6/10 | 0.361 s, 7/10 |
| 2,000 | 0.545 s, 10/10 | 0.849 s, 10/10 | 0.456 s, 9/10 | 0.208 s, 7/10 | 0.818 s, 8/10 |

Aggressive reduction is the fastest banding at every size, and it does not reproduce the counters. Among bandings that keep all ten counters on this collection, 32×16×2 is the fastest at every size. The order of the other bandings does change: at 2,000 routes the moderate banding is faster than 32×16×2, and the 128-permutation banding is faster than the high-recall banding. Those two faster bandings no longer select the same ten segments. On this collection the 128-permutation banding matches the exact selection at 500 routes and not at 1,000 or 2,000, even though its graph-edge recall stays near the calibration operating point. A configuration picked for agreement at 500 routes is not automatically the same choice at 2,000. This benchmark did not retune one.

## Answers

The placement answers below are from the canonical routes. The runtime answers have a later revision in the streaming section. That revision does not replace the placement results.

1. At the M3 operating points, verified LSH keeps 510 of 511 uniform graph edges and 661 of 691 commuter edges. A high-recall banding keeps all of them. An aggressive banding does not.
2. One missed uniform edge changes Louvain only slightly. Thirty missed commuter edges change it more, including the largest community, but not beyond recognition (ARI 0.874). Aggressive retrieval does change the communities substantially (ARI about 0.09).
3. High-recall partitions produce the same counters as the exact pipeline. The uniform primary partition changes one K = 10 counter at lambda 0.25. The commuter primary partition keeps all ten at both tested lambdas. Aggressive retrieval changes most of the counters once lambda is above 0.
4. Where the counters change at the primary bandings, held-out coverage moves by at most 1.2 percentage points in this sample. Larger coverage gaps appear only after the graph has lost most of its edges. A coverage increase in that regime is not a win for the approximate objective.
5. In the first traced pass, the 32-permutation pipeline is faster than materialized exact Jaccard, and the 128-permutation pipeline is slower at 500 canonical routes. In the repeated timing-only comparison, both are faster than the streaming exact baseline at 500, 1,000, and 2,000 routes on the seed-24242 collection. Placement itself is a small part of the time.
6. With 32 permutations, 16 bands, and 2 rows, LSH is faster than both exact pipelines at every tested size from 500 to 2,000. Against streaming exact, the median gap is about 0.15 s at 500 routes and about 3.1 s at 2,000. No smaller size was added after seeing these times.
7. The useful tradeoff is still the primary and high-recall bandings: nearly the same communities and counters, and less time than exact Jaccard. Their memory advantage was mostly against the materialized pair list. Streaming exact uses less tracked memory than those LSH bandings. Aggressive candidate reduction is cheaper still and does not preserve the communities.
8. Several primary-banding differences are one counter, or zero counters, on a single 250-route evaluation sample. That is too small a change to claim a practical difference in placement quality. It is large enough to show that a missed edge can move a counter.

## Limitations

The evaluation sample is the original held-out draw, one sample per scenario. A 1.2 percentage point gap is one or a few routes. The timing collection is a different simulated draw, and its coverage difference is not held-out. Only two route scenarios and four pre-specified bandings were compared. Modularity is not compared across graphs. NMI should not be read as preservation of the non-singleton corridors when ARI is low. Nothing here is a measurement of cyclists.

## Files

`scripts/run_integrated_study.py` writes `outputs/integrated/`. The canonical M1–M5 hashes were checked before and after the run and did not change.

Figures from the placement comparison: `graph_recall.png`, `partition_agreement.png`, `placement_overlap_k10.png`, `coverage_difference_k10.png`. The first single-pass timing figures are `runtime.png` and `stage_breakdown.png`, also kept as `first_pass_runtime.png` and `first_pass_stage_breakdown.png`. The repeated three-method figures are `fair_runtime.png`, `fair_memory.png`, `fair_bandings.png`, and `fair_stages.png`.

Tables: `graph_comparison.csv`, `communities.csv`, `placements.csv`, `canonical_timing.csv`, `scalability.csv`, `streaming_equivalence.csv`, `fair_timing_runs.csv`, `fair_timing_summary.csv`, `fair_stages.csv`, and `summary.json`. The first single-pass timing tables are `first_pass_scalability.csv` and `first_pass_canonical_timing.csv`.
