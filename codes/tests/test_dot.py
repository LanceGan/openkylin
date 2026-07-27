"""Tests for DOT parser — systemd-analyze dot output format."""

import pytest

from kylinbootlab.analysis.dot import parse_dot

# --- Sample DOT fixtures ---

SIMPLE_DOT = """\
digraph systemd {
    "basic.target"->"sysinit.target" [color="green"];
    "sysinit.target"->"dbus.service" [color="green"];
    "dbus.service"->"NetworkManager.service" [color="red"];
}
"""

DOT_WITH_ATTRS = """\
strict digraph systemd {
    "basic.target" [shape=ellipse, label="basic"];
    "basic.target"->"sysinit.target" [color="green", weight=1];
    "NetworkManager.service" [shape=box, label="NM"];
}
"""

DOT_WITH_COMMENTS = """\
digraph systemd {
    // This is a comment
    "a.service"->"b.service" [color="green"];
    /* multi-line
       comment */
    "b.service"->"c.service" [color="red"];
}
"""

DOT_SELF_LOOP = """\
digraph systemd {
    "a.service"->"a.service" [color="green"];
}
"""

DOT_DUPLICATE_EDGES = """\
digraph systemd {
    "a.service"->"b.service" [color="green"];
    "a.service"->"b.service" [color="red"];
}
"""

EMPTY_DOT = "digraph systemd {\n}\n"


def test_parse_simple_dot_extracts_nodes_and_edges() -> None:
    g = parse_dot(SIMPLE_DOT)
    assert g.nodes == {"basic.target", "sysinit.target", "dbus.service", "NetworkManager.service"}
    assert ("basic.target", "sysinit.target") in g.edges
    assert ("sysinit.target", "dbus.service") in g.edges
    assert ("dbus.service", "NetworkManager.service") in g.edges
    assert len(g.edges) == 3


def test_parse_dot_detects_strict() -> None:
    g = parse_dot(DOT_WITH_ATTRS)
    assert g.strict is True
    g2 = parse_dot(SIMPLE_DOT)
    assert g2.strict is False


def test_parse_dot_extracts_node_attributes() -> None:
    g = parse_dot(DOT_WITH_ATTRS)
    assert g.node_attrs["basic.target"] == {"shape": "ellipse", "label": "basic"}
    assert g.node_attrs["NetworkManager.service"] == {"shape": "box", "label": "NM"}
    assert "sysinit.target" not in g.node_attrs  # no attrs declared


def test_parse_dot_strips_comments() -> None:
    g = parse_dot(DOT_WITH_COMMENTS)
    assert "a.service" in g.nodes
    assert "b.service" in g.nodes
    assert "c.service" in g.nodes
    assert len(g.edges) == 2
    # comments should not appear as nodes
    assert "This" not in g.nodes
    assert "multi" not in g.nodes


def test_parse_dot_handles_self_loop() -> None:
    g = parse_dot(DOT_SELF_LOOP)
    assert g.nodes == {"a.service"}
    assert ("a.service", "a.service") in g.edges
    assert len(g.edges) == 1


def test_parse_dot_deduplicates_edges() -> None:
    g = parse_dot(DOT_DUPLICATE_EDGES)
    assert len(g.edges) == 1
    assert ("a.service", "b.service") in g.edges


def test_parse_empty_dot() -> None:
    g = parse_dot(EMPTY_DOT)
    assert g.nodes == set()
    assert g.edges == []
    assert g.node_attrs == {}


def test_parse_dot_ignores_graph_attributes() -> None:
    dot = 'digraph systemd {\n    rankdir=LR;\n    "a.service"->"b.service";\n}\n'
    g = parse_dot(dot)
    assert g.nodes == {"a.service", "b.service"}
    assert len(g.edges) == 1


def test_parse_dot_handles_quoted_labels() -> None:
    dot = 'digraph systemd {\n    "a.service" [label="Service \\"A\\""];\n}\n'
    g = parse_dot(dot)
    assert g.node_attrs["a.service"]["label"] == 'Service "A"'


def test_parse_dot_isolated_nodes_no_edges() -> None:
    dot = 'digraph systemd {\n    "a.service";\n    "b.service";\n    "c.service" [shape=box];\n}\n'
    g = parse_dot(dot)
    assert g.nodes == {"a.service", "b.service", "c.service"}
    assert g.edges == []


def test_malformed_dot_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="digraph"):
        parse_dot("not a digraph at all")


def test_dot_missing_closing_brace_raises_valueerror() -> None:
    with pytest.raises(ValueError, match="closing"):
        parse_dot("digraph systemd {\n    \"a\"->\"b\";\n")


def test_dot_with_tabs_and_crlf() -> None:
    dot = "digraph systemd {\r\n\t\"a.service\"->\"b.service\" [color=\"green\"];\r\n}\r\n"
    g = parse_dot(dot)
    assert ("a.service", "b.service") in g.edges


def test_parse_dot_order_preserves_edge_order() -> None:
    """Edges should appear in insertion order for reproducibility."""
    dot = """digraph systemd {
    "c"->"d";
    "a"->"b";
    "e"->"f";
}
"""
    g = parse_dot(dot)
    assert g.edges[0] == ("c", "d")
    assert g.edges[1] == ("a", "b")
    assert g.edges[2] == ("e", "f")


def test_dotgraph_from_real_recon_snippet() -> None:
    """Smoke test: a 20-edge snippet from the actual 1651-edge recon DOT."""
    dot = """\
strict digraph systemd {
    "basic.target"->"sysinit.target";
    "sysinit.target"->"local-fs.target";
    "sysinit.target"->"swap.target";
    "local-fs.target"->"var.mount";
    "sysinit.target"->"dbus.socket";
    "dbus.socket"->"dbus.service";
    "dbus.service"->"NetworkManager.service";
    "NetworkManager.service"->"NetworkManager-wait-online.service";
    "sysinit.target"->"systemd-journald.service";
    "systemd-journald.service"->"systemd-tmpfiles-setup.service";
    "sysinit.target"->"systemd-udevd.service";
    "systemd-udevd.service"->"systemd-udev-trigger.service";
    "multi-user.target"->"lightdm.service";
    "lightdm.service"->"graphical.target";
    "dbus.service"->"udisks2.service";
    "dbus.service"->"upower.service";
    "dbus.service"->"accounts-daemon.service";
    "dbus.service"->"polkit.service";
    "sysinit.target"->"systemd-resolved.service";
    "NetworkManager.service"->"wpa_supplicant.service";
}
"""
    g = parse_dot(dot)
    assert len(g.nodes) == 22
    assert len(g.edges) == 20
    assert g.strict is True
    assert "graphical.target" in g.nodes
    assert "basic.target" in g.nodes
    # leaf nodes
    assert "var.mount" in g.nodes
    assert "wpa_supplicant.service" in g.nodes
