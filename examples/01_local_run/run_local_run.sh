#!/usr/bin/env bash

set -euo pipefail

SLURM_CI_ROOT=$(dirname $(dirname $(dirname $(realpath $0))))


# slurm-ci must be in your local env
slurm-ci local-run --workflows ${SLURM_CI_ROOT}/.github/workflows/ --directory ${SLURM_CI_ROOT}

