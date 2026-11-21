# Data sources and provenance

## OpenStreetMap

- Source: https://www.openstreetmap.org/
- Access: https://osmnx.readthedocs.io/
- Intended use: bicycle-accessible street edges and routing topology.
- Requirements: store extraction date, query polygon or place, OSMnx version, network filters, graph statistics, and attribution.
- License: ODbL; check attribution/share-alike obligations before redistribution of derived map datasets.

### M1 pilot extract

The feasibility graph is the WGS84 rectangle in `configs/pilot.yaml` (west 12.5630, south 55.6705, east 12.5965, north 55.6880), labelled as the Indre By core. The bytes are the BBBike Copenhagen OpenStreetMap PBF with `Last-Modified` 2026-11-14T16:51:56Z. OSMnx 2.2 builds the directed bike graph from that file and clips it to the rectangle. The public Overpass interpreter was not usable from this network when the pilot was run. Provenance, the file hash, and the audit counts are in `docs/m1_assumptions.md` and, after a local run, in gitignored `data/processed/m1/extraction_metadata.json`.

## Copenhagen public traffic counts

- Source: Københavns Kommune, Bydata, dataset "Trafiktal" / "Traffic figures".
- Catalogue: https://www.opendata.dk/city-of-copenhagen/trafiktal
- File used by the external check: WFS CSV `k101:trafiktaelling` (EPSG:4326), licence CC0.
- Column notes: https://admin.opendata.dk/dataset/a8816a15-0609-4e3b-baca-897aedcbc9ac/resource/3a91cf0c-8366-404b-9e76-36f9ba769988/download/kolonner_dansk_english.xlsx
- What a bicycle value is: `aadt_cykler` is the published annual average daily bicycle traffic. Since 2009 the municipality defines it as the 07:00–19:00 bicycle count in both directions, multiplied by 1.03. It is not a continuous automatic counter and not an origin–destination matrix.
- Count types used: `Søsnittet` (annual harbour/lake screenline) and `Andre faste tællinger` (fixed sites on a 10-year cycle). `Øvrige tællinger` are one-off project counts and are only a sensitivity. `Krydstællinger` are junction counts and are not matched to a single segment.
- Local copy: gitignored `data/external/trafiktal.csv`, retrieved 21 November 2026.
- The comparison itself is documented in `docs/standout_extension.md`. Do not treat a rank correlation, or modeled-route coverage, as observed cyclist coverage.

## Simulated routes

- Calibration and evaluation OD pairs must be generated reproducibly with **different seeds**.
- Document origin and destination sampling, alternative-route algorithm and trip-weight assumptions.
- Do not label generated routes or weights as observed bicycle journeys.

Keep raw files, large graph snapshots and generated outputs under git-ignored `data/` or `outputs/`.
