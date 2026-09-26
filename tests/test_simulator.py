"""Tests for WhatIfSimulator."""

import pytest

from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, CausalNode
from kylinbootlab.analysis.simulator import WhatIfSimulator


def _small_cp_graph() -> CausalGraph:
    g = CausalGraph()
    g.add_node(CausalNode(name="src", blame_ns=10, layer="systemd"))
    g.add_node(CausalNode(name="slow", blame_ns=500, layer="systemd"))
    g.add_node(CausalNode(name="fast", blame_ns=100, layer="systemd"))
    g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
    g.add_edge(CausalEdge(source="src", target="slow", kind="after"))
    g.add_edge(CausalEdge(source="src", target="fast", kind="after"))
    g.add_edge(CausalEdge(source="slow", target="usable", kind="after"))
    g.add_edge(CausalEdge(source="fast", target="usable", kind="after"))
    return g


class TestWhatIfSimulator:
    def test_remove_edge_shortens_cp(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        result = sim.simulate({
            "kind": "remove_edge",
            "source": "src",
            "target": "slow",
        })
        assert result.predicted_gain_ns < 0  # improvement
        assert not result.degenerates_to_same_path

    def test_reduce_blame_on_cp_node_produces_gain(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        result = sim.simulate({
            "kind": "reduce_blame",
            "node": "slow",
            "pct": 50.0,
        })
        assert result.predicted_gain_ns < 0

    def test_reduce_blame_on_non_cp_node_produces_zero_gain(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        result = sim.simulate({
            "kind": "reduce_blame",
            "node": "fast",
            "pct": 50.0,
        })
        assert result.predicted_gain_ns == 0
        assert result.degenerates_to_same_path

    def test_degenerates_to_same_path_flag(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        # Removing the fast edge shouldn't change the cp at all
        result = sim.simulate({
            "kind": "remove_edge",
            "source": "src",
            "target": "fast",
        })
        assert result.degenerates_to_same_path
        assert result.predicted_gain_ns == 0

    def test_double_remove(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        sim.simulate({"kind": "remove_edge", "source": "src", "target": "slow"})
        # Second remove on a fresh copy of the original graph
        result2 = sim.simulate({
            "kind": "remove_edge",
            "source": "src",
            "target": "fast",
        })
        # After removing fast edge from original, only src->slow->usable remains
        # (same as original CP), so gain is 0 (degenerate).
        assert result2.predicted_gain_ns <= 0

    def test_empty_graph_no_sinks_handled_gracefully(self) -> None:
        g = CausalGraph()
        g.add_node(CausalNode(name="orphan", blame_ns=100, layer="systemd"))
        sim = WhatIfSimulator(g)
        with pytest.raises(ValueError):
            sim.simulate({"kind": "reduce_blame", "node": "orphan", "pct": 10.0})

    def test_simulate_action_reported_correctly(self) -> None:
        g = _small_cp_graph()
        sim = WhatIfSimulator(g)
        result = sim.simulate({
            "kind": "remove_edge",
            "source": "src",
            "target": "slow",
        })
        assert "remove_edge" in result.action
        assert "src" in result.action
        assert "slow" in result.action
        assert result.upper_bound_ns == 0
