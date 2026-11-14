"""One command to set up, refresh, commit and share the graph.

Unlike ``generate`` this command writes to the repository history: one commit on the current
branch that touches only the generated files (README section, configuration, and in per-branch
mode the SVG). It refuses to run when those files already have uncommitted changes, so it can
never sweep unrelated edits into the graph commit. The commit has a fixed message that the graph
engine recognises and does not draw, which makes the update a fixed point.

Two modes, chosen once and stored in ``gitgraph.toml``:

``shared``
    The SVG lives on a separate artifact branch and every branch's README points to the same URL;
    the README only changes on first setup, and each run refreshes the graph for all branches.
``local``
    The SVG is committed on the current branch (needed for private repositories).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from gitgraph.api import apply_readme, generate
from gitgraph.config import Config
from gitgraph.gitrun import GitCommandError, run_git
from gitgraph.readme import (
    ReadmeError,
    atomic_write,
    build_block,
    find_markers,
    image_reference,
    read_text,
    update_readme,
)


class SyncError(RuntimeError):
    """Raised when the refresh cannot be done safely."""


@dataclass(frozen=True, slots=True)
class SetupPlan:
    """First-time setup written inside :func:`sync` after the safety checks pass."""

    config_path: Path
    config_text: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    changed: tuple[str, ...]
    commit: str | None
    pushed: bool
    published: bool = False


def _git(repo: Path, *args: str, check: bool = True) -> str:
    try:
        return run_git(repo, *args, check=check).stdout
    except GitCommandError as exc:
        raise SyncError(str(exc)) from exc


def repo_top(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--show-toplevel").strip())


def generated_paths(repo: Path, config: Config, setup: SetupPlan | None = None) -> list[Path]:
    paths = [repo / config.readme.path]
    if not config.publish.enabled:
        paths.append(repo / config.output.svg)
        if config.output.json:
            paths.append(repo / config.output.json)
    if setup is not None:
        paths.append(setup.config_path)
    return paths


def sync(
    repo: Path,
    config: Config,
    *,
    push: bool = False,
    allow_dirty: bool = False,
    setup: SetupPlan | None = None,
) -> SyncResult:
    from gitgraph.publish import PublishError, publish

    repo = repo.resolve()
    top = repo_top(repo)
    shared = config.publish.enabled
    rels = [os.path.relpath(p, top) for p in generated_paths(repo, config, setup)]
    detached = run_git(repo, "symbolic-ref", "-q", "HEAD", check=False).returncode != 0
    if detached and (not shared or setup is not None):
        raise SyncError("HEAD is detached; check out a branch before syncing")
    dirty = _git(repo, "status", "--porcelain", "--", *rels).strip()
    if dirty and not allow_dirty:
        raise SyncError(
            "generated files already have uncommitted changes; commit or stash them first "
            f"({', '.join(rels)})"
        )
    for rel in rels:
        if run_git(repo, "check-ignore", "-q", "--", rel, check=False).returncode == 0:
            raise SyncError(f"{rel} is ignored by .gitignore; it cannot be committed")

    readme = repo / config.readme.path
    svg_path = repo / config.output.svg
    if setup is not None:
        atomic_write(setup.config_path, setup.config_text)
        if not readme.exists() or find_markers(read_text(readme)) is None:
            image = image_reference(svg_path, readme, config.readme.image, None)
            block = build_block(
                image, config.readme.heading, config.readme.heading_level, config.readme.alt
            )
            try:
                update_readme(readme, block, "append", create=True)
            except ReadmeError as exc:
                raise SyncError(str(exc)) from exc

    result = generate(repo, config)
    if not shared:
        atomic_write(svg_path, result.svg)
        if config.output.json:
            atomic_write(repo / config.output.json, result.json)
    try:
        apply_readme(repo, config, result, svg_path)
    except ReadmeError as exc:
        raise SyncError(str(exc)) from exc

    changed = _git(repo, "status", "--porcelain", "--", *rels).strip()
    sha: str | None = None
    if changed:
        if detached:
            raise SyncError("HEAD is detached; the updated files were written but not committed")
        _git(repo, "add", "--", *rels)
        _git(repo, "commit", "-q", "--no-verify", "-m", config.sync.commit_message, "--", *rels)
        sha = _git(repo, "rev-parse", "HEAD").strip()
    published = False
    if shared:
        try:
            published = publish(repo, config).commit is not None
        except PublishError as exc:
            raise SyncError(str(exc)) from exc
    pushed = False
    if push:
        _git(repo, "push", "-q")
        pushed = True
    return SyncResult(tuple(rels) if sha else (), sha, pushed, published)
