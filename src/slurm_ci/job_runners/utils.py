from typing import Dict


def resolve_container_image(image_template: str, matrix_vars: Dict) -> str:
    """Resolves container image name with matrix variables."""
    for key, value in matrix_vars.items():
        image_template = image_template.replace(f"${{{{ matrix.{key} }}}}", str(value))
    return image_template


def build_steps_script(job_spec: Dict) -> str:
    """Builds a shell script from the steps in a job spec."""
    script_lines = [
        "#!/bin/bash",
        "set -e",
        "set -x",
    ]
    for step in job_spec.get("steps", []):
        script_lines.append(f"echo '--- Running step: {step.get('name', 'unnamed')}'")
        script_lines.append(step["run"])
    return "\\n".join(script_lines)
