# Algorithms and invariants

## Topological order (`graph.py`)

Kahn's algorithm over the commit DAG, children before parents. A max-heap keyed on
`(committer time, SHA)` chooses between *unrelated* ready commits. Timestamps never override
ancestry, so clock skew cannot place a parent above its child. After a commit is emitted its
first parent is emitted immediately if it just became ready ("chain following"), which keeps
first-parent lines contiguous the way `git log --topo-order` does.

Invariants (tested, including on random DAGs with skewed timestamps):

1. every commit appears exactly once;
2. every commit appears before all of its parents;
3. identical input gives identical order;
4. a cycle raises `GraphError` instead of looping.

Complexity: O((V + E) log V). A 50 000-commit history is processed in about 19 s end to end on
a laptop (collection, layout and SVG rendering) using under 300 MB.

## Reachability

One bit per branch ref; bits are pushed from tips to ancestors in a single pass over the order.
This answers "which collected branches can reach this commit?" (shown in tooltips and JSON). It is
deliberately separate from colouring: a commit reachable from many branches is still **one node**.

## Ownership and colour (`lanes.py`)

- Branch *identity* is the branch name without the remote prefix, so `main` and `origin/main`
  share a lane.
- Identities are ranked: primary branch first (configured, `origin/HEAD`, `main`, `master`, the
  checked-out branch), then by tip age (the branch whose tip is oldest claims first, so a
  branch stacked on another keeps its own lane), then by name.
- Each identity walks first-parent chains from its tip(s) and claims unclaimed commits.
- A commit nobody claims (typically a merged-and-deleted branch) is *unattributed*. It is drawn
  with a muted, dashed line and listed in the legend as "unnamed history". **No branch name is
  invented**, and merge commit messages are never parsed.
- Palette index = SHA-1 of the name modulo palette size, then probing to the least-used index in
  sorted-name order. The primary branch is always palette index 0. Adding an unrelated branch
  therefore changes the colour of another branch only when it hashes to the same slot and sorts
  earlier. When branches outnumber colours, reused colours get a different dash pattern.

Visual rule for shared commits: a node is drawn in the colour of the line that *carries* it
(its owner). That does not claim exclusivity; the tooltip and JSON list every branch that
reaches it.

## Column assignment

Commits are placed top to bottom while a list of *slots* tracks the lines in flight; each slot
waits for one parent commit.

- A commit takes the column of an incoming slot whose colour matches its owner (else the
  leftmost). A tip with no incoming slot takes the first free column; column 0 is reserved for the
  primary branch until it appears.
- The first parent keeps the commit's column. Every further parent of a merge opens a new slot to
  the right. Several slots may wait for the same parent: they *converge* there, which draws a
  branch rejoining its fork point after running straight down in its own column.
- Rows hold one node each and a column that carries a slot never receives a node, so lines never
  pass through foreign nodes. `tests/invariants.py` samples every routed edge and asserts a
  clearance from all other nodes, on random DAGs.

## Geometry

- Labels sit in one column to the right of all lanes, so edges can never cross label text.
- Row height = `max(min_row_height, label block + row_gap)`; the label block holds badge rows,
  wrapped subject lines and the meta line. The node is centred on the block.
- Subject wrapping: greedy at word boundaries within `label_width`, words wider than a line are
  broken between characters (combining marks stay attached), at most `max_label_lines` lines; the
  last line is cut with `…`. Widths are heuristic (CJK/emoji wide, combining marks zero) because
  the viewer's font is unknown.
- Edge routes are `[child, (travel column, y+h), (travel column, y−h), parent]` waypoints with
  `h = min(curve_height, gap/2)`; consecutive points with different x become S-curves.

## Tags

See `tags.py`: version-like tags (`1.2`, `v1.2.3`, `1.0.0-rc.1`) compare numerically with
pre-releases below the release; others by date; ties by name. `latest_tag = "auto"` prefers the
highest stable version, then the highest pre-release, then the newest by date.
