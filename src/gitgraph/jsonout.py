"""JSON interchange/debug output of the computed layout. Deterministic; contains no timestamps
of generation and no e-mail addresses."""

from __future__ import annotations

import json
from typing import Any

from gitgraph._version import __version__
from gitgraph.layout import GraphLayout

SCHEMA_VERSION = 1


def layout_to_dict(layout: GraphLayout) -> dict[str, Any]:
    release = layout.release
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": {"name": "gitgraph", "version": __version__},
        "canvas": {"width": layout.width, "height": layout.height, "label_x": layout.label_x},
        "counts": dict(layout.counts),
        "latest_tag": None
        if release is None
        else {
            "name": release.name,
            "annotated": release.annotated,
            "commit": release.sha,
            "date": release.date,
        },
        "lanes": [
            {
                "name": lane.key,
                "color": lane.color,
                "dash": lane.dash,
                "commits_carried": lane.commit_count,
                "primary": lane.is_primary,
            }
            for lane in layout.lanes
        ],
        "nodes": [
            {
                "sha": n.sha,
                "row": n.row,
                "column": n.column,
                "x": n.x,
                "y": n.y,
                "kind": n.kind,
                "parent_count": n.parent_count,
                "lane": n.lane,
                "color": n.color,
                "subject": n.subject,
                "author": n.author,
                "authored_at": n.authored_at,
                "reachable_from": list(n.reachable_from),
                "refs": [b.text for b in n.badges if b.kind not in ("tag", "latest-tag", "more")],
                "tags": [b.target for b in n.badges if b.kind in ("tag", "latest-tag")],
            }
            for n in layout.nodes
        ],
        "edges": [
            {
                "child": e.child,
                "parent": e.parent,
                "kind": e.kind,
                "lane": e.lane,
                "color": e.color,
                "points": [list(p) for p in e.points],
            }
            for e in layout.edges
        ],
        "notes": [n.text for n in layout.notes],
        "diagnostics": [
            {"level": d.level, "code": d.code, "message": d.message} for d in layout.diagnostics
        ],
    }


def render_json(layout: GraphLayout) -> str:
    return json.dumps(layout_to_dict(layout), indent=2, ensure_ascii=False) + "\n"
