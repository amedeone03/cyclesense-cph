"""Download a versionable OpenStreetMap bicycle network (requires Internet).

Example:
    python scripts/download_graph.py --place "Copenhagen, Denmark" --output data/processed/bike.graphml

Use a validated, small study boundary for the actual pilot. OSMnx and
OpenStreetMap/Overpass responses can vary; record query time and assumptions.
"""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Download an OSM bicycle-routing graph")
    parser.add_argument("--place", required=True, help="Place name resolvable by OSMnx")
    parser.add_argument("--output", type=Path, required=True, help="Output GraphML path")
    args = parser.parse_args()
    try:
        import osmnx as ox
    except ImportError as exc:
        raise SystemExit("Install analysis dependencies: pip install -e '.[analysis]'") from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    graph = ox.graph_from_place(args.place, network_type="bike", simplify=True)
    ox.save_graphml(graph, filepath=str(args.output))
    print(f"Wrote {args.output} | nodes={len(graph.nodes)} | edges={len(graph.edges)}")
    print("Audit graph topology, bicycle access, and candidate edges before routing.")


if __name__ == "__main__":
    main()
