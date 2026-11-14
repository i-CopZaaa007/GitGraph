# GitHub Action

The action installs GitGraph, generates the SVG with the same CLI you use locally and publishes it
to a dedicated **artifact branch** (`gitgraph-assets` by default).

## Why a separate branch

Committing the SVG to the branch it visualises would add a commit per run, change the graph it
draws and could retrigger the workflow. The artifact branch is an orphan branch built with Git
plumbing (`hash-object`, `mktree`, `commit-tree`): the working tree and the index are never
touched, pushes are fast-forward only, and the branch is excluded from the graph automatically
(`--exclude gitgraph-assets --exclude '*/gitgraph-assets'`).

Trade-offs:

- The README references one stable URL (below), so the README itself never changes.
- `raw.githubusercontent.com` URLs work for **public** repositories. Private repositories cannot
  embed this URL in the README; commit the SVG on a normal branch instead (use `gitgraph generate
  --update-readme` in your own workflow and accept the extra commits).
- `GITHUB_TOKEN` pushes do not trigger other workflows, so the artifact push cannot loop.

## Setup

1. Add the workflow (`gitgraph init --workflow` writes this template). Set `uses:` to the
   repository and ref that host this action; pin a tag or commit SHA for reproducible runs.

   ```yaml
   # Example: refresh the graph on every push and publish it to the `gitgraph-assets` branch.
   name: GitGraph

   on:
     push:
       branches-ignore: [gitgraph-assets]   # the artifact branch must not retrigger the workflow
     workflow_dispatch:                     # allow manual runs

   permissions:
     contents: write                        # only needed to push the artifact branch

   concurrency:
     group: gitgraph                        # serialise updates of the artifact branch
     cancel-in-progress: false

   jobs:
     graph:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
           with:
             fetch-depth: 0                 # full history and all tags
         - uses: <owner>/<repo>@<ref>
           id: gitgraph
         # The README references the stable raw URL once (see the section below):
         #   ${{ steps.gitgraph.outputs.raw-url }}
   ```

2. Reference the image once in your README, between the markers:

   ```markdown
   <!-- gitgraph:start -->
   ![Git commit graph](https://raw.githubusercontent.com/<your-owner>/<your-repo>/gitgraph-assets/gitgraph.svg)
   <!-- gitgraph:end -->
   ```

   or `gitgraph init --add-markers --image <that URL>`.

## Requirements

- `actions/checkout` with `fetch-depth: 0` (the action also unshallows as a fallback).
- `permissions: contents: write` on the job (only used to push the artifact branch).
- If the default branch is protected, protect rules do not apply to the artifact branch unless you
  add a rule for it; do not require reviews or status checks on `gitgraph-assets`.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `config` | `""` | path to `gitgraph.toml` (auto-discovered if empty) |
| `working-directory` | `.` | repository directory |
| `file-name` | `gitgraph.svg` | file name on the artifact branch |
| `json` | `false` | also publish the JSON layout |
| `publish` | `true` | push to the artifact branch (`false` only generates) |
| `branch` | `gitgraph-assets` | artifact branch name (auto-excluded from the graph) |
| `commit-message` | `Update & Share Graph` | message on the artifact branch |
| `repository-url` | this repository | enables commit/tag links inside the SVG |
| `unshallow` | `true` | fetch full history if the checkout is shallow |
| `python-version` | `3.12` | interpreter used to run GitGraph |

Outputs: `svg-path`, `raw-url` (github.com only).

## Safety notes

- Inputs are passed to shell steps through environment variables, not interpolated into scripts.
- Secrets are never printed; the action does not read any.
- Concurrency: use the `concurrency` group shown in the example so two runs never race on the
  artifact branch.
- Manual runs: `workflow_dispatch` is included in the example.
