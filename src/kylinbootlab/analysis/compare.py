"""Cross-run graph comparison — detect structural and blame changes
between two ``CausalGraph`` instances from different boot runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def diff_graphs(
    graph_a: CausalGraph,
    graph_b: CausalGraph,
    run_a_id: str,
    run_b_id: str,
) -> dict[str, Any]:
    """Compare two causal graphs and return a structured diff dict.

    Returns dict with keys: run_a, run_b, nodes_added, nodes_removed,
    edges_added, edges_removed, blame_changed, critical_path_shifted,
    new_bottlenecks, top_blame_divergences.
    """
    from kylinbootlab.analysis.critical_path import critical_path as cp_fn

    nodes_a = set(graph_a.nodes.keys())
    nodes_b = set(graph_b.nodes.keys())

    nodes_added = sorted(nodes_b - nodes_a)
    nodes_removed = sorted(nodes_a - nodes_b)

    # Edges: compare as sets of (source, target)
    edges_a = {(e.source, e.target) for e in graph_a.edges}
    edges_b = {(e.source, e.target) for e in graph_b.edges}
    edges_added = sorted(edges_b - edges_a)
    edges_removed = sorted(edges_a - edges_b)

    # Blame changes (>10% relative delta)
    blame_changed: list[dict[str, Any]] = []
    for name in nodes_a & nodes_b:
        ba = graph_a.nodes[name].blame_ns
        bb = graph_b.nodes[name].blame_ns
        if ba == 0 and bb == 0:
            continue
        denom = max(ba, bb, 1)
        delta_pct = abs(bb - ba) / denom * 100.0
        if delta_pct > 10.0:
            blame_changed.append(
                {
                    "node": name,
                    "before_ns": ba,
                    "after_ns": bb,
                    "delta_pct": round(delta_pct, 2),
                }
            )
    blame_changed.sort(key=lambda x: abs(x["after_ns"] - x["before_ns"]), reverse=True)

    # Critical path comparison
    try:
        cp_a = set(cp_fn(graph_a))
        cp_b = set(cp_fn(graph_b))
        critical_path_shifted = cp_a != cp_b
        new_bottlenecks = sorted(cp_b - cp_a)
    except ValueError:
        critical_path_shifted = False
        new_bottlenecks = []

    # Top-5 blame divergences
    top_blame_divergences = blame_changed[:5]

    return {
        "run_a": run_a_id,
        "run_b": run_b_id,
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "edges_added": [(s, t) for s, t in edges_added],
        "edges_removed": [(s, t) for s, t in edges_removed],
        "blame_changed": blame_changed,
        "critical_path_shifted": critical_path_shifted,
        "new_bottlenecks": new_bottlenecks,
        "top_blame_divergences": top_blame_divergences,
    }
