"""Read-only Git adapter.

Only inspection commands are run (``rev-parse``, ``for-each-ref``, ``log``, ``symbolic-ref``,
``config --get``). Commands are executed with argument arrays, never through a shell. Everything
Git reports is treated as untrusted data.
"""

from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path

from gitgraph.models import (
    Commit,
    Diagnostic,
    Person,
    Reference,
    RefKind,
    RepositorySnapshot,
    Tag,
)

DEFAULT_EXCLUDES: tuple[str, ...] = ("gitgraph-assets", "*/gitgraph-assets")
_LOG_FIELDS = 10
_LOG_FORMAT = "%x00".join(["%H", "%P", "%an", "%ae", "%at", "%cn", "%ce", "%ct", "%s", "%b"])


class GitError(RuntimeError):
    """Raised when Git cannot be run or reports a failure."""


@dataclass(frozen=True, slots=True)
class CollectionOptions:
    """Which references define the history to collect."""

    branches: bool = True
    remotes: bool = True
    tags: bool = True
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    hide_subject: str | None = None
    hide_paths: tuple[str, ...] = ()
    extra: dict[str, str] = field(default_factory=dict)


def _run(repo: Path, args: list[str], *, stdin: str | None = None, check: bool = True) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C.UTF-8"})
    command = ["git", "--no-pager", "--no-replace-objects", "-C", str(repo), *args]
    try:
        proc = subprocess.run(
            command,
            input=stdin.encode() if stdin is not None else None,
            capture_output=True,
            env=env,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git executable not found on PATH") from exc
    if check and proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise GitError(f"git {args[0]} failed: {stderr or 'exit code ' + str(proc.returncode)}")
    return proc.stdout.decode("utf-8", "replace") if proc.returncode == 0 else ""


def _matches(patterns: tuple[str, ...], *names: str) -> bool:
    return any(fnmatch.fnmatchcase(n, p) for p in patterns for n in names)


def _person(name: str, email: str) -> Person:
    return Person(name=name, email=email)


def _to_int(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def remote_url(repo: Path, remote: str = "origin") -> str | None:
    """Return the configured URL of ``remote`` or ``None``."""
    out = _run(repo, ["config", "--get", f"remote.{remote}.url"], check=False).strip()
    return out or None


def collect(repo: Path, options: CollectionOptions | None = None) -> RepositorySnapshot:
    """Collect commits, branch refs and tags reachable from the selected references."""
    options = options or CollectionOptions()
    repo = Path(repo)
    if not repo.is_dir():
        raise GitError(f"not a directory: {repo}")
    _run(repo, ["rev-parse", "--git-dir"])  # raises if this is not a repository

    diagnostics: list[Diagnostic] = []
    is_shallow = _run(repo, ["rev-parse", "--is-shallow-repository"]).strip() == "true"
    boundary: frozenset[str] = frozenset()
    if is_shallow:
        shallow_path = Path(
            _run(repo, ["rev-parse", "--path-format=absolute", "--git-path", "shallow"]).strip()
        )
        if shallow_path.is_file():
            boundary = frozenset(
                line.strip() for line in shallow_path.read_text().splitlines() if line.strip()
            )
        diagnostics.append(
            Diagnostic(
                "warning",
                "shallow-clone",
                "This is a shallow clone: history is truncated at the shallow boundary. "
                "Fetch full history (for example `git fetch --unshallow`, or "
                "`fetch-depth: 0` in actions/checkout) for a complete graph.",
            )
        )

    refs, tags = _collect_refs(repo, options, diagnostics)

    head_sha = (
        _run(repo, ["rev-parse", "--verify", "-q", "HEAD^{commit}"], check=False).strip() or None
    )
    head_branch = _run(repo, ["symbolic-ref", "-q", "--short", "HEAD"], check=False).strip() or None
    origin_head = _run(
        repo, ["symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD"], check=False
    ).strip()
    default_branch = origin_head.removeprefix("origin/") if origin_head else None

    # HEAD is only a fallback tip when branches were requested, nothing matched and there is no
    # tag to anchor the graph; it must not resurrect history the user switched off or filtered.
    wants_branches = options.branches or options.remotes
    if not refs and not tags and head_sha is not None and wants_branches and not options.include:
        refs = (Reference("HEAD", "HEAD", RefKind.OTHER, head_sha),)
        diagnostics.append(
            Diagnostic(
                "info", "head-fallback", "No branches were collected; using HEAD as the only tip."
            )
        )

    tips = sorted({r.target_sha for r in refs} | {t.target_sha for t in tags})
    commits = _read_commits(repo, tips) if tips else {}
    if not tips:
        diagnostics.append(Diagnostic("info", "no-refs", "No references with commits were found."))

    if options.hide_subject and options.hide_paths and commits:
        prefix = _run(repo, ["rev-parse", "--show-prefix"], check=False).strip()
        wanted = frozenset(prefix + path for path in options.hide_paths)
        hidden = _find_generated(repo, commits, options.hide_subject, wanted)
        if hidden:
            commits, refs, tags, head_sha = _splice(commits, refs, tags, head_sha, hidden)
            diagnostics.append(
                Diagnostic(
                    "info",
                    "hidden-graph-commits",
                    "Automatic graph-update commits (see [sync] in the configuration) are not drawn.",
                )
            )

    return RepositorySnapshot(
        commits=commits,
        refs=refs,
        tags=tags,
        head_sha=head_sha,
        head_branch=head_branch,
        default_branch=default_branch,
        is_shallow=is_shallow,
        shallow_boundary=boundary,
        diagnostics=tuple(diagnostics),
    )


def _collect_refs(
    repo: Path, options: CollectionOptions, diagnostics: list[Diagnostic]
) -> tuple[tuple[Reference, ...], tuple[Tag, ...]]:
    fmt = "%00".join(
        [
            "%(refname)",
            "%(objecttype)",
            "%(objectname)",
            "%(*objecttype)",
            "%(*objectname)",
            "%(symref)",
            "%(taggername)",
            "%(taggeremail)",
            "%(taggerdate:unix)",
            "%(contents:subject)",
        ]
    )
    out = _run(repo, ["for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes", "refs/tags"])
    refs: list[Reference] = []
    tags: list[Tag] = []
    for line in out.split("\n"):
        if not line:
            continue
        parts = line.split("\0")
        if len(parts) != 10:
            continue
        full, otype, oid, peeled_type, peeled_oid, symref, tname, temail, tdate, tmsg = parts
        if symref:
            continue  # symbolic refs such as refs/remotes/origin/HEAD are aliases
        if full.startswith("refs/heads/"):
            short = full.removeprefix("refs/heads/")
            if not options.branches or _filtered(options, short, full):
                continue
            if otype == "commit":
                refs.append(Reference(full, short, RefKind.LOCAL_BRANCH, oid))
        elif full.startswith("refs/remotes/"):
            short = full.removeprefix("refs/remotes/")
            if not options.remotes or _filtered(options, short, full):
                continue
            remote = short.split("/", 1)[0]
            if otype == "commit" and "/" in short:
                refs.append(Reference(full, short, RefKind.REMOTE_BRANCH, oid, remote))
        elif full.startswith("refs/tags/"):
            short = full.removeprefix("refs/tags/")
            if not options.tags or _filtered(options, short, full, is_tag=True):
                continue
            tag = _make_tag(
                repo,
                short,
                full,
                otype,
                oid,
                peeled_type,
                peeled_oid,
                (tname, temail, tdate, tmsg),
                diagnostics,
            )
            if tag is not None:
                tags.append(tag)
    refs.sort(key=lambda r: r.full_name)
    tags.sort(key=lambda t: t.name)
    return tuple(refs), tuple(tags)


def _filtered(options: CollectionOptions, short: str, full: str, *, is_tag: bool = False) -> bool:
    """``exclude`` applies to every ref; ``include`` narrows branches only, so that selecting
    a few branches does not silently drop all tags (use ``tags = false`` for that)."""
    if _matches(options.exclude, short, full):
        return True
    if is_tag:
        return False
    return bool(options.include) and not _matches(options.include, short, full)


def _make_tag(
    repo: Path,
    name: str,
    full: str,
    otype: str,
    oid: str,
    peeled_type: str,
    peeled_oid: str,
    meta: tuple[str, str, str, str],
    diagnostics: list[Diagnostic],
) -> Tag | None:
    if otype == "commit":
        return Tag(name=name, target_sha=oid, annotated=False, object_sha=oid)
    if otype != "tag":
        diagnostics.append(
            Diagnostic(
                "warning",
                "tag-not-commit",
                f"Tag {name!r} points to a {otype}, not a commit; skipped.",
            )
        )
        return None
    target = peeled_oid
    if peeled_type != "commit":
        resolved = _run(
            repo, ["rev-parse", "--verify", "-q", f"{full}^{{commit}}"], check=False
        ).strip()
        if not resolved:
            diagnostics.append(
                Diagnostic(
                    "warning",
                    "tag-not-commit",
                    f"Tag {name!r} does not resolve to a commit; skipped.",
                )
            )
            return None
        target = resolved
    tname, temail, tdate, tmsg = meta
    tagged_at = _to_int(tdate) if tdate else None
    return Tag(
        name=name,
        target_sha=target,
        annotated=True,
        object_sha=oid,
        tagger=_person(tname, temail.strip("<>")) if tname else None,
        tagged_at=tagged_at,
        message=tmsg or None,
    )


def _read_commits(repo: Path, tips: list[str]) -> dict[str, Commit]:
    out = _run(
        repo,
        ["-c", "log.showSignature=false", "log", "-z", f"--format={_LOG_FORMAT}", "--stdin"],
        stdin="\n".join(tips) + "\n",
    )
    fields = out.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % _LOG_FIELDS != 0:
        raise GitError("unexpected output while reading commit log")
    commits: dict[str, Commit] = {}
    for i in range(0, len(fields), _LOG_FIELDS):
        sha, parents, an, ae, at, cn, ce, ct, subject, body = (
            f.strip("\n") for f in fields[i : i + _LOG_FIELDS]
        )
        commits[sha] = Commit(
            sha=sha,
            parents=tuple(parents.split()),
            subject=subject,
            body=body.strip(),
            author=_person(an, ae),
            authored_at=_to_int(at),
            committer=_person(cn, ce),
            committed_at=_to_int(ct),
        )
    return commits


def _find_generated(
    repo: Path, commits: dict[str, Commit], subject: str, paths: frozenset[str]
) -> dict[str, str]:
    """Single-parent commits with exactly ``subject`` that touch only ``paths``.

    Returns hidden SHA -> its parent. Merges and root commits are never hidden.
    """
    hidden: dict[str, str] = {}
    for sha, commit in commits.items():
        if commit.subject != subject or len(commit.parents) != 1:
            continue
        out = _run(repo, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z", sha])
        files = [f for f in out.split("\0") if f]
        if files and all(f in paths for f in files):
            hidden[sha] = commit.parents[0]
    return hidden


def _splice(
    commits: dict[str, Commit],
    refs: tuple[Reference, ...],
    tags: tuple[Tag, ...],
    head_sha: str | None,
    hidden: dict[str, str],
) -> tuple[dict[str, Commit], tuple[Reference, ...], tuple[Tag, ...], str | None]:
    """Remove ``hidden`` commits and re-point children, refs and tags at their parents."""

    def resolve(sha: str) -> str:
        while sha in hidden:
            sha = hidden[sha]
        return sha

    kept = {
        sha: replace(c, parents=tuple(dict.fromkeys(resolve(p) for p in c.parents)))
        for sha, c in commits.items()
        if sha not in hidden
    }
    new_refs = tuple(replace(r, target_sha=resolve(r.target_sha)) for r in refs)
    new_tags = tuple(replace(t, target_sha=resolve(t.target_sha)) for t in tags)
    return kept, new_refs, new_tags, resolve(head_sha) if head_sha else None
