# Limitations and troubleshooting

## What Git can and cannot tell us

- **A branch is a mutable pointer.** The graph shows where branch refs point *now*. A branch's
  past positions are not recorded in the object graph.
- **Deleted branches.** Their names and creation/deletion times are unrecoverable from commits
  alone. If their commits are still reachable (for example after a merge) they are drawn as
  *unnamed history*; if not reachable they are absent. The reflog and unreachable objects are not
  part of the graph.
- **Squash merges** create an ordinary one-parent commit; the squashed branch is not an ancestor,
  so no merge line is drawn. **Rebases** and **force-pushes** rewrite history: the graph shows the
  current refs only, and old commits that are no longer reachable disappear.
- **Fast-forward merges** produce no merge commit, so the branches simply share a line.
- **Merge detection** uses the parent count. A message that says "Merge ..." on a one-parent
  commit is not a merge, and a merge with a custom message still is.
- **Octopus merges** are drawn as one merge node with several incoming lines.

## Scope

By default every commit reachable from local branches, remote-tracking branches and tags is shown
(`history.max_commits = 0`). `include`/`exclude` patterns narrow this; the artifact branch
`gitgraph-assets` is excluded by default. Symbolic refs (`origin/HEAD`), `refs/stash`, notes and
pull-request refs are never collected. If no branch or tag is collected (for example a detached HEAD in a repository without branches), `HEAD` is used as the only tip; it is not used when you disabled or filtered refs on purpose.

**Detached HEAD** commits that no collected ref reaches are not shown (only refs define the history). In CI, `pull_request` checkouts are such a case: the graph shows the branches and tags, not the temporary merge commit.

**Stale remote-tracking branches** (deleted upstream) stay in the graph until `git fetch --prune`.

**Same name, different remotes.** `main`, `origin/main` and `fork/main` share one lane and colour (badges show the full names), even when they diverge.

**Primary branch guess.** Order: `history.primary_branch`, `origin/HEAD`, `main`, `master`, the checked-out branch. If your trunk is `master` while a stale `main` exists, set `primary_branch`.

**Many branches.** Width grows with concurrently open lines (30 parallel branches ≈ 1,270 px); the legend lists 24 names and summarises the rest. Use `include`/`exclude` to focus.

**Shallow clones** are detected. Boundary commits are drawn as dashed squares and the footer says
the history is truncated; they are not claimed to be initial commits. Fix: `git fetch --unshallow`
or `fetch-depth: 0` in `actions/checkout`.

**Missing remote refs.** Remote-tracking branches only exist if they were fetched. In CI use
`fetch-depth: 0` (which fetches all branches and tags) so the graph matches what you see locally.

**Multiple roots.** Unrelated histories each end in their own root; the footer says so and no
shared initial commit is implied.

## Rendering

- Text width is estimated; very different fonts may wrap slightly earlier or later than expected.
- `<a>` links in the SVG only work when the SVG is opened directly. GitHub shows README images
  through `<img>`, where links inside the image are not clickable.
- The default theme is `light`. `theme = "auto"` follows the viewer's operating-system colour scheme. GitHub's own theme
  setting can differ; use `theme = "light"` or `"dark"` (or publish two files) if that matters.
- Very large histories produce very large SVGs. Use `history.max_commits` for README embedding.
- Mermaid output is not provided: Mermaid's `gitGraph` is branch-centric and cannot express unnamed lines, octopus merges or shared commits faithfully.

## Caching

GitHub proxies and caches images referenced by absolute URL. A relative path to a file in the same
repository is served from the repository. After an update you may need to wait for the cache or
reload; `readme.cache_bust = true` appends `?v=<hash of the SVG>` to the image reference.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error: not a git repository` | pass `--repo` or run inside a repository |
| Graph is short in CI | shallow checkout; use `fetch-depth: 0` |
| `README has no ... markers` | run `gitgraph init --add-markers` or set `readme.insert` |
| `found 2 start marker(s)` | duplicated markers; remove the extra ones by hand (nothing was changed) |
| Legend shows "unnamed history" | commits reachable only through merges of deleted branches |
| Remote branches missing | `git fetch --all` or include them in the checkout |
