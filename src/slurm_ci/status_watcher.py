import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import toml
from sqlalchemy.orm import Session

from .config import STATUS_DIR
from .database import Build, Job, SessionLocal
from .slurm_utils import get_job_info_from_sacct, is_slurm_job_active


logger = logging.getLogger(__name__)


class StatusWatcher:
    """Watches the status directory and synchronizes TOML files with the database."""

    def __init__(self, status_dir: Optional[str] = None) -> None:
        self.status_dir = Path(status_dir or STATUS_DIR)
        self._processed_files = {}  # filename -> last_modified_time

    def scan_status_files(self) -> List[Path]:
        """Scan the status directory for TOML files."""
        if not self.status_dir.exists():
            return []

        return list(self.status_dir.glob("*.toml"))

    def read_status_file(self, file_path: Path) -> Optional[Dict]:
        """Read and parse a TOML status file."""
        try:
            with open(file_path, "r") as f:
                return toml.load(f)
        except (IOError, toml.TomlDecodeError) as e:
            logger.warning("Could not read status file %s: %s", file_path, e)
            return None

    def extract_build_info(self, status_data: Dict) -> Dict:
        """Extract build information from status data."""
        project = status_data.get("project", {})
        git = status_data.get("git", {})

        project_name = project.get("name", "unknown")
        commit_sha = git.get("commit", "unknown")
        branch = git.get("branch", "unknown")
        workflow_file = project.get("workflow_file", "")
        working_directory = project.get("working_directory", "")

        build_key = (
            f"{project_name}#{commit_sha}#{workflow_file}#{branch}#{working_directory}"
        )

        return {
            "build_key": build_key,
            "repo_full_name": project_name,
            "commit_sha": commit_sha,
            "branch": branch,
            "workflow_file": workflow_file,
            "working_directory": working_directory,
        }

    def extract_job_info(self, status_data: Dict, file_path: Path) -> Dict:
        """Extract job information from status data."""
        # Generate job name from matrix args
        matrix_args = status_data.get("matrix", {})
        job_name = (
            "_".join([f"{k}:{v}" for k, v in matrix_args.items()]) or file_path.stem
        )

        # Get slurm info
        slurm_info = status_data.get("slurm", {})
        job_id = slurm_info.get("job_id")

        # Query sacct for job state and exit code if job_id is available
        sacct_info = None
        if job_id is not None and job_id > 0:
            sacct_info = get_job_info_from_sacct(job_id)

        # Determine job status and exit code
        runtime = status_data.get("runtime", {})
        ci = status_data.get("ci", {})

        has_end_time = "end" in runtime
        runtime_exit_code = runtime.get("end", {}).get("exit_code")

        # Runtime data comes directly from the executed script and should be
        # treated as authoritative for terminal states when present.
        if has_end_time:
            status = "completed" if runtime_exit_code == 0 else "failed"
        else:
            status = "running" if "start_time" in runtime else "pending"
        exit_code = runtime_exit_code

        # When there is no runtime.end (the job script never finished
        # writing), use any previously-persisted slurm state already in the
        # TOML file as a fallback.  This prevents jobs from reverting to
        # "running" when sacct data expires on subsequent syncs.
        persisted_slurm_state = slurm_info.get("state")
        persisted_sacct_exit = slurm_info.get("sacct_exit_code")
        if not has_end_time and persisted_slurm_state:
            if persisted_slurm_state in ["COMPLETED"]:
                status = "completed"
                if persisted_sacct_exit is not None:
                    exit_code = persisted_sacct_exit
            elif (
                persisted_slurm_state
                in [
                    "FAILED",
                    "TIMEOUT",
                    "OUT_OF_MEMORY",
                ]
                or "CANCELLED" in persisted_slurm_state
            ):
                status = "failed"
                if persisted_sacct_exit is not None:
                    exit_code = persisted_sacct_exit

        # Update status file with sacct data if available
        if sacct_info:
            slurm_state = sacct_info.state
            sacct_exit_code = sacct_info.exit_code

            # Update the status file with sacct data
            if slurm_state:
                slurm_info["state"] = slurm_state
            if sacct_exit_code is not None:
                slurm_info["sacct_exit_code"] = sacct_exit_code

            # Write back atomically so a kill mid-write doesn't corrupt the file
            try:
                dir_ = str(file_path.parent)
                fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
                try:
                    with os.fdopen(fd, "w") as f:
                        toml.dump(status_data, f)
                    os.replace(tmp_path, str(file_path))
                except Exception:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
            except Exception as e:
                logger.warning("Could not update status file with sacct data: %s", e)

            # Use sacct data to refine status when available.
            if slurm_state:
                # Map SLURM states to our status
                if slurm_state in ["COMPLETED"]:
                    status = "completed"
                    if sacct_exit_code is not None:
                        exit_code = sacct_exit_code
                elif slurm_state in ["FAILED", "TIMEOUT", "OUT_OF_MEMORY", "CANCELLED"]:
                    status = "failed"
                    if sacct_exit_code is not None:
                        exit_code = sacct_exit_code
                elif slurm_state in ["RUNNING"]:
                    # Do not overwrite a terminal runtime state with a transient
                    # non-terminal scheduler state.
                    if not has_end_time:
                        status = "running"
                elif slurm_state in ["PENDING", "CONFIGURING"]:
                    # Submitted to Slurm but not yet allocated a node.
                    if not has_end_time:
                        status = "submitted"
                else:
                    # Unknown scheduler state: keep runtime-derived status.
                    pass

        # Extract timing information
        start_time = runtime.get("start_time")
        end_time = runtime.get("end", {}).get("time")

        return {
            "name": job_name,
            "status": status,
            "exit_code": exit_code,
            "matrix_args": json.dumps(matrix_args) if matrix_args else None,
            "log_file_path": ci.get("logfile_path"),
            "status_file_path": str(file_path),
            "start_time": datetime.fromtimestamp(start_time, tz=timezone.utc).replace(
                tzinfo=None
            )
            if start_time
            else None,
            "end_time": datetime.fromtimestamp(end_time, tz=timezone.utc).replace(
                tzinfo=None
            )
            if end_time
            else None,
            "created_at": datetime.fromtimestamp(start_time, tz=timezone.utc).replace(
                tzinfo=None
            )
            if start_time
            else datetime.now(timezone.utc).replace(tzinfo=None),
            "logs": None,  # Will be populated from log file if available
            "file_path": str(file_path),
        }

    def get_or_create_build(self, session: Session, build_info: Dict) -> Build:
        """Get existing build or create new one."""
        build = (
            session.query(Build)
            .filter(
                Build.repo_full_name == build_info["repo_full_name"],
                Build.commit_sha == build_info["commit_sha"],
                Build.workflow_file == build_info["workflow_file"],
                Build.branch == build_info["branch"],
                Build.working_directory == build_info["working_directory"],
            )
            .first()
        )

        if not build:
            build = Build(
                repo_full_name=build_info["repo_full_name"],
                commit_sha=build_info["commit_sha"],
                branch=build_info["branch"],
                workflow_file=build_info["workflow_file"],
                working_directory=build_info["working_directory"],
                event_type="manual",  # TODO: detect if it's from CI/webhook
                status="running",
            )
            session.add(build)
            session.commit()  # Commit to get the ID

        return build

    def sync_file_to_db(self, file_path: Path) -> bool:
        """Sync a single status file to the database."""
        status_data = self.read_status_file(file_path)
        if not status_data:
            return False

        session = SessionLocal()
        try:
            # Extract build information
            build_info = self.extract_build_info(status_data)
            build = self.get_or_create_build(session, build_info)

            # Extract job information
            job_info = self.extract_job_info(status_data, file_path)

            # Check if job already exists (based on build_id + name)
            existing_job = (
                session.query(Job)
                .filter(Job.build_id == build.id, Job.name == job_info["name"])
                .first()
            )

            if existing_job:
                # Check if the job status has changed by comparing actual status values
                should_update = (
                    existing_job.status != job_info["status"]
                    or existing_job.exit_code != job_info["exit_code"]
                    or existing_job.end_time != job_info["end_time"]
                )

                if not should_update:
                    logger.debug(
                        "Skipping update for job %s — no changes detected",
                        job_info["name"],
                    )

                if should_update:
                    existing_job.status = job_info["status"]
                    existing_job.exit_code = job_info["exit_code"]
                    existing_job.matrix_args = job_info["matrix_args"]
                    existing_job.log_file_path = job_info["log_file_path"]
                    existing_job.status_file_path = job_info["status_file_path"]
                    existing_job.start_time = job_info["start_time"]
                    existing_job.end_time = job_info["end_time"]
                    logger.info(
                        "Updated job %s -> %s", job_info["name"], job_info["status"]
                    )
            else:
                # Create new job
                job = Job(
                    build_id=build.id,
                    name=job_info["name"],
                    status=job_info["status"],
                    exit_code=job_info["exit_code"],
                    matrix_args=job_info["matrix_args"],
                    log_file_path=job_info["log_file_path"],
                    status_file_path=job_info["status_file_path"],
                    start_time=job_info["start_time"],
                    end_time=job_info["end_time"],
                    created_at=job_info["created_at"],
                    logs=job_info["logs"],
                )
                session.add(job)
                logger.info(
                    "Created job %s -> %s", job_info["name"], job_info["status"]
                )

            # Update build status and freshness timestamp
            self.update_build_status(session, build)
            build.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)  # ty: ignore[invalid-assignment]

            session.commit()
            return True

        except Exception as e:
            logger.error("Error syncing %s: %s", file_path, e)
            session.rollback()
            return False
        finally:
            session.close()

    def update_build_status(self, session: Session, build: Build) -> None:
        """Update build status based on its jobs.

        Status precedence (highest to lowest):
          failed > incomplete > running > submitted > completed > pending
        """
        # ty flags SQLAlchemy ORM attribute assignment as invalid because the
        # mapped types are exposed as Column[Unknown]; these writes are correct.
        terminal = {"completed", "failed", "incomplete"}
        jobs = session.query(Job).filter(Job.build_id == build.id).all()

        if not jobs:
            build.status = "pending"  # ty: ignore[invalid-assignment]
        elif all(job.status in terminal for job in jobs):
            statuses = {job.status for job in jobs}
            if statuses == {"completed"}:
                build.status = "completed"  # ty: ignore[invalid-assignment]
            elif "failed" in statuses:
                build.status = "failed"  # ty: ignore[invalid-assignment]
            else:
                build.status = "incomplete"  # ty: ignore[invalid-assignment]
        elif any(job.status == "running" for job in jobs):
            build.status = "running"  # ty: ignore[invalid-assignment]
        elif any(job.status == "submitted" for job in jobs):
            build.status = "submitted"  # ty: ignore[invalid-assignment]
        else:
            build.status = "running"  # ty: ignore[invalid-assignment]

    def reap_incomplete_jobs(self, stale_threshold_s: float = 3600) -> int:
        """Mark running/pending jobs as incomplete when their Slurm job is gone.

        For jobs with a Slurm job ID: checks sacct and marks incomplete if the
        scheduler says the job is no longer active.

        For jobs *without* a Slurm job ID (local runs, test runs): marks
        incomplete if they have been in a non-terminal state longer than
        ``stale_threshold_s`` seconds (default 1 hour) with no runtime.end.

        Returns the number of jobs reaped.
        """
        session = SessionLocal()
        reaped = 0
        now_ts = time.time()
        try:
            stale_jobs = (
                session.query(Job)
                .filter(Job.status.in_(["running", "submitted", "pending"]))
                .all()
            )

            for job in stale_jobs:
                if not job.status_file_path:
                    continue

                status_data = self.read_status_file(Path(str(job.status_file_path)))
                if status_data is None:
                    continue

                runtime = status_data.get("runtime", {})
                if "end" in runtime:
                    continue

                slurm_job_id = status_data.get("slurm", {}).get("job_id")

                if slurm_job_id is not None and slurm_job_id > 0:
                    active = is_slurm_job_active(slurm_job_id)
                    if active is None or active:
                        continue
                    job.status = "incomplete"  # ty: ignore[invalid-assignment]
                    logger.info(
                        "Reaped job %s (slurm %s): marked incomplete",
                        job.name,
                        slurm_job_id,
                    )
                else:
                    start_time = runtime.get("start_time")
                    if start_time is None:
                        continue
                    elapsed = now_ts - float(start_time)
                    if elapsed < stale_threshold_s:
                        continue
                    job.status = "incomplete"  # ty: ignore[invalid-assignment]
                    logger.info(
                        "Reaped job %s (no slurm id, stale %.0fs): marked incomplete",
                        job.name,
                        elapsed,
                    )

                reaped += 1

            if reaped:
                build_ids = {j.build_id for j in stale_jobs if j.status == "incomplete"}
                for build_id in build_ids:
                    build = session.query(Build).filter(Build.id == build_id).first()
                    if build:
                        self.update_build_status(session, build)

                session.commit()
                logger.info("Reaped %d incomplete job(s)", reaped)
        except Exception as e:
            logger.error("Error during incomplete-job reap: %s", e)
            session.rollback()
        finally:
            session.close()

        return reaped

    def sync_all_files(self) -> int:
        """Sync all status files to the database."""
        files = self.scan_status_files()
        synced_count = 0

        for file_path in files:
            if self.sync_file_to_db(file_path):
                synced_count += 1
                self._processed_files[str(file_path)] = file_path.stat().st_mtime

        logger.info("Synced %d/%d status files to database", synced_count, len(files))
        return synced_count

    def watch_directory(
        self,
        poll_interval: int = 30,
        sync_on_start: bool = True,
        reap_interval: int = 120,
    ) -> None:
        """Watch the status directory for changes and sync to database.

        Args:
            poll_interval: Seconds between file-change polls.
            sync_on_start: Run a full sync before entering the loop.
            reap_interval: Seconds between incomplete-job reap passes.
        """
        logger.info("Watching status directory: %s", self.status_dir)

        if sync_on_start:
            logger.info("Performing initial sync...")
            self.sync_all_files()

        last_reap_time = time.monotonic()

        try:
            while True:
                files = self.scan_status_files()
                updated_files = []

                for file_path in files:
                    file_str = str(file_path)
                    current_mtime = file_path.stat().st_mtime

                    if (
                        file_str not in self._processed_files
                        or current_mtime > self._processed_files[file_str]
                    ):
                        updated_files.append(file_path)

                for file_path in updated_files:
                    if self.sync_file_to_db(file_path):
                        self._processed_files[str(file_path)] = (
                            file_path.stat().st_mtime
                        )

                if updated_files:
                    logger.info("Processed %d updated file(s)", len(updated_files))

                now = time.monotonic()
                if now - last_reap_time >= reap_interval:
                    self.reap_incomplete_jobs()
                    last_reap_time = now

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Status watcher stopped")


def sync_status_to_db(status_dir: Optional[str] = None) -> int:
    """One-time sync of all status files to database."""
    watcher = StatusWatcher(status_dir)
    return watcher.sync_all_files()


def start_status_watcher(
    status_dir: Optional[str] = None, poll_interval: int = 30
) -> None:
    """Start the status directory watcher."""
    watcher = StatusWatcher(status_dir)
    watcher.watch_directory(poll_interval)
