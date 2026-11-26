# CycleSense CPH — Study plan

## Goal

Place **K** bicycle counters on eligible cycling-network edges to study trade-offs between:

- held-out modeled-route interception;
- representation of distinct *route-overlap* communities;
- robustness to changing simulated OD and route-choice distributions;
- computation time and memory.

## Research questions

1. **Similarity (LSH):** What recall and computational savings do MinHash/LSH offer versus exact route-pair Jaccard evaluation?
2. **Placement:** Does community-aware placement represent more distinct route communities than global greedy at the same K? What coverage penalty does it incur?
3. **Robustness:** How sensitive are the counter locations and their held-out performance to shifted OD sampling and alternative routes?

## Unit of observation

- Cycling network: directed or undirected **edges** from a versioned, audited OSMnx bike graph.
- Routes: edge sequences and (for overlap) sets of normalized physical-edge IDs.
- Candidate sensor: an eligible physical-edge counting line; directionality assumed and documented.
- Route is *covered* if it intersects >=1 selected counter edge.

## Central optimization baseline

For route set R and candidate edges C, with route weights w >= 0:

`F(S) = sum_{r in R} w[r] * 1[route r intersects S] / sum_{r in R} w[r]`, subject to `S subset C` and `|S| <= K`.

With a fixed route set, nonnegative weights and only this cardinality constraint, the greedy maximum coverage objective is monotone and submodular, so the standard `(1 - 1/e)` approximation guarantee applies. This guarantee does not automatically apply to every fairness extension.

## Community-aware extension

- Find approximate route-neighbor candidates using MinHash/LSH.
- Verify candidate overlap using exact Jaccard; build a sparse route-overlap graph.
- Detect route communities using Louvain.
- Define and preregister a diversity objective, e.g. a community-balanced route-weighting variant, **before** evaluating results.
- Compare community-aware strategy with global greedy and geographical K-Means.

## Evaluation protocol

- **Feasibility**: audited connected subgraph; realistic counter candidates; working route generator.
- **Exact baselines**: exhaustive pairwise Jaccard on *small samples*, route-frequency baseline, greedy coverage.
- **LSH quality**: pairwise recall and precision at Jaccard threshold, candidate reduction, runtime, peak RAM.
- **Coverage**: held-out weighted route coverage versus K (same candidates and scenarios across methods).
- **Diversity**: number/fraction of represented communities; community-wise held-out coverage; worst-covered community.
- **Robustness**: evaluate all methods under held-out OD distributions, alternative-route choices, and single-counter failures.
- **Scalability**: separate preprocessing time (routing, signature building, graph creation) from optimization time.
- **Uncertainty**: multiple independent seeds and variability intervals. Do not tune on test routes.

## Limitations

Synthetic routes are not measured trips. Route-overlap communities may reflect graph geometry and scenario design rather than actual cycling behavior. This is a methodological benchmark, not a validated municipal installation plan.

## Milestones

1. Repository setup and synthetic unit tests.
2. Small Copenhagen graph and two or more plausible routing scenarios. The M1 pilot rectangle, physical-edge rule, and the uniform / commuter-proxy samplers are specified in `docs/m1_assumptions.md`. Alternative-route generation is deferred.
3. Strong baseline performance, defined metric and held-out validation. The M2 protocol is `docs/m2_baselines.md`. MinHash, LSH, and Louvain stay out of that run.
4. LSH route-similarity graph, Louvain, and community-aware placement. The similarity graph and Louvain record is `docs/m3_communities.md`. The community-balanced placement record is `docs/m4_optimization.md`.
5. Scenario-shift, computation, and visualization. The validation record is `docs/m5_final_validation.md`. The graded notebook is not part of that run.
