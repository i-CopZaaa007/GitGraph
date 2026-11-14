"""Provider-independent domain models.

These records describe what Git reports. They carry no layout or rendering state; computed
visual attributes live in :mod:`gitgraph.layout`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RefKind(StrEnum):
    """Kind of a collected reference."""

    LOCAL_BRANCH = "local_branch"
    REMOTE_BRANCH = "remote_branch"
    TAG = "tag"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Person:
    """Name and email as recorded in a commit or tag object."""

    name: str
    email: str = ""


@dataclass(frozen=True, slots=True)
class Commit:
    """A commit object. ``parents`` keeps Git's order (first parent first)."""

    sha: str
    parents: tuple[str, ...]
    subject: str
    body: str
    author: Person
    authored_at: int
    committer: Person
    committed_at: int

    @property
    def short_sha(self) -> str:
        return self.sha[:7]

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1

    @property
    def is_root(self) -> bool:
        return not self.parents


@dataclass(frozen=True, slots=True)
class Reference:
    """A branch-like reference pointing at a commit."""

    full_name: str
    short_name: str
    kind: RefKind
    target_sha: str
    remote: str | None = None

    @property
    def branch_name(self) -> str:
        """Name without the remote prefix; local and remote-tracking refs share it."""
        if self.kind is RefKind.REMOTE_BRANCH and self.remote:
            return self.short_name[len(self.remote) + 1 :]
        return self.short_name


@dataclass(frozen=True, slots=True)
class Tag:
    """A tag peeled to the commit it marks."""

    name: str
    target_sha: str
    annotated: bool
    object_sha: str
    tagger: Person | None = None
    tagged_at: int | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A non-fatal observation about the collected data or the produced graph."""

    level: str  # "info" | "warning"
    code: str
    message: str


@dataclass(frozen=True, slots=True)
class RepositorySnapshot:
    """Everything the graph engine needs, collected in one read-only pass."""

    commits: dict[str, Commit]
    refs: tuple[Reference, ...]
    tags: tuple[Tag, ...]
    head_sha: str | None
    head_branch: str | None
    default_branch: str | None
    is_shallow: bool
    shallow_boundary: frozenset[str]
    diagnostics: tuple[Diagnostic, ...] = ()
