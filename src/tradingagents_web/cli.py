"""Command-line entry point for the read-only WebUI."""

from __future__ import annotations

import argparse
import webbrowser

import uvicorn

from tradingagents.default_config import DEFAULT_CONFIG

from .app import create_app
from .settings import WebSettings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="TradingAgents WebUI (read-only history/report browser)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host only")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="Open the browser")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    settings = WebSettings(
        results_dir=DEFAULT_CONFIG["results_dir"],
        memory_log_path=DEFAULT_CONFIG["memory_log_path"],
        data_cache_dir=DEFAULT_CONFIG["data_cache_dir"],
        host=args.host,
    )
    app = create_app(settings)
    url = f"http://{args.host}:{args.port}/"
    print(f"TradingAgents WebUI: {url}")
    print("Serving only existing artifacts; analysis runs are not available in Iteration 1.")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        workers=1,
    )
    return 0
