"""Critical path and slack algorithms on ``CausalGraph``.

- ``critical_path(graph, sink)`` — longest blame-sum path from sources to sink.
- ``slack(graph, node, sink)`` — nanoseconds the node can slip without
  delaying the sink.

Both are pure functions: no side effects, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def _all_paths_from_sources(
    graph: CausalGraph,
    sink: str,
) -> list[list[str]]:
    """DFS-enumerate every path from any source node to *sink*.

    Sources are nodes with zero in-edges.  Returns list of paths where
    each path is a list of node names in traversal order.
    """
    sources = graph.sources()
    if not sources:
        # Graph with no sources: if the sink itself is a node, return single-node path
        if sink in graph.nodes:
            return [[sink]]
        return []

    all_paths: list[list[str]] = []

    def dfs(current: str, visited: list[str]) -> None:
        if current == sink:
            all_paths.append(list(visited))
            return
        for succ in graph.successors(current):
            if succ not in visited:  # avoid cycles
                visited.append(succ)
                dfs(succ, visited)
                visited.pop()

    for src in sources:
        dfs(src, [src])

    return all_paths


def _path_blame_sum(graph: CausalGraph, path: list[str]) -> int:
    """Sum of blame_ns for every node in the path."""
    return sum(graph.nodes[n].blame_ns for n in path)


def _cp_length(graph: CausalGraph, sink: str) -> int:
    """Return total blame_ns of the critical path (longest blame-sum)."""
    paths = _all_paths_from_sources(graph, sink)
    if not paths:
        raise ValueError(f"No path to sink '{sink}' found — sink may not be reachable")
    return max(_path_blame_sum(graph, p) for p in paths)


def critical_path(graph: CausalGraph, sink: str = "usable") -> list[str]:
    """Return node names along the longest blame-sum path to *sink*.

    DFS enumerates all source-to-sink paths.  Ties are broken by first
    found (insertion-order stable through ``graph.successors``).

    Raises:
        ValueError: If the graph has no nodes or no path reaches *sink*.
    """
    if not graph.nodes:
        raise ValueError("Cannot compute critical path on an empty graph")

    paths = _all_paths_from_sources(graph, sink)
    if not paths:
        raise ValueError(f"No path to sink '{sink}' found — sink may not be reachable")

    best_path: list[str] = paths[0]
    best_len = _path_blame_sum(graph, best_path)
    for p in paths[1:]:
        length = _path_blame_sum(graph, p)
        if length > best_len:
            best_len = length
            best_path = p[:]
    return best_path


def slack(graph: CausalGraph, node_name: str, sink: str = "usable") -> int:
    """Nanoseconds *node_name* can slip without delaying *sink*.

    ``slack = critical_path_length - max_blame_sum_through(node_name)``.
    Always non-negative; zero means the node is on at least one critical
    path.

    Raises:
        KeyError: If *node_name* is not in the graph.
        ValueError: If no path reaches *sink*.
    """
    if node_name not in graph.nodes:
        raise KeyError(f"Node '{node_name}' is not present in the graph")

    cp_len = _cp_length(graph, sink)
    paths = _all_paths_from_sources(graph, sink)
    max_through = 0
    for p in paths:
        if node_name in p:
            max_through = max(max_through, _path_blame_sum(graph, p))
    return cp_len - max_through
