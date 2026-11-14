from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from conftest import build_diamond
from gitgraph.collector import collect
from gitgraph.graph import build_graph
from gitgraph.layout import LayoutOptions, build_layout
from gitgraph.theme import DEFAULT_PALETTE
from gitrepo import GitRepo
from invariants import check_graph, check_layout, node_by_subject
from synthetic import make_snapshot, sha_of
from test_graph import random_dag


def layout_of(snap, **opts):  # type: ignore[no-untyped-def]
    graph = build_graph(snap)
    return graph, build_layout(snap, graph, LayoutOptions(**opts))


def test_linear_history_is_one_column() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (1,)}, {"main": 2})
    graph, layout = layout_of(snap)
    check_layout(layout, graph)
    assert {n.column for n in layout.nodes} == {0}
    assert [n.subject for n in layout.nodes] == ["commit 2", "commit 1", "commit 0"]
    assert layout.nodes[-1].kind == "root"


def test_newest_on_top_root_at_bottom_in_real_repo(repo: GitRepo) -> None:
    shas = build_diamond(repo)
    snap = collect(repo.root)
    graph = build_graph(snap)
    layout = build_layout(snap, graph)
    check_graph(graph)
    check_layout(layout, graph)
    assert layout.nodes[0].sha == shas["M"]
    assert layout.nodes[-1].sha == shas["a"]
    assert layout.nodes[0].kind == "merge"


def test_primary_branch_gets_column_zero_even_if_not_newest() -> None:
    # topic tip is newer than main tip, yet main keeps column 0
    snap = make_snapshot(
        {0: (), 1: (0,), 2: (1,), 3: (1,)}, {"main": 2, "topic": 3}, times={3: 1_800_000_000}
    )
    graph, layout = layout_of(snap)
    check_layout(layout, graph)
    by_sha = {n.sha: n for n in layout.nodes}
    assert by_sha[sha_of(2)].column == 0
    assert by_sha[sha_of(3)].column > 0
    assert by_sha[sha_of(1)].column == 0


def test_branch_lane_keeps_its_colour_and_primary_is_first_palette_entry() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (1,), 3: (1,)}, {"main": 2, "topic": 3})
    _graph, layout = layout_of(snap)
    by_sha = {n.sha: n for n in layout.nodes}
    assert by_sha[sha_of(2)].color == DEFAULT_PALETTE[0]
    assert by_sha[sha_of(3)].color != by_sha[sha_of(2)].color
    edge = next(e for e in layout.edges if e.child == sha_of(3))
    assert edge.color == by_sha[sha_of(3)].color  # divergence line keeps the branch colour


def test_unnamed_history_is_muted_and_dashed_not_invented() -> None:
    # 3 merges 2 (side line); no ref points into the side line
    snap = make_snapshot({0: (), 1: (0,), 2: (0,), 3: (1, 2)}, {"main": 3})
    _graph, layout = layout_of(snap)
    side = next(n for n in layout.nodes if n.sha == sha_of(2))
    assert side.lane is None
    assert side.dash is not None
    assert [lane.label for lane in layout.lanes] == ["main"]
    assert layout.legend[-1].text == "unnamed history"


def test_colour_of_existing_branches_is_stable_when_unrelated_branch_added() -> None:
    base = {0: (), 1: (0,), 2: (1,), 3: (1,), 4: (1,)}
    one = make_snapshot(base, {"main": 2, "alpha": 3})
    two = make_snapshot(base, {"main": 2, "alpha": 3, "zeta": 4})
    _, l1 = layout_of(one)
    _, l2 = layout_of(two)
    colours1 = {lane.label: lane.color for lane in l1.lanes}
    colours2 = {lane.label: lane.color for lane in l2.lanes}
    assert colours1["main"] == colours2["main"]
    assert colours1["alpha"] == colours2["alpha"]


def test_more_branches_than_palette_colours_use_dash_as_secondary_cue() -> None:
    parents = {0: ()}
    branches = {"main": 0}
    for i in range(1, 14):
        parents[i] = (0,)
        branches[f"b{i:02d}"] = i
    graph, layout = layout_of(make_snapshot(parents, branches))
    check_layout(layout, graph)
    keys = {(lane.color, lane.dash) for lane in layout.lanes}
    assert len(keys) == len(layout.lanes)  # every lane differs in colour or dash


def test_long_label_expands_row_and_never_overlaps_neighbours() -> None:
    long = "word " * 80
    snap = make_snapshot({0: (), 1: (0,), 2: (1,)}, {"main": 2}, subjects={1: long})
    graph, layout = layout_of(snap, max_label_lines=3)
    check_layout(layout, graph)
    middle = layout.nodes[1]
    assert len(middle.lines) == 3
    assert middle.lines[-1].endswith("…")
    assert middle.label_height > layout.nodes[0].label_height


def test_long_unbroken_text_and_thai_are_wrapped() -> None:
    snap = make_snapshot(
        {0: (), 1: (0,)}, {"main": 1}, subjects={1: "ก" * 300, 0: "https://" + "a" * 400}
    )
    graph, layout = layout_of(snap, max_label_lines=2)
    check_layout(layout, graph)
    for n in layout.nodes:
        assert len(n.lines) <= 2


def test_full_message_mode_includes_body(repo: GitRepo) -> None:
    repo.commit("Subject\n\nBody sentence here.")
    snap = collect(repo.root)
    graph = build_graph(snap)
    subject_only = build_layout(snap, graph, LayoutOptions())
    full = build_layout(snap, graph, LayoutOptions(message_mode="full"))
    assert subject_only.nodes[0].lines == ("Subject",)
    assert full.nodes[0].lines == ("Subject", "Body sentence here.")


def test_tags_become_badges_and_latest_is_flagged(repo: GitRepo) -> None:
    repo.commit("one")
    repo.tag("v1.0.0")
    repo.commit("two")
    repo.tag("v1.10.0", annotated=True)
    repo.commit("three")
    repo.tag("v1.9.0")
    snap = collect(repo.root)
    graph = build_graph(snap)
    layout = build_layout(snap, graph)
    assert layout.release is not None and layout.release.name == "v1.10.0"
    kinds = {b.text: b.kind for n in layout.nodes for b in n.badges}
    assert kinds["v1.10.0"] == "latest-tag"
    assert kinds["v1.9.0"] == "tag"
    # the tagged commit stays at its true position (not pinned to the top)
    two = node_by_subject(layout, "two")
    assert two.row == 1
    assert layout.release.sha == two.sha


def test_many_badges_are_summarised() -> None:
    snap = make_snapshot({0: ()}, {"main": 0}, tags={f"t{i}": 0 for i in range(20)})
    graph, layout = layout_of(snap)
    texts = [b.text for b in layout.nodes[0].badges]
    assert any(t.startswith("+") and "more" in t for t in texts)
    check_layout(layout, graph)


def test_shallow_boundary_is_marked_not_called_initial() -> None:
    snap = make_snapshot({5: (), 6: (5,)}, {"main": 6}, shallow_boundary=frozenset({sha_of(5)}))
    _graph, layout = layout_of(snap)
    assert layout.nodes[-1].kind == "boundary"
    assert any("shallow" in n.text.lower() for n in layout.notes)
    assert not any(n.text.startswith("End of graph \u00b7 initial commit") for n in layout.notes)


def test_multiple_roots_note_does_not_invent_shared_initial_commit() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (), 3: (2,)}, {"a": 1, "b": 3})
    graph, layout = layout_of(snap)
    check_layout(layout, graph)
    text = " ".join(n.text for n in layout.notes)
    assert "2 root commit" in text and "unrelated" in text


def test_missing_parent_gets_stub_edge() -> None:
    snap = make_snapshot({5: (4,), 6: (5,)}, {"main": 6})
    graph, layout = layout_of(snap)
    check_layout(layout, graph)
    assert [e.kind for e in layout.edges if e.child == sha_of(5)] == ["missing"]


def test_empty_snapshot_has_fallback() -> None:
    snap = make_snapshot({}, {})
    _graph, layout = layout_of(snap)
    assert layout.nodes == ()
    assert layout.empty_message
    assert layout.height > 0


def test_layout_is_deterministic() -> None:
    parents, branches, times = random_dag(7, 40)
    snap = make_snapshot(parents, branches, times=times)
    _, a = layout_of(snap)
    _, b = layout_of(snap)
    assert a == b


@settings(max_examples=80, deadline=None)
@given(st.integers(0, 10_000), st.integers(1, 70))
def test_random_dags_produce_valid_layouts(seed: int, size: int) -> None:
    parents, branches, times = random_dag(seed, size)
    snap = make_snapshot(parents, branches, times=times)
    graph, layout = layout_of(snap)
    check_graph(graph)
    check_layout(layout, graph)


@settings(max_examples=30, deadline=None)
@given(st.integers(0, 10_000), st.integers(2, 40))
def test_random_dags_with_truncation_are_valid(seed: int, size: int) -> None:
    parents, branches, times = random_dag(seed, size)
    snap = make_snapshot(parents, branches, times=times)
    graph = build_graph(snap, max_commits=max(1, size // 2))
    layout = build_layout(snap, graph)
    check_graph(graph)
    check_layout(layout, graph)


def test_stacked_branch_keeps_its_own_lane(repo: GitRepo) -> None:
    repo.commit("m1")
    repo.branch("develop")
    repo.commit("dev1")
    repo.commit("dev2")
    repo.branch("a-feature")  # alphabetically before "develop"
    repo.commit("feat1")
    repo.checkout("main")
    repo.commit("m2")
    snap = collect(repo.root)
    graph = build_graph(snap)
    layout = build_layout(snap, graph)
    check_layout(layout, graph)
    lane_of = {n.subject: n.lane for n in layout.nodes}
    assert lane_of == {
        "m2": "main",
        "feat1": "a-feature",
        "dev2": "develop",
        "dev1": "develop",
        "m1": "main",
    }
    assert {lane.label for lane in layout.lanes} == {"main", "develop", "a-feature"}
