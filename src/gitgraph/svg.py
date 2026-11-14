"""SVG renderer. Consumes a :class:`GraphLayout`; never touches Git.

All text is sanitised and XML-escaped. The output is a self-contained document: no scripts, no
external fonts or images. Colour themes are implemented with an embedded stylesheet.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from html import escape

from gitgraph.layout import Badge, GraphEdge, GraphLayout, GraphNode
from gitgraph.text import clean_text, text_width
from gitgraph.theme import theme_css
from gitgraph.urls import format_link, is_safe_http_url


@dataclass(frozen=True, slots=True)
class RenderOptions:
    theme: str = "light"
    responsive: bool = True
    repository_url: str | None = None
    commit_url: str = "{repo}/commit/{sha}"
    tag_url: str = "{repo}/tree/{tag}"


def _num(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _attr(value: str) -> str:
    return escape(clean_text(value), quote=True)


def _text(value: str) -> str:
    return escape(clean_text(value), quote=False)


def _edge_path(edge: GraphEdge) -> str:
    pts = edge.points
    parts = [f"M{_num(pts[0][0])} {_num(pts[0][1])}"]
    for (x0, y0), (x1, y1) in itertools.pairwise(pts):
        if x0 == x1:
            parts.append(f"L{_num(x1)} {_num(y1)}")
        else:
            mid = (y0 + y1) / 2
            parts.append(f"C{_num(x0)} {_num(mid)} {_num(x1)} {_num(mid)} {_num(x1)} {_num(y1)}")
    return " ".join(parts)


class _Links:
    def __init__(self, options: RenderOptions) -> None:
        url = options.repository_url
        self.base = url if url and is_safe_http_url(url) else None
        self.options = options

    def commit(self, sha: str) -> str | None:
        if self.base is None:
            return None
        return format_link(self.options.commit_url, self.base, sha=sha)

    def tag(self, name: str) -> str | None:
        if self.base is None or not name:
            return None
        return format_link(self.options.tag_url, self.base, tag=name)


def _wrap_link(markup: str, href: str | None) -> str:
    if href is None:
        return markup
    return f'<a href="{_attr(href)}" target="_blank">{markup}</a>'


def render_svg(layout: GraphLayout, options: RenderOptions | None = None) -> str:
    """Render ``layout`` as a standalone SVG document."""
    options = options or RenderOptions()
    opts = layout.options
    links = _Links(options)
    out: list[str] = []
    w, h = _num(layout.width), _num(layout.height)
    counts = layout.counts
    title = f"{clean_text(opts.title)} – Git history graph"
    desc = (
        f"Vertical Git commit graph with {counts.get('commits', 0)} commits, "
        f"{counts.get('merges', 0)} merge commits and {counts.get('branches', 0)} branch lines. "
        "Newest commits are at the top; the oldest commit is at the bottom."
    )
    if layout.release is not None:
        desc += f" Latest tag: {clean_text(layout.release.name)}."
    style = ' style="max-width:100%;height:auto"' if options.responsive else ""
    out.append(
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="gg-title gg-desc" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}"{style} '
        f'font-family="{_attr(opts.font_family)}" font-size="{_num(opts.font_size)}">'
    )
    out.append(f'<title id="gg-title">{_text(title)}</title>')
    out.append(f'<desc id="gg-desc">{_text(desc)}</desc>')
    out.append(f"<style>\n{theme_css(options.theme)}\n</style>")
    out.append(f'<rect class="bg" x="0" y="0" width="{w}" height="{h}" rx="8"/>')

    _header(out, layout)
    out.append('<g class="edges" fill="none" stroke-linecap="round" stroke-linejoin="round">')
    for edge in layout.edges:
        out.append(_edge_markup(edge, opts.line_width, opts.node_radius))
    out.append("</g>")
    out.append('<g class="nodes">')
    for node in layout.nodes:
        out.append(_node_markup(node, layout, links))
    out.append("</g>")
    _footer(out, layout)
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _header(out: list[str], layout: GraphLayout) -> None:
    opts = layout.options
    pad = _num(opts.padding)
    if layout.title_y is not None:
        out.append(
            f'<text class="text" x="{pad}" y="{_num(layout.title_y)}" '
            f'font-size="{_num(opts.font_size + 5)}" font-weight="600">{_text(opts.title)}</text>'
        )
    if layout.stats_y is not None:
        out.append(
            f'<text class="muted" x="{pad}" y="{_num(layout.stats_y)}" '
            f'font-size="{_num(opts.meta_size)}">{_text(layout.stats_text)}</text>'
        )
    rel = layout.release
    if rel is not None:
        x, y = rel.x, rel.y
        kind = "annotated tag" if rel.annotated else "tag"
        out.append('<g class="release">')
        out.append(
            f'<rect class="accent" x="{_num(x)}" y="{_num(y)}" width="3" '
            f'height="{_num(rel.height)}" rx="1.5"/>'
        )
        name_size = opts.font_size + 3
        out.append(
            f'<text class="text" x="{_num(x + 14)}" y="{_num(y + name_size)}" '
            f'font-size="{_num(name_size)}" font-weight="700">{_text(rel.name)}</text>'
        )
        name_w = text_width(clean_text(rel.name), name_size) * 1.08
        detail = f"latest {kind} \u00b7 {rel.date} \u00b7 {rel.short_sha}"
        out.append(
            f'<text class="muted" x="{_num(x + 14 + name_w + 10)}" y="{_num(y + name_size)}" '
            f'font-size="{_num(opts.meta_size)}">{_text(detail)}</text>'
        )
        if rel.message:
            out.append(
                f'<text class="muted" x="{_num(x + 14)}" '
                f'y="{_num(y + name_size + opts.meta_height + 4)}" '
                f'font-size="{_num(opts.meta_size)}">{_text(rel.message)}</text>'
            )
        out.append("</g>")
    if layout.legend:
        out.append('<g class="legend">')
        for item in layout.legend:
            dash = f' stroke-dasharray="{_attr(item.dash)}"' if item.dash else ""
            cy = item.y + 7
            out.append(
                f"<g><title>{_text(item.full_text)}</title>"
                f'<line x1="{_num(item.x)}" y1="{_num(cy)}" x2="{_num(item.x + 24)}" '
                f'y2="{_num(cy)}" stroke="{_attr(item.color)}" '
                f'stroke-width="{_num(opts.line_width)}"{dash} stroke-linecap="round"/>'
                f'<circle class="node" cx="{_num(item.x + 12)}" cy="{_num(cy)}" r="3.5" '
                f'stroke="{_attr(item.color)}" stroke-width="2"/>'
                f'<text class="text" x="{_num(item.x + 30)}" y="{_num(cy + 4)}" '
                f'font-size="{_num(opts.meta_size + 1)}">{_text(item.text)}</text></g>'
            )
        if layout.legend_overflow:
            last = layout.legend[-1]
            out.append(
                f'<text class="muted" x="{_num(opts.padding)}" y="{_num(last.y + 33)}" '
                f'font-size="{_num(opts.meta_size)}">{_text(layout.legend_overflow)}</text>'
            )
        out.append("</g>")


def _edge_markup(edge: GraphEdge, line_width: float, radius: float) -> str:
    dash = f' stroke-dasharray="{_attr(edge.dash)}"' if edge.dash else ""
    if edge.kind == "missing":
        end_x, end_y = edge.points[-1]
        return (
            f'<path d="{_edge_path(edge)}" stroke="{_attr(edge.color)}" '
            f'stroke-width="{_num(line_width)}" stroke-dasharray="3 3"/>'
            f'<circle class="node" cx="{_num(end_x)}" cy="{_num(end_y)}" r="{_num(radius * 0.45)}" '
            f'stroke="{_attr(edge.color)}" stroke-width="1.5"/>'
        )
    return (
        f'<path d="{_edge_path(edge)}" stroke="{_attr(edge.color)}" '
        f'stroke-width="{_num(line_width)}"{dash}/>'
    )


def _badge_markup(badge: Badge, links: _Links, font_size: float) -> str:
    x, y, w, h = badge.x, badge.y, badge.width, badge.height
    text_y = y + h / 2 + font_size * 0.35
    if badge.kind in ("tag", "latest-tag"):
        # Tags are plain text with a small flag; the newest one is bold and accent-coloured.
        latest = badge.kind == "latest-tag"
        cls = "accent" if latest else "muted"
        weight = "700" if latest else "500"
        cy = y + h / 2
        inner = (
            f'<path class="{cls}" d="M{_num(x + 1)} {_num(cy - 6)}v12h1.6v-4.5h5.4l-1.4-3.2 '
            f'1.4-3.2h-5.4v-1.1z"/>'
            f'<text class="{cls}" x="{_num(x + 14)}" y="{_num(text_y)}" '
            f'font-size="{_num(font_size)}" font-weight="{weight}">{_text(badge.text)}</text>'
        )
        title = f"{'Latest tag' if latest else 'Tag'}: {badge.text}"
        return _wrap_link(f"<g><title>{_text(title)}</title>{inner}</g>", links.tag(badge.target))
    if badge.kind == "more":
        return (
            f'<text class="muted" x="{_num(x)}" y="{_num(text_y)}" '
            f'font-size="{_num(font_size)}">{_text(badge.text)}</text>'
        )
    color = badge.color
    if badge.kind == "remote":
        stroke = f' stroke="{_attr(color)}"' if color else ""
        return (
            f'<g><rect class="node{"" if color else " border"}" x="{_num(x)}" y="{_num(y)}" '
            f'width="{_num(w)}" height="{_num(h)}" rx="3"{stroke} stroke-width="1.5" '
            f'stroke-dasharray="3 2"/>'
            f'<text class="text" x="{_num(x + 7)}" y="{_num(text_y)}" '
            f'font-size="{_num(font_size)}">{_text(badge.text)}</text></g>'
        )
    if color:  # a "line sign": solid colour, white text, like a transit line badge
        return (
            f'<g><rect x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" height="{_num(h)}" '
            f'rx="3" fill="{_attr(color)}"/>'
            f'<text class="onsign" x="{_num(x + 7)}" y="{_num(text_y)}" '
            f'font-size="{_num(font_size)}" font-weight="600">{_text(badge.text)}</text></g>'
        )
    return (
        f'<g><rect class="surface border" x="{_num(x)}" y="{_num(y)}" width="{_num(w)}" '
        f'height="{_num(h)}" rx="3" stroke-width="1"/>'
        f'<text class="text" x="{_num(x + 7)}" y="{_num(text_y)}" '
        f'font-size="{_num(font_size)}">{_text(badge.text)}</text></g>'
    )


def _node_shape(node: GraphNode, radius: float, line_width: float) -> str:
    """Stations: ring = commit, heavy dark ring = merge (interchange), square = terminus."""
    cx, cy, r = node.x, node.y, radius
    color = _attr(node.color)
    ring = _num(max(line_width - 0.5, 2))
    if node.kind == "merge":
        return (
            f'<circle class="node ink" cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r + 2)}" '
            f'stroke-width="{_num(line_width)}"/>'
        )
    if node.kind in ("root", "boundary"):
        d = r + 0.5
        shape = (
            f'x="{_num(cx - d)}" y="{_num(cy - d)}" width="{_num(2 * d)}" height="{_num(2 * d)}" '
            f'rx="2"'
        )
        if node.kind == "boundary":
            return (
                f'<rect class="node terminus" {shape} stroke="{color}" '
                f'stroke-width="{ring}" stroke-dasharray="2 2"/>'
            )
        return f'<rect class="terminus" {shape} fill="{color}"/>'
    return (
        f'<circle class="node" cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(r)}" '
        f'stroke="{color}" stroke-width="{ring}"/>'
    )


def _node_markup(node: GraphNode, layout: GraphLayout, links: _Links) -> str:
    opts = layout.options
    kind_text = {
        "merge": "merge commit",
        "root": "initial (root) commit",
        "boundary": "shallow boundary commit",
    }.get(node.kind, "commit")
    reach = ", ".join(node.reachable_from) or "no collected branch"
    tooltip = (
        f"{node.short_sha} – {node.subject}\n{kind_text}\n"
        f"Author: {node.author}\nReachable from: {reach}"
    )
    parts = [f"<g><title>{_text(tooltip)}</title>"]
    parts.append(_node_shape(node, opts.node_radius, opts.line_width))
    parts.append("</g>")
    node_markup = "".join(parts)
    href = links.commit(node.sha)
    label: list[str] = []
    for i, line in enumerate(node.lines):
        baseline = (
            node.lines_top + i * opts.line_height + opts.line_height / 2 + opts.font_size * 0.35
        )
        label.append(
            f'<text class="text" x="{_num(node.label_x)}" y="{_num(baseline)}">{_text(line)}</text>'
        )
    if node.meta:
        baseline = node.meta_y + opts.meta_height / 2 + opts.meta_size * 0.35
        label.append(
            f'<text class="muted" x="{_num(node.label_x)}" y="{_num(baseline)}" '
            f'font-size="{_num(opts.meta_size)}">{_text(node.meta)}</text>'
        )
    label_markup = _wrap_link("".join(label), href)
    badges = "".join(_badge_markup(b, links, opts.badge_size) for b in node.badges)
    return _wrap_link(node_markup, href) + label_markup + badges


def _footer(out: list[str], layout: GraphLayout) -> None:
    opts = layout.options
    if layout.empty_message is not None:
        y = layout.height - opts.padding - opts.line_height / 2 + opts.font_size * 0.35
        out.append(
            f'<text class="muted" x="{_num(opts.padding)}" y="{_num(y)}">'
            f"{_text(layout.empty_message)}</text>"
        )
        return
    if layout.rule_y is not None:
        out.append(
            f'<line class="border" x1="{_num(opts.padding)}" y1="{_num(layout.rule_y)}" '
            f'x2="{_num(layout.width - opts.padding)}" y2="{_num(layout.rule_y)}" '
            'stroke-width="1" stroke-dasharray="4 4"/>'
        )
    for note in layout.notes:
        out.append(
            f'<text class="muted" x="{_num(opts.padding)}" y="{_num(note.y)}" '
            f'font-size="{_num(opts.meta_size)}">{_text(note.text)}</text>'
        )
