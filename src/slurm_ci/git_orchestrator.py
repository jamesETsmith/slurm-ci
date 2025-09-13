import base64

from .database import Build, Job, SessionLocal
from .github_api import GithubAPI
from .job_runners.local_docker_runner import LocalDockerRunner
from .job_runners.slurm_runner import SlurmJobRunner
from .workflow_parser import WorkflowParser


class GitBasedOrchestrator:
    def __init__(self, config) -> None:
        self.config = config
        self.github_api = GithubAPI(config.GITHUB_TOKEN)
        self.runners = {
            "local": LocalDockerRunner(),
            "slurm": SlurmJobRunner(config),
        }
        self.db_session = SessionLocal()

    def handle_webhook(self, event_type, event_data) -> None:
        """Main entry point for handling GitHub webhooks"""

        if event_type == "push":
            repo_full_name = event_data["repository"]["full_name"]
            commit_sha = event_data["after"]
            build = self._create_build_record(repo_full_name, commit_sha, event_type)
            self.process_push_event(repo_full_name, commit_sha, build)
        elif event_type == "pull_request":
            action = event_data.get("action")
            if action in ["opened", "synchronize"]:
                repo_full_name = event_data["repository"]["full_name"]
                commit_sha = event_data["pull_request"]["head"]["sha"]
                build = self._create_build_record(
                    repo_full_name, commit_sha, event_type
                )
                self.process_pull_request_event(repo_full_name, commit_sha, build)
        else:
            print(f"Ignoring event type: {event_type}")

    def _create_build_record(self, repo_full_name, commit_sha, event_type):
        new_build = Build(
            repo_full_name=repo_full_name,
            commit_sha=commit_sha,
            event_type=event_type,
        )
        self.db_session.add(new_build)
        self.db_session.commit()
        self.db_session.refresh(new_build)
        return new_build

    def process_push_event(self, repo_full_name, commit_sha, build) -> None:
        print(f"Processing push event for {repo_full_name} at commit {commit_sha}")
        self._fetch_and_run_workflow(repo_full_name, commit_sha, build)

    def process_pull_request_event(self, repo_full_name, commit_sha, build) -> None:
        print(f"Processing PR event for {repo_full_name} at commit {commit_sha}")
        self._fetch_and_run_workflow(repo_full_name, commit_sha, build)

    def _fetch_and_run_workflow(self, repo_full_name, commit_sha, build) -> None:
        """Fetches workflow files from a repo and runs them."""
        workflow_paths = [".github/workflows", ".amd/workflows"]
        for path in workflow_paths:
            try:
                contents = self.github_api.get_repo_contents(
                    repo_full_name, path, commit_sha
                )
                for item in contents:
                    if item["name"].endswith((".yml", ".yaml")):
                        self._run_jobs_from_workflow(
                            repo_full_name, commit_sha, item, build
                        )
            except Exception as e:
                print(f"Could not fetch workflows from {path}: {e}")

    def _run_jobs_from_workflow(self, repo_full_name, commit_sha, workflow_item, build) -> None:
        """Parses a workflow file and runs the jobs."""

        # 1. Get workflow content
        file_content_base64 = self.github_api.get_repo_contents(
            repo_full_name, workflow_item["path"], commit_sha
        )["content"]

        workflow_content = base64.b64decode(file_content_base64).decode("utf-8")

        # 2. Parse workflow
        parser = WorkflowParser(workflow_content)
        jobs = parser.get_jobs()
        matrix_combinations = parser.generate_matrix_combinations()

        # 3. Run jobs
        if not matrix_combinations:
            matrix_combinations = [{}]  # Simple job, no matrix

        for job_name, job_spec in jobs.items():
            for matrix_vars in matrix_combinations:
                # 1. Create Job record in DB
                new_job = Job(
                    build_id=build.id,
                    name=job_name,
                    status="running",
                )
                self.db_session.add(new_job)
                self.db_session.commit()
                self.db_session.refresh(new_job)

                print(f"Running job: {job_name} with matrix {matrix_vars}")

                runner_name = job_spec.get("runs-on", "local")
                if runner_name in self.runners:
                    runner = self.runners[runner_name]

                    # 2. Run the job
                    result = runner.run_job(job_spec, matrix_vars)

                    # 3. Update Job record with results
                    new_job.status = "success" if result.get("success") else "failed"
                    new_job.exit_code = result.get(
                        "exit_code", 1 if not result.get("success") else 0
                    )
                    new_job.logs = result.get("output", "")
                    self.db_session.commit()

                else:
                    print(f"Runner '{runner_name}' not found for job '{job_name}'")
                    new_job.status = "failed"
                    new_job.logs = f"Runner '{runner_name}' not found."
                    self.db_session.commit()

                self._update_build_status(build)

    def _update_build_status(self, build) -> None:
        """Checks all jobs for a build and updates the build's status."""

        job_statuses = [job.status for job in build.jobs]

        new_status = "running"
        if "failed" in job_statuses:
            new_status = "failed"
        elif all(status == "success" for status in job_statuses):
            new_status = "success"

        if build.status != new_status:
            build.status = new_status
            self.db_session.commit()
