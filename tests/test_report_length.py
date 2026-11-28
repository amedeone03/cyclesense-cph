"""The course report stays inside the 2026 character limit."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _counter():
    path = ROOT / "scripts" / "count_report.py"
    spec = importlib.util.spec_from_file_location("count_report", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_text_is_under_the_stricter_limit() -> None:
    module = _counter()
    result = module.counts((ROOT / "report" / "report.tex").read_text(encoding="utf-8"))
    assert result["report_characters_excluding_space"] <= 11000
    assert result["report_plus_appendix"] <= 11000
    assert (ROOT / "report" / "report.pdf").is_file()
    for name in (
        "fig1_network.pdf",
        "fig2_baselines.pdf",
        "fig3_lsh.pdf",
        "fig4_stability.pdf",
        "fig5_municipal.pdf",
    ):
        assert (ROOT / "report" / "figures" / name).is_file()
