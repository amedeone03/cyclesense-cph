"""Optional Overpass download of a bike graph.

The M1 pilot does not use this script. Its graphs are already stored under
``data/processed/m1/``:

- ``copenhagen_bike_full.graphml`` — clipped extract, including fragments
- ``copenhagen_bike_routing_wgs84.graphml`` — routing component in longitude/latitude
- ``copenhagen_bike_routing_projected.graphml`` — same topology in the projected CRS

``data/processed/copenhagen_bike.graphml`` is not a canonical file. A previous
``--place`` / ``--output`` invocation did not create it because this script
calls ``save_graphml`` only after ``download_bike_graph`` returns, and that
call queries Overpass. The Overpass host refused the connection, so the
script raised before creating the output path. ``scripts/run_m1.py`` wrote
the study graph from the BBBike PBF instead, under ``data/processed/m1/``.

When those validated files exist, this command prints their paths and
returns. It does not contact Overpass and it does not copy the GraphML to
``--output``. Pass ``--force`` only for a separate Overpass attempt.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.network import bbox_polygon, download_bike_graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Download an OSM bicycle-routing graph")
    parser.add_argument("--place", help="Place name resolvable by OSMnx")
    parser.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        help="Exact WGS84 rectangle",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output GraphML path")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Query Overpass even when validated M1 files already exist.",
    )
    args = parser.parse_args()
    if bool(args.place) == bool(args.bbox):
        parser.error("provide exactly one of --place or --bbox")

    existing = validated_m1_artifacts(REPO_ROOT)
    if existing is not None and not args.force:
        print("Validated M1 files already exist. Not downloading and not writing a second graph.")
        print(f"Requested output left unchanged: {args.output}")
        for name in ("full_graph", "routing_wgs84", "routing_projected", "candidates", "routes", "summary"):
            print(f"  {name}: {existing[name].relative_to(REPO_ROOT)}")
        print("Interactive map: python scripts/map_m1.py")
        return

    try:
        import osmnx as ox
    except ImportError as exc:
        raise SystemExit("Install analysis dependencies: pip install -e '.[analysis]'") from exc

    cache_folder = str(REPO_ROOT / "cache" / "osmnx")
    if args.bbox:
        west, south, east, north = args.bbox
        polygon = bbox_polygon(west, south, east, north)
        place_query = None
    else:
        place_query = args.place
        polygon = ox.geocode_to_gdf(place_query).geometry.iloc[0]
        west, south, east, north = polygon.bounds
    graph, metadata = download_bike_graph(polygon, cache_folder=cache_folder, retain_all=True)
    metadata["boundary"] = {
        "type": "polygon" if place_query else "bbox",
        "crs": "EPSG:4326",
        "west": west,
        "south": south,
        "east": east,
        "north": north,
    }
    metadata["place_query"] = place_query
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(graph, filepath=str(args.output))
    sidecar = args.output.with_suffix(".metadata.json")
    sidecar.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} | nodes={graph.number_of_nodes()} | edges={graph.number_of_edges()}")
    print(f"Wrote {sidecar}")
    print("Audit graph topology, bicycle access, and candidate edges before routing.")


if __name__ == "__main__":
    main()
