#!/usr/bin/env python3
"""Daemon management for git-watch processes."""

import json
import os
import signal
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Dict, List, Optional

import psutil

from .git_watch_config import GitWatchConfig


class DaemonManager:
    """Manages git-watch daemon processes."""

    def __init__(self) -> None:
        self.base_dir = Path.home() / ".slurm-ci" / "git-watch"
        self.pids_dir = self.base_dir / "pids"
        self.status_dir = self.base_dir / "status"
        self.logs_dir = self.base_dir / "logs"

        # Create directories
        for directory in [self.pids_dir, self.status_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def get_pid_file(self, daemon_name: str) -> Path:
        """Get the PID file path for a daemon."""
        return self.pids_dir / f"{daemon_name}.pid"

    def get_status_file(self, daemon_name: str) -> Path:
        """Get the status file path for a daemon."""
        return self.status_dir / f"{daemon_name}.status"

    def get_log_file(self, daemon_name: str) -> Path:
        """Get the log file path for a daemon."""
        return self.logs_dir / f"{daemon_name}.log"

    def write_pid_file(self, daemon_name: str, pid: int) -> None:
        """Write PID to file."""
        pid_file = self.get_pid_file(daemon_name)
        with open(pid_file, "w") as f:
            f.write(str(pid))

    def read_pid_file(self, daemon_name: str) -> Optional[int]:
        """Read PID from file."""
        pid_file = self.get_pid_file(daemon_name)
        if not pid_file.exists():
            return None

        try:
            with open(pid_file, "r") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None

    def remove_pid_file(self, daemon_name: str) -> None:
        """Remove PID file."""
        pid_file = self.get_pid_file(daemon_name)
        if pid_file.exists():
            pid_file.unlink()

    def write_status_file(
        self,
        daemon_name: str,
        config: GitWatchConfig,
        status: str = "running",
        last_check: Optional[datetime] = None,
        last_commit: Optional[str] = None,
    ) -> None:
        """Write status information to file."""
        status_file = self.get_status_file(daemon_name)
        status_data = {
            "daemon_name": daemon_name,
            "status": status,
            "pid": os.getpid(),
            "started_at": datetime.now().isoformat(),
            "last_check": last_check.isoformat() if last_check else None,
            "last_commit": last_commit,
            "config": {
                "repo_url": config.repo_url,
                "branch": config.branch,
                "polling_interval": config.polling_interval,
                "workflow_file": config.workflow_file,
                "working_directory": config.working_directory,
            },
        }

        with open(status_file, "w") as f:
            json.dump(status_data, f, indent=2)

    def read_status_file(self, daemon_name: str) -> Optional[Dict]:
        """Read status information from file."""
        status_file = self.get_status_file(daemon_name)
        if not status_file.exists():
            return None

        try:
            with open(status_file, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def remove_status_file(self, daemon_name: str) -> None:
        """Remove status file."""
        status_file = self.get_status_file(daemon_name)
        if status_file.exists():
            status_file.unlink()

    def is_daemon_running(self, daemon_name: str) -> bool:
        """Check if a daemon is currently running."""
        pid = self.read_pid_file(daemon_name)
        if pid is None:
            return False

        try:
            # Check if process exists and is still running
            process = psutil.Process(pid)
            return process.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Process doesn't exist or we can't access it
            self.cleanup_daemon_files(daemon_name)
            return False

    def stop_daemon(self, daemon_name: str, timeout: int = 30) -> bool:
        """Stop a daemon gracefully."""
        pid = self.read_pid_file(daemon_name)
        if pid is None:
            print(f"No PID file found for daemon: {daemon_name}")
            return False

        try:
            process = psutil.Process(pid)
            if not process.is_running():
                print(f"Daemon {daemon_name} is not running")
                self.cleanup_daemon_files(daemon_name)
                return True

            print(f"Stopping daemon {daemon_name} (PID: {pid})...")

            # Try graceful shutdown first
            process.send_signal(signal.SIGTERM)

            # Wait for process to terminate
            try:
                process.wait(timeout=timeout)
                print(f"Daemon {daemon_name} stopped gracefully")
            except psutil.TimeoutExpired:
                print(
                    f"Daemon {daemon_name} did not stop gracefully, "
                    "forcing termination..."
                )
                process.send_signal(signal.SIGKILL)
                process.wait(timeout=5)
                print(f"Daemon {daemon_name} forcefully terminated")

            self.cleanup_daemon_files(daemon_name)
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            print(f"Error stopping daemon {daemon_name}: {e}")
            self.cleanup_daemon_files(daemon_name)
            return False

    def cleanup_daemon_files(self, daemon_name: str) -> None:
        """Clean up daemon files (PID and status)."""
        self.remove_pid_file(daemon_name)
        self.remove_status_file(daemon_name)

    def list_running_daemons(self) -> List[Dict]:
        """List all running git-watch daemons."""
        running_daemons = []

        for pid_file in self.pids_dir.glob("*.pid"):
            daemon_name = pid_file.stem

            if self.is_daemon_running(daemon_name):
                status_data = self.read_status_file(daemon_name)
                if status_data:
                    running_daemons.append(status_data)
                else:
                    # Create minimal status if status file is missing
                    pid = self.read_pid_file(daemon_name)
                    running_daemons.append(
                        {
                            "daemon_name": daemon_name,
                            "status": "running",
                            "pid": pid,
                            "started_at": "unknown",
                            "config": {},
                        }
                    )

        return running_daemons

    def stop_all_daemons(self, timeout: int = 30) -> int:
        """Stop all running git-watch daemons."""
        running_daemons = self.list_running_daemons()
        stopped_count = 0

        for daemon_info in running_daemons:
            daemon_name = daemon_info["daemon_name"]
            if self.stop_daemon(daemon_name, timeout):
                stopped_count += 1

        return stopped_count

    def setup_signal_handlers(self, daemon_name: str) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum: int, frame: Optional[FrameType]) -> None:
            print(f"\nReceived signal {signum}, shutting down daemon {daemon_name}...")
            self.cleanup_daemon_files(daemon_name)
            exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)
