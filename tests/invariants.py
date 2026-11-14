"""Reusable structural checks for graphs and layouts."""

from __future__ import annotations

import itertools
import math

from gitgraph.graph import CommitGraph
from gitgraph.layout import GraphEdge, GraphLayout, GraphNode


def check_graph(graph: CommitGraph) -> None:
    assert len(graph.order) == len(set(graph.order)) == len(graph.commits)
    position = {sha: i for i, sha in enumerate(graph.order)}
    for sha in graph.order:
        for parent in graph.parents[sha]:
            if parent in position:
                assert position[sha] < position[parent], "child must precede parent"
                assert sha in graph.children[parent]
            else:
                assert parent in graph.missing_parents[sha]
    for sha, kids in graph.children.items():
        for kid in kids:
            assert sha in graph.parents[kid]
    assert all(not graph.commits[r].parents for r in graph.roots)
    assert all(len(graph.parents[m]) > 1 for m in graph.merges)


def _cubic(
    p0: tuple[float, float], p1: tuple[float, float], steps: int = 24
) -> list[tuple[float, float]]:
    (x0, y0), (x1, y1) = p0, p1
    if x0 == x1:
        return [(x0, y0 + (y1 - y0) * t / steps) for t in range(steps + 1)]
    mid = (y0 + y1) / 2
    out = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u**3 * x0 + 3 * u**2 * t * x0 + 3 * u * t**2 * x1 + t**3 * x1
        y = u**3 * y0 + 3 * u**2 * t * mid + 3 * u * t**2 * mid + t**3 * y1
        out.append((x, y))
    return out


def edge_samples(edge: GraphEdge) -> list[tuple[float, float]]:
    samples: list[tuple[float, float]] = []
    for a, b in zip(edge.points, edge.points[1:], strict=False):
        samples.extend(_cubic(a, b))
    return samples


def check_layout(layout: GraphLayout, graph: CommitGraph) -> None:
    nodes = {n.sha: n for n in layout.nodes}
    assert set(nodes) == set(graph.order), "every commit has exactly one node"
    assert len(layout.nodes) == len(graph.order)
    coords = {(n.x, n.y) for n in layout.nodes}
    assert len(coords) == len(layout.nodes), "node coordinates must be unique"
    # rows strictly ordered and label blocks never overlap
    ordered = list(layout.nodes)
    for upper, lower in itertools.pairwise(ordered):
        assert upper.y < lower.y
        assert upper.label_top + upper.label_height <= lower.label_top + 1e-6
    for n in ordered:
        assert n.label_top >= 0 and n.label_top + n.label_height <= layout.height
        assert n.x + layout.options.node_radius <= n.label_x
    # edges
    expected = sum(len(graph.parents[s]) for s in graph.order)
    assert len(layout.edges) == expected
    for edge in layout.edges:
        child = nodes[edge.child]
        assert edge.points[0] == (child.x, child.y)
        if edge.parent is None:
            assert edge.kind == "missing"
            assert edge.child in graph.missing_parents
            continue
        parent = nodes[edge.parent]
        assert edge.points[-1] == (parent.x, parent.y)
        assert child.y < parent.y, "child above parent"
        ys = [p[1] for p in edge.points]
        assert ys == sorted(ys)
    # no edge passes through the circle of a node it is not attached to
    radius = layout.options.node_radius
    for edge in layout.edges:
        samples = edge_samples(edge)
        for node in layout.nodes:
            if node.sha in (edge.child, edge.parent):
                continue
            nearest = min(math.hypot(node.x - x, node.y - y) for x, y in samples)
            assert nearest >= radius * 0.9, (
                f"edge {edge.child[:7]}->{edge.parent} crosses node {node.sha[:7]}"
            )
    # canvas contains everything
    for node in layout.nodes:
        assert 0 <= node.x < layout.width and 0 <= node.y < layout.height
    for edge in layout.edges:
        assert all(0 <= x <= layout.width and 0 <= y <= layout.height for x, y in edge.points)


def node_by_subject(layout: GraphLayout, subject: str) -> GraphNode:
    for n in layout.nodes:
        if n.subject == subject:
            return n
    raise KeyError(subject)
