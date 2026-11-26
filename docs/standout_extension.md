# Stand-out extension: municipal bicycle counts

This note compares three ways to extend CycleSense and records the extension that was implemented. It does not replace M3 (MinHash, LSH, Louvain) or the proposed M4 placement objective.

M1 is the saved Indre By graph and the uniform / commuter-proxy routes. M2 through M5 are the placement, community, and validation results on those routes. This extension reuses `evaluate_coverage` and `greedy_max_coverage`, the same coverage definition as M2. It does not read or write an M2–M5 result file, and it does not change the saved M1 graph or routes.

## 1. Options

### A. Compare simulated corridors with published bicycle counts

Københavns Kommune publishes "Trafiktal" (Traffic figures) on opendata.dk. The CSV is CC0, has coordinates, a count type, a year, and a bicycle AADT field. Inside the M1 rectangle there are on the order of a hundred recent bicycle counts, including named screenlines such as Dronning Louises Bro and Knippelsbro.

Scientific value is high if the join is honest: it is the first external measurement in the project. It does not need MinHash, Louvain, or M4. The main risks are a wrong street match, a mix of count years, and over-reading a correlation. The counts are not trips, and the municipality chooses where to count.

### B. Place additional counters around sites the city already counts

The same file identifies recurring counting places (`Søsnittet`, counted every year, and `Andre faste tællinger`, repeated on a 10-year cycle). Those are not a confirmed inventory of permanently installed hardware. They are the municipality's standing count programme. Once a place is joined to an eligible segment by geometry and street name, the existing greedy algorithm can ask where K further segments would intercept simulated routes that the current sites miss.

This is a practical question the all-from-scratch baselines do not ask. It is independent of M3/M4. It is only as good as the join in option A. Inventing coordinates was rejected.

### C. Tighten OpenStreetMap eligibility and re-run placement

The M1 candidate rule is already a tag-and-length proxy. A stricter subset (for example dropping service roads or primary carriageways) can be built from `candidates.csv` with no new data. That comparison would show whether the proxy moves the greedy set. It cannot say whether a site can actually be installed, and it adds no external evidence. Complexity is low. Value for the report is smaller than A or B.

### Not pursued

Strava Metro and other trip datasets are not public here. The older "Faste cykeltællinger" workbooks (2005–2014) duplicate the role of Trafiktal with less current locations. A dashboard would not answer the research question.

## 2. Recommendation

A and B use one verified file and stay inside the existing coverage definition. C is feasible but does not bring an observation. The implemented extension is A, with B restricted to the sites A can verify.

Pre-specified rules, fixed before any rank correlation was computed:

- Study rectangle: `configs/pilot.yaml` (west 12.5630, south 55.6705, east 12.5965, north 55.6880).
- Bicycle measurement: published `aadt_cykler` only. Since 2009 the municipality defines it as the 07:00–19:00 count in both directions, times 1.03. This code does not apply the factor again.
- Year: latest count in 2019 or later for each counting-place id. The OpenStreetMap extract used by M1 is dated 2026-11-14.
- Primary sites: `Søsnittet` and `Andre faste tællinger`. Junction counts (`Krydstællinger`) are excluded. One-off project counts (`Øvrige tællinger`) are a sensitivity sample only.
- Snap: nearest eligible M1 segment within 35 m. If another segment is also within 35 m and within 12 m of the nearest distance, the site is ambiguous and unused.
- A snap is in the primary sample only when the published street name and the OpenStreetMap name agree, ignoring punctuation. Short fragments such as `gade` do not count.
- If fewer than 8 primary sites remain, Spearman is not interpreted.
- Rank correlation uses calibration-route traversals. Greedy additions are chosen on calibration routes and scored on held-out routes. The two scenarios are not pooled.
- A geographic baseline on the same sites is Spearman correlation between AADT and distance to the M1 commuter anchor (Rådhuspladsen). That baseline is a description of the counted sites, not a demand model.

## 3. What was implemented

| Piece | Path |
| --- | --- |
| Parsing, matching, Spearman, complementary greedy | `src/cyclesense/external_validation.py` |
| Reproducible run | `scripts/run_external_validation.py` |
| Interactive map | `src/cyclesense/standout_map.py`, `scripts/map_standout.py` |
| Unit tests | `tests/test_external_validation.py`, `tests/test_standout_map.py` |
| This note | `docs/standout_extension.md` |

Command, from the repository root after `python scripts/run_m1.py`:

```bash
python scripts/run_external_validation.py
```

The first run downloads the municipal CSV to `data/external/trafiktal.csv` if it is not already there. Tables and figures are written to `outputs/standout/`. Both directories are gitignored.

M1 graphs, `candidates.csv`, `routes.csv`, the coverage implementation, route generation, and `configs/pilot.yaml` are not modified.

## 4. Results

Executed on 21 November 2026 with `python scripts/run_external_validation.py` after a local `python scripts/run_m1.py`. The M1 audit matches the checked-in pilot: 1,157 routing nodes, 1,047 eligible segments, 1,500 simulated routes (500 + 250 uniform, 500 + 250 commuter-proxy). Seeds remain 42 and 10049.

Municipal file: `data/external/trafiktal.csv`, retrieved 21 November 2026 from the WFS URL in `src/cyclesense/external_validation.py`. SHA-256 `d46f3214ee2a4db9c8ff9a9708934fe6c6fbfb8b0f753aa0dd9ba58981a341ad`. 1,236 rows had a coordinate. Licence CC0, Københavns Kommune / Bydata.

Of the recurring places inside the rectangle with a positive bicycle AADT in 2019 or later, 44 remained after keeping the latest year for each place. The snap left 31 unambiguous geometry matches, 11 ambiguous sites, and 2 unmatched sites. Street names agreed for 26 of the 31 matches. Those 26 are the primary sample: 23 `Andre faste tællinger` and 3 `Søsnittet`, years 2022–2025, bicycle AADT from 500 to 33,000. The median snap distance on that sample is 0.44 m. Four of the 31 geometry matches were kept out of the primary sample because the street names disagreed. Frederiksborggade against Rosenborggade at 27 m is a genuine mismatch. `Tietgensbro` / `Tietgensgade` and `Løngangsstræde` / `Løngangstræde` are spelling differences on what is probably the same street, so the name rule also drops a few plausible joins. One matched segment on H.C. Andersens Boulevard had no OpenStreetMap name and was left out of the primary sample.

Spearman correlations use 2,000 permutations and seed 42. The primary comparison is calibration-route traversals against bicycle AADT.

| Sample | n | Uniform rho (p) | Commuter-proxy rho (p) |
| --- | --- | --- | --- |
| Primary, name-agreeing recurring sites | 26 | 0.257 (0.204) | 0.231 (0.249) |
| Geometric recurring matches, names not required | 31 | 0.364 (0.052) | 0.357 (0.049) |
| Sensitivity: recurring plus one-off project counts | 69 | 0.525 (0.001) | 0.498 (0.001) |

On the primary sites, bicycle AADT is not ranked with distance to Rådhuspladsen (rho 0.136, p 0.515). The top quarter of AADT overlaps the top quarter of simulated traversals for 2 of 6 uniform sites and 3 of 6 commuter-proxy sites.

The primary coefficients are positive and small. With 26 sites they are compatible with no rank agreement. Two concrete rows show why a single correlation is a poor summary. Knippelsbro, 2025, bicycle AADT 21,400, lies on 100 uniform and 89 commuter-proxy calibration routes. Dronning Louises Bro, 2025, bicycle AADT 33,000, lies on 0 routes in both scenarios. That bridge is on the west edge of the pilot rectangle, so the simulated trips, which start and end inside the clipped graph, do not cross it. The zero is a boundary effect of the M1 extract.

The project-count sensitivity is a planned secondary sample, not a replacement for the primary test. Adding those one-off counts produces a moderate rank agreement. Those places were chosen for projects, and the p-values above are not adjusted for the several correlations reported in the same run.

Held-out modeled-route coverage for the 26 name-verified segments, and for greedy segments added from the calibration routes:

| Scenario | Existing | Existing + 5 | Existing + 10 | Existing + 20 | Greedy set of 26 |
| --- | --- | --- | --- | --- | --- |
| Uniform | 0.736 | 0.836 | 0.872 | 0.920 | 0.880 |
| Commuter proxy | 0.724 | 0.828 | 0.852 | 0.892 | 0.880 |

The same-size greedy set shares 3 edges with the 26 municipal segments (Jaccard 0.061). On calibration it reaches 0.950 (uniform) and 0.974 (commuter proxy); on the held-out routes it falls to 0.880. The municipal set was not fit to the calibration routes, and its held-out coverage (0.736 / 0.724) is close to its calibration coverage (0.714 / 0.712). Five additional greedy segments raise held-out coverage by about 0.10. A greedy set of 5 segments, chosen without treating any municipal site as already installed, covers 0.524 of the uniform held-out routes and 0.532 of the commuter-proxy held-out routes. Both figures are below the coverage of the 26 municipal segments.

Figures, gitignored under `outputs/standout/`:

- `alignment_scatter.png` — primary AADT against calibration traversals
- `coverage_comparison.png` — held-out coverage for the rows above
- `matched_sites.png` — the 26 segments and the published AADT

Tables: `alignment_primary.csv`, `coverage.csv`, `matches_recurring.csv`, `summary.json`.

`python scripts/map_standout.py` writes `outputs/standout/standout_counters.html` and a static `outputs/standout/standout_counters.png` from the same M1 artifacts and the cached municipal CSV. The default layers are the 26 name-verified locations and the first five greedy additions for the uniform scenario. The next five uniform segments, and both commuter-proxy groups, stay in the collapsed layer control. Commuter-proxy additions are dashed. Ordinary basemap streets are drawn lighter than the counter lines. The coverage table stays visible; the longer reading notes are behind "How to read this map". Popups show the street name, physical-edge ID, published bicycle AADT, count year and category, and, for a proposed segment, its greedy rank and the calibration-route coverage it adds after the municipal segments and earlier additions. That increment is not held-out coverage. Street names on the basemap are hover text. The page does not request public map tiles. The caption states held-out modeled-route coverage for the existing set, the set plus 5, and the set plus 10, separately for the uniform and commuter-proxy scenarios.

## 5. What this does not show

- A correlation is not evidence that the simulator causes, or equals, municipal counts.
- Held-out modeled-route coverage is not the share of cyclists a counter would observe.
- The city decides where to count. Agreement among those streets can be weaker or stronger than agreement on a random street.
- Counts from 2019–2025 are compared with a November 2026 street extract and with routes that have no clock time.
- Ambiguous snaps and street-name failures are dropped. Parallel cycle tracks can be dropped for that reason.
- The rectangle is about 2 km across. A result here is not a Copenhagen-wide siting plan.
- `Øvrige tællinger` and junction counts are not the standing programme.

## 6. Why it helps the DTU report

M3 through M5 show what the placement methods do on simulated routes. This extension adds an external measurement those algorithms do not use. Inside the pilot rectangle, simulated route frequency does not reliably rank the city's recurring bicycle counts: the primary Spearman coefficients are about 0.23–0.26 with permutation p-values about 0.20–0.25. The same sites already intercept roughly three quarters of the held-out simulated routes, a coverage-maximising set of the same size intercepts 0.88 while sharing only 3 edges, and five further greedy segments add about ten percentage points of modeled-route coverage. The report can place those statements beside the M1–M5 results without calling them observed cyclist coverage. The weak rank agreement qualifies the simulated routes: they are a usable coverage benchmark, and they are not a ranking of published bicycle AADT. Dronning Louises Bro, on the west edge of the study rectangle, is the clearest boundary effect behind that qualification.
