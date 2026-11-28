"""Execute notebooks/analysis.ipynb and check that saved studies are untouched."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "analysis.ipynb"
SENTINELS = (
    "data/processed/m1/summary.json",
    "outputs/m2/results.csv",
    "outputs/m4/placements.csv",
    "outputs/m5/summary.json",
    "outputs/integrated/summary.json",
    "outputs/exact_optimization/summary.json",
    "outputs/placement_stability/summary.json",
    "outputs/infrastructure/summary.json",
    "outputs/municipal_redundancy/summary.json",
)
REQUIRED_HEADINGS = (
    "Research questions",
    "Data and network",
    "Maximum-coverage optimization",
    "Certified optimization",
    "Route similarity",
    "Scalability of the fair comparison",
    "Louvain communities",
    "Robustness",
    "Published municipal counts",
    "Infrastructure filters and coverage attribution",
    "Synthesis",
)


def main() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    if notebook.get("nbformat") != 4:
        raise SystemExit("analysis.ipynb is not nbformat 4")
    text = "\n".join(cell["source"] if isinstance(cell["source"], str) else "".join(cell["source"]) for cell in notebook["cells"])
    missing = [heading for heading in REQUIRED_HEADINGS if heading not in text]
    if missing:
        raise SystemExit(f"Notebook is missing sections: {missing}")
    if "/Users/" in text or "http://" in text or "https://" in text:
        raise SystemExit("Notebook contains a local home path or a network URL")
    for name in ("provenance.json", "baselines.csv", "fair_timing.csv", "exact_comparison.csv"):
        if not (ROOT / "notebooks" / "assets" / name).is_file():
            raise SystemExit(f"Missing portable asset {name}")
    before = _fingerprints()
    started = time.perf_counter()
    notebook, executed, skipped = _execute()
    elapsed = time.perf_counter() - started
    nbformat.write(notebook, NOTEBOOK)
    after = _fingerprints()
    changed = [path for path, digest in before.items() if after.get(path) != digest]
    if changed:
        raise SystemExit(f"Notebook execution changed saved artifacts: {changed}")
    print(f"Executed {executed} code cells in {elapsed:.1f} seconds.")
    if skipped:
        print("Optional visualizations skipped:")
        for line in skipped:
            print(f"  {line}")
    print("Saved study artifacts were unchanged.")


def _execute() -> tuple[object, int, list[str]]:
    from nbclient import NotebookClient

    notebook = nbformat.read(NOTEBOOK, as_version=4)
    client = NotebookClient(
        notebook,
        timeout=180,
        kernel_name="python3",
        resources={"metadata": {"path": str(ROOT)}},
        allow_errors=False,
    )
    client.execute()
    skipped = []
    code_cells = 0
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        code_cells += 1
        for output in cell.get("outputs", []):
            text = ""
            if output.get("output_type") == "stream":
                text = output.get("text", "")
            elif output.get("output_type") in {"execute_result", "display_data"}:
                text = (output.get("data") or {}).get("text/plain", "")
            if isinstance(text, list):
                text = "".join(text)
            if "skipped" in text.lower():
                skipped.append(text.strip().splitlines()[0][:180])
    return notebook, code_cells, skipped


def _fingerprints() -> dict[str, tuple[int, int]]:
    found = {}
    for relative in SENTINELS:
        path = ROOT / relative
        if path.is_file():
            stat = path.stat()
            found[relative] = (stat.st_size, stat.st_mtime_ns)
    return found


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1) from error
