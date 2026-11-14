"""Build in-memory snapshots without Git, for fast graph/layout property tests."""

from __future__ import annotations

from gitgraph.models import Commit, Person, Reference, RefKind, RepositorySnapshot, Tag

PERSON = Person("Tester", "t@example.invalid")


def sha_of(index: int) -> str:
    return f"{index:040x}"


def make_commit(
    index: int, parents: tuple[int, ...], time: int, subject: str | None = None
) -> Commit:
    return Commit(
        sha=sha_of(index),
        parents=tuple(sha_of(p) for p in parents),
        subject=subject if subject is not None else f"commit {index}",
        body="",
        author=PERSON,
        authored_at=time,
        committer=PERSON,
        committed_at=time,
    )


def make_snapshot(
    parents: dict[int, tuple[int, ...]],
    branches: dict[str, int],
    *,
    times: dict[int, int] | None = None,
    tags: dict[str, int] | None = None,
    subjects: dict[int, str] | None = None,
    shallow_boundary: frozenset[str] = frozenset(),
) -> RepositorySnapshot:
    commits = {}
    for index, plist in parents.items():
        t = (times or {}).get(index, 1_700_000_000 + index * 60)
        commit = make_commit(index, plist, t, (subjects or {}).get(index))
        commits[commit.sha] = commit
    refs = tuple(
        Reference(f"refs/heads/{name}", name, RefKind.LOCAL_BRANCH, sha_of(target))
        for name, target in sorted(branches.items())
    )
    tag_objs = tuple(
        Tag(name, sha_of(target), annotated=False, object_sha=sha_of(target))
        for name, target in sorted((tags or {}).items())
    )
    return RepositorySnapshot(
        commits=commits,
        refs=refs,
        tags=tag_objs,
        head_sha=None,
        head_branch=None,
        default_branch=None,
        is_shallow=bool(shallow_boundary),
        shallow_boundary=shallow_boundary,
    )
