"""Text templates written by ``gitgraph init``."""

WORKFLOW_TEMPLATE = """\
# Publishes the graph SVG to a dedicated branch so the graph never adds commits to the
# history it visualises. Replace OWNER/REPO@REF with the location of the GitGraph action.
name: GitGraph

on:
  push:
    branches-ignore: [gitgraph-assets]
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: gitgraph
  cancel-in-progress: false

jobs:
  graph:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # full history is required for a complete graph
      - uses: OWNER/REPO@REF
"""
