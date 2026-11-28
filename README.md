# CycleSense CPH

**Simulation-based bicycle-counter placement in central Copenhagen**  
**DTU 02807 — Computational Tools for Data Science · Autumn 2026**

CycleSense CPH studies where a limited number of bicycle counters could be placed on a mapped street network to cover as many **simulated cycling routes** as possible. It combines graph analysis, MinHash/Locality-Sensitive Hashing (LSH), Louvain community detection, greedy optimization, exact mixed-integer programming, and robustness analysis.

> **Project status:** The computational implementation, experiments, and reproducible analysis notebook are complete. **The academic report is a team draft**, not a final hand-in: group names, individual contributions, and the final character count still require review.
>
> **Scientific scope:** Street geometry comes from OpenStreetMap; the routes and coverage scores are simulated. The project does **not** estimate the percentage of real cyclists captured, validate actual installation feasibility, or recommend removing municipal counting locations.

## Start here — guide for teammates

| If you want to… | Start with |
| --- | --- |
| Understand the entire study and its main findings | **This README**, then [the analysis notebook](notebooks/analysis.ipynb) |
| Write or revise the academic report | [Report source](report/report.tex), [draft PDF](report/report.pdf), and [the experiment documentation](docs/) |
| Check the numbers and generate core figures | [Notebook](notebooks/analysis.ipynb) and [validated notebook assets](notebooks/assets/) |
| Understand the research design | [Research plan](docs/research_plan.md), [M1 assumptions](docs/m1_assumptions.md), and [reproducibility notes](docs/reproducibility.md) |
| Run code or tests | [Installation and commands](#installation-and-quick-start) |
| Explore counter locations interactively | [Interactive planner](#interactive-planner-optional-local-artifacts) |

**Suggested reading order for report writers:** Introduction and conclusions in the notebook → baseline/optimization results → MinHash–LSH/Louvain results → robustness → municipal comparison → the report draft. The detailed `docs/` files support claims that cannot fit in the short report.

## Research question and approach

**Given a budget of `K` eligible physical street segments, which locations maximize modeled-route coverage, and how reliable are those locations under computational and behavioral uncertainty?**

We investigate four connected questions:

1. **Optimization:** How well does greedy maximum coverage perform compared with other placement rules and a certified mathematical optimum?
2. **Computational methods:** Can verified MinHash–LSH approximate exact route-overlap computation while preserving meaningful Louvain communities and counter placements?
3. **Reliability:** How do alternative simulated routes, origin–destination assumptions, and calibration samples change coverage and chosen locations?
4. **External interpretation:** How do the model's proposed locations and coverage relate to Copenhagen's published bicycle counting sites?

### Conceptual pipeline

```text
Versioned OSM extract ──→ Directed bicycle-routing graph
                                 │
                                 ▼
                   Simulated origin–destination pairs
                                 │
                                 ▼
                  Routes as physical street-segment sets
                       │                     │
                       ▼                     ▼
            Jaccard / MinHash–LSH     Counter candidates
                       │                     │
                       ▼                     ▼
               Route-overlap graph    Greedy / MILP placement
                       │                     │
                       ▼                     │
                Louvain communities ──→ Community-weighted variant
                                             │
                                             ▼
                                 Independent held-out evaluation
                                             │
                         ┌───────────────────┴────────────────────┐
                         ▼                                        ▼
                 Robustness / stability                    Municipal data check
```

A route is **covered** if it crosses at least one selected physical segment. It counts only once even if it crosses several proposed counters. For nonnegative route weights, the optimization objective is

\[
F(S)=\sum_{r\in R} w_r\,\mathbf{1}\{E(r)\cap S\neq\varnothing\},
\qquad S\subseteq C,\quad |S|\leq K.
\]

Here, `R` is a set of simulated routes, `C` is the eligible candidate set, and `E(r)` is the set of physical segments traversed by route `r`. The project's standard greedy selector maximizes successive marginal coverage gains.

### Data and experimental setup

| Item | Validated pilot setup |
| --- | --- |
| Study area | An approximately 2 × 2 km rectangle around Indre By, central Copenhagen |
| Network source | OpenStreetMap via a BBBike Copenhagen PBF extract, recorded 14 November 2026 |
| Routing graph | 1,157 nodes, 2,732 directed edges |
| Physical street segments | 1,698 (opposite directions mapped to shared physical IDs) |
| Eligible counting segments | 1,047 |
| Simulated OD scenarios | Uniform sampling and a commuter-proxy sampler |
| Canonical routes | Per scenario: 500 calibration routes + 250 held-out routes |
| Main counter budgets | `K = 5, 10, 20, 30` |
| Municipal comparison | 26 name-verified counting locations from Copenhagen's published Trafiktal data |

Only the **calibration routes** are used to choose counters and route communities. Held-out routes are used to evaluate finished selections. The commuter-proxy scenario is an assumption, **not an observed commuting-demand model**.

## Methods in plain language

| Method | What it does | Why it matters |
| --- | --- | --- |
| **Maximum-coverage greedy** | Repeatedly selects the physical segment that covers the most additional weighted simulated routes | Strong, interpretable placement baseline; the fixed nonnegative objective is monotone submodular with a `1-1/e` approximation guarantee |
| **MILP / HiGHS** | Solves the same coverage problem using binary counter and route-coverage variables | Measures greedy's calibration optimality gap with solver certification |
| **Exact Jaccard** | Measures route similarity from overlap between physical-segment sets | Ground truth for evaluating approximate similarity retrieval |
| **MinHash + verified LSH** | Proposes potentially similar route pairs using signatures and buckets, then verifies them using exact Jaccard | Reduces pairwise search work without treating hash collisions as confirmed similarities |
| **Louvain** | Detects communities in a weighted route-overlap graph | Tests whether representing route groups improves placement beyond total coverage |
| **Community-balanced greedy** | Reweights calibration routes using Louvain communities | Explores a coverage/diversity trade-off |
| **Route-choice and sampling sensitivity** | Perturbs simulated path costs and resamples calibration routes | Tests whether performance and locations survive changes in assumptions |
| **Infrastructure filters** | Restricts eligible segments using saved OSM cycling-facility tags | Measures the coverage cost of hypothetical mapped-infrastructure policies |
| **Coverage attribution / Shapley** | Allocates unique and shared modeled coverage among municipal counting sites | Separates redundancy of modeled routes from real-world usefulness |

**A crucial distinction:** MILP certifies optimality only for a stated **calibration objective**, not for observed Copenhagen traffic or a real installation decision.

## Main findings

These are selected results from the validated experiments; the notebook and linked documentation contain the complete comparisons. Percentages below measure **simulated-route coverage**, unless explicitly labeled otherwise.

| Finding | Evidence | Interpretation |
| --- | --- | --- |
| **Greedy is a strong baseline** | At uniform `K=10`, held-out greedy coverage is **72.8%**, versus **40.4%** for the route-frequency baseline | Choosing marginally new routes matters more than selecting the busiest-looking segments |
| **Greedy is nearly optimal on calibration routes** | Unweighted greedy equals the certified MILP optimum at `K=5` and `K=10` in both scenarios; larger-budget gaps are below 1 percentage point | Optimization error is small for the defined maximum-coverage objective |
| **Calibration ties do not imply identical generalization** | At uniform `K=10`, greedy and an MILP solution both attain **74.0%** calibration coverage, but **72.8%** versus **68.8%** held-out coverage | Different optimal counter sets can generalize differently |
| **Verified LSH speeds up the large route-similarity pipeline** | At 10,000 simulated routes: approximately **10.28 s** for verified LSH versus **85.29 s** for streaming exact Jaccard (~8.3×) | LSH reduces runtime, but streaming exact used **less Python-tracked memory**; the largest exact timing was one run |
| **Community balancing is not a consistent gain** | At `K=10`, uniform held-out coverage is **72.4%** for the `λ=0.25` balanced rule versus **72.8%** for greedy; commuter is **66.8%** versus **69.2%** | Louvain is useful for studying route structure, but reweighting does not reliably improve coverage |
| **Alternative simulated paths reduce coverage** | Uniform greedy `K=10` changes from **72.8%** on original held-out paths to about **65.7%** under the 15% detour experiment | A good shortest-path placement is sensitive to route-choice assumptions |
| **Selected locations are unstable** | Across 30 new uniform calibration draws at `K=10`, only **Knippelsbro / Børsgade** appears in every set; mean pairwise set Jaccard is **0.27** | Similar coverage can be delivered by substantially different streets |
| **Municipal locations provide a useful modeled reference** | The 26 matched sites cover **73.6%** of uniform held-out simulated routes; 5 greedy additions reach **83.6%**, and 10 reach **87.2%** | The extra percentages are modeled gains, **not observed cyclist capture** |
| **External count agreement is weak** | The simulated traversal ranking versus published bicycle AADT has Spearman `ρ≈0.26` in the uniform scenario | The simulation is not an empirically validated traffic-demand model |
| **Stricter infrastructure filters can be costly** | At uniform `K=10`, held-out coverage falls from **72.8%** unrestricted to **68.4%** with explicitly mapped facilities, or **30.0%** for dedicated-cycleway-only candidates | OSM tags are useful for sensitivity tests, not proof of installation feasibility |

**Overall conclusion:** Greedy already performs very well on the specified simulated coverage objective. The larger limitations are **how routes are simulated, how candidate streets are defined, how unstable equivalent placements can be, and how weakly simulated traversals reflect observed bicycle counts**.

### Where to find the evidence

| Topic | Main technical record |
| --- | --- |
| Network creation and scenario assumptions | [`docs/m1_assumptions.md`](docs/m1_assumptions.md) |
| Baselines and coverage evaluation | [`docs/m2_baselines.md`](docs/m2_baselines.md) |
| Jaccard, MinHash–LSH and Louvain | [`docs/m3_communities.md`](docs/m3_communities.md) |
| Community-weighted placement and ablations | [`docs/m4_optimization.md`](docs/m4_optimization.md) |
| End-to-end approximate vs exact pipeline | [`docs/integrated_study.md`](docs/integrated_study.md) |
| 500–10,000-route performance and memory | [`docs/scalability_study.md`](docs/scalability_study.md) |
| Route-choice perturbation and route-aware training | [`docs/route_choice_robustness.md`](docs/route_choice_robustness.md), [`docs/robust_placement.md`](docs/robust_placement.md) |
| Certified MILP vs greedy | [`docs/exact_optimization.md`](docs/exact_optimization.md) |
| Stability over 30 independent calibration draws | [`docs/placement_stability.md`](docs/placement_stability.md) |
| OSM facility-tag restrictions | [`docs/infrastructure_constraints.md`](docs/infrastructure_constraints.md) |
| Published traffic counts and complementary sites | [`docs/standout_extension.md`](docs/standout_extension.md) |
| Unique/shared coverage and Shapley attribution | [`docs/municipal_redundancy.md`](docs/municipal_redundancy.md) |
| Interactive planning interface | [`docs/planner.md`](docs/planner.md) |

## Installation and quick start

Requirements: **Python 3.11 or newer** and Git. Run these commands from the repository root.

```bash
python3 -m venv .venv
source .venv/bin/activate          # macOS / Linux
python -m pip install --upgrade pip
python -m pip install -e '.[analysis,dev]'
```

### Run the final notebook — recommended for teammates

```bash
jupyter lab notebooks/analysis.ipynb
```

In Jupyter, choose **Run All Cells**. The notebook combines small live demonstrations of the tested project functions with **21 portable validated result assets** under `notebooks/assets/`. It does **not** regenerate the full Copenhagen experiments or access the network. The optional street-map cell skips gracefully if the large local graph is absent.

Or validate notebook execution from the terminal:

```bash
python scripts/validate_notebook.py
```

The notebook and its asset bundle were tested in an extracted, clean Python 3.14 environment without the large local experiment outputs. Python 3.11 has been used for the repository's unit-test CI, **not for a full notebook execution in CI**.

### Run automated checks

```bash
python -m pytest -q
ruff check src scripts tests
python scripts/reproduce.py --mode smoke
```

The last reported local audit passed **193 tests**. Smoke mode checks the environment and does not download data or rerun experiments. The GitHub Actions workflow runs tests and Ruff with Python 3.11, using the `dev` dependencies.

**Do not run `scripts/validate_results.py` on a fresh clone expecting it to succeed:** it validates the complete **gitignored study-output tree**, which is not bundled. It is intended for a machine with saved experiment artifacts.

## Interactive planner (optional local artifacts)

The [what-if planner](docs/planner.md) can switch between saved methods, budgets, scenarios, municipal additions and selection-frequency heatmaps. It is a standalone HTML viewer over **previously computed results**, not a live optimizer.

On a checkout where the local `data/` and `outputs/` study results already exist:

```bash
python scripts/map_planner.py
python -m http.server 8765 --bind 127.0.0.1
```

Open `http://127.0.0.1:8765/outputs/planner/cyclesense_planner.html`.

The planner **cannot be regenerated from a clean Git clone alone**: its detailed placements and GraphML live under gitignored paths. The academic notebook and report are the portable alternatives. The planner makes no public map-tile requests.

## Repository layout

```text
cyclesense-cph/
├── src/cyclesense/          Algorithms, graph utilities, evaluation and plots
├── scripts/                 Experiment runners, validation and asset export
├── notebooks/
│   ├── analysis.ipynb       Final executable research notebook
│   └── assets/              Small, validated result tables + provenance
├── report/
│   ├── report.tex           Editable academic report DRAFT
│   ├── report.pdf           Compiled draft PDF
│   └── figures/             Report figures and source records
├── docs/                    Detailed study protocols, outcomes and limitations
├── configs/                 Pilot settings, seeds and data integrity manifest
├── snapshots/               Frozen municipal Trafiktal source CSV (CC0)
├── tests/                   Unit and integration tests
├── .github/workflows/       CI checks
├── pyproject.toml           Installation requirements and tooling
├── data/                    Processed graph and local inputs (gitignored)
├── outputs/                 Large experiment outputs and interactive maps (gitignored)
└── cache/                   Historical OSM PBF and cache (gitignored)
```

## Reproducibility and data provenance

| Source or artifact | Availability | Important caveat |
| --- | --- | --- |
| **Original OSM PBF** | Local `cache/osm/Copenhagen.osm.pbf`; not tracked | The [BBBike Copenhagen URL](https://download.bbbike.org/osm/bbbike/Copenhagen/Copenhagen.osm.pbf) serves a **mutable** extract, not the historical file used here |
| **Processed routing graph and simulated routes** | Local `data/processed/m1/`; not tracked | Rebuilding the exact published graph requires the recorded PBF bytes or saved GraphML |
| **Municipal Trafiktal** | Tracked [21 November 2026 snapshot](snapshots/trafiktal-2026-11-21.csv) | Published recurring counting locations, not confirmed installed permanent sensors; CC0 data |
| **Core notebook result tables** | Tracked `notebooks/assets/` | Exported from saved experiments; provenance and source hashes in [`provenance.json`](notebooks/assets/provenance.json) |
| **Full figures and experiment tables** | Local `outputs/`; not tracked | The notebook and report contain the selected portable evidence |
| **Report and source** | Tracked `report/` | Draft pending group review |

The project records the OSM and Trafiktal hashes, versions and workflow steps in [`configs/reproducibility.yaml`](configs/reproducibility.yaml). Full reproduction instructions are in [`docs/reproducibility.md`](docs/reproducibility.md).

To regenerate a **portable notebook asset bundle** from complete saved study outputs, use:

```bash
python scripts/export_notebook_assets.py
python scripts/validate_notebook.py
```

Do not regenerate the assets merely because the full `data/` and `outputs/` trees are missing. Re-running the full pipeline from a freshly downloaded OSM extract can change the underlying network and no longer reproduce the published results. Full reproduction from scratch with the original historical OSM snapshot was not independently certified.

### Important limitations

- Simulated origin–destination pairs and shortest paths are **not observed cycling trips**. The route-choice detours are also simulated.
- The study rectangle clips routes and misses activity outside its boundary. In particular, Dronning Louises Bro has published high bicycle counts but zero modeled traversal in this pilot.
- Selection stability and Shapley values describe the model's coverage game; they are not estimates of traffic volume or reasons to install/remove physical counting equipment.
- OSM tags do not establish ownership, clearance, power supply, permissions or engineering suitability.
- The municipal AADT observations cover different locations/years and should never be substituted for simulated route coverage.
- Benchmark times and tracked memory are measurements on the reported machine, not universal hardware performance.

## Report handover — tasks for the group

The academic report is a **draft for collaborative editing**: [`report/report.tex`](report/report.tex) and [`report/report.pdf`](report/report.pdf).

**The computational work is complete; the group owns the final report revision and submission.** Before uploading, please:

1. **Insert all group members' full names** in the LaTeX author field and replace the individual-contributions placeholder with accurate descriptions.
2. **Review the argument and figures.** The notebook is the main reference for the validated numerical results; the detailed method notes are in `docs/`. Avoid turning the report into a chronology of experimental milestones.
3. **Recompile and recount the *rendered* PDF.** The 2026 brief specifies 11,000 non-whitespace characters for four members or 12,500 for five. In the last audit, the draft's **rendered** report plus contribution appendix counted approximately **10,937 characters** against the conservative 11,000 threshold. That leaves only **63 characters before adding names/contributions**. Shorten wording where necessary. `python scripts/count_report.py` is a **LaTeX-source proxy that undercounts rendered figure labels**; do not rely on it alone.
4. **Inspect every PDF page** for readable legends, mathematical notation, citations and uncut tables. The current report has six pages and five figures.
5. **Build the final submission archive** and check that it contains the final PDF, notebook, assets, source code and required instructions. The previous `submission/` ZIP was a draft, not a final hand-in.
6. **Submit through DTU Learn**, according to the official project brief, **by 4 December 2026 at 23:59**. A GitHub commit by itself is not a DTU Learn submission.

**Report-writing recommendation:** Lead with the certified near-optimality of greedy; explain why LSH/Louvain and robustness experiments remain computationally interesting; close with the limited external validity of simulated-route placement. Keep negative results visible.

## Data attribution and academic references

- **[OpenStreetMap](https://www.openstreetmap.org/copyright)** contributors — mapped streets and network tags (ODbL), obtained via the **[BBBike](https://download.bbbike.org/osm/bbbike/Copenhagen/)** extract.
- **[Københavns Kommune — Trafiktal](https://www.opendata.dk/city-of-copenhagen/trafiktal)** — published traffic counts (frozen project snapshot, CC0).
- The report and notebook cite the relevant methodological literature for maximum coverage, MinHash/LSH, Louvain, and related evaluation tools.

For the reproducibility protocol, assumptions, and full experimental records, use [`docs/reproducibility.md`](docs/reproducibility.md) and the [research notebook](notebooks/analysis.ipynb).
