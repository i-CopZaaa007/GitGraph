from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from conftest import build_diamond
from gitgraph.api import generate
from gitgraph.collector import collect
from gitgraph.config import Config
from gitgraph.graph import build_graph
from gitgraph.layout import LayoutOptions, build_layout
from gitgraph.svg import RenderOptions, render_svg
from gitrepo import GitRepo
from synthetic import make_snapshot

SVG_NS = "{http://www.w3.org/2000/svg}"
PAYLOADS = [
    "<script>alert(1)</script>",
    '"><svg onload=alert(1)>',
    "]]></text><image href='http://evil.example/x.png'/>",
    "&amp; &lt;b&gt; &#x3C; <b>bold</b>",
    "‮evil‬ RTL override",
    "ctrl\x00\x01\x08chars\x1b[31m",
    "emoji 🎉 日本語 ก็ไทย café",
    "x" * 500,
]


def render(snapshot, **kwargs):  # type: ignore[no-untyped-def]
    graph = build_graph(snapshot)
    layout = build_layout(snapshot, graph, LayoutOptions())
    return layout, render_svg(layout, RenderOptions(**kwargs))


def test_svg_is_well_formed_and_self_contained(repo: GitRepo) -> None:
    build_diamond(repo)
    repo.tag("v1.0.0", annotated=True)
    result = generate(repo.root, Config())
    root = ET.fromstring(result.svg)
    assert root.tag == f"{SVG_NS}svg"
    assert root.get("viewBox") == f"0 0 {root.get('width')} {root.get('height')}"
    assert root.get("role") == "img"
    assert root.find(f"{SVG_NS}title") is not None and root.find(f"{SVG_NS}desc") is not None
    lowered = result.svg.lower()
    for forbidden in ("<script", "<image", "<foreignobject", "http://", "javascript:", " on"):
        if forbidden == "http://":
            # the only URL allowed is the XML namespace declaration
            assert lowered.count("http://") == 1
        elif forbidden == " on":
            assert not re.search(r"\son[a-z]+=", lowered)
        else:
            assert forbidden not in lowered


def test_untrusted_text_is_escaped_everywhere(repo: GitRepo) -> None:
    for i, payload in enumerate(PAYLOADS):
        safe = payload.replace("\x00", "")  # git refuses NUL in messages
        repo.commit(f"{safe} {i}")
    repo.git("branch", "feat<script>alert(1)</script>")
    repo.git("tag", "-a", "v1&<x>", "-m", '<b>msg</b> "quoted" & more')
    result = generate(repo.root, Config())
    root = ET.fromstring(result.svg)  # must still parse
    assert not list(root.iter(f"{SVG_NS}script"))
    assert not list(root.iter(f"{SVG_NS}image"))
    for element in root.iter():
        for name in element.attrib:
            assert not name.startswith("on")
    assert "<script" not in result.svg
    assert "‮" not in result.svg
    assert "\x1b" not in result.svg
    texts = " ".join("".join(e.itertext()) for e in root.iter(f"{SVG_NS}text"))
    assert "<script>" in texts  # shown as literal text, not interpreted


def test_json_output_parses_and_has_no_emails(repo: GitRepo) -> None:
    shas = build_diamond(repo)
    result = generate(repo.root, Config())
    data = json.loads(result.json)
    assert data["schema_version"] == 1
    assert {n["sha"] for n in data["nodes"]} == set(shas.values())
    assert "example.invalid" not in result.json


def test_links_only_when_repository_url_known(repo: GitRepo) -> None:
    build_diamond(repo)
    snap = collect(repo.root)
    graph = build_graph(snap)
    layout = build_layout(snap, graph)
    assert "<a " not in render_svg(layout)
    linked = render_svg(layout, RenderOptions(repository_url="https://github.com/o/r"))
    assert linked.count("<a ") > 0
    assert 'href="https://github.com/o/r/commit/' in linked
    ET.fromstring(linked)


def test_unsafe_repository_url_is_ignored(repo: GitRepo) -> None:
    build_diamond(repo)
    snap = collect(repo.root)
    layout = build_layout(snap, build_graph(snap))
    svg = render_svg(layout, RenderOptions(repository_url="javascript:alert(1)"))
    assert "<a " not in svg and "javascript" not in svg


def test_tag_link_encodes_components(repo: GitRepo) -> None:
    repo.commit("one")
    repo.git("tag", "rel/a#b%c")
    snap = collect(repo.root)
    layout = build_layout(snap, build_graph(snap))
    svg = render_svg(layout, RenderOptions(repository_url="https://example.com/o/r"))
    assert "rel/a%23b%25c" in svg
    ET.fromstring(svg)


def test_themes() -> None:
    snap = make_snapshot({0: ()}, {"main": 0})
    _, auto = render(snap, theme="auto")
    _, dark = render(snap, theme="dark")
    _, light = render(snap, theme="light")
    assert "prefers-color-scheme:dark" in auto
    assert "prefers-color-scheme" not in dark and "#0d1117" in dark
    assert "prefers-color-scheme" not in light and "#ffffff" in light


def test_empty_repository_renders_fallback(repo: GitRepo) -> None:
    result = generate(repo.root, Config())
    root = ET.fromstring(result.svg)
    assert "No commits to display" in "".join(root.itertext())


def test_merge_root_and_boundary_shapes_are_distinct() -> None:
    snap = make_snapshot({0: (), 1: (0,), 2: (0,), 3: (1, 2)}, {"main": 3})
    layout, svg = render(snap)
    assert svg.count('class="terminus"') == 1  # root terminus square
    kinds = {n.kind for n in layout.nodes}
    assert kinds == {"merge", "commit", "root"}


def test_output_is_stable_across_runs(repo: GitRepo) -> None:
    build_diamond(repo)
    first = generate(repo.root, Config())
    second = generate(repo.root, Config())
    assert first.svg == second.svg
    assert first.json == second.json
