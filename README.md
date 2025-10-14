# slurm-ci

`slurm-ci` is a tool for running GitHub Actions workflows on a Slurm cluster. It provides a bridge between the local development environment and a high-performance computing (HPC) environment, allowing you to test and run your CI pipelines with the power of Slurm.

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
