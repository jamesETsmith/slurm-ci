#!/usr/bin/env python3
import argparse
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

from slurm_ci.config import ACT_BINARY, ACT_PATH
from slurm_ci.daemon_manager import DaemonManager
from slurm_ci.dashboard import app
from slurm_ci.database import init_db
from slurm_ci.git_watch_config import (
    create_example_config as create_git_watch_example_config,
)
from slurm_ci.git_watcher import start_git_watcher
from slurm_ci.service_manager import ServiceManager
from slurm_ci.slurm_launcher import launch_slurm_jobs, relaunch_slurm_job
from slurm_ci.slurm_run_config import (
    SlurmRunConfig,
)
from slurm_ci.slurm_run_config import (
    create_example_config as create_slurm_run_example_config,
)
from slurm_ci.status_file import StatusFile
from slurm_ci.status_watcher import start_status_watcher, sync_status_to_db


SERVICE_DB_WATCH = "db-watch"
SERVICE_DASHBOARD = "dashboard"


def local_run(args: argparse.Namespace, unknown_args: list[str]) -> None:
    """Wrapper for the 'act' binary."""
    print("Calling act with:\n", f"{ACT_BINARY} " + " ".join(unknown_args))
    subprocess.run([ACT_BINARY, *unknown_args])


def install_act(args: argparse.Namespace) -> None:
    """Install the 'act' binary."""
    print(f"Installing act to {ACT_PATH}")
    install_dir = Path(ACT_PATH)
    install_dir.mkdir(exist_ok=True, parents=True)

    arch = platform.machine()
    if arch == "x86_64":
        arch = "amd64"

    cmd = [
        "curl",
        "--proto",
        "=https",
        "--tlsv1.2",
        "-sSf",
        "https://raw.githubusercontent.com/nektos/act/master/install.sh",
    ]
    ps = subprocess.run(cmd, capture_output=True, text=True, check=True)
    subprocess.run(
        ["bash", "-s", "--", "-b", str(install_dir)],
        input=ps.stdout,
        text=True,
        check=True,
    )
    print("act installed successfully")


def relaunch_run(args: argparse.Namespace) -> None:
    """Relaunches a workflow from a status file."""
    print("relaunch subcommand called.")
    print(f"Arguments: {args}")
    status_file = StatusFile.from_file(args.status_file)
    relaunch_slurm_job(status_file, dryrun=False)


def generate_slurm_run_config_template(
    output_path: str = "slurm-run-config.toml",
) -> None:
    """Generates a template config file for slurm-run."""
    print(f"Generating slurm-run config template at: {output_path}")
    create_slurm_run_example_config(output_path)
    print("Template generated successfully.")


def slurm_run(args: argparse.Namespace) -> None:
    """Runs workflows on a Slurm cluster.

    There are 3 options here:
    1) You specify a workflow file and directory and it runs with the default SLURM
       options.
    2) You specify only a toml config file where slurm-ci reads, workflow file and
       directory and slurm options from the config file.
    3) Generate a config file template for the user to fill out
    """
    print("slurm-run subcommand called.")
    print(f"Arguments: {args}")

    if args.generate_template:
        generate_slurm_run_config_template()
        return

    # Handle template path if provided
    template_path = None
    if args.template:
        template_path = Path(args.template)

    # Handle custom slurm options from config file
    custom_sbatch_options = None
    matrix_map = None
    workflow_file = args.workflow_file
    working_directory = args.working_directory

    if args.config:
        if args.workflow_file or args.working_directory:
            print(
                "Error: Cannot specify both --config and"
                " --workflow-file/--working-directory"
            )
            sys.exit(1)
        try:
            config = SlurmRunConfig.from_file(args.config)
            custom_sbatch_options = config.slurm_options
            matrix_map = config.matrix_map
            workflow_file = config.workflow_file
            working_directory = config.working_directory
            if custom_sbatch_options:
                print(
                    f"Using custom SLURM options from config: {custom_sbatch_options}"
                )
            if matrix_map:
                print(f"Using matrix mappings from config: {matrix_map}")
        except Exception as e:
            print(f"Warning: Could not load config file {args.config}: {e}")
    elif not (args.workflow_file and args.working_directory):
        print(
            "Error: Must specify either --config or --workflow-file/--working-directory"
        )
        sys.exit(1)

    launch_slurm_jobs(
        workflow_file,
        working_directory,
        dryrun=args.dryrun,
        template_path=template_path,
        custom_sbatch_options=custom_sbatch_options,
        matrix_map=matrix_map,
    )


def db_init(args: argparse.Namespace) -> None:
    """Initialize the database."""
    print("Initializing database...")
    init_db()
    print("Database initialized successfully!")


def db_sync(args: argparse.Namespace) -> None:
    """Sync status files to database."""
    print("Syncing status files to database...")
    count = sync_status_to_db(args.status_dir)
    print(f"Synced {count} status files to database")


def db_watch(args: argparse.Namespace) -> None:
    """Watch status directory and sync to database."""
    print(f"Starting status directory watcher (polling every {args.interval}s)")
    start_status_watcher(args.status_dir, args.interval)


def dashboard(args: argparse.Namespace) -> None:
    """Start the web dashboard."""
    print(f"Starting web dashboard on http://localhost:{args.port}")
    app.run(debug=args.debug, host=args.host, port=args.port)


def db_hard_clean(args: argparse.Namespace) -> None:
    """Delete the database and status file directory."""
    from slurm_ci.config import DATABASE_URL, STATUS_DIR

    db_path = DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        print(f"Deleting database file: {db_path}")
        os.remove(db_path)
    else:
        print("Database file not found.")

    if os.path.exists(STATUS_DIR):
        print(f"Deleting status file directory: {STATUS_DIR}")
        shutil.rmtree(STATUS_DIR)
    else:
        print("Status file directory not found.")
    print("Hard clean complete.")


def db_soft_reset(args: argparse.Namespace) -> None:
    """Regenerate the database from the status file directory."""
    from slurm_ci.config import DATABASE_URL, STATUS_DIR

    db_path = DATABASE_URL.replace("sqlite:///", "")
    if os.path.exists(db_path):
        print(f"Deleting database file: {db_path}")
        os.remove(db_path)
    else:
        print("Database file not found, skipping deletion.")

    print("Initializing new database...")
    init_db()

    print("Syncing status files to database...")
    count = sync_status_to_db(STATUS_DIR)
    print(f"Synced {count} status files to database")

    print("Soft reset complete.")


def git_watch_start(args: argparse.Namespace) -> None:
    """Start a git-watch daemon."""
    print(f"Starting git-watch daemon from config: {args.config_file}")
    start_git_watcher(args.config_file)


def git_watch_stop(args: argparse.Namespace) -> None:
    """Stop a git-watch daemon."""
    daemon_manager = DaemonManager()

    if args.daemon_name:
        # Stop specific daemon
        if daemon_manager.stop_daemon(args.daemon_name):
            print(f"Successfully stopped daemon: {args.daemon_name}")
        else:
            print(f"Failed to stop daemon: {args.daemon_name}")
            sys.exit(1)
    else:
        print("Error: daemon name is required")
        sys.exit(1)


def git_watch_stop_all(args: argparse.Namespace) -> None:
    """Stop all git-watch daemons."""
    daemon_manager = DaemonManager()
    stopped_count = daemon_manager.stop_all_daemons()
    print(f"Stopped {stopped_count} daemon(s)")


def git_watch_status(args: argparse.Namespace) -> None:
    """Show status of git-watch daemons."""
    daemon_manager = DaemonManager()
    running_daemons = daemon_manager.list_running_daemons()

    if not running_daemons:
        print("No git-watch daemons are currently running")
        return

    print(f"Found {len(running_daemons)} running git-watch daemon(s):")
    print()

    for daemon in running_daemons:
        print(f"Daemon: {daemon['daemon_name']}")
        print(f"  PID: {daemon.get('pid', 'unknown')}")
        print(f"  Status: {daemon.get('status', 'unknown')}")
        print(f"  Started: {daemon.get('started_at', 'unknown')}")
        print(f"  Last Check: {daemon.get('last_check', 'never')}")
        print(f"  Last Commit: {daemon.get('last_commit', 'none')}")

        config = daemon.get("config", {})
        if config:
            print(f"  Repository: {config.get('repo_url', 'unknown')}")
            print(f"  Branch: {config.get('branch', 'unknown')}")
            interval = config.get("polling_interval", "unknown")
            print(f"  Polling Interval: {interval}s")
        print()


def git_watch_create_config(args: argparse.Namespace) -> None:
    """Create an example git-watch configuration file."""
    output_path = args.output or "git-watch-config.toml"
    create_git_watch_example_config(output_path)


def _is_port_available(host: str, port: int) -> bool:
    """Return whether a TCP host/port pair can be bound."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def services_up(args: argparse.Namespace) -> None:
    """Start support services for local development."""
    manager = ServiceManager()

    if not args.skip_db_init:
        print("Initializing database...")
        init_db()

    if not _is_port_available(args.host, args.port):
        print(f"Error: dashboard port is occupied on {args.host}:{args.port}")
        sys.exit(1)

    db_watch_command = [sys.executable, "-m", "slurm_ci.cli", "db-watch"]
    if args.status_dir:
        db_watch_command.extend(["--status-dir", args.status_dir])
    db_watch_command.extend(["--interval", str(args.interval)])

    dashboard_command = [
        sys.executable,
        "-m",
        "slurm_ci.cli",
        "dashboard",
        "--host",
        args.host,
        "--port",
        str(args.port),
    ]

    if args.dashboard_debug:
        dashboard_command.append("--debug")

    started, reason = manager.start_service(
        SERVICE_DB_WATCH,
        db_watch_command,
        metadata={
            "status_dir": args.status_dir,
            "interval": args.interval,
        },
    )
    if started:
        print("Started db-watch service")
    elif reason == "already-running":
        print("db-watch service already running")

    started, reason = manager.start_service(
        SERVICE_DASHBOARD,
        dashboard_command,
        metadata={
            "host": args.host,
            "port": args.port,
            "debug": args.dashboard_debug,
        },
    )
    if started:
        print("Started dashboard service")
    elif reason == "already-running":
        print("dashboard service already running")

    print("Services are ready. Use 'slurm-ci services status' to inspect.")


def services_down(args: argparse.Namespace) -> None:
    """Stop support services for local development."""
    manager = ServiceManager()
    failures = 0

    for service_name in [SERVICE_DASHBOARD, SERVICE_DB_WATCH]:
        had_pid = manager.read_pid_file(service_name) is not None
        stopped = manager.stop_service(
            service_name, timeout=args.timeout, force=args.force
        )
        if stopped:
            print(f"Stopped {service_name}")
        else:
            if not had_pid:
                print(f"{service_name} was not running")
            else:
                print(f"Failed to stop {service_name}")
                failures += 1

    if failures > 0:
        sys.exit(1)


def services_status(args: argparse.Namespace) -> None:
    """Show status for support services."""
    manager = ServiceManager()
    services = manager.list_services([SERVICE_DB_WATCH, SERVICE_DASHBOARD])
    running_count = 0

    for service in services:
        state = "running" if service["running"] else "stopped"
        if service["running"]:
            running_count += 1

        print(f"Service: {service['service_name']}")
        print(f"  State: {state}")
        print(f"  PID: {service.get('pid') or 'none'}")
        print(f"  Started: {service.get('started_at') or 'unknown'}")
        metadata = service.get("metadata", {})
        if metadata:
            for key, value in metadata.items():
                print(f"  {key}: {value}")
        print(f"  Log: {service['log_file']}")
        print()

    print(f"Running {running_count}/{len(services)} services")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="slurm-ci - A tool for running CI workflows locally or on Slurm."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: install-act
    parser_install_act = subparsers.add_parser(
        "install-act", help="Install the 'act' binary."
    )
    parser_install_act.set_defaults(func=install_act)

    # Subcommand: local-run
    parser_local = subparsers.add_parser(
        "local-run", help="Run workflows locally using act."
    )
    parser_local.set_defaults(func=local_run)

    # Subcommand: slurm-run
    parser_slurm = subparsers.add_parser(
        "slurm-run", help="Run workflows on a Slurm cluster."
    )
    parser_slurm.add_argument(
        "--workflow_file", help="Workflow file to run.", default=None
    )
    parser_slurm.add_argument(
        "--working_directory", help="The project's working directory.", default=None
    )
    parser_slurm.add_argument(
        "--dryrun",
        action="store_true",
        help="Perform a dry run without executing jobs."
        + " (This will still submit the jobs to slurm and pull the dockerfiles.)",
    )
    parser_slurm.add_argument(
        "--template",
        help="Full path to jinja template file for SLURM job script generation.",
    )
    parser_slurm.add_argument(
        "--config",
        help="Path to git-watch config file to load custom SLURM options from.",
    )
    parser_slurm.add_argument(
        "--generate-template",
        action="store_true",
        help="Generate a template config file for slurm-run.",
    )
    parser_slurm.set_defaults(func=slurm_run)

    # Subcommand: relaunch
    parser_relaunch = subparsers.add_parser(
        "relaunch", help="Relaunch a workflow from a status file."
    )
    parser_relaunch.add_argument("status_file", help="Status file to relaunch from.")
    parser_relaunch.set_defaults(func=relaunch_run)

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

    # Subcommand: db-hard-clean
    parser_db_hard_clean = subparsers.add_parser(
        "db-hard-clean",
        help="Delete the database and status file directory (a hard clean).",
    )
    parser_db_hard_clean.set_defaults(func=db_hard_clean)

    # Subcommand: db-soft-reset
    parser_db_soft_reset = subparsers.add_parser(
        "db-soft-reset",
        help="Regenerate the database from the status file directory (a soft reset).",
    )
    parser_db_soft_reset.set_defaults(func=db_soft_reset)

    # Subcommand: git-watch
    parser_git_watch = subparsers.add_parser(
        "git-watch", help="Git repository watching commands."
    )
    git_watch_subparsers = parser_git_watch.add_subparsers(
        dest="git_watch_command", required=True
    )

    # git-watch start
    parser_git_watch_start = git_watch_subparsers.add_parser(
        "start", help="Start a git-watch daemon."
    )
    parser_git_watch_start.add_argument(
        "config_file", help="Path to git-watch configuration file."
    )
    parser_git_watch_start.set_defaults(func=git_watch_start)

    # git-watch stop
    parser_git_watch_stop = git_watch_subparsers.add_parser(
        "stop", help="Stop a git-watch daemon."
    )
    parser_git_watch_stop.add_argument(
        "daemon_name", help="Name of the daemon to stop."
    )
    parser_git_watch_stop.set_defaults(func=git_watch_stop)

    # git-watch stop-all
    parser_git_watch_stop_all = git_watch_subparsers.add_parser(
        "stop-all", help="Stop all git-watch daemons."
    )
    parser_git_watch_stop_all.set_defaults(func=git_watch_stop_all)

    # git-watch status
    parser_git_watch_status = git_watch_subparsers.add_parser(
        "status", help="Show status of git-watch daemons."
    )
    parser_git_watch_status.set_defaults(func=git_watch_status)

    # git-watch create-config
    parser_git_watch_create_config = git_watch_subparsers.add_parser(
        "create-config", help="Create an example git-watch configuration file."
    )
    parser_git_watch_create_config.add_argument(
        "--output", "-o", help="Output file path (default: git-watch-config.toml)."
    )
    parser_git_watch_create_config.set_defaults(func=git_watch_create_config)

    # Subcommand: services
    parser_services = subparsers.add_parser(
        "services", help="Manage local support services (db-watch and dashboard)."
    )
    services_subparsers = parser_services.add_subparsers(
        dest="services_command", required=True
    )

    parser_services_up = services_subparsers.add_parser(
        "up", help="Start support services."
    )
    parser_services_up.add_argument(
        "--status-dir",
        help="Status directory for db-watch (default: ~/.slurm-ci/job_status)",
    )
    parser_services_up.add_argument(
        "--interval",
        type=int,
        default=30,
        help="db-watch polling interval in seconds (default: 30)",
    )
    parser_services_up.add_argument(
        "--host", default="127.0.0.1", help="Dashboard host (default: 127.0.0.1)"
    )
    parser_services_up.add_argument(
        "--port", type=int, default=5001, help="Dashboard port (default: 5001)"
    )
    parser_services_up.add_argument(
        "--dashboard-debug", action="store_true", help="Run dashboard in debug mode"
    )
    parser_services_up.add_argument(
        "--skip-db-init",
        action="store_true",
        help="Skip database initialization before starting services",
    )
    parser_services_up.set_defaults(func=services_up)

    parser_services_down = services_subparsers.add_parser(
        "down", help="Stop support services."
    )
    parser_services_down.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Graceful shutdown timeout in seconds (default: 30)",
    )
    parser_services_down.add_argument(
        "--force",
        action="store_true",
        help="Force kill services if graceful shutdown times out",
    )
    parser_services_down.set_defaults(func=services_down)

    parser_services_status = services_subparsers.add_parser(
        "status", help="Show support service status."
    )
    parser_services_status.set_defaults(func=services_status)

    #
    # Parse arguments
    #
    args, unknown_args = parser.parse_known_args()

    #
    # Check if act binary is installed
    #
    if not shutil.which(ACT_BINARY) and args.command != "install-act":
        print(
            f"act binary not found at '{ACT_BINARY}'.\n"
            "Please install it by running 'slurm-ci install-act'\n"
            "or set the 'SLURM_CI_ACT_BINARY' environment variable."
        )
        sys.exit(1)

    #
    # Run the appropriate function
    #
    if args.command == "local-run":
        args.func(args, unknown_args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
