# Architecture

```
 git CLI ──► collector ──► RepositorySnapshot ──► graph ──► CommitGraph
                                                              │
                      config ─────────────────────────────────┤
                                                              ▼
                                      lanes (ownership, colours, columns)
                                                              │
                                                              ▼
                                          layout ──► GraphLayout ──► svg / jsonout
                                                                         │
 README.md ◄── readme (markers) ◄────────────── cli / action ◄──────────┘
```

| Module | Responsibility | Knows about |
|---|---|---|
| `models` | Immutable records: `Commit`, `Reference`, `Tag`, `RepositorySnapshot`, `Diagnostic` | nothing |
| `collector` | Runs read-only Git commands with argument arrays; parses NUL-delimited output | `models` |
| `graph` | Adjacency, roots, merges, topological order, ref reachability | `models` |
| `lanes` | Branch ownership, colours, column assignment (no coordinates) | `graph`, `models` |
| `layout` | Coordinates, label wrapping, badges, edge routes, header/footer | `graph`, `lanes`, `tags`, `text` |
| `svg`, `jsonout` | Serialise a `GraphLayout`; escape all text | `layout`, `theme`, `urls` |
| `readme` | Marker detection, replacement, insertion, atomic write | nothing |
| `config` | TOML → typed settings with validation | option dataclasses |
| `api` | `generate()` orchestration used by CLI and integrations | everything above |
| `cli` | argparse front end, exit codes, `init`/`validate` | `api`, `readme`, `config` |
| `action.yml`, `action/` | Thin composite action: install, run the CLI, publish | the CLI only |

Boundaries enforced by design:

- Only `collector` imports `subprocess`. Git is never invoked through a shell.
- `layout` and the renderers never call Git. They receive plain data.
- No GitHub-specific field exists in the domain model. A repository URL is optional renderer
  input (`RenderOptions.repository_url`).
- The renderers never mutate commits; computed visual attributes live in `GraphNode`.

## Data contracts

- `RepositorySnapshot.commits` maps full SHA → `Commit`; `Commit.parents` keeps Git's order.
- Parents absent from `commits` are not an error: `build_graph` records them in
  `CommitGraph.missing_parents` and the layout draws a truncation stub plus a diagnostic.
- `GraphLayout.nodes` is ordered top → bottom; `GraphNode.row` equals its index.
- `GraphEdge.points` is a polyline of waypoints; consecutive points with different x are joined
  by a vertical-tangent S-curve by the renderer.

## JSON schema (version 1)

`gitgraph generate --json out.json` writes: `schema_version`, `generator`, `canvas`, `counts`,
`latest_tag`, `lanes`, `nodes` (sha, row, column, x, y, kind, parent_count, lane, color, subject,
author, authored_at, reachable_from, refs, tags), `edges`, `notes`, `diagnostics`. The output has
no generation timestamp and no e-mail addresses, so it is byte-stable for identical input.
