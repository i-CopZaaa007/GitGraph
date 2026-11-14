from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from gitgraph.cli import main
from gitgraph.collector import CollectionOptions, collect
from gitgraph.config import Config
from gitgraph.graph import build_graph
from gitgraph.sync import SyncError, sync
from gitrepo import GitRepo

MARKER = "Update & Share Graph"
OPTIONS = CollectionOptions(hide_subject=MARKER, hide_paths=("docs/gitgraph.svg", "README.md"))


def configure(repo: GitRepo) -> None:
    repo.git("config", "user.name", "Test User")
    repo.git("config", "user.email", "user@example.invalid")
    repo.git("config", "commit.gpgsign", "false")


def graph_commit(repo: GitRepo, content: str = "x") -> str:
    (repo.root / "docs").mkdir(exist_ok=True)
    (repo.root / "docs" / "gitgraph.svg").write_text(content, encoding="utf-8")
    repo.git("add", "docs/gitgraph.svg")
    repo.git("commit", "-q", "-m", MARKER)
    return repo.head()


# ---- hiding automatic commits -----------------------------------------------------------------
def test_generated_commits_are_spliced_out(repo: GitRepo) -> None:
    a = repo.commit("a")
    graph_commit(repo, "1")
    b = repo.commit("b")
    graph_commit(repo, "2")  # branch tip is a hidden commit
    snap = collect(repo.root, OPTIONS)
    assert set(snap.commits) == {a, b}
    assert snap.commits[b].parents == (a,)
    assert snap.refs[0].target_sha == b
    assert snap.head_sha == b
    assert any(d.code == "hidden-graph-commits" for d in snap.diagnostics)
    build_graph(snap)


def test_only_exact_generated_commits_are_hidden(repo: GitRepo) -> None:
    repo.commit("a")
    repo.commit(MARKER)  # right message but touches a non-generated file
    graph_commit(repo)
    snap = collect(repo.root, OPTIONS)
    assert len(snap.commits) == 2
    assert collect(repo.root).commits.keys() != snap.commits.keys()  # off by default


def test_merge_with_marker_subject_is_never_hidden(repo: GitRepo) -> None:
    repo.commit("a")
    repo.branch("topic")
    repo.commit("t")
    repo.checkout("main")
    repo.commit("m")
    repo.merge("topic", message=MARKER)
    assert len(collect(repo.root, OPTIONS).commits) == 4


# ---- sync -------------------------------------------------------------------------------------
@pytest.fixture
def initialised(repo: GitRepo) -> GitRepo:
    configure(repo)
    repo.commit("one")
    repo.commit("two")
    assert main(["init", "--repo", str(repo.root)]) == 0
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "add gitgraph")
    return repo


def test_init_is_one_step_setup(repo: GitRepo) -> None:
    repo.commit("one")
    assert main(["init", "--repo", str(repo.root)]) == 0
    assert (repo.root / "gitgraph.toml").exists()
    assert (repo.root / "docs" / "gitgraph.svg").read_text(encoding="utf-8").startswith("<svg")
    readme = (repo.root / "README.md").read_text(encoding="utf-8")
    assert "![Git commit graph](docs/gitgraph.svg)" in readme
    # repeating init is harmless
    before = readme
    assert main(["init", "--repo", str(repo.root)]) == 0
    assert (repo.root / "README.md").read_text(encoding="utf-8") == before


def test_init_flags_skip_steps(repo: GitRepo) -> None:
    repo.commit("one")
    assert main(["init", "--repo", str(repo.root), "--no-readme", "--no-generate"]) == 0
    assert (repo.root / "gitgraph.toml").exists()
    assert not (repo.root / "README.md").exists()
    assert not (repo.root / "docs").exists()


def test_sync_commits_only_generated_files_and_is_idempotent(initialised: GitRepo) -> None:
    repo = initialised
    repo.commit("three")
    result = sync(repo.root, Config())
    assert result.commit is not None
    assert sorted(result.changed) == ["README.md", "docs/gitgraph.svg"] or result.changed == (
        "docs/gitgraph.svg",
    )
    files = repo.git("show", "--name-only", "--format=", "HEAD").split()
    assert set(files) <= {"README.md", "docs/gitgraph.svg"}
    assert repo.git("log", "-1", "--format=%s") == MARKER
    assert repo.git("status", "--porcelain") == ""
    svg = (repo.root / "docs" / "gitgraph.svg").read_text(encoding="utf-8")
    assert "three" in svg and MARKER not in svg
    # fixed point: nothing more to do, no endless chain of graph commits
    count = repo.git("rev-list", "--count", "HEAD")
    again = sync(repo.root, Config())
    assert again.commit is None
    assert repo.git("rev-list", "--count", "HEAD") == count


def test_sync_leaves_other_staged_and_unstaged_work_alone(initialised: GitRepo) -> None:
    repo = initialised
    repo.commit("three")
    (repo.root / "staged.txt").write_text("s", encoding="utf-8")
    repo.git("add", "staged.txt")
    (repo.root / "wip.txt").write_text("w", encoding="utf-8")
    assert sync(repo.root, Config()).commit is not None
    assert "staged.txt" not in repo.git("show", "--name-only", "--format=", "HEAD")
    assert repo.git("diff", "--cached", "--name-only") == "staged.txt"
    assert (repo.root / "wip.txt").exists()


def test_sync_refuses_when_generated_files_are_dirty(initialised: GitRepo) -> None:
    repo = initialised
    repo.commit("three")
    readme = repo.root / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "\nmy unsaved note\n", encoding="utf-8")
    with pytest.raises(SyncError, match="uncommitted"):
        sync(repo.root, Config())
    assert "my unsaved note" in readme.read_text(encoding="utf-8")
    assert repo.git("log", "-1", "--format=%s") == "three"


def test_sync_refuses_detached_head_and_missing_markers(
    initialised: GitRepo, tmp_path: Path
) -> None:
    repo = initialised
    repo.git("checkout", "-q", "--detach")
    with pytest.raises(SyncError, match="detached"):
        sync(repo.root, Config())
    repo.checkout("main")
    (repo.root / "README.md").write_text("# no markers\n", encoding="utf-8")
    repo.git("commit", "-qam", "drop markers")
    with pytest.raises(SyncError, match="markers"):
        sync(repo.root, Config())


def test_sync_refuses_ignored_output(initialised: GitRepo) -> None:
    repo = initialised
    (repo.root / ".gitignore").write_text("docs/\n", encoding="utf-8")
    repo.git("add", ".gitignore")
    repo.git("commit", "-qm", "ignore docs")
    with pytest.raises(SyncError, match="ignored"):
        sync(repo.root, Config())


def test_sync_command_and_push(initialised: GitRepo, tmp_path: Path) -> None:
    repo = initialised
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    repo.git("remote", "add", "origin", str(bare))
    repo.git("push", "-q", "-u", "origin", "main")
    repo.commit("three")
    assert main(["sync", "--repo", str(repo.root), "--push"]) == 0
    remote_head = subprocess.run(
        ["git", "-C", str(bare), "log", "-1", "--format=%s", "main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remote_head == MARKER
    assert main(["sync", "--repo", str(repo.root)]) == 0  # second run: nothing to do


def test_sync_command_reports_errors(
    initialised: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = initialised
    (repo.root / "README.md").write_text("x\n", encoding="utf-8")
    assert main(["sync", "--repo", str(repo.root)]) == 1
    assert "uncommitted" in capsys.readouterr().err


# ---- one-command flow: sync sets everything up -----------------------------------------------
def test_sync_on_a_fresh_repository_sets_up_commits_and_hides_its_commit(
    repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    configure(repo)
    repo.commit("one")
    repo.commit("two")
    assert main(["sync", "--repo", str(repo.root)]) == 0  # no remote: per-branch mode
    err = capsys.readouterr().err
    assert "first run" in err and "local" in err
    assert repo.git("log", "-1", "--format=%s") == MARKER
    files = set(repo.git("show", "--name-only", "--format=", "HEAD").split())
    assert files == {"README.md", "gitgraph.toml", "docs/gitgraph.svg"}
    assert repo.git("status", "--porcelain") == ""
    svg = (repo.root / "docs" / "gitgraph.svg").read_text(encoding="utf-8")
    assert "2 commits" in svg and MARKER not in svg  # its own commit is not drawn
    # nothing more to do the second time
    count = repo.git("rev-list", "--count", "HEAD")
    assert main(["sync", "--repo", str(repo.root)]) == 0
    assert repo.git("rev-list", "--count", "HEAD") == count


def test_sync_setup_refuses_when_readme_has_uncommitted_edits(repo: GitRepo) -> None:
    configure(repo)
    repo.commit("one")
    (repo.root / "README.md").write_text("# mine\n", encoding="utf-8")
    repo.git("add", "README.md")
    repo.git("commit", "-qm", "readme")
    (repo.root / "README.md").write_text("# mine\nunsaved\n", encoding="utf-8")
    assert main(["sync", "--repo", str(repo.root)]) == 1
    assert (repo.root / "README.md").read_text(encoding="utf-8") == "# mine\nunsaved\n"
    assert not (repo.root / "gitgraph.toml").exists()  # nothing was written
