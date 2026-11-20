# Data sources and provenance

## OpenStreetMap

- Source: https://www.openstreetmap.org/
- Access: https://osmnx.readthedocs.io/
- Intended use: bicycle-accessible street edges and routing topology.
- Requirements: store extraction date, query polygon or place, OSMnx version, network filters, graph statistics, and attribution.
- License: ODbL; check attribution/share-alike obligations before redistribution of derived map datasets.

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
