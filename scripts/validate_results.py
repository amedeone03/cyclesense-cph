"""Check saved experiment outputs for internal consistency.

Missing core outputs fail the check. ``--allow-missing scalability`` accepts
a tree that intentionally skipped the 10,000-route study. The checks use
relationships already stored in the outputs. They do not recompute coverage.

    python scripts/validate_results.py
    python scripts/validate_results.py --allow-missing scalability
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cyclesense.reproducibility import validate_outputs, write_environment_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--allow-missing", action="append", default=[], metavar="STEP")
    args = parser.parse_args()
    errors, notes = validate_outputs(ROOT, allow_missing=set(args.allow_missing))
    report = write_environment_report(ROOT, mode="validate", errors=errors, notes=notes)
    for error in errors:
        print(f"Error: {error}")
    for note in notes:
        print(f"Note: {note}")
    print(f"Wrote {report.relative_to(ROOT)}")
    if errors:
        raise SystemExit(1)
    print("Saved results passed the consistency checks.")


if __name__ == "__main__":
    main()
