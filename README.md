# Slurm CI

Slurm CI is a tool for running CI workflows locally or on a Slurm cluster.

## Known Issues
It will sometimes create multiple jobs on the same node (maybe because the nodes have been broken into virtual mahcines) and docker crashes.

## Usage

```bash
# Run a workflow on the current machine (i.e. nektos/act wrapper):
slurm-ci local-run --<pass through args to nektos/act>

# Read the workflows and submit all jobs to the slurm as individual jobs:
slurm-ci slurm-run <workflow_file> <working_directory>
```

## Installation

```
# Install nektos/act
curl --proto '=https' --tlsv1.2 -sSf https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Add act to your PATH
export PATH=PATH:$(pwd)/bin

# Install slurm-ci
pip install -e .
```

## Design Goals

- Make it easier to run CI workflows locally
  - `nektos/act` essentially does this for us
- Support launching slurm jobs for running all workflows (and all matrix combinations)
  - We need to find workflows, break them down into the smallest jobs (i.e. single matrix comfix)
  - Create and submit slurm jobs that use `nektos/act` to run the jobs
- Monitor and trigger new jobs when a new commit is pushed to the repository
- Create a UI and database for managing the jobs and their results
  - Let's start with just the database and UI for local testing, we'll add the remote monitoring later

