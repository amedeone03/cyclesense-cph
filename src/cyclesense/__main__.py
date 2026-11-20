"""Tiny local smoke test; real network analysis is intentionally not implemented yet."""

from .coverage import greedy_max_coverage


def main() -> None:
    example_routes = {
        "route_1": {"bridge", "street_a"},
        "route_2": {"bridge", "street_b"},
        "route_3": {"park_path"},
    }
    result = greedy_max_coverage(example_routes, budget=1)
    print("CycleSense CPH — synthetic smoke test")
    print(f"Selected counter: {result.selected_edges}")
    print(f"Modeled-route coverage: {result.coverage_fraction:.1%}")
    print("No Copenhagen network or actual cycling measurements used.")


if __name__ == "__main__":
    main()
