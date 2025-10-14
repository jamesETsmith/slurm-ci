import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker


class CommitStatus(Enum):
    """Enum for commit processing status."""

    PENDING = "pending"  # Never seen before, should launch job
    RUNNING = "running"  # Job is currently running, do not launch
    COMPLETED = "completed"  # Job completed successfully, do not launch
    FAILED = "failed"  # Job completed with failure, do not launch
    EXCEPTION = "exception"  # Job had exception/corruption, should relaunch


from . import config


engine = create_engine(config.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Build(Base):
    __tablename__ = "builds"
    id = Column(Integer, primary_key=True, index=True)
    repo_full_name = Column(String, index=True)
    commit_sha = Column(String)
    branch = Column(String)
    workflow_file = Column(String)
    working_directory = Column(String)
    event_type = Column(String)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    jobs = relationship("Job", back_populates="build")


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    build_id = Column(Integer, ForeignKey("builds.id"))
    name = Column(String)
    status = Column(String, default="pending")
    exit_code = Column(Integer)
    logs = Column(Text)
    matrix_args = Column(Text)  # JSON string of matrix arguments
    log_file_path = Column(String)
    status_file_path = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    build = relationship("Build", back_populates="jobs")


class GitRepo(Base):
    __tablename__ = "git_repos"
    id = Column(Integer, primary_key=True, index=True)
    daemon_name = Column(String, unique=True, index=True)
    repo_url = Column(String, index=True)
    branch = Column(String, default="main")
    workflow_file = Column(String)
    working_directory = Column(String)
    polling_interval = Column(Integer, default=300)
    is_active = Column(Boolean, default=True)
    last_checked_at = Column(DateTime)
    last_commit_sha = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
    commit_trackers = relationship("CommitTracker", back_populates="repo")


class CommitTracker(Base):
    __tablename__ = "commit_trackers"
    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(Integer, ForeignKey("git_repos.id"))
    commit_sha = Column(String, index=True)
    processed_at = Column(DateTime, default=datetime.datetime.utcnow)
    build_triggered = Column(Boolean, default=False)  # Keep for backward compatibility
    build_id = Column(Integer, ForeignKey("builds.id"), nullable=True)
    # New status field for better tracking
    status = Column(
        String, default="pending"
    )  # pending, running, completed, failed, exception
    last_updated = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
    repo = relationship("GitRepo", back_populates="commit_trackers")
    build = relationship("Build")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
