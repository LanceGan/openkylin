"""What-If Simulator — edit-and-recompute critical path.

Copies the graph, applies a single edit action (remove_edge or
reduce_blame), recomputes the critical path, and reports the gain.
The gain is an *upper bound* — real-world improvement may be less.
"""

from __future__ import annotations

from typing import Any

from kylinbootlab.analysis.graph import CausalGraph, WhatIfResult


class WhatIfSimulator:
    """Simulate graph edits and predict their effect on critical path.

    Each call to ``simulate()`` creates a fresh copy of the graph, applies
    one edit, and recomputes the critical path.
    """

    def __init__(self, graph: CausalGraph) -> None:
        self._graph = graph

    def simulate(self, action: dict[str, Any]) -> WhatIfResult:
        """Apply *action* to a copy of the graph and return the predicted gain.

        Actions:
            ``{"kind": "remove_edge", "source": str, "target": str}``
            ``{"kind": "reduce_blame", "node": str, "pct": float}``

        Returns:
            WhatIfResult with ``predicted_gain_ns`` (negative = improvement),
            ``degenerates_to_same_path`` if cp did not change, and ``action``
            describing the edit.
        """
        from kylinbootlab.analysis.critical_path import critical_path as cp_fn

        g_copy = self._copy_graph()
        kind = action["kind"]

        # Compute old cp on the *original* graph
        old_cp = cp_fn(self._graph)
        old_len = sum(self._graph.nodes[n].blame_ns for n in old_cp)

        action_desc = ""
        if kind == "remove_edge":
            src = action["source"]
            tgt = action["target"]
            g_copy.edges = [
                e
                for e in g_copy.edges
                if not (e.source == src and e.target == tgt)
            ]
            action_desc = f"remove_edge({src}, {tgt})"
        elif kind == "reduce_blame":
            node = action["node"]
            pct = action["pct"]
            if node in g_copy.nodes:
                g_copy.nodes[node].blame_ns = int(
                    g_copy.nodes[node].blame_ns * (1.0 - pct / 100.0)
                )
            action_desc = f"reduce_blame({node}, {pct}%)"
        else:
            raise ValueError(f"Unknown action kind: {kind}")

        # Recompute cp on edited copy
        new_cp = cp_fn(g_copy)
        new_len = sum(g_copy.nodes[n].blame_ns for n in new_cp)
        gain = new_len - old_len  # negative = shorter cp = improvement

        degenerates = (set(new_cp) == set(old_cp)) and (gain == 0)

        return WhatIfResult(
            action=action_desc,
            predicted_gain_ns=gain,
            upper_bound_ns=0,  # per spec: removal cannot harm; reduction cannot harm
            affected_nodes=[n for n in new_cp if n not in old_cp],
            degenerates_to_same_path=degenerates,
        )

    def _copy_graph(self) -> CausalGraph:
        """Deep-copy the graph (nodes + edges) so edits are isolated."""
        g = CausalGraph()
        for name, node in self._graph.nodes.items():
            g.nodes[name] = node.model_copy(deep=True)
        for edge in self._graph.edges:
            g.edges.append(edge.model_copy(deep=True))
        return g
