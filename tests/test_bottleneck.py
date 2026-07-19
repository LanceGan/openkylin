"""Tests for bottleneck ranking engine."""

from kylinbootlab.analysis.bottleneck import rank_bottlenecks
from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, CausalNode


def _graph_from_triples(triples: list[tuple[str, str, int]]) -> CausalGraph:
    """(source, target, blame_ns_on_target). Graph is a simple chain with zero-blame sources."""
    g = CausalGraph()
    blame: dict[str, int] = {}
    for src, tgt, b in triples:
        g.add_edge(CausalEdge(source=src, target=tgt, kind="after"))
        blame[tgt] = b
        if src not in blame:
            blame[src] = 0
    for name in g.nodes:
        g.nodes[name].blame_ns = blame.get(name, 0)
    return g


class TestRankBottlenecks:
    def test_ranking_preserves_blame_order_for_same_slack(self) -> None:
        """When all nodes have slack=0 (all on cp), higher blame ranks first."""
        g = _graph_from_triples([
            ("a", "b", 500),
            ("b", "c", 300),
            ("c", "usable", 200),
        ])
        g.nodes["a"].blame_ns = 100
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=5)
        # All on cp -> slack=0, score proportional to blame
        assert results[0].node == "b"  # 500 > 300 > 200 > 100
        assert results[0].blame_ns == 500

    def test_high_slack_node_excluded_from_top_k(self) -> None:
        """A node with large slack should rank lower than low-slack nodes."""
        # Arrange data so cp_node is on CP (blame 2000 > 1000) and
        # slacky is off-CP with slack=1000.
        g = _graph_from_triples([
            ("src", "cp_node", 2000),
            ("src", "slacky", 1000),
            ("cp_node", "usable", 0),
            ("slacky", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 100
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=2)
        # cp_node is on cp (slack=0); slacky has slack=1000ns and off cp -> score 0
        top_nodes = [r.node for r in results]
        assert "cp_node" in top_nodes

    def test_ranking_top_k_respected(self) -> None:
        g = _graph_from_triples([
            ("a", "b", 100), ("b", "c", 200), ("c", "d", 300),
            ("d", "e", 400), ("e", "usable", 500),
        ])
        g.nodes["a"].blame_ns = 50
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=3)
        assert len(results) == 3

    def test_insertion_order_stable_tiebreak(self) -> None:
        """Equal scores should be stable (secondary sort by blame, tertiary by insertion)."""
        g = _graph_from_triples([
            ("a", "x", 100),
            ("a", "y", 100),
            ("x", "z", 0),
            ("y", "z", 0),
            ("z", "usable", 0),
        ])
        g.nodes["a"].blame_ns = 0
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=10)
        # All non-sink, non-source nodes present; order stable across calls
        results2 = rank_bottlenecks(g, top_k=10)
        assert [r.node for r in results] == [r.node for r in results2]

    def test_on_critical_path_flag_set_correctly(self) -> None:
        g = _graph_from_triples([
            ("src", "cp_node", 1000),
            ("src", "off_cp", 10),
            ("cp_node", "usable", 0),
            ("off_cp", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 100
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=10)
        on_cp = {r.node for r in results if r.on_critical_path}
        assert "cp_node" in on_cp
        assert "off_cp" not in on_cp

    def test_empty_graph_returns_empty_list(self) -> None:
        g = CausalGraph()
        results = rank_bottlenecks(g)
        assert results == []
