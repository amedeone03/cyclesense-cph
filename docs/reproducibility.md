# Reproducibility

CycleSense CPH compares counter placements on simulated routes over an OpenStreetMap bicycle graph. The geometry is observed infrastructure. The routes, coverages, and communities are simulated. Municipal bicycle counts are published observations at recurring count sites. They are not a permanent-sensor inventory, and they are not the same quantity as modeled-route coverage.

## Environment

Supported Python is 3.11 or newer (`requires-python` in `pyproject.toml`). The project is not pinned to 3.11 only.

GitHub Actions installs the `dev` extra on Python 3.11 and runs `ruff check src scripts tests` and `pytest -q`. That job does not download OpenStreetMap data and does not run the 10,000-route study.

On this development machine `python3.11` is not installed, so Python 3.11 was not executed locally. GitHub Actions is the 3.11 run. A separate temporary environment, using the available Python 3.14.4, installed `.[analysis,dev]`, passed the 135 unit tests, and passed `python scripts/reproduce.py --mode smoke`. The working `.venv` was left in place.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[analysis,dev]'
```

The `analysis` extra is required for OSMnx, the municipal certificate bundle (`certifi`), maps, and the experiment scripts. The `dev` extra adds pytest, Ruff, and PyYAML. Scripts import the installed package. They also insert `src/` on `sys.path` when launched as files, so a developer checkout can run them after the editable install. There is no dependency on Cursor and no absolute path is required.

macOS certificate failures usually come from a python.org install that has not run `Install Certificates.command`. Install the `analysis` extra, which includes `certifi`. The municipal downloader uses `ssl.create_default_context` plus that bundle. Certificate verification stays enabled.

## What is stored, and what is not

| Kind | Where | In Git |
| --- | --- | --- |
| Frozen municipal CSV (CC0, 21 Nov 2026) | `snapshots/trafiktal-2026-11-21.csv` | yes |
| OSM PBF used for the published graph | `cache/osm/Copenhagen.osm.pbf` | no (about 50 MB) |
| Processed graph, candidates, routes | `data/processed/m1/` | no |
| Figures, tables, maps | `outputs/` | no |
| Machine report | `outputs/reproducibility/environment.json` | no |

The municipal snapshot hash is `d46f3214ee2a4db9c8ff9a9708934fe6c6fbfb8b0f753aa0dd9ba58981a341ad`. The OSM PBF hash, verified against the local file, is `3661ec97aa60999a911d0824fca03e525f7ec076bbb5c0339f905f0971fa5262`. Both are recorded in `configs/reproducibility.yaml`. Seeds, the study rectangle, and budgets stay in `configs/pilot.yaml` and are not copied into the manifest.

## OpenStreetMap

- URL: https://download.bbbike.org/osm/bbbike/Copenhagen/Copenhagen.osm.pbf
- HTTP `Last-Modified` of the file used here: 2026-11-14T16:51:56Z
- Format: OSM PBF, licence ODbL. Attribute OpenStreetMap contributors.
- Boundary: `configs/pilot.yaml` rectangle, west 12.563, south 55.6705, east 12.5965, north 55.688 (WGS84).
- Processing: OSMnx bike preset, then `truncate_graph_polygon` with `truncate_by_edge` false. The pipeline version is `m1.2`.

BBBike does not publish that URL as a dated historical snapshot. Downloading it again can produce a different file. A different hash is a new extract, not a reproduction of the published graph. If the local PBF is missing but `data/processed/m1/` is present and passes the M1 checks, later experiments can continue from the saved graph. Rebuilding the graph still needs the recorded PBF bytes.

`scripts/run_m1.py --force-download` fetches the current PBF again and rebuilds the graph. `scripts/download_graph.py` is an Overpass path. It is not how the pilot graph was built.

## Municipal counts

The frozen CSV is the file used for the published comparison. When `data/external/trafiktal.csv` is missing, `scripts/run_external_validation.py` copies the snapshot. When the working file's hash matches, it is used. When the hash differs, the script stops and does not overwrite the file. `--refresh-counts` refuses to replace a matching snapshot. A live download is attempted only with that flag and only when the working file is absent. If the live hash differs, the response is left at `data/external/trafiktal.live.csv` and is not treated as the published snapshot.

The live endpoint can gain or drop count sites. HTTPS certificate checks stay on.

## Commands

Smoke mode is the default. It checks Python, the analysis imports, both config files, the recorded checksums, and the schema of any outputs that are already present. It does not download data and does not rerun experiments. Missing required inputs are errors.

```bash
python scripts/reproduce.py --mode smoke
```

Full mode runs the existing scripts in this order:

1. `scripts/run_m1.py`
2. `scripts/run_m2.py`
3. `scripts/run_m3.py`
4. `scripts/run_m4.py`
5. `scripts/run_m5.py`
6. `scripts/run_external_validation.py`
7. `scripts/run_integrated_study.py`
8. `scripts/run_route_choice_study.py`
9. `scripts/run_robust_placement.py`
10. `scripts/run_exact_optimization.py` (heavy)
11. `scripts/run_placement_stability.py` (heavy)
12. `scripts/run_scalability_study.py` (heavy)
13. `scripts/run_infrastructure_study.py`
14. `scripts/run_municipal_redundancy.py`
15. `scripts/map_m1.py`
16. `scripts/map_standout.py`
17. `scripts/validate_results.py`

A step whose output file already exists is skipped. Pass `--confirm-overwrite` to rerun it. That flag can replace saved results because the runners write to fixed paths. There is no separate output directory.

```bash
python scripts/reproduce.py --mode full --skip-heavy
```

`--skip-heavy` skips steps 10–12: the exact MILP benchmark, the placement-stability resampling, and the nested 500 to 10,000 route scalability study. Smoke mode does not run the infrastructure study or the municipal-redundancy attribution. Full mode runs it when `outputs/infrastructure/summary.json` is absent. Integrated LSH, route-choice, and robust placement still run when their outputs are absent. Smoke mode does not solve a MILP or draw new calibration samples. On this machine the integrated study took several minutes, the scalability study took about 17 minutes, the robust-placement study took about 36 seconds once the saved graph was loaded, the exact benchmark took about 28 seconds, and the stability study took about 4 minutes. A from-scratch M1 build also needs the OSM extract and a network connection the first time the PBF is fetched.

This repository was not rebuilt from an empty `data/` and `outputs/` tree during the reproducibility freeze. The smoke check and `python scripts/validate_results.py` were run against the saved artifacts. Full mode on that tree skips every step that already has an output.

```bash
python scripts/validate_results.py
python scripts/validate_results.py --allow-missing scalability
```

The validator checks relationships: disjoint M1 splits, coverage in 0–1, M4 lambda 0 matching M2 greedy, M3 acceptance, integrated edge accounting, route-choice detour caps, scalability rows that are either measured or explicitly not measured, the municipal snapshot hash, when an exact-optimization summary is present, that a time-limited MILP row is not marked proven, and, when a placement-stability summary is present, that its replicates are new calibration draws and that held-out routes were not used for selection. It does not recompute the published percentages. Numerical comparisons of saved coverage use exact equality of the stored values. Detour caps allow `1e-9` so a binary floating-point value on the cap is not rejected. No other tolerance is used.

## What can run offline

With the frozen municipal CSV, the recorded PBF or the saved M1 GraphML, and the saved outputs, smoke and validation need no network. Maps read the local PBF for the geographical basemap and do not request public tiles. Open `outputs/m1/m1_network.html` or `outputs/standout/standout_counters.html` in a browser, or run `python scripts/map_m1.py --serve` after the map exists.

A first fetch of the PBF, or `--refresh-counts` when the working CSV is missing, needs network access. A changed hash on either file is a new data version.

## What a successful check looks like

`python scripts/reproduce.py --mode smoke` exits 0 and writes `outputs/reproducibility/environment.json`. That report contains the Python version, operating system, package versions, checksums, and pass/fail status. It does not contain a username, home directory, or host name. Do not commit it.

`python scripts/validate_results.py` exits 0 when the saved tables agree with each other. It does not prove that a new OpenStreetMap download would produce the same graph.

## What cannot be reproduced exactly without the original bytes

- The street graph, if the only available PBF is a later BBBike extract.
- The municipal rank comparison, if the only available CSV is a later WFS response.
- Byte-for-byte HTML maps. Regeneration can change timestamps and page metadata without changing the selected counter IDs.
- Wall-clock times. The published timings are observations from one machine, not constants the validator recomputes.
