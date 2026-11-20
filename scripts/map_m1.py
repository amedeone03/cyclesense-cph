"""Draw the saved M1 network as an interactive HTML map.

This reads the canonical GraphML, candidate table, and route table. It does
not download a graph and it does not generate routes. By default it also
draws streets, buildings, parks, and water from the local BBBike PBF. The
page does not request public map tiles.

    python scripts/map_m1.py
    python scripts/map_m1.py --no-basemap
    python scripts/map_m1.py --serve

``--no-basemap`` keeps the tile-free network view only. ``--serve`` writes
the map and serves it at http://127.0.0.1:8765/m1_network.html.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.basemap import load_context_basemap
from cyclesense.interactive import local_map_server, read_table, write_interactive_map


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes-per-scenario", type=int, default=3)
    parser.add_argument(
        "--no-basemap",
        action="store_true",
        help="Write the tile-free network view and do not read the local PBF.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="After writing the map, serve it at http://127.0.0.1:PORT/m1_network.html",
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    paths = validated_m1_artifacts(ROOT)
    if paths is None:
        raise SystemExit(
            "No validated M1 artifacts in data/processed/m1/. "
            "Run `python scripts/run_m1.py` once; this script will not download a graph."
        )
    import osmnx as ox

    graph = ox.load_graphml(paths["routing_wgs84"])
    sample_x = float(next(iter(graph.nodes(data=True)))[1]["x"])
    if not (8.0 < sample_x < 16.0):
        raise SystemExit(f"{paths['routing_wgs84']} does not look like a WGS84 graph (x={sample_x}).")
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    box = metadata["boundary"]
    boundary = (float(box["west"]), float(box["south"]), float(box["east"]), float(box["north"]))
    basemap = None
    if not args.no_basemap:
        pbf = Path(str(metadata.get("pbf_path") or ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"))
        if not pbf.is_file():
            pbf = ROOT / "cache" / "osm" / "Copenhagen.osm.pbf"
        print(f"Reading geographical context from {pbf}", flush=True)
        basemap = load_context_basemap(pbf, boundary, paths["summary"].parent / "context_basemap.json")
        if basemap is None:
            print("Local basemap unavailable. Writing the tile-free network view.", flush=True)
        else:
            counts = ", ".join(
                f"{key}={len((basemap.get(key) or {}).get('features') or [])}"
                for key in ("water", "green", "buildings", "streets", "waterways", "labels")
            )
            print(f"Local basemap features: {counts}", flush=True)
    output = write_interactive_map(
        graph,
        read_table(paths["candidates"]),
        read_table(paths["routes"]),
        paths["interactive_map"],
        routes_per_scenario=args.routes_per_scenario,
        boundary=boundary,
        basemap=basemap,
    )
    print(f"Wrote {output.relative_to(ROOT)}", flush=True)
    print(f"Routing graph: {paths['routing_wgs84'].relative_to(ROOT)}", flush=True)
    print("Study boundary:", " ".join(str(value) for value in boundary), flush=True)
    print("Click a blue segment to read its physical-edge ID.", flush=True)
    print("Geographical view: python scripts/map_m1.py", flush=True)
    print("Tile-free view:    python scripts/map_m1.py --no-basemap", flush=True)
    print("In the default map, uncheck Geographical basemap for the tile-free network.", flush=True)
    print(f"Open:       python scripts/map_m1.py --serve --port {args.port}", flush=True)
    print(f"            http://127.0.0.1:{args.port}/{output.name}", flush=True)
    if not args.serve:
        return
    server = local_map_server(output.parent, port=args.port)
    print(f"Serving {output.parent.relative_to(ROOT)} — stop with Ctrl+C.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
