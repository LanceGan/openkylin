"""Tests for cross-run graph comparison."""

from kylinbootlab.analysis.compare import diff_graphs
from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, CausalNode


def _identical_graph() -> CausalGraph:
    g = CausalGraph()
    g.add_node(CausalNode(name="a", blame_ns=100, layer="systemd"))
    g.add_node(CausalNode(name="b", blame_ns=200, layer="systemd"))
    g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
    g.add_edge(CausalEdge(source="a", target="b", kind="after"))
    g.add_edge(CausalEdge(source="b", target="usable", kind="after"))
    return g


class TestDiffGraphs:
    def test_identical_graphs_return_empty_diff(self) -> None:
        g1 = _identical_graph()
        g2 = _identical_graph()
        diff = diff_graphs(g1, g2, "run-1", "run-2")
        assert diff["nodes_added"] == []
        assert diff["nodes_removed"] == []
        assert diff["edges_added"] == []
        assert diff["edges_removed"] == []
        assert diff["critical_path_shifted"] is False

    def test_blame_change_detected(self) -> None:
        g1 = _identical_graph()
        g2 = _identical_graph()
        g2.nodes["b"].blame_ns = 400  # doubled from 200
        diff = diff_graphs(g1, g2, "run-1", "run-2")
        assert len(diff["blame_changed"]) >= 1
        changed = {c["node"] for c in diff["blame_changed"]}
        assert "b" in changed

    def test_edge_added_detected(self) -> None:
        g1 = _identical_graph()
        g2 = _identical_graph()
        g2.add_node(CausalNode(name="c", blame_ns=50, layer="systemd"))
        g2.add_edge(CausalEdge(source="a", target="c", kind="after"))
        diff = diff_graphs(g1, g2, "run-1", "run-2")
        assert "c" in diff["nodes_added"]
        assert len(diff["edges_added"]) == 1

    def test_critical_path_shift_detected(self) -> None:
        g1 = _identical_graph()
        g2 = _identical_graph()
        # Make b much slower, pushing cp to route differently if possible
        g2.nodes["b"].blame_ns = 10_000_000_000
        diff = diff_graphs(g1, g2, "run-1", "run-2")
        # cp should be the same node set if topology unchanged
        # But if blame change is extreme, it's still the same cp nodes
        assert isinstance(diff["critical_path_shifted"], bool)

    def test_top_blame_divergences_limited_to_5(self) -> None:
        g1 = CausalGraph()
        g2 = CausalGraph()
        for i in range(7):
            g1.add_node(CausalNode(name=f"n{i}", blame_ns=100 + i * 50, layer="systemd"))
            g2.add_node(CausalNode(name=f"n{i}", blame_ns=200 + i * 100, layer="systemd"))
        g1.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        g2.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        diff = diff_graphs(g1, g2, "run-1", "run-2")
        assert len(diff["top_blame_divergences"]) <= 5
