"""Geometry: rows, coordinates, labels, badges, edge routes, header and footer.

The layout engine consumes a snapshot and its graph and produces a :class:`GraphLayout`. It never
calls Git and knows nothing about renderers or hosting providers. All coordinates are in SVG user
units (pixels). Row heights adapt to the label text, so rows are never too short for their label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from gitgraph.graph import CommitGraph
from gitgraph.lanes import EdgeRoute, LaneStyle, Placement, place, resolve_primary
from gitgraph.models import Diagnostic, RepositorySnapshot, Tag
from gitgraph.tags import select_latest, sort_tags
from gitgraph.text import (
    clean_text,
    text_width,
    truncate_to_width,
    wrap_limited,
)
from gitgraph.theme import DEFAULT_PALETTE, MUTED_PALETTE

DEFAULT_FONT = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", "Noto Sans Thai", '
    "Helvetica, Arial, sans-serif"
)
MAX_BADGES = 8
BADGE_HEIGHT = 18.0
BADGE_GAP = 4.0
MIN_WIDTH = 380.0


@dataclass(frozen=True, slots=True)
class LayoutOptions:
    title: str = "Commit graph"
    show_title: bool = True
    show_legend: bool = True
    show_release_summary: bool = True
    show_tags: bool = True
    show_branch_labels: bool = True
    show_sha: bool = True
    show_author: bool = False
    show_date: bool = False
    message_mode: str = "subject"  # "subject" | "full"
    max_label_lines: int = 3
    label_width: float = 520.0
    font_family: str = DEFAULT_FONT
    font_size: float = 13.0
    node_radius: float = 6.0
    line_width: float = 3.5
    lane_spacing: float = 22.0
    row_gap: float = 16.0
    min_row_height: float = 40.0
    padding: float = 24.0
    label_gap: float = 24.0
    curve_height: float = 18.0
    palette: tuple[str, ...] = DEFAULT_PALETTE
    muted_palette: tuple[str, ...] = MUTED_PALETTE
    latest_tag_strategy: str = "auto"
    primary_branch: str | None = None

    @property
    def line_height(self) -> float:
        return round(self.font_size * 1.4, 2)

    @property
    def meta_size(self) -> float:
        return max(8.0, self.font_size - 2)

    @property
    def meta_height(self) -> float:
        return round(self.meta_size * 1.45, 2)

    @property
    def badge_size(self) -> float:
        return max(8.0, self.font_size - 2)


@dataclass(frozen=True, slots=True)
class Badge:
    text: str
    kind: str  # "branch" | "remote" | "head" | "tag" | "latest-tag" | "more"
    color: str | None
    x: float
    y: float
    width: float
    height: float
    target: str = ""  # tag name for tag badges (used for links)


@dataclass(frozen=True, slots=True)
class GraphNode:
    sha: str
    short_sha: str
    row: int
    column: int
    x: float
    y: float
    kind: str  # "commit" | "merge" | "root" | "boundary"
    color: str
    dash: str | None
    lane: str | None
    parent_count: int
    label_x: float
    label_top: float
    label_height: float
    lines: tuple[str, ...]
    lines_top: float
    meta: str
    meta_y: float
    badges: tuple[Badge, ...]
    reachable_from: tuple[str, ...]
    author: str
    authored_at: int
    subject: str


@dataclass(frozen=True, slots=True)
class GraphEdge:
    child: str
    parent: str | None
    kind: str  # "parent" | "merge" | "missing"
    color: str
    dash: str | None
    lane: str | None
    points: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class BranchLane:
    key: str | None
    label: str
    color: str
    dash: str | None
    commit_count: int
    is_primary: bool


@dataclass(frozen=True, slots=True)
class LegendItem:
    text: str
    full_text: str
    color: str
    dash: str | None
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ReleaseSummary:
    name: str
    annotated: bool
    sha: str
    short_sha: str
    date: str
    message: str | None
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class FooterNote:
    text: str
    y: float


@dataclass(frozen=True, slots=True)
class GraphLayout:
    options: LayoutOptions
    width: float
    height: float
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    lanes: tuple[BranchLane, ...]
    label_x: float
    title_y: float | None
    stats_text: str
    stats_y: float | None
    release: ReleaseSummary | None
    legend: tuple[LegendItem, ...]
    legend_overflow: str | None
    rule_y: float | None
    notes: tuple[FooterNote, ...]
    empty_message: str | None
    diagnostics: tuple[Diagnostic, ...]
    counts: dict[str, int] = field(default_factory=dict)


def format_date(timestamp: int) -> str:
    try:
        return datetime.fromtimestamp(timestamp, UTC).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return "unknown date"


@dataclass(slots=True)
class _RowContent:
    lines: list[str]
    meta: str
    badges: list[Badge]
    badge_rows: int
    block_height: float
    row_height: float


def _label_lines(subject: str, body: str, options: LayoutOptions) -> list[str]:
    paragraphs = [clean_text(subject) or "(no subject)"]
    if options.message_mode == "full" and body:
        cleaned = clean_text(body, keep_newlines=True)
        paragraphs.extend(p for p in (line.strip() for line in cleaned.split("\n")) if p)
    return wrap_limited(paragraphs, options.label_width, options.font_size, options.max_label_lines)


def _meta_text(sha: str, author: str, timestamp: int, options: LayoutOptions) -> str:
    parts: list[str] = []
    if options.show_sha:
        parts.append(sha[:7])
    if options.show_author:
        parts.append(clean_text(author))
    if options.show_date:
        parts.append(format_date(timestamp))
    return truncate_to_width(" · ".join(parts), options.label_width, options.meta_size)


def _pill_width(text: str, options: LayoutOptions, *, icon: bool) -> float:
    return text_width(text, options.badge_size) + 14 + (12 if icon else 0)


def _build_badges(
    names: list[tuple[str, str, str | None, str]],
    options: LayoutOptions,
) -> tuple[list[Badge], int]:
    """Place pills left to right inside ``label_width``, wrapping to further rows."""
    shown = names
    extra = 0
    if len(names) > MAX_BADGES:
        shown = names[: MAX_BADGES - 1]
        extra = len(names) - len(shown)
    entries = list(shown)
    if extra:
        entries.append((f"+{extra} more", "more", None, ""))
    badges: list[Badge] = []
    x = 0.0
    row = 0
    for text, kind, color, target in entries:
        text = truncate_to_width(text, 220, options.badge_size)
        width = _pill_width(text, options, icon=kind in ("tag", "latest-tag"))
        if x > 0 and x + width > options.label_width:
            row += 1
            x = 0.0
        badges.append(
            Badge(
                text, kind, color, x, row * (BADGE_HEIGHT + BADGE_GAP), width, BADGE_HEIGHT, target
            )
        )
        x += width + 6
    return badges, (row + 1 if badges else 0)


def _route_points(
    route: EdgeRoute,
    xs: dict[int, float],
    y_child: float,
    y_parent: float | None,
    options: LayoutOptions,
) -> tuple[tuple[float, float], ...]:
    x_child = xs[route.child_column]
    if y_parent is None or route.parent_column is None:
        return ((x_child, y_child), (x_child, y_child + options.node_radius * 2.4))
    x_travel = xs[route.travel_column]
    x_parent = xs[route.parent_column]
    half = min(options.curve_height, (y_parent - y_child) / 2)
    points = [(x_child, y_child)]
    if x_travel != x_child:
        points.append((x_travel, y_child + half))
    if x_parent != x_travel:
        points.append((x_travel, y_parent - half))
    points.append((x_parent, y_parent))
    return tuple(points)


def build_layout(
    snapshot: RepositorySnapshot, graph: CommitGraph, options: LayoutOptions | None = None
) -> GraphLayout:
    """Compute the full layout for ``graph``."""
    options = options or LayoutOptions()
    diagnostics = [*snapshot.diagnostics, *graph.diagnostics]
    primary = resolve_primary(
        snapshot.refs, options.primary_branch, snapshot.default_branch, snapshot.head_branch
    )
    placement = place(graph, snapshot.refs, options.palette, options.muted_palette, primary)

    # Tags and refs per commit.
    included = set(graph.order)
    committed_at = {sha: c.committed_at for sha, c in graph.commits.items()}
    visible_tags = (
        [t for t in snapshot.tags if t.target_sha in included] if options.show_tags else []
    )
    latest = select_latest(visible_tags, committed_at, options.latest_tag_strategy)
    tags_at: dict[str, list[Tag]] = {}
    for tag in sort_tags(visible_tags, committed_at):
        tags_at.setdefault(tag.target_sha, []).append(tag)
    refs_at: dict[str, list[tuple[str, str, str | None, str]]] = {}
    if options.show_branch_labels:
        for ref in sorted(snapshot.refs, key=lambda r: (r.kind.value, r.short_name)):
            if ref.target_sha not in included:
                continue
            lane = placement.lane_styles.get(ref.branch_name)
            kind = {"remote_branch": "remote", "other": "head"}.get(ref.kind.value, "branch")
            refs_at.setdefault(ref.target_sha, []).append(
                (clean_text(ref.short_name), kind, lane.color if lane else None, "")
            )

    # 1. Row content and heights (independent of columns).
    rows: dict[str, _RowContent] = {}
    for sha in graph.order:
        commit = graph.commits[sha]
        lines = _label_lines(commit.subject, commit.body, options)
        meta = _meta_text(sha, commit.author.name, commit.authored_at, options)
        entries: list[tuple[str, str, str | None, str]] = []
        for tag in tags_at.get(sha, []):
            kind = "latest-tag" if latest is not None and tag.name == latest.name else "tag"
            entries.append((clean_text(tag.name), kind, None, tag.name))
        entries.extend(refs_at.get(sha, []))
        badges, badge_rows = _build_badges(entries, options)
        block = (
            badge_rows * (BADGE_HEIGHT + BADGE_GAP)
            + len(lines) * options.line_height
            + (options.meta_height if meta else 0)
        )
        rows[sha] = _RowContent(
            lines,
            meta,
            badges,
            badge_rows,
            block,
            max(options.min_row_height, block + options.row_gap),
        )

    # 2. Horizontal geometry.
    pad = options.padding
    xs = {
        c: pad + options.node_radius + 2 + c * options.lane_spacing
        for c in range(max(placement.column_count, 1))
    }
    lanes_right = xs[placement.column_count - 1] + options.node_radius if graph.order else pad
    label_x = lanes_right + options.label_gap
    width = max(MIN_WIDTH, label_x + options.label_width + pad)
    content_w = width - 2 * pad

    # 3. Header.
    y = pad
    title_y: float | None = None
    stats_y: float | None = None
    if options.show_title:
        title_y = y + options.font_size + 5
        y += options.font_size + 12
    counts = {
        "commits": len(graph.order),
        "merges": len(graph.merges),
        "roots": len(graph.roots),
        "branches": len(placement.lane_styles),
        "tags": len(visible_tags),
    }
    stats_text = (
        f"{counts['commits']} commits · {counts['merges']} merges · "
        f"{len({r.branch_name for r in snapshot.refs})} branches · {counts['tags']} tags"
    )
    if options.show_title:
        stats_y = y + options.meta_size + 4
        y += options.meta_size + 14
    release: ReleaseSummary | None = None
    if options.show_release_summary and latest is not None:
        height = 40.0 if latest.message else 22.0
        when = latest.tagged_at if latest.tagged_at is not None else committed_at[latest.target_sha]
        release = ReleaseSummary(
            name=clean_text(latest.name),
            annotated=latest.annotated,
            sha=latest.target_sha,
            short_sha=latest.target_sha[:7],
            date=format_date(when),
            message=truncate_to_width(clean_text(latest.message), content_w - 28, options.meta_size)
            if latest.message
            else None,
            x=pad,
            y=y,
            width=content_w,
            height=height,
        )
        y += height + 14
    legend, legend_overflow, y = _layout_legend(placement, options, content_w, y)
    y += 6

    # 4. Row positions.
    nodes: list[GraphNode] = []
    y_of: dict[str, float] = {}
    row_index: dict[str, int] = {}
    cursor = y
    for i, sha in enumerate(graph.order):
        row = rows[sha]
        centre = cursor + row.row_height / 2
        y_of[sha] = centre
        row_index[sha] = i
        top = centre - row.block_height / 2
        lines_top = top + row.badge_rows * (BADGE_HEIGHT + BADGE_GAP)
        meta_y = lines_top + len(row.lines) * options.line_height
        placed = tuple(
            Badge(b.text, b.kind, b.color, label_x + b.x, top + b.y, b.width, b.height, b.target)
            for b in row.badges
        )
        commit = graph.commits[sha]
        if commit.is_root:
            kind = "boundary" if sha in snapshot.shallow_boundary else "root"
        else:
            kind = "merge" if commit.is_merge else "commit"
        style = placement.node_styles[sha]
        nodes.append(
            GraphNode(
                sha=sha,
                short_sha=sha[:7],
                row=i,
                column=placement.columns[sha],
                x=xs[placement.columns[sha]],
                y=centre,
                kind=kind,
                color=style.color,
                dash=style.dash,
                lane=style.key,
                parent_count=len(commit.parents),
                label_x=label_x,
                label_top=top,
                label_height=row.block_height,
                lines=tuple(row.lines),
                lines_top=lines_top,
                meta=row.meta,
                meta_y=meta_y,
                badges=placed,
                reachable_from=tuple(graph.refs_reaching(sha)),
                author=clean_text(commit.author.name),
                authored_at=commit.authored_at,
                subject=clean_text(commit.subject),
            )
        )
        cursor += row.row_height
    cursor_end = cursor

    # 5. Edges.
    edges = [
        GraphEdge(
            child=r.child,
            parent=r.parent,
            kind=r.kind,
            color=r.style.color,
            dash=r.style.dash,
            lane=r.style.key,
            points=_route_points(
                r, xs, y_of[r.child], y_of.get(r.parent) if r.parent else None, options
            ),
        )
        for r in sorted(
            placement.routes,
            key=lambda r: (row_index[r.child], r.kind, row_index.get(r.parent or "", 1 << 30)),
        )
    ]

    # 6. Lanes for the legend.
    lanes = [
        BranchLane(k, clean_text(k), s.color, s.dash, placement.lane_commit_counts[k], k == primary)
        for k, s in placement.lane_styles.items()
    ]

    # 7. Footer.
    notes: list[FooterNote]
    rule_y: float | None
    notes, rule_y, height = _footer(snapshot, graph, options, content_w, cursor_end, nodes)
    empty_message = None
    if not graph.order:
        empty_message = (
            "No commits to display. The repository is empty or no references were collected."
        )
        empty_y = y + 10
        height = empty_y + options.line_height + pad
        rule_y = None
        notes = []
    return GraphLayout(
        options=options,
        width=width,
        height=height,
        nodes=tuple(nodes),
        edges=tuple(edges),
        lanes=tuple(lanes),
        label_x=label_x,
        title_y=title_y,
        stats_text=stats_text,
        stats_y=stats_y,
        release=release,
        legend=tuple(legend),
        legend_overflow=legend_overflow,
        rule_y=rule_y,
        notes=tuple(notes),
        empty_message=empty_message,
        diagnostics=tuple(diagnostics),
        counts=counts,
    )


def _layout_legend(
    placement: Placement, options: LayoutOptions, content_w: float, y: float
) -> tuple[list[LegendItem], str | None, float]:
    if not options.show_legend:
        return [], None, y
    entries: list[tuple[str, str, LaneStyle]] = []
    for key, style in placement.lane_styles.items():
        label = truncate_to_width(clean_text(key), 220, options.meta_size + 1)
        entries.append((label, clean_text(key), style))
    if placement.has_unattributed:
        entries.append(
            (
                "unnamed history",
                "Lines no branch ref points to (e.g. merged or deleted branches)",
                LaneStyle(None, options.muted_palette[0], "4 4", 0),
            )
        )
    if not entries:
        return [], None, y
    items: list[LegendItem] = []
    x = options.padding
    row_y = y
    limit = options.padding + content_w
    shown = 0
    for label, full, style in entries[:24]:
        w = 30 + text_width(label, options.meta_size + 1) + 22
        if x > options.padding and x + w > limit:
            x = options.padding
            row_y += 22
        items.append(LegendItem(label, full, style.color, style.dash, x, row_y))
        x += w
        shown += 1
    overflow = f"+{len(entries) - shown} more branches" if len(entries) > shown else None
    if overflow:
        row_y += 22
    return items, overflow, row_y + 22


def _footer(
    snapshot: RepositorySnapshot,
    graph: CommitGraph,
    options: LayoutOptions,
    content_w: float,
    y_end: float,
    nodes: list[GraphNode],
) -> tuple[list[FooterNote], float, float]:
    texts: list[str] = []
    real_roots = [n for n in nodes if n.kind == "root"]
    boundary = [n for n in nodes if n.kind == "boundary"]
    if len(real_roots) == 1 and not boundary:
        texts.append(f"End of graph · initial commit {real_roots[0].short_sha}")
    elif len(real_roots) + len(boundary) > 1 or (boundary and real_roots):
        texts.append(
            f"End of graph · {len(real_roots)} root commit(s)"
            + (f" and {len(boundary)} shallow boundary commit(s)" if boundary else "")
            + ". Separate roots are unrelated histories; no shared initial commit is implied."
        )
    elif real_roots:
        texts.append(f"End of graph · initial commit {real_roots[0].short_sha}")
    if boundary:
        texts.append(
            ("" if texts else "End of graph \u00b7 ")
            + "History is truncated: this is a shallow clone, so boundary commits (dashed squares) "
            "are not the true initial commits."
        )
    if graph.truncated:
        texts.append(
            f"Showing the newest {len(graph.order)} commits only; older history is omitted."
        )
    if graph.missing_parents:
        texts.append("Dashed stubs mark parents that are missing from the collected history.")
    notes: list[FooterNote] = []
    rule_y = y_end + 4
    cursor = rule_y + 12 + options.meta_size
    for text in texts:
        for line in wrap_limited([text], content_w, options.meta_size, 3):
            notes.append(FooterNote(line, cursor))
            cursor += options.meta_height + 2
    return notes, rule_y, cursor - options.meta_size + options.padding
