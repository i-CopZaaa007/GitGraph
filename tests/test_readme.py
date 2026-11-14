from __future__ import annotations

from pathlib import Path

import pytest

from gitgraph.readme import (
    END_MARKER,
    START_MARKER,
    ReadmeError,
    apply_block,
    build_block,
    find_markers,
    update_readme,
)

BLOCK = build_block("docs/g.svg", "Commit graph", 2, "alt")


def test_replaces_only_between_markers() -> None:
    text = f"# Title\n\nintro\n\n{START_MARKER}\nOLD STUFF\n{END_MARKER}\n\n## After\ntail\n"
    out = apply_block(text, BLOCK)
    assert out.startswith("# Title\n\nintro\n\n")
    assert out.endswith("\n\n## After\ntail\n")
    assert "OLD STUFF" not in out
    assert "![alt](docs/g.svg)" in out


def test_idempotent() -> None:
    text = f"# T\n\n{START_MARKER}\nold\n{END_MARKER}\nmore\n"
    once = apply_block(text, BLOCK)
    assert apply_block(once, BLOCK) == once


@pytest.mark.parametrize("insert", ["append", "prepend", "after-first-heading"])
def test_insertion_modes_are_idempotent_and_preserve_content(insert: str) -> None:
    text = "# Project\n\nSome text.\n\n## Usage\n\nrun it\n"
    once = apply_block(text, BLOCK, insert)
    assert apply_block(once, BLOCK, insert) == once
    assert once.replace(BLOCK, "").count("run it") == 1
    for line in text.splitlines():
        assert line in once.splitlines()
    assert find_markers(once) is not None


def test_after_first_heading_position() -> None:
    out = apply_block("# Project\n\nText\n", BLOCK, "after-first-heading")
    lines = out.splitlines()
    assert lines[0] == "# Project"
    assert lines[2] == START_MARKER
    assert out.rstrip().endswith("Text")


def test_none_without_markers_is_an_error() -> None:
    with pytest.raises(ReadmeError, match=r"no .*markers"):
        apply_block("# Hi\n", BLOCK, "none")


@pytest.mark.parametrize(
    "text",
    [
        f"{START_MARKER}\nonly start\n",
        f"{END_MARKER}\nonly end\n",
        f"{START_MARKER}\n{START_MARKER}\n{END_MARKER}\n",
        f"{START_MARKER}\n{END_MARKER}\n{END_MARKER}\n",
        f"{END_MARKER}\n{START_MARKER}\n",
    ],
)
def test_malformed_markers_fail_safely(text: str) -> None:
    with pytest.raises(ReadmeError):
        apply_block(text, BLOCK, "append")


def test_markers_inside_code_fences_are_ignored() -> None:
    text = f"# Docs\n\n```md\n{START_MARKER}\n{END_MARKER}\n```\n"
    assert find_markers(text) is None
    out = apply_block(text, BLOCK, "append")
    assert out.startswith(text)  # fenced example untouched
    assert find_markers(out) is not None


def test_inline_mentions_are_not_markers() -> None:
    text = f"Use `{START_MARKER}` and `{END_MARKER}` to delimit.\n"
    assert find_markers(text) is None


def test_crlf_is_preserved() -> None:
    text = f"# T\r\n\r\n{START_MARKER}\r\nold\r\n{END_MARKER}\r\ntail\r\n"
    out = apply_block(text, BLOCK)
    assert "\n" not in out.replace("\r\n", "")
    assert out.endswith("tail\r\n")
    assert apply_block(out, BLOCK) == out
    appended = apply_block("# T\r\ntext\r\n", BLOCK, "append")
    assert "\n" not in appended.replace("\r\n", "")


def test_missing_trailing_newline_is_kept() -> None:
    text = f"x\n{START_MARKER}\nold\n{END_MARKER}"
    out = apply_block(text, BLOCK)
    assert out.endswith(END_MARKER) and not out.endswith("\n")


def test_empty_readme() -> None:
    out = apply_block("", BLOCK, "append")
    assert out == BLOCK


def test_update_file_atomic_and_unchanged_returns_false(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_text("# Hi\n", encoding="utf-8")
    assert update_readme(path, BLOCK, "append") is True
    first = path.read_text(encoding="utf-8")
    assert update_readme(path, BLOCK, "append") is False
    assert path.read_text(encoding="utf-8") == first
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".gitgraph-")]


def test_malformed_file_is_not_modified(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    original = f"keep me\n{START_MARKER}\nnever closed\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ReadmeError):
        update_readme(path, BLOCK, "append")
    assert path.read_text(encoding="utf-8") == original


def test_non_utf8_file_is_not_modified(tmp_path: Path) -> None:
    path = tmp_path / "README.md"
    path.write_bytes(b"\xff\xfe bad")
    with pytest.raises(ReadmeError):
        update_readme(path, BLOCK, "append")
    assert path.read_bytes() == b"\xff\xfe bad"


def test_alt_text_cannot_break_markdown() -> None:
    block = build_block("a.svg", "", 2, "x](http://evil)[y\nz")
    assert (
        "![x  http://evil)  y z](a.svg)" in block
        or "](http://evil)" not in block.split("\n")[2][:6]
    )
    assert block.count("\n![") == 1
