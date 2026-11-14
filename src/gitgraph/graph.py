"""Commit DAG: adjacency, roots, merges, topological order and ref reachability.

Invariants of :func:`build_graph` (all covered by tests):

* every included commit appears exactly once in ``order``;
* a commit appears before (above) all of its parents;
* the order is deterministic for identical input;
* parent SHAs absent from the included set are listed in ``missing_parents`` rather than
  silently dropped.

Ordering uses Kahn's algorithm with a max-heap keyed on (committer time, SHA) to break ties
between unrelated commits, plus "chain following": after emitting a commit, its first parent is
emitted immediately if it became ready. This keeps first-parent lines contiguous (like
``git log --topo-order``). Timestamps never override ancestry. Complexity: O((V + E) log V).
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass

from gitgraph.models import Commit, Diagnostic, RepositorySnapshot


class GraphError(ValueError):
    """Raised when commit data cannot form a DAG."""


@dataclass(frozen=True, slots=True)
class CommitGraph:
    commits: dict[str, Commit]
    order: tuple[str, ...]
    parents: dict[str, tuple[str, ...]]
    children: dict[str, tuple[str, ...]]
    missing_parents: dict[str, tuple[str, ...]]
    roots: tuple[str, ...]
    merges: frozenset[str]
    ref_names: tuple[str, ...]
    reach: dict[str, int]
    truncated: bool
    diagnostics: tuple[Diagnostic, ...]

    def refs_reaching(self, sha: str) -> list[str]:
        bits = self.reach.get(sha, 0)
        return [name for i, name in enumerate(self.ref_names) if bits >> i & 1]


def build_graph(snapshot: RepositorySnapshot, *, max_commits: int | None = None) -> CommitGraph:
    """Build the graph for ``snapshot``, optionally keeping only the newest ``max_commits``."""
    commits = snapshot.commits
    parents = {sha: tuple(dict.fromkeys(c.parents)) for sha, c in commits.items()}
    order = _topological_order(commits, parents)

    truncated = False
    diagnostics: list[Diagnostic] = []
    if max_commits is not None and 0 < max_commits < len(order):
        order = order[:max_commits]
        truncated = True
        diagnostics.append(
            Diagnostic(
                "info",
                "truncated",
                f"Showing the newest {max_commits} of {len(commits)} commits in topological order.",
            )
        )
    included = set(order)
    commits = {sha: commits[sha] for sha in order}
    parents = {sha: parents[sha] for sha in order}

    children_acc: dict[str, list[str]] = {sha: [] for sha in order}
    missing: dict[str, tuple[str, ...]] = {}
    for sha in order:
        gone = tuple(p for p in parents[sha] if p not in included)
        if gone:
            missing[sha] = gone
        for p in parents[sha]:
            if p in included:
                children_acc[p].append(sha)
    children = {sha: tuple(kids) for sha, kids in children_acc.items()}

    absent = [s for s, gone in missing.items() for p in gone if p not in snapshot.commits]
    if absent:
        boundary_only = all(s in snapshot.shallow_boundary for s in absent)
        if not boundary_only:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "missing-parents",
                    f"{len(absent)} commit(s) reference parent objects that are not available; "
                    "their lines end in a truncation marker.",
                )
            )

    roots = tuple(s for s in order if not commits[s].parents)
    merges = frozenset(s for s in order if len(parents[s]) > 1)
    ref_names, reach = _reachability(snapshot, order, parents, included)
    return CommitGraph(
        commits=commits,
        order=tuple(order),
        parents=parents,
        children=children,
        missing_parents=missing,
        roots=roots,
        merges=merges,
        ref_names=ref_names,
        reach=reach,
        truncated=truncated,
        diagnostics=tuple(diagnostics),
    )


def _topological_order(
    commits: dict[str, Commit], parents: dict[str, tuple[str, ...]]
) -> list[str]:
    pending: dict[str, int] = dict.fromkeys(commits, 0)
    for plist in parents.values():
        for p in plist:
            if p in pending:
                pending[p] += 1

    def key(sha: str) -> tuple[int, str]:
        return (-commits[sha].committed_at, sha)

    heap = [key(s) for s, n in pending.items() if n == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        _, sha = heapq.heappop(heap)
        current: str | None = sha
        while current is not None:
            order.append(current)
            following: str | None = None
            for index, parent in enumerate(parents[current]):
                if parent not in pending:
                    continue
                pending[parent] -= 1
                if pending[parent] == 0:
                    if index == 0:
                        following = parent
                    else:
                        heapq.heappush(heap, key(parent))
            current = following
    if len(order) != len(commits):
        raise GraphError("commit data contains a cycle; cannot order topologically")
    return order


def _reachability(
    snapshot: RepositorySnapshot,
    order: list[str],
    parents: dict[str, tuple[str, ...]],
    included: set[str],
) -> tuple[tuple[str, ...], dict[str, int]]:
    """Bitset per commit of the branch refs that can reach it (one pass over the DAG)."""
    names = sorted({r.short_name for r in snapshot.refs})
    index = {name: i for i, name in enumerate(names)}
    reach: dict[str, int] = dict.fromkeys(order, 0)
    for ref in snapshot.refs:
        if ref.target_sha in included:
            reach[ref.target_sha] |= 1 << index[ref.short_name]
    for sha in order:
        bits = reach[sha]
        if bits:
            for p in parents[sha]:
                if p in included:
                    reach[p] |= bits
    return tuple(names), reach
