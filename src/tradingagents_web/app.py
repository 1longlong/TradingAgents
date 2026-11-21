"""FastAPI application factory for the WebUI."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from tradingagents_web import __version__
from tradingagents_web.api import (
    announcements,
    audit,
    backtests,
    checkpoints,
    comparisons,
    config,
    health,
    history,
    portfolio,
    runs,
    session,
    simulation,
)
from tradingagents_web.errors import error_response
from tradingagents_web.runtime.coordinator import RunCoordinator
from tradingagents_web.runtime.graph_runner import GraphRunner
from tradingagents_web.runtime.model_catalog import OpenRouterCatalog
from tradingagents_web.security import (
    csrf_path,
    host_allowed,
    origin_allowed,
    security_headers,
)
from tradingagents_web.settings import WebSettings


def _secured(response):
    for key, value in security_headers().items():
        response.headers[key] = value
    return response


def create_app(settings: WebSettings, runner_factory=None) -> FastAPI:
    app = FastAPI(
        title="TradingAgents WebUI",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.coordinator = RunCoordinator(settings, runner_factory or GraphRunner)
    app.state.announcement_cache = None
    app.state.openrouter_catalog = OpenRouterCatalog()
    app.state.simulation = None
    if sys.platform != "win32":
        from tradingagents_web.runtime.simulation import SimulationService

        app.state.simulation = SimulationService(settings, app.state.coordinator)
        app.router.add_event_handler("shutdown", app.state.simulation.close)

    @app.middleware("http")
    async def _security_middleware(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            return _secured(error_response(400, "validation", "invalid host"))

        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and csrf_path(request.url.path):
            token = request.headers.get("x-csrf-token")
            if not token or token != app.state.csrf_token:
                return _secured(error_response(403, "security", "missing or invalid CSRF token"))
            origin = request.headers.get("origin")
            if origin and not origin_allowed(origin):
                return _secured(error_response(403, "security", "cross-origin request rejected"))

        response = await call_next(request)
        return _secured(response)

    for router in (
        session.router,
        config.router,
        portfolio.router,
        checkpoints.router,
        runs.router,
        backtests.router,
        announcements.router,
        health.router,
        history.router,
        audit.router,
        comparisons.router,
        simulation.router,
    ):
        app.include_router(router)

    static_dir = Path(settings.static_dir)
    index = static_dir / "index.html"
    if index.is_file():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path == "api" or full_path.startswith("api/"):
                return error_response(404, "not_found", "not found")
            candidate = static_dir / full_path
            if candidate.is_file() and candidate.resolve().is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(index)

    else:

        @app.get("/", include_in_schema=False)
        async def missing_static():
            return PlainTextResponse(
                "Frontend build missing. Run `npm run build` in "
                "src/tradingagents_web/frontend before starting the WebUI.",
                status_code=503,
            )

    return app
