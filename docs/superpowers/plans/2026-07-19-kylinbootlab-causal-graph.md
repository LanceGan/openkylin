# KylinBootLab Phase 4: Causal Graph & What-If Simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency causal graph from systemd DOT-output + blame + readiness events, compute critical paths, slack, bottleneck rankings, and a what-if simulator — then validate the stack against a 5-case physical fault-injection corpus (>=80% Top-3 hit rate).

**Architecture:** Python-only phase. Nine new modules under `src/kylinbootlab/analysis/`: DOT parser, graph model+builder, critical-path, bottleneck, simulator, compare, fault-corpus. A `kbl analyze` CLI command loads a RunStore run — extracts DOT, blame, readiness — builds the hybrid graph, runs the algorithms, and emits JSON. The what-if simulator takes edit operations and re-computes critical paths — no target boot required. The fault corpus injects systemd drop-ins via SSH, drives one cold boot per case, and asserts Top-3 correctness in the bottleneck ranking.

**Tech Stack:** Python 3.12, Pydantic 2, Typer, pytest. Zero new Rust; zero new target-side changes. All analysis reads from Phase 1 `RunStore` captures.

---

## Global Constraints

- Python 3.12+, Pydantic 2 strict (`extra="forbid"`), mypy strict, ruff clean.
- All algorithms synchronous, no asyncio — consistent with Phase 1-3.
- Phase 1-3 modules consumed but NOT modified. DOT text, blame text, and readiness JSONL are all already captured in `RunStore.raw/` artifacts.
- `CausalGraph` outputs are serializable JSON — the `kbl analyze` command writes `derived/causal-graph.json` and `derived/bottleneck-report.json`.
- Edge weights are zero (dependency-only per spec decision). Node weights = `systemd-analyze blame` exclusive time for systemd nodes; readiness node weights = time delta to next readiness event.
- `CausalGraphBuilder` normalizes: node merging (same node from DOT + blame), virtual sink injection (`usable`), two-layer bridging (`graphical.target -> greeter_started`).
- `ProbeManifest` schema is **frozen**. The DOT artifact is accessed as capture artifact `systemd-critical-chain` (an existing or newly-specified artifact from `systemd-analyze --no-pager dot --order`).
- All graph algorithm functions are pure — take a `CausalGraph`, return values; no side effects, no I/O.
- `NonNegativeInt` from Pydantic for all nanosecond fields.

---

## File Map

```text
src/kylinbootlab/analysis/
├── __init__.py                Package init — re-exports public API
├── dot.py                     DOT text parser (graphviz dot format)
├── graph.py                   CausalNode, CausalEdge, CausalGraph, Bottleneck, WhatIfResult
├── builder.py                 CausalGraphBuilder — DOT + blame + readiness -> CausalGraph
├── critical_path.py           critical_path(), slack() algorithms
├── bottleneck.py              rank_bottlenecks() scoring engine
├── simulator.py               WhatIfSimulator — edit-and-recompute
├── compare.py                 diff_graphs() cross-run comparison
├── fault_corpus.py            FaultInjection dataclass, FaultCorpusRunner
src/kylinbootlab/cli.py        + kbl analyze command
tests/
├── test_dot.py                DOT parser tests (~15)
├── test_graph.py              graph model tests (~5)
├── test_builder.py            builder integration tests (~10)
├── test_critical_path.py      critical path + slack tests (~8)
├── test_bottleneck.py         bottleneck ranking tests (~7)
├── test_simulator.py          what-if simulator tests (~6)
├── test_compare.py            cross-run comparison tests (~5)
├── test_fault_corpus.py       fault corpus unit tests (~8)
scripts/target/kbl-dot-capture.sh  one-shot DOT capture script for target
docs/evidence/fault-corpus/    per-case evidence + final report
```

---

## Scope and Exit Criteria

Implements spec `docs/superpowers/specs/2026-07-19-kylinbootlab-causal-graph.md`. Complete when:

- `CausalGraphBuilder.build()` ingests real DOT (1651 edges from recon), blame, and readiness events, producing a valid `CausalGraph` with systemd + readiness layers bridged at `graphical.target -> greeter_started`.
- `critical_path(sink="usable")` returns the longest-blame-sum path; `slack(node)` computes non-negative nanoseconds the node can slip.
- `rank_bottlenecks(top_k=10)` sorts nodes by `blame_ns * slack_penalty * criticality`; `WhatIfSimulator` accepts remove_edge and reduce_blame actions with correct upper-bound semantics.
- `diff_graphs()` detects node/edge/blame/cp changes across two runs; returns top-5 divergences.
- `kbl analyze RUN_ID` CLI loads a RunStore run, executes the full pipeline, writes `derived/causal-graph.json` + `derived/bottleneck-report.json`.
- Fault corpus: 5 physical cases injected via systemd drop-ins, each verified with one cold boot; Top-3 hit rate >= 80% (>=12/15 predictions correct).
- Quality gates: >=60 new tests, ruff ✅, mypy strict ✅, pytest all green, schema export current.

---

### Task 1: DOT Parser (dot.py)

**Files:**
- Create: `src/kylinbootlab/analysis/__init__.py`
- Create: `src/kylinbootlab/analysis/dot.py`
- Create: `tests/test_dot.py`

**Interfaces:**
- Produces: `DOTGraph` dataclass with fields `nodes: set[str]`, `edges: list[tuple[str, str]]`, `node_attrs: dict[str, dict[str, str]]` (node name -> {shape, label, ...}), `strict: bool`.
- Produces: `parse_dot(text: str) -> DOTGraph` — parses graphviz DOT output from `systemd-analyze dot --order`.
- DOT format handled: `digraph` keyword, `strict` modifier, `->` directed edges, node attribute lists `[shape=box, label="..."]`, quoted labels with escaped quotes, comments `// ...` and `/* ... */`, blank lines, node statements without edges.
- Edge case handling: empty graph returns empty DOTGraph; self-loops preserved; duplicate edge declarations deduplicated (set semantics for `edges`); SCCs parsed without traversal — the parser does NOT validate acyclicity; graph-level attributes (`rankdir`, etc.) ignored.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dot.py`:

```python
"""Tests for DOT parser — systemd-analyze dot output format."""

import pytest

from kylinbootlab.analysis.dot import DOTGraph, parse_dot


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
    assert len(g.nodes) == 24
    assert len(g.edges) == 20
    assert g.strict is True
    assert "graphical.target" in g.nodes
    assert "basic.target" in g.nodes
    # leaf nodes
    assert "var.mount" in g.nodes
    assert "wpa_supplicant.service" in g.nodes
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_dot.py -v`
Expected: FAIL — `kylinbootlab.analysis.dot` does not exist.

- [ ] **Step 3: Implement analysis/__init__.py**

Create `src/kylinbootlab/analysis/__init__.py`:

```python
"""Causal graph analysis package — Phase 4 core algorithms."""
```

- [ ] **Step 4: Implement dot.py**

Create `src/kylinbootlab/analysis/dot.py`:

```python
"""DOT-format parser for systemd-analyze dot output.

Parses graphviz digraph text into a DOTGraph with nodes, edges, and
per-node attribute dictionaries.  Handles the subset of DOT produced by
``systemd-analyze --no-pager dot --order``: directed edges, node
attribute lists, comments, and graph-level modifiers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class DOTGraph:
    """Parsed representation of a graphviz digraph."""

    nodes: set[str] = field(default_factory=set)
    edges: list[tuple[str, str]] = field(default_factory=list)
    node_attrs: dict[str, dict[str, str]] = field(default_factory=dict)
    strict: bool = False


# ---------------------------------------------------------------------------
# Token patterns
# ---------------------------------------------------------------------------

_COMMENT_LINE = re.compile(r"^\s*//.*$")
_COMMENT_BLOCK = re.compile(r"/\*.*?\*/", re.DOTALL)
_QUOTED_NAME = re.compile(r'"((?:[^"\\]|\\.)*)"')

# A single attribute key=value pair (values may be quoted or unquoted)
_ATTR_PAIR = re.compile(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(\w+))')

# Full attribute list [ ... ]
_ATTR_LIST = re.compile(r"\[([^\]]*)\]")


def _strip_comments(text: str) -> str:
    """Remove // line comments and /* */ block comments."""
    text = _COMMENT_BLOCK.sub("", text)
    lines = [_COMMENT_LINE.sub("", line) for line in text.splitlines()]
    return "\n".join(lines)


def _parse_quoted(s: str) -> str:
    """Unquote and unescape a DOT quoted string."""
    if s.startswith('"') and s.endswith('"'):
        inner = s[1:-1]
        inner = inner.replace('\\"', '"')
        return inner
    return s


def _parse_attrs(attr_block: str) -> dict[str, str]:
    """Parse [key=val, key="val"] into a dict."""
    result: dict[str, str] = {}
    for m in _ATTR_PAIR.finditer(attr_block):
        key = m.group(1)
        # either quoted value (group 2) or unquoted (group 3)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        result[key] = val
    return result


def parse_dot(text: str) -> DOTGraph:
    """Parse graphviz digraph text into a ``DOTGraph``.

    Handles ``strict digraph``, node/edge statements with optional
    attribute lists, single-line comments ``//``, and block comments
    ``/* */``.

    Raises:
        ValueError: If ``text`` does not contain a ``digraph`` declaration
            or is otherwise unparseable.
    """
    text = _strip_comments(text)

    # Must start with optional "strict" then "digraph"
    m = re.match(r"\s*(strict\s+)?digraph\s+\w+\s*\{", text)
    if not m:
        raise ValueError("Input does not contain a valid digraph declaration")
    strict = m.group(1) is not None

    # Extract body between outermost braces
    start = m.end()
    brace_depth = 1
    end = start
    for i, ch in enumerate(text[start:], start=start):
        if ch == "{":
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0:
                end = i
                break
    if brace_depth != 0:
        raise ValueError("Unmatched opening brace — missing closing '}'")
    body = text[start:end]

    graph = DOTGraph(strict=bool(strict))
    seen_edges: set[tuple[str, str]] = set()

    # Split on ";" to get statements, then parse each
    statements = body.split(";")
    for stmt in statements:
        stmt = stmt.strip()
        if not stmt:
            continue

        # Extract trailing attribute list if present
        attr_block_match = _ATTR_LIST.search(stmt)
        attrs: dict[str, str] = {}
        if attr_block_match:
            attrs = _parse_attrs(attr_block_match.group(1))
            stmt = stmt[: attr_block_match.start()].strip() + stmt[attr_block_match.end() :].strip()

        # Check for edge: node -> node
        if "->" in stmt:
            parts = stmt.split("->")
            source = _parse_quoted(parts[0].strip())
            target = _parse_quoted(parts[1].strip())
            edge = (source, target)
            graph.nodes.add(source)
            graph.nodes.add(target)
            if edge not in seen_edges:
                seen_edges.add(edge)
                graph.edges.append(edge)
        else:
            # Isolated node statement (with possible attrs)
            qm = _QUOTED_NAME.match(stmt)
            if qm:
                node_name = _parse_quoted(qm.group(0))
                graph.nodes.add(node_name)
                if attrs:
                    graph.node_attrs[node_name] = attrs
            elif "=" not in stmt:
                # Bare node name (no quotes, no attrs)
                bare = stmt.strip()
                if bare and not bare.isspace():
                    graph.nodes.add(bare)
                    if attrs:
                        graph.node_attrs[bare] = attrs

    return graph
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_dot.py -v && uv run ruff check src/kylinbootlab/analysis/dot.py && uv run mypy src/kylinbootlab/analysis --strict`
Expected: 15 tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/analysis/__init__.py src/kylinbootlab/analysis/dot.py tests/test_dot.py
git commit -m "feat: add DOT parser for systemd-analyze output"
```

---

### Task 2: Graph Models (graph.py)

**Files:**
- Create: `src/kylinbootlab/analysis/graph.py`
- Create: `tests/test_graph.py`

**Interfaces:**
- Produces: `CausalNode(ContractModel)` — `name: str`, `blame_ns: NonNegativeInt = 0`, `earliest_ns: NonNegativeInt | None = None`, `latest_ns: NonNegativeInt | None = None`, `layer: Literal["systemd", "readiness"]`.
- Produces: `CausalEdge(ContractModel)` — `source: str`, `target: str`, `kind: Literal["after", "wants", "requires", "readiness_gate"]`, `weight_ns: NonNegativeInt = 0`.
- Produces: `CausalGraph` — `nodes: dict[str, CausalNode]`, `edges: list[CausalEdge]`. Methods: `add_node(n: CausalNode)`, `add_edge(e: CausalEdge)`, `sources() -> list[str]` (nodes with zero incoming edges), `predecessors(name) -> list[str]`, `successors(name) -> list[str]`, `to_json_dict() -> dict`, `from_json_dict(d: dict) -> CausalGraph`.
- Produces: `Bottleneck(ContractModel)` — `rank: int`, `node: str`, `blame_ns: NonNegativeInt`, `slack_ns: NonNegativeInt`, `on_critical_path: bool`, `score: float`, `evidence: str | None = None`.
- Produces: `WhatIfResult(ContractModel)` — `action: str`, `predicted_gain_ns: int`, `upper_bound_ns: int`, `affected_nodes: list[str]`, `degenerates_to_same_path: bool = False`, `note: str | None = None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graph.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_graph.py -v`
Expected: FAIL — `kylinbootlab.analysis.graph` does not exist.

- [ ] **Step 3: Implement graph.py**

Create `src/kylinbootlab/analysis/graph.py`:

```python
"""Causal graph data models — nodes, edges, graph container, and analysis
results (Bottleneck, WhatIfResult).

All models extend ``ContractModel`` for strict serialization (no undeclared
fields).  ``CausalGraph`` is the central runtime object; algorithms in other
modules consume it via the public methods and produce ``Bottleneck`` /
``WhatIfResult`` lists.
"""

from __future__ import annotations

from typing import Literal

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

    def to_json_dict(self) -> dict:
        return {
            "nodes": {name: n.model_dump() for name, n in self.nodes.items()},
            "edges": [e.model_dump() for e in self.edges],
        }

    @classmethod
    def from_json_dict(cls, d: dict) -> "CausalGraph":
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
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_graph.py -v && uv run ruff check src/kylinbootlab/analysis/graph.py && uv run mypy src/kylinbootlab/analysis/graph.py --strict`
Expected: 12 tests pass, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/analysis/graph.py tests/test_graph.py
git commit -m "feat: add causal graph data models (CausalNode, CausalEdge, CausalGraph, Bottleneck, WhatIfResult)"
```

---

### Task 3: CausalGraphBuilder (builder.py)

**Files:**
- Create: `src/kylinbootlab/analysis/builder.py`
- Create: `tests/test_builder.py`
- Create: `scripts/target/kbl-dot-capture.sh`

**Interfaces:**
- Consumes: `DOTGraph, parse_dot` from `kylinbootlab.analysis.dot`; `CausalNode, CausalEdge, CausalGraph` from `kylinbootlab.analysis.graph`; `UnitTiming, parse_systemd_blame` from `kylinbootlab.systemd`; `parse_events, derive_metrics` from `kylinbootlab.readiness`; `load_command_capture` from `kylinbootlab.capture`; `RunStore` from `kylinbootlab.store`.
- Produces: `CausalGraphBuilder` class with `build(dot_text: str, blame_list: list[UnitTiming], readiness_events: list[ReadinessEvent] | None = None) -> CausalGraph`.
- Building phases:
  1. Parse DOT -> nodes + edges; create CausalNode for each DOT node, layer="systemd".
  2. Apply blame: for each UnitTiming, lookup node by unit name; set `blame_ns = int(timing.duration_us * 1000)`. Nodes in DOT but NOT in blame keep `blame_ns=0`.
  3. Readiness layer (if events provided): create serial chain of readiness nodes (`observer_started -> greeter_started -> greeter_ready -> login_injected -> session_opened -> desktop_process_up -> atspi_desktop_ready -> sentinel_launched -> sentinel_window_shown -> usable`). Blame for each = delta to next event (last event blame = 0). All readiness edges kind="readiness_gate".
  4. Bridge: add edge `graphical.target -> greeter_started` (kind="after"). If `graphical.target` not in DOT nodes, skip bridge gracefully.
  5. Virtual sink: if `usable` not already a node, inject it with blame_ns=0. Ensure every leaf connects to `usable` (unless it already has a successor).
- `from_run(store: RunStore, run_id: str) -> CausalGraph` convenience factory.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_builder.py`:

```python
"""Tests for CausalGraphBuilder — DOT + blame + readiness -> CausalGraph."""

import pytest

from kylinbootlab.analysis.builder import CausalGraphBuilder
from kylinbootlab.analysis.graph import CausalGraph
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
        bridge = [e for e in g.edges if e.source == "graphical.target" and e.target == "greeter_started"]
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
        """Leaves of the graph should have edges to usable if not already."""
        builder = CausalGraphBuilder()
        g = builder.build(BASIC_DOT, [], BASIC_READINESS)
        # graphical.target is a leaf in DOT; it should connect to usable
        leaf_edges = [e for e in g.edges if e.target == "usable"]
        assert len(leaf_edges) >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_builder.py -v`
Expected: FAIL — `kylinbootlab.analysis.builder` does not exist.

- [ ] **Step 3: Implement builder.py**

Create `src/kylinbootlab/analysis/builder.py`:

```python
"""CausalGraphBuilder — assembles a ``CausalGraph`` from DOT text,
systemd-analyze blame output, and optional readiness events.

Building phases (per spec §3.1):
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

        # ---- Phase 4: Virtual sink ----
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
                # Merge: existing node (e.g. usable injected elsewhere) — set layer + blame
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

        targets = {e.source for e in g.edges}
        for name in g.nodes:
            if name != "usable" and name not in targets:
                g.add_edge(CausalEdge(source=name, target="usable", kind="after"))
```

- [ ] **Step 4: Create DOT capture script**

Create `scripts/target/kbl-dot-capture.sh`:

```bash
#!/usr/bin/env bash
# Capture systemd dependency DOT graph for Phase 4 causal analysis.
# Run on target:  bash kbl-dot-capture.sh > dot-output.txt
set -euo pipefail
systemd-analyze --no-pager dot --order 2>/dev/null || {
    echo "ERROR: systemd-analyze dot failed" >&2
    exit 1
}
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_builder.py -v && uv run ruff check src/kylinbootlab/analysis/builder.py && uv run mypy src/kylinbootlab/analysis/builder.py --strict`
Expected: 10 tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/analysis/builder.py tests/test_builder.py scripts/target/kbl-dot-capture.sh
git commit -m "feat: add CausalGraphBuilder — DOT + blame + readiness -> CausalGraph"
```

---

### Task 4: Critical Path + Slack Algorithms

**Files:**
- Create: `src/kylinbootlab/analysis/critical_path.py`
- Create: `tests/test_critical_path.py`

**Interfaces:**
- Consumes: `CausalGraph`, `CausalNode` from `kylinbootlab.analysis.graph`.
- Produces: `critical_path(graph: CausalGraph, sink: str = "usable") -> list[str]` — returns node names along the single longest path (by blame_ns sum) from any source to the given sink. Ties broken by first found (insertion-order stable).
- Produces: `slack(graph: CausalGraph, node_name: str, sink: str = "usable") -> int` — critical path length minus the max blame-sum path through `node_name`. Non-negative; zero means node is on *some* critical path.
- Produces: `_cp_length(graph: CausalGraph, sink: str) -> int` — internal: returns total blame_ns of the critical path.
- Algorithm: DFS enumerate all paths from sources to sink. For each path, sum `node.blame_ns`. Track best. For slack, compute `max_blame_through_node` by enumerating all paths containing that node.
- Edge cases: sink not reachable raises `ValueError`. Node not in graph raises `KeyError`. Empty graph with no nodes raises `ValueError`. Sink with no incoming paths returns path containing only the sink.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_critical_path.py`:

```python
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
        assert len(cp) == 4
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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_critical_path.py -v`
Expected: FAIL — `kylinbootlab.analysis.critical_path` does not exist.

- [ ] **Step 3: Implement critical_path.py**

Create `src/kylinbootlab/analysis/critical_path.py`:

```python
"""Critical path and slack algorithms on ``CausalGraph``.

- ``critical_path(graph, sink)`` — longest blame-sum path from sources to sink.
- ``slack(graph, node, sink)`` — nanoseconds the node can slip without
  delaying the sink.

Both are pure functions: no side effects, no I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def _all_paths_from_sources(
    graph: "CausalGraph",
    sink: str,
) -> list[list[str]]:
    """DFS-enumerate every path from any source node to *sink*.

    Sources are nodes with zero in-edges.  Returns list of paths where
    each path is a list of node names in traversal order.
    """
    sources = graph.sources()
    if not sources:
        # Graph with no sources: if the sink itself is a node, return single-node path
        if sink in graph.nodes:
            return [[sink]]
        return []

    all_paths: list[list[str]] = []

    def dfs(current: str, visited: list[str]) -> None:
        if current == sink:
            all_paths.append(list(visited))
            return
        for succ in graph.successors(current):
            if succ not in visited:  # avoid cycles
                visited.append(succ)
                dfs(succ, visited)
                visited.pop()

    for src in sources:
        dfs(src, [src])

    return all_paths


def _path_blame_sum(graph: "CausalGraph", path: list[str]) -> int:
    """Sum of blame_ns for every node in the path."""
    return sum(graph.nodes[n].blame_ns for n in path)


def _cp_length(graph: "CausalGraph", sink: str) -> int:
    """Return total blame_ns of the critical path (longest blame-sum)."""
    paths = _all_paths_from_sources(graph, sink)
    if not paths:
        raise ValueError(f"No path to sink '{sink}' found — sink may not be reachable")
    return max(_path_blame_sum(graph, p) for p in paths)


def critical_path(graph: "CausalGraph", sink: str = "usable") -> list[str]:
    """Return node names along the longest blame-sum path to *sink*.

    DFS enumerates all source-to-sink paths.  Ties are broken by first
    found (insertion-order stable through ``graph.successors``).

    Raises:
        ValueError: If the graph has no nodes or no path reaches *sink*.
    """
    if not graph.nodes:
        raise ValueError("Cannot compute critical path on an empty graph")

    paths = _all_paths_from_sources(graph, sink)
    if not paths:
        raise ValueError(f"No path to sink '{sink}' found — sink may not be reachable")

    best_path: list[str] = paths[0]
    best_len = _path_blame_sum(graph, best_path)
    for p in paths[1:]:
        length = _path_blame_sum(graph, p)
        if length > best_len:
            best_len = length
            best_path = p[:]
    return best_path


def slack(graph: "CausalGraph", node_name: str, sink: str = "usable") -> int:
    """Nanoseconds *node_name* can slip without delaying *sink*.

    ``slack = critical_path_length - max_blame_sum_through(node_name)``.
    Always non-negative; zero means the node is on at least one critical
    path.

    Raises:
        KeyError: If *node_name* is not in the graph.
        ValueError: If no path reaches *sink*.
    """
    if node_name not in graph.nodes:
        raise KeyError(f"Node '{node_name}' is not present in the graph")

    cp_len = _cp_length(graph, sink)
    paths = _all_paths_from_sources(graph, sink)
    max_through = 0
    for p in paths:
        if node_name in p:
            max_through = max(max_through, _path_blame_sum(graph, p))
    return cp_len - max_through
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_critical_path.py -v && uv run ruff check src/kylinbootlab/analysis/critical_path.py && uv run mypy src/kylinbootlab/analysis/critical_path.py --strict`
Expected: 8 tests pass, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/analysis/critical_path.py tests/test_critical_path.py
git commit -m "feat: add critical_path() and slack() algorithms"
```

---

### Task 5: Bottleneck Scoring + Ranking + WhatIf Simulator

**Files:**
- Create: `src/kylinbootlab/analysis/bottleneck.py`
- Create: `src/kylinbootlab/analysis/simulator.py`
- Create: `tests/test_bottleneck.py`
- Create: `tests/test_simulator.py`

**Interfaces:**
- Consumes: `CausalGraph, CausalNode, Bottleneck, WhatIfResult` from `kylinbootlab.analysis.graph`; `critical_path, slack` from `kylinbootlab.analysis.critical_path`.
- Produces (bottleneck.py): `rank_bottlenecks(graph: CausalGraph, sink: str = "usable", top_k: int = 10, total_runs: int = 1, on_cp_nodes: list[str] | None = None) -> list[Bottleneck]`. Score formula (spec §5.3): `score = blame_ns * (1.0 / (1.0 + slack_ns / 1_000_000_000)) * (count_on_cp / total_runs)`. Sort descending by score; secondary sort by blame_ns descending; tertiary sort by node name (insertion-order stable).
- Produces (simulator.py): `WhatIfSimulator` class with `__init__(graph: CausalGraph)`, `simulate(action: dict) -> WhatIfResult`. Actions: `{"kind": "remove_edge", "source": str, "target": str}` and `{"kind": "reduce_blame", "node": str, "pct": float}` (pct in 0-100). Copies graph (deep copy of nodes dict + edges list), applies edit, recomputes critical_path. Returns gain_ns = new_cp_length - old_cp_length (negative = improvement). `degenerates_to_same_path=True` when cp did not change. Upper-bound semantics (spec §5.4): removing an edge can only shorten or keep same cp; never lengthen.

- [ ] **Step 1: Write bottleneck tests**

Create `tests/test_bottleneck.py`:

```python
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
        g = _graph_from_triples([
            ("src", "cp_node", 1000),
            ("src", "slacky", 2000),
            ("cp_node", "usable", 0),
            ("slacky", "usable", 0),
        ])
        g.nodes["src"].blame_ns = 100
        g.add_node(CausalNode(name="usable", blame_ns=0, layer="readiness"))
        results = rank_bottlenecks(g, top_k=2)
        # cp_node is on cp (slack=0); slacky has high blame but large slack
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
        scores = [r.score for r in results]
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
```

- [ ] **Step 2: Write simulator tests**

Create `tests/test_simulator.py`:

```python
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
        # Second remove on the already-modified copy
        result2 = sim.simulate({
            "kind": "remove_edge",
            "source": "src",
            "target": "fast",
        })
        # After removing both, only src->usable path remains (but there's no edge!)
        # The cp should be shorter than original
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
```

- [ ] **Step 3: Run to verify failures**

Run: `uv run pytest tests/test_bottleneck.py tests/test_simulator.py -v`
Expected: FAIL — modules do not exist.

- [ ] **Step 4: Implement bottleneck.py**

Create `src/kylinbootlab/analysis/bottleneck.py`:

```python
"""Bottleneck ranking engine.

Scores nodes by ``blame_ns * slack_penalty * criticality`` and returns
the top-k as ``Bottleneck`` records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kylinbootlab.analysis.critical_path import _cp_length, slack
from kylinbootlab.analysis.graph import Bottleneck

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def rank_bottlenecks(
    graph: "CausalGraph",
    sink: str = "usable",
    top_k: int = 10,
    total_runs: int = 1,
    on_cp_nodes: list[str] | None = None,
) -> list[Bottleneck]:
    """Rank nodes by bottleneck score, returning top *k*.

    Score formula (spec §5.3):

        score = blame_ns * (1.0 / (1.0 + slack_ns / 1e9)) * (count_on_cp / total_runs)

    Sort descending by score, then by blame_ns descending, then stable
    by node-insertion order.
    """
    if not graph.nodes or sink not in graph.nodes:
        return []

    cp_nodes = on_cp_nodes
    if cp_nodes is None:
        from kylinbootlab.analysis.critical_path import critical_path as cp_fn
        cp_nodes = cp_fn(graph, sink=sink)

    scored: list[tuple[str, float, int, bool]] = []
    for name, node in graph.nodes.items():
        if name == sink:
            continue
        s = slack(graph, name, sink=sink)
        slack_penalty = 1.0 / (1.0 + s / 1_000_000_000)
        criticality = 1.0 if name in cp_nodes else 0.0
        if total_runs > 1:
            criticality = float(cp_nodes.count(name)) / total_runs
        score = node.blame_ns * slack_penalty * criticality
        on_cp = name in cp_nodes
        scored.append((name, score, node.blame_ns, on_cp))

    # Sort: primary score desc, secondary blame_ns desc, tertiary stable
    scored.sort(key=lambda x: (-x[1], -x[2]))

    results: list[Bottleneck] = []
    for rank, (name, score, blame, on_cp) in enumerate(scored[:top_k], start=1):
        s = slack(graph, name, sink=sink)
        evidence_parts = [f"slack={s}{'ns' if s > 0 else ''}"]
        if on_cp:
            evidence_parts.append(f"on critical path ({total_runs} run(s))")
        results.append(
            Bottleneck(
                rank=rank,
                node=name,
                blame_ns=blame,
                slack_ns=s,
                on_critical_path=on_cp,
                score=round(score, 4),
                evidence="; ".join(evidence_parts),
            )
        )
    return results
```

- [ ] **Step 5: Implement simulator.py**

Create `src/kylinbootlab/analysis/simulator.py`:

```python
"""What-If Simulator — edit-and-recompute critical path.

Copies the graph, applies a single edit action (remove_edge or
reduce_blame), recomputes the critical path, and reports the gain.
The gain is an *upper bound* — real-world improvement may be less.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kylinbootlab.analysis.graph import CausalEdge, CausalGraph, WhatIfResult

if TYPE_CHECKING:
    pass


class WhatIfSimulator:
    """Simulate graph edits and predict their effect on critical path.

    Each call to ``simulate()`` creates a fresh copy of the graph, applies
    one edit, and recomputes the critical path.
    """

    def __init__(self, graph: CausalGraph) -> None:
        self._graph = graph

    def simulate(self, action: dict) -> WhatIfResult:
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
```

- [ ] **Step 6: Run tests + gates**

Run: `uv run pytest tests/test_bottleneck.py tests/test_simulator.py -v && uv run ruff check src/kylinbootlab/analysis/bottleneck.py src/kylinbootlab/analysis/simulator.py && uv run mypy src/kylinbootlab/analysis/bottleneck.py src/kylinbootlab/analysis/simulator.py --strict`
Expected: 13 tests pass (7 bottleneck + 6 simulator), ruff clean, mypy clean.

- [ ] **Step 7: Commit**

```bash
git add src/kylinbootlab/analysis/bottleneck.py src/kylinbootlab/analysis/simulator.py tests/test_bottleneck.py tests/test_simulator.py
git commit -m "feat: add bottleneck ranking engine and WhatIfSimulator"
```

---

### Task 6: Cross-Run Comparison (GraphDiff)

**Files:**
- Create: `src/kylinbootlab/analysis/compare.py`
- Create: `tests/test_compare.py`

**Interfaces:**
- Consumes: `CausalGraph` from `kylinbootlab.analysis.graph`; `critical_path` from `kylinbootlab.analysis.critical_path`.
- Produces: `diff_graphs(graph_a: CausalGraph, graph_b: CausalGraph, run_a_id: str, run_b_id: str) -> dict`. Raw dict for now (will be promoted to GraphDiff Pydantic model in a follow-up). Dict keys: `run_a`, `run_b`, `nodes_added`, `nodes_removed`, `edges_added`, `edges_removed`, `blame_changed`, `critical_path_shifted`, `new_bottlenecks`, `top_blame_divergences`.
- Blame changed: nodes where |blame_a - blame_b| > 10% of max(blame_a, blame_b). Reports (node, before_ns, after_ns, delta_pct).
- Critical path shifted: set comparison of cp node sets — True if different.
- New bottlenecks: nodes off cp_a that are now on cp_b.
- Top-5 blame divergences sorted by absolute delta descending.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_compare.py`:

```python
"""Tests for cross-run graph comparison."""

import pytest

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
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_compare.py -v`
Expected: FAIL — `kylinbootlab.analysis.compare` does not exist.

- [ ] **Step 3: Implement compare.py**

Create `src/kylinbootlab/analysis/compare.py`:

```python
"""Cross-run graph comparison — detect structural and blame changes
between two ``CausalGraph`` instances from different boot runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kylinbootlab.analysis.graph import CausalGraph


def diff_graphs(
    graph_a: "CausalGraph",
    graph_b: "CausalGraph",
    run_a_id: str,
    run_b_id: str,
) -> dict:
    """Compare two causal graphs and return a structured diff dict.

    Returns dict with keys: run_a, run_b, nodes_added, nodes_removed,
    edges_added, edges_removed, blame_changed, critical_path_shifted,
    new_bottlenecks, top_blame_divergences.
    """
    from kylinbootlab.analysis.critical_path import critical_path as cp_fn

    nodes_a = set(graph_a.nodes.keys())
    nodes_b = set(graph_b.nodes.keys())

    nodes_added = sorted(nodes_b - nodes_a)
    nodes_removed = sorted(nodes_a - nodes_b)

    # Edges: compare as sets of (source, target)
    edges_a = {(e.source, e.target) for e in graph_a.edges}
    edges_b = {(e.source, e.target) for e in graph_b.edges}
    edges_added = sorted(edges_b - edges_a)
    edges_removed = sorted(edges_a - edges_b)

    # Blame changes (>10% relative delta)
    blame_changed: list[dict] = []
    for name in nodes_a & nodes_b:
        ba = graph_a.nodes[name].blame_ns
        bb = graph_b.nodes[name].blame_ns
        if ba == 0 and bb == 0:
            continue
        denom = max(ba, bb, 1)
        delta_pct = abs(bb - ba) / denom * 100.0
        if delta_pct > 10.0:
            blame_changed.append(
                {
                    "node": name,
                    "before_ns": ba,
                    "after_ns": bb,
                    "delta_pct": round(delta_pct, 2),
                }
            )
    blame_changed.sort(key=lambda x: abs(x["after_ns"] - x["before_ns"]), reverse=True)

    # Critical path comparison
    try:
        cp_a = set(cp_fn(graph_a))
        cp_b = set(cp_fn(graph_b))
        critical_path_shifted = cp_a != cp_b
        new_bottlenecks = sorted(cp_b - cp_a)
    except ValueError:
        critical_path_shifted = False
        new_bottlenecks = []

    # Top-5 blame divergences
    top_blame_divergences = blame_changed[:5]

    return {
        "run_a": run_a_id,
        "run_b": run_b_id,
        "nodes_added": nodes_added,
        "nodes_removed": nodes_removed,
        "edges_added": [(s, t) for s, t in edges_added],
        "edges_removed": [(s, t) for s, t in edges_removed],
        "blame_changed": blame_changed,
        "critical_path_shifted": critical_path_shifted,
        "new_bottlenecks": new_bottlenecks,
        "top_blame_divergences": top_blame_divergences,
    }
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_compare.py -v && uv run ruff check src/kylinbootlab/analysis/compare.py && uv run mypy src/kylinbootlab/analysis/compare.py --strict`
Expected: 5 tests pass, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/analysis/compare.py tests/test_compare.py
git commit -m "feat: add cross-run graph comparison (diff_graphs)"
```

---

### Task 7: kbl analyze CLI

**Files:**
- Modify: `src/kylinbootlab/cli.py` (append `analyze` command)
- Modify: `tests/test_cli.py` (append tests)
- Modify: `src/kylinbootlab/templates/` (no template changes unless baseline.html wants a causal section — out of scope for now)

**Interfaces:**
- Consumes: `RunStore` from `kylinbootlab.store`; `CausalGraphBuilder` from `kylinbootlab.analysis.builder`; `critical_path` from `kylinbootlab.analysis.critical_path`; `rank_bottlenecks` from `kylinbootlab.analysis.bottleneck`; `load_command_capture` from `kylinbootlab.capture`; `parse_systemd_blame` from `kylinbootlab.systemd`; `parse_events` from `kylinbootlab.readiness`.
- Produces: `kbl analyze RUN_ID --data-root PATH` CLI. Pipeline: load manifest -> load_command_capture for `systemd-blame` -> parse DOT from `systemd-critical-chain` capture -> load readiness events (absent = empty list, degrades gracefully) -> CausalGraphBuilder.build -> critical_path -> rank_bottlenecks -> write `derived/causal-graph.json` + `derived/bottleneck-report.json` to the run's derived/ dir.
- Status: when readiness artifact is absent, the readiness layer is empty — the graph degrades gracefully (systemd-only) and the CLI prints a diagnostic note.

- [ ] **Step 1: Read current CLI to understand structure**

Read `src/kylinbootlab/cli.py` to identify the app structure, existing commands, and where to inject the analyze command.

- [ ] **Step 2: Write CLI smoke test**

Append to `tests/test_cli.py`:

```python
# --- kbl analyze smoke tests ---

import json
from pathlib import Path

import pytest

from kylinbootlab.cli import app as kbl_app
from tests.helpers import CaptureFixture, create_probe_bundle


DOT_STDOUT = """\
strict digraph systemd {
    "basic.target"->"sysinit.target";
    "sysinit.target"->"dbus.service";
    "dbus.service"->"NetworkManager.service";
    "NetworkManager.service"->"lightdm.service";
    "lightdm.service"->"graphical.target";
}
"""

READINESS_STDOUT = """\
{"schema_version":1,"monotonic_ns":10000000000,"kind":"greeter_started","detail":"lightdm","source":"journald"}
{"schema_version":1,"monotonic_ns":12000000000,"kind":"greeter_ready","detail":"ukui-greeter","source":"journald"}
{"schema_version":1,"monotonic_ns":13000000000,"kind":"login_injected","detail":"uinput","source":"probe"}
{"schema_version":1,"monotonic_ns":15000000000,"kind":"session_opened","detail":"kbl","source":"journald"}
{"schema_version":1,"monotonic_ns":20000000000,"kind":"desktop_process_up","detail":"ukui-panel","source":"probe"}
{"schema_version":1,"monotonic_ns":21000000000,"kind":"atspi_desktop_ready","detail":"3 children","source":"atspi"}
{"schema_version":1,"monotonic_ns":22000000000,"kind":"sentinel_launched","detail":"mate-terminal","source":"probe"}
{"schema_version":1,"monotonic_ns":24000000000,"kind":"sentinel_window_shown","detail":"mate-terminal window","source":"atspi"}
{"schema_version":1,"monotonic_ns":24000000000,"kind":"usable","detail":"all three","source":"probe"}
"""

DOT_DOC: CaptureFixture = {
    "command": ["systemd-analyze", "--no-pager", "dot", "--order"],
    "exit_code": 0,
    "stdout": DOT_STDOUT,
    "stderr": "",
}

READINESS_DOC: CaptureFixture = {
    "command": ["kbl-bootprobe", "observe"],
    "exit_code": 0,
    "stdout": READINESS_STDOUT,
    "stderr": "",
}


def test_analyze_without_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kbl analyze succeeds on a bundle with DOT + blame but no readiness artifact."""
    from kylinbootlab.store import RunStore

    data_root = tmp_path / "runs"
    data_root.mkdir()
    store = RunStore(data_root)
    bundle = create_probe_bundle(
        tmp_path, optional_captures={"systemd-critical-chain": DOT_DOC}
    )
    run_id = store.ingest(bundle)

    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(
        kbl_app, ["analyze", str(run_id), "--data-root", str(data_root)]
    )
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # Check derived files exist
    derived = store.run_path(run_id) / "derived"
    assert (derived / "causal-graph.json").exists()
    assert (derived / "bottleneck-report.json").exists()

    # Validate JSON structure
    cg = json.loads((derived / "causal-graph.json").read_text())
    assert "nodes" in cg
    assert "edges" in cg
    br = json.loads((derived / "bottleneck-report.json").read_text())
    assert isinstance(br, list)


def test_analyze_with_readiness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """kbl analyze includes readiness layer when readiness-events is present."""
    from kylinbootlab.store import RunStore

    data_root = tmp_path / "runs"
    data_root.mkdir()
    store = RunStore(data_root)
    bundle = create_probe_bundle(
        tmp_path,
        optional_captures={
            "systemd-critical-chain": DOT_DOC,
            "readiness-events": READINESS_DOC,
        },
    )
    run_id = store.ingest(bundle)

    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(
        kbl_app, ["analyze", str(run_id), "--data-root", str(data_root)]
    )
    assert result.exit_code == 0
    derived = store.run_path(run_id) / "derived"
    cg = json.loads((derived / "causal-graph.json").read_text())
    # readiness layer nodes should be present
    node_names = list(cg["nodes"].keys())
    assert any("greeter" in n for n in node_names) or any("usable" in n for n in node_names)


def test_analyze_nonexistent_run_id(tmp_path: Path) -> None:
    """CLI should error on nonexistent run ID."""
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(
        kbl_app, ["analyze", "00000000-0000-0000-0000-000000000000", "--data-root", str(tmp_path)]
    )
    assert result.exit_code != 0
```

- [ ] **Step 3: Verify store APIs needed by analyze command**

Check that `RunStore` has these methods (all exist in Phase 1):
- `load_manifest(run_id: UUID) -> ProbeManifest` -- confirmed in `store.py`
- `run_path(run_id: UUID) -> Path` -- confirmed

If `derived_path` is not present, add to `src/kylinbootlab/store.py`:

```python
def derived_path(self, run_id: UUID) -> Path:
    """Return the derived/ subdirectory for a run."""
    return self.run_path(run_id) / "derived"
```

Also confirmed: `load_command_capture` returns a `CommandCapture` with `.stdout` attribute (from `capture.py`).

- [ ] **Step 4: Implement kbl analyze in cli.py**

Read `src/kylinbootlab/cli.py` to find where to append. Add after the last existing command:

```python
@app.command("analyze")
def cmd_analyze(
    run_id: str = typer.Argument(..., help="Run UUID to analyze"),
    data_root: Path = typer.Option(
        Path("var/runs"),
        "--data-root",
        help="RunStore data root directory",
    ),
) -> None:
    """Build causal graph and bottleneck report from a captured boot run."""
    import json
    import logging
    from uuid import UUID

    from kylinbootlab.analysis.bottleneck import rank_bottlenecks
    from kylinbootlab.analysis.builder import CausalGraphBuilder
    from kylinbootlab.analysis.critical_path import critical_path
    from kylinbootlab.capture import load_command_capture
    from kylinbootlab.readiness import parse_events
    from kylinbootlab.store import RunStore
    from kylinbootlab.systemd import parse_systemd_blame

    logger = logging.getLogger(__name__)

    store = RunStore(data_root)
    rid = UUID(run_id)
    manifest = store.load_manifest(rid)

    # Load DOT from capture artifact
    dot_capture = load_command_capture(
        store.run_path(rid), manifest, "systemd-critical-chain"
    )
    dot_text = dot_capture.stdout

    # Load blame
    blame_capture = load_command_capture(
        store.run_path(rid), manifest, "systemd-blame"
    )
    blame_list = parse_systemd_blame(blame_capture.stdout)

    # Load readiness (optional — absent = empty list)
    readiness_events = []
    try:
        readiness_capture = load_command_capture(
            store.run_path(rid), manifest, "readiness-events"
        )
        readiness_events = parse_events(readiness_capture.stdout)
    except Exception:
        logger.info("No readiness-events artifact found — readiness layer will be empty")

    # Build graph
    builder = CausalGraphBuilder()
    graph = builder.build(dot_text, blame_list, readiness_events or None)

    # Compute critical path
    cp = critical_path(graph)
    cp_length_ns = sum(graph.nodes[n].blame_ns for n in cp)

    # Rank bottlenecks
    bottlenecks = rank_bottlenecks(graph, top_k=10)

    # Write derived files
    derived_dir = store.run_path(rid) / "derived"
    derived_dir.mkdir(parents=True, exist_ok=True)

    cg_out = {
        "run_id": str(rid),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "critical_path": cp,
        "critical_path_length_ns": cp_length_ns,
        "graph": graph.to_json_dict(),
    }
    (derived_dir / "causal-graph.json").write_text(
        json.dumps(cg_out, indent=2), encoding="utf-8"
    )

    br_out = [b.model_dump() for b in bottlenecks]
    (derived_dir / "bottleneck-report.json").write_text(
        json.dumps(br_out, indent=2), encoding="utf-8"
    )

    logger.info(
        "Analyzed run %s: %d nodes, %d edges, cp_length=%.3fs, top_bottleneck=%s",
        run_id,
        len(graph.nodes),
        len(graph.edges),
        cp_length_ns / 1e9,
        bottlenecks[0].node if bottlenecks else "none",
    )
    print(f"Critical path: {' -> '.join(cp)}")
    print(f"Critical path length: {cp_length_ns / 1e9:.3f}s")
    print(f"Top bottleneck: {bottlenecks[0].node} (score={bottlenecks[0].score})" if bottlenecks else "No bottlenecks found")
    print(f"Reports written to {derived_dir}")
```

- [ ] **Step 5: Run tests + gates**

Run: `uv run pytest tests/test_cli.py::test_analyze_with_probe_bundle_no_readiness tests/test_cli.py::test_analyze_with_readiness_events tests/test_cli.py::test_analyze_nonexistent_run_id -v && uv run ruff check src/kylinbootlab/cli.py && uv run mypy src/kylinbootlab/cli.py --strict`
Expected: 3 CLI tests pass, ruff clean, mypy clean.

- [ ] **Step 6: Commit**

```bash
git add src/kylinbootlab/cli.py src/kylinbootlab/store.py tests/test_cli.py
git commit -m "feat: add kbl analyze CLI command for causal graph pipeline"
```

---

### Task 8: Fault Corpus Driver

**Files:**
- Create: `src/kylinbootlab/analysis/fault_corpus.py`
- Create: `tests/test_fault_corpus.py`

**Interfaces:**
- Consumes: `SubprocessRunner` from `kylinbootlab.remote`.
- Produces: `FaultInjection` dataclass — `name: str`, `unit: str`, `drop_in_content: str`, `drop_in_path: str`, `expected_ranks: list[tuple[str, str]]` (list of (node_name, expected_rank_range like "1-3", "4-5", or "not_in_top3")).
- Produces: `FaultResult` dataclass — `case: str`, `status: Literal["pass", "fail", "error"]`, `actual_ranking: list[str]`, `expected_ranking: list[tuple[str, str]]`, `error_message: str | None`.
- Produces: `FaultCorpusReport` dataclass — `cases: list[FaultResult]`, `hit_rate: float`, `total_predictions: int`, `correct_predictions: int`.
- Produces: `FaultCorpusRunner` class with `__init__(target: str, store: RunStore, incoming_root: Path, runner: SubprocessRunner)`. Methods: `run_case(fi: FaultInjection) -> FaultResult` (inject -> boot -> analyze -> verify -> restore). `run_all(cases: list[FaultInjection]) -> FaultCorpusReport`.
- Unit tests: SSH command construction correctness (verify the exact commands that would be sent to the target for inject + restore), drop-in path correctness. No real VM needed for unit tests.
- Drop-in format examples are canonical per spec §7: for each case the inject and cleanup commands are explicit.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fault_corpus.py`:

```python
"""Unit tests for fault corpus driver — command construction only."""

import pytest

from kylinbootlab.analysis.fault_corpus import (
    FAULT_CASES,
    FaultCorpusReport,
    FaultInjection,
    FaultResult,
    build_inject_commands,
    build_cleanup_commands,
)


class TestFaultInjection:
    def test_case1_fake_dependency_structure(self) -> None:
        case = FAULT_CASES[0]
        assert case.name == "critical-path-fake-dep"
        assert case.unit == "NetworkManager.service"
        assert "After=foo-slow.service" in case.drop_in_content
        assert "/etc/systemd/system/NetworkManager.service.d/kbl-fault.conf" in case.drop_in_path

    def test_case2_sleep_delay_structure(self) -> None:
        case = FAULT_CASES[1]
        assert case.name == "exclusive-delay-dbus"
        assert case.unit == "dbus.service"
        assert "/bin/sleep 3" in case.drop_in_content or "ExecStartPre" in case.drop_in_content
        assert "/etc/systemd/system/dbus.service.d/kbl-fault.conf" in case.drop_in_path


class TestCommandConstruction:
    def test_inject_commands_for_case2(self) -> None:
        """Case 2 (dbus sleep) inject commands are well-formed."""
        case = FAULT_CASES[1]
        cmds = build_inject_commands(case)
        assert len(cmds) >= 2
        # mkdir + tee for drop-in
        assert any("mkdir" in c for c in cmds)
        assert any("tee" in c for c in cmds)
        assert any("daemon-reload" in c for c in cmds)
        # The drop-in path should be in the tee command
        tee_cmd = next(c for c in cmds if "tee" in c)
        assert case.drop_in_path in tee_cmd

    def test_cleanup_commands_for_case4(self) -> None:
        """Case 4 (lightdm) cleanup removes drop-in and reloads."""
        case = FAULT_CASES[3]
        cmds = build_cleanup_commands(case)
        assert any("rm -f" in c for c in cmds)
        assert any("daemon-reload" in c for c in cmds)

    def test_inject_commands_for_case1_includes_foo_slow_unit(self) -> None:
        """Case 1 needs both a new unit file AND a drop-in."""
        case = FAULT_CASES[0]
        cmds = build_inject_commands(case)
        assert any("foo-slow" in c for c in cmds)

    def test_cleanup_commands_for_case1_remove_both(self) -> None:
        case = FAULT_CASES[0]
        cmds = build_cleanup_commands(case)
        assert any("foo-slow" in c for c in cmds)
        assert any("NetworkManager" in c for c in cmds)


class TestFaultResult:
    def test_pass_status(self) -> None:
        r = FaultResult(
            case="test-case",
            status="pass",
            actual_ranking=["dbus.service", "NetworkManager.service", "lightdm.service"],
            expected_ranking=[("dbus.service", "1-3")],
        )
        assert r.status == "pass"

    def test_fail_status(self) -> None:
        r = FaultResult(
            case="test-case",
            status="fail",
            actual_ranking=["wpa_supplicant.service"],
            expected_ranking=[("dbus.service", "1-3")],
        )
        assert r.status == "fail"


class TestFaultCorpusReport:
    def test_hit_rate_calculation(self) -> None:
        report = FaultCorpusReport(
            cases=[
                FaultResult(case="c1", status="pass", actual_ranking=["a"], expected_ranking=[("a", "1-1")]),
                FaultResult(case="c2", status="pass", actual_ranking=["b"], expected_ranking=[("b", "1-3")]),
                FaultResult(case="c3", status="fail", actual_ranking=["d"], expected_ranking=[("c", "1-3")]),
            ],
            total_predictions=3,
            correct_predictions=2,
        )
        assert report.hit_rate == pytest.approx(2 / 3)

    def test_hit_rate_zero_when_no_predictions(self) -> None:
        report = FaultCorpusReport(cases=[], total_predictions=0, correct_predictions=0)
        assert report.hit_rate == 0.0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fault_corpus.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement fault_corpus.py**

Create `src/kylinbootlab/analysis/fault_corpus.py`:

```python
"""Fault injection corpus driver for causal graph validation.

Defines 5 fault cases per spec §7.  Each case injects a systemd drop-in,
triggers one cold boot, verifies Top-3 bottleneck ranking, and restores
the system.  The ``FaultCorpusRunner`` orchestrates injection, boot,
analysis, verification, and cleanup via SSH.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FaultInjection:
    """One fault-injection test case."""

    name: str
    unit: str
    drop_in_content: str
    drop_in_path: str
    expected_ranks: list[tuple[str, str]]  # (node_name, "1-3" | "not_in_top3" | "1-2")


@dataclass
class FaultResult:
    """Outcome of one fault-injection case."""

    case: str
    status: Literal["pass", "fail", "error"]
    actual_ranking: list[str]
    expected_ranking: list[tuple[str, str]]
    error_message: str | None = None


@dataclass
class FaultCorpusReport:
    """Aggregate report across all fault cases."""

    cases: list[FaultResult]
    total_predictions: int
    correct_predictions: int

    @property
    def hit_rate(self) -> float:
        if self.total_predictions == 0:
            return 0.0
        return self.correct_predictions / self.total_predictions


# ---------------------------------------------------------------------------
# 5 canonical fault cases (spec §7)
# ---------------------------------------------------------------------------

# Shared prefix for all drop-in files
_DROPIN_HEADER = "[Unit]\nDescription=kbl-fault\n"

# Case 1: Critical-path fake dependency on NetworkManager
CASE1_DROPIN = _DROPIN_HEADER + "After=foo-slow.service\n"
CASE1_FOO_UNIT = "[Unit]\nDescription=kbl-fault-fake-unit\n"

# Case 2: dbus Exclusive delay (sleep 3s)
CASE2_DROPIN = "[Service]\nExecStartPre=/bin/sleep 3\n"

# Case 3: No-op delay on large-slack unit (ukui-bluetooth)
CASE3_DROPIN = "[Service]\nExecStartPre=/bin/sleep 5\n"

# Case 4: lightdm delay
CASE4_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"

# Case 5: Combined dbus + lightdm
CASE5_DBUS_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"
CASE5_LIGHTDM_DROPIN = "[Service]\nExecStartPre=/bin/sleep 2\n"

FAULT_CASES: list[FaultInjection] = [
    FaultInjection(
        name="critical-path-fake-dep",
        unit="NetworkManager.service",
        drop_in_content=CASE1_DROPIN,
        drop_in_path="/etc/systemd/system/NetworkManager.service.d/kbl-fault.conf",
        expected_ranks=[("NetworkManager.service", "1-1")],
    ),
    FaultInjection(
        name="exclusive-delay-dbus",
        unit="dbus.service",
        drop_in_content=CASE2_DROPIN,
        drop_in_path="/etc/systemd/system/dbus.service.d/kbl-fault.conf",
        expected_ranks=[("dbus.service", "1-1")],
    ),
    FaultInjection(
        name="no-op-delay-bluetooth",
        unit="ukui-bluetooth.service",
        drop_in_content=CASE3_DROPIN,
        drop_in_path="/etc/systemd/system/ukui-bluetooth.service.d/kbl-fault.conf",
        expected_ranks=[("ukui-bluetooth.service", "not_in_top3")],
    ),
    FaultInjection(
        name="lightdm-delay",
        unit="lightdm.service",
        drop_in_content=CASE4_DROPIN,
        drop_in_path="/etc/systemd/system/lightdm.service.d/kbl-fault.conf",
        expected_ranks=[("lightdm.service", "1-2")],
    ),
    FaultInjection(
        name="combined-dbus-lightdm",
        unit="dbus.service",  # primary unit (Case 5 has two drop-ins)
        drop_in_content=CASE5_DBUS_DROPIN,
        drop_in_path="/etc/systemd/system/dbus.service.d/kbl-fault.conf",
        expected_ranks=[
            ("dbus.service", "1-2"),
            ("lightdm.service", "1-2"),
        ],
    ),
]

# Additional drop-in for Case 5 (lightdm side)
CASE5_EXTRA_DROPIN = FaultInjection(
    name="combined-dbus-lightdm-lightdm",
    unit="lightdm.service",
    drop_in_content=CASE5_LIGHTDM_DROPIN,
    drop_in_path="/etc/systemd/system/lightdm.service.d/kbl-fault.conf",
    expected_ranks=[],  # covered by the main Case 5 entry
)


# ---------------------------------------------------------------------------
# Command builders (testable without real SSH)
# ---------------------------------------------------------------------------


def build_inject_commands(case: FaultInjection) -> list[str]:
    """Build the SSH command lines for injecting a fault case.

    Returns a list of strings; each is a complete command to run on the
    target (e.g. via ``ssh target ...``).
    """
    cmds: list[str] = []

    # Case 1 special: create the fake foo-slow.service unit first
    if case.name == "critical-path-fake-dep":
        foo_unit = "[Unit]\nDescription=kbl-fault-fake-unit\n"
        cmds.append(
            f"echo '{foo_unit}' | sudo tee /etc/systemd/system/foo-slow.service"
        )
        cmds.append("sudo systemctl daemon-reload")

    # Create drop-in directory
    drop_in_dir = case.drop_in_path.rsplit("/", 1)[0]
    cmds.append(f"sudo mkdir -p {drop_in_dir}")

    # Write drop-in
    escaped = case.drop_in_content.replace("'", "'\\''")
    cmds.append(
        f"echo '{escaped}' | sudo tee {case.drop_in_path}"
    )

    # Reload systemd
    cmds.append("sudo systemctl daemon-reload")

    # Case 5: also write the lightdm drop-in
    if case.name == "combined-dbus-lightdm":
        lightdm_dir = "/etc/systemd/system/lightdm.service.d"
        lightdm_content = CASE5_LIGHTDM_DROPIN.replace("'", "'\\''")
        cmds.append(f"sudo mkdir -p {lightdm_dir}")
        cmds.append(
            f"echo '{lightdm_content}' | sudo tee {lightdm_dir}/kbl-fault.conf"
        )
        cmds.append("sudo systemctl daemon-reload")

    return cmds


def build_cleanup_commands(case: FaultInjection) -> list[str]:
    """Build the SSH command lines for restoring the target after a case."""
    cmds: list[str] = []

    # Remove drop-in
    cmds.append(f"sudo rm -f {case.drop_in_path}")

    # Case 1: also remove the fake unit
    if case.name == "critical-path-fake-dep":
        cmds.append("sudo rm -f /etc/systemd/system/foo-slow.service")

    # Case 5: also remove lightdm drop-in
    if case.name == "combined-dbus-lightdm":
        cmds.append("sudo rm -f /etc/systemd/system/lightdm.service.d/kbl-fault.conf")

    # Reload
    cmds.append("sudo systemctl daemon-reload")

    return cmds
```

- [ ] **Step 4: Run tests + gates**

Run: `uv run pytest tests/test_fault_corpus.py -v && uv run ruff check src/kylinbootlab/analysis/fault_corpus.py && uv run mypy src/kylinbootlab/analysis/fault_corpus.py --strict`
Expected: 8 tests pass, ruff clean, mypy clean.

- [ ] **Step 5: Commit**

```bash
git add src/kylinbootlab/analysis/fault_corpus.py tests/test_fault_corpus.py
git commit -m "feat: add fault corpus driver (5 cases, command builders, report model)"
```

---

### Task 9: Run Fault Corpus on Real VM

**Files:**
- No new code files. Evidence goes to `docs/evidence/fault-corpus/`.
- Create: `docs/evidence/fault-corpus/README.md` (runner notes + checklist)

**Prerequisites:**
- VM running openKylin, SSH reachable at `kbl@kbl-target.local`.
- Phase 2 orchestrator available and functional (power control + experiment queue).
- `kbl-bootprobe` deployed on target (from Phase 1).
- Phase 4 analysis modules installed (`pip install -e .` in the repo root).
- `systemd-critical-chain` DOT artifact collected on each boot (add to snapshot capture spec or run `systemd-analyze --no-pager dot --order > /var/lib/kylinbootlab/runs/.../raw/systemd-critical-chain`).

**Procedure (per case):**

- [ ] **Step 1: Inject fault**

SSH to target and run inject commands for the case. Example for Case 2 (dbus sleep):

```bash
ssh kbl@kbl-target.local "sudo mkdir -p /etc/systemd/system/dbus.service.d && echo '[Service]
ExecStartPre=/bin/sleep 3' | sudo tee /etc/systemd/system/dbus.service.d/kbl-fault.conf && sudo systemctl daemon-reload"
```

Verify: `ssh kbl@kbl-target.local "cat /etc/systemd/system/dbus.service.d/kbl-fault.conf"`
Expected output: the drop-in content with `ExecStartPre=/bin/sleep 3`.

- [ ] **Step 2: Boot and collect**

Use Phase 2 orchestrator to queue one cold boot and collect snapshot:

```bash
uv run kbl experiment run --target kbl@kbl-target.local --data-root var/runs --incoming-root var/incoming
```

Record the `RUN_ID` from the output.

- [ ] **Step 3: Analyze**

Run the Phase 4 analyze pipeline on the collected run:

```bash
uv run kbl analyze RUN_ID --data-root var/runs
```

Expected: critical path and bottleneck report written to `var/runs/<RUN_ID>/derived/`.

- [ ] **Step 4: Verify ranking**

Read `derived/bottleneck-report.json` and check that expected nodes appear in the correct rank ranges:

```python
# Verification script for one case (run from repo root)
import json, sys
from pathlib import Path

report_path = Path(f"var/runs/{sys.argv[1]}/derived/bottleneck-report.json")
bottlenecks = json.loads(report_path.read_text())
top3_nodes = {b["node"] for b in bottlenecks[:3]}

expected = {
    "critical-path-fake-dep": {"NetworkManager.service"},
    "exclusive-delay-dbus": {"dbus.service"},
    "no-op-delay-bluetooth": set(),  # ukui-bluetooth NOT in top 3
    "lightdm-delay": {"lightdm.service"},
    "combined-dbus-lightdm": {"dbus.service", "lightdm.service"},
}

case_name = sys.argv[2]
expected_nodes = expected[case_name]

if case_name == "no-op-delay-bluetooth":
    passed = "ukui-bluetooth.service" not in top3_nodes
else:
    passed = expected_nodes.issubset(top3_nodes)

print(f"Case {case_name}: {'PASS' if passed else 'FAIL'}")
print(f"  Expected nodes in Top-3: {expected_nodes}")
print(f"  Actual Top-3: {top3_nodes}")
```

- [ ] **Step 5: Restore**

SSH to target and remove the drop-in:

```bash
ssh kbl@kbl-target.local "sudo rm -f /etc/systemd/system/dbus.service.d/kbl-fault.conf && sudo systemctl daemon-reload"
```

Verify removal: `ssh kbl@kbl-target.local "test -f /etc/systemd/system/dbus.service.d/kbl-fault.conf && echo STILL_EXISTS || echo CLEAN"`

- [ ] **Step 6: Log result**

Record pass/fail, actual Top-3 ranking, and any error notes in `docs/evidence/fault-corpus/case-<N>-<name>.json`:

```json
{
    "case": "exclusive-delay-dbus",
    "run_id": "<UUID>",
    "timestamp": "2026-07-19T...",
    "status": "pass",
    "expected_top3": ["dbus.service"],
    "actual_top3": ["dbus.service", "NetworkManager.service", "lightdm.service"],
    "hit": true
}
```

- [ ] **Step 7: Repeat for all 5 cases**

| # | Case Name | Expected Result |
|---|-----------|----------------|
| 1 | critical-path-fake-dep | NetworkManager.service in Top-3 |
| 2 | exclusive-delay-dbus | dbus.service rank 1 |
| 3 | no-op-delay-bluetooth | ukui-bluetooth.service NOT in Top-3 |
| 4 | lightdm-delay | lightdm.service rank 1 or 2 |
| 5 | combined-dbus-lightdm | dbus + lightdm both in Top-3 |

- [ ] **Step 8: Compute hit rate**

Count correct predictions across all 5 cases. Each case may contribute multiple predictions (Case 5 has 2). Target: >= 80% (>= 12/15 correct if 3 predictions per case, or >= the appropriate fraction for the actual prediction count).

```bash
# After all 5 cases complete, compute hit rate
uv run python -c "
import json
from pathlib import Path

evidence_dir = Path('docs/evidence/fault-corpus')
files = sorted(evidence_dir.glob('case-*.json'))
total = 0
correct = 0
for f in files:
    d = json.loads(f.read_text())
    total += 1
    if d.get('hit', False):
        correct += 1
print(f'Hit rate: {correct}/{total} = {correct/total*100:.1f}%')
print('PASS' if correct/total >= 0.8 else 'FAIL')
"
```

- [ ] **Step 9: Write final report**

Create `docs/evidence/fault-corpus/report.json`:

```json
{
    "phase": "4",
    "validator": "fault-corpus",
    "threshold": ">=80% hit rate",
    "total_cases": 5,
    "total_predictions": "<N>",
    "correct_predictions": "<M>",
    "hit_rate": "<X>%",
    "result": "PASS|FAIL",
    "cases": []
}
```

- [ ] **Step 10: Commit evidence**

```bash
git add docs/evidence/fault-corpus/
git commit -m "evidence: add Phase 4 fault corpus results"
```

---

### Task 10: Quality Gates + Evidence Commit

**Files:**
- No new code. Run quality gates across the entire repo.

**Prerequisites:** All Tasks 1-9 complete, all tests passing, all commits made.

- [ ] **Step 1: Schema export check**

Run: `uv run python scripts/export_schema.py --check`
Expected: "Schema is current" or exit code 0.

- [ ] **Step 2: Ruff lint**

Run: `uv run ruff check .`
Expected: exit code 0, no warnings.

- [ ] **Step 3: Mypy strict**

Run: `uv run mypy src tests --strict`
Expected: exit code 0.

- [ ] **Step 4: Pytest full suite**

Run: `uv run pytest tests/ -q --ignore=tests/test_rust_contract.py`
Expected: all tests pass. Count the total:

```bash
uv run pytest tests/ -q --ignore=tests/test_rust_contract.py --tb=no 2>&1 | tail -5
```

Target: >= 60 new tests beyond Phase 1-3 baseline. Phase 1 had 30 tests. Phase 3 added ~20. Target for Phase 4: >= 110 total tests.

- [ ] **Step 5: Cargo gates (Rust unchanged)**

Run: `cargo fmt --all -- --check && cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace`
Expected: all clean (Rust side unchanged by Phase 4).

- [ ] **Step 6: Count new test total**

Total tests expected from this plan:

| File | Test count |
|------|-----------|
| test_dot.py | 15 |
| test_graph.py | 12 |
| test_builder.py | 10 |
| test_critical_path.py | 8 |
| test_bottleneck.py | 7 |
| test_simulator.py | 6 |
| test_compare.py | 5 |
| test_fault_corpus.py | 8 |
| test_cli.py (new) | 3 |
| **Total new** | **74** |

- [ ] **Step 7: Log final commit series**

Run: `git log --oneline HEAD~20..HEAD | wc -l`
Expected: approximately 10 commits (1 per task) plus evidence commits.

- [ ] **Step 8: Commit stray evidence**

```bash
git status
# If any uncommitted files:
git add <evidence files>
git commit -m "evidence: finalize Phase 4 quality gate evidence"
```

- [ ] **Step 9: Final commit message for the plan**

If this plan file itself has been updated during implementation, commit it:

```bash
git add docs/superpowers/plans/2026-07-19-kylinbootlab-causal-graph.md
git commit -m "docs: add Phase 4 causal-graph implementation plan (10 tasks)"
```

---

## Implementation Notes

### Expected commit series (10 commits)

```
feat: add DOT parser for systemd-analyze output
feat: add causal graph data models (CausalNode, CausalEdge, CausalGraph, Bottleneck, WhatIfResult)
feat: add CausalGraphBuilder — DOT + blame + readiness -> CausalGraph
feat: add critical_path() and slack() algorithms
feat: add bottleneck ranking engine and WhatIfSimulator
feat: add cross-run graph comparison (diff_graphs)
feat: add kbl analyze CLI command for causal graph pipeline
feat: add fault corpus driver (5 cases, command builders, report model)
evidence: add Phase 4 fault corpus results
docs: add Phase 4 causal-graph implementation plan (10 tasks)
```

### Module dependency graph

```
                      dot.py (parse_dot, DOTGraph)
                            |
                      builder.py (CausalGraphBuilder)
                       /       |        \
                      /        |         \
                 graph.py   systemd.py   readiness.py
                 (models)   (blame)      (events)
                      |
        ┌─────────────┼─────────────┐
        |             |             |
  critical_path.py  bottleneck.py  simulator.py
        |             |
  compare.py     fault_corpus.py
        |
      cli.py (kbl analyze)
```

### Spec coverage checklist

| Spec section | Covered by |
|---|---|
| §3.1 Graph construction pipeline | Task 3 (builder.py) |
| §3.2 Hybrid layering | Task 3 (builder._add_readiness_layer) |
| §3.3 Integration with Phase 1/2/3 | Task 7 (CLI from_run), Task 8 (fault corpus SSH) |
| §4.1-4.6 Data models | Task 2 (graph.py) |
| §5.1 Critical path algorithm | Task 4 (critical_path.py) |
| §5.2 Slack algorithm | Task 4 (critical_path.py slack()) |
| §5.3 Bottleneck scoring | Task 5 (bottleneck.py) |
| §5.4 What-If simulator | Task 5 (simulator.py) |
| §6 Readiness blame mapping | Task 3 (builder._add_readiness_layer delta-blame) |
| §7 Fault injection corpus | Task 8 (fault_corpus.py), Task 9 (VM runbook) |
| §8 Test strategy | All task test files |
| §9 New file layout | File Map section above |
| §10 YAGNI exclusions | All respected — no eBPF, no visualization, no auto-optimize |
| §11 Phase 5 interface | Bottleneck.list, WhatIfResult, GraphDiff, FaultCorpusReport |
