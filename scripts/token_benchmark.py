#!/usr/bin/env python3
"""Token benchmark harness for repeated, reproducible TradingAgents runs.

This is benchmark tooling only. It is a consumer of the existing programmatic
TradingAgents execution path (``TradingAgentsGraph.propagate``) and the existing
observability telemetry JSON. It does NOT modify any business behavior, prompts,
tools, routing, or the telemetry schema.

Commands
--------
init
    Create an experiment directory with a starter ``experiment.json`` and
    ``notes.md`` (canonical NVDA / 2026-09-23 baseline).
validate
    Validate an experiment definition without calling any LLM.
run
    Run each case ``measured_runs`` times (each in a fresh subprocess), collect
    telemetry, and write ``summary.json`` / ``summary.csv`` / ``summary.md``.
summarize
    Rebuild the summary files from already-stored telemetry (no LLM calls).
compare
    Compare a candidate experiment's summary against a baseline summary.
_run-single
    Hidden: execute ONE measured run in the current process (invoked by ``run``
    in a fresh subprocess for process isolation).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
from collections.abc import MutableMapping
from datetime import datetime, timezone
from pathlib import Path

# The repository root must be importable so ``tradingagents`` resolves no matter
# which directory this script is launched from (the shell wrapper runs it from
# the repo root, but callers may invoke it by absolute path).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tradingagents.dataflows.utils import safe_ticker_component

# Kept in sync with the telemetry payload consumers expect. Bump only when the
# experiment/summary format changes deliberately.
TOOL_SCHEMA_VERSION = 1

# Valid analyst wire keys as used by ``GraphSetup`` / ``TradingAgentsGraph``.
VALID_ANALYSTS = ("market", "social", "news", "fundamentals")

# Stable agent id -> human-readable display name (for reports). Mirrors the
# observability NODE_TO_AGENT inverse ordering (id -> display).
AGENT_DISPLAY = {
    "market_analyst": "Market Analyst",
    "sentiment_analyst": "Sentiment Analyst",
    "news_analyst": "News Analyst",
    "fundamentals_analyst": "Fundamentals Analyst",
    "bull_researcher": "Bull Researcher",
    "bear_researcher": "Bear Researcher",
    "research_manager": "Research Manager",
    "trader": "Trader",
    "aggressive_analyst": "Aggressive Analyst",
    "conservative_analyst": "Conservative Analyst",
    "neutral_analyst": "Neutral Analyst",
    "portfolio_manager": "Portfolio Manager",
    "unattributed": "(unattributed)",
}
# Analysts in their natural graph order (used to order the "execution" agents in
# reports before the debate/management agents).
_ANALYST_DISPLAY_ORDER = [
    "Market Analyst", "Sentiment Analyst", "News Analyst", "Fundamentals Analyst",
    "Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
    "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst",
    "Portfolio Manager",
]
_UNATTRIBUTED_LABEL = "(unattributed)"

EXPERIMENT_FILE = "experiment.json"
NOTE_FILE = "notes.md"
CODE_STATE_FILE = "code_state.json"
RUNS_DIR = "runs"
# A run may be retried after an invalid attempt. Each attempt gets its own
# directory (runs/run_NN/attempt_MM) so a retry can never overwrite the failed
# attempt or reuse its artifacts / provider cache.
ATTEMPT_DIR_GLOB = "attempt_*"
# Marks a run directory as already attempted, so an aborted experiment can be
# resumed without overwriting (or silently reusing) earlier attempts.
RUN_STATE_FILE = "run_state.json"
METADATA_FILE = "metadata.json"
TELEMETRY_FILE = "telemetry.json"
RUNNER_REPORT_FILE = "runner_report.json"
SUMMARY_JSON = "summary.json"
SUMMARY_CSV = "summary.csv"
SUMMARY_AGENTS_CSV = "summary_agents.csv"
SUMMARY_MD = "summary.md"
SUMMARY_INDEX_JSON = "summary_index.json"
# Written by ``measure``: the machine-readable verdict of the one-shot run.
MEASUREMENT_STATUS_FILE = "measurement_status.json"

# Bumped whenever the file enumeration / hashing rules below change, so two
# ``working_tree_sha256`` values are only ever compared when they were produced
# by the same algorithm.
FINGERPRINT_ALGORITHM = f"working-tree-sha256-v{TOOL_SCHEMA_VERSION}"

# Only code that can change a measured number is fingerprinted. Data caches,
# generated output and the benchmark artifacts themselves are excluded by
# policy (see ``_FINGERPRINT_EXCLUDE_PREFIXES``), so the harness can refresh a
# cache or write telemetry without invalidating its own fingerprint.
_FINGERPRINT_INCLUDE_PREFIXES = (
    "tradingagents/",
    "cli/",
    "scripts/",
    "tests/",
    "token_benchmarks/baseline_v1/experiment.json",
    "token_benchmarks/baseline_v2/experiment.json",
)
_FINGERPRINT_ROOT_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "pytest.ini",
    "mypy.ini",
    "tox.ini",
    "run_cli.py",
)
# Cheap, extension-independent protection: a credential file is never hashed
# even if somebody force-adds it to the index.
_FINGERPRINT_SECRET_NAMES = frozenset({
    ".env", ".env.local", ".env.enterprise", ".env_secrets", ".envrc",
})
_FINGERPRINT_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")
_FINGERPRINT_EXCLUDE_PREFIXES = (
    # Raw benchmark evidence and generated reports: writing them must never
    # change the fingerprint of the code that produced them.
    "token_benchmarks/measurements/",
    "token_benchmarks/cases/",
    "runs/",
    "cases/",
    # Caches / runtime state.
    "data_cache/",
    "reports/",
    ".venv/",
    ".git/",
    "__pycache__/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".mypy_cache/",
    ".tox/",
    "node_modules/",
)
# Directory name fragments that identify a backup by convention.
_FINGERPRINT_BACKUP_DIR_MARKERS = ("backup", ".bak", ".orig")
_FINGERPRINT_EXCLUDE_SUFFIXES = (
    ".pyc", ".pyo", ".pyd", ".log", ".tmp", ".swp", ".bak", ".orig",
)
_FINGERPRINT_EXCLUDE_NAMES = frozenset({
    CODE_STATE_FILE,
    SUMMARY_INDEX_JSON,
    MEASUREMENT_STATUS_FILE,
    "summary.json",
    "summary.csv",
    "summary.md",
    "summary_agents.csv",
})


# ---------------------------------------------------------------------------
# Experiment definition / validation
# ---------------------------------------------------------------------------
def default_experiment(experiment_id: str, output_root: Path) -> dict:
    """Return the canonical starter baseline experiment definition."""
    return {
        "schema_version": TOOL_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "description": "Observability baseline before token optimization",
        "measured_runs": 5,
        "cases": [
            {
                "case_id": "nvda_2026_09_23",
                "ticker": "NVDA",
                "trade_date": "2026-09-23",
                "analysts": list(VALID_ANALYSTS),
                "research_rounds": 1,
                "risk_rounds": 1,
            }
        ],
        "provider": "openai_compatible",
        "quick_model": "CS5351/DeepSeek-V4-Flash",
        "deep_model": "CS5351/DeepSeek-V4-Flash",
        "output_language": "English",
        "cache_policy": "preserve_existing",
    }


def default_notes(experiment_id: str) -> str:
    """Return the human-authored starter notes for an experiment."""
    return f"""# {experiment_id}

## Purpose

Establish the token-consumption baseline before optimization.

## Changes

No token optimization.
Observability-only baseline.

## Hypothesis

N/A — baseline measurement.

## Compared with

None.
"""


def validate_trade_date(value) -> str:
    """Return the canonical ``YYYY-MM-DD`` date or raise ``ValueError``.

    Explicit dates only. ``today`` / empty / implicit-now are rejected to keep
    experiments reproducible.
    """
    if value is None:
        raise ValueError("trade_date must be an explicit ISO date YYYY-MM-DD")
    s = str(value).strip()
    if not s:
        raise ValueError("trade_date must be an explicit ISO date YYYY-MM-DD")
    try:
        canonical = datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d") == s
    except ValueError:
        canonical = False
    if not canonical:
        raise ValueError(f"trade_date must be an explicit ISO date YYYY-MM-DD, got {value!r}")
    return s


def validate_ticker(value) -> str:
    """Return the explicit non-empty ticker or raise ``ValueError``."""
    if value is None:
        raise ValueError("ticker must be explicit")
    s = str(value).strip()
    if not s:
        raise ValueError("ticker must be explicit")
    return s


def validate_experiment(data: dict) -> list[str]:
    """Validate an experiment definition; return a list of error strings.

    Raises ``ValueError`` for structurally non-dict input. Never calls an LLM or
    any external service. Only non-secret validation occurs here.
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        raise ValueError("experiment definition must be a JSON object")

    exp_id = data.get("experiment_id")
    if not exp_id or not str(exp_id).strip():
        errors.append("experiment_id is required")

    if "description" not in data:
        errors.append("description is required")

    measured = data.get("measured_runs")
    if not isinstance(measured, int) or isinstance(measured, bool) or measured < 1:
        errors.append("measured_runs must be an integer >= 1")

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
    else:
        case_ids = set()
        for i, case in enumerate(cases):
            if not isinstance(case, dict):
                errors.append(f"cases[{i}] must be an object")
                continue
            prefix = f"cases[{i}]"
            case_id = case.get("case_id")
            if not case_id or not str(case_id).strip():
                errors.append(f"{prefix}.case_id is required")
            elif case_id in case_ids:
                errors.append(f"{prefix}.case_id {case_id!r} is duplicated")
            else:
                case_ids.add(case_id)
            try:
                validate_ticker(case.get("ticker"))
            except ValueError as exc:
                errors.append(f"{prefix}.ticker: {exc}")
            try:
                validate_trade_date(case.get("trade_date"))
            except ValueError as exc:
                errors.append(f"{prefix}.trade_date: {exc}")
            analysts = case.get("analysts")
            if not isinstance(analysts, list) or not analysts:
                errors.append(f"{prefix}.analysts must be a non-empty list")
            else:
                for a in analysts:
                    if a not in VALID_ANALYSTS:
                        errors.append(
                            f"{prefix}.analysts contains invalid key {a!r} (valid: "
                            f"{', '.join(VALID_ANALYSTS)})"
                        )
            for field in ("research_rounds", "risk_rounds"):
                val = case.get(field)
                if not isinstance(val, int) or isinstance(val, bool) or val < 1:
                    errors.append(f"{prefix}.{field} must be an integer >= 1")

    for field in ("provider", "quick_model", "deep_model"):
        if not data.get(field):
            errors.append(f"{field} is required")

    cache = data.get("cache_policy")
    if cache not in ("preserve_existing",):
        errors.append(
            "cache_policy must be 'preserve_existing' (only supported value)"
        )

    if data.get("schema_version") not in (None, TOOL_SCHEMA_VERSION):
        errors.append(
            f"schema_version must be {TOOL_SCHEMA_VERSION} got {data.get('schema_version')!r}"
        )

    return errors


def case_signature(exp: dict, case: dict) -> tuple:
    """Return a reproducible signature of a case's material benchmark inputs.

    Two experiments with the same signature are directly comparable; a mismatch
    blocks an unconditional comparison.
    """
    return (
        validate_ticker(case.get("ticker")),
        validate_trade_date(case.get("trade_date")),
        tuple(case.get("analysts") or []),
        case.get("research_rounds"),
        case.get("risk_rounds"),
        exp.get("provider"),
        exp.get("quick_model"),
        exp.get("deep_model"),
        exp.get("output_language"),
    )


def case_label(case: dict) -> str:
    """A short human label for a case (used in reports)."""
    return f"{case.get('ticker')} / {case.get('trade_date')}"


# ---------------------------------------------------------------------------
# Metric extraction from one telemetry payload
# ---------------------------------------------------------------------------
def _zero_agent_metrics():
    return {
        "llm_calls": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "reasoning_tokens": 0,
        "cached_input_tokens": 0,
        "tool_calls": 0,
        "tool_rounds": 0,
        "prompt_utf8_bytes_sum": 0,
        "tool_message_utf8_bytes_sum": 0,
        "tool_result_utf8_bytes_sum": 0,
    }


def _extract_agent_metrics(agent: dict) -> dict:
    """Extract per-agent token/tool metrics from a telemetry agents entry."""
    inp = agent.get("reported_input_tokens_sum") or 0
    out = agent.get("reported_output_tokens_sum") or 0
    return {
        "llm_calls": agent.get("llm_calls") or 0,
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": inp + out,
        "reasoning_tokens": agent.get("reported_reasoning_tokens_sum") or 0,
        "cached_input_tokens": agent.get("reported_cached_input_tokens_sum") or 0,
        "tool_calls": agent.get("tool_calls") or 0,
        "tool_rounds": agent.get("tool_rounds") or 0,
        "prompt_utf8_bytes_sum": agent.get("prompt_utf8_bytes_sum") or 0,
        "tool_message_utf8_bytes_sum": agent.get("tool_message_utf8_bytes_sum") or 0,
        "tool_result_utf8_bytes_sum": agent.get("tool_result_utf8_bytes_sum") or 0,
    }


def _portable_path(path: Path | None, base: Path | None) -> str | None:
    """Render ``path`` relative to ``base`` so reports carry no host absolute path.

    A benchmark report is committed and shared, but the absolute location of a
    run's telemetry says nothing about the measurement while leaking the
    operator's home directory. Paths inside ``base`` become ``POSIX``-style
    relative paths (``runs/run_01/attempt_01/telemetry.json``); a path outside
    it keeps only its file name, and only the drive/tree root is dropped. The
    result is always resolved against the experiment directory (see
    :func:`_resolve_report_path`), so the report stays readable on this machine.
    """
    if path is None:
        return None
    p = Path(path)
    if base is not None:
        try:
            return p.resolve().relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            pass
    # Outside the experiment tree: keep the recognizable suffix, never the
    # host-specific prefix (home directory, mount point).
    parts = p.parts
    if len(parts) >= 3:
        return Path(*parts[-3:]).as_posix()
    return p.name if p.name else None


def _resolve_report_path(stored: str | None, base: Path | None) -> str | None:
    """Resolve a ``telemetry_path`` recorded by :func:`_portable_path`."""
    if not stored:
        return None
    p = Path(stored)
    if p.is_absolute() or base is None:
        return str(p)
    return str(Path(base) / p)


# Why a run is not a measured sample. Kept explicit and mutually exclusive so a
# failed run can never be mistaken for "token usage was merely missing".
INVALID_BUSINESS_FAILED = "business_run_failed"
INVALID_LLM_ERRORS = "llm_call_errors"
INVALID_USAGE_MISSING = "token_usage_missing"
INVALID_TELEMETRY_INCOMPLETE = "telemetry_incomplete"


def llm_error_count(payload: dict) -> int:
    """Total failed LLM calls recorded in one telemetry payload.

    A failed call is an explicit error signal from the graph: the SDK gave up
    (``OpenAITimeoutError``, 429 exhaustion, ...) or the response could not be
    used. ``run_totals.llm_error_count`` is authoritative; the per-agent
    aggregates are cross-checked and the largest value wins, so a payload with
    an incomplete run-totals block cannot hide an error.
    """
    total = 0
    run_totals = payload.get("run_totals") or {}
    try:
        total = int(run_totals.get("llm_error_count") or 0)
    except (TypeError, ValueError):
        total = 0
    per_agent = 0
    for agg in (payload.get("agents") or {}).values():
        if not isinstance(agg, dict):
            continue
        try:
            per_agent += int(agg.get("llm_error_count") or 0)
        except (TypeError, ValueError):
            continue
    return max(total, per_agent)


def _usage_coverage_problem(payload: dict) -> str | None:
    """Return why provider token usage is incomplete, or ``None`` if complete."""
    coverage = payload.get("usage_coverage") or {}
    if not coverage.get("complete"):
        return INVALID_USAGE_MISSING
    audit = payload.get("audit_quality") or {}
    if "usage_complete" in audit and not audit.get("usage_complete"):
        return INVALID_USAGE_MISSING
    if "telemetry_complete" in audit and not audit.get("telemetry_complete"):
        return INVALID_TELEMETRY_INCOMPLETE
    return None


def run_invalidity_reason(payload: dict) -> str | None:
    """Classify why a telemetry payload is not a valid measurement sample.

    A run only contributes to the mean when every call *succeeded* and every
    token is accounted for. The checks are ordered from the coarsest signal to
    the finest:

    1. the application did not complete the run (``business_run_failed``);
    2. an LLM call errored — even if the failed call still reported a usage
       block, the transcript is partial, so this is ``llm_call_errors``;
    3. a successful call reported no provider usage / the telemetry says it was
       not finalized (``token_usage_missing`` / ``telemetry_incomplete``).

    Step 2 is the reason ``usage_coverage.complete`` alone is not enough: a
    timeout that carried usage (or a retried-then-succeeded call) leaves the
    token count plausible while the run's business output is incomplete.
    """
    run = payload.get("run") or {}
    status = run.get("run_status")
    if status is not None and status != "completed":
        return INVALID_BUSINESS_FAILED
    if llm_error_count(payload) > 0:
        return INVALID_LLM_ERRORS
    return _usage_coverage_problem(payload)


def extract_run_metrics(payload: dict, telemetry_path: Path | None,
                        run_index: int, *, base_dir: Path | None = None) -> dict:
    """Normalize one telemetry payload into the benchmark's per-run metric dict.

    ``total_tokens`` is exactly reported input + reported output. Reasoning and
    cached-input tokens are informational subsets and are NOT added again.
    Missing provider usage is NEVER treated as zero in the validity decision,
    and a failed LLM call invalidates the sample even when it reported usage
    (see :func:`run_invalidity_reason`).
    """
    run = payload.get("run", {}) or {}
    run_totals = payload.get("run_totals", {}) or {}
    usage_coverage = payload.get("usage_coverage", {}) or {}
    audit = payload.get("audit_quality", {}) or {}

    inp = run_totals.get("reported_input_tokens_sum") or 0
    out = run_totals.get("reported_output_tokens_sum") or 0

    run_status = run.get("run_status")
    usage_complete = bool(usage_coverage.get("complete"))
    invalid_reason = run_invalidity_reason(payload)

    agents_metrics = {}
    for agent_id, agg in (payload.get("agents", {}) or {}).items():
        agents_metrics[agent_id] = _extract_agent_metrics(agg)

    event_counts = {
        "llm_call_events": len(payload.get("llm_call_events") or []),
        "tool_call_events": len(payload.get("tool_call_events") or []),
        "tool_round_events": len(payload.get("tool_round_events") or []),
        "prefetch_events": len(payload.get("prefetch_events") or []),
        "structured_events": len(payload.get("structured_events") or []),
        "node_context_events": len(payload.get("node_context_events") or []),
    }

    return {
        "run_index": run_index,
        "telemetry_run_id": run.get("telemetry_run_id"),
        "run_status": run_status,
        "failure_type": run.get("failure_type"),
        "ticker": run.get("ticker"),
        "trade_date": run.get("trade_date"),
        "duration_ms": run.get("duration_ms"),
        "llm_calls": run_totals.get("llm_calls") or 0,
        "reported_input_tokens_sum": inp,
        "reported_output_tokens_sum": out,
        "total_tokens": inp + out,
        "reported_reasoning_tokens_sum": run_totals.get("reported_reasoning_tokens_sum") or 0,
        "reported_cached_input_tokens_sum": run_totals.get("reported_cached_input_tokens_sum") or 0,
        "tool_calls": run_totals.get("tool_calls") or 0,
        "tool_rounds": run_totals.get("tool_rounds") or 0,
        "duplicate_tool_call_count": run_totals.get("duplicate_tool_call_count") or 0,
        "prefetched_data_calls": run_totals.get("prefetched_data_calls") or 0,
        "usage_complete": bool(audit.get("usage_complete")),
        "attribution_complete": bool(audit.get("attribution_complete")),
        "telemetry_complete": bool(audit.get("telemetry_complete")),
        "usage_coverage_complete": usage_complete,
        "llm_error_count": llm_error_count(payload),
        "invalid_reason": invalid_reason,
        "valid": invalid_reason is None,
        "event_counts": event_counts,
        "agents": agents_metrics,
        "telemetry_path": _portable_path(telemetry_path, base_dir),
    }


# ---------------------------------------------------------------------------
# Aggregate statistics
# ---------------------------------------------------------------------------
def aggregate(values):
    """Return ``{n, mean, median, stdev, min, max}`` for numeric ``values``.

    Uses sample standard deviation when n >= 2. For n == 1, stdev is ``None``
    (never 0), so a single sample never masquerades as having no variance.
    Empty input returns all-None with n == 0.
    """
    vals = [float(v) for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "stdev": None, "min": None, "max": None}
    if n == 1:
        return {
            "n": 1, "mean": vals[0], "median": vals[0], "stdev": None,
            "min": vals[0], "max": vals[0],
        }
    return {
        "n": n,
        "mean": round(statistics.mean(vals), 4),
        "median": round(statistics.median(vals), 4),
        "stdev": round(statistics.stdev(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
    }


# Run-total fields we aggregate across valid runs.
_RUN_TOTAL_FIELDS = [
    ("input_tokens", "reported_input_tokens_sum"),
    ("output_tokens", "reported_output_tokens_sum"),
    ("total_tokens", "total_tokens"),
    ("cached_input_tokens", "reported_cached_input_tokens_sum"),
    ("llm_calls", "llm_calls"),
    ("tool_calls", "tool_calls"),
    ("tool_rounds", "tool_rounds"),
    ("runtime_ms", "duration_ms"),
]

# Per-agent fields we aggregate across valid runs.
_AGENT_FIELDS = [
    ("input_tokens", "input_tokens"),
    ("output_tokens", "output_tokens"),
    ("total_tokens", "total_tokens"),
    ("llm_calls", "llm_calls"),
    ("tool_calls", "tool_calls"),
    ("tool_rounds", "tool_rounds"),
    ("prompt_bytes", "prompt_utf8_bytes_sum"),
    ("tool_message_bytes", "tool_message_utf8_bytes_sum"),
    ("tool_result_bytes", "tool_result_utf8_bytes_sum"),
]


def build_run_summary(metrics_list, experiment: dict, case: dict, exp_dir: Path) -> dict:
    """Build the summary dict from a list of per-run metric dicts.

    Only runs where ``valid`` is True contribute to numeric aggregates. Invalid /
    partial runs are preserved (listed individually) but excluded from aggregates.
    """
    valid_runs = [m for m in metrics_list if m.get("valid")]
    run_totals = {}
    for out_key, src_key in _RUN_TOTAL_FIELDS:
        run_totals[out_key] = aggregate([m.get(src_key) for m in valid_runs])

    # Per-agent aggregation over valid runs only.
    agent_names = set()
    for m in valid_runs:
        agent_names.update((m.get("agents") or {}).keys())
    per_agent = {}
    for aid in sorted(agent_names):
        entry = {}
        for out_key, src_key in _AGENT_FIELDS:
            entry[out_key] = aggregate(
                [(m.get("agents") or {}).get(aid, {}).get(src_key) for m in valid_runs]
            )
        per_agent[aid] = entry

    return {
        "schema_version": TOOL_SCHEMA_VERSION,
        "experiment_id": experiment.get("experiment_id"),
        "case": case_label(case),
        "case_id": case.get("case_id"),
        "ticker": case.get("ticker"),
        "trade_date": case.get("trade_date"),
        "analysts": list(case.get("analysts") or []),
        "research_rounds": case.get("research_rounds"),
        "risk_rounds": case.get("risk_rounds"),
        "provider": experiment.get("provider"),
        "quick_model": experiment.get("quick_model"),
        "deep_model": experiment.get("deep_model"),
        "output_language": experiment.get("output_language"),
        "cache_policy": experiment.get("cache_policy"),
        "measured_target": experiment.get("measured_runs"),
        "measured_valid": len(valid_runs),
        "run_totals": run_totals,
        "per_agent": per_agent,
        "quality": {
            "usage_complete": sum(1 for m in metrics_list if m.get("usage_complete")),
            "attribution_complete": sum(1 for m in metrics_list if m.get("attribution_complete")),
            "telemetry_complete": sum(1 for m in metrics_list if m.get("telemetry_complete")),
            "measured": len(metrics_list),
            "valid": len(valid_runs),
        },
        # Individual runs preserved verbatim-ish (only the metric dicts).
        "runs": metrics_list,
    }


# ---------------------------------------------------------------------------
# Markdown / CSV
# ---------------------------------------------------------------------------
def _validity_label(metrics: dict) -> str:
    """``yes`` for a measured sample, otherwise the reason it was excluded."""
    if metrics.get("valid"):
        return "yes"
    reason = metrics.get("invalid_reason") or metrics.get("error") or "invalid"
    return f"no ({reason})"


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.1f}" if abs(value) < 1e7 else f"{value:.6g}"
    return str(value)


def write_summary_md(summary: dict, experiment: dict, path: Path) -> None:
    lines = []
    lines.append(f"# Token Benchmark: {summary['experiment_id']}")
    lines.append("")
    lines.append("Case:")
    lines.append(f"{summary['case']}")
    lines.append("")
    lines.append("Measured runs (valid / target):")
    lines.append(
        f"{summary['measured_valid']} / {summary['measured_target']}"
    )
    lines.append("")
    lines.append("Configuration:")
    lines.append(f"- analysts: {', '.join(summary['analysts'])}")
    lines.append(f"- research rounds: {summary['research_rounds']}")
    lines.append(f"- risk rounds: {summary['risk_rounds']}")
    lines.append(f"- quick model: {summary['quick_model']}")
    lines.append(f"- deep model: {summary['deep_model']}")
    lines.append(f"- provider: {summary['provider']}")
    lines.append(f"- cache policy: {summary['cache_policy']}")
    lines.append("")

    lines.append("## Run totals")
    lines.append("")
    lines.append("| Metric | Mean | Median | Std | Min | Max |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for out_key, _src in [
        ("input_tokens", None), ("output_tokens", None), ("total_tokens", None),
        ("cached_input_tokens", None), ("llm_calls", None), ("tool_calls", None),
        ("tool_rounds", None), ("runtime_ms", None),
    ]:
        agg = summary["run_totals"][out_key]
        lines.append(
            f"| {out_key} | {_fmt(agg['mean'])} | {_fmt(agg['median'])} | "
            f"{_fmt(agg['stdev'])} | {_fmt(agg['min'])} | {_fmt(agg['max'])} |"
        )
        # Patch total_tokens max to int-like display for readability if large.
    lines.append("")

    # Per-agent, sorted by mean total_tokens descending.
    lines.append("## Token usage by agent")
    lines.append("")
    total_mean = summary["run_totals"]["total_tokens"]["mean"] or 0
    rows = []
    for aid, entry in summary["per_agent"].items():
        label = AGENT_DISPLAY.get(aid, aid)
        mean_total = entry["total_tokens"]["mean"]
        pct = (mean_total / total_mean * 100) if total_mean else 0.0
        rows.append((mean_total if mean_total is not None else -1.0, label, entry))
    rows.sort(key=lambda r: r[0], reverse=True)
    lines.append("| Agent | Mean Input | Mean Output | Mean Total | % of Run |")
    lines.append("| --- | --- | --- | --- | --- |")
    for _mt, label, entry in rows:
        total_mean_e = entry["total_tokens"]["mean"] or 0
        pct = (total_mean_e / total_mean * 100) if total_mean else 0.0
        lines.append(
            f"| {label} | {_fmt(entry['input_tokens']['mean'])} | "
            f"{_fmt(entry['output_tokens']['mean'])} | {_fmt(total_mean_e)} | "
            f"{pct:.1f}% |"
        )
    lines.append("")

    lines.append("## Tool behavior")
    lines.append("")
    lines.append("| Agent | Tool Calls | Tool Rounds | Tool Result Bytes |")
    lines.append("| --- | --- | --- | --- |")
    for _mt, label, entry in rows:
        lines.append(
            f"| {label} | {_fmt(entry['tool_calls']['mean'])} | "
            f"{_fmt(entry['tool_rounds']['mean'])} | "
            f"{_fmt(entry['tool_result_bytes']['mean'])} |"
        )
    lines.append("")

    q = summary["quality"]
    lines.append("## Quality / Coverage")
    lines.append("")
    lines.append("Usage complete:")
    lines.append(f"{q['usage_complete']}/{q['measured']}")
    lines.append("")
    lines.append("Attribution complete:")
    lines.append(f"{q['attribution_complete']}/{q['measured']}")
    lines.append("")
    lines.append("Telemetry complete:")
    lines.append(f"{q['telemetry_complete']}/{q['measured']}")
    lines.append("")

    lines.append("## Individual runs")
    lines.append("")
    lines.append("| Run | Input | Output | Total | LLM | Tools | Rounds | Runtime | Status | Valid |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in summary["runs"]:
        lines.append(
            f"| {m['run_index']:02d} | {_fmt(m['reported_input_tokens_sum'])} | "
            f"{_fmt(m['reported_output_tokens_sum'])} | {_fmt(m['total_tokens'])} | "
            f"{_fmt(m['llm_calls'])} | {_fmt(m['tool_calls'])} | {_fmt(m['tool_rounds'])} | "
            f"{_fmt(m['duration_ms'])} | {m['run_status']} | {_validity_label(m)} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_csv(summary: dict, experiment: dict, path: Path) -> None:
    fieldnames = [
        "experiment_id", "case_id", "case", "run_index", "ticker", "trade_date",
        "run_status", "input_tokens", "output_tokens", "total_tokens",
        "cached_input_tokens", "llm_calls", "tool_calls", "tool_rounds",
        "runtime_ms", "usage_complete", "attribution_complete", "telemetry_complete",
        "valid", "invalid_reason", "llm_errors", "telemetry_path",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in summary["runs"]:
            row = {
                "experiment_id": summary["experiment_id"],
                "case_id": summary["case_id"],
                "case": summary["case"],
                "run_index": m["run_index"],
                "ticker": m["ticker"],
                "trade_date": m["trade_date"],
                "run_status": m["run_status"],
                "input_tokens": m["reported_input_tokens_sum"],
                "output_tokens": m["reported_output_tokens_sum"],
                "total_tokens": m["total_tokens"],
                "cached_input_tokens": m["reported_cached_input_tokens_sum"],
                "llm_calls": m["llm_calls"],
                "tool_calls": m["tool_calls"],
                "tool_rounds": m["tool_rounds"],
                "runtime_ms": m["duration_ms"],
                "usage_complete": m["usage_complete"],
                "attribution_complete": m["attribution_complete"],
                "telemetry_complete": m["telemetry_complete"],
                "valid": m["valid"],
                "invalid_reason": m.get("invalid_reason") or m.get("error") or "",
                "llm_errors": m.get("llm_error_count", ""),
                "telemetry_path": m["telemetry_path"] or "",
            }
            writer.writerow(row)


def write_summary_agents_csv(summary: dict, experiment: dict, path: Path) -> None:
    fieldnames = [
        "experiment_id", "case_id", "run_index", "agent_id", "agent",
        "input_tokens", "output_tokens", "total_tokens", "reasoning_tokens",
        "cached_input_tokens", "llm_calls", "tool_calls", "tool_rounds",
        "prompt_bytes", "tool_message_bytes", "tool_result_bytes", "valid",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in summary["runs"]:
            for aid, am in (m.get("agents") or {}).items():
                writer.writerow({
                    "experiment_id": summary["experiment_id"],
                    "case_id": summary["case_id"],
                    "run_index": m["run_index"],
                    "agent_id": aid,
                    "agent": AGENT_DISPLAY.get(aid, aid),
                    "input_tokens": am["input_tokens"],
                    "output_tokens": am["output_tokens"],
                    "total_tokens": am["total_tokens"],
                    "reasoning_tokens": am["reasoning_tokens"],
                    "cached_input_tokens": am["cached_input_tokens"],
                    "llm_calls": am["llm_calls"],
                    "tool_calls": am["tool_calls"],
                    "tool_rounds": am["tool_rounds"],
                    "prompt_bytes": am["prompt_utf8_bytes_sum"],
                    "tool_message_bytes": am["tool_message_utf8_bytes_sum"],
                    "tool_result_bytes": am["tool_result_utf8_bytes_sum"],
                    "valid": m["valid"],
                })


def write_summary(summary: dict, experiment: dict, exp_dir: Path) -> None:
    write_summary_md(summary, experiment, exp_dir / SUMMARY_MD)
    write_summary_csv(summary, experiment, exp_dir / SUMMARY_CSV)
    write_summary_agents_csv(summary, experiment, exp_dir / SUMMARY_AGENTS_CSV)
    (exp_dir / SUMMARY_JSON).write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _case_output_dir(exp_dir: Path, case: dict) -> Path:
    """Per-case report directory: ``<exp_dir>/cases/<case_id>``."""
    safe = _safe_ticker_component(case.get("case_id"))
    return Path(exp_dir) / "cases" / safe


def write_experiment_summaries(summaries: dict, experiment: dict, exp_dir: Path) -> None:
    """Write reports for every case without losing any case.

    A single-case experiment keeps the canonical top-level
    ``summary.{json,csv,md}``. Multi-case experiments write one report set per
    case under ``cases/<case_id>/`` plus an ``index.json`` listing them, so no
    case silently overwrites another.
    """
    exp_dir = Path(exp_dir)
    cases = experiment["cases"]
    if len(cases) == 1:
        write_summary(summaries[cases[0]["case_id"]], experiment, exp_dir)
        return
    index = []
    for case in cases:
        case_id = case["case_id"]
        case_summary = summaries[case_id]
        out_dir = _case_output_dir(exp_dir, case)
        out_dir.mkdir(parents=True, exist_ok=True)
        write_summary(case_summary, experiment, out_dir)
        index.append({
            "case_id": case_id,
            "case": case_summary.get("case"),
            "ticker": case.get("ticker"),
            "trade_date": case.get("trade_date"),
            "measured_target": case_summary.get("measured_target"),
            "measured_valid": case_summary.get("measured_valid"),
            "summary_json": str(out_dir / SUMMARY_JSON),
            "summary_csv": str(out_dir / SUMMARY_CSV),
            "summary_agents_csv": str(out_dir / SUMMARY_AGENTS_CSV),
            "summary_md": str(out_dir / SUMMARY_MD),
        })
    (exp_dir / SUMMARY_INDEX_JSON).write_text(
        json.dumps({
            "schema_version": TOOL_SCHEMA_VERSION,
            "experiment_id": experiment.get("experiment_id"),
            "case_count": len(cases),
            "cases": index,
        }, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _summary_path(exp_dir: Path) -> Path:
    return Path(exp_dir) / SUMMARY_JSON


def load_summary(exp_dir: Path) -> dict:
    path = _summary_path(exp_dir)
    if not path.exists():
        raise FileNotFoundError(f"no summary at {path} (run `summarize` or `run` first)")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_COMPARE_METRICS = [
    ("input_tokens", "input_tokens"),
    ("output_tokens", "output_tokens"),
    ("total_tokens", "total_tokens"),
    ("llm_calls", "llm_calls"),
    ("tool_calls", "tool_calls"),
    ("tool_rounds", "tool_rounds"),
    ("runtime_ms", "runtime_ms"),
]


def compare_summaries(baseline: dict, candidate: dict, *, allow_mismatch: bool = False) -> dict:
    """Compare candidate against baseline; return a comparison dict / raise.

    Baseline=0 is handled safely (percent is None, not ZeroDivisionError). No
    qualitative claim ("improvement") is emitted; callers read the signed
    percentage as reduction/increase.
    """
    if not allow_mismatch:
        mismatches = []
        for key in ("ticker", "trade_date", "provider", "quick_model", "deep_model", "output_language"):
            b, c = baseline.get(key), candidate.get(key)
            if b != c:
                mismatches.append(f"{key}: baseline={b!r}, candidate={c!r}")
        if baseline.get("analysts") != candidate.get("analysts"):
            mismatches.append(f"analysts: baseline={baseline.get('analysts')!r}, candidate={candidate.get('analysts')!r}")
        if baseline.get("research_rounds") != candidate.get("research_rounds"):
            mismatches.append(
                f"research_rounds: baseline={baseline.get('research_rounds')!r}, "
                f"candidate={candidate.get('research_rounds')!r}"
            )
        if baseline.get("risk_rounds") != candidate.get("risk_rounds"):
            mismatches.append(
                f"risk_rounds: baseline={baseline.get('risk_rounds')!r}, "
                f"candidate={candidate.get('risk_rounds')!r}"
            )
        if mismatches:
            raise ValueError(
                "baseline and candidate differ in material benchmark inputs:\n"
                + "\n".join(f"  - {m}" for m in mismatches)
                + "\nPass --override to compare anyway."
            )

    rows = []
    for out_key, _src in _COMPARE_METRICS:
        b_mean = (baseline.get("run_totals", {}).get(out_key, {}) or {}).get("mean")
        c_mean = (candidate.get("run_totals", {}).get(out_key, {}) or {}).get("mean")
        if b_mean is None:
            rows.append({
                "metric": out_key, "baseline": b_mean, "candidate": c_mean,
                "absolute": None, "percent": None, "note": "baseline has no valid mean",
            })
        else:
            absolute = (c_mean - b_mean) if c_mean is not None else None
            percent = ((c_mean - b_mean) / b_mean * 100) if (c_mean is not None and b_mean != 0) else None
            note = ("baseline=0" if b_mean == 0 else None) if (c_mean is not None and b_mean == 0) else None
            rows.append({
                "metric": out_key, "baseline": b_mean, "candidate": c_mean,
                "absolute": absolute, "percent": percent, "note": note,
            })

    # Per-agent total-token means.
    agent_rows = []
    base_agents = baseline.get("per_agent", {})
    cand_agents = candidate.get("per_agent", {})
    for aid in sorted(set(base_agents) | set(cand_agents)):
        b_mean = (base_agents.get(aid, {}).get("total_tokens", {}) or {}).get("mean")
        c_mean = (cand_agents.get(aid, {}).get("total_tokens", {}) or {}).get("mean")
        if b_mean is None:
            agent_rows.append({
                "agent": AGENT_DISPLAY.get(aid, aid), "baseline": b_mean,
                "candidate": c_mean, "absolute": None, "percent": None, "note": "no baseline mean",
            })
        else:
            absolute = (c_mean - b_mean) if c_mean is not None else None
            percent = ((c_mean - b_mean) / b_mean * 100) if (c_mean is not None and b_mean != 0) else None
            agent_rows.append({
                "agent": AGENT_DISPLAY.get(aid, aid), "baseline": b_mean,
                "candidate": c_mean, "absolute": absolute, "percent": percent,
                "note": ("baseline=0" if b_mean == 0 else None) if (c_mean is not None and b_mean == 0) else None,
            })

    return {
        "baseline_experiment": baseline.get("experiment_id"),
        "candidate_experiment": candidate.get("experiment_id"),
        "metrics": rows,
        "per_agent_total_tokens": agent_rows,
    }


def format_comparison(cmp: dict) -> str:
    lines = []
    lines.append("# Comparison")
    lines.append("")
    lines.append("Baseline: " + str(cmp["baseline_experiment"]))
    lines.append("Candidate: " + str(cmp["candidate_experiment"]))
    lines.append("")
    lines.append("## Run totals")
    lines.append("")
    lines.append("| Metric | Baseline | Candidate | Abs Δ | % Change |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in cmp["metrics"]:
        pct = f"{r['percent']:+.2f}%" if r["percent"] is not None else "N/A"
        note = f" ({r['note']})" if r.get("note") else ""
        lines.append(
            f"| {r['metric']} | {_fmt(r['baseline'])} | {_fmt(r['candidate'])} | "
            f"{_fmt(r['absolute'])} | {pct}{note} |"
        )
    lines.append("")
    lines.append("## Per-agent mean total tokens")
    lines.append("")
    lines.append("| Agent | Baseline | Candidate | Abs Δ | % Change |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in cmp["per_agent_total_tokens"]:
        pct = f"{r['percent']:+.2f}%" if r["percent"] is not None else "N/A"
        note = f" ({r['note']})" if r.get("note") else ""
        lines.append(
            f"| {r['agent']} | {_fmt(r['baseline'])} | {_fmt(r['candidate'])} | "
            f"{_fmt(r['absolute'])} | {pct}{note} |"
        )
    lines.append("")
    lines.append("Note: negative % indicates a reduction in the candidate versus baseline.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Code state / reproducibility
# ---------------------------------------------------------------------------
def _git_command(args) -> str | None:
    return _git_command_in(_PROJECT_ROOT, args)


def _git_command_in(root: Path, args) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False,
            cwd=root,
        )
        if out.returncode != 0:
            return None
        return out.stdout
    except Exception:  # noqa: BLE001
        return None


def _fingerprint_root() -> Path:
    """Repository root the fingerprint describes (overridable for tests)."""
    override = os.environ.get("TRADINGAGENTS_FINGERPRINT_ROOT")
    return Path(override).resolve() if override else _PROJECT_ROOT


def _relevant_package_versions() -> dict:
    versions = {}
    for name in ("langgraph", "langchain-core"):
        try:
            from importlib.metadata import version as _meta_version
            versions[name] = _meta_version(name)
        except Exception:  # noqa: BLE001
            versions[name] = None
    return versions


def _project_root() -> Path:
    # scripts/token_benchmark.py -> project root.
    return Path(__file__).resolve().parent.parent


_PROJECT_ROOT = _project_root()


def _normalize_rel_path(path: str) -> str | None:
    """Repo-relative POSIX path, or ``None`` if it must never be fingerprinted.

    Purely lexical: it does not touch the filesystem, so the same rules apply
    to paths that exist in the index, in the working tree, or nowhere at all.
    """
    rel = str(path).replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    rel = rel.lstrip("/")
    if not rel or rel == ".":
        return None
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    name = parts[-1]
    lowered = [p.lower() for p in parts]
    # Credentials are excluded by pattern as well as by extension, because a
    # force-added secret must not become reproducible metadata.
    if name in _FINGERPRINT_SECRET_NAMES or any(p in _FINGERPRINT_SECRET_NAMES for p in lowered):
        return None
    if name.startswith(".env"):
        return None
    if any(lowered[-1].endswith(sfx) for sfx in _FINGERPRINT_SECRET_SUFFIXES):
        return None
    if any(marker in p for p in lowered[:-1] for marker in _FINGERPRINT_BACKUP_DIR_MARKERS):
        return None
    if any(name.endswith(sfx) for sfx in _FINGERPRINT_EXCLUDE_SUFFIXES):
        return None
    if name in _FINGERPRINT_EXCLUDE_NAMES:
        return None
    # Raw evidence / generated output may live at any depth below the
    # experiment directories (``<exp>/runs/...``, ``measurements/...``).
    if any(p in ("runs", "cases", "measurements") for p in lowered[:-1]) and \
            any(p == "token_benchmarks" for p in lowered):
        return None
    joined = "/".join(parts)
    for prefix in _FINGERPRINT_EXCLUDE_PREFIXES:
        if joined == prefix.rstrip("/") or joined.startswith(prefix):
            return None
    if any(p in ("__pycache__", ".venv", ".pytest_cache", ".ruff_cache",
                 ".mypy_cache", "node_modules") for p in lowered[:-1]):
        return None
    return joined


def _fingerprint_eligible(path: str) -> bool:
    rel = _normalize_rel_path(path)
    if rel is None:
        return False
    if rel in _FINGERPRINT_ROOT_FILES:
        return True
    return any(rel.startswith(pref) for pref in _FINGERPRINT_INCLUDE_PREFIXES)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _working_tree_manifest() -> list[dict]:
    """Sorted ``[{path, sha256, untracked}]`` for every eligible working-tree file.

    Tracked files are enumerated with ``git ls-files`` so that a *deletion* is
    representable (the manifest simply lacks the path), and untracked source
    files with ``git ls-files --others --exclude-standard`` so that new code
    counts too. Contents always come from the working tree, never from the
    index or from HEAD, which is what makes the fingerprint describe the code
    that actually runs.

    A directory that is not a git checkout is fingerprinted too (nothing is
    tracked, everything is walked), so synthetic fixtures and unpacked
    snapshots still get an honest fingerprint instead of silently getting none.
    """
    root = _fingerprint_root()
    tracked = _git_command_in(root, ["ls-files", "-z"])
    untracked = _git_command_in(root, ["ls-files", "-z", "--others", "--exclude-standard"])

    if tracked is not None and untracked is not None:
        candidates = {p for p in tracked.split("\0") if p}
        candidates.update(p for p in untracked.split("\0") if p)
        untracked_set = {p for p in untracked.split("\0") if p}
        # Paths are only existence-checked below, so a directory scan is needed
        # solely to discover untracked files outside git; here we already have
        # them.
        return _build_manifest(candidates, untracked_set, allow_walk=False)

    return _build_manifest(None, set(), allow_walk=True)


def _walk_candidates() -> set[str]:
    """Repo-relative paths of every eligible file found by walking the tree."""
    root = _fingerprint_root()
    found: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            found.add(rel.replace(os.sep, "/"))
    return found


def _build_manifest(candidates: set[str] | None, untracked_set: set[str],
                    *, allow_walk: bool) -> list[dict]:
    if candidates is None:
        if not allow_walk:
            raise RuntimeError("no candidate files to fingerprint")
        candidates = _walk_candidates()
    root = _fingerprint_root()
    manifest: list[dict] = []
    for raw in candidates:
        if not _fingerprint_eligible(raw):
            continue
        rel = _normalize_rel_path(raw)
        # A tracked file can be deleted in the working tree: it is absent from
        # the manifest, so the overall hash changes with the deletion.
        full = root / rel
        if not full.is_file() or full.is_symlink():
            continue
        manifest.append({"path": rel, "sha256": _sha256_file(full),
                         "untracked": raw in untracked_set})
    manifest.sort(key=lambda entry: entry["path"])
    return manifest


def working_tree_manifest() -> list[dict]:
    """Public alias of the manifest used by the fingerprint (sorted)."""
    return _working_tree_manifest()


def fingerprint_manifest(manifest: list[dict]) -> str:
    """Hash a manifest canonically: order-independent, POSIX paths, no content."""
    lines = [f"{hashlib.sha256(e['path'].encode('utf-8')).hexdigest()} {e['sha256']}"
             for e in sorted(manifest, key=lambda entry: entry["path"])]
    payload = f"{FINGERPRINT_ALGORITHM}\n" + "\n".join(lines) + "\n"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_working_tree_fingerprint() -> dict:
    """Fingerprint the code that a measurement actually executes."""
    manifest = working_tree_manifest()
    return {
        "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
        "working_tree_sha256": fingerprint_manifest(manifest),
        "file_count": len(manifest),
        "tracked_file_count": sum(1 for e in manifest if not e.get("untracked")),
        "untracked_file_count": sum(1 for e in manifest if e.get("untracked")),
        "untracked_files": [e["path"] for e in manifest if e.get("untracked")],
        "files": manifest,
    }


def experiment_config_sha256(experiment: dict | None) -> str | None:
    """SHA-256 of the canonical experiment definition (no host-specific paths)."""
    if not experiment:
        return None
    canonical = json.dumps(experiment, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def capture_code_state(experiment: dict | None = None) -> dict:
    """Capture non-secret reproducibility metadata.

    No API keys, headers, env secrets, or raw `.env` contents are ever read,
    and no file contents are stored: only relative paths and their hashes.
    The fingerprint covers tracked *and* untracked source files, so it changes
    with any edit, addition or deletion of the code being benchmarked.
    """
    root = _fingerprint_root()
    head = _git_command_in(root, ["rev-parse", "HEAD"])
    head = head.strip() if head else None
    branch = _git_command_in(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip() if branch else None
    diff_binary = _git_command_in(root, ["diff", "--binary"]) or ""
    dirty_tracked = diff_binary != ""
    diff_sha = hashlib.sha256(diff_binary.encode("utf-8")).hexdigest() if diff_binary else None
    fp = compute_working_tree_fingerprint()
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "git_branch": branch,
        "git_head_commit": head,
        "git_working_tree_dirty": dirty_tracked,
        "git_diff_sha256": diff_sha,
        # The fingerprint is the integrity claim: a measurement whose working
        # tree differed at its end from its start is not a valid baseline.
        "fingerprint_algorithm": fp["fingerprint_algorithm"],
        "working_tree_sha256": fp["working_tree_sha256"],
        "file_count": fp["file_count"],
        "tracked_file_count": fp["tracked_file_count"],
        "untracked_file_count": fp["untracked_file_count"],
        "untracked_files": fp["untracked_files"],
        "experiment_config_sha256": experiment_config_sha256(experiment),
        "package_versions": _relevant_package_versions(),
        "tool_schema_version": TOOL_SCHEMA_VERSION,
        "experiment_schema_version": TOOL_SCHEMA_VERSION,
    }


def fingerprint_drift(before: dict | None, after: dict | None) -> dict:
    """Compare two code fingerprints; ``changed`` means the run is not a baseline."""
    before = before or {}
    after = after or {}
    before_hash = before.get("working_tree_sha256")
    after_hash = after.get("working_tree_sha256")
    changed = bool(before_hash and after_hash and before_hash != after_hash)
    return {
        "code_changed_during_measurement": changed,
        "working_tree_sha256_start": before_hash,
        "working_tree_sha256_end": after_hash,
    }


def write_code_state(exp_dir: Path, experiment: dict | None = None,
                     previous: dict | None = None) -> dict:
    """Write ``code_state.json``.

    ``previous`` is the start-of-measurement state: when given, this is the
    end-of-measurement capture and any drift is recorded in the artifact.
    """
    state = capture_code_state(experiment)
    if previous is not None:
        state["code_state_phase"] = "end_of_measurement"
        state["measurement_start_working_tree_sha256"] = \
            previous.get("working_tree_sha256")
        drift = fingerprint_drift(previous, state)
        state["code_changed_during_measurement"] = drift["code_changed_during_measurement"]
        if not drift["code_changed_during_measurement"]:
            del state["code_changed_during_measurement"]
    else:
        state["code_state_phase"] = "start_of_measurement"
    (exp_dir / CODE_STATE_FILE).write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return state


# ---------------------------------------------------------------------------
# Run orchestration (process isolation)
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _safe_ticker_component(ticker: str) -> str:
    """A filesystem-safe ticker component for run runtime dirs.

    Mirrors ``tradingagents.dataflows.utils.safe_ticker_component`` (the helper the
    observability telemetry path uses) so the harness's expected runtime directory
    matches the directory the application actually writes into. Tickers that are
    invalid for the application's path rules (e.g. crypto pairs like ``BTC-USD``)
    map to a deterministic, distinct directory.
    """
    digest = hashlib.sha256(str(ticker).encode("utf-8")).hexdigest()[:12]
    if isinstance(ticker, str) and ticker and len(ticker) <= 32:
        try:
            return safe_ticker_component(ticker)
        except ValueError:
            pass
    return f"ticker_{digest}"


def _run_slot_dir(exp_dir: Path, run_index: int) -> Path:
    """Directory holding every attempt of run ``run_index``."""
    return Path(exp_dir) / RUNS_DIR / f"run_{run_index:02d}"


def attempt_dirs(exp_dir: Path, run_index: int) -> list[Path]:
    """Return the attempts of a run that actually started, oldest first.

    A directory holding only a ``spec.json`` was written by ``run --dry-run``
    (or before the child was launched) and never ran, so it is not an attempt.
    """
    slot = _run_slot_dir(exp_dir, run_index)
    if not slot.is_dir():
        return []
    return sorted(
        d for d in slot.glob(ATTEMPT_DIR_GLOB)
        if d.is_dir() and any(p.name != "spec.json" for p in d.iterdir())
    )


def _attempt_dir(exp_dir: Path, run_index: int, attempt: int) -> Path:
    return _run_slot_dir(exp_dir, run_index) / f"attempt_{attempt:02d}"


def _run_runtime_dir(exp_dir: Path, case: dict, run_index: int,
                     attempt: int = 1) -> Path:
    safe = _safe_ticker_component(case.get("ticker"))
    date_comp = str(case.get("trade_date")).replace("/", "-")
    return (_attempt_dir(exp_dir, run_index, attempt) / "runtime" / safe / date_comp)


def _telemetry_snapshot(runtime_dir: Path) -> set[str]:
    """Return the set of telemetry artifact paths currently under ``runtime_dir``.

    Globs ``telemetry`` directories explicitly and lists ``*.json`` inside them.
    ``Path.rglob("telemetry/*.json")`` is unreliable here: newer Python versions
    treat ``/`` in a glob pattern as a directory separator, not as a literal
    match against the file name.
    """
    root = Path(runtime_dir)
    if not root.is_dir():
        return set()
    found: set[str] = set()
    for telemetry_dir in root.rglob("telemetry"):
        if telemetry_dir.is_dir():
            found.update(str(p) for p in telemetry_dir.glob("*.json") if p.is_file())
    return found


def _select_run_telemetry(runtime_dir: Path, before: set[str],
                          reported_path: str | None) -> Path:
    """Select this run's telemetry artifact from files created since ``before``.

    Only artifacts that did not exist before the run qualify, so leftover files
    from earlier attempts never make a valid re-run ambiguous. Exactly one new
    artifact is accepted. Zero is a failure and more than one is an ambiguity,
    even if the child reported one of them: silently picking the reported file
    would mask a genuine multi-artifact problem.
    """
    new = sorted(_telemetry_snapshot(runtime_dir) - set(before))
    if len(new) == 0:
        raise RuntimeError(
            f"no new telemetry artifact found under {runtime_dir} "
            f"({len(before)} pre-existing artifact(s) unchanged)"
        )
    if len(new) > 1:
        raise RuntimeError(
            f"multiple new telemetry artifacts found under {runtime_dir} ({new}); "
            f"refusing to guess"
        )
    selected = Path(new[0])
    if reported_path and str(Path(reported_path)) != str(selected):
        # The child disagrees with the only new artifact. That is a contract
        # violation rather than something to auto-resolve.
        raise RuntimeError(
            f"runner reported telemetry {reported_path} but the only new artifact "
            f"is {selected}; refusing to guess"
        )
    return selected


def _locate_telemetry(runtime_dir: Path, case: dict) -> Path | None:
    """Find exactly one telemetry artifact under a run's runtime results dir.

    Returns the path, or raises ``RuntimeError`` when zero or multiple artifacts
    exist. ``runtime_dir`` is run-specific so this is deterministic.
    """
    candidates = list(runtime_dir.rglob("telemetry/*.json"))
    if len(candidates) == 0:
        raise RuntimeError(
            f"no telemetry artifact found under {runtime_dir} for {case.get('ticker')}/"
            f"{case.get('trade_date')}"
        )
    if len(candidates) > 1:
        raise RuntimeError(
            f"multiple telemetry artifacts found under {runtime_dir} "
            f"({[str(c) for c in candidates]}); refusing to guess"
        )
    return candidates[0]


def _runner_report_path(run_dir: Path) -> Path:
    return Path(run_dir) / RUNNER_REPORT_FILE


def _run_single_process_args(run_dir: Path) -> list[str]:
    """Build the argv for a single isolated run (fresh process for one run)."""
    spec_path = Path(run_dir) / "spec.json"
    return [sys.executable, str(Path(__file__).resolve()), "_run-single",
            "--spec", str(spec_path)]


def prepare_run_spec(exp_dir: Path, experiment: dict, case: dict, run_index: int,
                     attempt: int = 1) -> Path:
    """Write the run spec JSON the child reads to run one measurement."""
    run_dir = _attempt_dir(exp_dir, run_index, attempt)
    run_dir.mkdir(parents=True, exist_ok=True)
    runtime_results = _run_runtime_dir(exp_dir, case, run_index, attempt)
    spec = {
        "experiment_id": experiment.get("experiment_id"),
        "case": case,
        "provider": experiment.get("provider"),
        "quick_model": experiment.get("quick_model"),
        "deep_model": experiment.get("deep_model"),
        "output_language": experiment.get("output_language"),
        "cache_policy": experiment.get("cache_policy"),
        "results_dir": str(runtime_results),
        "run_index": run_index,
    }
    spec_path = run_dir / "spec.json"
    spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
    return spec_path


def _default_runner(spec_path: Path, exp_dir: Path, run_index: int,
                    attempt: int = 1) -> dict:
    """Default runner: spawn a fresh Python subprocess for one measured run.

    Uses ``sys.executable`` so the current .venv Python is reused, and never
    shells out through ``shell=True``. The telemetry files present *before* the
    child starts are snapshotted so only artifacts this run produced are
    considered (see ``_select_run_telemetry``).
    """
    exp = Path(exp_dir)
    run_dir = _attempt_dir(exp, run_index, attempt)
    prev = _runner_report_path(run_dir)
    prev.unlink(missing_ok=True) if prev.exists() else None
    spec = _load_json(spec_path)
    before = _telemetry_snapshot(Path(spec["results_dir"]))
    args = _run_single_process_args(run_dir)
    try:
        proc = subprocess.run(args, cwd=str(exp), capture_output=True, text=True, timeout=None)
    except Exception as exc:  # noqa: BLE001
        return {"status": "it_failed", "error": f"subprocess launch failed: {exc!r}",
                "telemetry_before": sorted(before)}
    report = _load_json(prev) if prev.exists() else None
    return {
        "status": "ok" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "error": None if proc.returncode == 0 else (proc.stderr or "").strip()[-2000:],
        "report": report,
        # Only artifacts created by this run; pre-existing ones are never
        # candidates and are never deleted.
        "telemetry_new": sorted(_telemetry_snapshot(Path(spec["results_dir"])) - before),
        "telemetry_before": sorted(before),
    }


def _preferred_attempt_dir(exp_dir: Path, run_index: int) -> Path:
    """Directory a fresh measurement is written to (never an existing one)."""
    existing = attempt_dirs(exp_dir, run_index)
    next_attempt = (int(existing[-1].name.rsplit("_", 1)[1]) + 1) if existing else 1
    return _attempt_dir(exp_dir, run_index, next_attempt)


def execute_measured_run(exp_dir: Path, experiment: dict, case: dict,
                         run_index: int, *, runner=None, dry_run: bool = False,
                         run_dir: Path | None = None) -> dict:
    """Run one measurement and fold its telemetry into its attempt dir.

    ``runner`` is an injectable callable ``(spec_path, exp_dir, run_index,
    attempt) -> dict`` used by tests. The default is a fresh subprocess (process
    isolation). ``run_dir`` selects the attempt directory; by default a new
    attempt is created so an existing attempt is never overwritten.
    Returns the per-run metric dict.
    """
    if run_dir is None and not dry_run:
        run_dir = _preferred_attempt_dir(exp_dir, run_index)
    run_dir = Path(run_dir) if run_dir is not None else _run_slot_dir(exp_dir, run_index)
    attempt = int(run_dir.name.rsplit("_", 1)[1]) if run_dir.name.startswith("attempt_") else 1
    spec_path = prepare_run_spec(exp_dir, experiment, case, run_index, attempt)
    runner = runner or _default_runner
    runner_result = runner(spec_path, exp_dir, run_index, attempt) if not dry_run else {
        "status": "dry_run", "returncode": 0, "error": None, "report": None,
    }

    report = runner_result.get("report") or {}
    status = runner_result.get("status")
    if status == "dry_run":
        return {
            "run_index": run_index, "run_status": "dry_run", "valid": False,
            "telemetry_run_id": None, "ticker": case.get("ticker"),
            "trade_date": case.get("trade_date"), "error": "dry_run",
            "reported_input_tokens_sum": 0, "reported_output_tokens_sum": 0,
            "total_tokens": 0, "llm_calls": 0, "tool_calls": 0, "tool_rounds": 0,
            "duration_ms": None, "usage_complete": False, "attribution_complete": False,
            "telemetry_complete": False, "usage_coverage_complete": False,
            "reported_reasoning_tokens_sum": 0, "reported_cached_input_tokens_sum": 0,
            "duplicate_tool_call_count": 0, "prefetched_data_calls": 0,
            "event_counts": {}, "agents": {}, "telemetry_path": None,
        }

    telemetry_path = None
    telemetry_error = None
    # Attempt selection regardless of the child's exit code: a run may write a
    # complete telemetry artifact and then exit non-zero. When no new artifact
    # exists, selection raises and the run is recorded as failed.
    runtime_dir = _run_runtime_dir(exp_dir, case, run_index, attempt)
    reported = report.get("telemetry_path") if isinstance(report, dict) else None
    try:
        # The pre-run snapshot comes from the runner. Injected runners that
        # provide neither a snapshot nor a "new" list are assumed to have
        # written only the single artifact they report.
        before = runner_result.get("telemetry_before")
        if before is None:
            new_reported = runner_result.get("telemetry_new")
            if new_reported is None:
                before = [] if not reported else [
                    p for p in _telemetry_snapshot(runtime_dir)
                    if str(p) != str(reported)
                ]
            else:
                before = sorted(
                    _telemetry_snapshot(runtime_dir) - set(new_reported)
                )
        telemetry_path = _select_run_telemetry(runtime_dir, set(before), reported)
    except RuntimeError as exc:
        status = "status_mismatch"
        report = report or {}
        # Surface the selection failure in the run's metadata.
        report.setdefault("error", str(exc))
        telemetry_error = str(exc)

    # Copy telemetry into the canonical run location; never delete the original
    # and never overwrite an existing copy (a re-run keeps the earlier report
    # traceable under a run-id-specific name).
    copied_path = None
    if telemetry_path is not None:
        dest = run_dir / TELEMETRY_FILE
        if dest.exists():
            existing = _load_json(dest)
            if (existing.get("run") or {}).get("telemetry_run_id") != \
                    (_load_json(telemetry_path).get("run") or {}).get("telemetry_run_id"):
                dest = run_dir / f"telemetry.{telemetry_path.stem}.json"
                if dest.exists():
                    raise RuntimeError(f"refusing to overwrite existing telemetry copy {dest}")
        dest.write_bytes(telemetry_path.read_bytes())
        copied_path = dest

    runner_error = (
        (report.get("error") if isinstance(report, dict) else None)
        or runner_result.get("error")
        or telemetry_error
    )

    # Read telemetry to extract metrics. A selected artifact is the primary
    # evidence: it is parsed even when the child exited non-zero (e.g. the graph
    # raised after the run), and its own run_status then decides validity below.
    if copied_path is not None:
        payload = _load_json(copied_path)
        metrics = extract_run_metrics(payload, telemetry_path, run_index,
                                      base_dir=exp_dir)
        metrics["telemetry_path"] = _portable_path(copied_path, exp_dir)
        if runner_error:
            # Keep the diagnostic, but do not let it erase recorded metrics.
            metrics["runner_error"] = runner_error
    else:
        metrics = extract_run_metrics({}, None, run_index)
        metrics["run_status"] = "failed"
        metrics["valid"] = False
        metrics["error"] = runner_error

    # Telemetry is authoritative for whether the run is valid: a run the
    # application recorded as non-completed is never promoted to a valid sample,
    # even if the runner process exited 0. ``extract_run_metrics`` already
    # classifies the payload; the runner-reported error is only extra evidence,
    # so it can invalidate a sample but never certify one.
    if not metrics.get("valid"):
        reason = metrics.get("invalid_reason") or "invalid_telemetry"
        metrics.setdefault("error", None)
        metrics["error"] = metrics["error"] or reason

    # Write metadata.json (non-secret).
    metadata = {
        "run_index": run_index,
        "experiment_id": experiment.get("experiment_id"),
        "case_id": case.get("case_id"),
        "ticker": case.get("ticker"),
        "trade_date": case.get("trade_date"),
        "status": "ok" if metrics.get("valid") else ("failed" if metrics.get("run_status") == "failed" else "ambiguous"),
        "run_status": metrics.get("run_status"),
        "original_telemetry_path": _portable_path(telemetry_path, exp_dir),
        "copied_telemetry_path": _portable_path(copied_path, exp_dir),
        "runner_status": status,
        "error": metrics.get("error"),
        "runner_error": metrics.get("runner_error"),
        "usage_complete": metrics.get("usage_complete"),
        "attribution_complete": metrics.get("attribution_complete"),
        "telemetry_complete": metrics.get("telemetry_complete"),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / METADATA_FILE).write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    # Final state: the run is now a completed attempt (resumable).
    state_path = _run_state_path(run_dir)
    if state_path.exists():
        state = _load_json(state_path)
    else:
        state = {"run_index": run_index, "experiment_id": experiment.get("experiment_id"),
                 "case_id": case.get("case_id")}
    state.update({
        "attempt": attempt,
        "status": "finished" if copied_path is not None else "failed",
        "run_status": metrics.get("run_status"),
        "telemetry_path": _portable_path(copied_path, exp_dir) if copied_path is not None else None,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
                          encoding="utf-8")
    return metrics


def _run_state_path(run_dir: Path) -> Path:
    return Path(run_dir) / RUN_STATE_FILE


def _migrate_flat_run(exp_dir: Path, run_index: int) -> Path | None:
    """Copy an old flat-layout run into ``run_NN/attempt_01`` (if needed).

    Earlier harness versions stored a run's artifacts directly in
    ``runs/run_NN``. Those artifacts are the record of a real measurement, so
    they are *copied* into the attempt layout (never moved or overwritten) and
    stamped ``migrated_from`` in both the state file and metadata. Returns the
    attempt directory, or None when there is nothing to migrate.
    """
    slot = _run_slot_dir(exp_dir, run_index)
    if not slot.is_dir():
        return None
    flat = [p for p in (slot / TELEMETRY_FILE, slot / METADATA_FILE,
                        slot / RUN_STATE_FILE, slot / RUNNER_REPORT_FILE) if p.is_file()]
    if not flat:
        return None
    target = _attempt_dir(exp_dir, run_index, 1)
    if target.exists() and any(p.name != "spec.json" for p in target.iterdir()):
        # A real attempt already lives here; never merge legacy files into it.
        return target
    target.mkdir(parents=True, exist_ok=True)
    for src in flat:
        dest = target / src.name
        if not dest.exists():
            shutil.copy2(src, dest)
    provenance = _portable_path(slot, exp_dir)
    state_path = target / RUN_STATE_FILE
    if state_path.exists():
        state = _load_json(state_path)
    else:
        state = {"run_index": run_index, "attempt": 1}
    state.setdefault("status", "finished" if (target / TELEMETRY_FILE).exists() else "failed")
    state["migrated_from"] = provenance
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
                          encoding="utf-8")
    meta_path = target / METADATA_FILE
    if meta_path.exists():
        meta = _load_json(meta_path)
        meta["migrated_from"] = provenance
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True),
                             encoding="utf-8")
    return target


def _read_attempt(run_dir: Path, run_index: int) -> dict | None:
    """Rebuild one attempt's metrics from its stored evidence.

    Returns None when the attempt is unfinished: either it has no state file
    (never started) or it was interrupted before folding telemetry into the
    attempt directory (started, but no copied ``telemetry.json``). An
    interrupted attempt is never overwritten in place and never counts as a
    sample; it simply stays on disk and the run is retried in a new attempt.
    """
    run_dir = Path(run_dir)
    state_path = _run_state_path(run_dir)
    if not state_path.exists():
        return None
    tele_path = run_dir / TELEMETRY_FILE
    if not tele_path.exists():
        return None
    metrics = extract_run_metrics(_load_json(tele_path), tele_path, run_index,
                                   base_dir=run_dir.parent.parent.parent)
    metrics["attempt"] = run_dir.name
    metrics["telemetry_path"] = _portable_path(
        tele_path, run_dir.parent.parent.parent)
    if not metrics.get("valid"):
        # The stored telemetry explains why this attempt is not a measured
        # sample (failed business run, failed LLM call, or missing usage), so a
        # re-summarize classifies it exactly like the original run did.
        metrics["error"] = metrics.get("error") or metrics.get("invalid_reason") or "invalid_telemetry"
    return metrics


def _summarized_attempt(exp_dir: Path, run_index: int) -> dict | None:
    """Return the metrics of the latest finished attempt of a run, if any.

    An interrupted attempt (state ``started``, no telemetry) is skipped rather
    than treated as the run's outcome: it carries no measurement, so letting it
    mask an earlier finished attempt would silently drop a real sample.
    """
    attempts = []
    for run_dir in attempt_dirs(exp_dir, run_index):
        metrics = _read_attempt(run_dir, run_index)
        if metrics is not None:
            attempts.append(metrics)
    return attempts[-1] if attempts else None


def _mark_run_started(exp_dir: Path, experiment: dict, case: dict, run_index: int,
                      attempt: int) -> None:
    path = _run_state_path(_attempt_dir(exp_dir, run_index, attempt))
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "run_index": run_index,
        "attempt": attempt,
        "experiment_id": experiment.get("experiment_id"),
        "case_id": case.get("case_id"),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "started",
    }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def run_experiment(exp_dir: Path, experiment: dict, *, runner=None,
                   continue_on_error: bool = False, dry_run: bool = False) -> dict:
    """Run every case `measured_runs` times and write the summary.

    Fail-fast by default: a failed/ambiguous run raises after preserving its
    metadata. ``continue_on_error`` skips and keeps going.

    Resumable: runs that already finished in this experiment directory are
    reused from their stored telemetry instead of being executed again, so an
    aborted experiment can be continued without mixing attempts.

    The working-tree fingerprint is captured before the first run and again
    after the last one. A change in between is recorded in ``code_state.json``
    and carried into ``summary.json`` as ``code_changed_during_measurement``;
    such a measurement is never reported as a valid baseline.
    """
    exp_dir = Path(exp_dir)
    code_state = write_code_state(exp_dir, experiment)
    fingerprint_start = code_state.get("working_tree_sha256")

    all_metrics = []
    n_runs_total = experiment.get("measured_runs")
    for case in experiment["cases"]:
        for run_index in range(1, n_runs_total + 1):
            if not dry_run:
                _migrate_flat_run(exp_dir, run_index)
                stored = _summarized_attempt(exp_dir, run_index)
                if stored is not None and stored.get("valid"):
                    print(f"[bench] run {run_index} of {n_runs_total} for "
                          f"{case_label(case)}: already completed ({stored.get('attempt')}), "
                          f"reusing telemetry")
                    all_metrics.append(stored)
                    continue
                if stored is not None:
                    print(f"[bench] run {run_index} of {n_runs_total} for "
                          f"{case_label(case)}: previous attempt "
                          f"{stored.get('attempt')} is not a measured sample "
                          f"({stored.get('error')}); retrying in a new attempt directory")
                    if continue_on_error:
                        all_metrics.append(stored)
                        continue
            attempt = None
            if not dry_run:
                attempt = len(attempt_dirs(exp_dir, run_index)) + 1
                _mark_run_started(exp_dir, experiment, case, run_index, attempt)
            print(f"[bench] run {run_index} of {n_runs_total} for {case_label(case)}")
            try:
                metrics = execute_measured_run(
                    exp_dir, experiment, case, run_index, runner=runner, dry_run=dry_run,
                    run_dir=(_attempt_dir(exp_dir, run_index, attempt)
                             if attempt is not None else None),
                )
            except Exception as exc:  # noqa: BLE001
                all_metrics.append({
                    "run_index": run_index, "run_status": "_launch_error", "valid": False,
                    "error": repr(exc),
                    "reported_input_tokens_sum": 0, "reported_output_tokens_sum": 0,
                    "total_tokens": 0, "llm_calls": 0, "tool_calls": 0, "tool_rounds": 0,
                    "duration_ms": None, "usage_complete": False, "attribution_complete": False,
                    "telemetry_complete": False, "usage_coverage_complete": False,
                    "reported_reasoning_tokens_sum": 0, "reported_cached_input_tokens_sum": 0,
                    "duplicate_tool_call_count": 0, "prefetched_data_calls": 0,
                    "event_counts": {}, "agents": {}, "telemetry_path": None,
                    "ticker": case.get("ticker"), "trade_date": case.get("trade_date"),
                })
                if not continue_on_error:
                    raise
                continue
            all_metrics.append(metrics)
            if not dry_run and not metrics.get("valid") and not continue_on_error:
                raise RuntimeError(
                    f"run {run_index} for {case_label(case)} is not valid "
                    f"(status={metrics.get('run_status')}); aborting. Re-run with "
                    f"--continue-on-error to skip."
                )

    if dry_run:
        return {"code_state": code_state, "metrics": all_metrics}

    # End-of-measurement capture happens before the summary is generated, so a
    # same-tree check cannot observe files written by this harness itself.
    end_state = write_code_state(exp_dir, experiment, previous=code_state)
    drift = fingerprint_drift(code_state, end_state)

    # Build per-case summaries in a combined structure. For the baseline there is
    # a single case, so the top-level "summary" is that case's summary (kept in
    # the canonical location); multi-case support appends per-case files too.
    all_metrics_by_case = {}
    for m in all_metrics:
        key = (m.get("ticker"), m.get("trade_date"))
        all_metrics_by_case.setdefault(key, []).append(m)

    summaries = {}
    for case in experiment["cases"]:
        key = (case.get("ticker"), case.get("trade_date"))
        case_metrics = all_metrics_by_case.get(key, [])
        summary = build_run_summary(case_metrics, experiment, case, exp_dir)
        summary.update({
            "working_tree_sha256": fingerprint_start,
            "working_tree_sha256_end": end_state.get("working_tree_sha256"),
            "fingerprint_algorithm": FINGERPRINT_ALGORITHM,
            "experiment_config_sha256": experiment_config_sha256(experiment),
        })
        if drift["code_changed_during_measurement"]:
            summary["code_changed_during_measurement"] = True
            summary["measurement_complete"] = False
        summaries[case.get("case_id")] = summary
    write_experiment_summaries(summaries, experiment, exp_dir)
    return {"code_state": end_state, "summaries": summaries, "metrics": all_metrics,
            "fingerprint": drift}


def _apply_recorded_fingerprint(summaries: dict, exp_dir: Path,
                                experiment: dict) -> None:
    """Carry the recorded code fingerprint into rebuilt summaries.

    Offline ``summarize`` must keep working on any machine, so it never
    recomputes the working-tree hash (that would describe *this* checkout, not
    the run). It reuses what ``code_state.json`` recorded during the run, and
    keeps the "code changed" verdict sticky so a re-summarize can never promote
    an invalidated measurement back to a valid baseline.
    """
    state: dict = {}
    state_path = Path(exp_dir) / CODE_STATE_FILE
    if state_path.exists():
        try:
            state = _load_json(state_path)
        except (OSError, ValueError):
            state = {}
    drift = bool(state.get("code_changed_during_measurement"))
    for summary in summaries.values():
        if state.get("working_tree_sha256"):
            summary["working_tree_sha256"] = (
                state.get("measurement_start_working_tree_sha256")
                or state.get("working_tree_sha256"))
        if state.get("working_tree_sha256"):
            summary["working_tree_sha256_end"] = state.get("working_tree_sha256")
        if state.get("fingerprint_algorithm"):
            summary["fingerprint_algorithm"] = state["fingerprint_algorithm"]
        if state.get("experiment_config_sha256"):
            summary["experiment_config_sha256"] = state["experiment_config_sha256"]
        if drift:
            summary["code_changed_during_measurement"] = True
            summary["measurement_complete"] = False


def summarize_experiment(exp_dir: Path, experiment: dict | None = None) -> dict:
    """Rebuild summary files from stored telemetry (no LLM calls)."""
    exp_dir = Path(exp_dir)
    if experiment is None:
        exp_file = exp_dir / EXPERIMENT_FILE
        if not exp_file.exists():
            raise FileNotFoundError(f"no {EXPERIMENT_FILE} at {exp_dir}")
        experiment = _load_json(exp_file)

    runs_slot = exp_dir / RUNS_DIR
    metrics_by_key = {}
    if runs_slot.is_dir():
        run_slots = sorted(d for d in runs_slot.iterdir()
                           if d.is_dir() and d.name.startswith("run_"))
        for run_slot in run_slots:
            idx = int(run_slot.name.rsplit("_", 1)[1])
            _migrate_flat_run(exp_dir, idx)
            # One sample per run: the latest finished attempt. Earlier invalid
            # attempts stay on disk as evidence but never contribute metrics.
            metrics = _summarized_attempt(exp_dir, idx)
            if metrics is None:
                continue
            # Metadata identifies the case; find the attempt directory that
            # produced these metrics (the latest one).
            attempt_dir = None
            recorded = _resolve_report_path(metrics.get("telemetry_path"), exp_dir)
            for candidate in attempt_dirs(exp_dir, idx):
                if recorded is not None and \
                        Path(recorded).resolve() == (candidate / TELEMETRY_FILE).resolve():
                    attempt_dir = candidate
            meta_path = (attempt_dir or attempt_dirs(exp_dir, idx)[-1]) / METADATA_FILE
            metadata = _load_json(meta_path) if meta_path.exists() else {}
            key = (metadata.get("ticker"), metadata.get("trade_date"))
            metrics_by_key.setdefault(key, []).append((idx, metrics))

    summaries = {}
    for case in experiment["cases"]:
        key = (case.get("ticker"), case.get("trade_date"))
        ordered = sorted(metrics_by_key.get(key, []), key=lambda t: t[0])
        case_metrics = [m for _idx, m in ordered]
        summary = build_run_summary(case_metrics, experiment, case, exp_dir)
        summaries[case.get("case_id")] = summary
    _apply_recorded_fingerprint(summaries, exp_dir, experiment)

    if not summaries:
        raise RuntimeError(f"no run telemetry found under {runs_slot}")
    write_experiment_summaries(summaries, experiment, exp_dir)
    return {"summaries": summaries}


# ---------------------------------------------------------------------------
# Hidden single-run (executed in the freshly spawned subprocess)
# ---------------------------------------------------------------------------
def _run_single(spec_path: str) -> int:
    """Execute ONE measured TradingAgents run inside the current process.

    This is invoked by ``run`` in a fresh Python subprocess to isolate global
    state / ContextVars / callbacks between measured runs. Imports the real
    TradingAgents execution path here (lazily) so the orchestrator can stay
    lightweight and run validation/summarize/compare without business imports.
    """
    spec = _load_json(Path(spec_path))
    case = spec["case"]
    run_index = spec.get("run_index")

    import traceback

    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = dict(DEFAULT_CONFIG)
    config["results_dir"] = spec.get("results_dir")
    config["llm_provider"] = spec.get("provider")
    config["quick_think_llm"] = spec.get("quick_model")
    config["deep_think_llm"] = spec.get("deep_model")
    config["max_debate_rounds"] = case.get("research_rounds")
    config["max_risk_discuss_rounds"] = case.get("risk_rounds")
    config["output_language"] = spec.get("output_language")
    # checkpoint disabled for benchmarks (each run is an independent sample).
    config["checkpoint_enabled"] = False

    handler = StatsCallbackHandler()
    graph = TradingAgentsGraph(
        selected_analysts=tuple(case.get("analysts") or ()),
        config=config,
        callbacks=[handler],
    )

    # Locate the telemetry artifact this run produced (run-scoped results_dir).
    # Historical artifacts from earlier attempts may coexist in this runtime
    # directory; only files created by *this* child qualify. Snapshot the set
    # before the graph starts so leftover artifacts never masquerade as a fresh,
    # multiple-artifact ambiguity.
    telemetry_path = None
    results_root = Path(spec.get("results_dir"))
    telemetry_before = _telemetry_snapshot(results_root)
    status = "completed"
    error = None
    try:
        graph.propagate(case["ticker"], case["trade_date"])
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        error_type = type(exc).__name__
        error = f"{error_type}: {exc}"
        traceback.print_exc()

    try:
        telemetry_path = _select_run_telemetry(results_root, telemetry_before, None)
    except RuntimeError as exc:
        if status == "completed":
            status = "ambiguous"
        error = error or str(exc)

    # Record a runner report for the orchestrator to read.
    report = {
        "run_index": run_index,
        "experiment_id": spec.get("experiment_id"),
        "ticker": case.get("ticker"),
        "trade_date": case.get("trade_date"),
        "status": status,
        "run_status": status,
        "error": error,
        "telemetry_path": _portable_path(telemetry_path, Path(spec_path).parent.parent.parent),
    }
    run_dir = Path(spec_path).parent
    (run_dir / RUNNER_REPORT_FILE).write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return 0 if status == "completed" else 1


# ---------------------------------------------------------------------------
# One-command measurement (archive directory + preflight + execution)
# ---------------------------------------------------------------------------
# Every one-shot measurement lives under this directory, one timestamped
# subtree per run. It is git-ignored: measurements are local evidence, while
# the harness, its tests, and the canonical template stay versioned.
MEASUREMENTS_DIR = "measurements"
# The canonical experiment used as the template for every measurement. It is
# only ever read — a measurement writes its own copy.
TEMPLATE_EXPERIMENT = Path("token_benchmarks") / "baseline_v2" / EXPERIMENT_FILE
# Env vars the CityU environment loader maps onto the names the app reads. Only
# these two are touched; nothing else from the secrets file is imported, so a
# stray export in that file can never change the benchmark's configuration.
_CITYU_ENV_MAP = (
    ("CITYU_FOUNDRY_API_KEY", "OPENAI_COMPATIBLE_API_KEY"),
    ("CITYU_FOUNDRY_BASE_URL", "TRADINGAGENTS_LLM_BACKEND_URL"),
)
# Material inputs copied from the template. Everything else (experiment_id,
# case_id, ticker, date, rounds) is derived from the invocation.
_TEMPLATE_KEYS = (
    "provider", "quick_model", "deep_model", "output_language", "cache_policy",
)


def _safe_label(label: str) -> str:
    """Reduce a free-text label to a filename-safe token.

    Never allowed to escape the measurements directory (`..`, `/`) and never
    empty, so a label cannot turn into a path or produce a surprising name.
    """
    raw = "" if label is None else str(label)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.strip())
    cleaned = re.sub(r"[-.]{2,}", "-", cleaned).strip("-._")
    return cleaned[:48] or "manual"


def _dirname_component(value: str) -> str:
    """Ticker/date component: filesystem-safe and lowercase for stable sort."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    cleaned = cleaned.strip("-._")
    return cleaned[:48] or "unknown"


def measurements_root(repo_root: Path) -> Path:
    return Path(repo_root) / "token_benchmarks" / MEASUREMENTS_DIR


def new_measurement_dir(repo_root: Path, *, ticker: str, trade_date: str,
                        label: str, now: datetime | None = None) -> Path:
    """Return a fresh, never-reused directory for one measurement.

    Name: ``<local timestamp>_<ticker>_<date>_<label>``. The directory is
    created atomically so two invocations in the same second get distinct
    paths (``-2``, ``-3``, ...) instead of one overwriting the other.
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    base = (f"{stamp}_{_dirname_component(ticker)}_"
            f"{_dirname_component(trade_date)}_{_safe_label(label)}")
    root = measurements_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        candidate = root / (base if n == 1 else f"{base}-{n}")
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            n += 1


def build_measurement_experiment(template: dict, *, experiment_id: str,
                                 ticker: str, trade_date: str, runs: int) -> dict:
    """Derive a measurement's experiment definition from the canonical template.

    Only the invocation-dependent fields change; provider, models, language,
    cache policy, analyst set and debate/risk rounds are carried over verbatim
    so a measurement measures the same thing as the baseline.
    """
    if not template.get("cases"):
        raise ValueError("template experiment has no cases")
    base_case = template["cases"][0]
    case = {
        "case_id": re.sub(r"[^A-Za-z0-9]+", "_", f"{ticker}_{trade_date}").strip("_").lower(),
        "ticker": ticker,
        "trade_date": trade_date,
        "analysts": list(base_case.get("analysts") or list(VALID_ANALYSTS)),
        "research_rounds": base_case.get("research_rounds"),
        "risk_rounds": base_case.get("risk_rounds"),
    }
    exp = {
        "schema_version": TOOL_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "description": template.get("description") or "Token benchmark measurement",
        "measured_runs": runs,
        "cases": [case],
    }
    for key in _TEMPLATE_KEYS:
        exp[key] = template.get(key)
    return exp


def write_measurement_notes(exp_dir: Path, *, experiment: dict, label: str,
                            tool_version: str | None = None) -> Path:
    """Write the human-readable provenance note for one measurement."""
    case = experiment["cases"][0]
    lines = [
        f"# {experiment['experiment_id']}",
        "",
        "## Purpose",
        "",
        f"Token measurement requested with label `{label}`.",
        "Generated by `scripts/run_token_benchmark.sh` from the canonical",
        f"template `{TEMPLATE_EXPERIMENT.as_posix()}`.",
        "",
        "## Configuration",
        "",
        f"- ticker: {case.get('ticker')}",
        f"- trade_date: {case.get('trade_date')}",
        f"- analysts: {', '.join(case.get('analysts') or [])}",
        f"- research rounds: {case.get('research_rounds')}",
        f"- risk rounds: {case.get('risk_rounds')}",
        f"- provider: {experiment.get('provider')}",
        f"- quick model: {experiment.get('quick_model')}",
        f"- deep model: {experiment.get('deep_model')}",
        f"- output language: {experiment.get('output_language')}",
        f"- cache policy: {experiment.get('cache_policy')}",
        f"- measured runs: {experiment.get('measured_runs')}",
        "",
        "## Reproducibility",
        "",
        "`code_state.json` records the branch, HEAD, whether the working tree had",
        "uncommitted changes, and the diff fingerprint at measurement time. A",
        "dirty tree is recorded as-is, not treated as a guarantee of",
        "reproducibility: the numbers below describe *this* tree, and",
        "re-running the command on a different tree may produce different numbers",
        "(LLM sampling is not deterministic even on identical code).",
        "",
        "## Results",
        "",
        "See `summary.md` (readable), `summary.json` (machine), `summary.csv`",
        "(per run) and `summary_agents.csv` (per agent). Failed attempts are kept",
        "under `runs/run_NN/attempt_MM/` and never averaged in.",
        "",
    ]
    path = Path(exp_dir) / NOTE_FILE
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _env_file_values(path: Path) -> dict[str, str]:
    """Parse simple ``KEY=VALUE`` lines without executing the file.

    The secrets file is data, not a shell script: no ``source``, no command
    substitution, no expansion. Only the keys we explicitly map are used.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def apply_cityu_env(env: MutableMapping[str, str], secrets_path: Path) -> list[str]:
    """Map the CityU secrets onto the app's env vars. Returns the names applied.

    Existing values in ``env`` win, so an explicitly exported variable is never
    silently overridden. Names are returned, never values.
    """
    file_values = _env_file_values(Path(secrets_path))
    applied = []
    for source, target in _CITYU_ENV_MAP:
        value = file_values.get(source)
        if value and not env.get(target):
            env[target] = value
            applied.append(target)
    return applied


def required_cityu_env() -> list[str]:
    """The target variable names a real measurement needs to be configured."""
    return [target for _source, target in _CITYU_ENV_MAP]


def _run_path_from_report(metrics: dict, exp_dir: Path) -> Path | None:
    resolved = _resolve_report_path(metrics.get("telemetry_path"), Path(exp_dir))
    return Path(resolved) if resolved else None


def verify_measurement(exp_dir: Path, summary: dict) -> dict:
    """Cross-check a summary against the telemetry it claims to come from.

    Returns ``{"ok", "checks", "failures", "n_valid", "n_target"}``. These are
    *consistency* checks (does the report match the evidence?), deliberately
    separate from the validity rules in :func:`run_invalidity_reason`, which are
    never relaxed here.
    """
    exp_dir = Path(exp_dir)
    runs = summary.get("runs") or []
    checks: list[dict] = []
    failures: list[str] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")

    target = summary.get("measured_target")
    valid = [m for m in runs if m.get("valid")]
    n_valid = len(valid)

    record("run_count_matches_target", len(runs) == target,
           f"{len(runs)} stored run(s) for target {target}")
    record("valid_runs_match_summary", summary.get("measured_valid") == n_valid,
           f"summary says {summary.get('measured_valid')}, counted {n_valid}")

    # Every run: tokens must equal the per-run total, and the totals must be the
    # sum of the recorded LLM events in that run's own telemetry artifact.
    for m in runs:
        idx = m.get("run_index")
        tag = f"run_{idx:02d}" if isinstance(idx, int) else f"run_{idx}"
        expected = (m.get("reported_input_tokens_sum") or 0) + \
                   (m.get("reported_output_tokens_sum") or 0)
        record(f"{tag}_token_sum", expected == m.get("total_tokens"),
               f"input+output={expected} total_tokens={m.get('total_tokens')}")
        if not m.get("valid"):
            record(f"{tag}_invalid_reason", bool(m.get("invalid_reason") or m.get("error")),
                   f"reason={m.get('invalid_reason') or m.get('error')}")
            continue
        path = _run_path_from_report(m, exp_dir)
        if path is None or not path.is_file():
            record(f"{tag}_telemetry_present", False, f"missing telemetry at {path}")
            continue
        payload = _load_json(path)
        events = payload.get("llm_call_events") or []
        ev_in = sum(int((e.get("reported_input_tokens") or 0)) for e in events)
        ev_out = sum(int((e.get("reported_output_tokens") or 0)) for e in events)
        record(f"{tag}_events_match_tokens",
               ev_in == (m.get("reported_input_tokens_sum") or 0)
               and ev_out == (m.get("reported_output_tokens_sum") or 0),
               f"events={ev_in}/{ev_out} summary="
               f"{m.get('reported_input_tokens_sum')}/{m.get('reported_output_tokens_sum')}")
        record(f"{tag}_no_llm_errors", not llm_error_count(payload),
               f"llm_errors={llm_error_count(payload)}")
        record(f"{tag}_usage_complete", bool(payload.get("usage_coverage", {}).get("complete")),
               "provider usage accounted for every call")
        record(f"{tag}_attribution_complete",
               bool((payload.get("audit_quality") or {}).get("attribution_complete")),
               "no unattributed LLM/tool events")
        record(f"{tag}_telemetry_complete",
               bool((payload.get("audit_quality") or {}).get("telemetry_complete")),
               "telemetry finalized for a terminal run")

    # Code integrity: the fingerprint recorded at the start must equal the one
    # recorded at the end. A missing fingerprint is a failure, not a pass, so an
    # old artifact can never be mistaken for a verified baseline.
    start_hash = summary.get("working_tree_sha256")
    end_hash = summary.get("working_tree_sha256_end")
    record("code_fingerprint_recorded", bool(start_hash),
           f"start fingerprint={start_hash}")
    record("code_unchanged_during_measurement",
           bool(start_hash) and start_hash == end_hash
           and not summary.get("code_changed_during_measurement"),
           f"start={start_hash} end={end_hash}")

    # Averages must cover exactly the valid runs.
    for key, agg in (summary.get("run_totals") or {}).items():
        record(f"mean_{key}_n", (agg or {}).get("n") == n_valid,
               f"n={(agg or {}).get('n')} vs valid {n_valid}")

    # A consistency pass is not a completion: fewer valid runs than requested
    # is a failure in its own right, never something to average around.
    record("all_runs_valid", n_valid == target,
           f"{n_valid} valid of {target} requested")

    return {
        "ok": not failures,
        "checks": checks,
        "failures": failures,
        "n_valid": n_valid,
        "n_target": target,
        "code_changed_during_measurement": bool(
            summary.get("code_changed_during_measurement")),
    }


def measurement_status(summary: dict, verification: dict) -> str:
    """Short verdict used in the console output and ``notes.md``."""
    if verification.get("code_changed_during_measurement"):
        return (f"INVALID: code_changed_during_measurement"
                f" ({verification['n_valid']}/{verification['n_target']} valid)")
    if verification["n_valid"] == verification["n_target"] and verification["ok"]:
        return f"{verification['n_valid']}/{verification['n_target']} valid"
    return (f"INCOMPLETE: {verification['n_valid']}/{verification['n_target']} valid"
            f" ({len(verification['failures'])} check failure(s))")


def write_measurement_report(exp_dir: Path, *, summary: dict, verification: dict,
                             label: str, code_state: dict) -> Path:
    """Append the verification verdict to ``notes.md`` (the readable entry point)."""
    path = Path(exp_dir) / NOTE_FILE
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    status = measurement_status(summary, verification)
    lines = [
        "",
        "## Verification",
        "",
        f"- status: **{status}**",
        f"- label: `{label}`",
        f"- git branch: {code_state.get('git_branch')}",
        f"- git HEAD: {code_state.get('git_head_commit')}",
        f"- working tree dirty: {code_state.get('git_working_tree_dirty')}",
        f"- diff fingerprint: {code_state.get('git_diff_sha256')}",
        f"- working-tree fingerprint ({code_state.get('fingerprint_algorithm')}): "
        f"{code_state.get('working_tree_sha256') or code_state.get('measurement_start_working_tree_sha256')}",
        f"- fingerprinted files: {code_state.get('file_count')}",
        f"- experiment config sha256: {code_state.get('experiment_config_sha256')}",
        "",
    ]
    if verification.get("code_changed_during_measurement"):
        lines.append("**code_changed_during_measurement** — the working tree changed "
                     "while the measurement ran; this result is not a valid baseline.")
        lines.append("")
    if verification["failures"]:
        lines.append("Failed checks:")
        lines.append("")
        lines.extend(f"- {f}" for f in verification["failures"])
    else:
        lines.append(f"All {len(verification['checks'])} consistency checks passed.")
    lines.append("")
    status_file = Path(exp_dir) / MEASUREMENT_STATUS_FILE
    status_file.write_text(json.dumps({
        "status": status,
        "ok": verification["ok"],
        "valid_runs": verification["n_valid"],
        "target_runs": verification["n_target"],
        "label": label,
        "checks": verification["checks"],
        "failures": verification["failures"],
        "experiment_id": summary.get("experiment_id"),
        "code_state": code_state,
    }, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    path.write_text(existing.rstrip() + "\n" + "\n".join(lines), encoding="utf-8")
    return path


def _cmd_measure(args) -> int:
    repo_root = Path(args.repo_root).resolve()
    template_path = repo_root / TEMPLATE_EXPERIMENT
    if not template_path.is_file():
        print(f"error: template experiment not found at {template_path}")
        return 1
    template = _load_json(template_path)

    # Credentials are resolved before any artifact is written, so a missing key
    # fails fast without leaving a half-configured measurement behind.
    if not args.dry_run and args.secrets_file:
        secrets_path = Path(args.secrets_file).expanduser()
        if not secrets_path.is_file():
            print(f"error: credentials file not found: {secrets_path}")
            return 1
        apply_cityu_env(os.environ, secrets_path)
        missing = [name for name in required_cityu_env() if not os.environ.get(name)]
        if missing:
            print("error: missing required credential(s): " + ", ".join(missing))
            return 1
    if not template.get("cases"):
        print("error: template experiment has no cases")
        return 1
    template_case = template["cases"][0]

    # Defaults come from the template, never from "today": a measurement must
    # stay comparable with the baseline it is being compared against.
    ticker = args.ticker if args.ticker is not None else template_case.get("ticker")
    trade_date = args.date if args.date is not None else template_case.get("trade_date")
    runs = args.runs if args.runs is not None else template.get("measured_runs")

    if not ticker or not str(ticker).strip():
        print("error: --ticker must not be empty")
        return 1
    if not trade_date or not str(trade_date).strip():
        print("error: --date must not be empty")
        return 1
    if runs is None:
        print("error: the template does not define measured_runs; pass --runs")
        return 1
    # ``int(2.5)`` would silently become 2, so reject non-integral values
    # explicitly instead of quietly measuring a different count.
    try:
        if isinstance(runs, bool) or not isinstance(runs, (int, str)):
            raise TypeError
        runs_int = int(runs)
        if isinstance(runs, str) and runs.strip() != str(runs_int):
            raise ValueError
    except (TypeError, ValueError):
        print(f"error: --runs must be a positive integer, got {runs!r}")
        return 1
    if runs_int <= 0:
        print(f"error: --runs must be a positive integer, got {runs!r}")
        return 1
    runs = runs_int
    label = _safe_label(args.label)

    exp_dir = new_measurement_dir(repo_root, ticker=ticker,
                                  trade_date=trade_date, label=label)
    experiment = build_measurement_experiment(
        template,
        experiment_id=f"{exp_dir.name}",
        ticker=ticker, trade_date=trade_date, runs=int(runs),
    )
    (exp_dir / EXPERIMENT_FILE).write_text(
        json.dumps(experiment, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_measurement_notes(exp_dir, experiment=experiment, label=label)

    errors = validate_experiment(experiment)
    if errors:
        for e in errors:
            print(f"error: {e}")
        print(f"experiment: {exp_dir}")
        return 1

    print(f"experiment: {experiment['experiment_id']}", flush=True)
    print(f"results:    {exp_dir}", flush=True)
    if args.dry_run:
        code_state = write_code_state(exp_dir, experiment)
        result = run_experiment(exp_dir, experiment, dry_run=True)
        print(f"dry run completed; no LLM called, no telemetry produced")
        print(f"planned runs: {len(result.get('metrics') or [])}")
        return 0

    try:
        run_experiment(exp_dir, experiment, continue_on_error=args.continue_on_error)
    except Exception as exc:  # noqa: BLE001 - report progress, keep evidence
        print(f"error: measurement aborted: {exc}", file=sys.stderr)
        summary_path = exp_dir / SUMMARY_JSON
        if summary_path.exists():
            summary = _load_json(summary_path)
            verification = verify_measurement(exp_dir, summary)
            code_state = _load_json(exp_dir / CODE_STATE_FILE) \
                if (exp_dir / CODE_STATE_FILE).exists() else {}
            code_state.setdefault("measurement_start_working_tree_sha256",
                                  summary.get("working_tree_sha256"))
            write_measurement_report(exp_dir, summary=summary,
                                     verification=verification, label=label,
                                     code_state=code_state)
            print(f"status: {measurement_status(summary, verification)}")
        _print_measure_epilogue(exp_dir, summary_path if summary_path.exists() else None)
        return 1

    summary = _load_json(exp_dir / SUMMARY_JSON)
    verification = verify_measurement(exp_dir, summary)
    code_state = _load_json(exp_dir / CODE_STATE_FILE) \
        if (exp_dir / CODE_STATE_FILE).exists() else {}
    code_state.setdefault("measurement_start_working_tree_sha256",
                          summary.get("working_tree_sha256"))
    write_measurement_report(exp_dir, summary=summary, verification=verification,
                             label=label, code_state=code_state)
    if verification["ok"] and verification["n_valid"] == verification["n_target"]:
        print(f"Benchmark completed: {verification['n_valid']}/{verification['n_target']} valid")
    else:
        print(f"Benchmark INCOMPLETE: {verification['n_valid']}/{verification['n_target']} valid")
        for failure in verification["failures"][:10]:
            print(f"  - {failure}")
    print(f"Experiment: {experiment['experiment_id']}")
    print(f"Results: {exp_dir}")
    print(f"Report: {exp_dir / SUMMARY_MD}")
    return 0 if (verification["ok"] and verification["n_valid"] == verification["n_target"]) else 3


def _print_measure_epilogue(exp_dir: Path, summary_path: Path | None) -> None:
    print(f"Experiment: {exp_dir.name}")
    print(f"Results: {exp_dir}")
    if summary_path is not None:
        print(f"Report: {exp_dir / SUMMARY_MD}")


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {raw!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"expected a positive integer, got {raw!r}")
    return value


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _cmd_init(args) -> int:
    out_root = Path(args.output_root).resolve()
    exp_dir = out_root / args.id
    if exp_dir.exists() and not args.force:
        print(f"error: experiment already exists at {exp_dir} (use --force to overwrite)")
        return 2
    exp_dir.mkdir(parents=True, exist_ok=True)
    exp = default_experiment(args.id, out_root)
    (exp_dir / EXPERIMENT_FILE).write_text(
        json.dumps(exp, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    notes_path = exp_dir / NOTE_FILE
    if not notes_path.exists() or args.force:
        notes_path.write_text(default_notes(args.id), encoding="utf-8")
    print(f"created {exp_dir / EXPERIMENT_FILE}")
    print(f"created {notes_path}")
    return 0


def _cmd_validate(args) -> int:
    entry = Path(args.experiment)
    path = entry if entry.name == EXPERIMENT_FILE else entry / EXPERIMENT_FILE
    data = _load_json(path)
    errors = validate_experiment(data)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    exp = data
    print("experiment is valid")
    print(f"  experiment_id : {exp['experiment_id']}")
    print(f"  measured_runs : {exp['measured_runs']}")
    print(f"  provider      : {exp['provider']}")
    print(f"  quick_model   : {exp['quick_model']}")
    print(f"  deep_model    : {exp['deep_model']}")
    print(f"  cache_policy  : {exp['cache_policy']}")
    for c in exp["cases"]:
        print(f"  case: {case_label(c)}")
        print(f"    analysts    : {', '.join(c['analysts'])}")
        print(f"    research_rounds: {c['research_rounds']}")
        print(f"    risk_rounds : {c['risk_rounds']}")
    return 0


def _cmd_run(args) -> int:
    entry = Path(args.experiment)
    path = entry if entry.name == EXPERIMENT_FILE else entry / EXPERIMENT_FILE
    data = _load_json(path)
    errors = validate_experiment(data)
    if errors:
        for e in errors:
            print(f"error: {e}")
        return 1
    exp_dir = path.parent.resolve()
    run_experiment(
        exp_dir, data,
        continue_on_error=args.continue_on_error,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("dry run completed; no telemetry produced")
        return 0
    print(f"wrote {exp_dir / SUMMARY_JSON}")
    print(f"wrote {exp_dir / SUMMARY_CSV}")
    print(f"wrote {exp_dir / SUMMARY_AGENTS_CSV}")
    print(f"wrote {exp_dir / SUMMARY_MD}")
    return 0


def _cmd_summarize(args) -> int:
    exp_dir = Path(args.experiment_dir)
    summarize_experiment(exp_dir)
    print(f"wrote {exp_dir / SUMMARY_JSON}")
    print(f"wrote {exp_dir / SUMMARY_CSV}")
    print(f"wrote {exp_dir / SUMMARY_AGENTS_CSV}")
    print(f"wrote {exp_dir / SUMMARY_MD}")
    return 0


def _cmd_compare(args) -> int:
    baseline = load_summary(Path(args.baseline))
    candidate = load_summary(Path(args.candidate))
    try:
        cmp = compare_summaries(baseline, candidate, allow_mismatch=args.override)
    except ValueError as exc:
        print(f"error: {exc}")
        return 1
    print(format_comparison(cmp))
    return 0


def _cmd_run_single(args) -> int:
    return _run_single(args.spec)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="token_benchmark",
        description="Token benchmark harness for TradingAgents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a starter experiment directory")
    p.add_argument("--id", required=True)
    p.add_argument("--output-root", required=True)
    p.add_argument("--force", action="store_true", help="overwrite an existing experiment")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("validate", help="validate an experiment JSON (no LLM)")
    p.add_argument("--experiment", required=True)
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("run", help="run measured runs and write summaries")
    p.add_argument("--experiment", required=True)
    p.add_argument("--continue-on-error", action="store_true",
                   help="skip invalid runs instead of aborting (they stay in the "
                        "summary as invalid and never count as measured samples)")
    p.add_argument("--dry-run", action="store_true",
                   help="validate + orchestrate without executing an LLM run")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("summarize", help="rebuild summaries from stored telemetry")
    p.add_argument("--experiment-dir", required=True)
    p.set_defaults(func=_cmd_summarize)

    p = sub.add_parser("compare", help="compare candidate vs baseline summaries")
    p.add_argument("--baseline", required=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--override", action="store_true",
                   help="compare despite mismatched material inputs")
    p.set_defaults(func=_cmd_compare)

    p = sub.add_parser("_run-single", help=argparse.SUPPRESS)
    p.add_argument("--spec", required=True)
    p.set_defaults(func=_cmd_run_single)

    p = sub.add_parser(
        "measure",
        help="one-shot measurement: new timestamped dir, validate, run, verify",
    )
    p.add_argument("--repo-root", required=True,
                   help="repository root (the measurement is archived under "
                        "token_benchmarks/measurements/)")
    p.add_argument("--label", default="manual",
                   help="free-form label; sanitized for the directory name")
    p.add_argument("--ticker", default=None,
                   help="override the template ticker")
    p.add_argument("--date", default=None,
                   help="override the template trade date (YYYY-MM-DD)")
    p.add_argument("--runs", type=_positive_int, default=None,
                   help="number of measured runs (default: template value)")
    p.add_argument("--dry-run", action="store_true",
                   help="create the experiment and validate it without calling an LLM")
    p.add_argument("--secrets-file", default=None,
                   help="read CityU credentials from this file (key=value data, "
                        "never sourced); missing keys abort before any LLM call")
    p.add_argument("--continue-on-error", action="store_true",
                   help="keep going after an invalid run (it still never counts "
                        "as a measured sample)")
    p.set_defaults(func=_cmd_measure)

    return parser


def main(argv=None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
