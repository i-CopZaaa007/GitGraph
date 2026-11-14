from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from gitrepo import GitRepo


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[str], GitRepo]:
    def factory(name: str = "repo") -> GitRepo:
        return GitRepo(tmp_path / name)

    return factory


@pytest.fixture
def repo(make_repo: Callable[[str], GitRepo]) -> GitRepo:
    return make_repo("repo")


def build_diamond(repo: GitRepo) -> dict[str, str]:
    """main: a - b - M ; feature: b - f1 - f2 (merged into main)."""
    shas = {"a": repo.commit("a root")}
    shas["b"] = repo.commit("b")
    repo.branch("feature")
    shas["f1"] = repo.commit("f1")
    shas["f2"] = repo.commit("f2")
    repo.checkout("main")
    shas["m1"] = repo.commit("m1 on main")
    shas["M"] = repo.merge("feature", message="Merge feature")
    return shas
