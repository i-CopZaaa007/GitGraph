from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import build_diamond
from gitgraph.collector import CollectionOptions, GitError, collect
from gitgraph.models import RefKind
from gitrepo import GitRepo


def test_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        collect(tmp_path)


def test_missing_directory(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        collect(tmp_path / "nope")


def test_empty_repository(repo: GitRepo) -> None:
    snap = collect(repo.root)
    assert snap.commits == {}
    assert snap.refs == ()
    assert snap.head_sha is None
    assert any(d.code == "no-refs" for d in snap.diagnostics)


def test_single_commit(repo: GitRepo) -> None:
    sha = repo.commit("initial")
    snap = collect(repo.root)
    assert list(snap.commits) == [sha]
    commit = snap.commits[sha]
    assert commit.is_root and not commit.is_merge
    assert commit.subject == "initial"
    assert commit.author.name == "Test Author"
    assert snap.head_branch == "main"
    assert [r.short_name for r in snap.refs] == ["main"]


def test_merge_commit_parents_keep_git_order(repo: GitRepo) -> None:
    shas = build_diamond(repo)
    snap = collect(repo.root)
    merge = snap.commits[shas["M"]]
    assert merge.is_merge
    assert merge.parents == (shas["m1"], shas["f2"])
    assert len(snap.commits) == 6


def test_octopus_merge(repo: GitRepo) -> None:
    repo.commit("base")
    for name in ("x", "y", "z"):
        repo.branch(name)
        repo.commit(f"work {name}")
        repo.checkout("main")
    merge = repo.merge("x", "y", "z", message="octopus")
    snap = collect(repo.root)
    assert len(snap.commits[merge].parents) == 4


def test_multiline_message_and_body(repo: GitRepo) -> None:
    repo.commit("Subject line\n\nBody paragraph one.\nSecond line.")
    snap = collect(repo.root)
    (commit,) = snap.commits.values()
    assert commit.subject == "Subject line"
    assert commit.body == "Body paragraph one.\nSecond line."


def test_tags_lightweight_and_annotated(repo: GitRepo) -> None:
    first = repo.commit("one")
    repo.tag("light")
    second = repo.commit("two")
    repo.tag("v1.0.0", annotated=True)
    snap = collect(repo.root)
    tags = {t.name: t for t in snap.tags}
    assert tags["light"].annotated is False
    assert tags["light"].target_sha == first
    assert tags["v1.0.0"].annotated is True
    assert tags["v1.0.0"].target_sha == second
    assert tags["v1.0.0"].tagged_at is not None
    assert tags["v1.0.0"].object_sha != second  # tag object differs from commit


def test_tag_on_tag_is_peeled_to_commit(repo: GitRepo) -> None:
    sha = repo.commit("one")
    repo.git("tag", "-a", "inner", "-m", "inner")
    repo.git("tag", "-a", "outer", "-m", "outer", "inner")
    snap = collect(repo.root)
    assert {t.name: t.target_sha for t in snap.tags}["outer"] == sha


def test_tag_pointing_at_tree_is_skipped_with_diagnostic(repo: GitRepo) -> None:
    repo.commit("one")
    tree = repo.git("rev-parse", "HEAD^{tree}")
    repo.git("tag", "treetag", tree)
    snap = collect(repo.root)
    assert all(t.name != "treetag" for t in snap.tags)
    assert any(d.code == "tag-not-commit" for d in snap.diagnostics)


def test_deleted_branch_commits_are_kept_only_if_reachable(repo: GitRepo) -> None:
    repo.commit("base")
    repo.branch("gone")
    orphaned = repo.commit("only on gone")
    repo.checkout("main")
    repo.git("branch", "-D", "gone")
    snap = collect(repo.root)
    assert orphaned not in snap.commits  # no invented history for deleted refs
    assert [r.short_name for r in snap.refs] == ["main"]


def test_deleted_branch_after_merge_leaves_commits_but_no_name(repo: GitRepo) -> None:
    repo.commit("base")
    repo.branch("topic")
    topic_commit = repo.commit("topic work")
    repo.checkout("main")
    repo.commit("main work")
    repo.merge("topic")
    repo.git("branch", "-d", "topic")
    snap = collect(repo.root)
    assert topic_commit in snap.commits
    assert "topic" not in {r.short_name for r in snap.refs}


def test_multiple_roots(repo: GitRepo) -> None:
    root1 = repo.commit("root one")
    repo.orphan("other")
    root2 = repo.commit("root two")
    snap = collect(repo.root)
    assert {c.sha for c in snap.commits.values() if c.is_root} == {root1, root2}


def test_remote_tracking_and_exclusion(make_repo: Callable[[str], GitRepo], tmp_path: Path) -> None:
    origin = make_repo("origin")
    origin.commit("one")
    origin.branch("gitgraph-assets")
    origin.commit("artifact")
    origin.checkout("main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin.root), str(clone)], check=True)
    snap = collect(clone)
    names = {r.short_name: r for r in snap.refs}
    assert "origin/main" in names
    assert names["origin/main"].kind is RefKind.REMOTE_BRANCH
    assert names["origin/main"].branch_name == "main"
    assert "origin/HEAD" not in names  # symbolic alias skipped
    assert "origin/gitgraph-assets" not in names  # generated-artifact refs excluded by default
    assert snap.default_branch == "main"
    everything = collect(clone, CollectionOptions(exclude=()))
    assert "origin/gitgraph-assets" in {r.short_name for r in everything.refs}


def test_include_patterns_and_switches(repo: GitRepo) -> None:
    repo.commit("one")
    repo.branch("release/1.0")
    repo.commit("two")
    repo.tag("v1")
    repo.checkout("main")
    only = collect(repo.root, CollectionOptions(include=("release/*",), tags=False))
    assert [r.short_name for r in only.refs] == ["release/1.0"]
    assert only.tags == ()
    no_branches = collect(repo.root, CollectionOptions(branches=False))
    assert [t.name for t in no_branches.tags] == ["v1"]


def test_detached_head_falls_back_to_head(repo: GitRepo) -> None:
    first = repo.commit("one")
    repo.commit("two")
    repo.git("checkout", "-q", "--detach", first)
    repo.git("branch", "-D", "main")
    snap = collect(repo.root)
    assert [r.short_name for r in snap.refs] == ["HEAD"]
    assert snap.refs[0].kind is RefKind.OTHER


def test_shallow_clone_is_detected(make_repo: Callable[[str], GitRepo], tmp_path: Path) -> None:
    origin = make_repo("origin")
    for i in range(4):
        origin.commit(f"c{i}")
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "2", f"file://{origin.root}", str(clone)], check=True
    )
    snap = collect(clone)
    assert snap.is_shallow
    assert len(snap.commits) == 2
    assert len(snap.shallow_boundary) == 1
    assert any(d.code == "shallow-clone" for d in snap.diagnostics)


def test_shell_metacharacters_in_ref_names_are_data(repo: GitRepo) -> None:
    repo.commit("one")
    repo.git("branch", "feat;touch-pwned&&$(id)")
    snap = collect(repo.root)
    assert "feat;touch-pwned&&$(id)" in {r.short_name for r in snap.refs}
    assert not (repo.root / "touch-pwned").exists()


def test_include_patterns_do_not_drop_tags(repo: GitRepo) -> None:
    repo.commit("one")
    repo.tag("v1")
    repo.branch("other")
    repo.commit("two")
    repo.checkout("main")
    snap = collect(repo.root, CollectionOptions(include=("main",)))
    assert [r.short_name for r in snap.refs] == ["main"]
    assert [t.name for t in snap.tags] == ["v1"]
    assert collect(repo.root, CollectionOptions(exclude=("v*",))).tags == ()


def test_head_fallback_respects_user_choices(repo: GitRepo) -> None:
    repo.commit("one")
    repo.tag("v1")
    only_tags = collect(repo.root, CollectionOptions(branches=False, remotes=False))
    assert only_tags.refs == () and [t.name for t in only_tags.tags] == ["v1"]
    nothing = collect(repo.root, CollectionOptions(branches=False, remotes=False, tags=False))
    assert nothing.commits == {} and nothing.refs == ()
    filtered = collect(repo.root, CollectionOptions(include=("does-not-exist",), tags=False))
    assert filtered.commits == {}
