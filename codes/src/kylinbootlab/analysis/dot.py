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
        val = m.group(2).replace('\\"', '"') if m.group(2) is not None else m.group(3)
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
