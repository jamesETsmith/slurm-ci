# AGENTS.md

## Project Purpose

`slurm-ci` runs GitHub Actions workflows in Slurm environments. It has three main flows:

- Local workflow execution through `act`
- Slurm job submission for matrix-expanded workflow jobs
- Git repository polling (`git-watch`) that triggers Slurm runs for new commits

Core package path: `src/slurm_ci`.

## Codebase Map

- `src/slurm_ci/cli.py`: CLI entrypoint (`slurm-ci`) and command wiring
- `src/slurm_ci/workflow_parser.py`: YAML workflow parsing and matrix/include expansion
- `src/slurm_ci/slurm_launcher.py`: Jinja2 script rendering and `sbatch` submission
- `src/slurm_ci/status_file.py`: TOML status file creation and metadata updates
- `src/slurm_ci/status_watcher.py`: sync status TOML files into SQLite models
- `src/slurm_ci/git_watcher.py`: daemon loop for polling commits and triggering runs
- `src/slurm_ci/database.py`: SQLAlchemy models and DB init
- `src/slurm_ci/config.py`: runtime directories and env-var-based paths
- `tests/`: parser, launcher, git-watch, DB, and status sync tests

## Environment and Paths

The project uses runtime paths under `~/.slurm-ci` by default and supports env overrides:

- `SLURM_CI_DIR`
- `SLURM_CI_STATUS_DIR`
- `SLURM_CI_ACT_BINARY`

When writing tests or scripts, avoid assumptions about absolute home paths. Prefer temp dirs and monkeypatching env/config where possible.

## Setup Commands

```bash
pip install -e ".[dev]"
pre-commit install
```

## Validation Commands

Run these before finalizing changes:

```bash
ruff check .
ruff format .
pytest -q
```

If a full suite is expensive or environment-dependent, run a focused subset for touched modules, for example:

```bash
pytest -q tests/parser/test_workflow_parser.py
pytest -q tests/test_git_watcher.py
pytest -q tests/slurm_launcher/test_launcher_mocked.py
```

## Development Conventions

- Python 3.10+ style with type hints and docstrings for non-trivial functions
- Keep imports Ruff/isort-compliant
- Preserve CLI compatibility in `cli.py` (existing flags/subcommands are user-facing)
- Prefer deterministic, unit-level tests with mocks over real Slurm/daemon execution
- Keep status-file shape backward compatible (`project`, `git`, `ci`, `slurm`, `matrix`, `runtime`)
- Use existing SQLAlchemy models rather than ad-hoc schema changes

## Safety Rules for Changes

- Do not remove or silently alter env-var overrides in `config.py`
- Do not hardcode cluster-specific values beyond existing defaults unless feature-gated
- Avoid breaking matrix include semantics in `workflow_parser.py`
- Any change to status sync logic should preserve handling of:
  - incomplete jobs (no `runtime.end`)
  - `runtime.end.exit_code`
  - optional `sacct` augmentation
- For daemon behavior, ensure failures are logged and recoverable rather than crash-only

## Testing Guidance by Area

- Parser changes: update/add tests in `tests/parser/`
- Slurm launch/template changes: update/add tests in `tests/slurm_launcher/` (prefer mocked `subprocess.run`)
- Git-watch changes: update/add tests in `tests/test_git_watcher.py` and `tests/git_watch/`
- DB/status sync changes: update/add tests in `tests/test_database.py` and `tests/test_status_sync_fix.py`

## Notes for Agentic Edits

- Make minimal, targeted edits; avoid broad refactors unless requested
- Keep public behavior stable unless task explicitly asks for a behavior change
- If introducing new config fields, document defaults and migration behavior
- When adding files, place docs in `docs/` and tests near relevant existing suites
- Always rerun tests and linting (see pyproject.toml) after making changes and address any issues
