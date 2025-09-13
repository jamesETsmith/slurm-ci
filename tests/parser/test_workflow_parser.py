import json
from slurm_ci.workflow_parser import WorkflowParser

parser = WorkflowParser(open("ci.yml").read())


def test_get_jobs():
    jobs = parser.get_jobs()
    assert "test-rocm-versions" in jobs
    job0 = jobs["test-rocm-versions"]
    print("\n" + json.dumps(job0, indent=4))
    assert job0["runs-on"] == "ubuntu-latest"
    assert job0["strategy"]["matrix"]["rocm_version"] == ["6.4.2", "6.4.3"]
    assert job0["strategy"]["matrix"]["gpu_arch"] == ["gfx90a", "gfx942"]


def test_get_job_matrix():
    job_matrix = parser.get_job_matrix("test-rocm-versions")
    assert "rocm_version" in job_matrix
    assert "gpu_arch" in job_matrix


def test_generate_matrix_combinations():
    test_generate_matrix_combinations = parser.generate_matrix_combinations()
    print(test_generate_matrix_combinations)
    assert len(test_generate_matrix_combinations) == 4
