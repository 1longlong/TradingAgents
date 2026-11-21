"""Local startup supervision: ADR-002/003, REQ-WEB-020/026, INV-WEB-001/013/015.

Uses installed tools only. Readiness never invokes a provider or reads user
artifacts; shutdown targets only process groups created by this launcher.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import webbrowser
from contextlib import contextmanager, suppress
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


class LaunchError(RuntimeError):
    """An actionable local prerequisite or service-lifecycle failure."""


def check_port(port: int) -> None:
    """Refuse occupied loopback ports; never stop their existing listeners."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
    except OSError as exc:
        raise LaunchError(f"Port {port} is unavailable. Choose another port.") from exc


def frontend_tools(frontend: Path) -> str:
    """Check the source checkout and existing toolchain without installing it."""
    if not (frontend / "package.json").is_file():
        raise LaunchError("This mode requires a source checkout with the frontend directory.")
    npm = shutil.which("npm")
    if not npm or not shutil.which("node"):
        raise LaunchError("Node.js and npm are required. Install the README prerequisites first.")
    if not (frontend / "node_modules" / "vite" / "package.json").is_file():
        raise LaunchError(
            "Frontend dependencies are missing. Run npm ci in the frontend directory."
        )
    return npm


@contextmanager
def _interrupts():
    def stop(signum, frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _spawn(command: list[str], *, cwd: Path | None = None, env=None):
    # Separate owned groups let Ctrl+C clean up npm's Node child as well.
    if os.name == "posix":
        return subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)
    return subprocess.Popen(
        command, cwd=cwd, env=env, creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    )


def stop_processes(processes) -> None:
    """Terminate only owned groups, including descendants of an exited wrapper."""
    for process in reversed(processes):
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        elif process.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
    for process in reversed(processes):
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name != "posix":
                process.kill()
            else:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        # A wrapper may exit before a descendant; don't leave its group behind.
        if os.name == "posix":
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)


def build_frontend(frontend: Path, npm: str) -> None:
    """Run the existing build; a failed build must never start a stale UI."""
    processes = []
    with _interrupts():
        try:
            processes.append(_spawn([npm, "run", "build"], cwd=frontend))
            code = processes[0].wait()
            if code:
                raise LaunchError(f"Frontend build failed with status {code}. Server not started.")
        finally:
            stop_processes(processes)
    if not (frontend.parent / "static" / "index.html").is_file():
        raise LaunchError("Frontend build produced no static/index.html. Server not started.")


def _ready(url: str, *, health: bool = False) -> bool:
    # Loopback requests must not go through an environment-configured proxy.
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=0.3) as response:
            if response.status != 200:
                return False
            return not health or json.loads(response.read(4096)).get("status") == "ok"
    except (OSError, URLError, ValueError, AttributeError):
        return False


def _check_children(processes) -> None:
    for name, process in zip(("Backend", "Frontend"), processes, strict=True):
        code = process.poll()
        if code is not None:
            raise LaunchError(f"{name} exited with status {code}.")


def run_development(
    frontend: Path,
    npm: str,
    port: int,
    frontend_port: int,
    log_level: str,
    open_browser: bool,
    *,
    timeout: float = 30,
) -> int:
    """Supervise one backend and Vite; preserve single-worker API semantics."""
    backend_url = f"http://127.0.0.1:{port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    processes = []
    with _interrupts():
        try:
            processes.append(
                _spawn(
                    [
                        sys.executable,
                        "-m",
                        "tradingagents_web",
                        "--port",
                        str(port),
                        "--log-level",
                        log_level,
                    ]
                )
            )
            env = dict(os.environ, TRADINGAGENTS_WEB_BACKEND_PORT=str(port))
            processes.append(
                _spawn(
                    [
                        npm,
                        "run",
                        "dev",
                        "--",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(frontend_port),
                        "--strictPort",
                    ],
                    cwd=frontend,
                    env=env,
                )
            )
            deadline = time.monotonic() + timeout
            while True:
                _check_children(processes)
                if (
                    _ready(backend_url + "/api/health", health=True)
                    and _ready(frontend_url + "/@vite/client")
                    and _ready(frontend_url + "/api/health", health=True)
                ):
                    _check_children(processes)
                    break
                if time.monotonic() >= deadline:
                    raise LaunchError("Services did not become ready before the startup timeout.")
                time.sleep(0.1)
            print(f"Frontend ready: {frontend_url}/", flush=True)
            print(f"Backend ready:  {backend_url}/api/health", flush=True)
            print(
                "Frontend hot reload is enabled. Restart this command after backend edits.",
                flush=True,
            )
            print("Press Ctrl+C to stop both services.", flush=True)
            if open_browser:
                webbrowser.open(frontend_url + "/")
            while True:
                _check_children(processes)
                time.sleep(0.2)
        finally:
            stop_processes(processes)
