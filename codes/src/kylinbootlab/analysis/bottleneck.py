"""Bottleneck ranking engine.

Scores nodes by ``blame_ns * slack_penalty * criticality`` and returns
the top-k as ``Bottleneck`` records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kylinbootlab.analysis.critical_path import slack
from kylinbootlab.analysis.graph import Bottleneck

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def rank_bottlenecks(
    graph: CausalGraph,
    sink: str = "usable",
    top_k: int = 10,
    total_runs: int = 1,
    on_cp_nodes: list[str] | None = None,
) -> list[Bottleneck]:
    """Rank nodes by bottleneck score, returning top *k*.

    Score formula (spec §5.3):

        score = blame_ns * (1.0 / (1.0 + slack_ns / 1e9)) * (count_on_cp / total_runs)

    Sort descending by score, then by blame_ns descending, then stable
    by node-insertion order.
    """
    if not graph.nodes or sink not in graph.nodes:
        return []

    cp_nodes = on_cp_nodes
    if cp_nodes is None:
        from kylinbootlab.analysis.critical_path import critical_path as cp_fn

        cp_nodes = cp_fn(graph, sink=sink)

    scored: list[tuple[str, float, int, bool]] = []
    for name, node in graph.nodes.items():
        if name == sink:
            continue
        s = slack(graph, name, sink=sink)
        slack_penalty = 1.0 / (1.0 + s / 1_000_000_000)
        criticality = 1.0 if name in cp_nodes else 0.0
        if total_runs > 1:
            criticality = float(cp_nodes.count(name)) / total_runs
        score = node.blame_ns * slack_penalty * criticality
        on_cp = name in cp_nodes
        scored.append((name, score, node.blame_ns, on_cp))

    # Sort: primary score desc, secondary blame_ns desc, tertiary stable
    scored.sort(key=lambda x: (-x[1], -x[2]))

    results: list[Bottleneck] = []
    for rank, (name, score_val, blame, on_cp) in enumerate(scored[:top_k], start=1):
        s = slack(graph, name, sink=sink)
        evidence_parts = [f"slack={s}{'ns' if s > 0 else ''}"]
        if on_cp:
            evidence_parts.append(f"on critical path ({total_runs} run(s))")
        results.append(
            Bottleneck(
                rank=rank,
                node=name,
                blame_ns=blame,
                slack_ns=s,
                on_critical_path=on_cp,
                score=round(score_val, 4),
                evidence="; ".join(evidence_parts),
            )
        )
    return results
