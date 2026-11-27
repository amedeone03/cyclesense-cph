"""Snapshot checks and the ordered reproduction workflow.

This module does not place counters or generate routes. Checksums and the
step order come from ``configs/reproducibility.yaml``. Seeds stay in
``configs/pilot.yaml``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml

from cyclesense.artifacts import validated_m1_artifacts
from cyclesense.validation import validate_m1_summary

MANIFEST_PATH = Path("configs/reproducibility.yaml")
PILOT_PATH = Path("configs/pilot.yaml")
ANALYSIS_IMPORTS = ("osmnx", "networkx", "yaml", "numpy", "pandas", "matplotlib", "folium", "certifi")


@dataclass(frozen=True)
class Step:
    id: str
    script: str
    sentinel: str
    heavy: bool


def load_manifest(root: Path) -> dict[str, Any]:
    """Read the reproducibility manifest. Missing keys are left for the caller."""
    path = root / MANIFEST_PATH
    if not path.is_file():
        raise FileNotFoundError(f"missing {MANIFEST_PATH.as_posix()}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise TypeError(f"{MANIFEST_PATH.as_posix()} must be a mapping")
    return loaded


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def workflow_steps(manifest: Mapping[str, Any]) -> list[Step]:
    """Experiment order. Heavy steps are marked, not removed."""
    workflow = manifest.get("workflow") or {}
    heavy = {str(item) for item in workflow.get("heavy") or []}
    steps = []
    for row in workflow.get("steps") or []:
        steps.append(
            Step(
                id=str(row["id"]),
                script=str(row["script"]),
                sentinel=str(row["sentinel"]),
                heavy=str(row["id"]) in heavy,
            )
        )
    if not steps:
        raise ValueError("reproducibility workflow has no steps")
    return steps


def selected_steps(steps: Sequence[Step], *, skip_heavy: bool) -> list[Step]:
    if skip_heavy:
        return [step for step in steps if not step.heavy]
    return list(steps)


def plan_actions(steps: Sequence[Step], root: Path, *, confirm_overwrite: bool) -> list[tuple[str, Step]]:
    """Return ``skip`` or ``run`` for each step. Existing outputs are skipped by default."""
    actions = []
    for step in steps:
        if (root / step.sentinel).is_file() and not confirm_overwrite:
            actions.append(("skip", step))
        else:
            actions.append(("run", step))
    return actions


def check_setup(root: Path) -> tuple[list[str], list[str]]:
    """Return errors and notes. Notes do not fail the smoke check."""
    errors: list[str] = []
    notes: list[str] = []
    if sys.version_info < (3, 11):  # noqa: UP036 — report an interpreter older than the package metadata
        errors.append(f"Python {sys.version.split()[0]} is below the required 3.11")
    try:
        manifest = load_manifest(root)
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)], notes
    pilot = root / PILOT_PATH
    if not pilot.is_file():
        errors.append(f"missing {PILOT_PATH.as_posix()}")
    else:
        try:
            loaded = yaml.safe_load(pilot.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"could not parse {PILOT_PATH.as_posix()}: {exc}")
        else:
            if not isinstance(loaded, dict) or "study_area" not in loaded or "simulation" not in loaded:
                errors.append(f"{PILOT_PATH.as_posix()} is missing study_area or simulation")
    for package in ANALYSIS_IMPORTS:
        module_name = "yaml" if package == "yaml" else package
        try:
            __import__(module_name)
        except ImportError:
            errors.append(
                f"missing package {package}. Install with python -m pip install -e '.[analysis,dev]'"
            )
    errors.extend(_checksum_errors(root, manifest, notes))
    present_errors, present_notes = validate_outputs(root, allow_missing=_all_step_ids(manifest))
    errors.extend(present_errors)
    notes.extend(present_notes)
    return errors, notes


def _all_step_ids(manifest: Mapping[str, Any]) -> set[str]:
    return {step.id for step in workflow_steps(manifest)}


def _checksum_errors(root: Path, manifest: Mapping[str, Any], notes: list[str]) -> list[str]:
    errors: list[str] = []
    osm = manifest.get("osm") or {}
    municipal = manifest.get("municipal") or {}
    pbf = root / str(osm.get("local_path") or "")
    expected_pbf = str(osm.get("sha256") or "")
    if not expected_pbf or expected_pbf == "unavailable":
        errors.append("OSM sha256 is not recorded")
    elif pbf.is_file():
        actual = sha256_file(pbf)
        if actual != expected_pbf:
            errors.append(
                f"OSM PBF hash {actual} does not match the recorded snapshot {expected_pbf}. "
                "Do not treat a newer BBBike download as the published graph."
            )
    else:
        saved = validated_m1_artifacts(root)
        if saved is None:
            errors.append(
                "OSM PBF is missing and no validated M1 graph is saved. "
                f"The public URL is {osm.get('url')}. It is a current extract, not a frozen "
                "historical file, so a new download may not match the recorded hash."
            )
        else:
            notes.append(
                "OSM PBF is absent. Saved M1 GraphML can be used offline. "
                "Rebuilding from the BBBike URL may not reproduce the published graph."
            )
    if str(osm.get("historical_snapshot")) != "unavailable":
        notes.append("OSM historical_snapshot is not marked unavailable; confirm the manifest.")
    snapshot = root / str(municipal.get("snapshot_path") or "")
    expected_csv = str(municipal.get("sha256") or "")
    if not expected_csv:
        errors.append("municipal sha256 is not recorded")
    elif not snapshot.is_file():
        errors.append(
            f"frozen municipal snapshot is missing at {municipal.get('snapshot_path')}. "
            "It is CC0 and is part of the repository. Do not replace it with a live download."
        )
    else:
        actual = sha256_file(snapshot)
        if actual != expected_csv:
            errors.append(
                f"municipal snapshot hash {actual} does not match {expected_csv}. "
                "The published count comparison uses the recorded file only."
            )
    working = root / str(municipal.get("local_path") or "")
    if working.is_file() and expected_csv:
        actual = sha256_file(working)
        if actual != expected_csv:
            errors.append(
                f"working municipal CSV hash {actual} does not match the frozen snapshot. "
                "Refuse this file for the published results."
            )
    elif snapshot.is_file():
        notes.append(
            f"working copy {municipal.get('local_path')} is absent. "
            "The municipal script restores it from the frozen snapshot."
        )
    return errors


def resolve_municipal_file(
    root: Path,
    destination: Path,
    *,
    refresh: bool,
    download: Callable[[str, Path], None],
) -> str:
    """Use the frozen municipal CSV. Never replace a matching file with a live download.

    Returns ``snapshot`` or ``restored``. A hash mismatch raises ``SystemExit``.
    """
    manifest = load_manifest(root)
    municipal = manifest["municipal"]
    expected = str(municipal["sha256"])
    snapshot = root / str(municipal["snapshot_path"])
    url = str(municipal["url"])
    if destination.is_file() and destination.stat().st_size > 0:
        actual = sha256_file(destination)
        if actual == expected:
            if refresh:
                raise SystemExit(
                    "Refusing to refresh the validated municipal CSV. "
                    "Its hash matches the frozen snapshot. A live file would be a new version."
                )
            return "snapshot"
        raise SystemExit(
            f"Municipal CSV hash {actual} does not match the frozen snapshot {expected}. "
            "This file was not overwritten. Restore "
            f"{municipal['snapshot_path']} or copy it to {destination}."
        )
    if snapshot.is_file() and sha256_file(snapshot) == expected and not refresh:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(snapshot, destination)
        return "restored"
    if not refresh:
        raise SystemExit(
            "The municipal CSV is missing. Copy "
            f"{municipal['snapshot_path']} to {destination}. "
            "A live WFS download can be a newer inventory and is not started automatically."
        )
    live = destination.with_name(destination.stem + ".live.csv")
    download(url, live)
    actual = sha256_file(live)
    if actual == expected:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(live, destination)
        return "snapshot"
    raise SystemExit(
        f"Live municipal download hash {actual} differs from the frozen snapshot {expected}. "
        f"The new version was left at {live.name} and was not installed as the published file."
    )


def validate_outputs(root: Path, *, allow_missing: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Check saved results. Absence is an error unless the step id is allowed."""
    allowed = allow_missing or set()
    errors: list[str] = []
    notes: list[str] = []
    manifest = load_manifest(root)
    for step in workflow_steps(manifest):
        path = root / step.sentinel
        if not path.is_file():
            message = f"{step.id} output is missing: {step.sentinel}"
            if step.id in allowed:
                notes.append(message)
            else:
                errors.append(message)
    if (root / "data/processed/m1/summary.json").is_file():
        errors.extend(_check_m1(root))
    if (root / "outputs/m2/results.csv").is_file() and (root / "outputs/m4/placements.csv").is_file():
        errors.extend(_check_m2_m4(root))
    elif (root / "outputs/m2/results.csv").is_file():
        errors.extend(_check_coverage_table(root / "outputs/m2/results.csv", "m2"))
    if (root / "outputs/m3/summary.json").is_file():
        errors.extend(_check_m3(root))
    if (root / "outputs/m5/summary.json").is_file():
        errors.extend(_check_flag(root / "outputs/m5/summary.json", ("acceptance", "passed"), "m5"))
    if (root / "outputs/integrated/summary.json").is_file():
        errors.extend(_check_integrated(root))
    if (root / "outputs/route_choice/route_diagnostics.csv").is_file():
        errors.extend(_check_route_choice(root))
    if (root / "outputs/scalability/timing_summary.csv").is_file():
        errors.extend(_check_scalability(root))
    if (root / "outputs/standout/summary.json").is_file():
        errors.extend(_check_municipal(root))
    if (root / "outputs/robust_placement/summary.json").is_file():
        errors.extend(_check_robust_placement(root))
    if (root / "outputs/exact_optimization/summary.json").is_file():
        errors.extend(_check_exact_optimization(root))
    if (root / "outputs/placement_stability/summary.json").is_file():
        errors.extend(_check_placement_stability(root))
    return errors, notes


def _check_m1(root: Path) -> list[str]:
    summary = json.loads((root / "data/processed/m1/summary.json").read_text(encoding="utf-8"))
    errors = validate_m1_summary(summary)
    routes = root / "data/processed/m1/routes.csv"
    if not routes.is_file():
        errors.append("M1 routes.csv is missing")
        return errors
    calibration: set[tuple[str, str, str]] = set()
    evaluation: set[tuple[str, str, str]] = set()
    calibration_paths: set[tuple[str, str]] = set()
    evaluation_paths: set[tuple[str, str]] = set()
    with routes.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["scenario"], row["origin_node"], row["destination_node"])
            path_key = (row["scenario"], row["physical_edge_ids"])
            if row["split"] == "calibration":
                calibration.add(key)
                calibration_paths.add(path_key)
            elif row["split"] == "evaluation":
                evaluation.add(key)
                evaluation_paths.add(path_key)
    if calibration & evaluation:
        errors.append("M1 calibration and evaluation share origin-destination pairs")
    if calibration_paths & evaluation_paths:
        errors.append("M1 calibration and evaluation share a physical path")
    if validated_m1_artifacts(root) is None:
        errors.append("M1 artifacts failed the saved-summary completeness check")
    return errors


def _check_m2_m4(root: Path) -> list[str]:
    errors = _check_coverage_table(root / "outputs/m2/results.csv", "m2")
    greedy = {}
    with (root / "outputs/m2/results.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["method"] == "greedy":
                greedy[(row["scenario"], int(row["k"]))] = row["selected_edges"]
                if int(row["n_selected"]) != int(row["k"]):
                    errors.append(f"m2 greedy {row['scenario']} K={row['k']} does not have K edges")
    with (root / "outputs/m4/placements.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            errors.extend(_fraction_errors(row, ("calibration_coverage", "heldout_coverage"), "m4"))
            if row["source"] != "louvain" or float(row["lambda"]) != 0.0:
                continue
            key = (row["scenario"], int(row["k"]))
            if key not in greedy:
                continue
            if row["selected_edges"] != greedy[key]:
                errors.append(
                    f"M4 lambda 0 does not match M2 greedy for {key} at threshold {row['threshold']}"
                )
    return errors


def _check_coverage_table(path: Path, label: str) -> list[str]:
    errors = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return [f"{label} results are empty"]
    for row in rows:
        errors.extend(_fraction_errors(row, ("calibration_coverage", "heldout_coverage"), label))
        edges = [part for part in row["selected_edges"].split("|") if part]
        if len(edges) != len(set(edges)):
            errors.append(f"{label} selection repeats an edge")
        if int(row["n_selected"]) != len(edges):
            errors.append(f"{label} n_selected does not match the edge list")
    return errors


def _fraction_errors(row: Mapping[str, str], fields: Sequence[str], label: str) -> list[str]:
    errors = []
    for field in fields:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError):
            errors.append(f"{label} {field} is not a number")
            continue
        if not 0.0 <= value <= 1.0:
            errors.append(f"{label} {field} is outside 0–1")
    return errors


def _check_m3(root: Path) -> list[str]:
    errors = []
    payload = json.loads((root / "outputs/m3/summary.json").read_text(encoding="utf-8"))
    if payload.get("acceptance_passed") is not True:
        errors.append("M3 acceptance_passed is not true")
    communities = root / "outputs/m3/communities.csv"
    if communities.is_file():
        seen = set()
        with communities.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                seen.add(row["scenario"])
                if int(row["n_communities"]) < 1:
                    errors.append(f"M3 reports no communities for {row['scenario']}")
        if not {"uniform", "commuter_proxy"} <= seen:
            errors.append("M3 communities do not cover both scenarios")
    distribution = root / "outputs/m3/exact_distribution.csv"
    if distribution.is_file():
        with distribution.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                start = float(row["bin_start"])
                if not 0.0 <= start <= 1.0:
                    errors.append("M3 exact Jaccard bin is outside 0–1")
                    break
    return errors


def _check_flag(path: Path, keys: Sequence[str], label: str) -> list[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cursor: Any = payload
    for key in keys:
        if not isinstance(cursor, dict) or key not in cursor:
            return [f"{label} is missing {'.'.join(keys)}"]
        cursor = cursor[key]
    if cursor is not True:
        return [f"{label} {'.'.join(keys)} is not true"]
    return []


def _check_integrated(root: Path) -> list[str]:
    payload = json.loads((root / "outputs/integrated/summary.json").read_text(encoding="utf-8"))
    acceptance = payload.get("acceptance") or {}
    errors = []
    for key in (
        "exact_reproduces_m3_and_m4",
        "streaming_exact_matches_materialized_reference",
        "approximate_edges_are_verified_subgraphs",
        "canonical_artifacts_unchanged",
    ):
        if acceptance.get(key) is not True:
            errors.append(f"integrated acceptance {key} is not true")
    for row in payload.get("graphs") or []:
        missed = row.get("n_edges_missed")
        retained = row.get("n_edges_retained")
        exact = row.get("n_exact_edges")
        if None in {missed, retained, exact}:
            continue
        if int(retained) + int(missed) != int(exact):
            errors.append("integrated graph retained and missed edges do not sum to the exact edge count")
        if int(row.get("n_approximate_edges") or 0) > int(exact):
            errors.append("integrated approximate graph has more edges than the exact graph")
    return errors


def _check_route_choice(root: Path) -> list[str]:
    errors = []
    limits = set()
    with (root / "outputs/route_choice/route_diagnostics.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            status = row["status"]
            if status not in {"changed", "unchanged", "rejected_detour", "failed"}:
                errors.append(f"unknown route-choice status {status}")
                break
            limit = float(row["detour_limit"])
            limits.add(limit)
            if status == "changed" and row["detour"] != "" and float(row["detour"]) > limit + 1e-9:
                errors.append("a changed route exceeds its detour cap")
                break
            if row["origin_node"] == "" or row["destination_node"] == "":
                errors.append("a route-choice row is missing an endpoint")
                break
    placements = root / "outputs/m4/placements.csv"
    chosen = root / "outputs/route_choice/summary.json"
    if placements.is_file() and chosen.is_file():
        summary = json.loads(chosen.read_text(encoding="utf-8"))
        if summary.get("routes_are_simulated") is not True:
            errors.append("route-choice summary does not mark routes as simulated")
        for row in summary.get("shortest_coverage_matches_saved_m4") or []:
            if row.get("matches") is not True:
                errors.append("route-choice shortest-path coverage does not match the saved M4 placement")
                break
    if not limits:
        errors.append("route-choice diagnostics have no detour limits")
    return errors


def _check_placement_stability(root: Path) -> list[str]:
    summary = json.loads((root / "outputs/placement_stability/summary.json").read_text(encoding="utf-8"))
    errors = []
    if summary.get("routes_are_simulated") is not True:
        errors.append("placement stability summary does not mark routes as simulated")
    if summary.get("held_out_used_for_selection") is not False:
        errors.append("placement stability used held-out routes for selection")
    if summary.get("replicates_are_independent_od_draws") is not True:
        errors.append("placement stability does not identify its replicates as new OD draws")
    if int(summary.get("n_replicates") or 0) < 2:
        errors.append("placement stability summary has fewer than two replicates")
    return errors


def _check_exact_optimization(root: Path) -> list[str]:
    summary = json.loads((root / "outputs/exact_optimization/summary.json").read_text(encoding="utf-8"))
    errors = []
    if summary.get("routes_are_simulated") is not True:
        errors.append("exact optimization summary does not mark routes as simulated")
    if summary.get("held_out_used_for_selection") is not False:
        errors.append("exact optimization used held-out routes for selection")
    runs = root / "outputs/exact_optimization/solver_runs.csv"
    if runs.is_file():
        with runs.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                status = row.get("status")
                if status not in {"optimal", "time_limited", "infeasible", "unbounded", "failed", "no_incumbent"}:
                    errors.append(f"unknown MILP status {status}")
                    break
                if status == "time_limited" and str(row.get("proven_optimal")).lower() == "true":
                    errors.append("a time-limited MILP run is marked proven optimal")
                    break
                if status == "optimal" and str(row.get("proven_optimal")).lower() != "true":
                    errors.append("an optimal MILP run is not marked proven")
                    break
    return errors


def _check_robust_placement(root: Path) -> list[str]:
    summary = json.loads((root / "outputs/robust_placement/summary.json").read_text(encoding="utf-8"))
    errors = []
    if summary.get("routes_are_simulated") is not True:
        errors.append("robust placement summary does not mark routes as simulated")
    if summary.get("training_uses_calibration_only") is not True:
        errors.append("robust placement training is not marked as calibration-only")
    if summary.get("held_out_used_for_selection") is not False:
        errors.append("robust placement does not record that held-out routes were unused")
    if summary.get("seed_ranges_disjoint") is not True:
        errors.append("robust placement seed ranges are not marked disjoint")
    placements = root / "outputs/robust_placement/placements.csv"
    if placements.is_file():
        seen: dict[tuple[str, str], set[str]] = {}
        with placements.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                key = (row["method"], row["k"])
                seen.setdefault(key, set()).add(row["physical_edge_id"])
        for (method, k_text), edges in seen.items():
            if len(edges) != int(k_text):
                errors.append(f"robust placement {method} K={k_text} does not have K distinct edges")
    return errors


def _check_scalability(root: Path) -> list[str]:
    errors = []
    with (root / "outputs/scalability/timing_summary.csv").open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return ["scalability timing summary is empty"]
    for row in rows:
        status = row.get("status")
        if status not in {"measured", "not_run", "resource_limit"}:
            errors.append(f"unknown scalability status {status}")
            continue
        if status == "measured":
            if int(row.get("n_timing_repeats") or 0) < 1 or row.get("median_seconds") in {"", None}:
                errors.append(f"measured scalability row {row.get('method')} has no timing observation")
        elif row.get("median_seconds") not in {"", None}:
            errors.append("an unmeasured scalability row contains a runtime")
    summary_path = root / "outputs/scalability/summary.json"
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if summary.get("routes_are_simulated") is not True:
            errors.append("scalability summary does not mark routes as simulated")
        if summary.get("timing_excludes_tracemalloc") is not True:
            errors.append("scalability summary does not separate timing from tracemalloc")
    return errors


def _check_municipal(root: Path) -> list[str]:
    errors = []
    manifest = load_manifest(root)
    expected = str(manifest["municipal"]["sha256"])
    working = root / str(manifest["municipal"]["local_path"])
    if working.is_file() and sha256_file(working) != expected:
        errors.append("standout results are not tied to the frozen municipal snapshot")
    summary = json.loads((root / "outputs/standout/summary.json").read_text(encoding="utf-8"))
    primary = (summary.get("samples") or {}).get("recurring_name_agree") or {}
    if int(primary.get("n_analysis_edges") or 0) < 1:
        errors.append("municipal summary has no name-verified analysis edges")
    for row in summary.get("coverage") or []:
        for field in ("held_out_existing_coverage",):
            value = row.get(field)
            if value is None or not 0.0 <= float(value) <= 1.0:
                errors.append("municipal modeled-route coverage is outside 0–1")
                break
    note = json.dumps(summary.get("interpretation") or {})
    if "observed" not in note.lower() and "not a causal" not in note.lower():
        provenance = summary.get("provenance") or {}
        if "simulated" not in json.dumps(provenance).lower() and "not a causal" not in json.dumps(provenance).lower():
            errors.append("municipal summary does not distinguish counts from modeled coverage")
    return errors


def execute(command: Sequence[str], *, cwd: Path) -> None:
    """Run one existing script. A non-zero exit is raised, not hidden."""
    completed = subprocess.run(list(command), cwd=cwd, check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def write_environment_report(
    root: Path,
    *,
    mode: str,
    errors: Sequence[str],
    notes: Sequence[str],
) -> Path:
    """Write a report without usernames, home directories, or host names."""
    manifest_path = root / MANIFEST_PATH
    pilot = root / PILOT_PATH
    manifest = load_manifest(root) if manifest_path.is_file() else {}
    checksums = {}
    for label, relative in (
        ("osm", str((manifest.get("osm") or {}).get("local_path") or "")),
        ("municipal_snapshot", str((manifest.get("municipal") or {}).get("snapshot_path") or "")),
        ("municipal_working", str((manifest.get("municipal") or {}).get("local_path") or "")),
        ("configuration", PILOT_PATH.as_posix()),
        ("manifest", MANIFEST_PATH.as_posix()),
    ):
        path = root / relative if relative else None
        if path is not None and path.is_file():
            checksums[label] = sha256_file(path)
        elif relative:
            checksums[label] = "missing"
    packages = {}
    for name in ("networkx", "osmnx", "numpy", "pandas", "pyyaml", "folium", "certifi", "matplotlib"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "not-installed"
    output = root / "outputs" / "reproducibility" / "environment.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "mode": mode,
        "python": sys.version.split()[0],
        "python_requires": manifest.get("python_requires"),
        "operating_system": platform.system(),
        "operating_system_release": platform.release(),
        "machine": platform.machine(),
        "packages": packages,
        "checksums": checksums,
        "pilot_configuration_present": pilot.is_file(),
        "validation_passed": not errors,
        "errors": list(errors),
        "notes": list(notes),
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output
