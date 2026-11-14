# Configuration reference

`gitgraph.toml` (or `.gitgraph.toml`) in the repository root is read automatically; use `--config`
for another file. Every key is optional. Unknown keys and invalid values are rejected with a
message naming the section and key. `gitgraph init` writes a commented starter file.

Paths from the command line (`-o`, `--json`) are relative to the current directory; paths in the
file are relative to the repository.

## `[output]`

| Key | Default | |
|---|---|---|
| `svg` | `docs/gitgraph.svg` | SVG path |
| `json` | `""` | extra JSON layout path (empty = none) |

## `[history]`

| Key | Default | |
|---|---|---|
| `branches`, `remotes`, `tags` | `true` | which ref kinds to collect |
| `include` | `[]` | fnmatch patterns selecting **branches** (local and remote); empty means all. Tags are not affected; use `tags = false` or `exclude` |
| `exclude` | `["gitgraph-assets", "*/gitgraph-assets"]` | patterns to drop from branches *and* tags (wins over include) |
| `max_commits` | `0` | newest N commits in topological order; `0` = all |
| `primary_branch` | `""` | lane that gets column 0 and the first colour |
| `latest_tag` | `auto` | `auto`, `version`, `date` (see algorithms) |

## `[display]`

| Key | Default | |
|---|---|---|
| `title`, `show_title` | `"Commit graph"`, `true` | heading inside the SVG |
| `legend` | `true` | branch legend |
| `release_summary` | `true` | latest-tag line above the graph |
| `tags`, `branch_labels` | `true` | badges on commits |
| `sha`, `author`, `date` | `true`, `false`, `false` | meta line under the message |
| `message_mode` | `subject` | `subject` or `full` (adds the commit body) |
| `max_label_lines` | `3` | lines per label; the last is cut with `…` |

## `[layout]`

`label_width` (520), `font_family`, `font_size` (13), `node_radius` (6), `line_width` (3.5),
`lane_spacing` (22), `row_gap` (16), `min_row_height` (40), `padding` (24). Orientation is
vertical (newest on top) only.

## `[theme]`

`name` = `light` (default), `dark`, or `auto` (follows the viewer's colour scheme); `palette` = list of
`#rrggbb` colours (the default palette has four accent colours plus three neutrals, keeps ≥ 3:1 contrast on white and on `#0d1117`, and ≥ 4.5:1 for white text on a branch sign);
`responsive` adds `max-width:100%;height:auto` to the root element.

## `[links]`

`repository_url` (empty = no links, `auto` = derive from `origin`, https only, credentials
stripped), `commit_url` (`{repo}/commit/{sha}`), `tag_url` (`{repo}/tree/{tag}`). Adjust the
templates for GitLab (`{repo}/-/commit/{sha}`) or other hosts.

## `[readme]`

`path`, `heading` (empty = none), `heading_level`, `insert` (`none`, `append`, `prepend`,
`after-first-heading` – used only when markers are missing), `image` (path or URL overriding the
SVG path), `alt`, `cache_bust`.

## `[sync]`

`commit_message` (`"Update & Share Graph"`) is the message used by `gitgraph sync`; `hide_commits` (`true`) hides single-parent commits with exactly that message that touch only the generated files. See [automation.md](automation.md).

## `[publish]` (shared mode)

`enabled` (`false`), `branch` (`gitgraph-assets`), `remote` (`origin`), `file` (`gitgraph.svg`). When enabled,
`gitgraph sync`/`publish` push the SVG to that branch; the branch is excluded
from the graph automatically. See [automation](automation.md).

## Markers

```markdown
<!-- gitgraph:start -->
...anything here is replaced...
<!-- gitgraph:end -->
```

Rules: exactly one pair; markers on their own lines; markers inside fenced code blocks are
ignored; duplicated, missing-partner or reversed markers abort without writing. Line endings and
everything outside the markers are preserved, and repeated runs produce identical files.
