# Contributing

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Checks (all must pass)

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/pytest
```

Optional heavier runs:

```bash
GITGRAPH_PERF_COMMITS=50000 .venv/bin/pytest tests/test_performance.py -s -k large
GITGRAPH_PERF_FULL=1 .venv/bin/pytest tests/test_performance.py -k medium
```

## Layout of the code

See [docs/architecture.md](docs/architecture.md). The key rule: `collector` is the only module that
runs Git; `layout` and `svg` never import it; nothing in the core knows about GitHub.

## Guidelines

- Treat every string that comes from Git as untrusted. Route text through `text.clean_text` and
  escape it at the output boundary.
- Keep output deterministic: no timestamps of generation, no unordered iteration, no randomness.
- Add a test with the change. Graph and layout changes should keep the invariants in
  `tests/invariants.py` passing, including the randomised DAG tests.
- Tests that need Git build real repositories with `tests/gitrepo.py`; they never touch the
  global Git configuration.
