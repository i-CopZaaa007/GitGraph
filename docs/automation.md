# Setup and automation

## One command: `gitgraph sync`

```bash
pip install "git+https://github.com/i-CopZaaa007/test-GitGraph.git"   # until it is on PyPI
cd your-repository
gitgraph sync
```

The first run sets everything up; later runs just refresh. Each run:

1. **First time only:** writes `gitgraph.toml`, adds the README markers (creates `README.md` if
   missing; nothing outside the markers is touched) and picks a mode (below).
2. Regenerates the graph.
3. Commits only the generated files with the message **`Update & Share Graph`**.
4. In shared mode, publishes the SVG so every branch shows the same current graph.

Options: `--push` (push the current branch afterwards), `--mode auto|shared|local` and `--image URL`
(first run only), `--allow-dirty`. `gitgraph init` is still available for a local setup that
commits nothing.

### Two modes

| | `shared` | `local` |
|---|---|---|
| Where the SVG lives | separate branch `gitgraph-assets` | `docs/gitgraph.svg` on each branch |
| Commit on your branch | only the first time (README + config) | every time the graph changes |
| Graph current on all branches | **yes**, one image for all | no, only the branch you synced |
| Private repositories | image does not load (see below) | works |

`--mode auto` (default) chooses **shared** only for a **public github.com** repository, found by
trying to read it without credentials; otherwise it uses **local** and tells you why. The choice
is stored in `gitgraph.toml` (`[publish] enabled`), so later runs need no flags. Edit that file to
switch.

Shared mode publishes `https://raw.githubusercontent.com/<owner>/<repo>/gitgraph-assets/gitgraph.svg`.
Raw URLs cannot be loaded without credentials, so the image does not render in a private
repository's README. Use `--image URL` for another host.

### Safety rules

- It refuses if the files it would commit already have uncommitted edits (so your own README
  changes are never swept in; `--allow-dirty` overrides). Other staged or unstaged work is left
  exactly as it was.
- It refuses on a detached HEAD when it would need to commit, if an output file is ignored by
  `.gitignore`, or if the README has no valid markers.
- Running it again changes nothing (fixed point).
- The artifact branch is built with Git plumbing: your working tree, index and branches are not
  touched, its history only grows (fast-forward pushes, never forced), and it is excluded from the
  graph.
- The graph is built from the refs of the clone that runs it. Run `git fetch` first to include
  other people's branches; the last run wins.

`gitgraph publish` only does the publishing step (`--dry-run` builds the commit without pushing).
`gitgraph generate --update-readme` writes the files and nothing else, without touching history.

### Why the update commits are not drawn

Each update is a commit, and drawing it would change the graph again, forever. GitGraph therefore
does not draw commits whose subject is exactly the `[sync] commit_message` **and** that touch only
the generated files (SVG, JSON output, README, `gitgraph.toml`). They are spliced out in every graph:
children are re-linked to the hidden commit's parent and refs that point at one are moved to that
parent. Merge commits and root commits are never hidden. Set `hide_commits = false` to draw them
(then the graph can never settle, so do not combine that with `sync`).

The graph is complete up to the latest real commit; it never includes the update commit itself.
