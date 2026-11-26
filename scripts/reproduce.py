"""Check the environment or run the existing experiment scripts in order.

Smoke mode is the default when ``--mode`` is omitted. It does not download
data and it does not rerun experiments. Full mode skips a step whose output
already exists unless ``--confirm-overwrite`` is given.

``--skip-heavy`` omits the 10,000-route scalability study
(``scripts/run_scalability_study.py``). The integrated and route-choice
studies still run. They are part of the published results and can take
several minutes when their outputs are absent.

    python scripts/reproduce.py --mode smoke
    python scripts/reproduce.py --mode full --skip-heavy
    python scripts/reproduce.py --mode full --confirm-overwrite
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from cyclesense.reproducibility import (
    check_setup,
    execute,
    load_manifest,
    plan_actions,
    selected_steps,
    validate_outputs,
    workflow_steps,
    write_environment_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--mode", choices=("smoke", "full"), default="smoke")
    parser.add_argument(
        "--skip-heavy",
        action="store_true",
        help="Do not run the 10,000-route scalability study.",
    )
    parser.add_argument(
        "--confirm-overwrite",
        action="store_true",
        help="Rerun steps even when their saved outputs already exist.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "smoke":
        errors, notes = check_setup(ROOT)
        report = write_environment_report(ROOT, mode="smoke", errors=errors, notes=notes)
        _print_lists("Error", errors)
        _print_lists("Note", notes)
        print(f"Wrote {report.relative_to(ROOT)}")
        if errors:
            raise SystemExit(1)
        print("Smoke check passed. No experiments were rerun and no data was downloaded.")
        return

    setup_errors, setup_notes = check_setup(ROOT)
    if setup_errors:
        _print_lists("Error", setup_errors)
        write_environment_report(ROOT, mode="full", errors=setup_errors, notes=setup_notes)
        raise SystemExit(1)
    manifest = load_manifest(ROOT)
    steps = selected_steps(workflow_steps(manifest), skip_heavy=args.skip_heavy)
    for action, step in plan_actions(steps, ROOT, confirm_overwrite=args.confirm_overwrite):
        if action == "skip":
            print(f"skip {step.id}: {step.sentinel} exists")
            continue
        print(f"run {step.id}: {step.script}", flush=True)
        execute([sys.executable, step.script], cwd=ROOT)
    allowed = {"scalability"} if args.skip_heavy else set()
    errors, notes = validate_outputs(ROOT, allow_missing=allowed)
    notes = [*setup_notes, *notes]
    report = write_environment_report(ROOT, mode="full", errors=errors, notes=notes)
    _print_lists("Error", errors)
    _print_lists("Note", notes)
    print(f"Wrote {report.relative_to(ROOT)}")
    if errors:
        raise SystemExit(1)
    print("Full reproduction finished. Existing outputs were kept unless --confirm-overwrite was set.")


def _print_lists(label: str, rows: list[str]) -> None:
    for row in rows:
        print(f"{label}: {row}")


if __name__ == "__main__":
    main()
