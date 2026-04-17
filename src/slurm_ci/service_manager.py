#!/usr/bin/env python3
"""Service management for local slurm-ci support services."""

import json
import os
import signal
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import psutil

from .config import SLURM_CI_DIR


class ServiceManager:
    """Manages background support services for local development."""

    def __init__(self, base_dir: Optional[Path] = None) -> None:
        resolved_base_dir = base_dir or (SLURM_CI_DIR / "services")
        self.base_dir = resolved_base_dir
        self.pids_dir = self.base_dir / "pids"
        self.status_dir = self.base_dir / "status"
        self.logs_dir = self.base_dir / "logs"

        for directory in [self.pids_dir, self.status_dir, self.logs_dir]:
            directory.mkdir(parents=True, exist_ok=True)

    def get_pid_file(self, service_name: str) -> Path:
        """Get the PID file path for a service."""
        return self.pids_dir / f"{service_name}.pid"

    def get_status_file(self, service_name: str) -> Path:
        """Get the status file path for a service."""
        return self.status_dir / f"{service_name}.status"

    def get_log_file(self, service_name: str) -> Path:
        """Get the log file path for a service."""
        return self.logs_dir / f"{service_name}.log"

    def write_pid_file(self, service_name: str, pid: int) -> None:
        """Write PID to file."""
        pid_file = self.get_pid_file(service_name)
        with open(pid_file, "w") as file_handle:
            file_handle.write(str(pid))

    def read_pid_file(self, service_name: str) -> Optional[int]:
        """Read PID from file."""
        pid_file = self.get_pid_file(service_name)
        if not pid_file.exists():
            return None

        try:
            with open(pid_file, "r") as file_handle:
                return int(file_handle.read().strip())
        except (ValueError, IOError):
            return None

    def remove_pid_file(self, service_name: str) -> None:
        """Remove PID file."""
        pid_file = self.get_pid_file(service_name)
        if pid_file.exists():
            pid_file.unlink()

    def write_status_file(
        self,
        service_name: str,
        pid: int,
        command: list[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Write service status information to file."""
        status_file = self.get_status_file(service_name)
        status_data = {
            "service_name": service_name,
            "status": "running",
            "pid": pid,
            "started_at": datetime.now().isoformat(),
            "command": command,
            "metadata": metadata or {},
            "log_file": str(self.get_log_file(service_name)),
        }

        with open(status_file, "w") as file_handle:
            json.dump(status_data, file_handle, indent=2)

    def read_status_file(self, service_name: str) -> Optional[dict[str, Any]]:
        """Read service status information from file."""
        status_file = self.get_status_file(service_name)
        if not status_file.exists():
            return None

        try:
            with open(status_file, "r") as file_handle:
                return json.load(file_handle)
        except (json.JSONDecodeError, IOError):
            return None

    def remove_status_file(self, service_name: str) -> None:
        """Remove status file."""
        status_file = self.get_status_file(service_name)
        if status_file.exists():
            status_file.unlink()

    def cleanup_service_files(self, service_name: str) -> None:
        """Clean up PID and status files for a service."""
        self.remove_pid_file(service_name)
        self.remove_status_file(service_name)

    def is_service_running(self, service_name: str) -> bool:
        """Check if a service process is currently running."""
        pid = self.read_pid_file(service_name)
        if pid is None:
            return False

        try:
            process = psutil.Process(pid)
            if process.is_running():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        self.cleanup_service_files(service_name)
        return False

    def start_service(
        self,
        service_name: str,
        command: list[str],
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str]:
        """Start a service if not already running."""
        if self.is_service_running(service_name):
            return False, "already-running"

        log_file = self.get_log_file(service_name)
        with open(log_file, "a") as log_handle:
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        self.write_pid_file(service_name, process.pid)
        self.write_status_file(service_name, process.pid, command, metadata=metadata)
        return True, "started"

    def stop_service(
        self, service_name: str, timeout: int = 30, force: bool = False
    ) -> bool:
        """Stop a service gracefully."""
        pid = self.read_pid_file(service_name)
        if pid is None:
            return False

        try:
            process = psutil.Process(pid)
            if not process.is_running():
                self.cleanup_service_files(service_name)
                return True

            try:
                pgid = os.getpgid(pid)
            except OSError:
                pgid = None

            if pgid and pgid == pid:
                os.killpg(pgid, signal.SIGTERM)
            else:
                process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=timeout)
            except psutil.TimeoutExpired:
                if not force:
                    return False
                if pgid and pgid == pid:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    process.send_signal(signal.SIGKILL)
                process.wait(timeout=5)

            self.cleanup_service_files(service_name)
            return True

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self.cleanup_service_files(service_name)
            return False

    def list_services(self, expected_services: list[str]) -> list[dict[str, Any]]:
        """List service states for a set of expected service names."""
        service_rows: list[dict[str, Any]] = []

        for service_name in expected_services:
            running = self.is_service_running(service_name)
            status_data = self.read_status_file(service_name) or {}
            pid = self.read_pid_file(service_name)
            service_rows.append(
                {
                    "service_name": service_name,
                    "running": running,
                    "pid": pid,
                    "started_at": status_data.get("started_at"),
                    "metadata": status_data.get("metadata", {}),
                    "log_file": str(self.get_log_file(service_name)),
                }
            )

        return service_rows
