"""Configuration: TOML file -> validated, typed settings."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from gitgraph.collector import DEFAULT_EXCLUDES, CollectionOptions
from gitgraph.layout import DEFAULT_FONT, LayoutOptions
from gitgraph.svg import RenderOptions
from gitgraph.theme import DEFAULT_PALETTE, THEME_NAMES

CONFIG_FILENAMES = ("gitgraph.toml", ".gitgraph.toml")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class ConfigError(ValueError):
    """Raised for unreadable or invalid configuration."""


@dataclass(frozen=True, slots=True)
class OutputConfig:
    svg: str = "docs/gitgraph.svg"
    json: str = ""


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    branches: bool = True
    remotes: bool = True
    tags: bool = True
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    max_commits: int = 0
    primary_branch: str = ""
    latest_tag: str = "auto"


@dataclass(frozen=True, slots=True)
class LayoutConfig:
    label_width: float = 520.0
    font_family: str = DEFAULT_FONT
    font_size: float = 13.0
    node_radius: float = 6.0
    line_width: float = 3.5
    lane_spacing: float = 22.0
    row_gap: float = 16.0
    min_row_height: float = 40.0
    padding: float = 24.0


@dataclass(frozen=True, slots=True)
class DisplayConfig:
    title: str = "Commit graph"
    show_title: bool = True
    legend: bool = True
    release_summary: bool = True
    tags: bool = True
    branch_labels: bool = True
    sha: bool = True
    author: bool = False
    date: bool = False
    message_mode: str = "subject"
    max_label_lines: int = 3


@dataclass(frozen=True, slots=True)
class ThemeConfig:
    name: str = "light"
    palette: tuple[str, ...] = DEFAULT_PALETTE
    responsive: bool = True


@dataclass(frozen=True, slots=True)
class LinksConfig:
    repository_url: str = ""
    commit_url: str = "{repo}/commit/{sha}"
    tag_url: str = "{repo}/tree/{tag}"


@dataclass(frozen=True, slots=True)
class ReadmeConfig:
    path: str = "README.md"
    heading: str = "Commit graph"
    heading_level: int = 2
    insert: str = "none"
    image: str = ""
    alt: str = "Git commit graph"
    cache_bust: bool = False


@dataclass(frozen=True, slots=True)
class SyncConfig:
    commit_message: str = "Update & Share Graph"
    hide_commits: bool = True


@dataclass(frozen=True, slots=True)
class PublishConfig:
    """Shared mode: the SVG lives on one branch that every other branch's README points to."""

    enabled: bool = False
    branch: str = "gitgraph-assets"
    remote: str = "origin"
    file: str = "gitgraph.svg"


@dataclass(frozen=True, slots=True)
class Config:
    output: OutputConfig = field(default_factory=OutputConfig)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)
    theme: ThemeConfig = field(default_factory=ThemeConfig)
    links: LinksConfig = field(default_factory=LinksConfig)
    readme: ReadmeConfig = field(default_factory=ReadmeConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    publish: PublishConfig = field(default_factory=PublishConfig)

    def collection_options(self) -> CollectionOptions:
        h = self.history
        hide = self.sync.hide_commits and bool(self.sync.commit_message)
        paths = tuple(
            p for p in (self.output.svg, self.output.json, self.readme.path, *CONFIG_FILENAMES) if p
        )
        artifact = self.publish.branch
        exclude = tuple(dict.fromkeys((*h.exclude, artifact, f"*/{artifact}")))
        return CollectionOptions(
            h.branches,
            h.remotes,
            h.tags,
            h.include,
            exclude,
            hide_subject=self.sync.commit_message if hide else None,
            hide_paths=tuple(Path(p).as_posix() for p in paths) if hide else (),
        )

    def layout_options(self) -> LayoutOptions:
        d, ly, h = self.display, self.layout, self.history
        return LayoutOptions(
            title=d.title,
            show_title=d.show_title,
            show_legend=d.legend,
            show_release_summary=d.release_summary,
            show_tags=d.tags,
            show_branch_labels=d.branch_labels,
            show_sha=d.sha,
            show_author=d.author,
            show_date=d.date,
            message_mode=d.message_mode,
            max_label_lines=d.max_label_lines,
            label_width=ly.label_width,
            font_family=ly.font_family,
            font_size=ly.font_size,
            node_radius=ly.node_radius,
            line_width=ly.line_width,
            lane_spacing=ly.lane_spacing,
            row_gap=ly.row_gap,
            min_row_height=ly.min_row_height,
            padding=ly.padding,
            palette=self.theme.palette,
            latest_tag_strategy=h.latest_tag,
            primary_branch=h.primary_branch or None,
        )

    def render_options(self, repository_url: str | None) -> RenderOptions:
        return RenderOptions(
            theme=self.theme.name,
            responsive=self.theme.responsive,
            repository_url=repository_url,
            commit_url=self.links.commit_url,
            tag_url=self.links.tag_url,
        )


_ENUMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("display", "message_mode"): ("subject", "full"),
    ("theme", "name"): THEME_NAMES,
    ("readme", "insert"): ("none", "append", "prepend", "after-first-heading"),
    ("history", "latest_tag"): ("auto", "version", "date"),
}
_POSITIVE = {
    ("layout", "label_width"): 120.0,
    ("layout", "font_size"): 6.0,
    ("layout", "node_radius"): 2.0,
    ("layout", "line_width"): 0.5,
    ("layout", "lane_spacing"): 10.0,
    ("layout", "min_row_height"): 16.0,
    ("display", "max_label_lines"): 1,
    ("readme", "heading_level"): 1,
}
_MAXIMUM = {("readme", "heading_level"): 6, ("display", "max_label_lines"): 50}


def _coerce(section: str, name: str, default: Any, value: Any) -> Any:
    where = f"[{section}] {name}"
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ConfigError(f"{where} must be true or false")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{where} must be an integer")
        return value
    if isinstance(default, float):
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"{where} must be a number")
        return float(value)
    if isinstance(default, str):
        if not isinstance(value, str):
            raise ConfigError(f"{where} must be a string")
        return value
    if isinstance(default, tuple):
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"{where} must be a list of strings")
        return tuple(value)
    raise AssertionError(where)  # pragma: no cover


def _load_section(cls: type[Any], section: str, data: Any) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ConfigError(f"[{section}] must be a table")
    known = {f.name: f for f in fields(cls)}
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise ConfigError(
            f"unknown key(s) in [{section}]: {', '.join(unknown)}. "
            f"Valid keys: {', '.join(sorted(known))}"
        )
    kwargs: dict[str, Any] = {}
    for name, value in data.items():
        value = _coerce(section, name, known[name].default, value)
        enum = _ENUMS.get((section, name))
        if enum is not None and value not in enum:
            raise ConfigError(f"[{section}] {name} must be one of: {', '.join(enum)}")
        low = _POSITIVE.get((section, name))
        if low is not None and value < low:
            raise ConfigError(f"[{section}] {name} must be at least {low}")
        high = _MAXIMUM.get((section, name))
        if high is not None and value > high:
            raise ConfigError(f"[{section}] {name} must be at most {high}")
        kwargs[name] = value
    result = cls(**kwargs)
    if section == "theme":
        if not result.palette:
            raise ConfigError("[theme] palette must not be empty")
        bad = [c for c in result.palette if not _HEX.match(c)]
        if bad:
            raise ConfigError(f"[theme] palette entries must look like #rrggbb: {', '.join(bad)}")
    if section == "history" and result.max_commits < 0:
        raise ConfigError("[history] max_commits must be 0 (unlimited) or positive")
    if section == "links":
        for key in ("commit_url", "tag_url"):
            if "{repo}" not in getattr(result, key):
                raise ConfigError(f"[links] {key} must contain the {{repo}} placeholder")
    return result


def config_from_dict(data: dict[str, Any]) -> Config:
    sections: dict[str, type[Any]] = {
        "output": OutputConfig,
        "history": HistoryConfig,
        "layout": LayoutConfig,
        "display": DisplayConfig,
        "theme": ThemeConfig,
        "links": LinksConfig,
        "readme": ReadmeConfig,
        "sync": SyncConfig,
        "publish": PublishConfig,
    }
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ConfigError(
            f"unknown section(s): {', '.join(unknown)}. Valid sections: {', '.join(sections)}"
        )
    return Config(
        **{name: _load_section(cls, name, data.get(name)) for name, cls in sections.items()}
    )


def load_config(path: Path | None, repo: Path) -> tuple[Config, Path | None]:
    """Load ``path`` or auto-discover ``gitgraph.toml`` in ``repo``; defaults if none exists."""
    if path is None:
        for name in CONFIG_FILENAMES:
            candidate = repo / name
            if candidate.is_file():
                path = candidate
                break
    if path is None:
        return Config(), None
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot parse {path}: {exc}") from exc
    return config_from_dict(data), path


def config_from_text(text: str) -> Config:
    """Parse TOML ``text`` (used for configuration that is not on disk yet)."""
    try:
        return config_from_dict(tomllib.loads(text))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"cannot parse configuration: {exc}") from exc


def with_overrides(config: Config, **sections: Any) -> Config:
    """Return ``config`` with whole sections replaced."""
    return replace(config, **sections)


STARTER_CONFIG = """\
# GitGraph configuration. Every key is optional; the values shown are the defaults.
# Reference: docs/configuration.md

[output]
svg = "docs/gitgraph.svg"      # where the SVG is written (relative to the repository)
# json = "docs/gitgraph.json"  # optional extra JSON layout output

[history]
branches = true                # local branches
remotes = true                 # remote-tracking branches
tags = true
# include = ["main", "release/*"]   # fnmatch patterns on ref names; empty = everything
exclude = ["gitgraph-assets", "*/gitgraph-assets"]  # never graph the artifact branch
max_commits = 0                # 0 = every reachable commit
# primary_branch = "main"      # default: origin/HEAD, then main, master, current branch
latest_tag = "auto"            # auto | version | date

[display]
title = "Commit graph"
show_title = true
legend = true
release_summary = true         # latest tag line above the graph
tags = true
branch_labels = true
sha = true
author = false
date = false
message_mode = "subject"       # subject | full
max_label_lines = 3

[layout]
label_width = 520
font_size = 13
node_radius = 6
line_width = 3.5
lane_spacing = 22

[theme]
name = "light"                 # light | dark | auto (follows the viewer's colour scheme)
responsive = true
# palette = ["#3b82f6", "#ea580c", "#059669"]

[links]
# repository_url = "https://github.com/OWNER/REPO"   # enables commit/tag links in the SVG

[readme]
path = "README.md"
heading = "Commit graph"
heading_level = 2
insert = "none"                # none | append | prepend | after-first-heading
# image = "https://raw.githubusercontent.com/OWNER/REPO/gitgraph-assets/gitgraph.svg"
alt = "Git commit graph"
cache_bust = false

[publish]
# Shared mode (`gitgraph init --shared`): one SVG on a separate branch, referenced by every
# branch's README, so the graph is identical and current everywhere.
# enabled = false
# branch = "gitgraph-assets"
# remote = "origin"
# file = "gitgraph.svg"
"""


def shared_config_text(image_url: str) -> str:
    """Starter config with shared (publish) mode switched on."""
    text = STARTER_CONFIG.replace("# enabled = false", "enabled = true", 1)
    old = '# image = "https://raw.githubusercontent.com/OWNER/REPO/gitgraph-assets/gitgraph.svg"'
    assert old in text
    return text.replace(old, f'image = "{image_url}"', 1)
