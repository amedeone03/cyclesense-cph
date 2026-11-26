# Route-choice-aware counter placement

The placements below are algorithmic suggestions on simulated routes. They are not approved installations. Coverage is modeled-route coverage. It is not a count of cyclists.

## Question

M5.6 held the M4 counters fixed and replaced held-out shortest paths with seeded detours. Uniform greedy at K=10 fell from 72.8% on the shortest paths to 65.7% at a 15% cap and 65.3% at a 30% cap, on seeds 91000–91019. Community-balanced placement lost coverage as well. This study asks whether choosing the counters on several simulated route choices, instead of on shortest paths alone, holds up better on held-out origin–destination pairs.

The hypotheses were fixed before these held-out scores were computed. All five can fail. They did not all succeed.

## Objective

For a set of eligible physical segments \(S\) with \(|S|=K\),

\[
F(S)=\sum_s \alpha_s \sum_r w_{s,r}\, I(\text{route}_{s,r}\cap S\neq\emptyset).
\]

Here \(s\) is a training scenario, \(r\) is a simulated realization of a calibration origin–destination pair, \(\alpha_s=1/2\) for uniform and commuter-proxy, and the route weights \(w_{s,r}\) are nonnegative and sum to 1. A route counts once, through its eligible physical-edge IDs.

The primary weights put half of each scenario on the original shortest paths and half on the alternative realizations. Inside each half, every calibration OD pair gets the same weight. If one OD pair has more realizations, that weight is split across them. Generating another alternative does not make the OD pair more important. The two scenarios keep equal total weight even when they contain different numbers of OD pairs. In this run each scenario has 500 calibration routes.

The control uses the same two scenarios and the same shortest paths, with no alternatives. It isolates the effect of the detours from the effect of pooling the two OD distributions. The existing uniform greedy, commuter greedy, and \(\lambda=0.25\) placements stay as saved scenario-specific references. They are not refit.

Each coverage indicator is monotone and submodular in \(S\): adding a segment cannot uncover a route, and the marginal gain of a segment falls as \(S\) grows. A nonnegative weighted sum of such functions is still monotone and submodular. The standard greedy algorithm therefore keeps the \(1-1/e\) approximation for this calibration objective. That guarantee does not extend to held-out coverage, to the minimum over seeds, to observed cyclist traffic, or to a maximin objective. This study optimizes expected coverage. It does not solve a worst-case problem. The lowest seed in the sample is a stress statistic, not a bound. Seed percentiles are not confidence intervals. The seeds share OD pairs.

The selector is the existing weighted greedy in `placement.select_greedy`, including the same deterministic tie break and the same fill to exactly \(K\) when further segments add no training weight. The algorithm was not rewritten.

## Training and evaluation

Training uses the saved M1 calibration OD pairs only. The perturbation is the M5.6 model: each directed edge is multiplied by \(\exp(0.35 Z)\) with \(Z\) standard normal, in sorted edge order. A different physical path is kept when its original-length detour is at most 15%. Otherwise the recorded route is the original shortest path and the status says why. Failed alternatives are kept. They are not dropped.

Training seeds are 82000–82009. They do not overlap the M5.6 seeds 91000–91019 or the fresh evaluation seeds 92000–92019. Sigma, the cap, and the seeds are in `configs/pilot.yaml` and were written to `outputs/robust_placement/experiment_config.json` before held-out scoring. They were not changed after the scores were seen.

Held-out OD pairs stay the saved M1 evaluation pairs. Placements are not retrained per condition. The fresh seeds are the numbers reported below. The reference seeds reproduce the saved M5.6 means for the existing greedy placements, with a difference of 0 from the stored four-decimal means. Shortest-path coverage of the saved greedy and balanced placements matches the M4 held-out values within 0.0005.

Of the 10,000 training alternatives, 85.4% used a different physical path inside the cap. The table contains 11,000 realizations and 8,565 distinct eligible-edge sets.

## Held-out coverage

Fresh seeds 92000–92019. Entries are mean modeled-route coverage in percent. The shortest-path column does not depend on the seed.

### K = 10

| Placement | Uniform shortest | Uniform 15% | Uniform 30% | Commuter shortest | Commuter 15% | Commuter 30% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform greedy | 72.8 | 65.1 | 64.7 | 70.0 | 61.5 | 60.9 |
| Commuter greedy | 62.4 | 57.7 | 57.4 | 69.2 | 64.0 | 63.6 |
| Pooled shortest | 72.0 | 64.1 | 63.5 | 73.2 | 63.2 | 62.5 |
| Robust pooled | 69.6 | 63.0 | 62.5 | 72.4 | 64.2 | 63.6 |
| Balanced \(\lambda=0.25\), own scenario | 72.4 | 64.0 | 63.4 | 66.8 | 63.0 | 62.6 |

### K = 20

| Placement | Uniform shortest | Uniform 15% | Uniform 30% | Commuter shortest | Commuter 15% | Commuter 30% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Uniform greedy | 84.0 | 78.2 | 78.0 | 83.6 | 76.0 | 75.3 |
| Commuter greedy | 80.8 | 78.2 | 78.0 | 86.8 | 81.4 | 81.2 |
| Pooled shortest | 85.2 | 80.4 | 80.1 | 86.0 | 80.7 | 80.2 |
| Robust pooled | 83.2 | 78.6 | 78.5 | 85.2 | 79.2 | 78.9 |
| Balanced \(\lambda=0.25\), own scenario | 81.2 | 76.3 | 76.1 | 84.0 | 79.4 | 79.4 |

About 83.5% of uniform held-out routes and 85.1% of commuter held-out routes changed at the 15% cap. The 30% cap changes 87.3% and 88.8%. The extra cap moves mean coverage by only a few tenths of a point, as in M5.6.

On the training objective, the robust K=10 set covers 69.4% of the weighted calibration realizations. The pooled shortest-path set covers 69.1% of that same objective. The optimizer did find a small training gain. It does not show up as a held-out gain.

## What the comparison says

Against the pooled shortest-path control, at the 15% cap:

- Uniform K=10: robust is 1.1 points lower. It is ahead on 2 of 20 seeds.
- Commuter K=10: robust is 1.0 point higher. It is ahead on 14 of 20 seeds.
- Uniform K=20: robust is 1.8 points lower. It is ahead on 2 of 20 seeds.
- Commuter K=20: robust is 1.5 points lower. It is ahead on 6 of 20 seeds.

The mean of the two scenario means at K=10 and 15% is 63.6% for pooled shortest paths and 63.6% for robust (63.62 and 63.56 before rounding). The minimum of the two scenario means is 63.2% for pooled and 63.0% for robust. Pooling the scenarios does raise the weaker scenario: commuter shortest-path coverage is 73.2% for the shared shortest-path set and 69.2% for the commuter-only greedy. Robust placement gives part of that commuter gain back and loses uniform shortest-path coverage, from 72.0% pooled to 69.6%.

Loss from each method's own shortest-path baseline is smaller for robust than for pooled at K=10 (6.6 versus 7.9 points on uniform; 8.2 versus 10.0 on commuter). That is not a more robust placement. The robust shortest-path coverage was already lower, so there was less left to lose. At K=20 on commuter routes the robust loss is larger, not smaller. Sample standard deviations at K=10 and 15% are 4.3 and 4.4 points on uniform, and 5.2 and 5.8 points on commuter. The spreads are similar.

Pooled shortest paths rank above robust on shortest-path coverage in every primary cell. That order reverses on 20% of uniform K=10 seeds and on 85% of commuter K=10 seeds. The reversal is a one-point commuter gain, not a general improvement.

K=10 robust counters, in greedy order. The calibration gain is the training objective, not a held-out gain.

| Rank | Street | Also in pooled K=10 |
| --- | --- | --- |
| 1 | Knippelsbro / Børsgade | yes |
| 2 | Gothersgade | yes |
| 3 | Lille Kongensgade | yes |
| 4 | Rigsdagsgården | yes |
| 5 | Gammeltorv | yes |
| 6 | Lille Langebro | yes |
| 7 | Gammel Mønt | yes |
| 8 | Nyhavnsbroen | yes |
| 9 | Nørre Voldgade | no |
| 10 | Nørre Farimagsgade | yes |

The pooled set uses Øster Voldgade instead of Nørre Voldgade. Nine of ten segments are shared. The K=10 robust set is contained in the K=20 robust set. At K=20 the two shared methods share 14 of 20 segments.

The training routes are still the same OD pairs, and most of the weight remains on corridors the shortest paths already use. A 0.2-point training gain from one swapped segment is too small to move held-out coverage in one direction.

## Municipal additions

The 26 name-verified published counting locations stay fixed. They are recurring count sites, not confirmed permanent sensors. Five further segments are chosen with the same robust weights, on calibration routes the 26 do not already cover, using the existing incremental greedy. The original five are the saved scenario-specific additions. They were not recomputed. None of the new segments repeats one of the 26.

Fresh-seed coverage, percent:

| Set | Uniform shortest | Uniform 15% | Commuter shortest | Commuter 15% |
| --- | ---: | ---: | ---: | ---: |
| 26 sites | 73.6 | 75.3 | 72.4 | 72.9 |
| 26 + original five | 83.6 | 82.3 | 82.8 | 79.5 |
| 26 + robust five | 83.2 | 82.5 | 82.8 | 81.0 |

The robust five are an unnamed segment `pe:268690821:13040511678:1419068140`, Rigsdagsgården, an unnamed segment `pe:697791:6646132086:659328721`, Larsbjørnsstræde, and Store Kongensgade. Two of those are also in the saved uniform additions, and Store Kongensgade is in the saved commuter additions. On these simulated routes the robust additions match the original commuter shortest-path gain and add about 1.5 points on commuter alternatives. They give up 0.4 points of uniform shortest-path coverage. The 26-site baseline itself barely moves under the detours. This does not explain the published AADT values, and it does not approve the five segments.

## Computation

Route generation took 7.2 seconds. Building the weight table took 0.004 seconds. Greedy selection took 0.012 seconds for pooled K=10 and 0.113 seconds for robust K=10. K=20 took 0.021 and 0.176 seconds. A separate tracemalloc pass, not included in those times, peaked at 25.6 MB of Python-tracked memory for the robust selector. The whole command took about 36 seconds, most of it in the two held-out seed blocks. These times are for 500 calibration OD pairs per scenario, 10 training seeds, and 250 held-out routes per scenario. They are not a claim about larger samples. The M5.7 benchmarks were not rerun.

## Limitations

The alternatives are one log-normal cost field with \(\sigma=0.35\), not estimated rider behaviour. Expected coverage is not protection against the worst seed. Optimizing across the two scenarios is not the same as succeeding on both when the counters are later scored separately. A calibration gain of 0.2 points is not held-out evidence. Simulated coverage is not bicycle traffic. The study rectangle still cuts routes at its boundary.

For the DTU report, the useful result is the negative one. Training on these detours does not beat a fair shortest-path greedy that already sees both OD scenarios. The earlier coverage drop under route choice remains a property of the held-out paths, not a defect that this objective removes.
