"""Write notebooks/analysis.ipynb. This does not execute it."""

from __future__ import annotations

from pathlib import Path

import nbformat
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

ROOT = Path(__file__).resolve().parents[1]


def md(source: str):
    return new_markdown_cell(source.strip() + "\n")


def code(source: str):
    return new_code_cell(source.strip() + "\n")


CELLS = [
    md(r"""
# CycleSense CPH

## Simulated-route coverage for bicycle counters in central Copenhagen

CycleSense asks where a small number of counters on the mapped street network would intercept simulated bicycle routes. The computational work combines a monotone submodular coverage objective, MinHash and locality-sensitive hashing, Louvain communities on a route-similarity graph, and checks against published municipal counts.

OpenStreetMap describes mapped infrastructure. The cycling routes are simulated origin–destination paths. The municipal bicycle counts are observed screenline data. **Coverage is the share of simulated routes that touch a chosen segment. It is not the share of cyclists a counter would record.**

### Research questions

1. **Optimization.** How effectively can a limited number of counter locations cover simulated cycling routes?
2. **Computational methods.** Can MinHash/LSH find similar routes quickly while preserving Louvain structure and the counters chosen from it?
3. **Generalization.** How stable are the selected locations across route distributions, route-choice assumptions, and calibration samples?
4. **Interpretation.** How do the optimized locations relate to published municipal counting sites, and where does the simulation stop being evidence about the city?

The pilot is the Indre By rectangle used throughout the study. Algorithms below run on small examples with the project's own functions. The Copenhagen numbers are read from tables exported from the saved experiments (`notebooks/assets/`). Those experiments are not rerun here. The optional interactive planner is a separate local page, `outputs/planner/cyclesense_planner.html`, and is not required for this notebook.
"""),
    code("""
import csv
import json
import platform
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display

HERE = Path.cwd().resolve()
ROOT = next(
    (candidate for candidate in (HERE, *HERE.parents) if (candidate / "pyproject.toml").is_file() and (candidate / "src" / "cyclesense").is_dir()),
    None,
)
if ROOT is None:
    raise FileNotFoundError("Open or run this notebook from the CycleSense repository.")
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
ASSETS = ROOT / "notebooks" / "assets"
if not (ASSETS / "provenance.json").is_file():
    raise FileNotFoundError("Missing notebooks/assets. From the repository root run python scripts/export_notebook_assets.py")

plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False, "font.size": 11, "figure.dpi": 120})
COLORS = {
    "greedy": "#163e72",
    "milp": "#2457a6",
    "random": "#9a9a9a",
    "geographical_kmeans": "#e09a3e",
    "route_frequency": "#5f8f6a",
    "streaming_exact": "#163e72",
    "verified_lsh": "#c47b2b",
}


def load_csv(name):
    path = ASSETS / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing notebook asset {name}.")
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_json(name):
    path = ASSETS / name
    if not path.is_file():
        raise FileNotFoundError(f"Missing notebook asset {name}.")
    return json.loads(path.read_text(encoding="utf-8"))


def show(figure):
    display(figure)
    plt.close(figure)


print(f"Python {platform.python_version()}")
for module_name in ("numpy", "scipy", "networkx", "matplotlib", "pandas"):
    module = __import__(module_name)
    print(f"{module_name} {module.__version__}")
print(f"Assets: {ASSETS.relative_to(ROOT)}")
"""),
    md(r"""
## 1. Data and network

The street graph is OpenStreetMap, accessed through the BBBike Copenhagen extract and cut to the study rectangle with OSMnx. The PBF is a living extract, not a frozen historical snapshot. The published graph uses the local file whose SHA-256 is stored with the dataset summary. The extract is not in Git. © OpenStreetMap contributors, ODbL.

A **physical segment** joins the two directions of one carriageway. Parallel ways between the same corners keep different identifiers. Counters are eligible physical segments: long enough, and not rejected by the bicycle-access and service rules in the M1 audit. Eligibility is a tag-and-length filter, not a permit to install a counter.

Routes are shortest paths on that graph. Uniform routes draw both ends inside the rectangle. Commuter-proxy routes are biased toward a city-hall anchor. Each scenario has 500 calibration routes and 250 held-out routes. The two splits do not share origin–destination pairs. Every accepted draw has weight 1. That weight is a sample weight, not a bicycle count. Placement uses the calibration split only.
"""),
    code("""
dataset = load_json("dataset.json")
graph = dataset["graph"]
routes = dataset["routes"]
print(f"Rectangle: west {dataset['boundary']['west']}, south {dataset['boundary']['south']}, east {dataset['boundary']['east']}, north {dataset['boundary']['north']}")
print(f"Extracted: {dataset['extraction_utc']}")
print(f"Routing graph: {graph['routing_nodes']} nodes, {graph['routing_edges']} directed edges, {graph['physical_segments']} physical segments")
print(f"Eligible counter segments: {graph['candidates']}")
print(f"Routes: {routes['valid_total']} total; calibration {routes['calibration']}; held-out {routes['evaluation']}")
print(f"Seeds: calibration {routes['seeds']['calibration']}, held-out {routes['seeds']['evaluation']}")
print(routes["scenario_weight_meaning"])

lengths = pd.DataFrame(load_csv("route_lengths.csv"))
lengths["n_edges"] = lengths["n_edges"].astype(int)
summary = lengths.groupby(["scenario", "split"])["n_edges"].agg(["count", "median", "mean", "min", "max"]).round(1)
display(summary)

figure, axes = plt.subplots(1, 2, figsize=(8.2, 3.4), sharey=True)
for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy")):
    for split, color, label in (("calibration", "#163e72", "Calibration"), ("evaluation", "#e09a3e", "Held-out")):
        values = lengths[(lengths.scenario == scenario) & (lengths.split == split)]["n_edges"]
        axis.hist(values, bins=15, histtype="step", linewidth=1.8, color=color, label=label)
    axis.set_title(title)
    axis.set_xlabel("Physical segments on the simulated route")
axes[0].set_ylabel("Routes")
axes[1].legend(frameon=False)
figure.suptitle("Route length in the saved pilot sample", y=1.02)
figure.tight_layout()
show(figure)
"""),
    code("""
graph_path = ROOT / "data/processed/m1/copenhagen_bike_routing_wgs84.graphml"
if not graph_path.is_file():
    print("Optional network map skipped. The saved GraphML is not in this checkout.")
else:
    import osmnx as ox
    from cyclesense.placement_stability_plots import physical_lines

    ox.settings.use_cache = True
    ox.settings.log_console = False
    lines = physical_lines(ox.load_graphml(graph_path))
    figure, axis = plt.subplots(figsize=(6.2, 6.0))
    for line in lines.values():
        if len(line) < 2:
            continue
        axis.plot([point[1] for point in line], [point[0] for point in line], color="#c8c4bc", linewidth=0.45)
    axis.set_aspect("equal")
    axis.set_axis_off()
    axis.set_title("Saved bicycle routing graph, Indre By core")
    figure.text(0.02, 0.02, "Mapped streets. Not observed bicycle trips.", color="#444444")
    figure.tight_layout()
    show(figure)
    print(f"Drew {len(lines)} physical segments from the local graph.")
"""),
    md(r"""
## 2. Maximum-coverage optimization

A counter set \(S\) covers a simulated route when the route's physical segments intersect \(S\). With route weights \(w_r\),

\[
F(S) = \sum_r w_r \, \mathbf{1}(E_r \cap S \neq \emptyset).
\]

\(F\) counts each route once. It is monotone and submodular. The greedy algorithm adds the eligible segment with the largest marginal gain and breaks ties by identifier. For a cardinality constraint, that greedy rule is guaranteed to reach at least \(1 - 1/e \approx 63.2\%\) of the optimal value of this objective (Nemhauser, Wolsey and Fisher, 1978). The guarantee is about the calibration objective. It is not a guarantee about held-out routes or about cyclists.

The next cell runs the project's greedy and exact search on a six-route example. The figure after it is the saved Copenhagen comparison: random placement, geographic K-means, route-frequency ranking, and greedy coverage. Random and K-means use seed 42. Greedy and route frequency are deterministic.
"""),
    code("""
from cyclesense.coverage import evaluate_coverage, greedy_max_coverage
from cyclesense.exact_optimization import brute_force_maximum_coverage, meets_approximation_guarantee

example = {
    "r1": {"a", "b"},
    "r2": {"a", "c"},
    "r3": {"b", "d"},
    "r4": {"c"},
    "r5": {"e"},
    "r6": {"d", "e"},
}
weights = {route_id: 1.0 for route_id in example}
eligible = ["a", "b", "c", "d", "e"]
greedy = greedy_max_coverage(example, 2, eligible_edges=eligible, weights=weights)
optimum, optimum_weight = brute_force_maximum_coverage(example, weights, eligible, 2)
greedy_coverage = evaluate_coverage(example, greedy.selected_edges, weights).coverage_fraction
optimum_coverage = optimum_weight / sum(weights.values())
print("Greedy edges:", greedy.selected_edges)
print(f"Greedy coverage: {greedy_coverage:.3f}")
print(f"Best coverage of size at most 2: {optimum_coverage:.3f} on {optimum}")
print("Meets the 1 - 1/e guarantee:", meets_approximation_guarantee(greedy_coverage, optimum_coverage))
previous = 0.0
for budget in (1, 2):
    chosen = greedy_max_coverage(example, budget, eligible_edges=eligible, weights=weights)
    coverage = evaluate_coverage(example, chosen.selected_edges, weights).coverage_fraction
    print(f"K={budget}: coverage {coverage:.3f}, marginal gain {coverage - previous:.3f}")
    previous = coverage
"""),
    code("""
baselines = pd.DataFrame(load_csv("baselines.csv"))
baselines["k"] = baselines["k"].astype(int)
for column in ("calibration_coverage", "heldout_coverage"):
    baselines[column] = baselines[column].astype(float)
labels = {
    "greedy": "Greedy",
    "route_frequency": "Route frequency",
    "geographical_kmeans": "Geographic K-means",
    "random": "Random",
}
figure, axes = plt.subplots(1, 2, figsize=(8.4, 3.6), sharey=True)
for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy")):
    for method in ("random", "geographical_kmeans", "route_frequency", "greedy"):
        subset = baselines[(baselines.scenario == scenario) & (baselines.method == method)].sort_values("k")
        axis.plot(subset["k"], 100 * subset["heldout_coverage"], "o-", color=COLORS[method], label=labels[method])
    axis.set_title(title)
    axis.set_xlabel("Counter budget K")
    axis.set_xticks([5, 10, 20, 30])
    axis.set_ylim(0, 100)
axes[0].set_ylabel("Held-out modeled-route coverage (%)")
axes[1].legend(frameon=False, fontsize=8)
figure.suptitle("Saved baseline comparison", y=1.02)
figure.tight_layout()
show(figure)
heldout = baselines[baselines.k == 10][["scenario", "method", "calibration_coverage", "heldout_coverage"]]
display(heldout.sort_values(["scenario", "heldout_coverage"]))
"""),
    md(r"""
### Reading the baseline

On the uniform held-out routes at \(K = 10\), greedy covers 72.8% and route frequency 40.4%. Geographic K-means covers 18.0% and one random draw covers 6.4%. The same order appears in the commuter-proxy sample. Greedy is strong here because the objective rewards segments that add routes not already covered, while frequency piles counters onto one busy corridor and K-means spreads them in space without looking at the routes.

Calibration coverage is higher than held-out coverage for greedy (74.0% against 72.8% at uniform \(K = 10\)). The gap is the difference between the sample used to choose the counters and a sample from the same route generator. It is not a measurement of cyclists.
"""),
    md(r"""
## 3. Certified optimization

The same objective can be written as a mixed-integer linear program. A binary variable \(x_e\) selects segment \(e\), and a binary variable \(y_r\) records that route \(r\) is covered:

\[
\max \sum_r w_r y_r
\quad
\sum_e x_e \le K
\quad
y_r \le \sum_{e \in E_r} x_e
\quad
x_e, y_r \in \{0, 1\}.
\]

The project solves this with SciPy's HiGHS interface. A solution is called optimal only when the solver status is optimal. The next cell certifies the six-route example. The table is the saved unweighted benchmark on the 1,047 eligible segments and the 500 calibration routes.
"""),
    code("""
from cyclesense.coverage import evaluate_coverage, greedy_max_coverage
from cyclesense.exact_optimization import greedy_optimality_gap, solve_maximum_coverage

example = {
    "r1": {"a", "b"},
    "r2": {"a", "c"},
    "r3": {"b", "d"},
    "r4": {"c"},
    "r5": {"e"},
    "r6": {"d", "e"},
}
weights = {route_id: 1.0 for route_id in example}
eligible = ["a", "b", "c", "d", "e"]
greedy_result = greedy_max_coverage(example, 2, eligible_edges=eligible, weights=weights)
greedy_coverage = evaluate_coverage(example, greedy_result.selected_edges, weights).coverage_fraction
certified = solve_maximum_coverage(example, weights, eligible, 2, time_limit_seconds=10, mip_rel_gap=1e-6)
print(f"Status: {certified.status}; proven optimal: {certified.proven_optimal}")
print(f"Certified coverage: {certified.coverage:.3f}")
print(greedy_optimality_gap(certified.coverage, greedy_coverage, proven=certified.proven_optimal))

exact = pd.DataFrame(load_csv("exact_comparison.csv"))
for column in ("k", "exact_coverage", "greedy_coverage", "absolute_gap", "heldout_greedy", "heldout_exact", "n_shared", "milp_seconds"):
    exact[column] = pd.to_numeric(exact[column])
display(exact[["scenario", "k", "status", "proven_optimal", "greedy_coverage", "exact_coverage", "absolute_gap", "heldout_greedy", "heldout_exact", "n_shared"]].sort_values(["scenario", "k"]))

figure, axes = plt.subplots(1, 2, figsize=(8.4, 3.5), sharey=True)
for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy")):
    subset = exact[exact.scenario == scenario].sort_values("k")
    axis.plot(subset["k"], 100 * subset["greedy_coverage"], "o-", color=COLORS["greedy"], label="Greedy, calibration")
    axis.plot(subset["k"], 100 * subset["exact_coverage"], "s--", color=COLORS["milp"], label="Certified MILP, calibration")
    axis.plot(subset["k"], 100 * subset["heldout_greedy"], "o-", color="#7aa0c4", label="Greedy, held-out")
    axis.plot(subset["k"], 100 * subset["heldout_exact"], "s--", color="#c47b2b", label="MILP, held-out")
    axis.set_title(title)
    axis.set_xlabel("Counter budget K")
    axis.set_ylim(0, 100)
axes[0].set_ylabel("Modeled-route coverage (%)")
axes[1].legend(frameon=False, fontsize=8)
figure.suptitle("Certified calibration optimum and held-out coverage", y=1.02)
figure.tight_layout()
show(figure)
"""),
    md(r"""
### What the certificate does and does not say

Every saved unweighted run returned status `optimal`. At \(K = 5\) and \(K = 10\), greedy matches the certified calibration value in both scenarios. At \(K = 20\) the absolute calibration gaps are 0.6 and 0.8 percentage points. At \(K = 30\) they are 0.4 points.

A certified set is not unique. Uniform \(K = 10\) shares 8 of 10 segments between greedy and the MILP solution, with the same 74.0% calibration coverage, but held-out coverage is 72.8% for greedy and 68.8% for the MILP set. Commuter-proxy \(K = 10\) goes the other way: the MILP held-out coverage is 70.4% and greedy is 69.2%. Higher calibration coverage does not imply higher held-out coverage. Solver optimality and generalization are different claims.
"""),
    md(r"""
## 4. Route similarity

Each route is the set of physical-segment identifiers it uses. Exact Jaccard similarity is

\[
J(A, B) = |A \cap B| / |A \cup B|.
\]

All-pairs Jaccard is exact and quadratic. MinHash compresses each set to a signature so that the fraction of equal rows estimates Jaccard (Broder, 1997). Banded locality-sensitive hashing returns pairs that share a band. Those pairs are candidates. The project then computes exact Jaccard and keeps a pair only when the exact value meets the threshold. Recall and precision below are about that candidate list, not about the signature estimate alone.
"""),
    code("""
from cyclesense.minhash import (
    build_lsh_buckets,
    build_signatures,
    query_lsh_pairs,
    retrieval_metrics,
    signature_jaccard,
    verify_candidates,
)
from cyclesense.similarity import jaccard_similarity

left, right = {"a", "b", "c", "d"}, {"b", "c", "d", "e"}
print(f"Exact Jaccard: {jaccard_similarity(left, right):.3f}")
signatures = build_signatures([left, right], num_perm=64, seed=42)
print(f"MinHash estimate, 64 rows: {signature_jaccard(signatures[0], signatures[1]):.3f}")

demo_routes = [
    {"s1", "s2", "s3", "s4"},
    {"s1", "s2", "s3", "s5"},
    {"s1", "s2", "s6"},
    {"t1", "t2", "t3"},
    {"t1", "t2", "t4"},
    {"u1", "u2"},
]
exact_pairs = {
    (left, right): jaccard_similarity(demo_routes[left], demo_routes[right])
    for left in range(len(demo_routes))
    for right in range(left + 1, len(demo_routes))
}
demo_signatures = build_signatures(demo_routes, num_perm=32, seed=7)
buckets = build_lsh_buckets(demo_signatures, bands=16, rows=2)
candidates = query_lsh_pairs(demo_signatures, buckets, bands=16, rows=2)
metrics = retrieval_metrics(candidates, exact_pairs, threshold=0.5, n_routes=len(demo_routes))
verified = verify_candidates(candidates, demo_routes, threshold=0.5)
print(f"Candidates: {metrics['n_candidates']}; true pairs at 0.5: {metrics['n_true_pairs']}")
print(f"Recall: {metrics['recall']:.2f}; precision before verification: {metrics['precision']:.2f}")
print(f"Pairs kept after exact verification: {len(verified)}")
"""),
    md(r"""
## 5. Scalability of the fair comparison

The fair benchmark compares **streaming exact Jaccard**, which never stores the full pair matrix, with **verified LSH** (32 permutations, 16 bands of 2 rows). Memory is peak Python-tracked allocation during the timed call, not resident set size.

The 10,000-route streaming run has one timing repetition. The verified-LSH run at that size has three. This notebook reads the saved timings. It does not launch the benchmark.
"""),
    code("""
timing = pd.DataFrame(load_csv("fair_timing.csv"))
timing = timing[timing.method.isin(["streaming_exact", "verified_lsh"])].copy()
for column in ("n_routes", "median_seconds", "median_peak_mb", "n_timing_repeats", "n_edges"):
    timing[column] = pd.to_numeric(timing[column])
candidates = pd.DataFrame(load_csv("lsh_candidates.csv"))
for column in ("n_routes", "n_candidates", "n_possible_pairs", "verify_s"):
    candidates[column] = pd.to_numeric(candidates[column])

figure, axes = plt.subplots(1, 3, figsize=(10.2, 3.4))
for method, label in (("streaming_exact", "Streaming exact"), ("verified_lsh", "Verified LSH")):
    subset = timing[timing.method == method].sort_values("n_routes")
    axes[0].plot(subset["n_routes"], subset["median_seconds"], "o-", color=COLORS[method], label=label)
    axes[1].plot(subset["n_routes"], subset["median_peak_mb"], "o-", color=COLORS[method], label=label)
axes[2].plot(candidates["n_routes"], candidates["n_candidates"] / 1e6, "o-", color=COLORS["verified_lsh"])
axes[0].set_ylabel("Median seconds")
axes[1].set_ylabel("Peak tracked memory (MB)")
axes[2].set_ylabel("LSH candidates (millions)")
for axis in axes:
    axis.set_xlabel("Routes")
    axis.set_xscale("log")
axes[0].legend(frameon=False, fontsize=8)
figure.suptitle("Saved scalability benchmark", y=1.03)
figure.tight_layout()
show(figure)
display(timing[timing.n_routes.isin([500, 10000])][["n_routes", "method", "n_timing_repeats", "median_seconds", "median_peak_mb", "n_edges"]].sort_values(["n_routes", "method"]))
"""),
    md(r"""
### The tradeoff

At 500 routes, verified LSH takes about 0.07 seconds and streaming exact about 0.21 seconds. Tracked memory is about 3.5 MB for LSH and 1.7 MB for streaming exact. At 10,000 routes the times are about 10 seconds and 85 seconds, and the memory figures are about 327 MB and 115 MB. Verified LSH is faster at every measured size in this table. It does not use less tracked memory. Most of the LSH time at 10,000 routes is exact verification of the candidate pairs: about 6.4 of the recorded stage seconds, against about 1.0 second to query the buckets.

A larger sample is not automatically a better placement sample. The 10,000 routes still reuse the same street network. The study does not treat them as independent observed trips.
"""),
    md(r"""
## 6. Louvain communities

Routes are nodes. An edge exists when exact Jaccard similarity is at least 0.5, and the similarity is the edge weight. Routes below the threshold stay in the graph as isolated nodes. Louvain (Blondel et al., 2008) then partitions that graph. It does not choose the number of communities, and it is not refit on held-out routes.

The community-balanced placer mixes coverage with a penalty for leaving large communities unrepresented. \(\lambda = 0\) is ordinary greedy. The primary balanced setting is \(\lambda = 0.25\), fixed before the held-out comparison.
"""),
    code("""
from cyclesense.communities import detect_communities, graph_statistics, similarity_graph

demo_routes = [
    {"s1", "s2", "s3", "s4"},
    {"s1", "s2", "s3", "s5"},
    {"s1", "s2", "s6"},
    {"t1", "t2", "t3"},
    {"t1", "t2", "t4"},
    {"u1", "u2"},
]
route_ids = [f"r{index}" for index in range(len(demo_routes))]
pairs = [
    (route_ids[left], route_ids[right], jaccard_similarity(demo_routes[left], demo_routes[right]))
    for left in range(len(demo_routes))
    for right in range(left + 1, len(demo_routes))
]
graph = similarity_graph(route_ids, pairs, threshold=0.5)
labels, modularity, sizes = detect_communities(graph, seed=42)
print(graph_statistics(graph))
print(f"Communities: {len(sizes)}; sizes: {sizes}; modularity: {modularity:.3f}")
print(f"Isolates kept as nodes: {sum(1 for node in graph if graph.degree(node) == 0)}")

similarity = load_json("similarity_graph.json")
print("Calibration graphs at threshold 0.5:")
display(pd.DataFrame(similarity["graph_threshold_0_5"])[["scenario", "n_nodes", "n_edges", "n_isolates"]])
print("Louvain on those graphs:")
display(pd.Series(similarity["communities_threshold_0_5"]))
"""),
    code("""
placement = pd.DataFrame(load_csv("community_placement.csv"))
for column in ("lambda", "k", "calibration_coverage", "heldout_coverage", "represented_fraction"):
    placement[column] = pd.to_numeric(placement[column])
focus = placement[placement.k == 10]
display(focus[["scenario", "lambda", "calibration_coverage", "heldout_coverage", "represented_fraction", "matches_m2_greedy"]])

figure, axis = plt.subplots(figsize=(6.4, 3.5))
positions = np.arange(2)
width = 0.35
for offset, lam, color, label in ((-width / 2, 0.0, "#163e72", "Greedy, lambda 0"), (width / 2, 0.25, "#c47b2b", "Balanced, lambda 0.25")):
    subset = focus[focus["lambda"] == lam].set_index("scenario").loc[["uniform", "commuter_proxy"]]
    axis.bar(positions + offset, 100 * subset["heldout_coverage"], width=width, color=color, label=label)
axis.set_xticks(positions, ["Uniform", "Commuter proxy"])
axis.set_ylabel("Held-out coverage (%)")
axis.set_ylim(0, 100)
axis.legend(frameon=False, fontsize=8)
axis.set_title("K = 10, similarity threshold 0.5")
figure.tight_layout()
show(figure)

ablation = pd.DataFrame(load_csv("community_ablation.csv"))
for column in ("louvain", "shuffle_mean", "louvain_minus_mean"):
    ablation[column] = pd.to_numeric(ablation[column])
display(ablation[["scenario", "louvain", "shuffle_mean", "louvain_minus_mean", "outside_central_90"]])

agreement = pd.DataFrame(load_csv("lsh_communities.csv"))
for column in ("graph_edge_recall", "adjusted_rand_index", "n_edges_missed"):
    agreement[column] = pd.to_numeric(agreement[column])
uniform_agreement = agreement[agreement.scenario == "uniform"][["role", "num_perm", "bands", "rows", "graph_edge_recall", "adjusted_rand_index", "n_edges_missed"]]
display(uniform_agreement)
"""),
    md(r"""
### What the communities change

At threshold 0.5 the uniform calibration graph has 500 routes, 511 edges and a large set of isolates. Louvain returns 241 communities, 178 of them singletons. The partition is fragmented. That limits how much a community penalty can move the counters.

\(\lambda = 0\) matches the M2 greedy edge set. At \(K = 10\), \(\lambda = 0.25\) lowers held-out coverage from 72.8% to 72.4% on uniform routes and from 69.2% to 66.8% on commuter-proxy routes. Against 30 shuffles of the community labels, the uniform balanced result sits inside the central 90% of the shuffle distribution. The commuter balanced result is 2.7 points below the shuffle mean, also inside that band. Community balancing does not consistently improve held-out coverage.

LSH changes this picture only when it drops edges. The primary uniform setting, 32 permutations and 16 bands of 2, misses one exact edge and has adjusted Rand index 0.97 against the exact Louvain partition. The aggressive banding misses 458 edges and the adjusted Rand index falls to 0.09. Approximation quality follows the verified edge set. A high-recall banding can preserve the partition; a banding that discards most edges does not.
"""),
    md(r"""
## 7. Robustness

Three uncertainties are separate. The origin–destination distribution can change. The path between the same ends can change when edge costs are perturbed. And a new calibration sample of 500 routes can select a different set of ten segments.

For route choice, each directed edge length is multiplied by \(\exp(0.35 Z)\) and a proposed path is kept when its detour on the original lengths is at most 15% or 30%. The counters in that experiment were already chosen on shortest paths. They are not refit on the detours. The later route-choice-aware placer does refit, on calibration routes only, and is compared with a pooled shortest-path greedy control on fresh seeds.
"""),
    code("""
choice = pd.DataFrame(load_csv("route_choice.csv"))
for column in ("k", "detour_limit", "coverage_mean", "shortest_coverage", "difference_mean"):
    choice[column] = pd.to_numeric(choice[column])
greedy_choice = choice[(choice.method == "greedy") & (choice.k == 10) & (choice.detour_limit == 0.15)]
display(greedy_choice[["scenario", "coverage_mean", "shortest_coverage", "difference_mean", "n_seeds"]])

figure, axis = plt.subplots(figsize=(6.2, 3.4))
positions = np.arange(2)
subset = greedy_choice.set_index("scenario").loc[["uniform", "commuter_proxy"]]
axis.bar(positions - 0.18, 100 * subset["shortest_coverage"], width=0.36, color="#163e72", label="Shortest-path held-out")
axis.bar(positions + 0.18, 100 * subset["coverage_mean"], width=0.36, color="#c47b2b", label="Mean under 15% detours")
axis.set_xticks(positions, ["Uniform", "Commuter proxy"])
axis.set_ylabel("Modeled-route coverage (%)")
axis.set_ylim(0, 100)
axis.legend(frameon=False, fontsize=8)
axis.set_title("Saved K = 10 greedy counters, 20 perturbation seeds")
figure.tight_layout()
show(figure)

robust = pd.DataFrame(load_csv("robust_fresh.csv"))
robust["coverage_mean"] = pd.to_numeric(robust["coverage_mean"])
fresh = robust[(robust.condition == "0.15") & (robust.k == 10)]
display(fresh[["scenario", "method", "coverage_mean", "n_seeds"]])
"""),
    code("""
stability = load_json("stability.json")
print(stability["headline"])
print(f"Draws: {stability['n_replicates']} independent calibration samples of {stability['calibration_routes']} routes.")
print("Selection frequency is not an installation probability:", stability["selection_frequency_is_not_cyclist_demand"])
display(pd.DataFrame(stability["groups"])[["scenario", "n_ever_selected", "n_always", "mean_jaccard", "mean_shared", "calibration_mean", "heldout_mean", "heldout_min", "heldout_max"]])
top = pd.DataFrame(stability["uniform_k10_top"])
top["selection_frequency"] = pd.to_numeric(top["selection_frequency"])
figure, axis = plt.subplots(figsize=(7.2, 3.6))
axis.barh(top["street_name"][::-1], 100 * top["selection_frequency"][::-1], color="#163e72")
axis.set_xlabel("Selection frequency across 30 uniform calibration draws (%)")
axis.set_xlim(0, 100)
axis.set_title("Most often selected segments at K = 10")
figure.tight_layout()
show(figure)
"""),
    md(r"""
### What stays stable

Under 15% detours, the saved uniform greedy set falls from 72.8% shortest-path held-out coverage to a mean of 65.7%. The commuter-proxy set falls from 69.2% to 65.9%. The counters were not chosen for those detours, so the drop is a sensitivity, not a refit.

On fresh seeds, training on the perturbed calibration routes does not beat pooled shortest-path greedy. At the 15% cap and \(K = 10\), mean uniform coverage is 63.0% for the route-choice placer and 64.1% for the pooled control. The commuter-proxy means are 64.2% and 63.2%. There is no consistent held-out gain.

Across 30 new uniform calibration draws, 61 distinct segments appear in some \(K = 10\) greedy set and one segment appears in every draw: Knippelsbro / Børsgade. Mean pairwise Jaccard is 0.27, so typical sets share about four of ten segments. Held-out coverage stays in a narrow band, roughly 66% to 74%, while the chosen streets move. Coverage can look stable when the placement does not. The frequencies are properties of this sampler. They are not probabilities that the city should install a counter.
"""),
    md(r"""
## 8. Published municipal counts

Københavns Kommune publishes Trafiktal screenline counts (CC0). The study uses the frozen snapshot of 21 November 2026, not a fresh download. Inside the pilot rectangle, 26 recurring bicycle counts match a physical segment by name and position. They are a counting programme, not a confirmed list of permanent sensors.

The association below is Spearman rank correlation between published bicycle AADT and three modeled quantities on the calibration routes, with 2,000 permutations. A weak coefficient is a weak coefficient. Dronning Louises Bro, on the west edge of the rectangle, has a high published count and no simulated traversal, because the simulated trips start and end inside the clipped graph.
"""),
    code("""
municipal = pd.DataFrame(load_csv("municipal_coverage.csv"))
for column in ("budget_new", "held_out_existing_coverage", "held_out_existing_plus_new", "calibration_existing_plus_new", "held_out_marginal_gain"):
    municipal[column] = pd.to_numeric(municipal[column])
display(municipal[["scenario", "budget_new", "held_out_existing_coverage", "held_out_existing_plus_new", "held_out_marginal_gain"]])

figure, axes = plt.subplots(1, 2, figsize=(8.0, 3.5), sharey=True)
for axis, scenario, title in zip(axes, ("uniform", "commuter_proxy"), ("Uniform", "Commuter proxy")):
    subset = municipal[municipal.scenario == scenario].sort_values("budget_new")
    existing = 100 * subset["held_out_existing_coverage"].iloc[0]
    added = 100 * subset["held_out_existing_plus_new"]
    axis.bar(["26 sites", "+5 greedy", "+10 greedy"], [existing, *added], color=["#163e72", "#5f8f6a", "#2457a6"])
    axis.set_title(title)
    axis.set_ylim(0, 100)
axes[0].set_ylabel("Held-out modeled-route coverage (%)")
figure.suptitle("Published sites plus greedy segments", y=1.02)
figure.tight_layout()
show(figure)

association = pd.DataFrame(load_csv("aadt_association.csv"))
for column in ("spearman_rho", "permutation_p"):
    association[column] = pd.to_numeric(association[column])
display(association[["scenario", "metric", "n", "spearman_rho", "permutation_p"]].round(3))
"""),
    md(r"""
### Simulated coverage is not a traffic gain

The 26 sites cover 73.6% of uniform held-out routes and 72.4% of commuter-proxy held-out routes. Five greedy segments chosen on the calibration routes raise those figures by 10.0 and 10.4 percentage points. Ten segments raise them by 13.6 and 12.8 points. These are additional simulated routes, not additional bicycles in the municipal series.

Rank agreement with AADT is weak. Uniform traversal has Spearman 0.26 (permutation p 0.21). Unique coverage and Shapley attribution do not agree more closely. The counts do not validate the route generator as a ranking of Copenhagen bicycle traffic.
"""),
    md(r"""
## 9. Infrastructure filters and coverage attribution

Two further checks use the same coverage definition. One restricts the eligible segments to OpenStreetMap tags that record a cycling facility. An absent cycleway tag stays unknown; it is not treated as proof that a facility is missing. The other attributes the coverage of the 26 municipal sites. Leave-one-out contribution is the coverage lost when one site is removed. For this objective it equals the share of routes that touch that site alone. Shapley attribution gives every municipal site on a covered route an equal share of that route, so the 26 values sum to the coverage of the full set.

The Shapley cell uses the tested function on four routes. The Copenhagen figures are the saved calibration results. Neither result is a recommendation to remove a counting site. A counting programme can serve purposes this coverage game does not represent.
"""),
    code("""
from cyclesense.municipal_redundancy import attribute_sites

shared = {"r1": {"m1"}, "r2": {"m1", "m2"}, "r3": {"m2", "m3"}, "r4": {"m3"}}
attributed = attribute_sites(shared, ["m1", "m2", "m3"])
print(f"Coverage of the three sites: {attributed['coverage']:.3f}")
print(f"Sum of Shapley values: {attributed['shapley_total']:.3f}")
for row in attributed["sites"]:
    print(
        f"{row['physical_edge_id']}: traversal {row['traversal_fraction']:.2f}, "
        f"unique {row['unique_fraction']:.2f}, Shapley {row['shapley']:.2f}"
    )

policies = pd.DataFrame(load_csv("infrastructure_policies.csv"))
policies["n_permitted"] = policies["n_permitted"].astype(int)
display(policies)

infra = pd.DataFrame(load_csv("infrastructure_coverage.csv"))
infra = infra[(infra.k == "10") & (infra.status == "feasible")].copy()
infra["heldout_coverage"] = infra["heldout_coverage"].astype(float)
infra["heldout_difference_pp"] = infra["heldout_difference_pp"].astype(float)
display(infra[["scenario", "policy", "n_permitted", "heldout_coverage", "heldout_difference_pp", "n_shared_with_unrestricted"]])

sites = pd.DataFrame(load_csv("redundancy_sites.csv"))
sites["leave_one_out_pp"] = sites["leave_one_out_pp"].astype(float)
sites["shapley_pp"] = sites["shapley_pp"].astype(float)
sites["traversal_fraction"] = sites["traversal_fraction"].astype(float)
uniform_sites = sites[sites.scenario == "uniform"].sort_values("leave_one_out_pp", ascending=False)
print("Largest unique contributions, uniform calibration:")
display(uniform_sites[["street", "description", "traversal_fraction", "leave_one_out_pp", "shapley_pp"]].head(5))
print("Zero unique contribution, uniform calibration:")
display(uniform_sites.loc[uniform_sites.leave_one_out_pp == 0, ["street", "description", "traversal_fraction", "shapley_pp", "bike_aadt"]])
"""),
    md(r"""
### Filters and shared coverage

The explicit-facility policy keeps 381 of 1,047 eligible segments. At \(K = 10\) it lowers held-out coverage by 4.4 points on uniform routes and 6.4 points on commuter-proxy routes. The dedicated-cycleway policy keeps 107 segments and lowers held-out coverage by 42.8 and 36.4 points. A mapped facility is not, by itself, a better counter site. The tag filter removes corridors the unrestricted greedy uses.

Knippelsbro has the largest unique contribution, 7.4 points on the uniform calibration routes, and a larger Shapley value, 12.9 points, because many of its routes also pass another counting segment. Kristen Bernikows Gade is the contrasting case: high traversal, little unique coverage, and a Shapley value that allocates the shared routes. Dronning Louises Bro contributes nothing in the simulation and has a published AADT of 33,000. The zero is a boundary of the route sample.
"""),
    md(r"""
## 10. Synthesis

**Optimization.** Greedy coverage dominates random, geographic K-means, and route-frequency placement on the held-out routes. On the calibration objective, HiGHS certifies that greedy is optimal at \(K = 5\) and \(K = 10\), and within one percentage point at \(K = 20\) and \(K = 30\). Different optimal sets can tie on calibration coverage and differ on held-out coverage. The \(1 - 1/e\) guarantee and the solver certificate describe \(F(S)\). They do not describe cyclists.

**Computational methods.** Verified LSH is faster than streaming exact Jaccard from 500 to 10,000 routes and uses more Python-tracked memory. Exact verification of candidates, not the hash query, dominates the large runs. Louvain on the threshold-0.5 graph is fragmented, and community-balanced placement does not consistently raise held-out coverage. When LSH retains the similarity edges, the Louvain partition stays close to the exact partition. When it discards them, adjusted Rand index collapses.

**Generalization.** Shortest-path counters lose modeled coverage under 15% detours. Training on those detours does not reliably beat a pooled shortest-path control. New calibration samples keep held-out coverage in a narrow band while replacing most of the ten segments. Knippelsbro / Børsgade is the only uniform \(K = 10\) segment selected in all 30 draws.

**Interpretation.** The 26 name-verified municipal sites already cover about three quarters of the held-out simulated routes. Five further greedy segments add about ten points of simulated coverage. Rank agreement with published AADT is weak, and the pilot boundary removes a busy bridge from the simulated trips. Infrastructure tags can shrink the candidate list sharply. Shapley values explain shared modeled coverage; they do not rank the city's need for a counter.

The accurate statement is therefore narrow. On this mapped network and these simulated routes, greedy maximum coverage is a strong and often certified optimizer, MinHash/LSH is a predictable computational tradeoff, and the placement is much less stable than its coverage number. None of those results is a map of where Copenhagen should install counters.

### Reproduce

```bash
python -m pip install -e '.[analysis,dev]'
python scripts/export_notebook_assets.py   # only if notebooks/assets is missing and the study outputs exist
jupyter lab notebooks/analysis.ipynb
```

`python scripts/validate_notebook.py` executes this notebook from the first cell to the last. Provenance for every exported table is in `notebooks/assets/provenance.json`.
"""),
]


def main() -> None:
    notebook = new_notebook(
        cells=CELLS,
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
    )
    path = ROOT / "notebooks" / "analysis.ipynb"
    nbformat.write(notebook, path)
    print(f"Wrote {path.relative_to(ROOT)} with {len(CELLS)} cells")


if __name__ == "__main__":
    main()
