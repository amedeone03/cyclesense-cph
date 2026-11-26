# M5.7 large-scale scalability

The integrated pipeline builds a Jaccard graph, runs Louvain, and places ten counters with community weights at lambda 0.25. This study asks how that pipeline behaves as the number of simulated routes grows from 500 to 10,000. It does not ask whether LSH is always the better method. The routes are simulated shortest paths on the fixed pilot network. They are not 10,000 observed trips.

The collection is a new draw, seed 73000. It is not the seed-24242 timing collection from the integrated study, so these seconds are not a rerun of that table.

## Design

One call to the M1 generator drew 10,000 uniform calibration routes. The 500, 1,000, 2,000, 5,000, and 10,000 benchmarks are prefixes of that list. A separate 250-route evaluation sample uses seed 73001 and excludes every benchmark origin–destination pair and physical path. Those routes are scored after placement. They are not graph nodes.

Similarity uses physical-edge sets. Placement and coverage use eligible edges and the saved candidate list. Louvain uses threshold 0.5, resolution 1, and seed 42. The budget is K = 10 and lambda 0.25.

Streaming exact computes every pair, discards pairs below 0.5 immediately, and does not store the full similarity list. Verified LSH keeps an edge only after exact Jaccard verification. No materialized all-pairs list is built at any size.

The primary banding is 32 permutations and 16 bands of 2 rows, the faster uniform configuration from the earlier calibration experiments. Three existing alternatives are included and were not chosen from this study’s coverage: 64×32×2, 64×16×4, and 128×32×4. Recall is recomputed on this draw. It is not copied from the smaller study.

Timing repeats use `perf_counter` and exclude route generation, graph loading, and tracemalloc. Memory repeats are separate tracemalloc peaks. They are not process RSS and are not used as runtimes. Repeats are five at 500, 1,000, and 2,000, and three at 5,000 and 10,000 for LSH. Streaming exact is repeated five times through 2,000 and three times at 5,000. The 10,000 streaming run was allowed by a pre-specified rule, because the 5,000 median was under 60 seconds and the graph had fewer than 250,000 edges, and that rule assigned it one timing repeat and one memory repeat. Stage times are one additional pass, not one of those repeats.

The machine is macOS 26.6.2 on arm64, Python 3.14.4, NetworkX 3.7. These timings belong to this process.

## Dataset

Generation took 4.7 seconds and 11,337 attempts. All 10,000 requested routes were kept. Every stored physical-edge sequence is unique, so the duplicate fraction in the benchmark file is 0. The sampler rejected 1,263 pairs for distance, 48 repeated origin–destination attempts, 7 same-node draws, and 19 routes with too few eligible edges. The route generator rejected 0 paths because the physical sequence had already been kept.

| Routes | Mean segments | Median segments | Unique segments |
| ---: | ---: | ---: | ---: |
| 500 | 27.7 | 27 | 1,401 |
| 1,000 | 27.5 | 27 | 1,512 |
| 2,000 | 27.4 | 27 | 1,586 |
| 5,000 | 27.5 | 27 | 1,626 |
| 10,000 | 27.5 | 27 | 1,633 |

The segment vocabulary almost stops growing after 2,000 routes. Additional routes are new sequences through nearly the same streets. That is a property of shortest paths on one small network, not evidence that cyclists repeat 10,000 independent journeys.

## Runtime

Median end-to-end seconds. The range is the fastest and slowest repeat. The 10,000 streaming value is a single observation.

| Routes | Streaming exact | LSH 32×16×2 | LSH 64×32×2 | LSH 64×16×4 | LSH 128×32×4 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 0.210 (0.210–0.222) | 0.068 (0.067–0.068) | 0.112 (0.110–0.141) | 0.090 (0.089–0.091) | 0.163 (0.161–0.178) |
| 1,000 | 0.847 (0.836–0.852) | 0.165 (0.164–0.167) | 0.269 (0.266–0.289) | 0.189 (0.187–0.206) | 0.341 (0.334–0.356) |
| 2,000 | 3.344 (3.325–3.439) | 0.485 (0.483–0.509) | 0.763 (0.757–0.779) | 0.425 (0.422–0.446) | 0.762 (0.744–0.772) |
| 5,000 | 21.27 (21.18–21.91) | 2.555 (2.550–2.573) | 3.818 (3.816–3.845) | 1.496 (1.495–1.497) | 2.420 (2.410–2.446) |
| 10,000 | 85.29 | 10.28 (10.23–10.30) | 14.86 (14.79–14.91) | 4.55 (4.51–4.56) | 7.03 (6.98–7.04) |

Against streaming exact, primary LSH is 3.1, 5.1, 6.9, 8.3, and 8.3 times faster at these five sizes. The last ratio compares three LSH repeats with one streaming observation. No repeat was cut short by the time budget, and no banding hit the candidate cap of 8,000,000 pairs or the bucket cap of 12,000 routes.

## Memory

Median tracemalloc peak, in megabytes. This is Python-tracked allocation during the call, not the operating-system resident set.

| Routes | Streaming exact | LSH 32×16×2 | LSH 64×32×2 | LSH 64×16×4 | LSH 128×32×4 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 1.7 | 3.5 | 5.5 | 4.1 | 7.4 |
| 1,000 | 3.3 | 8.5 | 12.3 | 8.2 | 14.9 |
| 2,000 | 7.1 | 19.8 | 27.5 | 17.1 | 30.7 |
| 5,000 | 31.3 | 84.7 | 118 | 48.6 | 77.8 |
| 10,000 | 115 | 327 | 452 | 158 | 183 |

Streaming exact uses less tracked memory than every LSH banding at every size. Primary LSH uses about three times the streaming peak at 10,000 routes. The memory advantage of LSH in the older materialized comparison does not appear once the exact baseline stops storing every pair.

## Candidates

Primary LSH retrieves a steady 4.2% of all route pairs. The reduction stays near 95.8% while the absolute candidate count still grows quadratically, because the pair set itself is quadratic.

| Routes | Possible pairs | 32×16×2 candidates | 64×32×2 | 64×16×4 | 128×32×4 | Largest bucket |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 124,750 | 5,334 | 7,955 | 1,101 | 1,485 | 39 |
| 1,000 | 499,500 | 20,673 | 30,703 | 4,137 | 5,750 | 72 |
| 2,000 | 1,999,000 | 82,335 | 120,532 | 15,859 | 22,480 | 149 |
| 5,000 | 12,497,500 | 523,035 | 772,133 | 101,165 | 145,785 | 363 |
| 10,000 | 49,995,000 | 2,094,016 | 3,087,433 | 410,519 | 587,825 | 731 |

The largest bucket is from 64×32×2. It grows with the sample and remains far below the cap. Candidate verification, not signature construction, becomes the expensive LSH stage. At 500 routes, signatures are about half of the primary end-to-end time. At 10,000 routes they are 0.75 of about 10.6 seconds in the stage pass, while verification takes 6.39 seconds and Louvain 1.53 seconds. Weights and greedy stay under 0.1 seconds. Streaming exact remains almost entirely the all-pairs scan: 85.9 of 87.1 stage-pass seconds at 10,000 routes, with Louvain at 1.06 seconds.

## Retrieval where the exact graph exists

Streaming exact finished at every size, including 10,000 routes, so the recall figures are full-graph recalls. No subset substitute is used. Every retained LSH weight matched the exact Jaccard, and no banding added an edge the exact graph did not have.

| Routes | 32×16×2 recall | Missed | ARI | Shared counters | 64×32×2 missed | 64×16×4 recall | 128×32×4 recall |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 500 | 0.996 | 2 | 0.998 | 8/10 | 0 | 0.839 | 0.954 |
| 1,000 | 0.996 | 8 | 0.940 | 4/10 | 0 | 0.847 | 0.959 |
| 2,000 | 0.997 | 27 | 0.991 | 10/10 | 0 | 0.836 | 0.955 |
| 5,000 | 0.996 | 178 | 0.918 | 9/10 | 1 | 0.828 | 0.956 |
| 10,000 | 0.997 | 666 | 0.901 | 10/10 | 8 | 0.833 | 0.958 |

Primary recall stays near 0.996. Adjusted Rand declines from 0.998 to 0.901. That is still a similar partition, and it is not the same ten counters at every size. At 1,000 routes the primary selection shares only 4 of 10 edges with streaming exact even though it misses only 8 graph edges.

The 64×32×2 banding misses 0, 0, 0, 1, and 8 edges. It selects the same ten counters as streaming exact through 5,000 routes and 9 of 10 at 10,000. Its ARI at 10,000 is 0.932, so a handful of missing edges can move the partition. It is also the slowest and most memory-heavy LSH setting, because it retrieves about 6.2% of pairs.

The 64×16×4 banding is the fastest at every size and keeps 82.8–84.7% of the edges. The 128×32×4 banding keeps about 95.4–95.9%. It is slower than 32×16×2 at 500 routes, where signatures dominate, and faster at 5,000 and 10,000 routes, where verification dominates and it has fewer candidates. That crossover was not used to change the primary configuration.

## Graph structure

For the streaming graph, density stays near 0.004. Average degree rises almost in proportion to the sample: 2.0, 3.8, 7.8, 19.7, 39.6. The largest component grows from 54 routes to 9,724 of 10,000. Isolate fraction falls from 0.35 to 0.013, while the isolate count only falls from 174 to 125. Louvain communities number 248, 288, 339, 286, and 214. The median community size stays 1. The largest community grows from 21 to 729.

Primary LSH tracks those figures closely. The graph is becoming one large component of highly overlapping simulated paths, plus a shrinking share of isolates. Modularity on that graph is not evidence of distinct cyclist populations. A larger sample from this network adds edges among routes that already share streets.

## Placement

Calibration coverage for streaming exact is 70.6%, 69.6%, 67.6%, 68.6%, and 69.1%. The same selections cover 68.0%, 66.8%, 64.8%, 68.8%, and 66.0% of the fixed 250 held-out routes. Coverage does not rise as the calibration sample grows. Consecutive streaming selections have Jaccard similarity 0.33, 0.33, 0.43, and 0.54. Primary LSH moves at least as much: 0.18, 0.43, 0.43, and 0.67 between those sizes.

The share of large communities represented by the exact selection falls from 0.82 at 500 routes to 0.51 at 10,000 routes. K stays at 10 while the largest community grows. More simulated routes do not, by themselves, make a ten-counter placement cover more of the partition or more of the held-out routes.

Held-out differences between LSH and streaming exact are small once the counters match, and they are not a reason to prefer an approximate graph. At 1,000 routes the primary selection has lower calibration coverage and higher held-out coverage than the exact selection. That held-out gap is one 250-route sample, and the counters were not chosen to produce it.

## Answers

1. Verified LSH processes 5,000 routes. Primary median runtime is 2.55 seconds and the tracemalloc peak is 85 MB.
2. It processes 10,000 routes on this machine. Primary median runtime is 10.3 seconds and the peak is 327 MB. Streaming exact also finished, in 85.3 seconds and 115 MB, with one timing repeat.
3. Candidate counts grow quadratically, at a nearly constant fraction of all pairs: about 4.2% for 32×16×2, 6.2% for 64×32×2, 0.8–0.9% for 64×16×4, and 1.2% for 128×32×4.
4. Streaming exact is limited by the all-pairs scan. Primary LSH is limited by candidate verification once the sample is large. Louvain is the next visible cost at 10,000 routes, at about 1.1–1.5 seconds. Greedy placement is not the bottleneck.
5. Signature construction is about half of primary runtime at 500 routes and about 7% at 10,000 routes.
6. No. Against streaming exact, LSH uses more tracked memory at every size. The earlier memory gap was mostly the materialized pair list, which this study does not build.
7. Stored routes do not repeat as whole paths. They do become highly overlapping: unique segments level off near 1,633, and the fraction of pairs above Jaccard 0.5 stays near 0.4%, so degree grows with the sample.
8. Community count does not grow with the sample. One component absorbs most routes, singleton communities remain the median, and the largest community grows. Partitions from primary LSH stay recognizably close to the exact partition, with ARI from 0.998 down to 0.901.
9. Exact comparisons exist at all five sizes. Edge recall for the primary banding is stable. The selected counters are not. They match exactly at 2,000 and 10,000 routes, share 9 of 10 at 5,000, and only 4 of 10 at 1,000.
10. Streaming exact is the better choice when the exact edge set is required or when tracked memory matters. Through 2,000 routes its runtime is a few seconds. At 10,000 routes it still fits in a few minutes and about 115 MB. LSH is the better choice when a few minutes is too long and missing well under 1% of edges, for the primary banding, is acceptable. The fastest banding, 64×16×4, is not a substitute if the exact counters matter: it misses about one edge in six.

## Limitations

The pilot network is small, and every route is a shortest path. A more diverse set of real journeys could produce fewer pairs above 0.5, smaller buckets, and a different runtime ranking. The 10,000 streaming figure is one pass. The held-out score is one 250-route sample. Bandings were fixed before this run. Nothing here was selected because it raised held-out coverage.

## Report use

The final report can say that verified LSH remains practical at 10,000 simulated routes on this network, that its speed advantage over streaming exact grows from about 3 times to about 8 times, and that streaming exact still uses less tracked memory. It should also say that a larger simulated sample does not settle the ten counter locations, and that these routes reuse a few thousand street segments.

## Files

`src/cyclesense/scalability.py`, `src/cyclesense/scalability_plots.py`, `scripts/run_scalability_study.py`, and `tests/test_scalability.py`. Outputs are under `outputs/scalability/`: `benchmark_config.json`, `dataset_diagnostics.csv`, `timing_runs.csv`, `timing_summary.csv`, `memory_results.csv`, `candidate_statistics.csv`, `graph_statistics.csv`, `validation_results.csv`, `selected_placements.csv`, `stage_times.csv`, `summary.json`, `runtime.png`, `memory.png`, `candidates.png`, `stages.png`, `graph_growth.png`, and `agreement.png`.
