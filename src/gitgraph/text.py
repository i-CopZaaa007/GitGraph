"""Untrusted-text sanitising, width estimation and wrapping.

Widths are heuristic: SVG text is measured by the viewer's fonts, which we cannot know. The
estimates err on the wide side so that wrapped labels do not overflow their column.
"""

from __future__ import annotations

import unicodedata

ELLIPSIS = "…"
_BIDI_CONTROLS = frozenset("‪‫‬‭‮⁦⁧⁨⁩")
_NARROW = frozenset("iljtfI.,:;'|!()[]{}`")
_WIDE_LATIN = frozenset("mwMW@")


def clean_text(value: str, *, keep_newlines: bool = False) -> str:
    """Drop characters that are invalid in XML or enable visual spoofing.

    Control characters, surrogates, non-characters and bidirectional override/isolate controls
    are removed. Tabs become spaces. Newlines are kept only when ``keep_newlines`` is true;
    otherwise they become spaces. Nothing else is rewritten (no normalisation, no trimming of
    inner whitespace).
    """
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        if ch == "\n":
            out.append("\n" if keep_newlines else " ")
        elif ch == "\r":
            continue
        elif ch == "\t":
            out.append(" ")
        elif (
            code < 0x20
            or 0x7F <= code <= 0x9F
            or 0xD800 <= code <= 0xDFFF
            or code in (0xFFFE, 0xFFFF)
            or ch in _BIDI_CONTROLS
        ):
            continue
        else:
            out.append(ch)
    return "".join(out)


def char_width_em(ch: str) -> float:
    """Estimated advance width of one code point, in em."""
    category = unicodedata.category(ch)
    if category in ("Mn", "Me", "Cf"):
        return 0.0
    if unicodedata.east_asian_width(ch) in ("W", "F") or ord(ch) >= 0x1F000:
        return 1.05
    if ch == " ":
        return 0.3
    if ch in _NARROW:
        return 0.34
    if ch in _WIDE_LATIN:
        return 0.9
    if ch.isupper():
        return 0.7
    return 0.6


def text_width(value: str, font_size: float) -> float:
    """Estimated rendered width in pixels."""
    return sum(char_width_em(ch) for ch in value) * font_size


def _clusters(token: str) -> list[str]:
    """Split into base characters with trailing combining marks attached."""
    clusters: list[str] = []
    for ch in token:
        if clusters and char_width_em(ch) == 0.0:
            clusters[-1] += ch
        else:
            clusters.append(ch)
    return clusters


def truncate_to_width(value: str, max_width: float, font_size: float) -> str:
    """Shorten ``value`` with an ellipsis so that it fits ``max_width``."""
    if text_width(value, font_size) <= max_width:
        return value
    budget = max_width - text_width(ELLIPSIS, font_size)
    out = ""
    used = 0.0
    for cluster in _clusters(value):
        width = text_width(cluster, font_size)
        if used + width > budget:
            break
        out += cluster
        used += width
    return out.rstrip() + ELLIPSIS


def wrap_paragraph(value: str, max_width: float, font_size: float) -> list[str]:
    """Greedy word wrap; words wider than a line are broken between characters."""
    lines: list[str] = []
    current = ""
    for word in value.split():
        candidate = f"{current} {word}" if current else word
        if text_width(candidate, font_size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if text_width(word, font_size) <= max_width:
            current = word
            continue
        piece = ""
        for cluster in _clusters(word):
            if piece and text_width(piece + cluster, font_size) > max_width:
                lines.append(piece)
                piece = ""
            piece += cluster
        current = piece
    if current:
        lines.append(current)
    return lines or [""]


def wrap_limited(
    paragraphs: list[str], max_width: float, font_size: float, max_lines: int
) -> list[str]:
    """Wrap paragraphs; if more than ``max_lines`` result, truncate the last with an ellipsis."""
    lines: list[str] = []
    for paragraph in paragraphs:
        lines.extend(wrap_paragraph(paragraph, max_width, font_size))
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = truncate_to_width(kept[-1] + ELLIPSIS, max_width, font_size)
    if not kept[-1].endswith(ELLIPSIS):
        kept[-1] += ELLIPSIS
    return kept
