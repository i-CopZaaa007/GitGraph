from __future__ import annotations

import os
import subprocess
import time
import tracemalloc
from pathlib import Path

import pytest

from gitgraph.api import generate
from gitgraph.config import Config
from invariants import check_layout

COMMITS = int(os.environ.get("GITGRAPH_PERF_COMMITS", "6000"))


def fast_import(root: Path, count: int) -> None:
    """Create a repo with ``count`` commits: a main line plus periodic merged side branches."""
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    lines: list[str] = []
    mark = 0
    main_mark = 0
    clock = 1_700_000_000

    def commit(ref: str, parent_marks: list[int]) -> int:
        nonlocal mark, clock
        mark += 1
        clock += 30
        msg = f"change number {mark}"
        lines.append(f"commit refs/heads/{ref}\nmark :{mark}")
        lines.append(f"committer T <t@example.invalid> {clock} +0000")
        lines.append(f"data {len(msg)}\n{msg}")
        if parent_marks:
            lines.append(f"from :{parent_marks[0]}")
            lines.extend(f"merge :{p}" for p in parent_marks[1:])
        lines.append("")
        return mark

    main_mark = commit("main", [])
    while mark < count:
        if mark % 40 == 0:
            side = main_mark
            for _ in range(3):
                side = commit("side", [side])
            main_mark = commit("main", [main_mark, side])
        else:
            main_mark = commit("main", [main_mark])
    data = "\n".join(lines) + "\n"
    subprocess.run(
        ["git", "-C", str(root), "fast-import", "--quiet"], input=data.encode(), check=True
    )
    subprocess.run(
        ["git", "-C", str(root), "branch", "-D", "side"], check=True, capture_output=True
    )


def test_large_history_is_handled_in_reasonable_time_and_memory(tmp_path: Path) -> None:
    fast_import(tmp_path / "big", COMMITS)
    tracemalloc.start()
    started = time.perf_counter()
    result = generate(tmp_path / "big", Config())
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(result.layout.nodes) >= COMMITS
    assert elapsed < 60, f"took {elapsed:.1f}s"
    assert peak < 1_500_000_000
    print(f"\n{len(result.layout.nodes)} commits: {elapsed:.2f}s, peak {peak / 1e6:.0f} MB")
    if COMMITS <= 6000:
        graph = result.graph
        check_layout_light(result.layout, graph)


def check_layout_light(layout, graph) -> None:  # type: ignore[no-untyped-def]
    assert len({(n.x, n.y) for n in layout.nodes}) == len(layout.nodes)
    assert [n.sha for n in layout.nodes] == list(graph.order)
    ys = [n.y for n in layout.nodes]
    assert ys == sorted(ys)


@pytest.mark.skipif(not os.environ.get("GITGRAPH_PERF_FULL"), reason="set GITGRAPH_PERF_FULL=1")
def test_full_invariants_on_medium_history(tmp_path: Path) -> None:
    fast_import(tmp_path / "mid", 600)
    result = generate(tmp_path / "mid", Config())
    check_layout(result.layout, result.graph)
