"""Pure offline comparison API: NFR-CMP-001/002/003, ADR-002, INV-9, INV-WEB-001/014."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Request
from fastapi.responses import Response

from tradingagents.comparison import fixtures
from tradingagents.comparison.runner import pair_and_aggregate, replay_scripted_case
from tradingagents.comparison.schemas import TRACEABILITY_DIMENSIONS, PairingError, StrategyKey
from tradingagents_web.errors import error_response

router = APIRouter(prefix="/api/comparisons", tags=["comparisons"])
_CASES = {
    "D": ("No new evidence", "representative", fixtures.case_no_new_evidence),
    "E": ("New valid evidence", "representative", fixtures.case_new_evidence_extension),
    "F": ("Protect the summary", "representative", fixtures.case_budget_protection),
    "G": ("Input exhaustion", "regression", fixtures.case_input_exhaustion),
}


def _catalog():
    return [
        {"case_id": key, "title": title, "role": role, "identity": factory().identity.to_dict()}
        for key, (title, role, factory) in _CASES.items()
    ]


@router.get("")
def catalog(request: Request):
    return _bounded(
        request,
        {
            "schema_version": "1.0",
            "scope": "scripted_offline",
            "cases": _catalog(),
            "representative_cases": 3,
            "regression_cases": 1,
            "rubric_dimensions": list(TRACEABILITY_DIMENSIONS),
        },
    )


def _comparison(case_id: str, dynamic_case_id: str | None):
    if case_id not in _CASES or (dynamic_case_id is not None and dynamic_case_id not in _CASES):
        raise KeyError("unknown comparison case")
    title, role, factory = _CASES[case_id]
    scripted = factory()
    fixed = replay_scripted_case(scripted)[StrategyKey.FIXED]
    dynamic_case = _CASES[dynamic_case_id or case_id][2]()
    dynamic = replay_scripted_case(dynamic_case)[StrategyKey.DYNAMIC]
    # The core owns four-part identity validation and every derived metric.
    report = pair_and_aggregate([fixed, dynamic])
    return {
        "schema_version": "1.0",
        "scope": "scripted_offline",
        "case_id": case_id,
        "dynamic_case_id": dynamic_case_id or case_id,
        "title": title,
        "role": role,
        "identity": scripted.identity.to_dict(),
        "policy": asdict(scripted.config),
        "fixed": fixed.to_dict(),
        "dynamic": dynamic.to_dict(),
        "report": report.to_dict(),
        "rubric_dimensions": list(TRACEABILITY_DIMENSIONS),
    }


def _bounded(request: Request, result: dict):
    if (
        len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        > request.app.state.settings.max_report_bytes
    ):
        return error_response(413, "storage", "comparison exceeds the response limit")
    return result


def _result(request: Request, case_id: str, dynamic_case_id: str | None):
    try:
        return _bounded(request, _comparison(case_id, dynamic_case_id))
    except KeyError:
        return error_response(404, "not_found", "comparison case not found")
    except PairingError:
        return error_response(
            422,
            "validation",
            "Comparison case identities do not match.",
            reason="identity_mismatch",
        )


@router.get("/{case_id}")
def case_result(request: Request, case_id: str, dynamic_case_id: str | None = None):
    return _result(request, case_id, dynamic_case_id)


@router.get("/{case_id}/download")
def download(request: Request, case_id: str, dynamic_case_id: str | None = None):
    result = _result(request, case_id, dynamic_case_id)
    if isinstance(result, Response):
        return result
    content = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if len(content.encode()) > request.app.state.settings.max_report_bytes:
        return error_response(413, "storage", "comparison exceeds the response limit")
    return Response(
        content,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="scripted-comparison-{case_id}.json"'
        },
    )
