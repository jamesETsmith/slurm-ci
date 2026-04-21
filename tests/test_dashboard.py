"""Targeted tests for dashboard routes and filters."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from slurm_ci import dashboard


def test_dashboard_filters() -> None:
    assert dashboard.format_json_filter("") == ""
    assert dashboard.format_json_filter('{"a":1}') == '{\n  "a": 1\n}'
    assert dashboard.format_json_filter("{bad") == "{bad"
    assert dashboard.basename_filter("/tmp/file.log") == "file.log"
    assert dashboard.timestamp_to_datetime_filter(1700000000).startswith("20")


def test_logs_route_reads_status_files(tmp_path: Path) -> None:
    good = tmp_path / "a.toml"
    good.write_text(
        "\n".join(
            [
                "[project]",
                'name = "proj"',
                'workflow_file = "wf.yml"',
                "[git]",
                'commit = "abcdef123456"',  # pragma: allowlist secret
                'branch = "main"',
                "[runtime]",
                "start_time = 100",
                "[runtime.end]",
                "time = 200",
                "exit_code = 0",
                "[slurm]",
                "job_id = 22",
            ]
        )
    )
    (tmp_path / "a.log").write_text("hello")
    (tmp_path / "bad.toml").write_text("invalid = [\n")

    with (
        patch("slurm_ci.dashboard.STATUS_DIR", str(tmp_path)),
        patch("slurm_ci.dashboard.render_template", return_value="ok") as mock_render,
    ):
        client = dashboard.app.test_client()
        resp = client.get("/logs")
        assert resp.status_code == 200
        log_entries = mock_render.call_args.kwargs["log_entries"]
        assert any(entry["project_name"] == "proj" for entry in log_entries)
        assert all("status" in entry for entry in log_entries)


def test_raw_log_and_status_routes(tmp_path: Path) -> None:
    log_file = tmp_path / "job.log"
    status_file = tmp_path / "job.toml"
    log_file.write_text("line1\nline2")
    status_file.write_text("[runtime]\nstart_time=1\n")

    with patch("slurm_ci.dashboard.STATUS_DIR", str(tmp_path)):
        client = dashboard.app.test_client()

        log_resp = client.get("/raw_log/job.log")
        assert log_resp.status_code == 200
        assert "line1" in log_resp.get_data(as_text=True)

        status_resp = client.get("/raw_status/job.toml")
        assert status_resp.status_code == 200
        assert "start_time" in status_resp.get_data(as_text=True)

        not_found = client.get("/raw_log/missing.log")
        assert not_found.status_code == 404


def test_build_detail_route_parses_matrix_args() -> None:
    build = SimpleNamespace(
        id=1,
        jobs=[
            SimpleNamespace(
                id=10,
                matrix_args=json.dumps({"os": "ubuntu", "py": "3.12"}),
                start_time=None,
            ),
            SimpleNamespace(id=11, matrix_args=None, start_time=None),
        ],
    )
    query = Mock()
    query.options.return_value = query
    query.filter.return_value = query
    query.first.return_value = build
    db = Mock()
    db.query.return_value = query

    with (
        patch("slurm_ci.dashboard.SessionLocal", return_value=db),
        patch(
            "slurm_ci.dashboard.render_template", return_value="detail"
        ) as mock_render,
    ):
        client = dashboard.app.test_client()
        resp = client.get("/build/1")
        assert resp.status_code == 200
        assert build.jobs[0].matrix_args_parsed["os"] == "ubuntu"
        assert "os" in mock_render.call_args.kwargs["matrix_arg_keys"]
        assert mock_render.call_args.kwargs["data_source"] == "sqlite"


def test_index_route_filter_and_summary_context() -> None:
    _ts = SimpleNamespace(strftime=lambda _fmt: "2025-01-01 00:00:00")
    build = SimpleNamespace(
        id=1,
        status="failed",
        branch="main",
        workflow_file=".github/workflows/test.yml",
        repo_full_name="org/repo",
        created_at=_ts,
        updated_at=_ts,
        jobs=[
            SimpleNamespace(
                status="failed",
                start_time=None,
                end_time=None,
            )
        ],
    )
    query = Mock()
    query.options.return_value = query
    query.order_by.return_value = query
    query.filter.return_value = query
    query.all.return_value = [build]

    # Second query in _load_builds_context (all_builds)
    query_all = Mock()
    query_all.order_by.return_value = query_all
    query_all.all.return_value = [build]

    db = Mock()
    db.query.side_effect = [query, query_all]

    with (
        patch("slurm_ci.dashboard.SessionLocal", return_value=db),
        patch(
            "slurm_ci.dashboard.render_template", return_value="index"
        ) as mock_render,
    ):
        client = dashboard.app.test_client()
        resp = client.get("/?status=failed&branch=main&workflow=test.yml")
        assert resp.status_code == 200
        kwargs = mock_render.call_args.kwargs
        assert kwargs["filters"]["status"] == "failed"
        assert kwargs["summary"]["status_counts"]["failed"] == 1
        assert kwargs["data_source"] == "sqlite"


def test_index_partials_render() -> None:
    _ts = SimpleNamespace(strftime=lambda _fmt: "2025-01-01 00:00:00")
    build = SimpleNamespace(
        id=2,
        status="completed",
        branch="dev",
        workflow_file="workflow.yml",
        repo_full_name="org/repo",
        created_at=_ts,
        updated_at=_ts,
        jobs=[],
    )
    query = Mock()
    query.options.return_value = query
    query.order_by.return_value = query
    query.filter.return_value = query
    query.all.return_value = [build]

    query_all = Mock()
    query_all.order_by.return_value = query_all
    query_all.all.return_value = [build]

    db = Mock()
    db.query.side_effect = [query, query_all, query, query_all]

    with (
        patch("slurm_ci.dashboard.SessionLocal", return_value=db),
        patch("slurm_ci.dashboard.render_template", return_value="partial"),
    ):
        client = dashboard.app.test_client()
        assert client.get("/partials/index_summary").status_code == 200
        assert client.get("/partials/index_table").status_code == 200


def test_job_log_and_download_routes(tmp_path: Path) -> None:
    log_file = tmp_path / "job.log"
    status_file = tmp_path / "job.toml"
    log_file.write_text("job output")
    status_file.write_text("[runtime]\nstart_time=1\n")

    job = SimpleNamespace(
        id=7,
        name="test-job",
        log_file_path=str(log_file),
        status_file_path=str(status_file),
    )
    query = Mock()
    query.filter.return_value = query
    query.first.return_value = job
    db = Mock()
    db.query.return_value = query

    with patch("slurm_ci.dashboard.SessionLocal", return_value=db):
        client = dashboard.app.test_client()
        assert client.get("/job/7/log").status_code == 200
        assert client.get("/job/7/status").status_code == 200
        assert client.get("/job/7/log/download").status_code == 200
        assert client.get("/job/7/status/download").status_code == 200


def test_debug_logs_route(tmp_path: Path) -> None:
    log_file = tmp_path / "x.log"
    log_file.write_text("abc")
    job = SimpleNamespace(id=1, name="n1", log_file_path=str(log_file))

    query = Mock()
    query.all.return_value = [job]
    db = Mock()
    db.query.return_value = query
    with patch("slurm_ci.dashboard.SessionLocal", return_value=db):
        client = dashboard.app.test_client()
        resp = client.get("/debug/logs")
        assert resp.status_code == 404

    with (
        patch("slurm_ci.dashboard.SessionLocal", return_value=db),
        patch.dict("os.environ", {"SLURM_CI_ENABLE_DEBUG_ROUTES": "1"}),
    ):
        client = dashboard.app.test_client()
        enabled_resp = client.get("/debug/logs")
        assert enabled_resp.status_code == 200
        body = enabled_resp.get_data(as_text=True)
        assert "Debug: Log Files Status" in body
        assert "n1" in body
