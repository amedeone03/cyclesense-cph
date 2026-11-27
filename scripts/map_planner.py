"""Write the interactive planner from saved study outputs.

The page copies measured placements and coverage. It does not place counters
or overwrite the study files.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cyclesense.planner import write_planner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    destination = write_planner(args.root)
    print(destination)


if __name__ == "__main__":
    main()
