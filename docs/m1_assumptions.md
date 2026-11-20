# M1 assumptions and limitations

M1 extracts a small central-Copenhagen bicycle graph and builds two simulated route scenarios. It does not place counters, estimate demand, or report a capture rate.

OpenStreetMap geometry is mapped infrastructure. Every route in this pilot is a shortest path between a sampled origin and destination. A route frequency is a property of that sampler. It is not a bicycle count and it is not an observed trip.

## Study boundary

The pilot area is the WGS84 rectangle in `configs/pilot.yaml`:

| Edge | Degrees |
| --- | --- |
| West | 12.5630 |
| South | 55.6705 |
| East | 12.5965 |
| North | 55.6880 |

The label is "Indre By core, Copenhagen, Denmark". The rectangle is the boundary. It is not the municipal border and not a Nominatim polygon. It covers roughly 2 km by 2 km around Rådhuspladsen, Kongens Nytorv, Nørreport, and the central station approaches.

`graph_snapshot_date` in the config is null. The pilot does **not** call the live Overpass interpreter. On this machine `overpass-api.de` refused TCP/443 on `65.109.112.52`, and the other advertised address did not return a reliable study-area response. OSMnx 2.2 instead reads a dated city extract and clips it:

- file: BBBike Copenhagen OpenStreetMap PBF
- URL: `https://download.bbbike.org/osm/bbbike/Copenhagen/Copenhagen.osm.pbf`
- OSM extract timestamp: `2026-11-14T16:51:56Z` (HTTP `Last-Modified`)
- sha256: `3661ec97aa60999a911d0824fca03e525f7ec076bbb5c0339f905f0971fa5262`
- local copy: gitignored `cache/osm/Copenhagen.osm.pbf`

`graph_from_pbf(..., network_type="bike")` applies OSMnx's bike preset in Python (highway present, not a private-access or `bicycle=no` way, and not the excluded highway classes). The same preset's Overpass QL is stored in the metadata for comparison. `truncate_graph_polygon` then keeps nodes inside the rectangle (`truncate_by_edge=False`). Streets that cross the border become dead-ends. Reuse the GraphML files under `data/processed/m1/` rather than expecting a later PBF or Overpass response to match.

## Direction and bicycle access

The graph stays directed. `bike` is not put in OSMnx's bidirectional-network list, so a generic `oneway` tag is not turned into two edges.

OSMnx does not read `oneway:bicycle` by itself. After download, a reverse edge is added only when the tags agree that bicycles may ride against the car one-way:

- `oneway:bicycle` is `no`, `false`, or `0`, or
- `cycleway`, `cycleway:left`, `cycleway:right`, or `cycleway:both` is `opposite`, `opposite_lane`, or `opposite_track`.

If a simplified edge carries a list of values, every value must agree. Mixed tags do not create a reverse edge. The added edge copies length and OSM way ids and is marked `added_contraflow`.

The OSMnx bike preset drops `highway=footway` even when `bicycle=yes`, and it drops ways tagged `bicycle=no` or private access. Routing can still use a carriageway that a cyclist would avoid in practice. That is a network-filter limit, not a demand model.

## Physical segments and candidates

A counter is one physical street segment between two intersections, not a node and not a radius.

The identifier `pe:{smaller node}:{larger node}:{osm way ids}` merges the two directions of the same way. The way-id list and its reverse are the same carriageway. Parallel ways between the same corners keep different ids. Separate blocks of one long OSM way keep different ids because the intersection nodes differ. A self-loop is marked `pe:loop:` and is not a candidate.

**Counting assumption.** One selected candidate observes every modeled traversal that uses that segment, in either direction. Direction-specific counting tubes are not represented.

A physical segment is eligible when all of the following hold:

- length at least 15 m (the longest positive directed length of the segment);
- every highway tag is in `cycleway`, `residential`, `living_street`, `unclassified`, `tertiary` (+ link), `secondary` (+ link), `primary` (+ link), `path`, `track`, `pedestrian`, `service`, or `road`;
- service is not alley, driveway, parking, parking aisle, emergency, drive-through, or slipway;
- bicycle is not `no`, `dismount`, `private`, or `use_sidepath`;
- access is not `private` or `no`;
- a `pedestrian` way is eligible only with `bicycle=yes`, `designated`, or `permissive`.

Trunk roads, footways, and steps are not candidates even if they remain in the routing graph. Eligibility is a tag-and-length proxy. It is not a legal, engineering, or municipal siting decision.

Edges with a missing or non-positive length, and self-loops, are removed before routing. Routes are then restricted to the largest strongly connected component so a sampled pair has a directed path. Nodes outside that component are reported in the audit and are not used as origins or destinations.

## Route scenarios

Both scenarios use length-weighted directed shortest paths. They do not model travel time, signals, turn delays, or cyclist preference. There is no all-pairs matrix.

Origins and destinations are drawn with `random.Random` (Mersenne Twister). The calibration seed is `simulation.random_seed` (42). The evaluation seed is that value plus `evaluation_seed_offset` (10007). Node ids are sorted before sampling so the stream does not depend on graph insertion order.

Euclidean distance is computed in the UTM metres of the projected graph. Pairs closer than 400 m or farther than 2500 m are rejected. A kept route must contain at least three eligible physical segments.

| Scenario | What the draw does |
| --- | --- |
| `uniform` | Origin and destination are uniform among routing nodes. |
| `commuter_proxy` | Spatial kernel around Rådhuspladsen (55.6761 N, 12.5689 E). With distance `d` metres from that point and floor `f = 50`, origin weight is `d + f` and destination weight is `1 / (d + f)`. |

`commuter_proxy` is not a home-to-work matrix. It does not use population, jobs, or education counts. It only moves more simulated destinations toward the documented anchor and more origins toward the edge of this small rectangle. The anchor is snapped to the nearest routing node for the audit; the weights use the projected anchor coordinates.

`alternative_route` (bounded detours) is listed under `deferred_scenarios` and is not generated.

Each accepted route stores:

- the ordered node path;
- `physical_edge_ids`, every physical segment on that path;
- `eligible_edge_ids`, the subset that passes the candidate rule;
- `scenario_weight = 1`, meaning one accepted draw.

Calibration is generated first. Evaluation uses the other seed and drops an origin-destination pair, or an identical physical-edge sequence, already present in that scenario's calibration sample. The two scenarios are not pooled.

## What is saved

Git ignores `data/`, `outputs/`, and `cache/`. These are the canonical M1 artifacts. `data/processed/copenhagen_bike.graphml` is not one of them.

| Role | Path |
| --- | --- |
| Clipped extract, including fragments, after the contraflow step | `data/processed/m1/copenhagen_bike_full.graphml` |
| Routing component, longitude/latitude, used for routes and the interactive map | `data/processed/m1/copenhagen_bike_routing_wgs84.graphml` |
| Same routing topology in the UTM zone OSMnx chooses | `data/processed/m1/copenhagen_bike_routing_projected.graphml` |
| Eligible physical segments | `data/processed/m1/candidates.csv` |
| Modeled routes | `data/processed/m1/routes.csv` |
| Provenance, audit, acceptance summary | `data/processed/m1/extraction_metadata.json`, `audit.json`, `summary.json` |
| Static figures | `outputs/m1/graph_candidates.png`, `outputs/m1/example_routes.png` |
| Interactive map | `outputs/m1/m1_network.html` |
| Source extract, not a graph | `cache/osm/Copenhagen.osm.pbf` |

`scripts/download_graph.py` with `--place` and `--output data/processed/copenhagen_bike.graphml` did not create that file. The script geocodes the place, then calls `download_bike_graph`, which queries Overpass. The output directory is created, and `ox.save_graphml` runs, only after that call returns. Overpass refused the connection, so the script raised `RuntimeError` before any GraphML was written. The study graph was produced separately by `scripts/run_m1.py` from the BBBike PBF and stored only under `data/processed/m1/`.

If `summary.json` passes the M1 completeness check and the pipeline version still matches, `download_graph.py` prints the canonical paths and returns. It does not query Overpass and it does not copy a graph to `--output`. `--force` is a separate Overpass attempt, not the pilot.

Reproduce the extract with `pip install -e '.[analysis,dev]'` and `python scripts/run_m1.py`. `--force-download` fetches the Copenhagen PBF again. The `analysis` extra includes `osmium`, which OSMnx needs to read PBF files, and `folium` for the interactive map.

Regenerate the interactive map without downloading or generating routes:

```bash
python scripts/map_m1.py
python scripts/map_m1.py --no-basemap
python scripts/map_m1.py --serve
```

The default command writes `outputs/m1/m1_network.html` and opens on the saved study boundary. It adds a geographical basemap read from the local BBBike PBF: streets and street names, buildings, parks and other green areas, and water. A display cache of that geometry is `data/processed/m1/context_basemap.json`. It is not a routing graph and it does not change candidates or routes. Layers are Geographical basemap, Bicycle routing network, Eligible counter segments, and Simulated routes. A click or hover on a blue segment reads the `physical_edge_id`. Six calibration routes (three from each scenario) are the simulated-route sample.

Uncheck Geographical basemap for the tile-free network on that same page. `python scripts/map_m1.py --no-basemap` writes that tile-free view directly. `--serve` rebuilds the default map and serves it at <http://127.0.0.1:8765/m1_network.html>. The HTML does not request `tile.openstreetmap.org`. A fixed caption attributes the geometry to OpenStreetMap contributors under the ODbL. Those lines are modeled shortest paths.

## Known limitations

- The rectangle cuts the network at an arbitrary border and is too small to represent Copenhagen.
- Shortest paths ignore delays, surface, and elevation. One-way traps can remain where contraflow tags are missing or mixed.
- OSMnx simplification can merge a block's tags into a list. Ambiguous lists are not treated as contraflow.
- Candidate filters will reject real cycle tracks that are tagged as footways, and they can accept a primary carriageway that cyclists do not use.
- The commuter proxy will look like "trips to the centre" because that is how the kernel is defined. That pattern is not evidence of commuting.
- Duplicate corridors inside one split are kept, because the sampler hit them more than once. They still have weight 1 each. Do not read the resulting edge frequencies as volumes.
- No municipal counter file is matched. No ground-truth trip exists in this repository.
- M2 placement, MinHash/LSH, and Louvain are not part of this run.

## Extraction record

Local run of `scripts/run_m1.py` on 20 November 2026. These are processing counts, not traffic findings. The machine-readable copy is gitignored `data/processed/m1/summary.json`.

| Item | Value |
| --- | --- |
| Processing time (UTC) | 2026-11-20T21:31:52+00:00 |
| OSM extract time | 2026-11-14T16:51:56Z |
| OSMnx / NetworkX | 2.2.0 / 3.7 |
| Projected CRS | EPSG:32633 |
| Clipped graph | 1,238 nodes, 2,638 directed edges |
| After contraflow tags | 207 reverse edges added (2,845 directed edges) |
| Unroutable edges removed | 8 (length audit found no non-positive lengths, so these are self-loops) |
| Routing component | 1,157 nodes, 2,732 directed edges (93.5% of clipped nodes) |
| Physical segments | 1,698 |
| Eligible candidates | 1,047 |
| Candidate rejections | 378 shorter than 15 m, 116 bicycle tag, 100 service yard/alley/driveway, 36 pedestrian without bicycle permission, 21 non-public access |
| Modeled routes | 1,500 valid (500 + 250 uniform, 500 + 250 commuter proxy) |
| Seeds | calibration 42, evaluation 10049 |
| Shared OD pairs or identical paths across the split | 0 |
| Routing-component path sample | 20/20 |
| Full-graph path sample | 35/40 (87.5%) |
| Runtime | about 30 seconds (27 s to build and clip the graph, 1 s to route, 1 s to draw) |

The routing component is one strong component, so every ordered pair inside it has a directed path. The 81 nodes left outside it, and the 20 weak components in the unclipped-to-component graph, are border fragments and one-way pockets. Maps: `outputs/m1/graph_candidates.png`, `outputs/m1/example_routes.png`, and `outputs/m1/m1_network.html`.
