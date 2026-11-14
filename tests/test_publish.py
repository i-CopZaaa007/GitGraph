from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from gitgraph.cli import main
from gitgraph.config import Config, ConfigError, config_from_dict
from gitgraph.publish import PublishError, publish, shared_image_url
from gitrepo import GitRepo

IMAGE = "https://example.invalid/g.svg"


def run(*args: str) -> int:
    return main(list(args))


def shared_config() -> Config:
    return config_from_dict({"publish": {"enabled": True}})


@pytest.fixture
def remote_repo(tmp_path: Path, make_repo: Callable[[str], GitRepo]) -> tuple[GitRepo, Path]:
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    repo = make_repo("work")
    repo.commit("one")
    repo.git("remote", "add", "origin", str(bare))
    repo.git("push", "-q", "-u", "origin", "main")
    return repo, bare


def remote_svg(bare: Path, branch: str = "gitgraph-assets") -> str:
    return subprocess.run(
        ["git", "-C", str(bare), "show", f"{branch}:gitgraph.svg"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_shared_image_url_for_github_remotes() -> None:
    for raw in ("https://github.com/o/r.git", "git@github.com:o/r.git"):
        assert shared_image_url(raw, "gitgraph-assets", "gitgraph.svg") == (
            "https://raw.githubusercontent.com/o/r/gitgraph-assets/gitgraph.svg"
        )
    with pytest.raises(PublishError):
        shared_image_url("https://gitlab.com/o/r.git", "b", "f.svg")
    with pytest.raises(PublishError):
        shared_image_url("/local/path", "b", "f.svg")


def test_publish_creates_orphan_branch_and_is_idempotent(
    remote_repo: tuple[GitRepo, Path],
) -> None:
    repo, bare = remote_repo
    before = (repo.git("status", "--porcelain"), repo.git("rev-parse", "main"))
    first = publish(repo.root, shared_config())
    assert first.pushed and first.commit
    assert "1 commits" in remote_svg(bare)
    parents = subprocess.run(
        ["git", "-C", str(bare), "rev-list", "--parents", "-n1", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert len(parents) == 1  # orphan history
    assert publish(repo.root, shared_config()).commit is None  # nothing changed
    assert (repo.git("status", "--porcelain"), repo.git("rev-parse", "main")) == before
    assert repo.git("branch", "--show-current") == "main"


def test_graph_covers_every_branch_and_excludes_the_artifact_branch(
    remote_repo: tuple[GitRepo, Path],
) -> None:
    repo, bare = remote_repo
    publish(repo.root, shared_config())
    repo.branch("feature/x")
    repo.commit("on feature")
    repo.checkout("main")
    result = publish(repo.root, shared_config())
    assert result.pushed
    svg = remote_svg(bare)
    assert "2 commits" in svg and "feature/x" in svg
    assert "gitgraph-assets" not in svg  # the artifact branch is never drawn
    count = subprocess.run(
        ["git", "-C", str(bare), "rev-list", "--count", "gitgraph-assets"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert count == "2"  # fast-forward history, never rewritten


def test_dry_run_pushes_nothing(remote_repo: tuple[GitRepo, Path]) -> None:
    repo, bare = remote_repo
    result = publish(repo.root, shared_config(), dry_run=True)
    assert result.commit and not result.pushed
    branches = subprocess.run(
        ["git", "-C", str(bare), "branch", "--list"], capture_output=True, text=True, check=True
    ).stdout
    assert "gitgraph-assets" not in branches


def test_publish_errors_are_clear(repo: GitRepo) -> None:
    repo.commit("one")
    with pytest.raises(PublishError, match="remote"):
        publish(repo.root, shared_config())
    bad = config_from_dict({"publish": {"enabled": True, "branch": "a..b"}})
    repo.git("remote", "add", "origin", "/nonexistent/path.git")
    with pytest.raises(PublishError, match="unsafe"):
        publish(repo.root, bad)
    with pytest.raises(PublishError):  # unreachable remote
        publish(repo.root, shared_config())
    with pytest.raises(ConfigError):
        config_from_dict({"publish": {"file": 3}})
    with pytest.raises(PublishError, match="file name"):
        publish(repo.root, config_from_dict({"publish": {"enabled": True, "file": "../x.svg"}}))


def test_custom_artifact_branch_is_excluded_automatically(
    remote_repo: tuple[GitRepo, Path],
) -> None:
    repo, bare = remote_repo
    config = config_from_dict({"publish": {"enabled": True, "branch": "graph-out"}})
    publish(repo.root, config)
    publish(repo.root, config)  # second run sees origin/graph-out locally
    assert "graph-out" not in remote_svg(bare, "graph-out")


def test_cli_publish_and_only_remote(
    remote_repo: tuple[GitRepo, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, bare = remote_repo
    (repo.root / "gitgraph.toml").write_text("[publish]\nenabled = true\n", encoding="utf-8")
    assert run("publish", "--repo", str(repo.root), "--only-remote", "fork") == 0
    assert "published" not in capsys.readouterr().err
    assert run("publish", "--repo", str(repo.root), "--dry-run") == 0
    assert "dry run" in capsys.readouterr().err
    assert run("publish", "--repo", str(repo.root)) == 0
    assert "published graph" in capsys.readouterr().err
    assert remote_svg(bare)


def test_sync_shared_mode_end_to_end(remote_repo: tuple[GitRepo, Path]) -> None:
    repo, bare = remote_repo
    repo.git("config", "user.name", "T")
    repo.git("config", "user.email", "t@example.invalid")
    readme = repo.root / "README.md"
    readme.write_text("# Project\n\nkeep this\n", encoding="utf-8")
    repo.git("add", "README.md")
    repo.git("commit", "-q", "-m", "readme")
    assert run("sync", "--repo", str(repo.root), "--mode", "shared", "--image", IMAGE) == 0
    toml = (repo.root / "gitgraph.toml").read_text(encoding="utf-8")
    assert toml.count("enabled = true") == 1
    assert not (repo.root / "docs" / "gitgraph.svg").exists()  # nothing stored in the branch
    text = readme.read_text(encoding="utf-8")
    assert f"![Git commit graph]({IMAGE})" in text and "keep this" in text
    assert repo.git("log", "-1", "--format=%s") == "Update & Share Graph"
    assert repo.git("status", "--porcelain") == ""
    assert "2 commits" in remote_svg(bare)  # the sync commit itself is not drawn
    assert (
        subprocess.run(
            ["git", "-C", str(bare), "log", "-1", "--format=%s", "gitgraph-assets"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == "Update & Share Graph"
    )

    # new branch + commit: one command refreshes the shared graph; README is untouched
    repo.branch("topic")
    repo.commit("topic work")
    before = readme.read_text(encoding="utf-8")
    head = repo.head()
    assert run("sync", "--repo", str(repo.root)) == 0
    assert "topic" in remote_svg(bare) and "3 commits" in remote_svg(bare)
    assert readme.read_text(encoding="utf-8") == before
    assert repo.head() == head  # no commit needed on the branch
    assert run("sync", "--repo", str(repo.root)) == 0  # fixed point


def test_sync_auto_mode_falls_back_for_non_github_remote(
    repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.git("config", "user.name", "T")
    repo.git("config", "user.email", "t@example.invalid")
    repo.commit("one")
    repo.git("remote", "add", "origin", "https://gitlab.com/o/r.git")
    assert run("sync", "--repo", str(repo.root)) == 0
    assert "not on github.com" in capsys.readouterr().err
    assert (repo.root / "docs" / "gitgraph.svg").exists()


def test_sync_auto_mode_picks_shared_only_for_public_repositories(
    remote_repo: tuple[GitRepo, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gitgraph import publish as pub

    repo, _ = remote_repo
    repo.git("config", "user.name", "T")
    repo.git("config", "user.email", "t@example.invalid")
    # pretend the remote is a private github.com repository
    monkeypatch.setattr(pub, "shared_image_url", lambda *a, **k: IMAGE)
    monkeypatch.setattr(pub, "is_public_github", lambda raw: False)
    mode, image, note = pub.decide_mode("https://github.com/o/r.git", "auto", None)
    assert (mode, image) == ("local", None) and "private" in note
    monkeypatch.setattr(pub, "is_public_github", lambda raw: True)
    assert pub.decide_mode("https://github.com/o/r.git", "auto", None)[:2] == ("shared", IMAGE)
    assert pub.decide_mode("https://github.com/o/r.git", "local", None)[0] == "local"
    with pytest.raises(PublishError):
        pub.decide_mode(None, "shared", None)
    capsys.readouterr()


def test_sync_shared_needs_a_remote_or_github(
    repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("one")
    assert run("sync", "--repo", str(repo.root), "--mode", "shared") == 1
    assert "remote" in capsys.readouterr().err
    repo.git("remote", "add", "origin", "https://gitlab.com/o/r.git")
    assert run("sync", "--repo", str(repo.root), "--mode", "shared") == 1
    assert "github.com" in capsys.readouterr().err
    assert not (repo.root / "gitgraph.toml").exists()
