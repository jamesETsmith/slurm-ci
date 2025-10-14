#!/usr/bin/env python3
"""Git repository watcher for automatic CI triggering."""

import logging
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import toml

from .daemon_manager import DaemonManager
from .database import CommitTracker, CommitStatus, GitRepo, SessionLocal, init_db
from .git_watch_config import GitWatchConfig
from .slurm_launcher import launch_slurm_jobs


class GitHubAPIError(Exception):
    """Exception raised for GitHub API errors."""

    pass


class GitWatcher:
    """Watches a Git repository for new commits and triggers CI jobs."""

    def __init__(self, config: GitWatchConfig) -> None:
        self.config = config
        self.daemon_manager = DaemonManager()
        self.logger = self._setup_logging()
        self.session = requests.Session()

        # Set up GitHub API headers
        if config.github_token:
            self.session.headers.update(
                {
                    "Authorization": f"token {config.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                }
            )

        # Validate configuration
        config.validate()

        # Set up database
        self._setup_database()

    def _setup_logging(self) -> logging.Logger:
        """Set up logging for the daemon."""
        logger = logging.getLogger(f"git-watch-{self.config.daemon_name}")
        logger.setLevel(logging.DEBUG)

        # Create file handler
        log_file = self.daemon_manager.get_log_file(self.config.daemon_name)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)

        # Create formatter
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        # Add handlers to logger
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

        return logger

    def _setup_database(self) -> None:
        """Set up database entry for this git repository."""
        session = SessionLocal()
        try:
            # Check if repo already exists
            existing_repo = (
                session.query(GitRepo)
                .filter(GitRepo.daemon_name == self.config.daemon_name)
                .first()
            )

            if existing_repo:
                # Update existing repo
                existing_repo.repo_url = self.config.repo_url
                existing_repo.branch = self.config.branch
                existing_repo.workflow_file = self.config.workflow_file
                existing_repo.working_directory = self.config.working_directory
                existing_repo.polling_interval = self.config.polling_interval
                existing_repo.is_active = True
                existing_repo.updated_at = datetime.utcnow()
                self.logger.info(
                    f"Updated existing repo entry: {self.config.daemon_name}"
                )
            else:
                # Create new repo entry
                new_repo = GitRepo(
                    daemon_name=self.config.daemon_name,
                    repo_url=self.config.repo_url,
                    branch=self.config.branch,
                    workflow_file=self.config.workflow_file,
                    working_directory=self.config.working_directory,
                    polling_interval=self.config.polling_interval,
                    is_active=True,
                )
                session.add(new_repo)
                self.logger.info(f"Created new repo entry: {self.config.daemon_name}")

            session.commit()
        except Exception as e:
            session.rollback()
            # Check if this is a "no such table" error
            if "no such table" in str(e):
                self.logger.info("Database tables not found, initializing database...")
                session.close()  # Close current session before init
                try:
                    init_db()
                    self.logger.info("Database initialized successfully")
                    # Retry the setup after initialization
                    self._setup_database()
                    return
                except Exception as init_error:
                    self.logger.error(f"Failed to initialize database: {init_error}")
                    raise init_error
            else:
                self.logger.error(f"Error setting up database: {e}")
                raise
        finally:
            session.close()

    def _fetch_latest_commit(self) -> Optional[str]:
        """Fetch the latest commit SHA from GitHub API."""
        try:
            commit_hash = subprocess.check_output(
                ["git", "ls-remote", self.config.repo_url, self.config.branch]
            )
            return commit_hash.decode("utf-8").split("\t")[0]
        except Exception as e:
            self.logger.error(f"Error fetching latest commit: {e}")
            return None

    def _should_process_commit(self, commit_sha: str) -> bool:
        """Check if a commit should be processed based on its current status."""
        session = SessionLocal()
        try:
            repo = (
                session.query(GitRepo)
                .filter(GitRepo.daemon_name == self.config.daemon_name)
                .first()
            )

            if not repo:
                self.logger.info(
                    f"Repository not found, will process commit: {commit_sha}"
                )
                return True

            tracker = (
                session.query(CommitTracker)
                .filter(
                    CommitTracker.repo_id == repo.id,
                    CommitTracker.commit_sha == commit_sha,
                )
                .first()
            )

            if not tracker:
                self.logger.info(f"New commit detected, will process: {commit_sha}")
                return True

            # Check status to determine if we should process
            status = tracker.status
            self.logger.info(f"Commit {commit_sha} has status: {status}")

            if status in [CommitStatus.PENDING.value, CommitStatus.EXCEPTION.value]:
                self.logger.info(
                    f"Commit {commit_sha} should be processed (status: {status})"
                )
                return True
            elif status in [
                CommitStatus.RUNNING.value,
                CommitStatus.COMPLETED.value,
                CommitStatus.FAILED.value,
            ]:
                self.logger.info(
                    f"Commit {commit_sha} should NOT be processed (status: {status})"
                )
                return False
            else:
                self.logger.warning(
                    f"Unknown status {status} for commit {commit_sha}, will process"
                )
                return True

        finally:
            session.close()

    def _update_commit_status(
        self,
        commit_sha: str,
        status: CommitStatus,
        build_triggered: bool = False,
        build_id: Optional[int] = None,
    ) -> None:
        """Update commit status in the database."""
        session = SessionLocal()
        try:
            repo = (
                session.query(GitRepo)
                .filter(GitRepo.daemon_name == self.config.daemon_name)
                .first()
            )

            if not repo:
                self.logger.error("Repository not found in database")
                return

            # Update repo's last commit
            repo.last_commit_sha = commit_sha
            repo.last_checked_at = datetime.utcnow()

            # Check if tracker already exists
            tracker = (
                session.query(CommitTracker)
                .filter(
                    CommitTracker.repo_id == repo.id,
                    CommitTracker.commit_sha == commit_sha,
                )
                .first()
            )

            if tracker:
                # Update existing tracker
                tracker.status = status.value
                tracker.build_triggered = build_triggered
                if build_id:
                    tracker.build_id = build_id
                tracker.last_updated = datetime.utcnow()
                self.logger.info(
                    f"Updated commit {commit_sha} status to: {status.value}"
                )
            else:
                # Create new tracker entry
                tracker = CommitTracker(
                    repo_id=repo.id,
                    commit_sha=commit_sha,
                    build_triggered=build_triggered,
                    build_id=build_id,
                    status=status.value,
                )
                session.add(tracker)
                self.logger.info(
                    f"Created new commit tracker for {commit_sha} "
                    f"with status: {status.value}"
                )

            session.commit()

        except Exception as e:
            session.rollback()
            self.logger.error(f"Error updating commit status: {e}")
        finally:
            session.close()

    def _check_running_jobs(self) -> None:
        """Check status of running jobs and update commit status accordingly."""
        session = SessionLocal()
        try:
            repo = (
                session.query(GitRepo)
                .filter(GitRepo.daemon_name == self.config.daemon_name)
                .first()
            )

            if not repo:
                return

            # Get all running commits
            running_commits = (
                session.query(CommitTracker)
                .filter(
                    CommitTracker.repo_id == repo.id,
                    CommitTracker.status == CommitStatus.RUNNING.value,
                )
                .all()
            )

            for tracker in running_commits:
                commit_sha = tracker.commit_sha
                self.logger.debug(f"Checking status of running commit: {commit_sha}")

                # Look for status files related to this commit
                status_files = self._find_status_files_for_commit(commit_sha)

                if not status_files:
                    self.logger.debug(f"No status files found for commit {commit_sha}")
                    continue

                # Check if all jobs are complete
                all_complete = True
                any_failed = False
                any_exception = False

                for status_file in status_files:
                    try:
                        with open(status_file, "r") as f:
                            status_data = toml.load(f)

                        runtime = status_data.get("runtime", {})
                        if "end" not in runtime:
                            # Job still running
                            all_complete = False
                            break

                        exit_code = runtime.get("exit_code")
                        if exit_code is None:
                            # Corrupted status file
                            any_exception = True
                        elif exit_code != 0:
                            any_failed = True

                    except Exception as e:
                        self.logger.warning(
                            f"Error reading status file {status_file}: {e}"
                        )
                        any_exception = True

                if all_complete:
                    if any_exception:
                        new_status = CommitStatus.EXCEPTION
                        self.logger.info(
                            f"Commit {commit_sha} completed with exceptions, will retry"
                        )
                    elif any_failed:
                        new_status = CommitStatus.FAILED
                        self.logger.info(f"Commit {commit_sha} completed with failures")
                    else:
                        new_status = CommitStatus.COMPLETED
                        self.logger.info(f"Commit {commit_sha} completed successfully")

                    self._update_commit_status(commit_sha, new_status)

        except Exception as e:
            self.logger.error(f"Error checking running jobs: {e}")
        finally:
            session.close()

    def _find_status_files_for_commit(self, commit_sha: str) -> list:
        """Find all status files related to a specific commit."""
        from .config import STATUS_DIR

        status_files = []
        status_dir = Path(STATUS_DIR)

        if not status_dir.exists():
            return status_files

        # Look through all .toml files in status directory
        for status_file in status_dir.glob("*.toml"):
            try:
                with open(status_file, "r") as f:
                    status_data = toml.load(f)

                git_info = status_data.get("git", {})
                if git_info.get("commit", "").startswith(
                    commit_sha[:8]
                ):  # Match first 8 chars
                    status_files.append(status_file)

            except Exception as e:
                self.logger.debug(f"Error reading status file {status_file}: {e}")
                continue

        return status_files

    def _trigger_ci_job(self, commit_sha: str) -> bool:
        """Trigger a CI job for the given commit."""
        try:
            # Construct workflow file path from config directory (not repo)
            workflow_file = Path(self.config.workflow_file)
            if not workflow_file.exists():
                self.logger.error(
                    f"Workflow file not found in config dir: {workflow_file}"
                )
                return False

            # Prepare git repository information for SLURM jobs
            git_repo = {
                "url": self.config.repo_url,
                "branch": self.config.branch,
                "commit_sha": commit_sha,
            }

            self.logger.info(f"Triggering CI job for commit: {commit_sha}")
            self.logger.info(f"Workflow file: {workflow_file}")
            self.logger.info(f"Repository: {self.config.repo_url}")
            self.logger.info(f"Branch: {self.config.branch}")

            # Launch slurm jobs with git repository info
            # Use a placeholder working directory since the actual repo will be
            # cloned on compute nodes
            launch_slurm_jobs(
                str(workflow_file),
                self.config.working_directory,
                dryrun=False,
                git_repo=git_repo,
                git_repo_url=self.config.repo_url,
                git_repo_branch=self.config.branch,
                custom_sbatch_options=self.config.slurm_options,
            )

            self.logger.info(f"Successfully triggered CI job for commit: {commit_sha}")
            return True

        except Exception as e:
            self.logger.error(f"Error triggering CI job: {e}")
            return False

    def _poll_once(self) -> None:
        """Perform one polling cycle."""
        self.logger.debug("Starting polling cycle")

        # First, check status of any running jobs
        self._check_running_jobs()

        # Fetch latest commit
        latest_commit = self._fetch_latest_commit()
        if not latest_commit:
            self.logger.warning("Could not fetch latest commit")
            return

        # Check if commit should be processed
        if not self._should_process_commit(latest_commit):
            self.logger.debug(f"Commit should not be processed: {latest_commit}")
            return

        self.logger.info(f"Processing commit: {latest_commit}")

        # Mark commit as running before triggering job
        self._update_commit_status(
            latest_commit, CommitStatus.RUNNING, build_triggered=True
        )

        # Trigger CI job
        job_triggered = self._trigger_ci_job(latest_commit)

        if not job_triggered:
            # If job failed to trigger, mark as exception for retry
            self._update_commit_status(
                latest_commit, CommitStatus.EXCEPTION, build_triggered=False
            )
            self.logger.error(
                f"Failed to trigger job for commit {latest_commit}, marked as exception"
            )

        # Update status file
        self.daemon_manager.write_status_file(
            self.config.daemon_name,
            self.config,
            status="running",
            last_check=datetime.now(),
            last_commit=latest_commit,
        )

    def run(self) -> None:
        """Run the git watcher daemon."""
        self.logger.info(f"Starting git-watch daemon: {self.config.daemon_name}")
        self.logger.info(f"Repository: {self.config.repo_url}")
        self.logger.info(f"Branch: {self.config.branch}")
        self.logger.info(f"Polling interval: {self.config.polling_interval} seconds")

        # Set up signal handlers
        self.daemon_manager.setup_signal_handlers(self.config.daemon_name)
        self.logger.info(f"Signal handlers setup for {self.config.daemon_name}")

        # Write PID file
        self.daemon_manager.write_pid_file(self.config.daemon_name, os.getpid())
        self.logger.info(f"PID file written for {self.config.daemon_name}")

        # Write initial status file
        self.daemon_manager.write_status_file(
            self.config.daemon_name, self.config, status="starting"
        )
        self.logger.info(f"Status file written for {self.config.daemon_name}")

        try:
            while True:
                try:
                    self._poll_once()
                except Exception as e:
                    self.logger.error(f"Error in polling cycle: {e}")

                self.logger.debug(
                    f"Sleeping for {self.config.polling_interval} seconds"
                )
                time.sleep(self.config.polling_interval)

        except KeyboardInterrupt:
            self.logger.info("Received interrupt signal, shutting down...")
        except Exception as e:
            self.logger.error(f"Unexpected error in daemon: {e}")
        finally:
            # Clean up
            self.daemon_manager.cleanup_daemon_files(self.config.daemon_name)
            self.logger.info("Git-watch daemon stopped")


def start_git_watcher(config_file: str) -> None:
    """Start a git-watch daemon from a configuration file."""
    try:
        config = GitWatchConfig.from_file(config_file)
        watcher = GitWatcher(config)
        watcher.run()
    except Exception as e:
        print(f"Error starting git-watch daemon: {e}")
        exit(1)
