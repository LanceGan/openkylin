"""Critical-path + slack on CausalGraph — topological DP, O(V+E).

Safe on the real 333-node / 1651-edge systemd DOT graph where DFS
path enumeration is exponential.
"""
from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def _topo_order(graph: CausalGraph, sink: str) -> list[str]:
    """Nodes that can reach *sink*, in topological order (sources first)."""
    pred: dict[str, list[str]] = {n: [] for n in graph.nodes}
    for e in graph.edges:
        if e.target in pred and e.source in pred:
            pred[e.target].append(e.source)

    reachable: set[str] = set()
    q = deque([sink])
    while q:
        v = q.popleft()
        if v in reachable:
            continue
        reachable.add(v)
        for p in pred.get(v, []):
            if p not in reachable:
                q.append(p)

    indeg = {v: 0 for v in reachable}
    for e in graph.edges:
        if e.source in reachable and e.target in reachable:
            indeg[e.target] += 1

    order: list[str] = []
    q2 = deque(v for v, d in indeg.items() if d == 0)
    while q2:
        v = q2.popleft()
        order.append(v)
        for e in graph.edges:
            if e.source == v and e.target in indeg:
                indeg[e.target] -= 1
                if indeg[e.target] == 0:
                    q2.append(e.target)
    return order


def _forward_dp(
    graph: CausalGraph, order: list[str],
) -> tuple[dict[str, int], dict[str, str | None]]:
    """dist[v] = max blame-sum from sources TO v (NOT including v)."""
    dist: dict[str, int] = {v: 0 for v in order}
    prev: dict[str, str | None] = {v: None for v in order}
    for v in order:
        cand = dist[v] + graph.nodes[v].blame_ns
        for e in graph.edges:
            if e.source == v and e.target in dist and cand > dist[e.target]:
                dist[e.target] = cand
                prev[e.target] = v
    return dist, prev


def _cp_length(graph: CausalGraph, sink: str) -> int:
    order = _topo_order(graph, sink)
    if sink not in order:
        return 0
    dist, _ = _forward_dp(graph, order)
    return dist.get(sink, 0) + graph.nodes[sink].blame_ns


def critical_path(graph: CausalGraph, sink: str = "usable") -> list[str]:
    if not graph.nodes:
        raise ValueError("empty graph")
    if sink not in graph.nodes:
        raise ValueError(f"sink '{sink}' not reachable in graph")

    order = _topo_order(graph, sink)
    if sink not in order:
        raise ValueError(f"no path to sink '{sink}'")

    dist, prev = _forward_dp(graph, order)
    path: list[str] = []
    cur: str | None = sink
    while cur is not None:
        path.append(cur)
        cur = prev.get(cur)
    path.reverse()
    return path


def slack(graph: CausalGraph, node_name: str, sink: str = "usable") -> int:
    if node_name not in graph.nodes:
        raise KeyError(node_name)

    order = _topo_order(graph, sink)
    dist, _ = _forward_dp(graph, order)

    # rdist_full[v] = blame[v] + max(rdist_full[w] for w in successors(v))
    rdist_full: dict[str, int] = {v: 0 for v in graph.nodes}
    for v in reversed(order):
        rdist_full[v] = graph.nodes[v].blame_ns
        best = 0
        for e in graph.edges:
            if e.source == v and e.target in rdist_full:
                best = max(best, rdist_full[e.target])
        rdist_full[v] += best

    cp_len = _cp_length(graph, sink)
    max_through = dist.get(node_name, 0) + rdist_full.get(node_name, 0)
    return max(0, cp_len - max_through)
