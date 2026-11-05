"""FastAPI application factory for the read-only WebUI."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from tradingagents_web import __version__
from tradingagents_web.api import health, history
from tradingagents_web.errors import error_response
from tradingagents_web.security import host_allowed, security_headers
from tradingagents_web.settings import WebSettings


def create_app(settings: WebSettings) -> FastAPI:
    app = FastAPI(
        title="TradingAgents WebUI",
        version=__version__,
        docs_url=None,
        redoc_url=None,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def _security_middleware(request: Request, call_next):
        if not host_allowed(request.headers.get("host")):
            response = error_response(400, "validation", "invalid host")
            for key, value in security_headers().items():
                response.headers[key] = value
            return response
        response = await call_next(request)
        for key, value in security_headers().items():
            response.headers[key] = value
        return response

    app.include_router(health.router)
    app.include_router(history.router)

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
            if candidate.is_file() and candidate.resolve().is_relative_to(
                static_dir.resolve()
            ):
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
