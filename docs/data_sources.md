# Data sources and provenance

## OpenStreetMap

- Source: https://www.openstreetmap.org/
- Access: https://osmnx.readthedocs.io/
- Intended use: bicycle-accessible street edges and routing topology.
- Requirements: store extraction date, query polygon or place, OSMnx version, network filters, graph statistics, and attribution.
- License: ODbL; check attribution/share-alike obligations before redistribution of derived map datasets.

### M1 pilot extract

The feasibility graph is the WGS84 rectangle in `configs/pilot.yaml` (west 12.5630, south 55.6705, east 12.5965, north 55.6880), labelled as the Indre By core. The bytes are the BBBike Copenhagen OpenStreetMap PBF with `Last-Modified` 2026-11-14T16:51:56Z. OSMnx 2.2 builds the directed bike graph from that file and clips it to the rectangle. The public Overpass interpreter was not usable from this network when the pilot was run. Provenance, the file hash, and the audit counts are in `docs/m1_assumptions.md` and, after a local run, in gitignored `data/processed/m1/extraction_metadata.json`.

## Copenhagen public traffic counts (optional)

- Source: Copenhagen municipality's Trafiktal catalogue.
- Intended use: limited, location-matched external plausibility checks, *not* a complete trip OD matrix.
- Open questions: which records are cyclist-specific, matching precision, time coverage, counting-line definition.
- Do not assume observed counts equal route-level trip ground truth.

## Simulated routes

- Calibration and evaluation OD pairs must be generated reproducibly with **different seeds**.
- Document origin and destination sampling, alternative-route algorithm and trip-weight assumptions.
- Do not label generated routes or weights as observed bicycle journeys.

Keep raw files, large graph snapshots and generated outputs under git-ignored `data/` or `outputs/`.
