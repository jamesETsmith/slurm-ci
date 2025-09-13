#!/usr/bin/env python3
import argparse
import json
import sys

from .local_orchestrator import LocalOrchestrator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SLURM CI Local Runner - Run workflows locally"
    )

    parser.add_argument(
        "workflow",
        nargs="?",
        help="Workflow file to run (auto-discovered if not specified)",
    )

    parser.add_argument(
        "-d",
        "--directory",
        default=".",
        help="Working directory (default: current directory)",
    )

    parser.add_argument("-m", "--matrix", help="Matrix combination as JSON string")

    parser.add_argument(
        "--list-workflows", action="store_true", help="List available workflows"
    )

    parser.add_argument("--list-jobs", help="List jobs in specified workflow")

    parser.add_argument("--job", help="Run specific job (default: all jobs)")

    parser.add_argument(
        "--execution-mode",
        choices=["local", "cluster"],
        default="local",
        help="Execution mode: local Docker or remote cluster",
    )

    parser.add_argument("--cluster-config", help="Path to cluster configuration file")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without running",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    try:
        # Parse matrix combination if provided
        matrix_vars = {}
        if args.matrix:
            matrix_vars = json.loads(args.matrix)

        # Initialize orchestrator
        cluster_config = None
        if args.cluster_config:
            with open(args.cluster_config) as f:
                cluster_config = json.load(f)

        orchestrator = LocalOrchestrator(
            working_directory=args.directory, cluster_config=cluster_config
        )

        # Handle different commands
        if args.list_workflows:
            workflows = orchestrator.list_available_workflows()
            print("Available workflows:")
            for workflow in workflows:
                print(f"  {workflow}")
            return

        if args.list_jobs:
            jobs = orchestrator.list_workflow_jobs(args.list_jobs)
            print(f"Jobs in {args.list_jobs}:")
            for job in jobs:
                print(f"  {job}")
            return

        if args.dry_run:
            plan = orchestrator.plan_execution(
                workflow_file=args.workflow,
                matrix_combination=matrix_vars,
                job_filter=args.job,
            )
            print("Execution plan:")
            print(json.dumps(plan, indent=2))
            return

        # Execute workflow
        results = orchestrator.execute_local_workflow(
            workflow_file=args.workflow,
            matrix_combination=matrix_vars,
            execution_mode=args.execution_mode,
        )

        # Report results
        success_count = sum(1 for r in results if r.get("success", False))
        total_count = len(results)

        if success_count == total_count:
            print(f"✓ All {total_count} job(s) completed successfully")
            sys.exit(0)
        else:
            print(f"✗ {total_count - success_count} of {total_count} job(s) failed")
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
