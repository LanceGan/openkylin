"""Tests for CausalNode, CausalEdge, CausalGraph, Bottleneck, WhatIfResult."""

import pytest
from pydantic import ValidationError

from kylinbootlab.analysis.graph import (
    Bottleneck,
    CausalEdge,
    CausalGraph,
    CausalNode,
    WhatIfResult,
)


class TestCausalNode:
    def test_minimal_node_construction(self) -> None:
        n = CausalNode(name="dbus.service", layer="systemd")
        assert n.name == "dbus.service"
        assert n.blame_ns == 0
        assert n.layer == "systemd"
        assert n.earliest_ns is None
        assert n.latest_ns is None

    def test_full_node_construction(self) -> None:
        n = CausalNode(
            name="NetworkManager.service",
            blame_ns=1_500_000_000,
            earliest_ns=6_000_000_000,
            latest_ns=7_500_000_000,
            layer="systemd",
        )
        assert n.blame_ns == 1_500_000_000
        assert n.latest_ns == 7_500_000_000

    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            CausalNode.model_validate({"name": "a", "layer": "systemd", "bogus": 1})

    def test_layer_must_be_systemd_or_readiness(self) -> None:
        with pytest.raises(ValidationError):
            CausalNode(name="a", layer="kernel")


class TestCausalEdge:
    def test_minimal_edge(self) -> None:
        e = CausalEdge(source="a", target="b", kind="after")
        assert e.weight_ns == 0

    def test_rejects_bad_kind(self) -> None:
        with pytest.raises(ValidationError):
            CausalEdge(source="a", target="b", kind="bogus")


class TestCausalGraph:
    def test_add_node_and_retrieve(self) -> None:
        g = CausalGraph()
        g.add_node(CausalNode(name="a", layer="systemd"))
        assert g.nodes["a"].name == "a"

    def test_add_edge_adds_implied_nodes(self) -> None:
        g = CausalGraph()
        g.add_edge(CausalEdge(source="a", target="b", kind="after"))
        assert len(g.edges) == 1
        assert g.edges[0].source == "a"

    def test_sources_returns_zero_indegree_nodes(self) -> None:
        g = CausalGraph()
        g.add_node(CausalNode(name="a", layer="systemd"))
        g.add_node(CausalNode(name="b", layer="systemd"))
        g.add_node(CausalNode(name="c", layer="systemd"))
        g.add_edge(CausalEdge(source="a", target="c", kind="after"))
        g.add_edge(CausalEdge(source="b", target="c", kind="after"))
        sources = g.sources()
        assert set(sources) == {"a", "b"}

    def test_predecessors_and_successors(self) -> None:
        g = CausalGraph()
        g.add_edge(CausalEdge(source="a", target="b", kind="after"))
        g.add_edge(CausalEdge(source="b", target="c", kind="after"))
        g.add_edge(CausalEdge(source="a", target="c", kind="after"))
        assert g.successors("a") == ["b", "c"]
        assert g.predecessors("c") == ["b", "a"]

    def test_to_json_roundtrip(self) -> None:
        g = CausalGraph()
        g.add_node(CausalNode(name="dbus", blame_ns=500_000_000, layer="systemd"))
        g.add_node(CausalNode(name="NM", blame_ns=1_000_000_000, layer="systemd"))
        g.add_edge(CausalEdge(source="dbus", target="NM", kind="after"))
        d = g.to_json_dict()
        g2 = CausalGraph.from_json_dict(d)
        assert g2.nodes["dbus"].blame_ns == 500_000_000
        assert len(g2.edges) == 1
        assert g2.edges[0].source == "dbus"


class TestBottleneck:
    def test_minimal_bottleneck(self) -> None:
        b = Bottleneck(rank=1, node="dbus", blame_ns=500, slack_ns=0, on_critical_path=True, score=0.95)
        assert b.evidence is None

    def test_bottleneck_with_evidence(self) -> None:
        b = Bottleneck(
            rank=1, node="dbus", blame_ns=500, slack_ns=0,
            on_critical_path=True, score=0.95,
            evidence="slack=0; on critical path 10/10 runs",
        )
        assert "10/10" in (b.evidence or "")


class TestWhatIfResult:
    def test_minimal_result(self) -> None:
        r = WhatIfResult(
            action="remove_edge(a,b)",
            predicted_gain_ns=-500,
            upper_bound_ns=0,
            affected_nodes=["b"],
        )
        assert r.degenerates_to_same_path is False
        assert r.note is None
