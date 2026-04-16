# slurm-ci

[![](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/jamesETsmith/slurm-ci/blob/main/LICENSE)

:construction: **This project is under active development and is not yet ready for production use.**
:construction: **Not all tests are working yet.**

`slurm-ci` is a tool for running GitHub Actions workflows on a Slurm cluster. It provides a bridge between the local development environment and a high-performance computing (HPC) environment, allowing you to test and run your CI pipelines with the power of Slurm.

## Installation

### From Github
```bash
pip install https://github.com/jamesETsmith/slurm-ci.git
```

### Dev setup (from source)
```bash
git clone https://github.com/jamesETsmith/slurm-ci.git
cd slurm-ci
pip install -e ".[dev]"
pre-commit install
```

## Overview
![slurm-ci_services](slurm-ci_services.svg)

## Commands

### `local-run`

The `local-run` command is a convenient wrapper around the `act` tool, allowing you to execute your GitHub Actions workflows locally. This is useful for testing and debugging your workflows before submitting them to the Slurm cluster.

**Usage:**

```bash
slurm-ci local-run [act arguments]
```

All arguments passed to `local-run` are forwarded directly to `act`. For more information on the available arguments, please refer to the `act` documentation.

**Example:**

```bash
slurm-ci local-run --job my-test-job
```

### `slurm-run`

The `slurm-run` command allows you to submit your GitHub Actions workflows to a Slurm cluster. It can be used in three different ways:

**1. Using command-line arguments:**

You can specify the workflow file and working directory directly on the command line.

**Usage:**

```bash
slurm-ci slurm-run --workflow_file <path_to_workflow> --working_directory <path_to_project>
```

**Example:**

```bash
slurm-ci slurm-run --workflow_file .github/workflows/main.yml --working_directory .
```

**2. Using a configuration file:**

For more complex configurations, you can use a TOML configuration file to specify the workflow, working directory, and any custom Slurm options.

**Usage:**

```bash
slurm-ci slurm-run --config <path_to_config.toml>
```

**Example `slurm-run-config.toml`:**
```toml
[slurm-ci]
workflow_file = ".github/workflows/main.yml"
working_directory = "."

[slurm-ci.slurm]
gres = "gpu:gfx942"
cpus-per-task = 32
time = "12:00:00"
```

**3. Generating a configuration template:**

You can generate a template configuration file to get started quickly.

**Usage:**

```bash
slurm-ci slurm-run --generate-template
```

This will create a `slurm-run-config.toml` file in your current directory with the default options, which you can then customize to your needs.

### `git-watch`

The `git-watch` command allows you to monitor a Git repository for new commits and automatically trigger `slurm-run` jobs. It runs as a daemon process and can be managed with the following subcommands:

**1. Create a configuration file:**

Before starting a `git-watch` daemon, you need to create a configuration file.

**Usage:**

```bash
slurm-ci git-watch create-config --output <path_to_config.toml>
```

**Example `git-watch-config.toml`:**

```toml
[daemon]
name = "my-project-main"
polling_interval = 300

[repository]
url = "https://github.com/user/repo"
branch = "main"
github_token = "optional_for_private_repos"

[slurm-ci]
workflow_file = "workflows/ci.yml"
working_directory = "/path/to/working-directory"

[slurm-ci.slurm]
gres = "gpu:gfx942"
"cpus-per-task" = 32
time = "12:00:00"
partition = "gpu"
```

The `[repository]` section also accepts wildcard ref patterns. Use any one
of the forms below (they are mutually exclusive):

```toml
[repository]
branch = "release/*"                       # single pattern
```

```toml
[repository]
branches = ["main", "release/*"]           # list of patterns
```

```toml
[repository]
url = "https://github.com/user/repo"

[repository.refs]
include = ["main", "refs/tags/v*"]
exclude = ["release/*-rc*"]
match_style = "git"                        # "fnmatch" (default) or "git"
```

Each matching ref triggers an independent CI run. See
[`docs/git-watch.md`](docs/git-watch.md#branch-patterns) for the full
pattern-matching reference.

**2. Start a daemon:**

**Usage:**

```bash
slurm-ci git-watch start --config <path_to_config.toml>
```

**3. Stop a daemon:**

**Usage:**

```bash
slurm-ci git-watch stop <daemon_name>
```

**4. Stop all daemons:**

**Usage:**

```bash
slurm-ci git-watch stop-all
```

**5. Check daemon status:**

**Usage:**

```bash
slurm-ci git-watch status
```

### `dashboard`

The dashboard is a lightweight Flask/Jinja UI for monitoring builds and jobs.
It is intentionally minimal and optimized for quick triage.

**Usage:**

```bash
slurm-ci dashboard --host 127.0.0.1 --port 5001
```

**Key behaviors:**

- `Builds` view is DB-backed (SQLite) and supports query filters:
  - `status`
  - `branch`
  - `workflow`
- `Logs` view is filesystem-backed (`$SLURM_CI_STATUS_DIR` or default status dir) and is labeled separately in the UI.
- Tables support client-side sort/search/pagination through `simple-datatables`.
- Summary cards and trend chart auto-refresh periodically via `htmx`.

**Debug route safety:**

The `/debug/logs` endpoint is disabled by default.
Enable it only when needed:

```bash
SLURM_CI_ENABLE_DEBUG_ROUTES=1 slurm-ci dashboard
```

### `services`

To run background services together (for example dashboard + DB sync watcher), use:

```bash
slurm-ci services up
```

