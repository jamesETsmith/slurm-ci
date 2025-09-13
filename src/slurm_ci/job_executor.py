import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict

import docker

from .job_runners.utils import build_steps_script, resolve_container_image


# This script is intended to be run on a Slurm compute node


def run_job_in_container(job_spec: Dict, matrix_vars: Dict):
    """
    Core logic to run a job's steps inside a Docker container.
    """
    docker_client = docker.from_env()
    working_dir = Path.cwd()  # Assume CWD on the node is the workspace

    container_spec = job_spec.get("container", {})
    if not container_spec.get("image"):
        raise ValueError("Job spec must include a container image")

    resolved_image = resolve_container_image(container_spec["image"], matrix_vars)

    _ensure_image_available(docker_client, resolved_image)

    script_content = build_steps_script(job_spec)

    container_config = {
        "image": resolved_image,
        "command": ["bash", "/tmp/workflow_script.sh"],
        "volumes": {
            str(working_dir): {"bind": "/workspace", "mode": "rw"},
            "/tmp": {"bind": "/tmp", "mode": "rw"},
        },
        "working_dir": "/workspace",
        "environment": _build_environment_vars(matrix_vars),
        "remove": True,
        "stdout": True,
        "stderr": True,
        "stream": True,
    }

    if _has_gpu_support():
        container_config["device_requests"] = [
            docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
        ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script_content)
        temp_script = f.name

    try:
        subprocess.run(["cp", temp_script, "/tmp/workflow_script.sh"], check=True)
        subprocess.run(["chmod", "+x", "/tmp/workflow_script.sh"], check=True)

        container = docker_client.containers.run(**container_config)

        for line in container:
            print(line.decode("utf-8"), end="")

        container.reload()
        exit_code = container.attrs["State"]["ExitCode"]

        return exit_code == 0

    finally:
        Path(temp_script).unlink(missing_ok=True)
        subprocess.run(["rm", "-f", "/tmp/workflow_script.sh"], check=False)


def _ensure_image_available(docker_client, image: str) -> None:
    try:
        docker_client.images.get(image)
        print(f"Image '{image}' found locally")
    except docker.errors.ImageNotFound:
        print(f"Image '{image}' not found locally, pulling...")
        docker_client.images.pull(image)
        print(f"Image '{image}' pulled successfully")


def _has_gpu_support() -> bool:
    try:
        gpus = docker.from_env().info().get("Runtimes", {}).get("nvidia", {})
        return bool(gpus)
    except Exception:
        return False


def _build_environment_vars(matrix_vars: Dict) -> Dict[str, str]:
    env_vars = {
        "CI": "true",
        "GITHUB_ACTIONS": "true",
        "GITHUB_WORKSPACE": "/workspace",
    }
    for key, value in matrix_vars.items():
        env_vars[f"MATRIX_{key.upper()}"] = str(value)
    return env_vars


def main() -> None:
    parser = argparse.ArgumentParser(description="Slurm CI Job Executor")
    parser.add_argument("job_spec_json", help="The job specification as a JSON string")
    parser.add_argument(
        "matrix_vars_json", help="The matrix variables for this job as a JSON string"
    )
    args = parser.parse_args()

    try:
        job_spec = json.loads(args.job_spec_json)
        matrix_vars = json.loads(args.matrix_vars_json)

        success = run_job_in_container(job_spec, matrix_vars)

        if not success:
            sys.exit(1)

    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
