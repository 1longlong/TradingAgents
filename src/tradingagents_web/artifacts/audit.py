"""Bounded audit projections: REQ-WEB-008/009/024, ADR-002, INV-WEB-003/004/005.

Only canonical core artifact families are readable. JSON/text is public data,
never a path, prompt or execution instruction. Core decisions are not recomputed.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from tradingagents.debate.evidence_manifest import EvidenceManifest
from tradingagents.report_artifacts import redact_secrets
from tradingagents_web.security import collect_secrets, redact_text

from .downloads import ArtifactUnavailable, FileTooLarge
from .index import Artifact

AUDIT_FILES = {
    "evidence_manifest": "0_quality/evidence_manifest.json",
    "gate_summary": "0_quality/gate_summary.md",
    "debate_trace": "2_research/debate_trace.json",
    "run_summary": "run_summary.json",
}
_PRIVATE_KEYS = {
    "config",
    "portfolio",
    "portfolio_json",
    "portfolio_context",
    "messages",
    "prompts",
    "raw_prompt",
    "raw_response",
    "headers",
    "backend_url",
    "password",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
    "checkpoint_path",
}
_URL = re.compile(r"https?://[^\s<>\"']+")
_ABSOLUTE_LOCATION = re.compile(r"(?<![\w:/])/(?:[^/\s\[\]\"'<>]+/)+[^\s\[\]\"'<>]*")
_WINDOWS_LOCATION = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>]*")


def _public_url(match: re.Match[str]) -> str:
    try:
        parsed = urlsplit(match.group())
        host = parsed.hostname or ""
        if parsed.port:
            host += f":{parsed.port}"
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return "[REDACTED URL]"


def public_data(value: Any, secrets: tuple[str, ...] | None = None, _depth: int = 0) -> Any:
    """Remove secret/path authority without filling absent audit values."""
    if _depth > 48:
        raise ValueError("audit nesting exceeds the projection limit")
    secrets = collect_secrets() if secrets is None else secrets
    if isinstance(value, str):
        text = redact_text(redact_secrets(value), secrets)
        if text.startswith("/") or PureWindowsPath(text).is_absolute():
            return "[REDACTED PATH]"
        text = _URL.sub(_public_url, text)
        text = _WINDOWS_LOCATION.sub("[REDACTED PATH]", text)
        return _ABSOLUTE_LOCATION.sub("[REDACTED PATH]", text)
    if isinstance(value, list):
        return [public_data(child, secrets, _depth + 1) for child in value]
    if isinstance(value, dict):
        projected = {}
        for key, child in value.items():
            if key.lower() in _PRIVATE_KEYS or key.lower().endswith(("_api_key", "_password")):
                continue
            if public_data(key, secrets) != key:
                continue
            if key == "report_paths":
                child = (
                    {
                        name: path
                        for name, path in child.items()
                        if name in AUDIT_FILES and path == AUDIT_FILES[name]
                    }
                    if isinstance(child, dict)
                    else {}
                )
            projected[key] = public_data(child, secrets, _depth + 1)
        return projected
    return value


@contextmanager
def _analysis_root(artifact: Artifact, results_dir: Path):
    if artifact.source not in {"run", "saved"}:
        raise ArtifactUnavailable("analysis audit is unavailable")
    with ExitStack() as stack:
        try:
            relative = artifact.path.absolute().relative_to(results_dir.absolute())
            if ".." in relative.parts or not hasattr(os, "O_NOFOLLOW"):
                raise ValueError("invalid root")
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            descriptor = os.open(results_dir.resolve(strict=True), flags)
            stack.callback(os.close, descriptor)
            for component in relative.parts:
                descriptor = os.open(component, flags, dir_fd=descriptor)
                stack.callback(os.close, descriptor)
        except (OSError, ValueError) as exc:
            raise ArtifactUnavailable("analysis audit is unavailable") from exc
        yield descriptor


def _read_at(root: int, relative: str, maximum: int) -> tuple[str, int]:
    with ExitStack() as stack:
        parts = Path(relative).parts
        directory = root
        for component in parts[:-1]:
            directory = os.open(
                component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
            )
            stack.callback(os.close, directory)
        descriptor = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
        )
        stream = stack.enter_context(os.fdopen(descriptor, "rb"))
        details = os.fstat(stream.fileno())
        if not stat.S_ISREG(details.st_mode):
            raise OSError("not a regular file")
        if details.st_size > maximum:
            raise FileTooLarge("audit exceeds response limit")
        raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            raise FileTooLarge("audit exceeds response limit")
        return raw.decode("utf-8"), len(raw)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON constant")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("non-finite JSON number")
    return parsed


def _decode(content: str, filename: str) -> Any:
    if filename.endswith(".md"):
        return content
    result = json.loads(
        content,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )
    if not isinstance(result, dict):
        raise ValueError("audit JSON must be an object")
    return result


def _audit_identity(artifact: Artifact, data: dict) -> tuple[str | None, list[str], list[str]]:
    summary = data.get("run_summary") or {}
    manifest = data.get("evidence_manifest") or {}
    issues = []
    if summary.get("ticker") and summary["ticker"] != artifact.ticker:
        issues.append("ticker_mismatch")
    # A saved report's indexed date is its save date, not an analysis cutoff.
    raw_target = summary.get("trade_date") or (artifact.date if artifact.source == "run" else None)
    target: str | None
    try:
        if not isinstance(raw_target, str):
            raise ValueError("missing analysis cutoff")
        target = date.fromisoformat(raw_target).isoformat()
    except (ValueError, TypeError):
        target = None
        issues.append("invalid_trade_date")
    if target and artifact.source == "run" and artifact.date and target != artifact.date:
        issues.append("trade_date_mismatch")
    gate_decision = manifest.get("gate_decision")
    if not isinstance(gate_decision, dict):
        gate_decision = {}
    confidence_cap = summary.get("confidence_cap")
    if not isinstance(confidence_cap, dict):
        confidence_cap = {}
    verdicts = {
        value
        for value in (
            manifest.get("verdict"),
            summary.get("gate_verdict"),
            gate_decision.get("decision"),
            confidence_cap.get("verdict"),
        )
        if isinstance(value, str) and value in {"normal", "degraded", "blocked"}
    }
    if len(verdicts) > 1:
        issues.append("gate_verdict_mismatch")
    records = manifest.get("evidence_records")
    records = (
        [item for item in records if isinstance(item, dict)] if isinstance(records, list) else []
    )
    identifiers = [
        item.get("evidence_id") for item in records if isinstance(item.get("evidence_id"), str)
    ]
    if len(set(identifiers)) != len(identifiers):
        issues.append("duplicate_evidence_id")
    records = [item for item in records if isinstance(item.get("evidence_id"), str)]
    evidence = EvidenceManifest.from_records(records)
    eligible = (
        [key for key in evidence.valid_ids if evidence.observed_at_not_later_than(key, target)]
        if not issues
        else []
    )
    return target, issues, eligible


def audit_view(artifact: Artifact, settings) -> dict:
    """Read four independent families; absence/invalidity never implies success."""
    families, data = [], {}
    remaining = settings.max_report_bytes
    with _analysis_root(artifact, settings.results_dir) as root:
        for kind, filename in AUDIT_FILES.items():
            status = "available"
            try:
                content, length = _read_at(root, filename, remaining)
                remaining -= length
                data[kind] = public_data(_decode(content, filename))
            except FileNotFoundError:
                status = "missing"
            except (UnicodeError, ValueError, RecursionError):
                status = "invalid"
            except OSError:
                status = "unavailable"
            families.append(
                {
                    "kind": kind,
                    "filename": filename,
                    "status": status,
                    "available": status == "available",
                }
            )
    count = len(data)
    availability = (
        "complete"
        if count == len(AUDIT_FILES)
        else "partial"
        if count
        else ("absent" if all(item["status"] == "missing" for item in families) else "unavailable")
    )
    target, issues, eligible = _audit_identity(artifact, data)
    result = {
        "schema_version": "1.0",
        "artifact_id": artifact.artifact_id,
        "ticker": artifact.ticker,
        "trade_date": target,
        "recorded_date": artifact.date,
        "source": artifact.source,
        "status": artifact.status,
        "rating": artifact.rating,
        "available": bool(count),
        "artifact_availability": availability,
        "artifacts": families,
        "data": data,
        "sanitized": True,
        "consistency": {"status": "inconsistent" if issues else "recorded", "issues": issues},
        "eligible_evidence_ids": eligible,
    }
    if (
        len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        > settings.max_report_bytes
    ):
        raise FileTooLarge("audit exceeds response limit")
    return result


def audit_artifact(artifact: Artifact, settings, kind: str) -> tuple[str, str, str]:
    """Preview/download the same sanitized family; no arbitrary paths accepted."""
    filename = AUDIT_FILES.get(kind)
    if filename is None:
        raise ArtifactUnavailable("audit family is unavailable")
    try:
        with _analysis_root(artifact, settings.results_dir) as root:
            content, _ = _read_at(root, filename, settings.max_report_bytes)
        value = public_data(_decode(content, filename))
        rendered = (
            value
            if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        )
        if len(rendered.encode()) > settings.max_report_bytes:
            raise FileTooLarge("audit exceeds response limit")
        return (
            rendered,
            "text/markdown" if filename.endswith(".md") else "application/json",
            Path(filename).name,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("audit artifact is invalid") from exc
    except OSError as exc:
        raise ArtifactUnavailable("audit family is unavailable") from exc
