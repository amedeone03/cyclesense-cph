"""Figures for the exact versus verified-LSH placement pipeline.

Every series is computed on simulated routes. A coverage difference is a
difference in modeled-route coverage, not observed cyclist capture.
"""

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

_MPLCONFIG = Path(__file__).resolve().parents[2] / "outputs" / "integrated" / "mplconfig"
_MPLCONFIG.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_MPLCONFIG))
os.environ.setdefault("MPLBACKEND", "Agg")

EXACT = "#4daf4a"
STREAMING = "#377eb8"
LSH = "#e41a1c"
SCENARIO_COLOR = {"uniform": "#4daf4a", "commuter_proxy": "#377eb8"}
METHOD_COLOR = {
    "materialized_exact": EXACT,
    "streaming_exact": STREAMING,
    "verified_lsh": LSH,
}
METHOD_LABEL = {
    "materialized_exact": "Materialized exact",
    "streaming_exact": "Streaming exact",
    "verified_lsh": "Verified LSH, 32×16×2",
}
SCENARIO_LABEL = {"uniform": "Uniform", "commuter_proxy": "Commuter proxy"}


def _save(figure, output: Path, plt) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.tight_layout()
    figure.savefig(output, dpi=140)
    plt.close(figure)


def plot_graph_recall(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Graph-edge recall of each pre-specified LSH banding."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8.2, 4.4))
    roles = _roles(rows)
    width = 0.36
    for offset, scenario in ((-width / 2, "uniform"), (width / 2, "commuter_proxy")):
        values = [_value(rows, scenario, role, "graph_edge_recall") for role in roles]
        positions = [index + offset for index in range(len(roles))]
        axis.bar(
            positions,
            values,
            width=width,
            color=SCENARIO_COLOR[scenario],
            label=SCENARIO_LABEL[scenario],
        )
    axis.set_xticks(
        range(len(roles)), [_role_label(role) for role in roles], rotation=15, ha="right"
    )
    axis.set_ylim(0, 1.05)
    axis.set_ylabel("Exact graph edges retained")
    axis.set_title("Verified LSH graph-edge recall on simulated calibration routes")
    axis.legend()
    _save(figure, output, plt)


def plot_partition_agreement(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Adjusted Rand index against graph-edge recall."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 4.4))
    for scenario, color in SCENARIO_COLOR.items():
        subset = [row for row in rows if row["scenario"] == scenario]
        axis.scatter(
            [float(row["graph_edge_recall"]) for row in subset],
            [float(row["adjusted_rand_index"]) for row in subset],
            color=color,
            s=46,
            label=SCENARIO_LABEL[scenario],
        )
    axis.set_xlim(0, 1.05)
    axis.set_ylim(0, 1.05)
    axis.set_xlabel("Graph-edge recall")
    axis.set_ylabel("Adjusted Rand index versus exact Louvain")
    axis.set_title("Partition agreement on simulated routes")
    axis.legend()
    _save(figure, output, plt)


def plot_placement_overlap(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Share of K=10 locations shared with the exact-pipeline selection."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(8.2, 4.4))
    roles = _roles(rows)
    width = 0.36
    for offset, scenario in ((-width / 2, "uniform"), (width / 2, "commuter_proxy")):
        values = [_value(rows, scenario, role, "selected_jaccard") for role in roles]
        positions = [index + offset for index in range(len(roles))]
        axis.bar(
            positions,
            values,
            width=width,
            color=SCENARIO_COLOR[scenario],
            label=SCENARIO_LABEL[scenario],
        )
    axis.set_xticks(
        range(len(roles)), [_role_label(role) for role in roles], rotation=15, ha="right"
    )
    axis.set_ylim(0, 1.05)
    axis.set_ylabel("Jaccard similarity of the selected sets")
    axis.set_title("K=10 placements, λ=0.25, simulated routes")
    axis.legend()
    _save(figure, output, plt)


def plot_coverage_difference(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Held-out modeled coverage of the approximate selection minus the exact selection."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 4.4))
    for scenario, color in SCENARIO_COLOR.items():
        subset = [row for row in rows if row["scenario"] == scenario]
        axis.scatter(
            [float(row["graph_edge_recall"]) for row in subset],
            [float(row["heldout_difference"]) * 100 for row in subset],
            color=color,
            s=46,
            label=SCENARIO_LABEL[scenario],
        )
    axis.axhline(0, color="#666666", linewidth=0.8)
    axis.set_xlim(0, 1.05)
    axis.set_xlabel("Graph-edge recall")
    axis.set_ylabel("Held-out coverage difference (pp)")
    axis.set_title("Approximate minus exact, K=10, λ=0.25")
    axis.legend()
    _save(figure, output, plt)


def plot_runtime(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """End-to-end seconds against the number of simulated routes."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.4, 4.4))
    ordered = sorted(rows, key=lambda row: int(row["n_routes"]))
    axis.plot(
        [int(row["n_routes"]) for row in ordered],
        [float(row["exact_seconds"]) for row in ordered],
        color=EXACT,
        marker="o",
        label="Exact Jaccard pipeline",
    )
    axis.plot(
        [int(row["n_routes"]) for row in ordered],
        [float(row["lsh_seconds"]) for row in ordered],
        color=LSH,
        marker="o",
        label="Verified LSH pipeline",
    )
    axis.set_xlabel("Simulated calibration routes")
    axis.set_ylabel("End-to-end seconds")
    axis.set_title("Similarity, Louvain, and placement")
    axis.legend()
    _save(figure, output, plt)


def plot_stage_breakdown(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Second-pass stage times at the largest measured route count."""
    import matplotlib.pyplot as plt

    largest = max(int(row["n_routes"]) for row in rows)
    chosen = next(row for row in rows if int(row["n_routes"]) == largest)
    exact_stages = (
        ("Pairwise Jaccard", "exact_pairwise_s"),
        ("Graph", "exact_graph_s"),
        ("Louvain", "exact_louvain_s"),
        ("Weights and greedy", "exact_placement_s"),
    )
    lsh_stages = (
        ("Signatures", "lsh_signature_s"),
        ("Index and query", "lsh_query_s"),
        ("Verify", "lsh_verify_s"),
        ("Graph", "lsh_graph_s"),
        ("Louvain", "lsh_louvain_s"),
        ("Weights and greedy", "lsh_placement_s"),
    )
    figure, axes = plt.subplots(1, 2, figsize=(8.6, 4.2), sharey=False)
    for axis, title, stages, color in (
        (axes[0], "Exact", exact_stages, EXACT),
        (axes[1], "Verified LSH", lsh_stages, LSH),
    ):
        labels = [name for name, _key in stages]
        values = [float(chosen[key]) for _name, key in stages]
        axis.barh(labels[::-1], values[::-1], color=color)
        axis.set_xlabel("Seconds")
        axis.set_title(f"{title}, {largest} simulated routes")
    _save(figure, output, plt)


def plot_fair_runtime(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Median end-to-end seconds. Whiskers are the min and max of the timing repeats."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.8, 4.4))
    for method, color in METHOD_COLOR.items():
        subset = sorted(
            (row for row in rows if row["method"] == method),
            key=lambda row: int(row["n_routes"]),
        )
        if not subset:
            continue
        positions = [int(row["n_routes"]) for row in subset]
        medians = [float(row["median_seconds"]) for row in subset]
        lower = [float(row["median_seconds"]) - float(row["min_seconds"]) for row in subset]
        upper = [float(row["max_seconds"]) - float(row["median_seconds"]) for row in subset]
        axis.errorbar(
            positions,
            medians,
            yerr=[lower, upper],
            color=color,
            marker="o",
            capsize=3,
            label=METHOD_LABEL[method],
        )
    axis.set_xlabel("Simulated calibration routes")
    axis.set_ylabel("Median end-to-end seconds")
    axis.set_title("Five timing repeats, generation excluded")
    axis.legend()
    _save(figure, output, plt)


def plot_fair_memory(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Median peak tracemalloc MB from separate memory repeats."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(6.8, 4.4))
    for method, color in METHOD_COLOR.items():
        subset = sorted(
            (row for row in rows if row["method"] == method),
            key=lambda row: int(row["n_routes"]),
        )
        if not subset:
            continue
        axis.plot(
            [int(row["n_routes"]) for row in subset],
            [float(row["median_peak_mb"]) for row in subset],
            color=color,
            marker="o",
            label=METHOD_LABEL[method],
        )
    axis.set_xlabel("Simulated calibration routes")
    axis.set_ylabel("Median peak Python-tracked MB")
    axis.set_title("tracemalloc peak, separate from the timing repeats")
    axis.legend()
    _save(figure, output, plt)


def plot_fair_bandings(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """Median runtime of the pre-specified LSH bandings and the streaming exact baseline."""
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7.2, 4.6))
    methods = []
    for row in rows:
        method = str(row["method"])
        if method not in methods and method != "materialized_exact":
            methods.append(method)
    colors = ["#377eb8", "#e41a1c", "#984ea3", "#ff7f00", "#a65628", "#4daf4a"]
    for index, method in enumerate(methods):
        subset = sorted(
            (row for row in rows if row["method"] == method),
            key=lambda row: int(row["n_routes"]),
        )
        axis.plot(
            [int(row["n_routes"]) for row in subset],
            [float(row["median_seconds"]) for row in subset],
            color=colors[index % len(colors)],
            marker="o",
            label=str(subset[0].get("label") or method),
        )
    axis.set_xlabel("Simulated calibration routes")
    axis.set_ylabel("Median end-to-end seconds")
    axis.set_title("Pre-specified bandings, not tuned on held-out coverage")
    axis.legend(fontsize=8)
    _save(figure, output, plt)


def plot_fair_stages(rows: Sequence[Mapping[str, object]], output: Path) -> None:
    """One elapsed-time stage pass at the largest route count. Not a tracemalloc run."""
    import matplotlib.pyplot as plt

    largest = max(int(row["n_routes"]) for row in rows)
    chosen = [row for row in rows if int(row["n_routes"]) == largest]
    figure, axes = plt.subplots(1, len(chosen), figsize=(3.1 * len(chosen), 4.2), sharey=False)
    if len(chosen) == 1:
        axes = [axes]
    for axis, row in zip(axes, chosen, strict=True):
        labels = [part.strip() for part in str(row["stage_names"]).split("|")]
        values = [float(part) for part in str(row["stage_seconds"]).split("|")]
        axis.barh(labels[::-1], values[::-1], color=METHOD_COLOR.get(str(row["method"]), "#666666"))
        axis.set_xlabel("Seconds")
        axis.set_title(str(row["label"]))
    figure.suptitle(f"Stage times, {largest} simulated routes", fontsize=11)
    _save(figure, output, plt)


def _roles(rows: Sequence[Mapping[str, object]]) -> list[str]:
    roles: list[str] = []
    for row in rows:
        role = str(row["role"])
        if role not in roles:
            roles.append(role)
    return roles


def _role_label(role: str) -> str:
    return role.replace("_", " ")


def _value(rows: Sequence[Mapping[str, object]], scenario: str, role: str, key: str) -> float:
    matches = [row for row in rows if row["scenario"] == scenario and row["role"] == role]
    if len(matches) != 1:
        raise ValueError(f"expected one {scenario} row for {role}")
    return float(matches[0][key])
