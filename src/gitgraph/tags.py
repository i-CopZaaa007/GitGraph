"""Tag ordering and latest-tag selection.

Not every project uses semantic versioning, so the rule is layered:

1. Tags that look like versions (``1.2``, ``v1.2.3``, ``1.0.0-rc.1``) are compared by their
   numeric components; a pre-release sorts below the same release.
2. In ``auto`` mode the latest tag is the highest stable version; if there is none, the highest
   pre-release version; if there are no version-like tags, the most recent tag by date
   (tagger date for annotated tags, otherwise the commit's committer date).
3. Remaining ties are broken by tag name, so the result is deterministic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from gitgraph.models import Tag

_VERSION_RE = re.compile(r"^[vV]?(?P<nums>\d+(?:\.\d+)*)(?P<rest>[-+._]?[A-Za-z].*)?$")
_PRE_TOKEN_RE = re.compile(r"[A-Za-z]+|\d+")


@dataclass(frozen=True, slots=True)
class ParsedVersion:
    numbers: tuple[int, ...]
    prerelease: tuple[tuple[int, int | str], ...]

    @property
    def is_stable(self) -> bool:
        return not self.prerelease

    def key(self) -> tuple[tuple[int, ...], int, tuple[tuple[int, int | str], ...]]:
        numbers = list(self.numbers)
        while len(numbers) > 1 and numbers[-1] == 0:
            numbers.pop()
        return (tuple(numbers), 1 if self.is_stable else 0, self.prerelease)


def parse_version(name: str) -> ParsedVersion | None:
    """Parse a version-like tag name, or return ``None`` if it does not look like one."""
    match = _VERSION_RE.match(name)
    if match is None:
        return None
    numbers = tuple(int(part) for part in match.group("nums").split("."))
    rest = match.group("rest") or ""
    prerelease: tuple[tuple[int, int | str], ...] = ()
    if rest and not rest.startswith("+"):
        tokens: list[tuple[int, int | str]] = []
        for token in _PRE_TOKEN_RE.findall(rest.split("+", 1)[0]):
            tokens.append((0, int(token)) if token.isdigit() else (1, token.lower()))
        prerelease = tuple(tokens)
    return ParsedVersion(numbers, prerelease)


def tag_date(tag: Tag, committed_at: Mapping[str, int]) -> int:
    """Date used for date-based ordering."""
    if tag.tagged_at is not None:
        return tag.tagged_at
    return committed_at.get(tag.target_sha, 0)


def _version_sort_key(tag: Tag) -> tuple[object, ...]:
    parsed = parse_version(tag.name)
    assert parsed is not None
    return (*parsed.key(), tag.name)


def sort_tags(tags: Sequence[Tag], committed_at: Mapping[str, int]) -> list[Tag]:
    """Order tags newest-first: version-like tags by version, then the rest by date."""
    versioned = [t for t in tags if parse_version(t.name) is not None]
    others = [t for t in tags if parse_version(t.name) is None]
    versioned.sort(key=_version_sort_key, reverse=True)
    others.sort(key=lambda t: (-tag_date(t, committed_at), t.name))
    return versioned + others


def select_latest(
    tags: Sequence[Tag], committed_at: Mapping[str, int], strategy: str = "auto"
) -> Tag | None:
    """Pick the latest tag according to ``strategy`` (``auto``, ``version`` or ``date``)."""
    if not tags:
        return None
    versioned = [t for t in tags if parse_version(t.name) is not None]
    by_date = min(tags, key=lambda t: (-tag_date(t, committed_at), t.name))
    if strategy == "date" or not versioned:
        return by_date
    stable = [t for t in versioned if (p := parse_version(t.name)) is not None and p.is_stable]
    pool = stable or versioned
    return max(pool, key=_version_sort_key)
