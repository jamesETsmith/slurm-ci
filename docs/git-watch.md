# Git Watch Documentation

The `git-watch` functionality allows you to automatically monitor GitHub repositories for new commits and trigger slurm-ci jobs when changes are detected.

## Overview

Git-watch runs as a daemon process that:
1. Polls a GitHub repository at regular intervals
2. Detects new commits on the specified branch
3. Triggers `slurm-ci slurm-run` to execute CI workflows on the Slurm cluster
4. Each SLURM job clones the repository directly on the compute node
5. Tracks processed commits in the database to avoid duplicate runs

## Configuration

Create a TOML configuration file with the following structure:

```toml
[daemon]
name = "my-project-main"
polling_interval = 300

[repository]
url = "https://github.com/user/repo"
branch = "main"
github_token = "optional_for_private_repos"

[slurm-ci]
config_dir = "/path/to/slurm-ci-configs"
workflow_file = "workflows/ci.yml"
```

### Configuration Options

#### `[daemon]` section
- `name`: Unique identifier for this daemon instance (required)
- `polling_interval`: How often to check for new commits in seconds (default: 300, minimum: 60)

#### `[repository]` section
- `url`: GitHub repository URL in HTTPS or SSH format (required)
- `branch`: Git branch or wildcard pattern to monitor (default: `"main"`). Accepts
  short branch names (`main`), wildcards (`release/*`), or fully-qualified refs
  (`refs/tags/v*`).
- `branches`: List of branch/ref patterns. Mutually exclusive with `branch` and
  `refs`. Example: `branches = ["main", "release/*"]`.
- `refs`: Table with `include`, optional `exclude`, and optional `match_style`.
  Mutually exclusive with `branch` and `branches`. See *Branch patterns* below.
- `github_token`: Personal access token for private repos or higher rate limits (optional)

##### Branch patterns

Each poll runs a single `git ls-remote` with the configured include patterns
and filters the returned refs locally. Every matching ref produces an
independent CI run (subject to the existing commit-tracker dedup, so each
unique commit SHA is still only triggered once).

Two match styles are available, controlled by `refs.match_style`:

| Style       | `*` behavior                  | `**` behavior             | Default |
|-------------|-------------------------------|---------------------------|---------|
| `fnmatch`   | Matches across `/`            | Not special               | yes     |
| `git`       | Does **not** cross `/`        | Matches 0+ segments       | no      |

`fnmatch` is the default for backward compatibility with existing configs
that used patterns like `release/*`.

Examples:

```toml
# Single pattern (legacy form)
[repository]
branch = "release/*"
```

```toml
# Multiple patterns
[repository]
branches = ["main", "release/*"]
```

```toml
# Include/exclude with git-style matching
[repository]
url = "https://github.com/user/repo"

[repository.refs]
include = ["main", "refs/tags/v*"]
exclude = ["release/*-rc*"]
match_style = "git"
```

With `match_style = "git"`, `release/*` matches `release/1.0` but not
`release/1.0/hotfix`; use `release/**` to cover nested segments.

#### `[slurm-ci]` section
- `config_dir`: Directory containing slurm-ci configuration files (required)
- `workflow_file`: Path to workflow file relative to config_dir (default: "workflows/ci.yml")

## Usage

### Create Example Configuration
```bash
slurm-ci git-watch create-config --output my-config.toml
```

### Start a Git-Watch Daemon
```bash
slurm-ci git-watch start my-config.toml
```

The daemon will run in the foreground. To run in the background, use:
```bash
nohup slurm-ci git-watch start my-config.toml > /dev/null 2>&1 &
```

### Check Daemon Status
```bash
slurm-ci git-watch status
```

### Stop a Specific Daemon
```bash
slurm-ci git-watch stop my-project-main
```

### Stop All Daemons
```bash
slurm-ci git-watch stop-all
```

## File Structure

Git-watch creates the following directory structure:

```
~/.slurm-ci/
├── git-watch/
│   ├── pids/
│   │   └── {daemon_name}.pid      # Process ID files
│   ├── status/
│   │   └── {daemon_name}.status   # Status information (JSON)
│   └── logs/
│       └── {daemon_name}.log      # Daemon log files
├── slurm_ci.db                    # Extended with git tracking tables
└── job_status/                    # Existing slurm job status files

Note: Repositories are cloned to temporary directories on each compute node and cleaned up after each job.
```

## Database Integration

Git-watch extends the existing slurm-ci database with two new tables:

- `git_repos`: Stores repository configuration and state
- `commit_trackers`: Tracks which commits have been processed

This ensures that:
- Commits are only processed once
- Daemon state persists across restarts
- You can track the history of triggered builds

## Workflow File Location

**Important**: The workflow file is read from your **config directory**, not from the cloned repository. This allows you to:
- Use standardized slurm-ci workflows across multiple repositories
- Maintain workflow files separately from the source code
- Avoid requiring each repository to have specific GitHub Actions files

Example directory structure:
```
/path/to/slurm-ci-configs/
├── workflows/
│   ├── ci.yml              # Your custom slurm-ci workflow
│   └── nightly.yml         # Additional workflows
├── matrix-configs/
│   └── gpu-matrix.yml      # Matrix configurations
└── environment/
    └── env-vars.yml        # Environment settings
```

## GitHub API Integration

Git-watch uses the GitHub API to fetch the latest commit SHA for the monitored branch. This approach:
- Is more efficient than cloning the entire repository for each check
- Respects GitHub's rate limiting
- Works with both public and private repositories (with appropriate tokens)

### Rate Limiting

- Without authentication: 60 requests per hour
- With GitHub token: 5,000 requests per hour
- Minimum polling interval: 60 seconds

## Error Handling

Git-watch includes robust error handling for:
- GitHub API failures (network issues, rate limiting, repository access)
- Git clone failures
- Slurm job submission errors
- Database connection issues

Errors are logged to the daemon log file and the daemon continues running.

## Multiple Daemons

You can run multiple git-watch daemons simultaneously to monitor:
- Different repositories
- Different branches of the same repository
- The same repository with different configurations

Each daemon must have a unique `name` in its configuration.

## Security Considerations

- Store GitHub tokens securely (consider using environment variables)
- Ensure the slurm-ci config directory has appropriate permissions
- Monitor daemon log files for any security-related errors
- Regularly rotate GitHub personal access tokens

## Troubleshooting

### Daemon Won't Start
- Check configuration file syntax with a TOML validator
- Verify GitHub repository URL and access permissions
- Ensure slurm config directory exists and is readable

### No Jobs Being Triggered
- Check daemon logs for GitHub API errors
- Verify workflow file exists in the repository
- Confirm slurm-ci can access the Slurm cluster
- Check database for commit tracking entries

### High Resource Usage
- Increase polling interval to reduce GitHub API calls
- Monitor cloned repository disk usage in `~/.slurm-ci/git-watch/repos/`
- Consider cleaning up old repository clones periodically
