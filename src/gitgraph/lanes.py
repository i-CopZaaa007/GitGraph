"""Branch ownership, lane colours and column assignment. Geometry-free.

Ownership
    Branch identities are ranked (primary branch first, then oldest tip first, then by name). Each identity walks
    the *first-parent* chain from its tip(s) and claims commits not yet claimed. A local branch
    and its remote-tracking refs share one identity. Commits claimed by nobody (for example the
    commits of a merged-and-deleted branch) stay unattributed: no branch name is invented.
    Ownership selects the colour of the line that carries a commit; it does **not** mean the
    commit belongs only to that branch. Reachability is reported separately by the graph.

Columns
    Commits are processed top to bottom while a list of *slots* tracks the lines currently in
    flight. Each slot waits for one parent commit. A commit takes the column of an incoming slot
    (preferring one whose colour matches its owner, otherwise the leftmost), or a free column if
    it is a tip. Its first parent keeps the commit's column; further parents (merges) open new
    slots to the right. Several slots may wait for the same commit: they converge there, which
    draws a branch rejoining its fork point. At most one commit occupies a row, and a column
    holding a slot never receives a node, so nodes never sit on foreign lines.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from gitgraph.graph import CommitGraph
from gitgraph.models import Reference

DASHES: tuple[str | None, ...] = (None, "7 4", "2 4", "9 3 2 3")
UNATTRIBUTED_DASH = "4 4"


@dataclass(frozen=True, slots=True)
class LaneStyle:
    """Resolved look of a lane."""

    key: str | None  # branch identity; None = unattributed
    color: str
    dash: str | None
    color_index: int


@dataclass(frozen=True, slots=True)
class EdgeRoute:
    child: str
    parent: str | None  # None => parent object not included (stub)
    kind: str  # "parent" (first parent) | "merge" | "missing"
    child_column: int
    travel_column: int
    parent_column: int | None
    style: LaneStyle


@dataclass(frozen=True, slots=True)
class Placement:
    columns: dict[str, int]
    routes: tuple[EdgeRoute, ...]
    column_count: int
    node_styles: dict[str, LaneStyle]
    lane_commit_counts: dict[str, int]
    lane_styles: dict[str, LaneStyle]  # named lanes only, primary first
    has_unattributed: bool
    primary: str | None


def identity_of(ref: Reference) -> str:
    return ref.branch_name


def stable_hash(text: str) -> int:
    return int.from_bytes(hashlib.sha1(text.encode("utf-8")).digest()[:4], "big")


def resolve_primary(
    refs: tuple[Reference, ...],
    configured: str | None,
    default_branch: str | None,
    head_branch: str | None,
) -> str | None:
    names = {identity_of(r) for r in refs}
    for candidate in (configured, default_branch, "main", "master", head_branch):
        if candidate and candidate in names:
            return candidate
    return None


def compute_ownership(
    graph: CommitGraph, refs: tuple[Reference, ...], primary: str | None
) -> tuple[dict[str, str], list[str]]:
    """Return (owner by commit, identity ranking)."""
    position = {sha: i for i, sha in enumerate(graph.order)}
    tips: dict[str, list[str]] = {}
    for ref in refs:
        if ref.target_sha in position:
            tips.setdefault(identity_of(ref), []).append(ref.target_sha)
    # Primary first. Then branches whose tips are *older* claim shared history first, so a branch
    # stacked on another keeps its own lane and only claims its extra commits. Ties by name.
    ranking = sorted(tips, key=lambda k: (k != primary, -max(position[t] for t in tips[k]), k))
    owner: dict[str, str] = {}
    for key in ranking:
        for tip in sorted(set(tips[key]), key=lambda s: position[s]):
            current: str | None = tip
            while current is not None and current not in owner:
                owner[current] = key
                parents = graph.parents[current]
                first = parents[0] if parents else None
                current = first if first in position else None
    return owner, ranking


def assign_styles(
    keys: list[str],
    primary: str | None,
    palette: tuple[str, ...],
) -> dict[str, LaneStyle]:
    """Deterministic colours: the primary gets index 0, others start at a hash-derived index
    and probe to the least-used colour. Reused colours get a different dash pattern."""
    uses = [0] * len(palette)
    styles: dict[str, LaneStyle] = {}
    ordered = ([primary] if primary in keys else []) + sorted(k for k in keys if k != primary)
    for key in ordered:
        if key == primary:
            index = 0
        else:
            start = stable_hash(key) % len(palette)
            probe = [(start + i) % len(palette) for i in range(len(palette))]
            index = min(probe, key=lambda i: uses[i])  # first minimum in probe order
        dash = DASHES[uses[index] % len(DASHES)]
        uses[index] += 1
        styles[key] = LaneStyle(key, palette[index], dash, index)
    return styles


def _slot(slots: list[_Pending | None], index: int) -> _Pending:
    pending = slots[index]
    assert pending is not None
    return pending


@dataclass(slots=True)
class _Pending:
    child: str
    parent: str
    kind: str
    child_column: int
    travel_column: int
    style: LaneStyle
    anon: int


def place(
    graph: CommitGraph,
    refs: tuple[Reference, ...],
    palette: tuple[str, ...],
    muted: tuple[str, ...],
    primary: str | None,
) -> Placement:
    owner, ranking = compute_ownership(graph, refs, primary)
    counts: dict[str, int] = {}
    for owner_key in owner.values():
        counts[owner_key] = counts.get(owner_key, 0) + 1
    named = [k for k in ranking if counts.get(k)]
    lane_styles = assign_styles(named, primary if primary in named else None, palette)

    def style_for(key: str | None, anon: int) -> LaneStyle:
        if key is not None:
            return lane_styles[key]
        idx = anon % len(muted)
        return LaneStyle(None, muted[idx], UNATTRIBUTED_DASH, idx)

    slots: list[_Pending | None] = []
    columns: dict[str, int] = {}
    node_styles: dict[str, LaneStyle] = {}
    routes: list[EdgeRoute] = []
    primary_pending = primary is not None and counts.get(primary, 0) > 0
    max_col = 0
    has_unattributed = False

    for sha in graph.order:
        key: str | None = owner.get(sha)
        incoming = [i for i, s in enumerate(slots) if s is not None and s.parent == sha]
        if incoming:
            preferred = [i for i in incoming if _slot(slots, i).style.key == key]
            column = (preferred or incoming)[0]
            inherited_anon = _slot(slots, column).anon
        else:
            free = [i for i, s in enumerate(slots) if s is None]
            if primary_pending and key != primary:
                if not slots:
                    slots.append(None)  # create column 0, reserved for the primary branch
                free = [i for i in free if i != 0]
            column = free[0] if free else len(slots)
            if column == len(slots):
                slots.append(None)
            inherited_anon = stable_hash(sha)
        if key == primary:
            primary_pending = False
        style = style_for(key, inherited_anon)
        if key is None:
            has_unattributed = True
        node_styles[sha] = style
        columns[sha] = column
        max_col = max(max_col, column)

        for i in incoming:
            pending = slots[i]
            assert pending is not None
            routes.append(
                EdgeRoute(
                    pending.child,
                    sha,
                    pending.kind,
                    pending.child_column,
                    pending.travel_column,
                    column,
                    pending.style,
                )
            )
            slots[i] = None

        for index, parent in enumerate(graph.parents[sha]):
            if parent not in graph.commits:
                routes.append(EdgeRoute(sha, None, "missing", column, column, None, style))
                continue
            if index == 0:
                slots[column] = _Pending(
                    sha, parent, "parent", column, column, style, inherited_anon
                )
                continue
            target = next(
                (i for i in range(column + 1, len(slots)) if slots[i] is None), len(slots)
            )
            if target == len(slots):
                slots.append(None)
            merge_style = style_for(owner.get(parent), stable_hash(parent))
            slots[target] = _Pending(
                sha, parent, "merge", column, target, merge_style, stable_hash(parent)
            )
            max_col = max(max_col, target)

    leftovers = [s for s in slots if s is not None]
    if leftovers:  # pragma: no cover - indicates a bug: every included parent has a row
        raise AssertionError("unresolved lane slots after placement")
    return Placement(
        columns=columns,
        routes=tuple(routes),
        column_count=max_col + 1 if graph.order else 0,
        node_styles=node_styles,
        lane_commit_counts=counts,
        lane_styles=lane_styles,
        has_unattributed=has_unattributed,
        primary=primary,
    )
