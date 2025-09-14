#!/usr/bin/env python3
import argparse
import subprocess

from slurm_ci.slurm_launcher import launch_slurm_jobs
from slurm_ci.status_watcher import sync_status_to_db, start_status_watcher
from slurm_ci.database import init_db
from slurm_ci.dashboard import app


def local_run(args, unknown_args):
    """Wrapper for the 'act' binary."""
    subprocess.run(["act", *unknown_args])


def slurm_run(args):
    """Runs workflows on a Slurm cluster."""
    print("slurm-run subcommand called.")
    print(f"Arguments: {args}")
    launch_slurm_jobs(args.workflow_file, args.working_directory)


def db_init(args):
    """Initialize the database."""
    print("Initializing database...")
    init_db()
    print("Database initialized successfully!")


def db_sync(args):
    """Sync status files to database."""
    print("Syncing status files to database...")
    count = sync_status_to_db(args.status_dir)
    print(f"Synced {count} status files to database")


def db_watch(args):
    """Watch status directory and sync to database."""
    print(f"Starting status directory watcher (polling every {args.interval}s)")
    start_status_watcher(args.status_dir, args.interval)


def dashboard(args):
    """Start the web dashboard."""
    print(f"Starting web dashboard on http://localhost:{args.port}")
    app.run(debug=args.debug, host=args.host, port=args.port)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="slurm-ci - A tool for running CI workflows locally or on Slurm."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: local-run
    parser_local = subparsers.add_parser(
        "local-run", help="Run workflows locally using act."
    )
    parser_local.set_defaults(func=local_run)

    # Subcommand: slurm-run
    parser_slurm = subparsers.add_parser(
        "slurm-run", help="Run workflows on a Slurm cluster."
    )
    parser_slurm.add_argument("workflow_file", help="Workflow file to run.")
    parser_slurm.add_argument(
        "working_directory", help="The project's working directory."
    )
    parser_slurm.set_defaults(func=slurm_run)

    # Subcommand: db-init
    parser_db_init = subparsers.add_parser("db-init", help="Initialize the database.")
    parser_db_init.set_defaults(func=db_init)

    # Subcommand: db-sync
    parser_db_sync = subparsers.add_parser(
        "db-sync", help="Sync status files to database (one-time)."
    )
    parser_db_sync.add_argument(
        "--status-dir",
        help="Status directory to sync from (default: ~/.slurm-ci/job_status)",
    )
    parser_db_sync.set_defaults(func=db_sync)

    # Subcommand: db-watch
    parser_db_watch = subparsers.add_parser(
        "db-watch", help="Watch status directory and continuously sync to database."
    )
    parser_db_watch.add_argument(
        "--status-dir",
        help="Status directory to watch (default: ~/.slurm-ci/job_status)",
    )
    parser_db_watch.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Polling interval in seconds (default: 30)",
    )
    parser_db_watch.set_defaults(func=db_watch)

    # Subcommand: dashboard
    parser_dashboard = subparsers.add_parser(
        "dashboard", help="Start the web dashboard."
    )
    parser_dashboard.add_argument(
        "--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)"
    )
    parser_dashboard.add_argument(
        "--port", type=int, default=5001, help="Port to bind to (default: 5001)"
    )
    parser_dashboard.add_argument(
        "--debug", action="store_true", help="Run in debug mode"
    )
    parser_dashboard.set_defaults(func=dashboard)

    args, unknown_args = parser.parse_known_args()

    if args.command == "local-run":
        args.func(args, unknown_args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
