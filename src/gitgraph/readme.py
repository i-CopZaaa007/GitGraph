"""Safe, idempotent README block insertion and replacement.

Only the region delimited by the start and end marker lines is ever replaced. Marker lines inside
fenced code blocks are ignored, so documentation that *shows* the markers is not touched. If the
markers are missing, duplicated or out of order, nothing is written and a helpful error is raised.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

START_MARKER = "<!-- gitgraph:start -->"
END_MARKER = "<!-- gitgraph:end -->"
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]")


class ReadmeError(ValueError):
    """Raised when the README cannot be updated safely."""


@dataclass(frozen=True, slots=True)
class Markers:
    start: int  # line index
    end: int


def _eol(text: str) -> str:
    crlf = text.count("\r\n")
    return "\r\n" if crlf and crlf * 2 >= text.count("\n") else "\n"


def _split(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _content(line: str) -> str:
    return line.rstrip("\r\n")


def _scan(lines: list[str]) -> tuple[list[int], list[int], int | None]:
    """Return marker line indexes (outside code fences) and the first heading index."""
    starts: list[int] = []
    ends: list[int] = []
    heading: int | None = None
    fence: str | None = None
    for i, line in enumerate(lines):
        body = _content(line)
        match = _FENCE_RE.match(body)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token[0] * 3
            elif token[0] == fence[0] and body.strip() == token:
                fence = None
            continue
        if fence is not None:
            continue
        stripped = body.strip()
        if stripped == START_MARKER:
            starts.append(i)
        elif stripped == END_MARKER:
            ends.append(i)
        elif heading is None and _HEADING_RE.match(body):
            heading = i
    return starts, ends, heading


def find_markers(text: str) -> Markers | None:
    """Locate a valid marker pair; ``None`` if absent; :class:`ReadmeError` if malformed."""
    starts, ends, _ = _scan(_split(text))
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1:
        raise ReadmeError(
            f"found {len(starts)} start marker(s) and {len(ends)} end marker(s); expected exactly "
            f"one of each ({START_MARKER} ... {END_MARKER}). Fix the README by hand; it was not modified."
        )
    if starts[0] > ends[0]:
        raise ReadmeError(
            "the end marker appears before the start marker; README was not modified."
        )
    return Markers(starts[0], ends[0])


def build_block(image: str, heading: str, level: int, alt: str, eol: str = "\n") -> str:
    """Markdown for the managed region, markers included, ending with ``eol``."""
    safe_alt = re.sub(r"[\[\]\r\n]", " ", alt).strip() or "Git commit graph"
    lines = [START_MARKER, ""]
    if heading.strip():
        lines += [f"{'#' * level} {heading.strip()}", ""]
    lines += [f"![{safe_alt}]({image})", "", END_MARKER]
    return eol.join(lines) + eol


def image_reference(svg_path: Path, readme_path: Path, override: str, version: str | None) -> str:
    """Path or URL used inside the Markdown image."""
    if override:
        ref = override
    else:
        relative = Path(os.path.relpath(svg_path.resolve(), readme_path.resolve().parent))
        ref = quote(relative.as_posix(), safe="/._-~")
    if version:
        ref += ("&" if "?" in ref else "?") + f"v={version}"
    return ref


def apply_block(text: str, block: str, insert: str = "none") -> str:
    """Return ``text`` with the managed block replaced, or inserted according to ``insert``."""
    eol = _eol(text) if text else "\n"
    block = block.replace("\r\n", "\n").replace("\n", eol)
    markers = find_markers(text)
    lines = _split(text)
    if markers is not None:
        end_line = lines[markers.end]
        terminator = end_line[len(_content(end_line)) :]
        new_block = block[: -len(eol)] + terminator if terminator != eol else block
        return "".join(lines[: markers.start]) + new_block + "".join(lines[markers.end + 1 :])
    if insert == "none":
        raise ReadmeError(
            f"README has no {START_MARKER} / {END_MARKER} markers. Add them where the graph "
            "should appear (run `gitgraph init --add-markers`), or set `readme.insert` to "
            "append, prepend or after-first-heading."
        )
    if insert == "prepend":
        return block + (eol + text if text else "")
    if insert == "after-first-heading":
        _, _, heading = _scan(lines)
        if heading is not None:
            head = lines[heading]
            if not head.endswith(("\n", "\r")):
                head += eol
            return (
                "".join(lines[:heading]) + head + eol + block + eol + "".join(lines[heading + 1 :])
            )
        insert = "append"
    if insert == "append":
        if not text:
            return block
        body = text if text.endswith(("\n", "\r")) else text + eol
        return body + eol + block
    raise ReadmeError(f"unknown insert mode {insert!r}")


def read_text(path: Path) -> str:
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except UnicodeDecodeError as exc:
        raise ReadmeError(f"{path} is not valid UTF-8; it was not modified.") from exc


def atomic_write(path: Path, data: str) -> None:
    """Write via a temporary file in the same directory, preserving permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".gitgraph-", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(data)
        if path.exists():
            shutil.copymode(path, tmp)
        else:
            tmp.chmod(0o644)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def update_readme(path: Path, block: str, insert: str = "none", *, create: bool = False) -> bool:
    """Update ``path`` in place. Returns ``True`` if the file changed."""
    if not path.exists():
        if not create:
            raise ReadmeError(f"{path} does not exist")
        atomic_write(path, block)
        return True
    original = read_text(path)
    updated = apply_block(original, block, insert)
    if updated == original:
        return False
    atomic_write(path, updated)
    return True
