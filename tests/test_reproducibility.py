"""Fixture checks for snapshot handling and the reproduction workflow."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

from cyclesense.external_validation import TRAFIKTAL_CSV_URL
from cyclesense.reproducibility import (
    check_setup,
    execute,
    load_manifest,
    plan_actions,
    resolve_municipal_file,
    selected_steps,
    validate_outputs,
    workflow_steps,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _write_tree(tmp: Path, *, pbf: str = "pbf-bytes", csv_text: str = "aadt_cykler\n1\n") -> dict:
    pbf_hash = _sha(pbf)
    csv_hash = _sha(csv_text)
    (tmp / "cache/osm").mkdir(parents=True)
    (tmp / "snapshots").mkdir()
    (tmp / "configs").mkdir()
    (tmp / "cache/osm/Copenhagen.osm.pbf").write_text(pbf, encoding="utf-8")
    (tmp / "snapshots/trafiktal-2026-11-21.csv").write_text(csv_text, encoding="utf-8")
    manifest = {
        "python_requires": ">=3.11",
        "osm": {
            "url": "https://example.invalid/copenhagen.osm.pbf",
            "local_path": "cache/osm/Copenhagen.osm.pbf",
            "sha256": pbf_hash,
            "historical_snapshot": "unavailable",
        },
        "municipal": {
            "url": "https://example.invalid/trafiktal.csv",
            "local_path": "data/external/trafiktal.csv",
            "snapshot_path": "snapshots/trafiktal-2026-11-21.csv",
            "sha256": csv_hash,
        },
        "workflow": {
            "heavy": ["scalability"],
            "steps": [
                {"id": "m1", "script": "scripts/run_m1.py", "sentinel": "data/processed/m1/summary.json"},
                {"id": "m2", "script": "scripts/run_m2.py", "sentinel": "outputs/m2/summary.json"},
                {"id": "scalability", "script": "scripts/run_scalability_study.py", "sentinel": "outputs/scalability/summary.json"},
            ],
        },
    }
    (tmp / "configs/reproducibility.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (tmp / "configs/pilot.yaml").write_text(
        yaml.safe_dump({"study_area": {"west": 1}, "simulation": {"scenarios": ["uniform"]}}),
        encoding="utf-8",
    )
    return manifest


def test_manifest_parses_and_keeps_step_order() -> None:
    manifest = load_manifest(ROOT)
    steps = workflow_steps(manifest)
    ids = [step.id for step in steps]
    assert ids.index("m1") < ids.index("m2") < ids.index("m5")
    assert ids.index("municipal") < ids.index("integrated") < ids.index("scalability")
    assert steps[-1].id == "map_standout"
    heavy = [step.id for step in steps if step.heavy]
    assert heavy == ["exact_optimization", "scalability"]


def test_skip_heavy_omits_the_large_benchmarks() -> None:
    steps = workflow_steps(load_manifest(ROOT))
    kept = [step.id for step in selected_steps(steps, skip_heavy=True)]
    assert "scalability" not in kept
    assert "exact_optimization" not in kept
    assert "integrated" in kept
    assert "route_choice" in kept


def test_existing_outputs_are_skipped_unless_overwrite_is_confirmed(tmp_path: Path) -> None:
    manifest = _write_tree(tmp_path)
    steps = workflow_steps(manifest)
    sentinel = tmp_path / "outputs/m2/summary.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("{}", encoding="utf-8")
    planned = {step.id: action for action, step in plan_actions(steps, tmp_path, confirm_overwrite=False)}
    assert planned["m2"] == "skip"
    assert planned["m1"] == "run"
    confirmed = {step.id: action for action, step in plan_actions(steps, tmp_path, confirm_overwrite=True)}
    assert confirmed["m2"] == "run"


def test_missing_osm_file_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_tree(tmp_path)
    (tmp_path / "cache/osm/Copenhagen.osm.pbf").unlink()
    monkeypatch.setattr("cyclesense.reproducibility.ANALYSIS_IMPORTS", ())
    errors, notes = check_setup(tmp_path)
    assert any("OSM PBF is missing" in error for error in errors)
    assert notes == [] or all("OSM" not in note or "absent" in note for note in notes)


def test_incorrect_osm_checksum_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_tree(tmp_path)
    (tmp_path / "cache/osm/Copenhagen.osm.pbf").write_text("different", encoding="utf-8")
    monkeypatch.setattr("cyclesense.reproducibility.ANALYSIS_IMPORTS", ())
    errors, _notes = check_setup(tmp_path)
    assert any("does not match the recorded snapshot" in error for error in errors)


def test_matching_snapshot_is_kept_and_a_live_file_is_not_installed(tmp_path: Path) -> None:
    manifest = _write_tree(tmp_path)
    destination = tmp_path / "data/external/trafiktal.csv"
    calls: list[str] = []

    def download(url: str, path: Path) -> None:
        calls.append(url)
        path.write_text("new-version\n", encoding="utf-8")

    assert resolve_municipal_file(tmp_path, destination, refresh=False, download=download) == "restored"
    assert destination.read_text(encoding="utf-8").startswith("aadt_cykler")
    assert calls == []
    with pytest.raises(SystemExit, match="Refusing to refresh"):
        resolve_municipal_file(tmp_path, destination, refresh=True, download=download)
    destination.unlink()
    with pytest.raises(SystemExit, match="new version"):
        resolve_municipal_file(tmp_path, destination, refresh=True, download=download)
    assert not destination.exists()
    assert (tmp_path / "data/external/trafiktal.live.csv").is_file()
    assert manifest["municipal"]["sha256"]


def test_hash_mismatch_does_not_overwrite_the_working_file(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    destination = tmp_path / "data/external/trafiktal.csv"
    destination.parent.mkdir(parents=True)
    destination.write_text("not-the-snapshot\n", encoding="utf-8")

    def download(url: str, path: Path) -> None:
        raise AssertionError(url)

    with pytest.raises(SystemExit, match="does not match"):
        resolve_municipal_file(tmp_path, destination, refresh=False, download=download)
    assert destination.read_text(encoding="utf-8") == "not-the-snapshot\n"


def test_failed_command_propagates(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        execute([sys.executable, "-c", "import sys; sys.exit(3)"], cwd=tmp_path)
    assert caught.value.code == 3


def test_validation_rejects_coverage_above_one(tmp_path: Path) -> None:
    manifest = _write_tree(tmp_path)
    results = tmp_path / "outputs/m2/results.csv"
    results.parent.mkdir(parents=True)
    results.write_text(
        "scenario,method,k,n_selected,calibration_coverage,heldout_coverage,selected_edges\n"
        "uniform,greedy,1,1,0.5,1.4,edge-a\n",
        encoding="utf-8",
    )
    errors, _notes = validate_outputs(tmp_path, allow_missing={step["id"] for step in manifest["workflow"]["steps"]})
    assert any("outside 0–1" in error for error in errors)


def test_default_mode_is_smoke() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("reproduce", ROOT / "scripts" / "reproduce.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.build_parser()
    assert parser.get_default("mode") == "smoke"
    assert parser.get_default("skip_heavy") is False
    assert parser.get_default("confirm_overwrite") is False
    help_text = parser.format_help()
    assert "10,000-route" in help_text


def test_recorded_municipal_url_matches_the_downloader() -> None:
    manifest = load_manifest(ROOT)
    assert manifest["municipal"]["url"] == TRAFIKTAL_CSV_URL
    assert manifest["municipal"]["sha256"] == "d46f3214ee2a4db9c8ff9a9708934fe6c6fbfb8b0f753aa0dd9ba58981a341ad"
    assert manifest["osm"]["historical_snapshot"] == "unavailable"
