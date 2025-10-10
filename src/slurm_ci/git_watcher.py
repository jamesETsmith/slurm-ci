#!/usr/bin/env python3
"""Git repository watcher for automatic CI triggering."""

import logging
import os
import requests
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .daemon_manager import DaemonManager
from .database import CommitTracker, GitRepo, SessionLocal, init_db
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
        logger.setLevel(logging.INFO)

        # Create file handler
        log_file = self.daemon_manager.get_log_file(self.config.daemon_name)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # Create console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

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
                existing_repo.config_dir = self.config.config_dir
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
                    config_dir=self.config.config_dir,
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

    def _get_github_api_url(self) -> str:
        """Get GitHub API URL for the repository."""
        repo_name = self.config.get_repo_name()
        return f"https://api.github.com/repos/{repo_name}/branches/{self.config.branch}"

    def _fetch_latest_commit(self) -> Optional[str]:
        """Fetch the latest commit SHA from GitHub API."""
        try:
            url = self._get_github_api_url()
            self.logger.debug(f"Fetching latest commit from: {url}")

            response = self.session.get(url, timeout=30)

            if response.status_code == 404:
                self.logger.error(
                    f"Repository or branch not found: "
                    f"{self.config.repo_url}#{self.config.branch}"
                )
                return None
            elif response.status_code == 403:
                self.logger.error("GitHub API rate limit exceeded or access denied")
                return None
            elif response.status_code != 200:
                self.logger.error(
                    f"GitHub API error: {response.status_code} - {response.text}"
                )
                return None

            data = response.json()
            commit_sha = data["commit"]["sha"]
            self.logger.debug(f"Latest commit SHA: {commit_sha}")
            return commit_sha

        except requests.exceptions.RequestException as e:
            self.logger.error(f"Error fetching latest commit: {e}")
            return None
        except (KeyError, ValueError) as e:
            self.logger.error(f"Error parsing GitHub API response: {e}")
            return None

    def _is_commit_processed(self, commit_sha: str) -> bool:
        """Check if a commit has already been processed."""
        session = SessionLocal()
        try:
            repo = (
                session.query(GitRepo)
                .filter(GitRepo.daemon_name == self.config.daemon_name)
                .first()
            )

            if not repo:
                return False

            tracker = (
                session.query(CommitTracker)
                .filter(
                    CommitTracker.repo_id == repo.id,
                    CommitTracker.commit_sha == commit_sha,
                )
                .first()
            )

            return tracker is not None
        finally:
            session.close()

    def _mark_commit_processed(
        self,
        commit_sha: str,
        build_triggered: bool = False,
        build_id: Optional[int] = None,
    ) -> None:
        """Mark a commit as processed in the database."""
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

            # Create commit tracker entry
            tracker = CommitTracker(
                repo_id=repo.id,
                commit_sha=commit_sha,
                build_triggered=build_triggered,
                build_id=build_id,
            )
            session.add(tracker)
            session.commit()

            self.logger.info(f"Marked commit as processed: {commit_sha}")
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error marking commit as processed: {e}")
        finally:
            session.close()

    def _clone_repository(self, commit_sha: str) -> Optional[str]:
        """Clone the repository at a specific commit to a temporary directory."""
        import tempfile

        try:
            # Create temporary directory for this clone
            temp_dir = tempfile.mkdtemp(prefix=f"slurm-ci-{self.config.daemon_name}-")
            self.logger.info(f"Cloning repository to temporary directory: {temp_dir}")

            # Clone the repository
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "--branch",
                    self.config.branch,
                    self.config.repo_url,
                    temp_dir,
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            # Checkout specific commit
            subprocess.run(
                ["git", "checkout", commit_sha],
                cwd=temp_dir,
                check=True,
                capture_output=True,
                text=True,
            )

            self.logger.info(f"Successfully cloned repository at commit: {commit_sha}")
            return temp_dir

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error cloning repository: {e}")
            self.logger.error(f"Command output: {e.stderr}")
            return None

    def _trigger_ci_job(self, commit_sha: str) -> bool:
        """Trigger a CI job for the given commit."""
        temp_dir = None
        try:
            # Clone repository to temporary directory
            temp_dir = self._clone_repository(commit_sha)
            if not temp_dir:
                return False

            # Construct workflow file path from config directory (not repo)
            workflow_file = Path(self.config.config_dir) / self.config.workflow_file
            if not workflow_file.exists():
                self.logger.error(
                    f"Workflow file not found in config dir: {workflow_file}"
                )
                return False

            self.logger.info(f"Triggering CI job for commit: {commit_sha}")
            self.logger.info(f"Workflow file: {workflow_file}")
            self.logger.info(f"Working directory: {temp_dir}")

            # Launch slurm jobs
            launch_slurm_jobs(str(workflow_file), temp_dir, dryrun=False)

            self.logger.info(f"Successfully triggered CI job for commit: {commit_sha}")
            return True

        except Exception as e:
            self.logger.error(f"Error triggering CI job: {e}")
            return False
        finally:
            # Note: We don't clean up the temporary directory here because
            # Slurm jobs run asynchronously and need access to the directory.
            # The cleanup will be handled by the Slurm job script itself.
            pass

    def _poll_once(self) -> None:
        """Perform one polling cycle."""
        self.logger.debug("Starting polling cycle")

        # Fetch latest commit
        latest_commit = self._fetch_latest_commit()
        if not latest_commit:
            self.logger.warning("Could not fetch latest commit")
            return

        # Check if commit has been processed
        if self._is_commit_processed(latest_commit):
            self.logger.debug(f"Commit already processed: {latest_commit}")
            return

        self.logger.info(f"New commit detected: {latest_commit}")

        # Trigger CI job
        job_triggered = self._trigger_ci_job(latest_commit)

        # Mark commit as processed
        self._mark_commit_processed(latest_commit, build_triggered=job_triggered)

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

        # Write PID file
        self.daemon_manager.write_pid_file(self.config.daemon_name, os.getpid())

        # Write initial status file
        self.daemon_manager.write_status_file(
            self.config.daemon_name, self.config, status="starting"
        )

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
