"""Tests for database.py module."""

import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from slurm_ci.database import (
    Base,
    Build,
    CommitStatus,
    CommitTracker,
    GitRepo,
    Job,
    init_db,
)


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    # Create a temporary database
    temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_url = f"sqlite:///{temp_db.name}"

    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    yield session

    session.close()
    engine.dispose()
    Path(temp_db.name).unlink()


class TestCommitStatus:
    """Tests for CommitStatus enum."""

    def test_enum_values(self) -> None:
        """Test CommitStatus enum values."""
        assert CommitStatus.PENDING.value == "pending"
        assert CommitStatus.RUNNING.value == "running"
        assert CommitStatus.COMPLETED.value == "completed"
        assert CommitStatus.FAILED.value == "failed"
        assert CommitStatus.EXCEPTION.value == "exception"


class TestBuild:
    """Tests for Build model."""

    def test_create_build(self, test_db) -> None:
        """Test creating a Build entry."""
        build = Build(
            repo_full_name="user/repo",
            commit_sha="abc123",
            branch="main",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
            event_type="push",
            status="pending",
        )

        test_db.add(build)
        test_db.commit()

        # Query back
        result = test_db.query(Build).filter(Build.commit_sha == "abc123").first()
        assert result is not None
        assert result.repo_full_name == "user/repo"
        assert result.branch == "main"
        assert result.status == "pending"

    def test_build_with_jobs(self, test_db) -> None:
        """Test Build with associated Jobs."""
        build = Build(
            repo_full_name="user/repo",
            commit_sha="xyz789",
            branch="develop",
            workflow_file="workflows/test.yml",
            working_directory="/tmp/work",
            event_type="pull_request",
        )
        test_db.add(build)
        test_db.commit()

        # Add jobs to build
        job1 = Job(
            build_id=build.id,
            name="test-job-1",
            status="running",
            matrix_args='{"python": "3.9"}',
        )
        job2 = Job(
            build_id=build.id,
            name="test-job-2",
            status="pending",
            matrix_args='{"python": "3.10"}',
        )

        test_db.add_all([job1, job2])
        test_db.commit()

        # Query build with jobs
        result = test_db.query(Build).filter(Build.id == build.id).first()
        assert len(result.jobs) == 2
        assert result.jobs[0].name == "test-job-1"
        assert result.jobs[1].name == "test-job-2"


class TestJob:
    """Tests for Job model."""

    def test_create_job(self, test_db) -> None:
        """Test creating a Job entry."""
        build = Build(
            repo_full_name="user/repo",
            commit_sha="job_test",
            branch="main",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(build)
        test_db.commit()

        job = Job(
            build_id=build.id,
            name="test-job",
            status="completed",
            exit_code=0,
            logs="Job completed successfully",
            matrix_args='{"os": "ubuntu-latest"}',
            log_file_path="/path/to/log.txt",
            status_file_path="/path/to/status.toml",
        )

        test_db.add(job)
        test_db.commit()

        # Query back
        result = test_db.query(Job).filter(Job.name == "test-job").first()
        assert result is not None
        assert result.status == "completed"
        assert result.exit_code == 0
        assert result.logs == "Job completed successfully"

    def test_job_timestamps(self, test_db) -> None:
        """Test job timestamps."""
        build = Build(
            repo_full_name="user/repo",
            commit_sha="timestamp_test",
            branch="main",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(build)
        test_db.commit()

        start = datetime.utcnow()
        job = Job(
            build_id=build.id,
            name="timestamp-job",
            start_time=start,
        )
        test_db.add(job)
        test_db.commit()

        result = test_db.query(Job).filter(Job.name == "timestamp-job").first()
        assert result.start_time is not None
        assert result.created_at is not None


class TestGitRepo:
    """Tests for GitRepo model."""

    def test_create_git_repo(self, test_db) -> None:
        """Test creating a GitRepo entry."""
        repo = GitRepo(
            daemon_name="test-daemon",
            repo_url="https://github.com/user/repo",
            branch="main",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
            polling_interval=300,
            is_active=True,
        )

        test_db.add(repo)
        test_db.commit()

        # Query back
        result = (
            test_db.query(GitRepo).filter(GitRepo.daemon_name == "test-daemon").first()
        )
        assert result is not None
        assert result.repo_url == "https://github.com/user/repo"
        assert result.branch == "main"
        assert result.polling_interval == 300
        assert result.is_active is True

    def test_git_repo_unique_daemon_name(self, test_db) -> None:
        """Test that daemon_name must be unique."""
        repo1 = GitRepo(
            daemon_name="unique-daemon",
            repo_url="https://github.com/user/repo1",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo1)
        test_db.commit()

        # Try to add another with same daemon_name
        repo2 = GitRepo(
            daemon_name="unique-daemon",
            repo_url="https://github.com/user/repo2",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo2)

        with pytest.raises(Exception):  # SQLAlchemy IntegrityError
            test_db.commit()

    def test_git_repo_with_commit_trackers(self, test_db) -> None:
        """Test GitRepo with CommitTracker relationships."""
        repo = GitRepo(
            daemon_name="tracker-test",
            repo_url="https://github.com/user/repo",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo)
        test_db.commit()

        # Add commit trackers
        tracker1 = CommitTracker(
            repo_id=repo.id,
            commit_sha="commit1",
            status="pending",
        )
        tracker2 = CommitTracker(
            repo_id=repo.id,
            commit_sha="commit2",
            status="running",
        )

        test_db.add_all([tracker1, tracker2])
        test_db.commit()

        # Query repo with trackers
        result = test_db.query(GitRepo).filter(GitRepo.id == repo.id).first()
        assert len(result.commit_trackers) == 2


class TestCommitTracker:
    """Tests for CommitTracker model."""

    def test_create_commit_tracker(self, test_db) -> None:
        """Test creating a CommitTracker entry."""
        repo = GitRepo(
            daemon_name="commit-tracker-test",
            repo_url="https://github.com/user/repo",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo)
        test_db.commit()

        tracker = CommitTracker(
            repo_id=repo.id,
            commit_sha="abc123xyz",
            build_triggered=True,
            status="completed",
        )

        test_db.add(tracker)
        test_db.commit()

        # Query back
        result = (
            test_db.query(CommitTracker)
            .filter(CommitTracker.commit_sha == "abc123xyz")
            .first()
        )
        assert result is not None
        assert result.build_triggered is True
        assert result.status == "completed"

    def test_commit_tracker_with_build(self, test_db) -> None:
        """Test CommitTracker with associated Build."""
        repo = GitRepo(
            daemon_name="tracker-build-test",
            repo_url="https://github.com/user/repo",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo)
        test_db.commit()

        build = Build(
            repo_full_name="user/repo",
            commit_sha="tracker_build",
            branch="main",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(build)
        test_db.commit()

        tracker = CommitTracker(
            repo_id=repo.id,
            commit_sha="tracker_build",
            build_triggered=True,
            build_id=build.id,
            status="running",
        )
        test_db.add(tracker)
        test_db.commit()

        # Query back with relationship
        result = (
            test_db.query(CommitTracker)
            .filter(CommitTracker.commit_sha == "tracker_build")
            .first()
        )
        assert result.build is not None
        assert result.build.commit_sha == "tracker_build"

    def test_commit_tracker_status_values(self, test_db) -> None:
        """Test CommitTracker with various status values."""
        repo = GitRepo(
            daemon_name="status-test",
            repo_url="https://github.com/user/repo",
            workflow_file="workflows/ci.yml",
            working_directory="/tmp/work",
        )
        test_db.add(repo)
        test_db.commit()

        statuses = ["pending", "running", "completed", "failed", "exception"]

        for i, status in enumerate(statuses):
            tracker = CommitTracker(
                repo_id=repo.id,
                commit_sha=f"commit_{i}",
                status=status,
            )
            test_db.add(tracker)

        test_db.commit()

        # Query all and verify
        results = (
            test_db.query(CommitTracker).filter(CommitTracker.repo_id == repo.id).all()
        )
        assert len(results) == 5
        tracked_statuses = [r.status for r in results]
        assert set(tracked_statuses) == set(statuses)


class TestInitDb:
    """Tests for init_db function."""

    def test_init_db(self, tmp_path: Path) -> None:
        """Test database initialization."""
        # This test is simple since init_db just creates tables
        # We verify it doesn't crash and creates the expected engine
        db_file = tmp_path / "test_init.db"
        db_url = f"sqlite:///{db_file}"

        # Temporarily patch the DATABASE_URL
        import slurm_ci.database as db_module

        original_engine = db_module.engine
        try:
            db_module.engine = create_engine(db_url)
            init_db()

            # Verify database file was created
            assert db_file.exists()

            # Verify tables exist
            from sqlalchemy import inspect

            inspector = inspect(db_module.engine)
            tables = inspector.get_table_names()

            assert "builds" in tables
            assert "jobs" in tables
            assert "git_repos" in tables
            assert "commit_trackers" in tables

        finally:
            db_module.engine = original_engine
