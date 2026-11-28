"""The examination notebook and its portable tables stay consistent."""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "analysis.ipynb"
ASSETS = ROOT / "notebooks" / "assets"
HEADINGS = (
    "Research questions",
    "Data and network",
    "Maximum-coverage optimization",
    "Certified optimization",
    "Route similarity",
    "Louvain communities",
    "Robustness",
    "Published municipal counts",
    "Synthesis",
)


def _notebook_text() -> str:
    document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert document["nbformat"] == 4
    chunks = []
    for cell in document["cells"]:
        source = cell["source"]
        chunks.append(source if isinstance(source, str) else "".join(source))
    return "\n".join(chunks)


def test_notebook_has_the_academic_sections() -> None:
    text = _notebook_text()
    for heading in HEADINGS:
        assert heading in text
    assert "/Users/" not in text
    assert "https://" not in text
    assert "http://" not in text
    assert "run_scalability_study" not in text


def test_portable_assets_exist() -> None:
    for name in (
        "provenance.json",
        "dataset.json",
        "baselines.csv",
        "exact_comparison.csv",
        "fair_timing.csv",
        "route_lengths.csv",
        "stability.json",
        "municipal_coverage.csv",
    ):
        assert (ASSETS / name).is_file(), name
    provenance = json.loads((ASSETS / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["sources"]
    assert all(item["sha256"] for item in provenance["sources"])


def test_exported_baselines_match_saved_m2_when_present() -> None:
    source = ROOT / "outputs/m2/results.csv"
    if not source.is_file():
        return
    saved = {
        (row["scenario"], row["method"], row["k"]): row["heldout_coverage"]
        for row in csv.DictReader(source.open(newline="", encoding="utf-8"))
        if row["method"] == "greedy" and row["seed"] == ""
    }
    exported = {
        (row["scenario"], row["method"], row["k"]): row["heldout_coverage"]
        for row in csv.DictReader((ASSETS / "baselines.csv").open(newline="", encoding="utf-8"))
        if row["method"] == "greedy"
    }
    assert exported[("uniform", "greedy", "10")] == saved[("uniform", "greedy", "10")]
    assert exported[("commuter_proxy", "greedy", "10")] == saved[("commuter_proxy", "greedy", "10")]
