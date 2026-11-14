"""Shared mode: publish the graph to a dedicated branch instead of committing it everywhere.

Every branch's README references the same image URL, so one update refreshes the graph on all
branches and the README never changes after setup. The artifact branch is an orphan history built
with Git plumbing (``hash-object``/``mktree``/``commit-tree``): the working tree, the index and
every visualised branch stay untouched, and the push is fast-forward only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from gitgraph.api import generate
from gitgraph.config import Config
from gitgraph.gitrun import GitCommandError, run_git
from gitgraph.urls import normalize_repository_url

_DEFAULT_IDENTITY = {
    "GIT_AUTHOR_NAME": "GitGraph",
    "GIT_AUTHOR_EMAIL": "gitgraph@users.noreply.github.com",
    "GIT_COMMITTER_NAME": "GitGraph",
    "GIT_COMMITTER_EMAIL": "gitgraph@users.noreply.github.com",
}


class PublishError(RuntimeError):
    """Raised when the graph cannot be published."""


@dataclass(frozen=True, slots=True)
class PublishResult:
    commit: str | None  # None when nothing changed
    pushed: bool


def shared_image_url(remote_url: str, branch: str, file: str) -> str:
    """Stable raw URL of the published SVG. Only github.com remotes can be derived."""
    repo_url = normalize_repository_url(remote_url)
    if repo_url is None or not repo_url.startswith("https://github.com/"):
        raise PublishError(
            "cannot derive an image URL from this remote (only github.com is supported); "
            "pass --image URL"
        )
    path = repo_url.removeprefix("https://github.com/")
    return f"https://raw.githubusercontent.com/{path}/{quote(branch, safe='/')}/{quote(file)}"


def _git(repo: Path, *args: str, **kwargs: object) -> str:
    try:
        return run_git(repo, *args, **kwargs).stdout.strip()  # type: ignore[arg-type]
    except GitCommandError as exc:
        raise PublishError(str(exc)) from exc


def publish(repo: Path, config: Config, *, dry_run: bool = False) -> PublishResult:
    """Generate the graph and push it to ``publish.branch`` on ``publish.remote``."""
    pub = config.publish
    if not pub.file or PurePosixPath(pub.file).name != pub.file:
        raise PublishError("[publish] file must be a plain file name")
    if (
        any(c in pub.branch for c in " ~^:?*[\\")
        or pub.branch.startswith("-")
        or ".." in pub.branch
    ):
        raise PublishError(f"unsafe branch name: {pub.branch!r}")
    if run_git(repo, "remote", "get-url", pub.remote, check=False).returncode != 0:
        raise PublishError(f"remote {pub.remote!r} does not exist; add it or set [publish] remote")

    result = generate(repo, config)
    files = {pub.file: result.svg}
    if config.output.json:
        files[PurePosixPath(config.output.json).name] = result.json

    entries = ""
    for name, text in files.items():
        blob = _git(repo, "hash-object", "-w", "--stdin", input_text=text)
        entries += f"100644 blob {blob}\t{name}\n"
    tree = _git(repo, "mktree", input_text=entries)

    parent: str | None = None
    exists = run_git(
        repo, "ls-remote", "--exit-code", "--heads", pub.remote, pub.branch, check=False
    )
    if exists.returncode == 0:
        _git(
            repo,
            "fetch",
            "--quiet",
            "--no-tags",
            pub.remote,
            f"+refs/heads/{pub.branch}:refs/remotes/{pub.remote}/{pub.branch}",
        )
        parent = _git(repo, "rev-parse", f"refs/remotes/{pub.remote}/{pub.branch}")
        if _git(repo, "rev-parse", f"{parent}^{{tree}}") == tree:
            return PublishResult(None, False)
    elif exists.returncode != 2:
        raise PublishError(f"cannot reach remote {pub.remote!r}: {exists.stderr.strip()}")

    identity: dict[str, str] = {}
    if (
        not run_git(repo, "config", "user.name", check=False).stdout.strip()
        or not run_git(repo, "config", "user.email", check=False).stdout.strip()
    ):
        identity = _DEFAULT_IDENTITY
    args = ["commit-tree", tree, "-m", config.sync.commit_message]
    if parent:
        args[2:2] = ["-p", parent]
    commit = _git(repo, *args, extra_env=identity)
    if dry_run:
        return PublishResult(commit, False)
    _git(repo, "push", "--quiet", pub.remote, f"{commit}:refs/heads/{pub.branch}")
    return PublishResult(commit, True)


def is_public_github(remote_url_value: str) -> bool:
    """True if the github.com repository can be read without any credentials."""
    import os
    import subprocess

    url = normalize_repository_url(remote_url_value)
    if url is None or not url.startswith("https://github.com/"):
        return False
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_TERMINAL_PROMPT="0",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_ASKPASS="true",
    )
    try:
        done = subprocess.run(
            ["git", "-c", "credential.helper=", "ls-remote", "--exit-code", f"{url}.git", "HEAD"],
            capture_output=True,
            env=env,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def decide_mode(
    remote_url_value: str | None, requested: str, image: str | None
) -> tuple[str, str | None, str]:
    """Choose ``shared`` or ``local`` for a first-time setup.

    Returns (mode, image URL for shared mode, note to show the user). In ``auto`` mode the shared
    image is only used when the repository is publicly readable, because the shared URL cannot be
    loaded from a private repository's README.
    """
    if requested == "local":
        return "local", None, ""
    if image:
        return "shared", image, ""
    if not remote_url_value:
        if requested == "shared":
            raise PublishError(
                "--mode shared needs a remote (git remote add origin ...) or --image"
            )
        return "local", None, "no remote configured: using per-branch mode"
    try:
        url = shared_image_url(remote_url_value, "gitgraph-assets", "gitgraph.svg")
    except PublishError:
        if requested == "shared":
            raise
        return "local", None, "remote is not on github.com: using per-branch mode"
    if requested == "shared" or is_public_github(remote_url_value):
        return "shared", url, ""
    return (
        "local",
        None,
        "the repository looks private, so a shared image URL would not load there: using "
        "per-branch mode (pass --mode shared to force shared mode)",
    )
