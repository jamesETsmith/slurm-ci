import datetime

from sqlalchemy import (
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
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    build = relationship("Build", back_populates="jobs")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    init_db()
