"""Tests for critical_path() and slack() algorithms."""

import pytest

from kylinbootlab.analysis.critical_path import critical_path, slack
from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, CausalNode


def _make_test_graph(spec: list[tuple[str, str, int]]) -> CausalGraph:
    """Build a graph from (source, target, blame_ns) tuples.  blame_ns
    is applied to *target* — sources get 0 by default."""
    g = CausalGraph()
    blame: dict[str, int] = {}
    for src, tgt, b in spec:
        g.add_edge(CausalEdge(source=src, target=tgt, kind="after"))
        blame[tgt] = b
        if src not in blame:
            blame[src] = 0
        # ensure both nodes exist with blame
    for name in g.nodes:
        g.nodes[name].blame_ns = blame.get(name, 0)
    return g


class TestCriticalPath:
    def test_single_path_graph(self) -> None:
        g = _make_test_graph([
            ("a", "b", 100),
            ("b", "c", 200),
            ("c", "usable", 300),
        ])
        g.nodes["a"].blame_ns = 50
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        cp = critical_path(g)
        assert cp == ["a", "b", "c", "usable"]

    def test_fork_where_one_side_longer(self) -> None:
        g = _make_test_graph([
            ("src", "short", 100),
            ("src", "long", 500),
            ("short", "usable", 0),
            ("long", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 10
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        cp = critical_path(g)
        assert "long" in cp
        assert "short" not in cp

    def test_fork_both_equal_takes_first_found(self) -> None:
        g = _make_test_graph([
            ("src", "path_a", 300),
            ("src", "path_b", 300),
            ("path_a", "usable", 0),
            ("path_b", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 100
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        cp = critical_path(g)
        # Either path_a or path_b should be chosen; both have same sum
        # Graph has 4 nodes but any single path traverses only 3.
        assert len(cp) == 3
        assert cp[0] == "src"
        assert cp[-1] == "usable"

    def test_sink_not_reachable_raises_valueerror(self) -> None:
        g = _make_test_graph([("a", "b", 100)])
        with pytest.raises(ValueError, match="reachable"):
            critical_path(g, sink="usable")

    def test_empty_graph_raises_valueerror(self) -> None:
        g = CausalGraph()
        with pytest.raises(ValueError, match="empty"):
            critical_path(g)

    def test_sink_as_only_node_returns_sink(self) -> None:
        g = CausalGraph()
        g.add_node(CausalNode(name="usable", blame_ns=42, layer="readiness"))
        cp = critical_path(g)
        assert cp == ["usable"]

    def test_smoke_with_real_data_structure(self) -> None:
        """Smoke test: a dot-like graph where cp contains longest blame-sum path."""
        g = _make_test_graph([
            ("basic.target", "sysinit.target", 0),
            ("sysinit.target", "dbus.service", 500),
            ("dbus.service", "NetworkManager.service", 3_129_000_000),
            ("NetworkManager.service", "graphical.target", 0),
            ("sysinit.target", "systemd-udevd.service", 50_000_000),
            ("systemd-udevd.service", "graphical.target", 0),
            ("basic.target", "local-fs.target", 120_000_000),
            ("local-fs.target", "sysinit.target", 0),
        ])
        g.nodes["basic.target"].blame_ns = 0
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        g.add_edge(CausalEdge(source="graphical.target", target="usable", kind="after"))
        cp = critical_path(g)
        assert "NetworkManager.service" in cp
        assert "systemd-udevd.service" not in cp


class TestSlack:
    def test_slack_of_node_on_cp_is_zero(self) -> None:
        g = _make_test_graph([
            ("a", "b", 300),
            ("b", "c", 200),
            ("c", "usable", 100),
        ])
        g.nodes["a"].blame_ns = 50
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        assert slack(g, "b", sink="usable") == 0

    def test_slack_of_node_off_cp_is_positive(self) -> None:
        g = _make_test_graph([
            ("src", "slow", 600),
            ("src", "fast", 100),
            ("slow", "usable", 0),
            ("fast", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 10
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        assert slack(g, "fast", sink="usable") > 0

    def test_slack_nonnegative(self) -> None:
        g = _make_test_graph([
            ("a", "b", 500),
            ("b", "usable", 0),
        ])
        g.nodes["a"].blame_ns = 0
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        assert slack(g, "a", sink="usable") >= 0

    def test_node_not_in_graph_raises_keyerror(self) -> None:
        g = _make_test_graph([("a", "b", 100)])
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        g.add_edge(CausalEdge(source="b", target="usable", kind="after"))
        with pytest.raises(KeyError, match="nonexistent"):
            slack(g, "nonexistent")

    def test_slack_equals_cp_minus_max_path_through(self) -> None:
        """Verify the slack invariant: slack(n) == cp_len - max_path_through(n)."""
        g = _make_test_graph([
            ("x", "a", 100),
            ("x", "b", 500),
            ("a", "y", 200),
            ("b", "y", 300),
            ("y", "usable", 100),
        ])
        g.nodes["x"].blame_ns = 10
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        # cp: x(10) -> b(500) -> y(100) -> usable(0) = 610
        # path through a: x(10) -> a(100) -> y(100) -> usable(0) = 210
        # slack("a") = 610 - 210 = 400
        s = slack(g, "a")
        assert s == 400
