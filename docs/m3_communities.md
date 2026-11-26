# M3 route similarity and communities

M3 compares simulated calibration routes by the physical street segments they traverse. A similarity is not an observed flow, and a community is not a measured cyclist type. Community-aware counter placement is not part of this run.

`scripts/run_m3.py` reads `data/processed/m1/` and does not rewrite those files or the M2 placement results.

## Representation

Each route is the set of physical-edge identifiers on its shortest path. Empty routes are dropped. Exact overlap is `jaccard_similarity` from `cyclesense.similarity`. Calibration scenarios are compared separately. The pair count for 500 non-empty routes is 124,750.

## MinHash and LSH

Signatures use 64-bit MinHash rows from a fixed seed (`42` for the calibration study). The banding grid is:

| Permutations | Bands × rows |
| --- | --- |
| 32 | 16×2, 8×4, 4×8 |
| 64 | 32×2, 16×4, 8×8 |
| 128 | 64×2, 32×4, 16×8, 8×16 |

A candidate pair shares at least one band. Recall and precision use exact Jaccard at 0.3, 0.5, and 0.7. Preprocessing is signature construction plus the bucket index. Query time is the probe of that index. Verification time is exact Jaccard on the candidates.

The operating point, chosen on calibration pairs only, is the banding at threshold 0.5 with recall at least 0.95 and the smallest candidate set. If none reaches 0.95, the highest recall is kept. That choice does not decide which edges enter the Louvain graph.

## Graph and Louvain

The graph uses every calibration route as a node. An edge exists when exact Jaccard is at least the threshold, and its weight is that Jaccard value. Thresholds are 0.3, 0.4, 0.5, 0.6, and 0.7. The primary threshold is 0.5, the value already stored in `configs/pilot.yaml`.

Louvain uses NetworkX with resolution 1 and seeds 42, 43, 44, 45, and 46. It is not asked for a community count. Isolated routes remain nodes.

Pair agreement is the fraction of route pairs for which two seeds agree on whether the routes share a community. Grouped-pair recall is the fraction of pairs that share a community under one seed and still share one under the other seed.

A partition is called collapsed when its largest community holds at least 80% of the routes. It is called fragmented when the largest community holds under 5% of the routes, or at least 80% of routes are singletons. Otherwise it is mixed. Those labels describe the sizes. They are not a model-selection rule.

## Held-out assignment

Louvain is not refit on evaluation routes. At a threshold, an evaluation route's neighbors are the calibration routes with exact Jaccard at least that threshold.

- No neighbors: unassigned.
- Neighbors in one community: assigned to that community.
- Neighbors in several communities: ambiguous, and left unassigned.

## Scalability

An independent uniform sample is generated in memory with seed 24242. It is not written into the canonical route file. Reported similarity times exclude route generation. Exact time is a count of all pairs. LSH time is split into preprocessing and query. The banding is the uniform operating point from the calibration study.

## Map

`outputs/m3/communities.html` draws one representative calibration route per community of at least two routes. The representative is the member with the highest mean exact Jaccard to the other members. The page opens the five largest uniform communities that have at least three routes. The layer control starts collapsed, and the other communities stay available there. Street names are hover text. The basemap is the local BBBike extract.

The numeric record below is filled from `outputs/m3/summary.json` after `scripts/run_m3.py` finishes.

## Execution record

`scripts/run_m3.py` completed on the saved M1 routes. Each scenario has 500 non-empty calibration routes and 250 evaluation routes. Acceptance checks passed. The pair list for each scenario has 124,750 exact comparisons.

### Exact Jaccard

| Scenario | Mean | Median | 90th | 99th | Pairs at 0 | Pairs ≥ 0.5 | Time | Peak memory |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform | 0.026 | 0.000 | 0.082 | 0.370 | 91,930 | 511 | 0.40 s | 14.8 MB |
| commuter_proxy | 0.027 | 0.000 | 0.086 | 0.404 | 91,002 | 691 | 0.38 s | 14.8 MB |

Pairs at or above each threshold:

| Scenario | 0.1 | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform | 10,369 | 4,542 | 2,182 | 1,033 | 511 | 207 | 66 | 20 | 1 |
| commuter_proxy | 10,963 | 4,988 | 2,498 | 1,295 | 691 | 340 | 127 | 38 | 6 |

Most route pairs do not overlap. The stored-pair memory is about 15 MB because every pair is retained.

### MinHash / LSH

The calibration operating points, using the pre-specified recall rule at Jaccard 0.5, are:

| Scenario | Permutations | Bands × rows | Recall | Precision | Candidates | Preprocess | Query | Verify |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| uniform | 32 | 16 × 2 | 0.998 | 0.093 | 5,457 | 0.23 s | 0.008 s | 0.020 s |
| commuter_proxy | 128 | 32 × 4 | 0.957 | 0.369 | 1,790 | 0.92 s | 0.004 s | 0.007 s |

High-recall bandings still return many false candidates. Precision at 0.5 is 0.09 for the uniform operating point, so the candidates have to be checked with exact Jaccard. Narrower bands raise precision and lose recall. For example, uniform with 128 permutations and 8 bands of 16 rows keeps 8 candidates and recall 0.016 at threshold 0.5.

On 500 routes, exact comparison already finishes in about 0.4 s. LSH plus verification is in the same range. It becomes the faster comparison once the sample is larger. On an independent uniform sample, with the uniform operating point and routing time excluded:

| Routes | Exact | LSH preprocess | LSH query | Verify | Recall | Precision |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 0.014 s | 0.051 s | 0.001 s | 0.001 s | 1.000 | 0.092 |
| 250 | 0.082 s | 0.116 s | 0.001 s | 0.005 s | 1.000 | 0.102 |
| 500 | 0.402 s | 0.236 s | 0.010 s | 0.023 s | 1.000 | 0.092 |
| 1,000 | 1.445 s | 0.447 s | 0.024 s | 0.092 s | 0.999 | 0.088 |
| 2,000 | 5.845 s | 0.915 s | 0.102 s | 0.404 s | 0.999 | 0.087 |

The scalability exact timer counts pairs and does not store them, so its peak memory stays under 0.04 MB. LSH preprocess peak memory grows from 0.2 MB at 100 routes to 3.3 MB at 2,000. Route generation for the 2,000-route sample took 1.1 s and is not included above.

### Similarity graph at the primary threshold 0.5

| Scenario | Edges | Density | Components | Isolates | Edge-weight mean |
| --- | ---: | ---: | ---: | ---: | ---: |
| uniform | 511 | 0.0041 | 238 | 178 | 0.597 |
| commuter_proxy | 691 | 0.0055 | 186 | 127 | 0.616 |

Raising the threshold removes edges quickly. At 0.3 the graphs have 2,182 and 2,498 edges. At 0.7 they have 66 and 127.

### Louvain, seed 42

| Scenario | Threshold | Communities | Size ≥ 2 | Singletons | Largest | Modularity | Reading |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| uniform | 0.3 | 62 | 19 | 43 | 79 | 0.811 | mixed |
| uniform | 0.5 | 241 | 63 | 178 | 27 | 0.913 | mixed |
| uniform | 0.7 | 438 | 46 | 392 | 5 | 0.970 | fragmented |
| commuter_proxy | 0.3 | 55 | 26 | 29 | 76 | 0.828 | mixed |
| commuter_proxy | 0.5 | 191 | 64 | 127 | 23 | 0.933 | fragmented |
| commuter_proxy | 0.7 | 390 | 56 | 334 | 9 | 0.969 | fragmented |

The commuter result at 0.5 is labeled fragmented because the largest community holds 23 of 500 routes, under the pre-specified 5% line. Across seeds 42–46 the community count at threshold 0.5 only moves from 240 to 241 (uniform) and from 190 to 191 (commuter). Mean grouped-pair recall at that threshold is 0.922 for uniform and 0.963 for commuter. The lowest uniform grouped-pair recall between two seeds is 0.830. Membership of the pairs that sit together is mostly stable, and it is not identical from seed to seed.

The communities with at least three routes share named streets: Gothersgade, Nørregade, Bremerholm, Vindebrogade, Havnegade, and Kongens Nytorv appear among the high-support edges. Those are corridor fragments. They do not organize most routes. At threshold 0.5, 178 uniform routes and 127 commuter routes remain isolated.

### Held-out assignment

Neighbors are calibration routes with exact Jaccard at least the threshold. Ambiguous routes are not assigned.

| Scenario | Threshold | Assigned | Ambiguous | Unassigned |
| --- | ---: | ---: | ---: | ---: |
| uniform | 0.3 | 139 (55.6%) | 96 (38.4%) | 15 |
| uniform | 0.5 | 138 (55.2%) | 33 (13.2%) | 79 |
| uniform | 0.7 | 45 (18.0%) | 5 (2.0%) | 200 |
| commuter_proxy | 0.3 | 159 (63.6%) | 73 (29.2%) | 18 |
| commuter_proxy | 0.5 | 142 (56.8%) | 43 (17.2%) | 65 |
| commuter_proxy | 0.7 | 68 (27.2%) | 22 (8.8%) | 160 |

At the primary threshold, a bit more than half of the evaluation routes match one calibration community. The rest are either too dissimilar or match more than one community.

### Acceptance

The run kept calibration and evaluation route ids apart, built each similarity graph from calibration routes only, and covered every calibration route exactly once in each Louvain partition. M3 acceptance checks passed. Community-aware placement was not run.
