# Data sources and provenance

## OpenStreetMap

- Source: https://www.openstreetmap.org/
- Access: https://osmnx.readthedocs.io/
- Intended use: bicycle-accessible street edges and routing topology.
- Requirements: store extraction date, query polygon or place, OSMnx version, network filters, graph statistics, and attribution.
- License: ODbL; check attribution/share-alike obligations before redistribution of derived map datasets.

### M1 pilot extract

The feasibility graph is the WGS84 rectangle in `configs/pilot.yaml` (west 12.5630, south 55.6705, east 12.5965, north 55.6880), labelled as the Indre By core. The bytes used for the published run are the BBBike Copenhagen OpenStreetMap PBF:

- URL: https://download.bbbike.org/osm/bbbike/Copenhagen/Copenhagen.osm.pbf
- HTTP `Last-Modified`: 2026-11-14T16:51:56Z
- Local path, gitignored: `cache/osm/Copenhagen.osm.pbf`
- SHA-256: `3661ec97aa60999a911d0824fca03e525f7ec076bbb5c0339f905f0971fa5262`
- Size of that file: 52,739,614 bytes
- Format: OSM PBF. OSMnx 2.2 reads it with the bike network preset and clips the graph with `truncate_graph_polygon` (`truncate_by_edge` false).

That URL serves BBBike's current Copenhagen extract. It is not a versioned historical snapshot, and a later download can have a different hash. The 50 MB file is not stored in Git. Exact reproduction of the published graph needs the local file with the hash above, or the saved GraphML under `data/processed/m1/`. The public Overpass interpreter was not usable from this network when the pilot was run. The audit is in `docs/m1_assumptions.md`.

## Copenhagen public traffic counts

- Source: Københavns Kommune, Bydata, dataset "Trafiktal" / "Traffic figures".
- Catalogue: https://www.opendata.dk/city-of-copenhagen/trafiktal
- File used by the external check: WFS CSV `k101:trafiktaelling` (EPSG:4326), licence CC0.
- Column notes: https://admin.opendata.dk/dataset/a8816a15-0609-4e3b-baca-897aedcbc9ac/resource/3a91cf0c-8366-404b-9e76-36f9ba769988/download/kolonner_dansk_english.xlsx
- What a bicycle value is: `aadt_cykler` is the published annual average daily bicycle traffic. Since 2009 the municipality defines it as the 07:00–19:00 bicycle count in both directions, multiplied by 1.03. It is not a continuous automatic counter and not an origin–destination matrix.
- Count types used: `Søsnittet` (annual harbour/lake screenline) and `Andre faste tællinger` (fixed sites on a 10-year cycle). `Øvrige tællinger` are one-off project counts and are only a sensitivity. `Krydstællinger` are junction counts and are not matched to a single segment.
- Frozen snapshot, tracked in Git: `snapshots/trafiktal-2026-11-21.csv`, retrieved 21 November 2026. SHA-256 `d46f3214ee2a4db9c8ff9a9708934fe6c6fbfb8b0f753aa0dd9ba58981a341ad` (326,842 bytes). Licence CC0.
- Working copy: gitignored `data/external/trafiktal.csv`. The municipal script copies the frozen snapshot there when the working file is missing. A file with a different hash is refused. `--refresh-counts` does not overwrite a matching snapshot. A live response with a different hash is saved as `trafiktal.live.csv` and is not used as the published file.
- The downloader verifies the HTTPS certificate. If verification fails, install `certifi` through the `analysis` extra or the macOS `Install Certificates.command`. Do not disable certificate checks.
- The comparison itself is documented in `docs/standout_extension.md`. Do not treat a rank correlation, or modeled-route coverage, as observed cyclist coverage.

## Simulated routes

- Calibration and evaluation OD pairs must be generated reproducibly with **different seeds**.
- Document origin and destination sampling, alternative-route algorithm and trip-weight assumptions.
- Do not label generated routes or weights as observed bicycle journeys.

Keep raw files, large graph snapshots and generated outputs under git-ignored `data/` or `outputs/`.
