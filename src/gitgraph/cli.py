"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

from gitgraph._version import __version__
from gitgraph.api import GenerationResult, apply_readme, generate
from gitgraph.collector import GitError, collect, remote_url
from gitgraph.config import (
    CONFIG_FILENAMES,
    STARTER_CONFIG,
    Config,
    ConfigError,
    config_from_text,
    load_config,
    shared_config_text,
)
from gitgraph.graph import GraphError
from gitgraph.publish import PublishError, decide_mode, publish
from gitgraph.readme import (
    ReadmeError,
    atomic_write,
    build_block,
    find_markers,
    image_reference,
    read_text,
    update_readme,
)
from gitgraph.sync import SetupPlan, SyncError
from gitgraph.sync import sync as sync_repo
from gitgraph.templates import WORKFLOW_TEMPLATE

EPILOG = """\
examples:
  gitgraph generate                       write docs/gitgraph.svg for the repo in the current directory
  gitgraph generate --repo ../project -o graph.svg --json graph.json
  gitgraph generate --update-readme       also refresh the marked README section
  gitgraph init                           one-step setup: config, README markers, first graph
  gitgraph sync                           set up if needed, refresh, commit and share the graph
  gitgraph validate --strict              check repository, config and README; warnings fail
"""


class CliError(RuntimeError):
    """A user-facing failure; message is printed without a traceback."""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitgraph",
        description="Generate an accurate vertical Git history graph as SVG.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"gitgraph {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo", type=Path, default=Path("."), help="repository path (default: .)")
        p.add_argument(
            "--config", type=Path, help="config file (default: ./gitgraph.toml if present)"
        )

    gen = sub.add_parser(
        "generate",
        help="collect history and write the graph",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    common(gen)
    gen.add_argument("-o", "--output", help="SVG output path, or '-' for stdout")
    gen.add_argument("--json", dest="json_output", help="also write the JSON layout to this path")
    gen.add_argument("--theme", choices=["auto", "light", "dark"], help="override theme")
    gen.add_argument("--repository-url", help="https URL enabling commit/tag links")
    gen.add_argument("--max-commits", type=int, help="show only the newest N commits")
    gen.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="additionally exclude refs matching this fnmatch pattern (repeatable)",
    )
    gen.add_argument("--update-readme", action="store_true", help="refresh the README section")
    gen.add_argument("-q", "--quiet", action="store_true", help="suppress the summary")

    init = sub.add_parser(
        "init",
        help="local setup: config, README markers, first graph (see `sync` for the one-step flow)",
        description="One-step setup. Writes gitgraph.toml, adds README markers (creating the "
        "README if needed), generates the SVG and fills the README section.",
    )
    init.add_argument("--repo", type=Path, default=Path("."), help="repository path (default: .)")
    init.add_argument(
        "--insert",
        choices=["append", "prepend", "after-first-heading"],
        default="append",
        help="where to add markers (default: append)",
    )
    init.add_argument("--image", help="image URL/path to reference instead of the SVG output path")
    init.add_argument("--no-readme", action="store_true", help="do not touch the README")
    init.add_argument("--no-generate", action="store_true", help="skip generating the first graph")
    init.add_argument(
        "--workflow", action="store_true", help="write .github/workflows/gitgraph.yml"
    )
    init.add_argument("--force", action="store_true", help="overwrite existing config/workflow")
    init.add_argument("--add-markers", action="store_true", help=argparse.SUPPRESS)  # legacy no-op

    syn = sub.add_parser(
        "sync",
        help="one step: set up if needed, refresh the graph, commit and share it",
        description="Sets GitGraph up on first run (config + README markers), regenerates the "
        "graph, commits only the generated files as 'Update & Share Graph' (never drawn in the "
        "graph) and, in shared mode, publishes the SVG for every branch. Refuses if the "
        "generated files already have uncommitted changes.",
    )
    common(syn)
    syn.add_argument(
        "--mode",
        choices=["auto", "shared", "local"],
        default="auto",
        help="first-time setup only: shared = one graph on a separate branch that every branch's "
        "README shows (public github.com repos), local = SVG committed per branch; auto picks "
        "shared for public repositories (default)",
    )
    syn.add_argument("--image", help="first-time setup only: image URL for shared mode")
    syn.add_argument("--push", action="store_true", help="push the current branch afterwards")
    syn.add_argument(
        "--allow-dirty",
        action="store_true",
        help="proceed even if generated files have uncommitted edits",
    )

    pub = sub.add_parser(
        "publish",
        help="shared mode: push the graph SVG to the artifact branch (no commits on your branches)",
    )
    common(pub)
    pub.add_argument("--dry-run", action="store_true", help="build the commit but do not push")
    pub.add_argument("--only-remote", metavar="NAME", help="do nothing unless this is the remote")
    pub.add_argument("-q", "--quiet", action="store_true")

    val = sub.add_parser("validate", help="check repository, configuration and README")
    common(val)
    val.add_argument("--strict", action="store_true", help="treat warnings as failures")

    sub.add_parser("version", help="print the version")
    return parser


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


STDOUT = Path("-")


def _write_output(path: Path, data: str) -> None:
    """Write ``data`` to ``path`` atomically; ``-`` means stdout."""
    if path == STDOUT:
        sys.stdout.write(data)
        return
    if path.is_dir():
        raise CliError(f"output path is a directory: {path}")
    atomic_write(path, data)


def _resolve_output(cli_value: str | None, config_value: str, repo: Path) -> Path | None:
    """Command-line paths are relative to the current directory, config paths to the repository.
    ``-`` selects stdout; ``None`` means the output is not requested."""
    if cli_value is not None:
        return Path(cli_value)
    return repo / config_value if config_value else None


def _readme_path(repo: Path, config: Config) -> Path:
    return repo / config.readme.path


def _cmd_generate(args: argparse.Namespace) -> int:
    repo: Path = args.repo
    config, _ = load_config(args.config, repo)
    if args.theme:
        config = replace(config, theme=replace(config.theme, name=args.theme))
    if args.repository_url:
        config = replace(config, links=replace(config.links, repository_url=args.repository_url))
    if args.max_commits is not None:
        if args.max_commits < 0:
            raise CliError("--max-commits must be 0 or greater")
        config = replace(config, history=replace(config.history, max_commits=args.max_commits))
    if args.exclude:
        history = replace(config.history, exclude=(*config.history.exclude, *args.exclude))
        config = replace(config, history=history)
    result: GenerationResult = generate(repo, config)

    svg_path = _resolve_output(args.output, config.output.svg, repo)
    assert svg_path is not None  # the default output.svg is never empty
    _write_output(svg_path, result.svg)
    json_path = _resolve_output(args.json_output, config.output.json, repo)
    if json_path is not None:
        _write_output(json_path, result.json)
    for diag in result.layout.diagnostics:
        if diag.level == "warning":
            _warn(diag.message)

    if args.update_readme:
        if svg_path == STDOUT:
            raise CliError("--update-readme needs a file output, not stdout")
        readme = _readme_path(repo, config)
        changed = apply_readme(repo, config, result, svg_path)
        if not args.quiet:
            print(
                f"README {'updated' if changed else 'already up to date'}: {readme}",
                file=sys.stderr,
            )
    if not args.quiet:
        c = result.layout.counts
        where = "stdout" if svg_path == STDOUT else svg_path
        print(
            f"Wrote {where}: {c['commits']} commits, {c['merges']} merges, "
            f"{c['branches']} branch lines, {c['tags']} tags",
            file=sys.stderr,
        )
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    repo: Path = args.repo
    collect(repo)  # verifies this is a Git repository; read-only
    config_path = repo / "gitgraph.toml"
    if config_path.exists() and not args.force:
        print(f"kept existing {config_path} (use --force to overwrite)", file=sys.stderr)
    else:
        atomic_write(config_path, STARTER_CONFIG)
        print(f"wrote {config_path}", file=sys.stderr)
    config, _ = load_config(config_path, repo)
    readme = _readme_path(repo, config)
    svg_path = repo / config.output.svg
    if not args.no_readme:
        image_ref = image_reference(svg_path, readme, args.image or config.readme.image, None)
        block = build_block(
            image_ref, config.readme.heading, config.readme.heading_level, config.readme.alt
        )
        if readme.exists():
            if find_markers(read_text(readme)) is not None:
                print(
                    f"{readme} already contains GitGraph markers; left unchanged", file=sys.stderr
                )
            else:
                update_readme(readme, block, args.insert)
                print(f"added markers to {readme}", file=sys.stderr)
        else:
            update_readme(readme, block, args.insert, create=True)
            print(f"created {readme} with GitGraph markers", file=sys.stderr)
    if not args.no_generate:
        result = generate(repo, config)
        atomic_write(svg_path, result.svg)
        print(f"wrote {svg_path}", file=sys.stderr)
        if not args.no_readme:
            apply_readme(repo, config, result, svg_path)
            print(f"updated {readme}", file=sys.stderr)
    if args.workflow:
        workflow = repo / ".github" / "workflows" / "gitgraph.yml"
        if workflow.exists() and not args.force:
            print(f"kept existing {workflow} (use --force to overwrite)", file=sys.stderr)
        else:
            atomic_write(workflow, WORKFLOW_TEMPLATE)
            print(f"wrote {workflow}; edit the `uses:` line before committing", file=sys.stderr)
    print(
        "done. Commit the new files (git add -A && git commit), or just run `gitgraph sync`.",
        file=sys.stderr,
    )
    return 0


def _publish_and_report(repo: Path, config: Config, *, dry_run: bool, quiet: bool) -> None:
    try:
        result = publish(repo, config, dry_run=dry_run)
    except (PublishError, SyncError) as exc:
        raise CliError(str(exc)) from exc
    if quiet:
        return
    target = f"{config.publish.remote}/{config.publish.branch}"
    if result.commit is None:
        print(f"graph already up to date on {target}", file=sys.stderr)
    elif result.pushed:
        print(f"published graph to {target} ({result.commit[:7]})", file=sys.stderr)
    else:
        print(f"dry run: would publish {result.commit[:7]} to {target}", file=sys.stderr)


def _cmd_publish(args: argparse.Namespace) -> int:
    config, _ = load_config(args.config, args.repo)
    if args.only_remote and args.only_remote != config.publish.remote:
        return 0
    _publish_and_report(args.repo, config, dry_run=args.dry_run, quiet=args.quiet)
    return 0


def _discover_config(repo: Path, explicit: Path | None) -> bool:
    if explicit is not None:
        return True
    return any((repo / name).is_file() for name in CONFIG_FILENAMES)


def _cmd_sync(args: argparse.Namespace) -> int:
    repo: Path = args.repo
    setup: SetupPlan | None = None
    if _discover_config(repo, args.config):
        config, _ = load_config(args.config, repo)
        if args.mode != "auto" or args.image:
            print("note: gitgraph.toml exists, so --mode/--image are ignored", file=sys.stderr)
    else:
        collect(repo)  # verifies this is a Git repository before anything is written
        try:
            mode, image, note = decide_mode(remote_url(repo), args.mode, args.image)
        except PublishError as exc:
            raise CliError(str(exc)) from exc
        if note:
            print(f"note: {note}", file=sys.stderr)
        text = shared_config_text(image) if mode == "shared" and image else STARTER_CONFIG
        config = config_from_text(text)
        setup = SetupPlan(repo / "gitgraph.toml", text)
        print(f"first run: setting up {mode} mode", file=sys.stderr)
    try:
        result = sync_repo(repo, config, push=args.push, allow_dirty=args.allow_dirty, setup=setup)
    except SyncError as exc:
        raise CliError(str(exc)) from exc
    if result.commit is not None:
        print(
            f"committed {', '.join(result.changed)} as {result.commit[:7]}"
            + (" and pushed" if result.pushed else ""),
            file=sys.stderr,
        )
    if result.published:
        print(
            f"shared the graph on {config.publish.remote}/{config.publish.branch}", file=sys.stderr
        )
    if result.commit is None and not result.published:
        print("graph already up to date; nothing to do", file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    repo: Path = args.repo
    errors: list[str] = []
    warnings: list[str] = []
    try:
        config, source = load_config(args.config, repo)
        print(f"ok: configuration {'loaded from ' + str(source) if source else '(defaults)'}")
    except ConfigError as exc:
        print(f"error: {exc}")
        return 1
    try:
        snapshot = collect(repo, config.collection_options())
    except GitError as exc:
        print(f"error: {exc}")
        return 1
    print(
        f"ok: {len(snapshot.commits)} commits, {len(snapshot.refs)} branch refs, "
        f"{len(snapshot.tags)} tags collected"
    )
    warnings.extend(d.message for d in snapshot.diagnostics if d.level == "warning")
    if not snapshot.commits:
        warnings.append("no commits collected; the generated graph will be empty")
    readme = _readme_path(repo, config)
    if readme.exists():
        try:
            state = "present" if find_markers(read_text(readme)) else "missing"
            if state == "missing" and config.readme.insert == "none":
                warnings.append(
                    f"{readme} has no GitGraph markers; run `gitgraph init --add-markers`"
                )
            else:
                print(f"ok: README markers {state}")
        except ReadmeError as exc:
            errors.append(str(exc))
    else:
        warnings.append(f"{readme} not found")
    for message in warnings:
        print(f"warning: {message}")
    for message in errors:
        print(f"error: {message}")
    if errors or (args.strict and warnings):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2
    try:
        if args.command == "version":
            print(f"gitgraph {__version__}")
            return 0
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "sync":
            return _cmd_sync(args)
        if args.command == "publish":
            return _cmd_publish(args)
        return _cmd_validate(args)
    except (CliError, ConfigError, GitError, GraphError, ReadmeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:  # pragma: no cover
        return 1


if __name__ == "__main__":
    sys.exit(main())
