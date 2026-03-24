"""In-process tests for cli.py command dispatch."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from slurm_ci import cli


def run_main_with_args(args: list[str]) -> None:
    with patch.object(sys, "argv", ["slurm-ci", *args]):
        cli.main()


def test_main_exits_when_act_missing_for_non_install_command() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value=None),
        patch("slurm_ci.cli.sys.exit", side_effect=SystemExit(1)),
    ):
        with pytest.raises(SystemExit):
            run_main_with_args(["db-init"])


def test_install_act_bypasses_act_binary_guard() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value=None),
        patch("slurm_ci.cli.install_act") as mock_install,
    ):
        run_main_with_args(["install-act"])
        mock_install.assert_called_once()


def test_local_run_dispatches_unknown_args() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.local_run") as mock_local_run,
    ):
        run_main_with_args(["local-run", "--job", "build"])
        mock_local_run.assert_called_once()
        assert mock_local_run.call_args[0][1] == ["--job", "build"]


def test_slurm_run_exits_on_conflicting_config_arguments() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.sys.exit", side_effect=SystemExit(1)),
    ):
        with pytest.raises(SystemExit):
            run_main_with_args(
                [
                    "slurm-run",
                    "--config",
                    "cfg.toml",
                    "--workflow_file",
                    "wf.yml",
                    "--working_directory",
                    ".",
                ]
            )


def test_slurm_run_uses_config_and_calls_launcher() -> None:
    config = SimpleNamespace(
        slurm_options={"time": "00:10:00"},
        matrix_map={"os": {"key": "partition", "value_prefix": "", "value_suffix": ""}},
        workflow_file="wf.yml",
        working_directory="/tmp/work",
    )
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.SlurmRunConfig.from_file", return_value=config),
        patch("slurm_ci.cli.launch_slurm_jobs") as mock_launch,
    ):
        run_main_with_args(["slurm-run", "--config", "cfg.toml"])
        mock_launch.assert_called_once()
        kwargs = mock_launch.call_args.kwargs
        assert kwargs["custom_sbatch_options"] == {"time": "00:10:00"}
        assert kwargs["matrix_map"] is not None


def test_dashboard_command_starts_flask_app() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.app.run") as mock_run,
    ):
        run_main_with_args(
            ["dashboard", "--host", "0.0.0.0", "--port", "9000", "--debug"]
        )
        mock_run.assert_called_once_with(debug=True, host="0.0.0.0", port=9000)


def test_db_sync_command_invokes_sync_function() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.sync_status_to_db", return_value=3) as mock_sync,
    ):
        run_main_with_args(["db-sync", "--status-dir", "/tmp/status"])
        mock_sync.assert_called_once_with("/tmp/status")


def test_services_up_starts_manager_services() -> None:
    manager = SimpleNamespace(start_service=Mock(return_value=(True, "started")))
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.ServiceManager", return_value=manager),
        patch("slurm_ci.cli.init_db") as mock_init_db,
        patch("slurm_ci.cli._is_port_available", return_value=True),
    ):
        run_main_with_args(["services", "up"])
        mock_init_db.assert_called_once()
        assert manager.start_service.call_count == 2


def test_services_up_fails_when_port_occupied() -> None:
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli._is_port_available", return_value=False),
        patch("slurm_ci.cli.sys.exit", side_effect=SystemExit(1)),
    ):
        with pytest.raises(SystemExit):
            run_main_with_args(["services", "up", "--port", "5001"])


def test_services_down_calls_stop_for_each_service() -> None:
    manager = SimpleNamespace(
        read_pid_file=Mock(side_effect=[123, 456]),
        stop_service=Mock(return_value=True),
    )
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.ServiceManager", return_value=manager),
    ):
        run_main_with_args(["services", "down"])
        assert manager.stop_service.call_count == 2


def test_services_status_lists_both_services() -> None:
    manager = SimpleNamespace(
        list_services=Mock(
            return_value=[
                {"service_name": "db-watch", "running": True, "log_file": "/tmp/a.log"},
                {
                    "service_name": "dashboard",
                    "running": False,
                    "log_file": "/tmp/b.log",
                },
            ]
        )
    )
    with (
        patch("slurm_ci.cli.shutil.which", return_value="/tmp/act"),
        patch("slurm_ci.cli.ServiceManager", return_value=manager),
    ):
        run_main_with_args(["services", "status"])
        manager.list_services.assert_called_once()
