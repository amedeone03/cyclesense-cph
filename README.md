# CycleSense CPH

**Robust and diversity-aware bicycle-counter placement in Copenhagen**  
DTU 02807 · Computational Tools for Data Science · 2026 final project

## Research goal

Given a budget of **K counters**, where should they be installed on a Copenhagen cycling network to balance:

1. **Modeled-route coverage** — proportion of plausible cycling routes intersecting at least one counter;
2. **Corridor diversity** — representation across distinct communities of overlapping routes;
3. **Robustness** — stability when origin–destination and route-choice assumptions change.

**Main research question:** Can route-similarity communities improve the coverage/diversity/robustness trade-off relative to geographical placement and pure maximum-coverage methods?

The project is a **simulation-based methods study**. OpenStreetMap geometry is real infrastructure data, but modeled journeys are **not observed cyclist trips**. We must not claim actual capture rates, forecast demand, or produce municipality-approved physical installation locations.

## Proposed methodology

1. Extract and audit a versioned Copenhagen bicycle-routing graph using OpenStreetMap/OSMnx.
2. Generate several reproducible origin–destination and route-choice scenarios.
3. Represent routes as sets of physical/eligible street-edge IDs.
4. Find high-overlap route pairs with **MinHash + LSH**; measure recall versus exact Jaccard and computation cost.
5. Build a route-overlap graph and apply **Louvain** community detection; evaluate stability.
6. Place counters with geographical K-Means, route-frequency, plain greedy maximum coverage, and community-aware greedy.
7. Evaluate on **held-out synthetic routes** and different assumptions; compare coverage, per-community representation, robustness, time, and RAM.

**Current implementation state:** repository scaffold and a tested, exact weighted route-coverage / greedy baseline. The Copenhagen graph, LSH and Louvain analyses, and final experiments are **not implemented yet**.

## Project structure

```text
cyclesense-cph/
├── .cursor/rules/project.mdc     # Optional Cursor project guidance
├── .github/workflows/tests.yml  # CI for pure-Python baseline
├── configs/pilot.yaml           # Initial experimental configuration
├── docs/
│   ├── research_plan.md         # Hypotheses and evaluation protocol
│   ├── data_sources.md          # Provenance / limitations
│   └── research_proposal.pdf    # Updated working proposal
├── notebooks/analysis.ipynb     # Reporting notebook starter
├── scripts/download_graph.py    # Download a network when online
├── src/cyclesense/
│   ├── coverage.py              # Exact coverage + greedy baseline
│   └── similarity.py            # Exact Jaccard baseline
├── tests/                       # Small synthetic tests
├── pyproject.toml
└── .gitignore
```

## Get started (Cursor / macOS)

From the project folder, open the **Terminal** in Cursor and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
pytest -q
python -m cyclesense
```

For network analysis and interactive notebooks, additionally install:

```bash
pip install -e '.[analysis]'
```

The first network download requires Internet access and OpenStreetMap Overpass availability. Start with a **small study area** to test routing and graph quality before downloading a citywide network:

```bash
python scripts/download_graph.py --place 'Copenhagen, Denmark' --output data/processed/copenhagen_bike.graphml
```

That command is illustrative and may be computationally heavy; smaller valid place polygons are preferred for the feasibility pilot. Document the chosen boundary and graph snapshot.

## Milestones

- [ ] **M0**: GitHub repository, Cursor workspace and passing local tests
- [ ] **M1**: Copenhagen subgraph extraction, topology audit, candidate sites, test routes
- [ ] **M2**: Random/K-Means/route-frequency/greedy baselines and held-out evaluation
- [ ] **M3**: MinHash–LSH similarity graph and Louvain route communities
- [ ] **M4**: Community-aware placement, scenario-shift robustness, scalability plots
- [ ] **M5**: DTU notebook and concise report, limitations and reproducible runs

## Data management

- `data/` and `outputs/` are ignored by Git. Never commit raw traces, large map extracts, or private datasets.
- Save extraction dates, OSM attribution, parameters and random seeds.
- Use distinct training/calibration and evaluation route samples.
- Do not report synthetic demand assumptions as observed Copenhagen cycling patterns.

See `docs/research_plan.md` for the intended experiments. This scaffold is a starting point, **not an implemented research result**.
