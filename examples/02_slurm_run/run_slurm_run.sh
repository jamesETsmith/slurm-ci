#!/usr/bin/env bash
set -euo pipefail

SLURM_CI_ROOT=$(dirname $(dirname $(dirname $(realpath $0))))

# slurm-ci must be in your local env
slurm-ci slurm-run --workflow_file ${SLURM_CI_ROOT}/.github/workflows/ci.yml --working_directory ${SLURM_CI_ROOT}

# Alternatively, you can use a config file
slurm-ci slurm-run --generate-template
# edit the config file
slurm-ci slurm-run --config slurm-run-config.toml
