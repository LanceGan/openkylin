"""Tests for CausalGraphBuilder — DOT + blame + readiness -> CausalGraph."""


from kylinbootlab.analysis.builder import CausalGraphBuilder
from kylinbootlab.readiness import ReadinessEvent

# --- Fixtures ---

BASIC_DOT = """\
strict digraph systemd {
    "basic.target"->"sysinit.target";
    "sysinit.target"->"dbus.service";
    "dbus.service"->"NetworkManager.service";
    "NetworkManager.service"->"graphical.target";
}
"""

BASIC_BLAME = [
    ("dbus.service", 0.5),
    ("NetworkManager.service", 3.1),
    ("graphical.target", 0.0),
]

BASIC_READINESS = [
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 10_000_000_000, "kind": "greeter_started",
         "detail": "lightdm", "source": "journald"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 12_000_000_000, "kind": "greeter_ready",
         "detail": "ukui-greeter", "source": "journald"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 13_000_000_000, "kind": "login_injected",
         "detail": "uinput", "source": "probe"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 15_000_000_000, "kind": "session_opened",
         "detail": "kbl", "source": "journald"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 20_000_000_000, "kind": "desktop_process_up",
         "detail": "ukui-panel", "source": "probe"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 21_000_000_000, "kind": "atspi_desktop_ready",
         "detail": "3 children", "source": "atspi"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 22_000_000_000, "kind": "sentinel_launched",
         "detail": "mate-terminal", "source": "probe"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 24_000_000_000, "kind": "sentinel_window_shown",
         "detail": "mate-terminal window", "source": "atspi"}
    ),
    ReadinessEvent.model_validate(
        {"schema_version": 1, "monotonic_ns": 24_000_000_000, "kind": "usable",
         "detail": "all three", "source": "probe"}
    ),
]


def _make_unit_timing(unit: str, duration_s: float):
    """Quick UnitTiming factory.  Duration in seconds, converted to nanoseconds."""
    from kylinbootlab.systemd import UnitTiming
    return UnitTiming(rank=0, unit=unit, duration_ns=int(duration_s * 1_000_000_000))


class TestBuilderDotOnly:
    def test_dot_only_builds_graph(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame)
        assert "dbus.service" in g.nodes
        assert g.nodes["NetworkManager.service"].blame_ns == 3_100_000_000
        assert g.nodes["basic.target"].blame_ns == 0  # not in blame
        assert len(g.edges) == 4

    def test_dot_node_not_in_blame_gets_zero_blame(self) -> None:
        builder = CausalGraphBuilder()
        g = builder.build(BASIC_DOT, [])
        assert g.nodes["basic.target"].blame_ns == 0
        assert g.nodes["NetworkManager.service"].blame_ns == 0


class TestBuilderWithReadiness:
    def test_readiness_layer_nodes_added(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, BASIC_READINESS)
        assert "greeter_started" in g.nodes
        assert g.nodes["greeter_started"].layer == "readiness"
        assert g.nodes["usable"].layer == "readiness"

    def test_readiness_nodes_have_blame_as_delta_to_next(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, BASIC_READINESS)
        # greeter_started -> greeter_ready: 12-10 = 2s = 2_000_000_000 ns
        assert g.nodes["greeter_started"].blame_ns == 2_000_000_000
        # usable (last event) has blame 0
        assert g.nodes["usable"].blame_ns == 0

    def test_readiness_edges_are_readiness_gate_kind(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, BASIC_READINESS)
        readiness_edges = [e for e in g.edges if e.kind == "readiness_gate"]
        assert len(readiness_edges) >= 5

    def test_bridge_from_graphical_target_to_greeter_started(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, BASIC_READINESS)
        bridge = [
            e for e in g.edges
            if e.source == "graphical.target" and e.target == "greeter_started"
        ]
        assert len(bridge) == 1
        assert bridge[0].kind == "after"

    def test_no_readiness_events_skips_readiness_layer(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, None)
        assert "greeter_started" not in g.nodes
        assert "usable" not in g.nodes

    def test_empty_readiness_list_skips_readiness_layer(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, [])
        assert "greeter_started" not in g.nodes

    def test_graph_missing_graphical_target_skips_bridge(self) -> None:
        """When DOT lacks graphical.target, builder should not crash."""
        dot_no_graphical = """\
digraph systemd { "a"->"b"; }
"""
        builder = CausalGraphBuilder()
        g = builder.build(dot_no_graphical, [], BASIC_READINESS)
        assert "greeter_started" in g.nodes  # readiness still built


class TestBuilderVirtualSink:
    def test_usable_injected_when_readiness_present(self) -> None:
        builder = CausalGraphBuilder()
        blame = [_make_unit_timing(u, d) for u, d in BASIC_BLAME]
        g = builder.build(BASIC_DOT, blame, BASIC_READINESS)
        assert "usable" in g.nodes

    def test_leaf_nodes_connect_to_usable(self) -> None:
        """Leaves of the graph should have edges to usable."""
        builder = CausalGraphBuilder()
        g = builder.build(BASIC_DOT, [], BASIC_READINESS)
        # At least one edge targets usable (from readiness chain or leaf wiring)
        leaf_edges = [e for e in g.edges if e.target == "usable"]
        assert len(leaf_edges) >= 1
