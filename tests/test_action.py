from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from gitrepo import GitRepo

SCRIPT = Path(__file__).resolve().parent.parent / "action" / "publish-artifact-branch.sh"


def run_script(cwd: Path, *files: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    base.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, **env})
    return subprocess.run(
        ["bash", str(SCRIPT), *map(str, files)],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=base,
        check=False,
    )


@pytest.fixture
def clone(tmp_path: Path) -> tuple[Path, Path, GitRepo]:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = GitRepo(tmp_path / "work")
    work.commit("one")
    work.git("remote", "add", "origin", str(bare))
    work.git("push", "-q", "origin", "main")
    return bare, work.root, work


def remote_tree(bare: Path, branch: str) -> str:
    return subprocess.run(
        ["git", "-C", str(bare), "ls-tree", "--name-only", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()


def test_publish_creates_orphan_branch_then_fast_forwards(
    clone: tuple[Path, Path, GitRepo], tmp_path: Path
) -> None:
    bare, work, repo = clone
    svg = tmp_path / "out" / "gitgraph.svg"
    svg.parent.mkdir()
    svg.write_text("<svg/>", encoding="utf-8")
    before_status = repo.git("status", "--porcelain")
    main_before = repo.git("rev-parse", "main")

    first = run_script(work, svg)
    assert first.returncode == 0, first.stderr
    assert remote_tree(bare, "gitgraph-assets") == ["gitgraph.svg"]
    parents = subprocess.run(
        ["git", "-C", str(bare), "rev-list", "--parents", "-n1", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert len(parents) == 1  # orphan: shares no history with the visualised branches

    unchanged = run_script(work, svg)
    assert "No change" in unchanged.stdout
    count = subprocess.run(
        ["git", "-C", str(bare), "rev-list", "--count", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "1"

    svg.write_text("<svg><g/></svg>", encoding="utf-8")
    assert run_script(work, svg).returncode == 0
    count = subprocess.run(
        ["git", "-C", str(bare), "rev-list", "--count", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "2"
    # working tree, index and visualised branch untouched
    assert repo.git("status", "--porcelain") == before_status
    assert repo.git("rev-parse", "main") == main_before
    assert repo.git("branch", "--show-current") == "main"


def test_dry_run_does_not_push(clone: tuple[Path, Path, GitRepo], tmp_path: Path) -> None:
    bare, work, _ = clone
    svg = tmp_path / "g.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    result = run_script(work, svg, GITGRAPH_DRY_RUN="true")
    assert result.returncode == 0 and "Dry run" in result.stdout
    ref = subprocess.run(
        ["git", "-C", str(bare), "branch", "--list", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert ref.strip() == ""


@pytest.mark.parametrize("branch", ["-bad", "a..b", "has space", "x:y", "a~1", ""])
def test_unsafe_branch_names_are_rejected(
    clone: tuple[Path, Path, GitRepo], tmp_path: Path, branch: str
) -> None:
    _, work, _ = clone
    svg = tmp_path / "g.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    result = run_script(work, svg, GITGRAPH_BRANCH=branch, GITGRAPH_DRY_RUN="true")
    if branch == "":  # empty falls back to the default branch name
        assert result.returncode == 0
    else:
        assert result.returncode == 2


def test_missing_file_fails(clone: tuple[Path, Path, GitRepo], tmp_path: Path) -> None:
    _, work, _ = clone
    assert run_script(work, tmp_path / "nope.svg").returncode == 1
    assert run_script(work).returncode == 2


def test_artifact_branch_is_excluded_from_graph_by_default(
    clone: tuple[Path, Path, GitRepo], tmp_path: Path
) -> None:
    from gitgraph.collector import collect

    _, work, _repo = clone
    svg = tmp_path / "g.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    assert run_script(work, svg).returncode == 0  # leaves refs/remotes/origin/gitgraph-assets
    snap = collect(work)
    assert "origin/gitgraph-assets" not in {r.short_name for r in snap.refs}
    assert len(snap.commits) == 1
