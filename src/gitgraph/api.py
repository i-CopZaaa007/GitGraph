"""High-level orchestration shared by the CLI and integrations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from gitgraph.collector import collect, remote_url
from gitgraph.config import Config
from gitgraph.graph import CommitGraph, build_graph
from gitgraph.jsonout import render_json
from gitgraph.layout import GraphLayout, build_layout
from gitgraph.models import RepositorySnapshot
from gitgraph.readme import build_block, image_reference, update_readme
from gitgraph.svg import render_svg
from gitgraph.urls import is_safe_http_url, normalize_repository_url


@dataclass(frozen=True, slots=True)
class GenerationResult:
    snapshot: RepositorySnapshot
    graph: CommitGraph
    layout: GraphLayout
    svg: str
    json: str


def resolve_repository_url(repo: Path, config: Config) -> str | None:
    """Explicit ``links.repository_url``, or derived from ``origin`` when set to ``auto``."""
    value = config.links.repository_url.strip()
    if not value:
        return None
    if value == "auto":
        raw = remote_url(repo)
        return normalize_repository_url(raw) if raw else None
    return value if is_safe_http_url(value) else None


def generate(repo: Path, config: Config) -> GenerationResult:
    snapshot = collect(repo, config.collection_options())
    graph = build_graph(snapshot, max_commits=config.history.max_commits or None)
    layout = build_layout(snapshot, graph, config.layout_options())
    svg = render_svg(layout, config.render_options(resolve_repository_url(repo, config)))
    return GenerationResult(snapshot, graph, layout, svg, render_json(layout))


def apply_readme(repo: Path, config: Config, result: GenerationResult, svg_path: Path) -> bool:
    """Refresh the marked README region. Returns ``True`` if the README changed."""
    readme = repo / config.readme.path
    version = (
        hashlib.sha256(result.svg.encode()).hexdigest()[:8] if config.readme.cache_bust else None
    )
    image = image_reference(svg_path, readme, config.readme.image, version)
    block = build_block(
        image, config.readme.heading, config.readme.heading_level, config.readme.alt
    )
    return update_readme(readme, block, config.readme.insert)
