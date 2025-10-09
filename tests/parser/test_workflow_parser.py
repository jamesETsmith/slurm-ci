import os
import json
import pytest
from slurm_ci.workflow_parser import WorkflowParser


@pytest.fixture
def parser() -> WorkflowParser:
    file_name = "ci.yml"
    cwd = os.path.dirname(os.path.abspath(__file__))
    parser = WorkflowParser(os.path.join(cwd, file_name))
    return parser


def test_get_jobs(parser: WorkflowParser):
    jobs = parser.get_jobs()
    assert "test-rocm-versions" in jobs
    job0 = jobs["test-rocm-versions"]
    print("\n" + json.dumps(job0, indent=4))
    assert job0["runs-on"] == "ubuntu-latest"
    assert job0["strategy"]["matrix"]["rocm_version"] == ["6.4.2", "6.4.3"]
    assert job0["strategy"]["matrix"]["gpu_arch"] == ["gfx90a", "gfx942"]


def test_get_job_matrix(parser: WorkflowParser):
    job_matrix = parser.get_job_matrix("test-rocm-versions")
    assert "rocm_version" in job_matrix
    assert "gpu_arch" in job_matrix


def test_generate_matrix_combinations(parser: WorkflowParser):
    test_generate_matrix_combinations = parser.generate_matrix_combinations()
    print(test_generate_matrix_combinations)
    assert len(test_generate_matrix_combinations) == 4


def test_generate_matrix_combinations_with_includes():
    cwd = os.path.dirname(os.path.abspath(__file__))
    parser = WorkflowParser(os.path.join(cwd, "ci_with_include.yml"))
    test_generate_matrix_combinations = parser.generate_matrix_combinations()
    print(test_generate_matrix_combinations)
    assert len(test_generate_matrix_combinations) == 10

    correct_combinations = [
        {"os": "macos-latest", "version": 12},
        {"os": "macos-latest", "version": 14},
        {"os": "macos-latest", "version": 16},
        {"os": "windows-latest", "version": 12},
        {"os": "windows-latest", "version": 14},
        {"os": "windows-latest", "version": 16},
        {"os": "windows-latest", "version": 17},
        {"os": "ubuntu-latest", "version": 12},
        {"os": "ubuntu-latest", "version": 14},
        {"os": "ubuntu-latest", "version": 16},
    ]

    for combination in test_generate_matrix_combinations:
        assert combination in correct_combinations
