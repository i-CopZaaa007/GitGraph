from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from conftest import build_diamond
from gitgraph._version import __version__
from gitgraph.cli import main
from gitgraph.readme import END_MARKER, START_MARKER
from gitrepo import GitRepo


def run(*args: str) -> int:
    return main(list(args))


def test_version_and_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert run("version") == 0
    assert __version__ in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        run("--version")
    assert exc.value.code == 0
    with pytest.raises(SystemExit):
        run("--help")
    out = capsys.readouterr().out
    assert "generate" in out and "examples:" in out
    assert run() == 2


def test_generate_writes_svg_and_json(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    build_diamond(repo)
    assert (
        run("generate", "--repo", str(repo.root), "--json", str(repo.root / "out" / "g.json")) == 0
    )
    svg = repo.root / "docs" / "gitgraph.svg"
    ET.fromstring(svg.read_text(encoding="utf-8"))
    data = json.loads((repo.root / "out" / "g.json").read_text(encoding="utf-8"))
    assert data["counts"]["commits"] == 6
    assert "6 commits" in capsys.readouterr().err


def test_generate_does_not_modify_repository(repo: GitRepo) -> None:
    build_diamond(repo)
    before = (repo.git("rev-parse", "--all"), repo.git("for-each-ref"), repo.git("reflog"))
    assert run("generate", "--repo", str(repo.root), "-q") == 0
    after = (repo.git("rev-parse", "--all"), repo.git("for-each-ref"), repo.git("reflog"))
    assert before == after
    assert repo.git("branch", "--show-current") == "main"


def test_generate_to_stdout(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit("one")
    assert run("generate", "--repo", str(repo.root), "-o", "-", "-q") == 0
    ET.fromstring(capsys.readouterr().out)


def test_generate_errors_are_actionable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run("generate", "--repo", str(tmp_path)) == 1
    assert "error:" in capsys.readouterr().err
    assert run("generate", "--repo", str(tmp_path / "missing")) == 1


def test_generate_rejects_bad_config(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit("one")
    (repo.root / "gitgraph.toml").write_text("[layout]\nfont_size = 'x'\n", encoding="utf-8")
    assert run("generate", "--repo", str(repo.root)) == 1
    assert "font_size" in capsys.readouterr().err


def test_output_directory_target_is_rejected(repo: GitRepo) -> None:
    repo.commit("one")
    (repo.root / "outdir").mkdir()
    assert run("generate", "--repo", str(repo.root), "-o", str(repo.root / "outdir")) == 1


def test_init_then_generate_updates_readme_idempotently(repo: GitRepo) -> None:
    build_diamond(repo)
    readme = repo.root / "README.md"
    readme.write_text("# Project\n\nIntro text.\n\n## License\n\nTBD\n", encoding="utf-8")
    assert (
        run("init", "--repo", str(repo.root), "--add-markers", "--insert", "after-first-heading")
        == 0
    )
    text = readme.read_text(encoding="utf-8")
    assert START_MARKER in text and END_MARKER in text
    assert (repo.root / "gitgraph.toml").exists()

    assert run("generate", "--repo", str(repo.root), "--update-readme", "-q") == 0
    first = readme.read_text(encoding="utf-8")
    assert run("generate", "--repo", str(repo.root), "--update-readme", "-q") == 0
    assert readme.read_text(encoding="utf-8") == first
    for line in ("# Project", "Intro text.", "## License", "TBD"):
        assert line in first.splitlines()
    assert "![Git commit graph](docs/gitgraph.svg)" in first


def test_init_never_overwrites_without_force(
    repo: GitRepo, capsys: pytest.CaptureFixture[str]
) -> None:
    repo.commit("one")
    config = repo.root / "gitgraph.toml"
    config.write_text("# mine\n", encoding="utf-8")
    assert run("init", "--repo", str(repo.root)) == 0
    assert config.read_text(encoding="utf-8") == "# mine\n"
    assert run("init", "--repo", str(repo.root), "--force") == 0
    assert config.read_text(encoding="utf-8") != "# mine\n"


def test_init_creates_readme_and_workflow(repo: GitRepo) -> None:
    repo.commit("one")
    assert run("init", "--repo", str(repo.root), "--add-markers", "--workflow") == 0
    assert START_MARKER in (repo.root / "README.md").read_text(encoding="utf-8")
    assert "fetch-depth: 0" in (repo.root / ".github/workflows/gitgraph.yml").read_text(
        encoding="utf-8"
    )
    # second run keeps existing markers untouched
    before = (repo.root / "README.md").read_text(encoding="utf-8")
    assert run("init", "--repo", str(repo.root), "--add-markers") == 0
    assert (repo.root / "README.md").read_text(encoding="utf-8") == before


def test_update_readme_without_markers_fails_and_keeps_file(repo: GitRepo) -> None:
    repo.commit("one")
    readme = repo.root / "README.md"
    readme.write_text("# Hello\n", encoding="utf-8")
    assert run("generate", "--repo", str(repo.root), "--update-readme", "-q") == 1
    assert readme.read_text(encoding="utf-8") == "# Hello\n"


def test_malformed_markers_fail_without_changes(repo: GitRepo) -> None:
    repo.commit("one")
    readme = repo.root / "README.md"
    content = f"{START_MARKER}\n{START_MARKER}\n{END_MARKER}\n"
    readme.write_text(content, encoding="utf-8")
    assert run("generate", "--repo", str(repo.root), "--update-readme", "-q") == 1
    assert readme.read_text(encoding="utf-8") == content
    assert run("validate", "--repo", str(repo.root)) == 1


def test_validate_reports_state(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit("one")
    assert run("validate", "--repo", str(repo.root)) == 0  # warnings only
    out = capsys.readouterr().out
    assert "1 commits" in out and "warning" in out
    assert run("validate", "--repo", str(repo.root), "--strict") == 1
    run("init", "--repo", str(repo.root), "--add-markers")
    capsys.readouterr()
    assert run("validate", "--repo", str(repo.root), "--strict") == 0


def test_cache_bust_and_custom_image(repo: GitRepo) -> None:
    repo.commit("one")
    (repo.root / "gitgraph.toml").write_text(
        '[readme]\ncache_bust = true\nimage = "https://example.com/g.svg"\ninsert = "append"\n',
        encoding="utf-8",
    )
    (repo.root / "README.md").write_text("# T\n", encoding="utf-8")
    assert run("generate", "--repo", str(repo.root), "--update-readme", "-q") == 0
    text = (repo.root / "README.md").read_text(encoding="utf-8")
    assert "![Git commit graph](https://example.com/g.svg?v=" in text


def test_module_entry_point(repo: GitRepo) -> None:
    repo.commit("one")
    done = subprocess.run(
        [sys.executable, "-m", "gitgraph", "generate", "--repo", str(repo.root), "-o", "-", "-q"],
        capture_output=True,
        text=True,
        check=True,
    )
    ET.fromstring(done.stdout)


def test_cli_paths_are_cwd_relative_and_config_paths_repo_relative(
    repo: GitRepo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.commit("one")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert run("generate", "--repo", str(repo.root), "-o", "cli.svg", "-q") == 0
    assert (elsewhere / "cli.svg").exists()
    assert run("generate", "--repo", str(repo.root), "-q") == 0
    assert (repo.root / "docs" / "gitgraph.svg").exists()


def test_exclude_option_hides_refs(repo: GitRepo, capsys: pytest.CaptureFixture[str]) -> None:
    repo.commit("one")
    repo.branch("secret-topic")
    repo.commit("hidden work")
    repo.checkout("main")
    out = repo.root / "g.json"
    assert (
        run("generate", "--repo", str(repo.root), "--exclude", "secret-*", "--json", str(out), "-q")
        == 0
    )
    assert "hidden work" not in out.read_text(encoding="utf-8")
