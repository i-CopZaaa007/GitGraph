"""Helpers that build deterministic temporary Git repositories with the Git CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitRepo:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.clock = 1_700_000_000
        self.serial = 0
        root.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "main")

    def env(self) -> dict[str, str]:
        stamp = f"{self.clock} +0000"
        return {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test Author",
            "GIT_AUTHOR_EMAIL": "author@example.invalid",
            "GIT_COMMITTER_NAME": "Test Committer",
            "GIT_COMMITTER_EMAIL": "committer@example.invalid",
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        }

    def git(self, *args: str, tick: int = 60) -> str:
        self.clock += tick
        done = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            env=self.env(),
            check=True,
        )
        return done.stdout.strip()

    def commit(self, message: str, *, tick: int = 60) -> str:
        self.serial += 1
        name = f"f{self.serial:04d}.txt"
        (self.root / name).write_text(message + "\n", encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-q", "-m", message, tick=tick)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def branch(self, name: str) -> None:
        self.git("checkout", "-q", "-b", name)

    def checkout(self, name: str) -> None:
        self.git("checkout", "-q", name)

    def merge(self, *names: str, message: str | None = None, ff: bool = False) -> str:
        args = ["merge", "-q", "--ff" if ff else "--no-ff"]
        args += ["-m", message or f"Merge {', '.join(names)}", *names]
        self.git(*args)
        return self.head()

    def tag(self, name: str, *, annotated: bool = False, target: str = "HEAD") -> None:
        if annotated:
            self.git("tag", "-a", name, "-m", f"Release {name}", target)
        else:
            self.git("tag", name, target)

    def orphan(self, name: str) -> None:
        self.git("checkout", "-q", "--orphan", name)
        self.git("rm", "-rfq", ".", tick=0)
