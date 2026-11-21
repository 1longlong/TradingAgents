"""WebUI startup: REQ-WEB-020/026, ADR-002/003, INV-WEB-001/013/015."""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path

from .launcher import LaunchError, build_frontend, check_port, frontend_tools, run_development


def _port(value: str) -> int:
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return port
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("port must be an integer between 1 and 65535")


def _serve(port: int, log_level: str, open_browser: bool) -> int:
    import uvicorn

    from tradingagents.default_config import DEFAULT_CONFIG

    from .app import create_app
    from .settings import WebSettings

    settings = WebSettings(
        results_dir=DEFAULT_CONFIG["results_dir"],
        memory_log_path=DEFAULT_CONFIG["memory_log_path"],
        data_cache_dir=DEFAULT_CONFIG["data_cache_dir"],
        host="127.0.0.1",
    )
    app = create_app(settings)
    url = f"http://127.0.0.1:{port}/"
    print(f"TradingAgents WebUI: {url}", flush=True)
    print("Serving local analysis, backtest, and existing artifacts.", flush=True)
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level=log_level, workers=1)
    )
    stopped = threading.Event()

    def open_when_ready():
        while not stopped.wait(0.05):
            if server.started:
                webbrowser.open(url)
                return

    browser = threading.Thread(target=open_when_ready, daemon=True) if open_browser else None
    if browser:
        browser.start()
    try:
        server.run()
    finally:
        stopped.set()
        if browser:
            browser.join(timeout=1)
    return 0 if server.started else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradingAgents WebUI (analysis, backtest, and history)"
    )
    parser.add_argument(
        "--host",
        choices=("127.0.0.1", "localhost"),
        default="127.0.0.1",
        help="Loopback only; localhost is an alias for 127.0.0.1",
    )
    parser.add_argument("--port", type=_port, default=8000, help="Backend port (default: 8000)")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dev", action="store_true", help="Start backend and Vite with frontend hot reload"
    )
    modes.add_argument("--build", action="store_true", help="Build the frontend before serving it")
    parser.add_argument("--frontend-port", type=_port, help="Vite port for --dev (default: 5173)")
    parser.add_argument("--open", action="store_true", help="Open the browser")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    if args.frontend_port is not None and not args.dev:
        parser.error("--frontend-port requires --dev")
    frontend_port = args.frontend_port or 5173
    if args.dev and args.port == frontend_port:
        parser.error("backend and frontend ports must be different")
    try:
        check_port(args.port)
        if args.dev:
            check_port(frontend_port)
        if args.dev or args.build:
            frontend = Path(__file__).resolve().parent / "frontend"
            npm = frontend_tools(frontend)
            if args.dev:
                return run_development(
                    frontend, npm, args.port, frontend_port, args.log_level, args.open
                )
            build_frontend(frontend, npm)
        return _serve(args.port, args.log_level, args.open)
    except (LaunchError, OSError) as exc:
        parser.exit(1, f"WebUI startup failed: {exc}\n")
    except KeyboardInterrupt:
        print("\nWebUI stopped.", flush=True)
        return 130
