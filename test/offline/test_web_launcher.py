"""REQ-WEB-020/026, ADR-002/003, INV-WEB-001/013/015: startup lifecycle contracts."""

from __future__ import annotations

import signal
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tradingagents_web import cli, launcher

pytestmark = pytest.mark.unit


@pytest.fixture
def commands(monkeypatch):
    spies = {
        name: Mock(return_value=0)
        for name in (
            "check_port",
            "frontend_tools",
            "build_frontend",
            "run_development",
            "_serve",
        )
    }
    spies["frontend_tools"].return_value = "/tools/npm"
    for name, spy in spies.items():
        monkeypatch.setattr(cli, name, spy)
    return spies


def test_default_serves_without_node_or_build(commands):
    assert cli.main([]) == 0
    commands["_serve"].assert_called_once_with(8000, "info", False)
    commands["frontend_tools"].assert_not_called()
    commands["build_frontend"].assert_not_called()


def test_build_finishes_before_server_and_preserves_custom_port(commands):
    order = []
    commands["build_frontend"].side_effect = lambda *args: order.append("build")
    commands["_serve"].side_effect = lambda *args: order.append("serve") or 0
    assert cli.main(["--build", "--open", "--port", "8018"]) == 0
    assert order == ["build", "serve"]
    commands["_serve"].assert_called_once_with(8018, "info", True)


def test_dev_uses_distinct_ports_and_does_not_build_or_serve_twice(commands):
    assert cli.main(["--dev", "--port", "8018", "--frontend-port", "5188", "--open"]) == 0
    assert [call.args[0] for call in commands["check_port"].call_args_list] == [8018, 5188]
    assert commands["run_development"].call_args.args[2:] == (8018, 5188, "info", True)
    commands["_serve"].assert_not_called()
    commands["build_frontend"].assert_not_called()


@pytest.mark.parametrize(
    "args",
    [
        ["--dev", "--build"],
        ["--frontend-port", "5174"],
        ["--dev", "--port", "5173"],
        ["--port", "0"],
        ["--port", "65536"],
        ["--port", "bad"],
        ["--host", "0.0.0.0"],
    ],
)
def test_invalid_launch_arguments_never_start_processes(commands, args):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    commands["run_development"].assert_not_called()
    commands["_serve"].assert_not_called()


def test_occupied_port_refuses_startup_before_build(commands, capsys):
    commands["check_port"].side_effect = launcher.LaunchError("Port 8000 is unavailable.")
    with pytest.raises(SystemExit) as error:
        cli.main(["--build"])
    assert error.value.code == 1
    assert "unavailable" in capsys.readouterr().err
    commands["build_frontend"].assert_not_called()
    commands["_serve"].assert_not_called()


def test_failed_build_never_starts_stale_assets(commands):
    commands["build_frontend"].side_effect = launcher.LaunchError("Frontend build failed.")
    with pytest.raises(SystemExit) as error:
        cli.main(["--build"])
    assert error.value.code == 1
    commands["_serve"].assert_not_called()


@pytest.mark.parametrize("problem", ["source", "node", "npm", "dependencies"])
def test_prerequisite_failures_are_actionable_without_installing(tmp_path, monkeypatch, problem):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    if problem != "source":
        (frontend / "package.json").write_text("{}")
    monkeypatch.setattr(
        launcher.shutil, "which", lambda name: None if name == problem else f"/tools/{name}"
    )
    with pytest.raises(
        launcher.LaunchError,
        match={
            "source": "source checkout",
            "node": "Node.js",
            "npm": "Node.js",
            "dependencies": "npm ci",
        }[problem],
    ):
        launcher.frontend_tools(frontend)


def test_build_failure_and_missing_output_clean_up_owned_process(tmp_path, monkeypatch):
    process = Mock()
    process.wait.return_value = 7
    monkeypatch.setattr(launcher, "_spawn", Mock(return_value=process))
    cleanup = Mock()
    monkeypatch.setattr(launcher, "stop_processes", cleanup)
    with pytest.raises(launcher.LaunchError, match="status 7"):
        launcher.build_frontend(tmp_path / "frontend", "/tools/npm")
    cleanup.assert_called_once_with([process])
    process.wait.return_value = 0
    with pytest.raises(launcher.LaunchError, match="no static/index.html"):
        launcher.build_frontend(tmp_path / "frontend", "/tools/npm")


@pytest.fixture
def children(monkeypatch):
    processes = [Mock(), Mock()]
    for process in processes:
        process.poll.return_value = None
    spawn = Mock(side_effect=processes)
    cleanup = Mock()
    monkeypatch.setattr(launcher, "_spawn", spawn)
    monkeypatch.setattr(launcher, "stop_processes", cleanup)
    return processes, spawn, cleanup


def test_dev_waits_for_direct_proxy_and_vite_readiness_before_opening(
    children, monkeypatch, tmp_path
):
    processes, spawn, cleanup = children
    probes = []

    def ready(url, **kwargs):
        probes.append(url)
        return len(probes) != 1

    monkeypatch.setattr(launcher, "_ready", ready)

    def opened(url):
        assert set(probes) == {
            "http://127.0.0.1:8018/api/health",
            "http://127.0.0.1:5188/api/health",
            "http://127.0.0.1:5188/@vite/client",
        }
        assert url == "http://127.0.0.1:5188/"

    browser = Mock(side_effect=opened)
    monkeypatch.setattr(launcher.webbrowser, "open", browser)

    def sleep(seconds):
        if seconds == 0.2:
            raise KeyboardInterrupt

    monkeypatch.setattr(launcher.time, "sleep", sleep)
    with pytest.raises(KeyboardInterrupt):
        launcher.run_development(tmp_path, "/tools/npm", 8018, 5188, "info", True)
    browser.assert_called_once()
    assert spawn.call_args_list[0].args[0][:3] == [sys.executable, "-m", "tradingagents_web"]
    assert spawn.call_args_list[1].kwargs["env"]["TRADINGAGENTS_WEB_BACKEND_PORT"] == "8018"
    assert "--strictPort" in spawn.call_args_list[1].args[0]
    cleanup.assert_called_once_with(processes)


@pytest.mark.parametrize("failure", ["backend", "frontend", "timeout", "spawn"])
def test_dev_failure_cleans_up_and_never_opens_browser(children, monkeypatch, tmp_path, failure):
    processes, spawn, cleanup = children
    browser = Mock()
    monkeypatch.setattr(launcher.webbrowser, "open", browser)
    monkeypatch.setattr(launcher, "_ready", lambda *args, **kwargs: False)
    if failure in {"backend", "frontend"}:
        processes[failure == "frontend"].poll.return_value = 9
    elif failure == "timeout":
        monkeypatch.setattr(launcher.time, "monotonic", Mock(side_effect=[0, 31]))
    else:
        spawn.side_effect = [processes[0], OSError("spawn failed")]
    with pytest.raises((launcher.LaunchError, OSError)):
        launcher.run_development(tmp_path, "/tools/npm", 8018, 5188, "info", True)
    browser.assert_not_called()
    cleanup.assert_called_once_with(processes[:1] if failure == "spawn" else processes)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX group cleanup contract")
def test_cleanup_targets_only_owned_groups_and_escalates_timeout(monkeypatch):
    process = Mock(pid=12345)
    process.wait.side_effect = [subprocess.TimeoutExpired("owned", 5), 0]
    kill = Mock()
    monkeypatch.setattr(launcher.os, "killpg", kill)
    launcher.stop_processes([process])
    assert kill.call_args_list[0].args == (12345, signal.SIGTERM)
    assert all(call.args[0] == 12345 for call in kill.call_args_list)
    assert any(call.args[1] == signal.SIGKILL for call in kill.call_args_list)


def test_static_browser_waits_for_server_startup_and_single_worker(tmp_path, monkeypatch):
    import uvicorn

    import tradingagents.default_config as defaults
    import tradingagents_web.app as application

    monkeypatch.setattr(
        defaults,
        "DEFAULT_CONFIG",
        {key: tmp_path / key for key in ("results_dir", "memory_log_path", "data_cache_dir")},
    )
    monkeypatch.setattr(application, "create_app", lambda settings: object())
    config = Mock()
    monkeypatch.setattr(uvicorn, "Config", config)
    opened = threading.Event()
    server = SimpleNamespace(started=False)

    def open_browser(url):
        assert server.started
        assert url == "http://127.0.0.1:8018/"
        opened.set()

    monkeypatch.setattr(cli.webbrowser, "open", open_browser)

    def run():
        assert not opened.is_set()
        server.started = True
        assert opened.wait(1)

    server.run = run
    monkeypatch.setattr(uvicorn, "Server", lambda configuration: server)
    assert cli._serve(8018, "warning", True) == 0
    assert config.call_args.kwargs["workers"] == 1
    assert config.call_args.kwargs["host"] == "127.0.0.1"
