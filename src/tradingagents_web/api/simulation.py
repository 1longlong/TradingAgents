"""FR-TRD-001..006, INV-TRD-001..003; ADR-001-simulated-trading-system.md."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from trading.models import AuditIntegrityError, PersistenceError, TradingError
from tradingagents_web.artifacts.audit import public_data
from tradingagents_web.artifacts.downloads import ArtifactUnavailable, FileTooLarge, section_file
from tradingagents_web.artifacts.index import ArtifactIndex
from tradingagents_web.errors import error_response
from tradingagents_web.models.simulation_requests import (
    AccountInput,
    SimulationApprovalInput,
    SimulationDecisionInput,
    SimulationError,
    SimulationJobInput,
)
from tradingagents_web.runtime.coordinator import RunConflict


class SimulationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request):
            try:
                return await handler(request)
            except RunConflict as exc:
                return error_response(
                    409,
                    "conflict",
                    "Another workspace task is active.",
                    active_run_id=exc.active_run_id,
                )
            except SimulationError as exc:
                return error_response(409, "simulation", str(exc))
            except RequestValidationError:
                return error_response(
                    422, "validation", "Invalid simulation request fields or types."
                )
            except (AuditIntegrityError, PersistenceError, OSError):
                return error_response(
                    409,
                    "storage",
                    "Simulation storage failed validation. No further changes are allowed until it is reconciled.",
                )
            except (TradingError, ValueError, ArtifactUnavailable, FileTooLarge):
                return error_response(
                    422,
                    "validation",
                    "The simulated operation was rejected. Check the report, quote, account version and approval expiry.",
                )

        return guarded


router = APIRouter(prefix="/api/simulation", tags=["simulation"], route_class=SimulationRoute)


def service(request):
    value = request.app.state.simulation
    if value is None:
        raise SimulationError(
            "Simulated trading is unavailable on this platform; the existing trading core requires POSIX file locking."
        )
    return value


@router.get("")
def state(request: Request):
    return public_data(service(request).state())


@router.post("/account")
def account(request: Request, body: AccountInput):
    return public_data(service(request).account(body))


@router.get("/reports")
def reports(request: Request):
    items = []
    for artifact in ArtifactIndex(request.app.state.settings).scan():
        if artifact.source not in {"run", "saved"} or artifact.status != "completed":
            continue
        try:
            section_file(
                artifact,
                "final_trade_decision" if artifact.source == "run" else "5_portfolio/decision",
            )
        except ArtifactUnavailable:
            continue
        items.append(artifact.to_item())
        if len(items) == 200:
            break
    return {"items": public_data(items)}


@router.post("/decisions")
def decision(request: Request, body: SimulationDecisionInput):
    return public_data(service(request).decision(body))


@router.post("/approvals/{request_id}")
def approve(request: Request, request_id: str, body: SimulationApprovalInput):
    return public_data(service(request).approve(request_id, body))


@router.get("/audit")
def audit(
    request: Request,
    run_id: str | None = None,
    event_type: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return public_data(
        service(request).audit(run_id=run_id, kind=event_type, offset=offset, limit=limit)
    )


@router.get("/jobs")
def jobs(request: Request):
    return {"items": public_data(service(request).jobs.list())}


@router.get("/jobs/{job_id}")
def job(request: Request, job_id: str):
    return public_data(service(request).jobs.get(job_id))


@router.post("/jobs", status_code=202)
def start_job(request: Request, body: SimulationJobInput):
    return public_data(service(request).jobs.start(body))
