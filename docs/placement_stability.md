# Placement stability across calibration draws

The question is which eligible street segments the existing greedy rule keeps selecting when the simulated calibration sample changes, and which segments appear only for some draws. Selection frequency is a property of this simulator and this optimizer. It is not a probability that a physical counter would be optimal for observed cyclists, and it is not a measure of bicycle demand.

The canonical M1 routes are left unchanged. Each replicate draws its own origin–destination sample on the saved routing graph, with the same distance limits, eligibility rule, and candidate universe as M1. Held-out routes stay out of selection and are used only to score the finished sets.

## Design

Thirty replicates use seeds `103000`–`103029`, stored in `configs/pilot.yaml`. Replicate `i` draws 500 uniform routes and 500 commuter-proxy routes from seed `103000 + i`. The two scenarios share the integer seed and use different samplers, so the draws are paired without being the same routes. The generator is asked for zero evaluation routes. No bootstrap of the canonical sample is used.

Methods, all using the existing greedy selector:

- Uniform greedy at K = 10 and K = 20.
- Commuter-proxy greedy at K = 10 and K = 20.
- Pooled shortest-path greedy at K = 10. Replicate `i` pools that replicate's two scenario samples with equal scenario weight.
- Route-choice-augmented pooled greedy at K = 10. The objective is the M5.9 objective: sigma 0.35, a 15% detour cap, and 10 perturbation seeds per replicate. Those seeds are `113000`–`113299`, disjoint from the calibration seeds and from the M5.9 training and evaluation seeds.

A street name can label more than one physical segment. Frequencies are computed per physical id and are not averaged across scenarios.

Pairwise Jaccard values reuse the same replicates, so the 435 pairs inside one method are not an independent sample. Means, medians, and the empirical 5th and 95th percentiles below are descriptive. The normalized entropy is the entropy of `frequency / K` divided by the log of the number of distinct selected segments. It is a concentration summary of the selection slots.

## What is selected repeatedly

Knippelsbro / Børsgade (`pe:2195105934:10169925770:1694109-1111604185`) is selected in all 30 draws for every method in this study, and it is the first greedy choice in every uniform K = 10 draw.

Uniform K = 10 then concentrates on a few other segments:

| Frequency | Mean rank | Segment |
| ---: | ---: | --- |
| 100% | 1.0 | Knippelsbro / Børsgade |
| 90% | 4.3 | Rigsdagsgården |
| 73% | 6.9 | Gammel Mønt |
| 57% | 6.7 | Lille Langebro |
| 50% | 2.1 | Gothersgade `pe:24987042:300094192:36522887` |

Five uniform K = 10 segments are selected in at least half of the draws. Two reach 80%. The other 56 segments that appear at least once are usually rare: 986 of the 1,047 eligible segments are never selected. The frequency histogram is a spike near zero plus a short tail.

Commuter K = 10 has the same always-selected bridge, then a different second segment: Gammeltorv `pe:697783:5305065025:1794685` in 97% of draws, mean rank 2.6. Rigsdagsgården is at 77% and Lille Langebro at 70%. The same Gothersgade id as above is at 57%. Fifty-eight segments appear at least once. Uniform and commuter therefore share a bridge and a handful of central segments, and they do not share the same second-ranked corridor.

The saved M2 sets are not typical of these draws. Mean Jaccard with the canonical uniform K = 10 placement is 0.30. That placement's own Gothersgade segment, `pe:706815:300094223:36522887`, is selected in 17% of the new uniform draws, while a different Gothersgade segment is selected in 50%. Mean Jaccard with the canonical commuter K = 10 placement is 0.17. Several of its streets, including Nørregade, Holbergsgade, and the canonical Vestergade / Gammeltorv segment, stay below 10%. The high-frequency Gammeltorv id is not that canonical segment.

## Set stability

| Placement | Distinct segments | In every draw | At least 80% | At least 50% | Mean Jaccard | Median | 5th–95th | Shared counters |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Uniform K=10 | 61 | 1 | 2 | 5 | 0.27 | 0.25 | 0.11–0.43 | 4.1 (1–8) |
| Uniform K=20 | 132 | 2 | 3 | 9 | 0.22 | 0.21 | 0.11–0.33 | 7.0 (3–12) |
| Commuter K=10 | 58 | 1 | 2 | 5 | 0.28 | 0.25 | 0.18–0.43 | 4.3 (2–8) |
| Commuter K=20 | 141 | 1 | 3 | 9 | 0.22 | 0.21 | 0.11–0.33 | 7.1 (3–13) |
| Pooled K=10 | 41 | 1 | 3 | 7 | 0.37 | 0.33 | 0.18–0.67 | 5.3 (2–9) |
| Route choice K=10 | 49 | 1 | 3 | 7 | 0.34 | 0.33 | 0.18–0.54 | 4.9 (1–9) |

Increasing K raises the number of shared counters and the number of segments that ever appear. It does not raise Jaccard similarity. A K = 20 set still replaces most of its members from one draw to the next.

Pooled training is more stable than either scenario-specific rule: fewer distinct segments, three segments at or above 80%, and mean Jaccard 0.37 against 0.27 and 0.28. Route-choice training, with the M5.9 objective held fixed, is close to the pooled shortest-path result and is not more stable than it. Mean Jaccard with the saved pooled placement is 0.48. Mean Jaccard with the saved route-choice placement is 0.43.

Normalized entropy is about 0.85–0.90 for every method. The selection slots are spread across the segments that appear, which matches the long low-frequency tail.

## Coverage of the unstable sets

Calibration coverage stays in a narrow band while the sets change. For the pooled and route-choice rows, held-out coverage is the average of the uniform and commuter evaluation scores. The scenario-specific rows use their own evaluation split.

| Placement | Calibration mean (min–max) | Held-out mean (min–max) |
| --- | --- | --- |
| Uniform K=10 | 71.4% (68.0–76.0) | 70.0% (65.6–73.6) |
| Uniform K=20 | 88.8% (86.8–91.0) | 84.4% (82.0–88.0) |
| Commuter K=10 | 74.3% (70.2–78.4) | 69.5% (66.4–72.0) |
| Commuter K=20 | 91.0% (87.2–92.8) | 84.3% (80.8–86.8) |
| Pooled K=10 | 71.4% (69.0–74.6) | 70.8% (67.8–73.0) |
| Route choice K=10 | 68.4% (66.0–71.9) | 70.0% (65.2–73.0) |

Sample standard deviations are about 1–2 percentage points. Held-out ranges of 6–8 points on 250 simulated routes show that distinct placements can land near one another without being interchangeable. The descriptive correlation between pairwise Jaccard and the absolute held-out difference is about −0.11 for uniform K = 10 and −0.35 for the route-choice sets. Those pairs are not independent, and the correlations are not a test. They do not say that a more overlapping pair has a reliably smaller held-out gap.

No replicate was chosen because its held-out coverage was high. There is no consensus placement in the reported scores.

## Relation to the exact benchmark

M5.10 found certified optima that match greedy at K = 10 and still use different segments, with held-out coverage that can move by a few points. This resampling shows the same kind of flatness from the other direction: many K = 10 sets, sharing on average about four counters, have calibration coverage inside a roughly eight-point band and held-out coverage inside a similar band. That is a related observation about the simulated objective. It does not identify a cause of the MILP-versus-greedy held-out difference, and it does not say which of those segments would capture real trips.

## Limitations

The draws share one network, one eligibility rule, and one greedy algorithm. They vary the origin–destination sample. They do not vary the map, the detour cap inside the route-choice objective, or the selector. Frequencies can change if those choices change. The commuter proxy is still a spatial kernel around Rådhuspladsen, not an observed commute matrix. Pairwise percentiles are descriptions of dependent pairs. The study took about four minutes on this machine, including the 30 route-choice replicates, and did not need a bootstrap fallback.
