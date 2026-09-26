"""Causal graph data models — nodes, edges, graph container, and analysis
results (Bottleneck, WhatIfResult).

All models extend ``ContractModel`` for strict serialization (no undeclared
fields).  ``CausalGraph`` is the central runtime object; algorithms in other
modules consume it via the public methods and produce ``Bottleneck`` /
``WhatIfResult`` lists.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import NonNegativeInt

from kylinbootlab.contracts import ContractModel


class CausalNode(ContractModel):
    """One node in the causal graph — a unit or a readiness milestone."""

    name: str
    blame_ns: NonNegativeInt = 0
    earliest_ns: NonNegativeInt | None = None
    latest_ns: NonNegativeInt | None = None
    layer: Literal["systemd", "readiness"]


class CausalEdge(ContractModel):
    """Directed dependency edge between two nodes."""

    source: str
    target: str
    kind: Literal["after", "wants", "requires", "readiness_gate"]
    weight_ns: NonNegativeInt = 0


class CausalGraph:
    """Immutable-in-practice directed graph of ``CausalNode`` / ``CausalEdge``.

    Algorithms read the graph; mutation happens during building only.  The
    graph is serializable to/from a plain dict via ``to_json_dict`` /
    ``from_json_dict``.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, CausalNode] = {}
        self.edges: list[CausalEdge] = []

    # -- mutation (builder phase) --

    def add_node(self, node: CausalNode) -> None:
        self.nodes[node.name] = node

    def add_edge(self, edge: CausalEdge) -> None:
        # Ensure both endpoints exist as nodes (default layer=systemd)
        for name in (edge.source, edge.target):
            if name not in self.nodes:
                self.nodes[name] = CausalNode(name=name, layer="systemd")
        self.edges.append(edge)

    # -- query --

    def sources(self) -> list[str]:
        """Nodes with zero incoming edges."""
        targets = {e.target for e in self.edges}
        return [n for n in self.nodes if n not in targets]

    def predecessors(self, name: str) -> list[str]:
        return [e.source for e in self.edges if e.target == name]

    def successors(self, name: str) -> list[str]:
        return [e.target for e in self.edges if e.source == name]

    # -- serialization --

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "nodes": {name: n.model_dump() for name, n in self.nodes.items()},
            "edges": [e.model_dump() for e in self.edges],
        }

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> CausalGraph:
        g = cls()
        for name, node_d in d.get("nodes", {}).items():
            g.nodes[name] = CausalNode.model_validate(node_d)
        for edge_d in d.get("edges", []):
            g.edges.append(CausalEdge.model_validate(edge_d))
        return g


class Bottleneck(ContractModel):
    """Ranked bottleneck with score, slack, and optional evidence string."""

    rank: int
    node: str
    blame_ns: NonNegativeInt
    slack_ns: NonNegativeInt
    on_critical_path: bool
    score: float
    evidence: str | None = None


class WhatIfResult(ContractModel):
    """Result of a single what-if edit operation."""

    action: str
    predicted_gain_ns: int
    upper_bound_ns: int
    affected_nodes: list[str]
    degenerates_to_same_path: bool = False
    note: str | None = None
