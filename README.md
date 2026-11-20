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

**Current implementation state:** exact weighted route-coverage / greedy baseline, plus an M1 pilot that downloads a small central-Copenhagen bike graph, defines physical counter segments, and generates uniform and commuter-proxy routes. LSH, Louvain, and placement experiments are **not implemented yet**. Modeled routes are not observed trips.

## Project structure

```text
cyclesense-cph/
├── .cursor/rules/project.mdc     # Optional Cursor project guidance
├── .github/workflows/tests.yml  # CI for pure-Python baseline
├── configs/pilot.yaml           # Initial experimental configuration
├── docs/
│   ├── research_plan.md         # Hypotheses and evaluation protocol
│   ├── data_sources.md          # Provenance / limitations
│   ├── m1_assumptions.md        # M1 boundary, candidates, route rules
│   └── research_proposal.pdf    # Updated working proposal
├── notebooks/analysis.ipynb     # Reporting notebook starter
├── scripts/download_graph.py    # Optional Overpass download; skips a saved M1 graph
├── scripts/run_m1.py            # Pilot graph, candidates, and routes
├── scripts/map_m1.py            # Interactive map of the saved M1 network
├── src/cyclesense/
│   ├── coverage.py              # Exact coverage + greedy baseline
│   ├── similarity.py            # Exact Jaccard baseline
│   ├── edges.py                 # Physical segment ids and eligibility
│   ├── network.py               # OSMnx extract, audit, candidates
│   ├── artifacts.py             # Canonical M1 file locations
│   ├── interactive.py           # Folium map of candidates and route samples
│   ├── sampling.py              # Uniform and commuter-proxy OD draws
│   └── routes.py                # Shortest paths and calibration split
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

The M1 pilot uses the rectangle in `configs/pilot.yaml`. The first run downloads the BBBike Copenhagen OpenStreetMap extract if it is not already in `cache/osm/`, then OSMnx builds and clips the bike graph. That needs the `analysis` extra, including `osmium`:

```bash
python scripts/run_m1.py
```

The canonical M1 graphs, written by `scripts/run_m1.py`, are:

- `data/processed/m1/copenhagen_bike_full.graphml`
- `data/processed/m1/copenhagen_bike_routing_wgs84.graphml`
- `data/processed/m1/copenhagen_bike_routing_projected.graphml`

There is no `data/processed/copenhagen_bike.graphml`. `scripts/download_graph.py --place ... --output ...` only saves a GraphML after an Overpass download returns. That download did not return, so the requested path was never created. When the validated M1 files above already exist, the same command prints those paths and does not download or copy the graph. Assumptions and the extraction record are in `docs/m1_assumptions.md`.

Regenerate the interactive map from the saved network and routes:

```bash
python scripts/map_m1.py
python scripts/map_m1.py --no-basemap
python scripts/map_m1.py --serve
```

`python scripts/map_m1.py` writes `outputs/m1/m1_network.html` and draws streets, street names, buildings, parks, and water from `cache/osm/Copenhagen.osm.pbf` inside the Indre By rectangle. The bicycle network, eligible counter segments, and six simulated routes are layers on top. Click a blue segment to read its physical-edge ID. Uncheck **Geographical basemap** in that same page for the tile-free network view.

`python scripts/map_m1.py --no-basemap` writes the tile-free view only and does not read the PBF.

`python scripts/map_m1.py --serve` rebuilds the default map and opens it at <http://127.0.0.1:8765/m1_network.html>. The page does not request `tile.openstreetmap.org`. Geometry is attributed to OpenStreetMap contributors under the ODbL.

## Milestones

- [ ] **M0**: GitHub repository, Cursor workspace and passing local tests
- [x] **M1**: Copenhagen subgraph extraction, topology audit, candidate sites, test routes
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
