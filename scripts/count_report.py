"""Count report text the way the Autumn 2026 brief specifies.

The brief caps the report at 11,000 characters excluding white space
(12,500 for a group of five). This count includes the title, body,
captions, mathematics, and references. It excludes the contribution
appendix, which the brief allows to sit with the notebook. Figure
drawings are not text. LaTeX commands are not counted; their visible
arguments are.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "report" / "report.tex"
LIMIT = 11000
LIMIT_GROUP_OF_FIVE = 12500


def brace_argument(source: str, command: str) -> str:
    marker = source.find("\\" + command + "{")
    if marker < 0:
        return ""
    start = source.find("{", marker)
    depth = 0
    characters: list[str] = []
    for character in source[start:]:
        if character == "{":
            depth += 1
            if depth > 1:
                characters.append(character)
        elif character == "}":
            depth -= 1
            if depth == 0:
                break
            characters.append(character)
        elif depth >= 1:
            characters.append(character)
    return "".join(characters)


def visible_text(source: str) -> str:
    source = re.sub(r"\\includegraphics(\[[^\]]*\])?\{[^}]*\}", "", source)
    source = re.sub(r"(?<!\\)%.*", "", source)
    for _ in range(8):
        source = re.sub(r"\\(?:textbf|emph|large|small|path|url|texttt)\{([^{}]*)\}", r"\1", source)
    source = re.sub(r"\\(?:cite|ref|eqref|label)\{[^{}]*\}", "", source)
    source = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?", " ", source)
    source = source.replace("{", "").replace("}", "").replace("~", " ").replace("&", " ")
    source = source.replace("\\", "")
    return re.sub(r"\s+", "", source)


def counts(source: str) -> dict[str, int]:
    front = " ".join(brace_argument(source, name) for name in ("title", "author", "date"))
    body = source.split(r"\begin{document}", 1)[1].split(r"\end{document}", 1)[0]
    report, _, appendix = body.partition(r"\section*{Appendix")
    report_characters = len(visible_text(front + "\n" + report))
    appendix_characters = len(visible_text(appendix))
    return {
        "report_characters_excluding_space": report_characters,
        "appendix_characters_excluding_space": appendix_characters,
        "report_plus_appendix": report_characters + appendix_characters,
        "limit_group_of_four": LIMIT,
        "limit_group_of_five": LIMIT_GROUP_OF_FIVE,
        "margin_under_group_of_four": LIMIT - report_characters,
        "margin_if_appendix_is_included": LIMIT - (report_characters + appendix_characters),
    }


def main() -> None:
    result = counts(SOURCE.read_text(encoding="utf-8"))
    destination = ROOT / "report" / "character_count.json"
    destination.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if result["report_plus_appendix"] > LIMIT:
        raise SystemExit("Report plus appendix exceeds 11,000 characters excluding white space.")


if __name__ == "__main__":
    main()
