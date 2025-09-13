#!/usr/bin/env python3
import argparse
import subprocess

from slurm_ci.slurm_launcher import launch_slurm_jobs


def local_run(args, unknown_args):
    """Wrapper for the 'act' binary."""
    subprocess.run(["act", *unknown_args])


def slurm_run(args):
    """Runs workflows on a Slurm cluster."""
    print("slurm-run subcommand called.")
    print(f"Arguments: {args}")
    launch_slurm_jobs(args.workflow_file, args.working_directory)


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

    args, unknown_args = parser.parse_known_args()

    if args.command == "local-run":
        args.func(args, unknown_args)
    else:
        args.func(args)


if __name__ == "__main__":
    main()
