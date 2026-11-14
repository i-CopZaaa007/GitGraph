"""Small wrapper for Git calls that may write (used by ``sync`` and ``publish``).

The read-only collector has its own runner; this one is only used by commands that the user
explicitly asked to change the repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


class GitCommandError(RuntimeError):
    """A Git command failed."""


def run_git(
    repo: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra_env or {})
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
        check=False,
    )
    if check and done.returncode != 0:
        raise GitCommandError(f"git {args[0]} failed: {(done.stderr or done.stdout).strip()}")
    return done
