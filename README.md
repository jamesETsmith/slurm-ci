## Design Goals
Dynamic Container Detection: Parses workflow YAML to extract container specifications

Matrix Variable Resolution: Handles ${{ matrix.variable }} expressions in container images

Flexible Orchestration: Supports both Kubernetes Jobs and Slurm+Docker execution

GPU-Aware Scheduling: Maps GPU architecture requirements to appropriate cluster nodes

Environment Compatibility: Maintains GitHub Actions environment variable compatibility

Immediate Feedback: Test workflows without committing to Git

Development Acceleration: Iterate on workflow configurations quickly

Flexible Execution: Choose between local Docker or remote cluster execution

Matrix Testing: Test specific matrix combinations locally

Workflow Discovery: Automatically find and list available workflows

Compatibility: Uses same workflow syntax as your Git-based system

## Example Usage
```bash
# Run workflow in current directory
./slurm-ci

# Run specific workflow file
./slurm-ci .slurm-ci/workflows/ci.yml

# Run with specific matrix combination
./slurm-ci --matrix '{"gpu_arch": "gfx90a", "rocm_version": "5.7.0"}'

# Run specific job only
./slurm-ci --job build-and-test

# Show execution plan without running
./slurm-ci --dry-run

# Run on cluster instead of locally
./slurm-ci --execution-mode cluster --cluster-config cluster.json

# List available workflows
./slurm-ci --list-workflows

# List jobs in specific workflow
./slurm-ci --list-jobs .amd/workflows/ci.yml

# Run from different directory
./slurm-ci -d /path/to/project .amd/workflows/ci.yml
```