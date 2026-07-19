"""CausalGraphBuilder — assembles a ``CausalGraph`` from DOT text,
systemd-analyze blame output, and optional readiness events.

Building phases:
1. Parse DOT -> systemd-layer nodes + edges.
2. Apply blame durations as node weights.
3. If readiness events present, build serial readiness chain with
   delta-blame and bridge ``graphical.target -> greeter_started``.
4. Inject ``usable`` virtual sink and connect all leaves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kylinbootlab.analysis.dot import parse_dot
from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, CausalNode

if TYPE_CHECKING:
    from kylinbootlab.readiness import ReadinessEvent
    from kylinbootlab.systemd import UnitTiming

# Ordered list of readiness event kinds forming the serial chain.
_READINESS_CHAIN = [
    "observer_started",
    "greeter_started",
    "greeter_ready",
    "login_injected",
    "session_opened",
    "desktop_process_up",
    "atspi_desktop_ready",
    "sentinel_launched",
    "sentinel_window_shown",
    "usable",
]


class CausalGraphBuilder:
    """Build a ``CausalGraph`` from DOT + blame + readiness."""

    def build(
        self,
        dot_text: str,
        blame_list: list[UnitTiming],
        readiness_events: list[ReadinessEvent] | None = None,
    ) -> CausalGraph:
        g = CausalGraph()

        # ---- Phase 1: DOT nodes + edges ----
        dot = parse_dot(dot_text)
        for node_name in dot.nodes:
            g.add_node(CausalNode(name=node_name, layer="systemd"))
        for src, tgt in dot.edges:
            g.add_edge(CausalEdge(source=src, target=tgt, kind="after"))

        # ---- Phase 2: Apply blame ----
        blame_map: dict[str, int] = {}
        for ut in blame_list:
            blame_map[ut.unit] = ut.duration_ns
        for name, node in g.nodes.items():
            if name in blame_map:
                node.blame_ns = blame_map[name]

        # ---- Phase 3: Readiness layer ----
        if readiness_events:
            self._add_readiness_layer(g, readiness_events)

        # ---- Phase 4: Virtual sink (only when readiness layer exists) ----
        if readiness_events:
            self._inject_usable_sink(g)

        return g

    # ------------------------------------------------------------------

    def _add_readiness_layer(
        self, g: CausalGraph, events: list[ReadinessEvent]
    ) -> None:
        """Build serial readiness chain with delta-blame and bridge."""
        # Index events by kind (first occurrence wins)
        by_kind: dict[str, ReadinessEvent] = {}
        for ev in events:
            if ev.kind not in by_kind:
                by_kind[ev.kind] = ev

        # Build chain following _READINESS_CHAIN order
        chain: list[tuple[str, int]] = []  # (kind, monotonic_ns)
        for kind in _READINESS_CHAIN:
            if kind in by_kind:
                chain.append((kind, by_kind[kind].monotonic_ns))

        if len(chain) < 2:
            return  # need at least two events for a meaningful chain

        # Add nodes with delta-blame
        prev_ns: int | None = None
        for i, (kind, ns) in enumerate(chain):
            blame_ns = 0
            if i < len(chain) - 1:
                blame_ns = chain[i + 1][1] - ns
            node = CausalNode(name=kind, blame_ns=blame_ns, layer="readiness")
            if kind not in g.nodes:
                g.add_node(node)
            else:
                # Merge: existing node (e.g. usable injected elsewhere)
                # — set layer + blame
                existing = g.nodes[kind]
                existing.layer = "readiness"
                existing.blame_ns = max(existing.blame_ns, blame_ns)

            if prev_ns is not None:
                prev_kind = chain[i - 1][0]
                g.add_edge(
                    CausalEdge(source=prev_kind, target=kind, kind="readiness_gate")
                )
            prev_ns = ns

        # ---- Bridge: graphical.target -> greeter_started ----
        if "graphical.target" in g.nodes and "greeter_started" in g.nodes:
            g.add_edge(
                CausalEdge(
                    source="graphical.target",
                    target="greeter_started",
                    kind="after",
                )
            )

    def _inject_usable_sink(self, g: CausalGraph) -> None:
        """Ensure every leaf connects to ``usable`` virtual sink."""
        if "usable" not in g.nodes:
            g.add_node(CausalNode(name="usable", layer="readiness"))

        sources = {e.source for e in g.edges}
        for name in g.nodes:
            if name != "usable" and name not in sources:
                g.add_edge(CausalEdge(source=name, target="usable", kind="after"))

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @staticmethod
    def from_run(store: object, run_id: str) -> CausalGraph:
        """Build a ``CausalGraph`` directly from a stored run.

        Loads the ``systemd-dot``, ``systemd-blame``, and optional
        ``readiness-events`` artifacts from *store*, parses them, and
        passes them to :meth:`build`.
        """
        from uuid import UUID

        from kylinbootlab.capture import load_command_capture
        from kylinbootlab.readiness import parse_events
        from kylinbootlab.store import BundleError, RunStore
        from kylinbootlab.systemd import parse_systemd_blame

        if not isinstance(store, RunStore):
            raise TypeError(
                f"store must be a RunStore instance, got {type(store).__name__}"
            )

        run_id_uuid = UUID(run_id)
        run_path = store.run_path(run_id_uuid)
        manifest = store.load_manifest(run_id_uuid)

        dot_capture = load_command_capture(run_path, manifest, "systemd-dot")
        blame_capture = load_command_capture(run_path, manifest, "systemd-blame")
        blame_list = parse_systemd_blame(blame_capture.stdout)

        readiness_events: list[ReadinessEvent] | None = None
        try:
            readiness_capture = load_command_capture(
                run_path, manifest, "readiness-events"
            )
            if readiness_capture.exit_code == 0 and readiness_capture.stdout.strip():
                readiness_events = parse_events(readiness_capture.stdout)
        except BundleError:
            pass

        builder = CausalGraphBuilder()
        return builder.build(dot_capture.stdout, blame_list, readiness_events)
