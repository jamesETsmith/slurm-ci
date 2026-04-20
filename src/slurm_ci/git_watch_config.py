#!/usr/bin/env python3
"""Configuration parser for git-watch functionality."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import toml

from .ref_matcher import MatchStyle, RefPatternSet


@dataclass
class GitWatchConfig:
    """Configuration for a git-watch daemon instance.

    Ref selection can be provided in one of three mutually-exclusive forms
    in the ``[repository]`` section of the TOML config:

    * ``branch = "<name-or-pattern>"`` — legacy scalar, default ``"main"``.
    * ``branches = ["<name-or-pattern>", ...]`` — list of patterns.
    * ``[repository.refs]`` table with ``include``, optional ``exclude``,
      and optional ``match_style``. Entries may be short branch names or
      fully-qualified refs (``refs/heads/...``, ``refs/tags/...``).

    ``match_style`` applies to all three forms and is either ``"fnmatch"``
    (default, ``*`` crosses ``/`` — legacy behavior) or ``"git"`` (``*``
    does not cross ``/``; ``**`` matches zero or more path segments).
    """

    # Required fields (no defaults)
    daemon_name: str
    repo_url: str
    workflow_file: str
    working_directory: str

    # Optional fields (with defaults)
    polling_interval: int = 300
    branch: str = "main"
    branches: Optional[List[str]] = None
    refs_include: Optional[List[str]] = None
    refs_exclude: List[str] = field(default_factory=list)
    match_style: MatchStyle = "fnmatch"
    github_token: Optional[str] = None
    slurm_options: Optional[Dict[str, Any]] = None

    @classmethod
    def from_file(cls, config_path: str) -> "GitWatchConfig":
        """Load configuration from a TOML file."""
        config_path_obj = Path(config_path).resolve()
        if not config_path_obj.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path_obj}")

        with open(config_path_obj, "r") as f:
            config_data = toml.load(f)

        config_dir = config_path_obj.parent
        slurm_ci_config = config_data.get("slurm-ci", {})

        # Resolve paths to be absolute relative to the config file
        if "workflow_file" in slurm_ci_config:
            workflow_file = Path(slurm_ci_config["workflow_file"])
            if not workflow_file.is_absolute():
                slurm_ci_config["workflow_file"] = str(
                    (config_dir / workflow_file).resolve()
                )

        if "working_directory" in slurm_ci_config:
            working_directory = Path(slurm_ci_config["working_directory"])
            if not working_directory.is_absolute():
                slurm_ci_config["working_directory"] = str(
                    (config_dir / working_directory).resolve()
                )

        return cls.from_dict(config_data)

    @classmethod
    def from_dict(cls, config_data: dict) -> "GitWatchConfig":
        """Create configuration from a dictionary."""
        daemon_config = config_data.get("daemon", {})
        repo_config = config_data.get("repository", {})
        slurm_config = config_data.get("slurm-ci", {})

        # Validate required fields
        required_fields = {
            "daemon.name": daemon_config.get("name"),
            "repository.url": repo_config.get("url"),
            "slurm-ci.workflow_file": slurm_config.get("workflow_file"),
            "slurm-ci.working_directory": slurm_config.get("working_directory"),
        }

        missing_fields = [name for name, value in required_fields.items() if not value]
        if missing_fields:
            raise ValueError(
                f"Missing required configuration fields: {', '.join(missing_fields)}"
            )

        # Reject unknown keys so typos and misplaced options are never
        # silently ignored.
        _KNOWN_REPO_KEYS = {
            "url",
            "branch",
            "branches",
            "refs",
            "exclude",
            "match_style",
            "github_token",
        }
        unknown = set(repo_config) - _KNOWN_REPO_KEYS
        if unknown:
            raise ValueError(
                f"Unknown key(s) in [repository]: {', '.join(sorted(unknown))}. "
                f"Allowed keys: {', '.join(sorted(_KNOWN_REPO_KEYS))}"
            )

        branch_scalar = repo_config.get("branch")
        branches_list = repo_config.get("branches")
        refs_table = repo_config.get("refs")

        specified = [
            key
            for key, value in (
                ("branch", branch_scalar),
                ("branches", branches_list),
                ("refs", refs_table),
            )
            if value is not None
        ]
        if len(specified) > 1:
            raise ValueError(
                "Configure at most one of 'repository.branch', "
                f"'repository.branches', or 'repository.refs'; got: {specified}"
            )

        # Top-level exclude/match_style apply to branch and branches forms.
        # When using [repository.refs], these are read from that subtable
        # instead and top-level values are rejected as ambiguous.
        top_exclude = repo_config.get("exclude")
        top_match_style = repo_config.get("match_style")

        refs_include: Optional[List[str]] = None
        refs_exclude: List[str] = []
        match_style: MatchStyle = "fnmatch"

        if refs_table is not None:
            if top_exclude is not None:
                raise ValueError(
                    "'repository.exclude' cannot be used together with "
                    "'repository.refs'; put excludes inside [repository.refs] instead"
                )
            if top_match_style is not None:
                raise ValueError(
                    "'repository.match_style' cannot be used together "
                    "with 'repository.refs'; put match_style inside "
                    "[repository.refs] instead"
                )

            if not isinstance(refs_table, dict):
                raise ValueError("'repository.refs' must be a table")
            include = refs_table.get("include")
            if not include:
                raise ValueError("'repository.refs.include' must be a non-empty list")
            if not isinstance(include, list) or not all(
                isinstance(p, str) for p in include
            ):
                raise ValueError("'repository.refs.include' must be a list of strings")
            refs_include = [str(p) for p in include]

            exclude = refs_table.get("exclude", [])
            if exclude and (
                not isinstance(exclude, list)
                or not all(isinstance(p, str) for p in exclude)
            ):
                raise ValueError("'repository.refs.exclude' must be a list of strings")
            refs_exclude = [str(p) for p in exclude] if exclude else []

            style_raw = refs_table.get("match_style", "fnmatch")
            if style_raw not in ("fnmatch", "git"):
                raise ValueError(
                    f"Unknown 'repository.refs.match_style' {style_raw!r}; "
                    "expected 'fnmatch' or 'git'"
                )
            match_style = style_raw
        else:
            # Parse top-level exclude (works with branch / branches)
            if top_exclude is not None:
                if not isinstance(top_exclude, list) or not all(
                    isinstance(p, str) for p in top_exclude
                ):
                    raise ValueError("'repository.exclude' must be a list of strings")
                refs_exclude = [str(p) for p in top_exclude]

            if top_match_style is not None:
                if top_match_style not in ("fnmatch", "git"):
                    raise ValueError(
                        f"Unknown 'repository.match_style' {top_match_style!r}; "
                        "expected 'fnmatch' or 'git'"
                    )
                match_style = top_match_style

        normalized_branches: Optional[List[str]] = None
        if branches_list is not None:
            if not isinstance(branches_list, list) or not branches_list:
                raise ValueError(
                    "'repository.branches' must be a non-empty list of strings"
                )
            if not all(isinstance(b, str) for b in branches_list):
                raise ValueError("'repository.branches' entries must all be strings")
            normalized_branches = [str(b) for b in branches_list]

        return cls(
            daemon_name=daemon_config["name"],
            polling_interval=daemon_config.get("polling_interval", 300),
            repo_url=repo_config["url"],
            branch=branch_scalar if branch_scalar is not None else "main",
            branches=normalized_branches,
            refs_include=refs_include,
            refs_exclude=refs_exclude,
            match_style=match_style,
            github_token=repo_config.get("github_token"),
            workflow_file=slurm_config["workflow_file"],
            working_directory=slurm_config["working_directory"],
            slurm_options=slurm_config.get("slurm"),
        )

    def ref_patterns(self) -> RefPatternSet:
        """Build the :class:`RefPatternSet` corresponding to this config.

        Precedence: ``refs.include`` > ``branches`` > ``branch``. Exactly one
        of these is populated in practice, enforced by :meth:`from_dict`.
        Excludes are forwarded for all three forms.
        """
        if self.refs_include:
            return RefPatternSet.from_refs(
                include=self.refs_include,
                exclude=self.refs_exclude,
                match_style=self.match_style,
            )
        if self.branches:
            return RefPatternSet.from_branches(
                self.branches,
                exclude=self.refs_exclude,
                match_style=self.match_style,
            )
        return RefPatternSet.from_branch(
            self.branch,
            exclude=self.refs_exclude,
            match_style=self.match_style,
        )

    def branch_label(self) -> str:
        """Return a human-readable summary of the watched refs.

        Used for display in logs, the daemon status file, and the
        ``git_repos`` table. Legacy scalar configs return just the branch
        name so existing dashboards continue to display unchanged values.
        """
        if self.refs_include:
            label = ",".join(self.refs_include)
        elif self.branches:
            label = ",".join(self.branches)
        else:
            label = self.branch

        if self.refs_exclude:
            label = f"{label} !({','.join(self.refs_exclude)})"
        return label

    def validate(self) -> None:
        """Validate the configuration."""
        if self.polling_interval < 60:
            raise ValueError("Polling interval must be at least 60 seconds")

        if not self.repo_url.startswith(("https://github.com/", "git@github.com:")):
            raise ValueError("Only GitHub repositories are currently supported")

        # Materializing the pattern set validates match_style and the
        # include/exclude entries (non-empty, normalizable).
        self.ref_patterns()

    def get_repo_name(self) -> str:
        """Extract repository name from URL."""
        if self.repo_url.startswith("https://github.com/"):
            return self.repo_url.replace("https://github.com/", "").rstrip(".git")
        elif self.repo_url.startswith("git@github.com:"):
            return self.repo_url.replace("git@github.com:", "").rstrip(".git")
        else:
            raise ValueError(f"Cannot parse repository name from URL: {self.repo_url}")


def create_example_config(output_path: str) -> None:
    """Create an example configuration file."""
    example_config = {
        "daemon": {
            "name": "my-project-main",
            "polling_interval": 300,
        },
        "repository": {
            "url": "https://github.com/user/repo",
            "branch": "main",
            "github_token": "optional_for_private_repos",
        },
        "slurm-ci": {
            "workflow_file": "workflows/ci.yml",
            "working_directory": "/path/to/working-directory",
            "slurm": {
                "gres": "gpu:gfx942",
                "cpus-per-task": 32,
                "time": "12:00:00",
                "partition": "gpu",
            },
        },
    }

    output_file = Path(output_path)
    with open(output_file, "w") as f:
        toml.dump(example_config, f)

    print(f"Example configuration created at: {output_file}")
