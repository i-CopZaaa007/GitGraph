from __future__ import annotations

import random

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import build_diamond
from gitgraph.collector import collect
from gitgraph.graph import GraphError, build_graph
from gitgraph.models import RepositorySnapshot
from gitrepo import GitRepo
from invariants import check_graph
from synthetic import make_snapshot, sha_of


def test_linear_history_order() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (1,)}, {"main": 2})
    graph = build_graph(snap)
    assert graph.order == (sha_of(2), sha_of(1), sha_of(0))
    assert graph.roots == (sha_of(0),)
    assert graph.merges == frozenset()
    check_graph(graph)


def test_timestamps_do_not_override_ancestry() -> None:
    # The parent claims to be newer than its child (clock skew).
    snap = make_snapshot({0: (), 1: (0,)}, {"main": 1}, times={0: 2_000_000_000, 1: 1_000_000_000})
    graph = build_graph(snap)
    assert graph.order == (sha_of(1), sha_of(0))


def test_merge_and_octopus_detection_uses_parent_count() -> None:
    snap = make_snapshot(
        {0: (), 1: (0,), 2: (0,), 3: (0,), 4: (1, 2, 3), 5: (4,)},
        {"main": 5},
        subjects={5: "Merge branch 'not-really-a-merge'"},
    )
    graph = build_graph(snap)
    assert graph.merges == frozenset({sha_of(4)})
    assert len(graph.parents[sha_of(4)]) == 3
    check_graph(graph)


def test_first_parent_chain_is_kept_contiguous() -> None:
    #   4 (merge: 3, 2)   main line 4-3-1-0 ; side 2-1
    snap = make_snapshot({0: (), 1: (0,), 2: (1,), 3: (1,), 4: (3, 2)}, {"main": 4})
    graph = build_graph(snap)
    assert graph.order[:2] == (sha_of(4), sha_of(3))
    check_graph(graph)


def test_reachability_is_not_exclusive_ownership() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (1,), 3: (1,)}, {"main": 2, "topic": 3})
    graph = build_graph(snap)
    assert graph.refs_reaching(sha_of(1)) == ["main", "topic"]
    assert graph.refs_reaching(sha_of(2)) == ["main"]
    assert graph.refs_reaching(sha_of(3)) == ["topic"]


def test_multiple_roots() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (), 3: (2,)}, {"a": 1, "b": 3})
    graph = build_graph(snap)
    assert set(graph.roots) == {sha_of(0), sha_of(2)}
    check_graph(graph)


def test_missing_parent_is_reported_not_dropped() -> None:
    snap = make_snapshot({5: (4,), 6: (5,)}, {"main": 6})  # commit 4 is absent
    graph = build_graph(snap)
    assert graph.missing_parents == {sha_of(5): (sha_of(4),)}
    assert any(d.code == "missing-parents" for d in graph.diagnostics)
    check_graph(graph)


def test_cycle_is_rejected() -> None:
    snap = make_snapshot({0: (1,), 1: (0,)}, {"main": 0})
    with pytest.raises(GraphError):
        build_graph(snap)


def test_duplicate_parents_collapse() -> None:
    snap = make_snapshot({0: (), 1: (0, 0)}, {"main": 1})
    graph = build_graph(snap)
    assert graph.parents[sha_of(1)] == (sha_of(0),)
    assert graph.merges == frozenset()


def test_max_commits_truncates_in_topological_order() -> None:
    snap = make_snapshot({i: ((i - 1,) if i else ()) for i in range(10)}, {"main": 9})
    graph = build_graph(snap, max_commits=3)
    assert graph.order == (sha_of(9), sha_of(8), sha_of(7))
    assert graph.truncated
    assert graph.missing_parents == {sha_of(7): (sha_of(6),)}
    assert any(d.code == "truncated" for d in graph.diagnostics)


def test_real_repository_matches_git_topology(repo: GitRepo) -> None:
    shas = build_diamond(repo)
    graph = build_graph(collect(repo.root))
    check_graph(graph)
    assert graph.order[0] == shas["M"]
    assert graph.roots == (shas["a"],)
    assert graph.merges == frozenset({shas["M"]})


def test_same_message_and_time_do_not_merge_commits(repo: GitRepo) -> None:
    repo.commit("same", tick=0)
    repo.commit("same", tick=0)
    graph = build_graph(collect(repo.root))
    assert len(graph.order) == 2


def random_dag(
    seed: int, size: int
) -> tuple[dict[int, tuple[int, ...]], dict[str, int], dict[int, int]]:
    rng = random.Random(seed)
    parents: dict[int, tuple[int, ...]] = {}
    for i in range(size):
        if i == 0 or rng.random() < 0.05:
            parents[i] = ()
            continue
        count = 1 if rng.random() < 0.75 else rng.choice([2, 2, 3])
        pool = list(range(max(0, i - 8), i)) if rng.random() < 0.85 else list(range(i))
        parents[i] = tuple(rng.sample(pool, min(count, len(pool))))
    has_child = {p for plist in parents.values() for p in plist}
    tips = [i for i in parents if i not in has_child] or [size - 1]
    branches = {f"b{k}": tip for k, tip in enumerate(tips[:6])}
    times = {i: rng.randrange(1_600_000_000, 1_800_000_000) for i in parents}  # skewed on purpose
    return parents, branches, times


@settings(max_examples=60, deadline=None)
@given(st.integers(0, 10_000), st.integers(1, 60))
def test_random_dags_satisfy_graph_invariants(seed: int, size: int) -> None:
    parents, branches, times = random_dag(seed, size)
    snap: RepositorySnapshot = make_snapshot(parents, branches, times=times)
    graph = build_graph(snap)
    check_graph(graph)
    assert build_graph(snap).order == graph.order  # deterministic
