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
from collections.abc import Mapping, MutableMapping
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
# v2 adds the fields the CAND-01 2x2 registration needs -- ``switches``,
# ``news_scope`` and ``budget`` -- and the run-level ``experiment_root``. The
# validator still accepts v1 so every archived experiment stays readable.
TOOL_SCHEMA_VERSION = 2
#: 3 adds the per-run memory-isolation contract (V3).
SUPPORTED_EXPERIMENT_SCHEMAS = (1, 2, 3)

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
#: The registered batch. Its specs, switch matrix and protocol *are* the
#: experiment: the fingerprint has to cover them or it describes code that ran
#: a study nobody registered. It did not cover them, and audit B round 4
#: (B-15) showed the consequence: edit a registration's ``deep_model``, commit,
#: rewrite the untracked ``FROZEN_COMMIT``, re-run the freeze writer, and the
#: gate printed "GATE PASSED -- safe to spend money" for a different
#: experiment. ``c3/`` stays excluded (see below) because it *states* the
#: fingerprint.
_FINGERPRINT_BATCH_PREFIX = "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/"
_FINGERPRINT_BATCH_INCLUDE = (
    "specs/",
    "SWITCH_MATRIX.csv",
    "experiment.json",
    "CAND01_BATCH_2X2_PROTOCOL_V2.md",
    "C3_PROTOCOL_FREEZE.md",
    "RUN_MANIFEST_TEMPLATE.csv",
)
_FINGERPRINT_INCLUDE_PREFIXES = (
    "tradingagents/",
    "cli/",
    "scripts/",
    "tests/",
    "token_benchmarks/baseline_v1/experiment.json",
    "token_benchmarks/baseline_v2/experiment.json",
    *(_FINGERPRINT_BATCH_PREFIX + name for name in _FINGERPRINT_BATCH_INCLUDE),
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
    # The freeze record states the fingerprint. Fingerprinting the file that
    # contains the fingerprint is a fixed point that cannot be satisfied --
    # writing the number changes the number -- so it is excluded, exactly like
    # code_state.json. It is itself hashed by c3/MANIFEST-style verification.
    "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2/c3/",
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

    if data.get("schema_version") not in (None,) + SUPPORTED_EXPERIMENT_SCHEMAS:
        errors.append(
            f"schema_version must be one of {SUPPORTED_EXPERIMENT_SCHEMAS} "
            f"got {data.get('schema_version')!r}"
        )

    # Budget configuration (U-2). A block that is present must be interpretable;
    # an absent block stays legal here because generic experiments may not use
    # the spend gate at all. The frozen batch *requires* the block, and that is
    # enforced on the run path (``_preflight_registration``).
    if "budget" in data:
        state = budget_state_from_experiment(data)
        if not state["ok"]:
            errors.append(f"budget: {state['state']}: {state['detail']}")

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
    """Extract per-agent token/tool metrics from a telemetry agents entry.

    A missing total is reported as ``0`` because a report column cannot hold
    ``null`` forever without breaking every reader -- but it is *flagged*, so a
    reader can tell "this agent used no tokens" from "this agent's tokens were
    not measured". Without the flag the two collapse into the same number, and
    a per-agent comparison would silently compare an unmeasured agent against a
    measured one as if both were facts (audit C-05p).
    """
    raw_inp = agent.get("reported_input_tokens_sum")
    raw_out = agent.get("reported_output_tokens_sum")
    inp = raw_inp or 0
    out = raw_out or 0
    # ``calls_without_provider_usage`` is the field the telemetry actually
    # publishes; reading only ``llm_calls_missing_usage`` (which it never
    # publishes) made this flag always-true (limitation L-5, audit C-6).
    missing_calls = int(
        agent.get("calls_without_provider_usage")
        or agent.get("llm_calls_missing_usage")
        or 0
    )
    missing_input = int(agent.get("llm_calls_missing_input_tokens") or 0)
    missing_output = int(agent.get("llm_calls_missing_output_tokens") or 0)
    measured = int(agent.get("llm_calls") or 0) > 0
    usage_complete = bool(measured and not (missing_calls or missing_input or missing_output))
    return {
        # ``True`` only when every one of this agent's calls reported both
        # halves of its usage; ``False`` means the token totals are a lower
        # bound and must not be compared as if exact.
        "usage_complete": usage_complete,
        "measured": measured,
        "llm_calls_missing_usage": missing_calls,
        "llm_calls_missing_input_tokens": missing_input,
        "llm_calls_missing_output_tokens": missing_output,
        "token_totals_are_lower_bound": not usage_complete,
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
INVALID_USAGE_INCOMPLETE = "token_usage_incomplete"
INVALID_USAGE_MISMATCH = "token_usage_mismatch"
INVALID_TELEMETRY_INCOMPLETE = "telemetry_incomplete"
INVALID_BUDGET_CONFIG = "budget_config_invalid"
INVALID_MEMORY_BASELINE_MODIFIED = "memory_snapshot_modified"
INVALID_MEMORY_STATE_MISSING = "memory_state_missing"
# Attribution sentinels, mirrored from tradingagents.observability so the
# validator does not import the product at module load.
_ATTRIBUTION_NONE = "none"
_AGENT_UNATTRIBUTED = "unattributed"

#: The four usage verdicts (audit C round 5, U-1). They are a *decision*, not a
#: description: only ``VALID`` may produce a measured sample.
USAGE_VALID = "VALID"
USAGE_MISSING = "MISSING"
USAGE_INCOMPLETE = "INCOMPLETE"
USAGE_MISMATCH = "MISMATCH"
USAGE_STATES = (USAGE_VALID, USAGE_MISSING, USAGE_INCOMPLETE, USAGE_MISMATCH)

_USAGE_INVALID_REASON = {
    USAGE_MISSING: INVALID_USAGE_MISSING,
    USAGE_INCOMPLETE: INVALID_USAGE_INCOMPLETE,
    USAGE_MISMATCH: INVALID_USAGE_MISMATCH,
}


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


def _as_count(value) -> int | None:
    """A non-negative integer count, or ``None`` when the value is not one."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def usage_verdict(payload: dict, *, replay_used: int | None = None) -> dict:
    """Decide whether provider usage and telemetry agree, and how completely.

    Independent audit C round 5 (U-1) found that ``agrees_with_telemetry`` was
    *computed and never consumed*: a run whose replay disagreed with its own
    totals still reported ``valid=True``. A check that cannot fail is not a
    check, so the verdict is now the gate on validity.

    Four states, mutually exclusive, checked in this order:

    ``MISMATCH``
        The payload contradicts itself or the replay: usage counts that do not
        add up to the call count, negative totals, per-call events that do not
        sum to the run totals, a negative count in the preserved vendor blob, or
        a replay total that differs from the telemetry total.
    ``MISSING``
        No provider usage was reported for a run that made calls (or no calls
        at all): there is nothing to measure.
    ``INCOMPLETE``
        Some usage exists but not for every call, some field was omitted, an
        event could not be attributed to an agent, the run did not finalize, or
        the preserved raw blob is absent for a call that reported usage.
    ``VALID``
        Everything above holds.

    A payload that predates per-call records (no ``llm_call_events`` key) is
    not treated as a mismatch: its replay is *inconclusive*, not contradictory.
    The verdict then rests on the telemetry's own coverage fields, and the
    inconclusiveness is reported rather than hidden.
    """
    coverage = payload.get("usage_coverage") or {}
    run_totals = payload.get("run_totals") or {}
    audit = payload.get("audit_quality") or {}
    checks = payload.get("usage_checks") or {}
    raw_events = payload.get("llm_call_events")
    events = [e for e in (raw_events or []) if isinstance(e, dict)] if isinstance(
        raw_events, (list, tuple)) else []
    # A payload produced by the current observability layer always carries
    # ``usage_checks`` *and* a list of per-call records. If it carries the
    # checks but the records are not a list, the usage cannot be attributed at
    # all -- that is a contradiction, not the legacy aggregate shape.
    malformed_events = ("usage_checks" in payload
                        and not isinstance(raw_events, (list, tuple)))
    # Per-call cross-checks need per-call records. A payload with no records at
    # all is the legacy/aggregate shape: its replay is *inconclusive*, not
    # contradictory, and saying so is more honest than inventing a mismatch.
    # ``usage_checks`` is written by the observability layer for every run, so
    # a payload that carries it and still has no events for a non-zero call
    # count is a genuine contradiction and is treated as one.
    events_recorded = bool(
        isinstance(raw_events, list)
        and (events or "usage_checks" in payload)
    )

    problems: list[str] = []
    mismatch: list[str] = []
    incomplete: list[str] = []

    calls = _as_count(coverage.get("llm_calls"))
    if calls is None:
        calls = _as_count(run_totals.get("llm_calls"))
    with_usage = _as_count(coverage.get("calls_with_provider_usage"))
    without_usage = _as_count(coverage.get("calls_without_provider_usage"))
    missing_input = _as_count(coverage.get("calls_missing_input_tokens"))
    missing_output = _as_count(coverage.get("calls_missing_output_tokens"))
    totals_in = _as_count(run_totals.get("reported_input_tokens_sum"))
    totals_out = _as_count(run_totals.get("reported_output_tokens_sum"))

    # --- contradictions ---------------------------------------------------
    if totals_in is None or totals_out is None:
        mismatch.append("run totals are not non-negative integers")
    if calls is not None and with_usage is not None and without_usage is not None:
        if with_usage + without_usage != calls:
            mismatch.append(
                f"usage counts do not add up: {with_usage} with + "
                f"{without_usage} without != {calls} calls")
    elif calls is not None:
        mismatch.append("usage coverage counts are missing")
    if malformed_events:
        mismatch.append(
            "per-call usage records are malformed (llm_call_events is not a list)")
    negative_preserved = _as_count(checks.get("negative_token_counts"))
    if negative_preserved:
        mismatch.append(
            f"the provider blob carries {negative_preserved} negative token count(s)")
    if events_recorded and calls:
        if len(events) > calls:
            mismatch.append(
                f"{len(events)} call events for a run that reports {calls} calls")
        event_in = 0
        event_out = 0
        event_with_usage = 0
        for ev in events:
            if ev.get("usage_source") is None:
                continue
            event_with_usage += 1
            if isinstance(ev.get("reported_input_tokens"), int):
                event_in += ev["reported_input_tokens"]
            if isinstance(ev.get("reported_output_tokens"), int):
                event_out += ev["reported_output_tokens"]
        if with_usage is not None and event_with_usage != with_usage:
            mismatch.append(
                f"{event_with_usage} events carry usage but coverage says "
                f"{with_usage}")
        if totals_in is not None and event_in != totals_in:
            mismatch.append(
                f"per-call input tokens sum to {event_in}, totals say {totals_in}")
        if totals_out is not None and event_out != totals_out:
            mismatch.append(
                f"per-call output tokens sum to {event_out}, totals say {totals_out}")
    if replay_used is not None and totals_in is not None and totals_out is not None \
            and events_recorded:
        if replay_used != totals_in + totals_out:
            mismatch.append(
                f"usage replay counted {replay_used} tokens, telemetry totals "
                f"say {totals_in + totals_out}")

    # --- absence ----------------------------------------------------------
    if calls is None or calls == 0:
        problems.append("the run recorded no LLM call")
    elif with_usage == 0:
        problems.append("no provider usage was reported for any call")

    # --- incompleteness ---------------------------------------------------
    if without_usage:
        incomplete.append(f"{without_usage} of {calls or '?'} calls reported no usage")
    if missing_input:
        incomplete.append(f"{missing_input} call(s) omitted input tokens")
    if missing_output:
        incomplete.append(f"{missing_output} call(s) omitted output tokens")
    if coverage.get("complete") is False:
        incomplete.append("the telemetry's own usage_coverage is not complete")
    if audit.get("usage_complete") is False:
        incomplete.append("audit_quality.usage_complete is false")
    if audit.get("attribution_complete") is not True:
        # ``is False`` let a missing flag, or an integer 0, pass as attributed.
        incomplete.append("usage could not be attributed (attribution_complete is not true)")
    # The aggregate flag is the producer's self-report; an event that says
    # ``attribution_type="none"`` (or, for schema-1 payloads, an
    # ``agent_id="unattributed"`` without a system type) is direct evidence and
    # must invalidate the run even if the flag was tampered with.
    raw_events = payload.get("llm_call_events")
    events = ([event for event in raw_events if isinstance(event, dict)]
              if isinstance(raw_events, list) else [])
    unattributed_events = [
        event for event in events
        if event.get("attribution_type") == _ATTRIBUTION_NONE
        or ("attribution_type" not in event
            and event.get("agent_id") == _AGENT_UNATTRIBUTED)
    ]
    if unattributed_events:
        incomplete.append(
            f"{len(unattributed_events)} provider call(s) carry no attribution in the event log")
    attribution_summary = payload.get("attribution")
    if isinstance(attribution_summary, dict):
        if attribution_summary.get("unattributed_calls"):
            incomplete.append(
                f"the attribution summary counts {attribution_summary['unattributed_calls']} "
                f"unattributed call(s)")
        try:
            accounted = (int(attribution_summary.get("agent_calls") or 0)
                         + int(attribution_summary.get("system_calls") or 0)
                         + int(attribution_summary.get("unattributed_calls") or 0))
        except (TypeError, ValueError):
            accounted = None
        if calls and accounted is not None and accounted != calls:
            mismatch.append(
                f"the attribution summary accounts for {accounted} calls, the run made {calls}")
    if audit.get("telemetry_complete") is False:
        incomplete.append("the run did not finalize its telemetry")
    if payload.get("unattributed_llm_events"):
        incomplete.append(
            f"{payload.get('unattributed_llm_events')} unattributed LLM event(s)")
    if payload.get("unattributed_tool_events"):
        incomplete.append(
            f"{payload.get('unattributed_tool_events')} unattributed tool event(s)")
    if checks:
        preserved = _as_count(checks.get("raw_usage_preserved"))
        expected = _as_count(checks.get("raw_usage_expected"))
        if expected and (preserved is None or preserved < expected):
            incomplete.append(
                f"the raw usage blob was kept for {preserved or 0} of {expected} calls")

    if mismatch:
        state = USAGE_MISMATCH
        reasons = mismatch + incomplete
    elif problems:
        state = USAGE_MISSING
        reasons = problems + incomplete
    elif incomplete:
        state = USAGE_INCOMPLETE
        reasons = incomplete
    else:
        state = USAGE_VALID
        reasons = []

    invalid = _USAGE_INVALID_REASON.get(state)
    # A run that never finalized is not merely "usage incomplete": its artifact
    # does not describe a completed run at all. Keeping the two distinct keeps
    # the reason actionable (audit C's original distinction).
    if state == USAGE_INCOMPLETE and audit.get("telemetry_complete") is False:
        invalid = INVALID_TELEMETRY_INCOMPLETE

    return {
        "state": state,
        "reasons": reasons,
        "calls": calls,
        "calls_with_provider_usage": with_usage,
        "calls_without_provider_usage": without_usage,
        "reported_input_tokens_sum": totals_in,
        "reported_output_tokens_sum": totals_out,
        "replay_used_tokens": replay_used,
        "replay_conclusive": events_recorded,
        "event_records_present": events_recorded,
        "negative_token_counts": negative_preserved or 0,
        "invalid_reason": invalid,
    }


def _usage_problem(payload: dict) -> str | None:
    """The invalid reason implied by the usage verdict, or ``None``."""
    return usage_verdict(payload)["invalid_reason"]



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
    return _usage_problem(payload)


# ---------------------------------------------------------------------------
# Budget configuration semantics (audit C round 5, U-2)
# ---------------------------------------------------------------------------
#: A cap of ``None`` means "no ceiling" *only* when the registration says so.
#: It used to be indistinguishable from "the protocol file is missing", "the
#: JSON is broken" or "the field was never written", and every one of those
#: collapsed to the same silent ``None``.
BUDGET_MODE_UNCAPPED = "uncapped_authorized"
BUDGET_MODE_CAPPED = "capped"
BUDGET_MODES = (BUDGET_MODE_UNCAPPED, BUDGET_MODE_CAPPED)

BUDGET_OK = "OK"
BUDGET_FILE_MISSING = "BUDGET_PROTOCOL_MISSING"
BUDGET_FILE_UNREADABLE = "BUDGET_PROTOCOL_UNREADABLE"
BUDGET_MALFORMED = "BUDGET_CONFIG_MALFORMED"
BUDGET_BLOCK_MISSING = "BUDGET_BLOCK_MISSING"
BUDGET_BLOCK_NOT_OBJECT = "BUDGET_BLOCK_NOT_OBJECT"
BUDGET_MODE_MISSING = "BUDGET_MODE_MISSING"
BUDGET_MODE_INVALID = "BUDGET_MODE_INVALID"
BUDGET_CAP_INVALID = "BUDGET_CAP_INVALID"


def budget_state_from_experiment(experiment: dict | None,
                                 *, source: str = "<registration>") -> dict:
    """Interpret one registration's ``budget`` block.

    Returns ``{"ok", "state", "mode", "max_total_tokens", "detail", "source"}``
    where ``state`` is one of the explicit codes above. The states are distinct
    on purpose: an operator who sees ``BUDGET_PROTOCOL_MISSING`` goes looking
    for the file, while ``BUDGET_MODE_MISSING`` means the file is there and the
    contract is not. Both refuse.
    """
    def bad(state: str, detail: str) -> dict:
        return {"ok": False, "state": state, "mode": None,
                "max_total_tokens": None, "detail": detail, "source": source}

    if experiment is None or not isinstance(experiment, dict):
        return bad(BUDGET_MALFORMED, "the experiment registration is not an object")
    if "budget" not in experiment:
        return bad(BUDGET_BLOCK_MISSING,
                   "the registration declares no 'budget' block")
    budget = experiment["budget"]
    if not isinstance(budget, dict):
        return bad(BUDGET_BLOCK_NOT_OBJECT,
                   f"'budget' must be an object, got {type(budget).__name__}")

    if "budget_mode" not in budget:
        return bad(
            BUDGET_MODE_MISSING,
            "no 'budget_mode'; a null cap cannot be distinguished from an "
            "unconfigured one, so this registration cannot be interpreted")
    mode = budget["budget_mode"]
    if not isinstance(mode, str) or mode not in BUDGET_MODES:
        return bad(BUDGET_MODE_INVALID,
                   f"budget_mode {mode!r} is not one of {list(BUDGET_MODES)}")

    if "max_total_tokens" not in budget:
        return bad(BUDGET_CAP_INVALID,
                   "'max_total_tokens' is absent; write it explicitly, even as null")
    cap = budget["max_total_tokens"]

    if mode == BUDGET_MODE_UNCAPPED:
        if cap is not None:
            return bad(BUDGET_CAP_INVALID,
                       f"budget_mode={BUDGET_MODE_UNCAPPED} requires "
                       f"max_total_tokens=null, got {cap!r}")
        return {"ok": True, "state": BUDGET_OK, "mode": mode,
                "max_total_tokens": None,
                "detail": "uncapped by explicit authorisation", "source": source}

    # capped
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 0:
        return bad(BUDGET_CAP_INVALID,
                   f"budget_mode={BUDGET_MODE_CAPPED} requires a non-negative "
                   f"integer max_total_tokens, got {cap!r}")
    return {"ok": True, "state": BUDGET_OK, "mode": mode, "max_total_tokens": cap,
            "detail": f"capped at {cap} tokens", "source": source}


def load_budget_state(path: Path) -> dict:
    """Read and interpret a registration file's budget block.

    The three ways this can fail before the block is even reached are reported
    separately -- missing file, unreadable file, unparseable JSON -- because the
    operator's next action differs for each.
    """
    path = Path(path)
    if not path.is_file():
        return {"ok": False, "state": BUDGET_FILE_MISSING, "mode": None,
                "max_total_tokens": None, "source": str(path),
                "detail": f"{path} does not exist"}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "state": BUDGET_FILE_UNREADABLE, "mode": None,
                "max_total_tokens": None, "source": str(path),
                "detail": f"{path} cannot be read: {exc}"}
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {"ok": False, "state": BUDGET_MALFORMED, "mode": None,
                "max_total_tokens": None, "source": str(path),
                "detail": f"{path} is not valid JSON: {exc}"}
    return budget_state_from_experiment(data, source=str(path))


def require_budget_state(experiment: dict | None, *,
                         source: str = "<registration>") -> dict:
    """Return the interpreted budget block, or refuse with ``RunRefused``.

    Every failure mode is a refusal: a budget contract that cannot be read is
    not the same experiment as one that explicitly authorises no ceiling, and
    the difference decides whether a run may be counted.
    """
    state = budget_state_from_experiment(experiment, source=source)
    if not state["ok"]:
        raise RunRefused(
            f"budget configuration is not usable ({state['state']}): "
            f"{state['detail']} [{source}]")
    return state


def require_budget_file(path: Path) -> dict:
    """As :func:`require_budget_state`, but reading the registration from disk."""
    state = load_budget_state(path)
    if not state["ok"]:
        raise RunRefused(
            f"budget configuration is not usable ({state['state']}): "
            f"{state['detail']} [{state['source']}]")
    return state


def _experiment_budget(exp_dir: Path | None = None) -> dict:
    """The frozen batch's budget state (or the given registration's).

    Never returns a bare ``None``: callers get a state they can report, so
    "uncapped" and "unreadable" cannot be confused downstream.
    """
    if exp_dir is not None:
        path = Path(exp_dir) / EXPERIMENT_FILE
        return load_budget_state(path)
    here = Path(__file__).resolve().parent.parent
    path = here / "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2" / EXPERIMENT_FILE
    return load_budget_state(path)


def _budget_for_run(exp_dir: Path, experiment: dict | None = None) -> tuple[dict | None, int | None]:
    """The budget contract for one run directory, and its cap.

    ``(None, None)`` means the registration states no contract at all (a
    generic experiment that never opted into the spend gate). A *present* block
    that cannot be interpreted is returned as a non-ok state so the caller can
    fail closed; it is never silently flattened to "uncapped". Used by the run
    path and by re-summarisation so both classify a stored attempt the same way
    (audit round 2, F3: re-summarising could otherwise report UNCAPPED for a
    registration whose contract was unreadable).
    """
    exp_dir = Path(exp_dir)
    if _is_frozen_batch_registration(exp_dir):
        state = _experiment_budget(exp_dir)
        return state, state["max_total_tokens"]
    if experiment is not None:
        if "budget" not in experiment:
            return None, None
        state = budget_state_from_experiment(
            experiment, source=f"{exp_dir}/{EXPERIMENT_FILE}")
        return state, state["max_total_tokens"]
    path = exp_dir / EXPERIMENT_FILE
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return ({"ok": False, "state": BUDGET_MALFORMED, "mode": None,
                 "max_total_tokens": None, "source": str(path),
                 "detail": f"cannot read the registration: {exc}"}, None)
    if not isinstance(data, dict) or "budget" not in data:
        return None, None
    state = budget_state_from_experiment(data, source=str(path))
    return state, state["max_total_tokens"]


def _experiment_token_cap() -> int | None:
    """This round's cap **if** the budget contract is usable, else ``None``.

    This is a convenience accessor, not a validity decision: ``None`` here can
    mean either "explicitly uncapped" or "the contract is unusable", which is
    why the run path uses :func:`_budget_for_run` and reports the state instead
    of calling this. Kept for callers that only need the number.
    """
    state = _experiment_budget()
    if not state["ok"]:
        return None
    return state["max_total_tokens"]



def _budget_summary(payload: dict, run_totals: dict, usage_coverage: dict,
                    *, max_total_tokens: int | None = None,
                    budget_state: dict | None = None) -> dict:
    """Report the spend gate's state for one run (``BUDGET_GUARD_DESIGN.md``).

    The gate is built from the run's own telemetry: every recorded call is
    replayed into it so ``used`` counts each call once and an unmeasured call
    makes the total a lower bound. The cap comes from the experiment's
    ``budget.max_total_tokens``, which is ``null`` this round -- so the state is
    ``UNCAPPED`` unless usage was missing, in which case ``UNKNOWN_SPEND`` is
    reported even though nothing blocks.

    This is reporting, not enforcement: the cap is absent by design and a
    ``null`` cap must never be replaced with a fallback (see the design doc §1).
    """
    from tradingagents.budget_guard import BudgetGate

    gate = BudgetGate(max_total_tokens=max_total_tokens)
    events = payload.get("llm_call_events")
    if not isinstance(events, (list, tuple)):
        # A tampered artifact can carry any JSON type here. The usage verdict
        # already calls that a mismatch; the replay must not raise on it and
        # abort an offline re-summarise of the whole study (audit round 3).
        events = []
    seen: dict[str, dict] = {}
    for position, ev in enumerate(events):
        if not isinstance(ev, dict):
            # Older payloads carry bare values in this section; they describe no
            # call this gate can attribute, so they are not replayed.
            continue
        # Deduplicate on the *callback* run id, which is unique per call. The
        # telemetry run id identifies the whole run, so using it as the fallback
        # collapsed every call of a run into one and made the replay disagree
        # with the run's own totals (U-1: the mismatch this produced was real,
        # but it was the replay's bug, not the payload's).
        rid = ev.get("callback_run_id")
        key = str(rid) if rid is not None else f"__event_{position}"
        seen[key] = {
            "run_id": key,
            "input": ev.get("reported_input_tokens"),
            "output": ev.get("reported_output_tokens"),
            "reported": ev.get("usage_source") is not None,
        }
    gate.record_calls(seen.values())
    info = gate.describe()
    # Report the *contract* that produced the cap, not just the number: a bare
    # ``null`` used to be ambiguous between "authorised uncapped" and "no budget
    # configuration could be read" (U-2).
    if budget_state is not None:
        info["mode"] = budget_state.get("mode")
        info["config_state"] = budget_state.get("state")
        info["config_source"] = budget_state.get("source")
        info["cap_authorised"] = bool(budget_state.get("ok"))
    # Cross-check against the telemetry totals the report also publishes; a
    # disagreement means the replay and the aggregate disagree, which the reader
    # must know about rather than see silently resolved.
    totals_in = _as_count(run_totals.get("reported_input_tokens_sum"))
    totals_out = _as_count(run_totals.get("reported_output_tokens_sum"))
    calls = _as_count(usage_coverage.get("llm_calls"))
    with_usage = _as_count(usage_coverage.get("calls_with_provider_usage"))
    no_usage_measured = bool(calls) and with_usage == 0
    telemetry_total = (None if totals_in is None or totals_out is None
                       or no_usage_measured
                       else totals_in + totals_out)
    info["telemetry_total_tokens"] = telemetry_total
    info["telemetry_total_known"] = telemetry_total is not None
    # "Agrees" is a claim about two known numbers. When either side is unknown
    # the honest answer is False, not True: an unmeasured total cannot agree
    # with anything (U-1).
    info["agrees_with_telemetry"] = (
        telemetry_total is not None and info["used_tokens"] == telemetry_total
    )
    info["calls_without_provider_usage"] = (
        usage_coverage.get("calls_without_provider_usage") or 0
    )
    return info


def extract_run_metrics(payload: dict, telemetry_path: Path | None,
                        run_index: int, *, base_dir: Path | None = None,
                        max_total_tokens: int | None = None,
                        budget_state: dict | None = None) -> dict:
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

    # A token total is only a measurement when it is known. ``... or 0`` turned
    # an unmeasured run into a measured zero (audit C round 5, U-1 / L-5), so
    # the value stays ``None`` and every renderer shows N/A instead.
    inp = _as_count(run_totals.get("reported_input_tokens_sum"))
    out = _as_count(run_totals.get("reported_output_tokens_sum"))

    run_status = run.get("run_status")
    usage_complete = bool(usage_coverage.get("complete"))
    invalid_reason = run_invalidity_reason(payload)

    agents_metrics = {}
    for agent_id, agg in (payload.get("agents", {}) or {}).items():
        agents_metrics[agent_id] = _extract_agent_metrics(agg)

    budget = _budget_summary(payload, run_totals, usage_coverage,
                            max_total_tokens=max_total_tokens,
                            budget_state=budget_state)

    # U-1: the verdict is now taken *with* the replay, so a payload whose
    # per-run replay disagrees with its own totals is MISMATCH and the run is
    # void. Previously ``agrees_with_telemetry`` was computed here and never
    # consulted, so a disagreeing run still reported ``valid=True``.
    verdict = usage_verdict(payload, replay_used=budget.get("used_tokens"))
    if verdict["state"] != USAGE_VALID:
        invalid_reason = invalid_reason or verdict["invalid_reason"]

    # A run whose entire usage is missing has no token total at all: leave it
    # unknown rather than publishing the collector's 0. A partial run keeps its
    # observed numbers and is flagged as a lower bound.
    totals_are_lower_bound = verdict["state"] in (USAGE_INCOMPLETE, USAGE_MISMATCH)
    if verdict["state"] == USAGE_MISSING:
        inp = out = None

    # A run that blew its cap is not a comparable sample: it stopped early by
    # construction, so publishing its token total beside uncapped runs would
    # invite exactly the wrong comparison. ``check()`` was previously never
    # called anywhere in production (audit C-04r), which made the gate's
    # refusal unreachable. This round is uncapped, so the branch cannot fire --
    # which is the point of wiring it: it is checked, and it would fire.
    if budget.get("blocks_run"):
        invalid_reason = invalid_reason or "budget_exhausted"

    # The same container guard as the replay: a tampered artifact may carry any
    # JSON type here, and counting it must not abort an offline re-summarise.
    raw_event_records = payload.get("llm_call_events")
    if not isinstance(raw_event_records, (list, tuple)):
        raw_event_records = []
    event_counts = {
        "llm_call_events": len(raw_event_records),
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
        "total_tokens": None if inp is None or out is None else inp + out,
        "totals_are_lower_bound": totals_are_lower_bound,
        "usage_verdict": verdict,
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
        "budget": budget,
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
    lines.append("| Run | Input | Output | Total | LLM | Tools | Rounds | Runtime | Status | Valid | Spend |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in summary["runs"]:
        lines.append(
            f"| {m['run_index']:02d} | {_fmt(m['reported_input_tokens_sum'])} | "
            f"{_fmt(m['reported_output_tokens_sum'])} | {_fmt(m['total_tokens'])} | "
            f"{_fmt(m['llm_calls'])} | {_fmt(m['tool_calls'])} | {_fmt(m['tool_rounds'])} | "
            f"{_fmt(m['duration_ms'])} | {m['run_status']} | {_validity_label(m)} | "
            f"{_budget_label(_budget(m))} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _budget(metric: dict) -> dict:
    """The run's spend summary, or an empty dict when it recorded none."""
    value = metric.get("budget")
    return value if isinstance(value, dict) else {}


def _budget_cell(cap) -> str:
    """Render a token cap for a CSV cell, keeping ``None`` distinct from blank."""
    return "null" if cap is None else str(cap)


def _budget_label(budget: dict) -> str:
    """One markdown cell describing the run's spend state.

    ``UNCAPPED`` and ``UNKNOWN_SPEND`` are different claims and must not both
    render as an empty cell: the first says the cap is absent by design, the
    second says the spend could not be measured (audit C-04b/c/d).
    """
    state = budget.get("state") or "UNKNOWN"
    used = budget.get("used_tokens")
    if budget.get("cap_authorised") is False:
        # The run is invalid because its budget contract could not be read; the
        # gate's own state is still UNCAPPED (no cap was applied), so rendering
        # only that word would describe the run as authorised (audit round 3).
        return (f"contract unusable "
                f"({budget.get('config_state') or 'unknown'}) — invalid")
    if state == "UNCAPPED":
        return "uncapped"
    if state == "UNKNOWN_SPEND":
        return "UNKNOWN_SPEND (lower bound)" if budget.get("used_is_lower_bound") \
            else "UNKNOWN_SPEND"
    if state == "EXHAUSTED":
        return "EXHAUSTED"
    cap = budget.get("max_total_tokens")
    return f"{used}/{cap}" if cap is not None else state


def write_summary_csv(summary: dict, experiment: dict, path: Path) -> None:
    fieldnames = [
        "experiment_id", "case_id", "case", "run_index", "ticker", "trade_date",
        "run_status", "input_tokens", "output_tokens", "total_tokens",
        "cached_input_tokens", "llm_calls", "tool_calls", "tool_rounds",
        "runtime_ms", "usage_complete", "attribution_complete", "telemetry_complete",
        "valid", "invalid_reason", "llm_errors", "telemetry_path",
        # Budget state belongs in the primary table, not only in JSON: an
        # UNKNOWN_SPEND or EXHAUSTED run must be visible to anyone reading the
        # CSV, and a null cap must be distinguishable from a missing one
        # (audit C-04b/c/d).
        "budget_state", "budget_max_total_tokens", "budget_used_tokens",
        "budget_used_is_lower_bound",
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
                "budget_state": _budget(m).get("state", ""),
                "budget_max_total_tokens": _budget_cell(
                    _budget(m).get("max_total_tokens")),
                "budget_used_tokens": _budget(m).get("used_tokens", ""),
                "budget_used_is_lower_bound": _budget(m).get(
                    "used_is_lower_bound", ""),
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


# ---------------------------------------------------------------------------
# Per-run memory isolation (V3)
# ---------------------------------------------------------------------------
# Every run starts from one immutable snapshot and writes only its own copy.
# Without this, a decision written by one run becomes a pending entry that the
# *next* run reflects on before the graph starts -- the run order then changes
# the token cost and the execution path, which is not acceptable for a
# controlled comparison.
MEMORY_DIRNAME = "memory"
MEMORY_FILE = "trading_memory.md"
MEMORY_STATE_FILE = "memory_state.json"
MEMORY_BLOCK_MODE = "per_run_snapshot_copy"


def memory_summary(path: Path) -> dict:
    """Entry/pending counts of a memory log, read with the product's own parser."""
    from tradingagents.agents.utils.memory import TradingMemoryLog

    log = TradingMemoryLog({"memory_log_path": str(path)})
    entries = log.load_entries()
    return {
        "entry_count": len(entries),
        "pending_count": sum(1 for entry in entries if entry.get("pending")),
        "sha256": _sha256_file(Path(path)) if Path(path).is_file() else None,
    }


def _requires_memory_isolation(definition: dict | None) -> bool:
    """V3 registrations (or any registration that declares ``memory``) must isolate."""
    if not isinstance(definition, dict):
        return False
    if "memory" in definition:
        return True
    return str(definition.get("protocol_version") or "").startswith("V3")


def _batch_requires_memory_isolation(registration_dir: Path) -> bool:
    """Whether a registration's *batch* declares the memory contract.

    A per-run registration can be edited to drop ``memory`` and
    ``protocol_version``; the batch experiment cannot be, because the gate
    reads it as well. This is the durable half of the requirement.
    """
    path = Path(registration_dir)
    directory = path.parent if path.is_file() else path
    batch = _memory_batch_dir(directory)
    try:
        experiment = _load_json(batch / EXPERIMENT_FILE)
    except Exception:  # noqa: BLE001 - no readable batch contract to enforce
        return False
    return _requires_memory_isolation(experiment)


def _memory_batch_dir(exp_dir: Path) -> Path:
    """The batch directory a registration lives in (``<batch>/specs/<run>``)."""
    return Path(exp_dir).resolve().parents[1]


def memory_block_for_registration(exp_dir: Path, experiment: dict) -> dict | None:
    """Resolve and validate a registration's memory snapshot declaration."""
    block = experiment.get("memory")
    if block is None:
        return None
    if not isinstance(block, dict):
        raise RunRefused("registration 'memory' must be an object")
    if block.get("mode") != MEMORY_BLOCK_MODE:
        raise RunRefused(
            f"registration memory mode {block.get('mode')!r} is not "
            f"{MEMORY_BLOCK_MODE!r}; a run without a snapshot copy cannot be a sample")
    relpath = block.get("baseline_relpath")
    if not relpath or not isinstance(relpath, str):
        raise RunRefused("registration memory block has no baseline_relpath")
    baseline = (_memory_batch_dir(exp_dir) / relpath).resolve()
    if not baseline.is_file():
        raise RunRefused(f"memory snapshot is missing: {baseline}")
    actual = _sha256_file(baseline)
    declared = block.get("baseline_sha256")
    if not declared or actual != declared:
        raise RunRefused(
            f"memory snapshot {baseline} hashes to {actual[:16]}…, but the "
            f"registration declares {str(declared)[:16]}…; the snapshot changed")
    return {"mode": MEMORY_BLOCK_MODE, "baseline_path": str(baseline),
            "baseline_sha256": actual, "baseline_relpath": relpath}


def prepare_run_memory(exp_dir: Path, experiment: dict, run_dir: Path) -> dict:
    """Copy the snapshot into ``run_dir`` and describe the isolated state."""
    block = memory_block_for_registration(exp_dir, experiment)
    if block is None:
        return {}
    baseline = Path(block["baseline_path"])
    memory_dir = Path(run_dir) / MEMORY_DIRNAME
    memory_dir.mkdir(parents=True, exist_ok=True)
    run_path = memory_dir / MEMORY_FILE
    shutil.copyfile(baseline, run_path)
    copied = _sha256_file(run_path)
    if copied != block["baseline_sha256"]:
        raise RunRefused("the per-run memory copy does not match its snapshot")
    summary = memory_summary(run_path)
    return {
        **block,
        "run_memory_path": str(run_path),
        "run_initial_sha256": copied,
        "pending_before": summary["pending_count"],
        "entry_count_before": summary["entry_count"],
        "memory_isolation_mode": MEMORY_BLOCK_MODE,
    }


def validate_memory_spec(spec: dict, *, attempt_dir: Path | None = None) -> dict:
    """Refuse a spec whose memory isolation cannot be proven.

    Runs before any paid call: the snapshot must still hash to its declared
    value, the run copy must exist, be byte-identical to the snapshot, and live
    inside this attempt's directory. A run whose memory cannot be isolated is
    not a controlled sample.
    """
    block = spec.get("memory")
    if not isinstance(block, dict) or not block:
        raise RunRefused("spec carries no memory isolation block")
    if block.get("mode") != MEMORY_BLOCK_MODE:
        raise RunRefused(f"unsupported memory isolation mode {block.get('mode')!r}")
    baseline_path = Path(str(block.get("baseline_path") or "")).resolve()
    run_path = Path(str(block.get("run_memory_path") or "")).resolve()
    declared = block.get("baseline_sha256")
    initial = block.get("run_initial_sha256")
    if not baseline_path.is_file():
        raise RunRefused(f"memory snapshot is missing: {baseline_path}")
    actual = _sha256_file(baseline_path)
    if not declared or actual != declared:
        raise RunRefused(
            f"memory snapshot changed: {actual[:16]}… != {str(declared)[:16]}…")
    if not run_path.is_file():
        raise RunRefused(f"run memory copy is missing: {run_path}")
    if run_path == baseline_path:
        raise RunRefused("the run memory path is the shared snapshot")
    if initial != declared:
        raise RunRefused("the run memory copy was not initialised from the snapshot")
    if _sha256_file(run_path) != initial:
        raise RunRefused(
            "the run memory copy was modified before the graph started; a run "
            "must begin from the immutable snapshot")
    if attempt_dir is not None:
        try:
            run_path.relative_to(Path(attempt_dir).resolve())
        except ValueError:
            raise RunRefused(
                f"run memory copy {run_path} is outside its attempt directory "
                f"{attempt_dir}") from None
    return block


def memory_state_after_run(spec: dict) -> dict:
    """State of the snapshot and the run copy after the graph finished."""
    block = spec.get("memory") or {}
    baseline = Path(str(block.get("baseline_path") or ""))
    run_path = Path(str(block.get("run_memory_path") or ""))
    if not block or not run_path.is_file():
        return {}
    summary = memory_summary(run_path)
    baseline_after = _sha256_file(baseline) if baseline.is_file() else None
    return {
        "memory_isolation_mode": block.get("mode"),
        "baseline_sha256": block.get("baseline_sha256"),
        "baseline_sha256_after": baseline_after,
        "baseline_unchanged": baseline_after == block.get("baseline_sha256"),
        "run_initial_sha256": block.get("run_initial_sha256"),
        "run_final_sha256": summary["sha256"],
        "run_changed": summary["sha256"] != block.get("run_initial_sha256"),
        "pending_before": block.get("pending_before"),
        "pending_after": summary["pending_count"],
        "entry_count_before": block.get("entry_count_before"),
        "entry_count_after": summary["entry_count"],
    }


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


#: Fields that describe *this invocation* rather than the registered definition.
#: ``results_dir`` and ``registration_dir`` are absolute host paths;
#: ``switches_source`` is provenance wording ("declared" in the delivered spec,
#: "registered" in a spec the parent builds) that cannot change the experiment.
#: Excluding them is what makes the digest recorded in ``effective_config.json``
#: match the released spec (audit round 2: it did not).
_SPEC_BODY_EXCLUDED = frozenset({"results_dir", "registration_dir", "switches_source"})


def spec_body_sha256(spec: dict) -> str:
    """SHA-256 of a run spec minus the machine-specific / internal fields.

    The same definition the spec generator and the delivered ``MANIFEST.sha256``
    use; a test pins the two implementations together, because a run's recorded
    value is only useful if it can be matched against the release.

    Excluded: ``results_dir`` (host-specific) and any key beginning with ``_``
    (runtime markers such as ``_spec_path``, which the child adds to its own
    copy). Including a marker made the value recorded in
    ``effective_config.json`` differ from the release's, so the one link back to
    the registered artefact was broken for every real run.
    """
    body = {k: v for k, v in spec.items()
            if k not in _SPEC_BODY_EXCLUDED and not str(k).startswith("_")}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False,
                           separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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


def compute_code_state(exp_dir: Path | None, experiment: dict | None = None) -> dict:
    """The code-state document, without writing it to ``exp_dir``.

    Used by dry runs and by callers that need the fingerprint only. Keeping it
    separate from ``write_code_state`` is what lets a rehearsal report the tree
    it *would* record without overwriting the recorded one.
    """
    state = capture_code_state(experiment)
    state["code_state_phase"] = "start_of_measurement"
    return state


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
                          reported_path: str | None,
                          reported_base: Path | None = None) -> Path:
    """Select this run's telemetry artifact from files created since ``before``.

    Only artifacts that did not exist before the run qualify, so leftover files
    from earlier attempts never make a valid re-run ambiguous. Exactly one new
    artifact is accepted. Zero is a failure and more than one is an ambiguity,
    even if the child reported one of them: silently picking the reported file
    would mask a genuine multi-artifact problem.

    ``reported_path`` may be relative: the child runs with its cwd set to the
    experiment directory and records a ``_portable_path``, while ``before``
    holds absolute snapshot strings. ``reported_base`` is the directory such a
    relative path is anchored to (the experiment dir at the call site); when it
    is ``None`` the path is resolved against the current working directory.
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
    if reported_path:
        reported = Path(reported_path)
        if not reported.is_absolute() and reported_base is not None:
            reported = Path(reported_base) / reported
        # Compare by resolved identity, not by spelling: the same artifact can
        # legitimately arrive under two different strings. ``resolve`` also
        # makes the comparison symlink- and ".."-safe. A genuinely different
        # file still fails below, so the single-artifact contract is unchanged.
        if reported.resolve() != selected.resolve():
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


def _is_frozen_batch_registration(exp_dir: Path) -> bool:
    """Is ``exp_dir`` one of the 16 registered directories of this batch?"""
    try:
        resolved = Path(exp_dir).resolve()
    except OSError:
        return False
    specs = _frozen_batch_dir() / "specs"
    if not specs.is_dir():
        return False
    return resolved.parent.resolve() == specs.resolve()


def build_run_spec(exp_dir: Path, experiment: dict, case: dict, run_index: int,
                   attempt: int = 1) -> dict:
    """Build the run spec the child reads, without writing it.

    Split out of :func:`prepare_run_spec` so a dry run can rehearse the *exact*
    spec a paid run would receive while leaving no trace on disk.
    """
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
        # Pinned into the spec so the child can prove it imported the tree this
        # experiment was registered against, instead of trusting its cwd.
        "experiment_root": str(_PROJECT_ROOT),
        # Where this run's registration lives, so the child can recompute
        # config_sha256 against the full definition rather than trusting a
        # 64-character string it was handed.
        "registration_dir": str(Path(exp_dir).resolve()),
        "run_index": run_index,
    }
    # The registered arm must travel with the spec. Omitting ``switches`` here
    # made ``_apply_spec_switches`` return ``{}``, so every arm silently ran
    # ``default_config`` -- four labels, one arm, 16 paid runs wasted. The
    # registration is the authority; copy it rather than re-deriving it.
    for inherited in ("switches", "config_sha256", "news_scope", "budget"):
        if inherited in experiment:
            spec[inherited] = experiment[inherited]
    # The arm travels unconditionally. ``prepare_run_spec`` used to copy these
    # only when present, so an armless registration produced an armless spec,
    # which the child then accepted and ran at ``DEFAULT_CONFIG`` (AB) while
    # labelled with whatever arm the directory name implied (audit A round 4,
    # H-B). A registration that cannot state its arm must fail here, loudly.
    # Enforced only for a registration that belongs to the frozen batch. A
    # registration outside it (a test fixture, a non-arm ablation) is not an
    # arm of this study, so it is not this function's job to invent one.
    if _is_frozen_batch_registration(exp_dir):
        absent = [key for key in ("switches", "config_sha256", "news_scope", "budget")
                  if key not in spec]
        if absent:
            raise RunRefused(
                f"registration {experiment.get('experiment_id')!r} does not state "
                f"{absent}; a run spec cannot carry an arm it was never given"
            )
    if "switches" in spec:
        spec["switches_source"] = "registered"
    # Memory isolation is part of the registered definition for this study: the
    # spec names the snapshot and the per-run copy the child must use.
    block = memory_block_for_registration(exp_dir, experiment)
    if block is not None:
        spec["memory"] = block
    return spec


def prepare_run_spec(exp_dir: Path, experiment: dict, case: dict, run_index: int,
                     attempt: int = 1) -> Path:
    """Write the run spec JSON the child reads to run one measurement."""
    run_dir = _attempt_dir(exp_dir, run_index, attempt)
    run_dir.mkdir(parents=True, exist_ok=True)
    spec = build_run_spec(exp_dir, experiment, case, run_index, attempt)
    memory = prepare_run_memory(exp_dir, experiment, run_dir)
    if memory:
        spec["memory"] = memory
        validate_memory_spec(spec, attempt_dir=run_dir)
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
    child_env = _child_env_for_spec(spec)
    try:
        proc = subprocess.run(args, cwd=str(exp), capture_output=True, text=True,
                              timeout=None, env=child_env)
    except Exception as exc:  # noqa: BLE001
        return {"status": "it_failed", "error": f"subprocess launch failed: {exc!r}",
                "telemetry_before": sorted(before)}
    report = _load_json(prev) if prev.exists() else None
    refusal_path = run_dir / REFUSAL_FILE
    if proc.returncode == 2 and refusal_path.exists():
        data = _load_json(refusal_path)
        return {
            "status": RUN_REFUSED_STATUS,
            "returncode": proc.returncode,
            "error": data.get("reason") or (proc.stderr or "").strip()[-2000:],
            "report": report,
            "telemetry_new": [],
            "telemetry_before": sorted(before),
            "refused": True,
        }
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
    """Directory a fresh measurement is written to (never an existing one).

    ``attempt_dirs`` deliberately ignores a directory that holds only a
    ``spec.json`` -- it never ran, so it is not an attempt and must not be
    counted. The *slot number* it occupies is still taken, though: skipping it
    made this function hand back ``attempt_01`` and overwrite the spec that was
    already there (audit C-08). Occupancy is therefore read from every existing
    attempt directory, counted or not.
    """
    slot = _run_slot_dir(exp_dir, run_index)
    taken = [int(d.name.rsplit("_", 1)[1])
             for d in slot.glob(ATTEMPT_DIR_GLOB) if d.is_dir()] if slot.is_dir() else []
    next_attempt = (max(taken) + 1) if taken else 1
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
    if dry_run:
        # A dry run must leave no trace of a measurement: no attempt directory,
        # no spec, no run slot. But it *must* rehearse the real thing: the spec a
        # paid run would receive, the real graph, the real switch consumption
        # and the effective-config record. A rehearsal that only counts loop
        # iterations proves nothing (limitation 1 in the preflight report).
        spec = build_run_spec(exp_dir, experiment, case, run_index, 1)
        rehearsal = rehearse_run_spec(spec)
        runner_result = {"status": "dry_run", "returncode": 0,
                         "error": None, "report": None}
        run_dir = None
    else:
        rehearsal = None
        run_dir = Path(run_dir) if run_dir is not None else _run_slot_dir(exp_dir, run_index)
        attempt = (int(run_dir.name.rsplit("_", 1)[1])
                   if run_dir.name.startswith("attempt_") else 1)
        spec_path = prepare_run_spec(exp_dir, experiment, case, run_index, attempt)
        runner = runner or _default_runner
        runner_result = runner(spec_path, exp_dir, run_index, attempt)

    report = runner_result.get("report") or {}
    status = runner_result.get("status")
    if status == RUN_REFUSED_STATUS:
        # The child refused before doing any work. Surface it as an exception
        # so the orchestrator can keep it out of the attempt sequence.
        raise RunRefused(runner_result.get("error") or "run refused")
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
            # The rehearsal's evidence: which switches the *real* graph consumed
            # and the verified effective-config digest. A dry run that cannot
            # produce these did not rehearse a paid run.
            "rehearsal": rehearsal,
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
        telemetry_path = _select_run_telemetry(runtime_dir, set(before), reported,
                                               reported_base=exp_dir)
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
    # The budget contract is interpreted once, from the run's own registration,
    # so an unreadable/malformed block is reported as such instead of silently
    # becoming an uncapped run (U-2). A registration of the frozen batch must
    # state the contract; a generic experiment that never uses the spend gate
    # (no ``budget`` block) keeps the pre-existing behaviour and is not
    # invalidated for lacking a field it never had.
    budget_state, budget_cap = _budget_for_run(exp_dir, experiment)
    if copied_path is not None:
        payload = _load_json(copied_path)
        metrics = extract_run_metrics(payload, telemetry_path, run_index,
                                      base_dir=exp_dir,
                                      max_total_tokens=budget_cap,
                                      budget_state=budget_state)
        metrics["telemetry_path"] = _portable_path(copied_path, exp_dir)
        if runner_error:
            # Keep the diagnostic, but do not let it erase recorded metrics.
            metrics["runner_error"] = runner_error
    else:
        metrics = extract_run_metrics({}, None, run_index,
                                      max_total_tokens=budget_cap,
                                      budget_state=budget_state)
        metrics["run_status"] = "failed"
        metrics["valid"] = False
        metrics["error"] = runner_error

    # A budget contract that cannot be interpreted makes the run unclassifiable:
    # the cap is unknown, so neither "within budget" nor "uncapped" can be
    # claimed. Fail closed rather than treating it as an uncapped run (U-2).
    # V3 memory isolation evidence, written by the child next to its spec.
    # A run that declares the contract but produces no evidence is not a
    # sample: without the file, a modified baseline would be undetectable, so
    # absence is an invalidity, not a pass (audit A/C M1).
    memory_state = {}
    if run_dir is not None and (run_dir / MEMORY_STATE_FILE).is_file():
        memory_state = _load_json(run_dir / MEMORY_STATE_FILE)
        metrics["memory"] = memory_state
        if not memory_state.get("baseline_unchanged", True):
            metrics["invalid_reason"] = (metrics.get("invalid_reason")
                                         or INVALID_MEMORY_BASELINE_MODIFIED)
            metrics["valid"] = False
    _run_spec = {}
    if run_dir is not None and (run_dir / "spec.json").is_file():
        _run_spec = _load_json(run_dir / "spec.json")
    if isinstance(_run_spec, dict) and _run_spec.get("memory") and not memory_state:
        metrics["invalid_reason"] = (metrics.get("invalid_reason")
                                     or INVALID_MEMORY_STATE_MISSING)
        metrics["valid"] = False
    if budget_state is not None and not budget_state["ok"]:
        metrics["invalid_reason"] = metrics.get("invalid_reason") or INVALID_BUDGET_CONFIG
        metrics["valid"] = False
        metrics["budget_error"] = {
            "state": budget_state["state"],
            "detail": budget_state["detail"],
            "source": budget_state["source"],
        }

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
        "memory": memory_state,
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
    exp_dir = run_dir.parent.parent.parent
    budget_state, budget_cap = _budget_for_run(exp_dir)
    metrics = extract_run_metrics(_load_json(tele_path), tele_path, run_index,
                                   base_dir=exp_dir,
                                   max_total_tokens=budget_cap,
                                   budget_state=budget_state)
    if budget_state is not None and not budget_state["ok"]:
        # A stored attempt whose registration has no usable budget contract is
        # not a sample, exactly as on the run path (fail closed, not UNCAPPED).
        metrics["invalid_reason"] = metrics.get("invalid_reason") or INVALID_BUDGET_CONFIG
        metrics["valid"] = False
        metrics["budget_error"] = {
            "state": budget_state["state"],
            "detail": budget_state["detail"],
            "source": budget_state["source"],
        }
    metrics["attempt"] = run_dir.name
    metrics["telemetry_path"] = _portable_path(
        tele_path, run_dir.parent.parent.parent)
    memory_path = run_dir / MEMORY_STATE_FILE
    spec_path = run_dir / "spec.json"
    run_spec = _load_json(spec_path) if spec_path.is_file() else {}
    memory_state = {}
    if memory_path.is_file():
        memory_state = _load_json(memory_path)
        metrics["memory"] = memory_state
        if not memory_state.get("baseline_unchanged", True):
            metrics["invalid_reason"] = (metrics.get("invalid_reason")
                                         or INVALID_MEMORY_BASELINE_MODIFIED)
            metrics["valid"] = False
    if isinstance(run_spec, dict) and run_spec.get("memory") and not memory_state:
        metrics["invalid_reason"] = (metrics.get("invalid_reason")
                                     or INVALID_MEMORY_STATE_MISSING)
        metrics["valid"] = False
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


def _preflight_registration(exp_dir: Path, experiment: dict, case: dict) -> None:
    """Refuse an invalid registration before any attempt directory exists.

    Checks everything the child would check, plus the registration-level facts
    only the parent knows (the experiment must declare switches, and the
    declared hash must equal the hash of the definition as it stands now).
    """
    from tradingagents.graph.switch_verification import (
        SwitchNotConsumed,
        validate_spec_switches,
    )

    switches = experiment.get("switches")
    if switches is None:
        # A study that registers the switch apparatus must say which arm it
        # runs; a study that never opted in (older benchmark templates) has no
        # arm to be consistent with, so there is nothing to refuse.
        if experiment.get("switches_required"):
            raise RunRefused(
                f"{getattr(exp_dir, 'name', exp_dir)}: registration requires "
                f"switches but declares none; a run without an arm cannot be a "
                f"sample"
            )
    else:
        try:
            validate_spec_switches(switches)
        except SwitchNotConsumed as exc:
            raise RunRefused(f"registration switches rejected: {exc}") from None
        # The arm must equal the one SWITCH_MATRIX.csv froze for this Run ID.
        # Recomputing ``config_sha256`` below only proves the definition agrees
        # with *itself*: audit B-10 showed that editing the switches and
        # rehashing produces a self-consistent file that runs another arm. The
        # matrix is tracked and covered by the freeze fingerprint.
        # Only a registration that lives in the frozen batch is one of *this
        # study's* arms. Applying the matrix to every experiment that happens
        # to declare switches would make the rule about the field rather than
        # about the study, and would refuse legitimate non-batch experiments
        # (and the wrapper's own sandbox) for carrying a Run ID they never
        # claimed.
        in_batch = _is_frozen_batch_registration(exp_dir)
        run_id = getattr(exp_dir, "name", "").split("_", 1)[0]
        frozen = _frozen_switch_matrix().get(run_id) if in_batch else None
        if in_batch and frozen is None:
            raise RunRefused(
                f"{getattr(exp_dir, 'name', exp_dir)}: Run ID {run_id!r} is not "
                f"in SWITCH_MATRIX.csv; an unregistered arm cannot be a sample"
            )
        # The Run ID must name *this* directory, not merely borrow its prefix.
        # A copy of ``R01_NVDA_C0`` placed in another experiment directory
        # carries the right name, the right switches and a matching hash, and
        # would otherwise be measured as a second, independent R01 -- doubling
        # one arm's weight and silently corrupting the 4x4 comparison (audit
        # B-06). The registration is only reachable from its frozen home.
        expected_dir = (_frozen_batch_dir() / "specs" / f"{run_id}_"
                        f"{_frozen_run_ticker(run_id)}_"
                        f"{_frozen_run_arm(run_id)}")
        if in_batch and Path(exp_dir).resolve() != expected_dir.resolve():
            raise RunRefused(
                f"{exp_dir}: carries Run ID {run_id} but is not that run's "
                f"registered directory ({expected_dir}); a Run ID names exactly "
                f"one run, and a copy elsewhere would be counted twice"
            )
        if in_batch and switches != frozen:
            raise RunRefused(
                f"{getattr(exp_dir, 'name', exp_dir)}: SWITCH_MATRIX.csv froze "
                f"{frozen} for {run_id}, but the registration declares {switches}"
            )

    declared = experiment.get("config_sha256")
    if declared is not None:
        try:
            actual = registration_sha256(experiment)
        except KeyError as exc:
            raise RunRefused(f"registration is missing hashed fields: {exc}") from None
        if actual != declared:
            raise RunRefused(
                f"registration config_sha256 mismatch: declares "
                f"{declared[:12]}…, hashes to {actual[:12]}…"
            )

    # U-2: a registration of *this* study must state a budget contract that can
    # be interpreted before any attempt directory exists. An absent block is a
    # refusal here, not an implicit "uncapped".
    if _is_frozen_batch_registration(exp_dir):
        require_budget_state(
            experiment, source=str(Path(exp_dir) / EXPERIMENT_FILE))
        # V3: a registration of this protocol that declares no memory snapshot
        # is refused before any attempt directory exists. V2 registrations stay
        # runnable (they predate the isolation contract).
        if (_requires_memory_isolation(experiment)
                or _batch_requires_memory_isolation(exp_dir)):
            block = memory_block_for_registration(exp_dir, experiment)
            if block is None:
                raise RunRefused(
                    "registration declares no memory snapshot; a V3 run must "
                    "start from one immutable snapshot")


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


def _discard_refused_attempt(exp_dir: Path, run_index: int, attempt: int) -> None:
    """Remove the directory of an attempt that was refused before it ran.

    Only the run-state marker and the spec the parent itself wrote may exist;
    if telemetry appeared the run did start and the directory is kept, so this
    can never delete evidence.
    """
    import shutil

    run_dir = _attempt_dir(exp_dir, run_index, attempt)
    if not run_dir.is_dir():
        return
    produced = [
        p for p in run_dir.rglob("*")
        if p.is_file() and p.name not in {"run_state.json", "spec.json",
                                         REFUSAL_FILE}
    ]
    if produced:
        return
    shutil.rmtree(run_dir, ignore_errors=True)


def _record_refusal(exp_dir: Path, case: dict, run_index: int, exc: Exception) -> Path:
    """Append a refusal to the study's own log, outside the attempt sequence."""
    log = Path(exp_dir) / "refusals.jsonl"
    entry = {
        "run_index": run_index,
        "ticker": case.get("ticker"),
        "trade_date": case.get("trade_date"),
        "case_id": case.get("case_id"),
        "reason": f"{type(exc).__name__}: {exc}",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return log


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
    # Audit A-00: the *parent* imports ``tradingagents`` too (budget gate, switch
    # verification). If the shared editable install wins, the parent would apply
    # one tree's rules and the child another. Refuse before touching anything.
    verify_import_root(_PROJECT_ROOT)
    # Every case is pre-flighted before any state is persisted. A spec the
    # harness refuses must not rewrite ``code_state.json``: the file records
    # *the code the study ran under*, and a run that never started did not run
    # under anything. Writing it first left a refusal looking like the start
    # of a measurement.
    for case in experiment["cases"]:
        _preflight_registration(exp_dir, experiment, case)
    if dry_run:
        # Compute the fingerprint without persisting it: a dry run must not
        # rewrite the study's recorded code state, or the pre-registration and
        # the on-disk state stop agreeing after a mere rehearsal.
        code_state = compute_code_state(exp_dir, experiment)
    else:
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
            # Refusals are decided *before* an attempt is numbered. Doing it
            # (as the child also does) in the parent means a refused run
            # leaves no attempt directory and cannot consume attempt_01.
            #
            # This runs for dry runs too. A rehearsal used to skip it, so
            # ``--dry-run`` happily accepted a spec with ``s2_downstream:
            # false`` -- a switch with no OFF implementation -- and reported
            # "would run". A rehearsal that cannot fail is not a rehearsal.
            # Only the *numbering* and the recorded start are withheld, since
            # a dry run must leave no trace.
            _preflight_registration(exp_dir, experiment, case)
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
            except RunRefused as exc:
                # A refusal means the run never started: there is no attempt to
                # number and no sample to lose. It is recorded under its own
                # log and the study stops, because a spec that the harness
                # now refuses must be fixed rather than skipped.
                if attempt is not None:
                    # The parent numbered this attempt before the child looked
                    # at the spec. Un-number it, so the next real run reuses
                    # attempt_01 and the study shows no phantom attempt.
                    _discard_refused_attempt(exp_dir, run_index, attempt)
                # A rehearsal leaves no trace, including no refusal log: nothing
                # was attempted, and a refusal artefact would make the study
                # look like it had a run that never happened.
                if not dry_run:
                    _record_refusal(exp_dir, case, run_index, exc)
                raise
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
def _apply_spec_switches(spec: dict, config: dict, defaults: dict,
                         explicitly_exported: frozenset[str] = frozenset()) -> dict:
    """Apply a spec's declared switches to ``config``; return what was applied.

    The spec is authoritative. A spec that omits ``switches`` entirely (every
    pre-V2 spec, and any spec produced outside the V2 generator) is left on the
    ``default_config`` behaviour, which is exactly what the shipped harness did
    before this function existed — no unrelated artefact starts failing.

    A spec that *does* declare switches must declare all of them, must use real
    booleans, and must not contradict an explicitly exported ``TRADINGAGENTS_*``
    variable: that combination means two records disagree about what the arm is,
    and silently preferring one of them is how a label goes wrong.
    """
    declared = spec.get("switches")
    if declared is None:
        return {}
    # Imported here rather than at module import time: this module stays
    # import-light so ``validate``/``summarize``/``compare`` never need the
    # business imports (same convention as ``_run_single``).
    from tradingagents.graph.switch_verification import (
        SWITCH_CONFIG_KEYS,
        SwitchNotConsumed,
        validate_spec_switches,
    )

    validate_spec_switches(declared)

    for name, key in SWITCH_CONFIG_KEYS.items():
        if key is None:
            continue          # declared-only switch (s2_downstream)
        wanted = declared[name]
        # ``defaults`` already has the env overrides applied; if the caller
        # exported an *explicit* different value, refusing is the only safe
        # outcome. An unset variable is not a contradiction: it just means the
        # environment has no opinion, and the spec fills the gap (that is the
        # normal case -- the harness launches every run with a neutral env).
        if key in explicitly_exported:
            ambient = defaults.get(key)
            if isinstance(ambient, bool) and ambient is not wanted:
                raise SwitchNotConsumed(
                    f"spec declares {name}={wanted} but the environment "
                    f"exported {key}={ambient}; refusing to run an ambiguous arm"
                )
        config[key] = wanted
    return {key: config[key] for key in SWITCH_CONFIG_KEYS.values() if key}


def _child_env_for_spec(spec: dict) -> dict:
    """Environment for one measured child process.

    Two things the child cannot recover on its own:

    * the study's switches. They are also applied from the spec inside
      ``_run_single``, but exporting them means a crash report, a stack trace
      and any ``get_config()`` dump taken from the child all agree with the arm.
    * the harness's optional-credential passthrough. ``_PASSTHROUGH_ENV`` is
      already applied to ``os.environ`` by ``apply_cityu_env`` at launch; the
      copy here makes that explicit and keeps the child from inheriting
      unrelated shell state silently.
    """
    env = dict(os.environ)
    # The frozen-release check's test seam must not travel to a paid child
    # (audit A round 5, R-5-C). Inheriting it from an operator's shell would
    # silently disable the one control that decides whether money is spent,
    # which is a hole rather than a seam. A test that needs it must ask for it
    # explicitly on this second, separately-named variable -- and that request
    # is refused outright once the spec is a registration of the frozen batch
    # (see ``verify_frozen_tree``), so it cannot reach a real paid run.
    if env.pop("TRADINGAGENTS_ALLOW_SKIP_FREEZE_CHECK_IN_CHILD", None) != "1":
        env.pop("TRADINGAGENTS_SKIP_FREEZE_CHECK", None)
    switches = spec.get("switches") or {}
    for name, env_var in SPEC_SWITCH_ENV:
        if name in switches:
            value = switches[name]
            env[env_var] = "true" if value is True else "false"

    # Audit A-00: the shared ``.venv`` installs ``tradingagents`` as an editable
    # package pointing at the *main* checkout. A child launched elsewhere (or by
    # a shell wrapper that changes directory) therefore imported a different
    # tree than the one the spec was registered against -- silently, because the
    # import succeeds. Pinning the experiment root on ``PYTHONPATH`` makes the
    # import follow the spec, and ``PYTHONSAFEPATH`` stops the interpreter from
    # re-ordering the script directory ahead of it. The child still verifies
    # with ``verify_import_root``; this is the mechanism that makes the
    # verification pass for the intended tree instead of failing for a tree the
    # operator never chose.
    experiment_root = spec.get("experiment_root")
    if experiment_root:
        existing = env.get("PYTHONPATH")
        parts = [str(experiment_root)]
        if existing:
            parts.extend(p for p in existing.split(os.pathsep) if p)
        env["PYTHONPATH"] = os.pathsep.join(parts)
        env["PYTHONSAFEPATH"] = "1"
    return env


def _exported_switch_keys() -> set[str]:
    """Config keys whose value came from a *non-empty* ``TRADINGAGENTS_*`` var.

    ``DEFAULT_CONFIG`` is built once at import time, so it already carries the
    env overrides; the only way to tell an explicit export from a default is to
    look at the environment itself.
    """
    from tradingagents.default_config import _ENV_OVERRIDES

    return {
        key for env_var, key in _ENV_OVERRIDES.items()
        if os.environ.get(env_var)
    }


EFFECTIVE_CONFIG_FILE = "effective_config.json"

#: The fields ``config_sha256`` covers. This mirrors
#: ``gen_cand01_batch_16run_specs_v2.HASHED_FIELDS`` and lives here so the run
#: path can *recompute* a registration's hash without importing the generator.
#: A test asserts the two tuples are identical.
#: Fields a run spec must carry to be a sample at all. These are the frozen
#: definition: a spec that omits one is not "an experiment at its defaults", it
#: is a spec that cannot prove which arm it runs (audit A round 4, H-B).
_SPEC_REQUIRED_FIELDS = (
    "config_sha256", "switches", "news_scope", "provider", "quick_model",
    "deep_model", "output_language", "cache_policy", "case",
)

#: Spec fields that legitimately differ from the registration: they describe
#: *this* invocation rather than the study, or they are the spec's own path.
_SPEC_VOLATILE_FIELDS = frozenset({
    "results_dir", "registration_dir", "_spec_path", "run_index", "attempt",
    "schema_version",  # the spec body is hashed without it in some formats
})

REGISTERED_HASH_FIELDS = (
    "experiment_id",
    "schema_version",
    "switches_required",
    "provider",
    "quick_model",
    "deep_model",
    "output_language",
    "cache_policy",
    "checkpoint_enabled",
    "budget",
    # V3 adds the memory-isolation contract to the hashed definition. It is
    # conditionally hashed (see ``registration_sha256``) so a V2 registration,
    # which predates the field, still recomputes to its original value.
    "memory",
    "cases",
    "switches",
    "news_scope",
)


def canonical_json(obj) -> str:
    """The canonical serialisation used for every experiment hash."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def registration_sha256(definition: dict) -> str:
    """Recompute the ``config_sha256`` a definition should carry.

    Raises ``KeyError`` if a hashed field is missing, so a truncated definition
    fails loudly instead of hashing a smaller object and matching by accident.

    ``memory`` is hashed only when the definition declares it: V2 registrations
    predate the memory contract, and their recorded hashes must keep
    recomputing to the same value.
    """
    required = [field for field in REGISTERED_HASH_FIELDS
                if field != "memory" or "memory" in definition]
    unknown = set(required) - set(definition)
    if unknown:
        raise KeyError(f"missing hashed field(s): {sorted(unknown)}")
    subset = {key: definition[key] for key in required}
    return hashlib.sha256(canonical_json(subset).encode("utf-8")).hexdigest()


#: Marker file a child writes when it refuses to run, and the status string the
#: orchestrator maps it to. A refusal is not a measurement: it never produces
#: telemetry and must never be counted as an attempt of the study.
REFUSAL_FILE = "refusal.json"
RUN_REFUSED_STATUS = "refused"


class RunRefused(RuntimeError):
    """Raised when a spec is refused before any paid call is made."""


#: Keys of the resolved config withheld from ``effective_config.json``. Secrets
#: by name; the value is replaced with a boolean "is set" flag, never printed.
_SECRET_CONFIG_KEYS = frozenset({
    "api_key", "openai_api_key", "anthropic_api_key", "google_api_key",
    "backend_url_secret",
})


def imported_module_path() -> str:
    """Absolute path of the ``tradingagents`` package this interpreter imported."""
    import tradingagents as _ta

    return str(Path(_ta.__file__).resolve())


def verify_import_root(expected_root: str | os.PathLike) -> None:
    """Refuse to run if ``tradingagents`` was imported from outside ``expected_root``.

    A shared editable install resolves the package from whichever checkout was
    installed, not from the worktree the operator believes they are in. Running
    a paid experiment against the wrong tree silently mixes code versions, so
    this is a hard failure rather than a warning.
    """
    root = Path(expected_root).resolve()
    actual = Path(imported_module_path())
    try:
        actual.relative_to(root)
    except ValueError:
        raise RuntimeError(
            f"tradingagents imported from {actual}, which is outside the "
            f"expected experiment root {root}; refusing to run"
        ) from None


def build_effective_config(*, config: dict, spec: dict, graph,
                           applied_switches: dict) -> dict:
    """The resolved configuration this process is really running with.

    Distinct from ``spec.json`` (what was requested) and from the summary (what
    happened): this is the state between the two, built before the paid call so
    a crash cannot lose it, and *verified* against the spec before the call so a
    misapplied switch cannot spend money first (audit B-23 + round 5).
    """
    from tradingagents.graph.switch_verification import (
        consume_switches_from_setup,
    )

    observed_switches = {}
    try:
        observed_switches = consume_switches_from_setup(graph.graph_setup)
    except Exception as exc:  # noqa: BLE001 - a broken probe must be visible
        observed_switches = {"_probe_error": f"{type(exc).__name__}: {exc}"}

    def _safe(value):
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return repr(value)

    resolved = {}
    for key in sorted(config):
        if key in _SECRET_CONFIG_KEYS:
            resolved[key] = {"redacted": True, "is_set": bool(config[key])}
        else:
            resolved[key] = _safe(config[key])

    return {
        # The identifiers a third party needs to prove *which* registered
        # experiment and *which* code produced this run (audit B round 5,
        # B-23). Without them the only link back to the release was the raw
        # spec file, whose hash was recomputable but never recorded here.
        "experiment_id": spec.get("experiment_id"),
        "config_sha256": spec.get("config_sha256"),
        # The spec body as it actually is, hashed here rather than copied: the
        # run spec carries no such field, and a recorded ``null`` would prove
        # nothing. ``spec_body_sha256()`` is the same function the delivered
        # MANIFEST uses, so this value can be matched against the release.
        "spec_body_sha256": spec_body_sha256(spec),
        "spec_switches": spec.get("switches"),
        "switches_applied_to_config": applied_switches,
        "switches_observed_from_graph_setup": observed_switches,
        "provider": spec.get("provider"),
        "quick_model": spec.get("quick_model"),
        "deep_model": spec.get("deep_model"),
        "resolved_config": resolved,
        "import_provenance": {
            "tradingagents_module": imported_module_path(),
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "cwd": os.getcwd(),
        },
    }


def verify_effective_config(payload: dict, spec: dict, *,
                            expected_root: str | os.PathLike | None = None) -> dict:
    """Check an ``effective_config`` record against the spec that produced it.

    This is the *consumer* of the artefact: writing a file nobody validates is
    how a record drifts from reality. It refuses when the recorded definition,
    the applied switches or the imported module disagree with the spec, and it
    treats a probe error as a failure rather than a note (the whole point is
    what the graph actually consumed).
    """
    problems: list[str] = []
    if payload.get("experiment_id") != spec.get("experiment_id"):
        problems.append(
            f"experiment_id {payload.get('experiment_id')!r} != "
            f"{spec.get('experiment_id')!r}")
    if payload.get("config_sha256") != spec.get("config_sha256"):
        problems.append("config_sha256 does not match the spec")
    if payload.get("spec_body_sha256") != spec_body_sha256(spec):
        problems.append("spec_body_sha256 does not match the spec body")
    if payload.get("spec_switches") != spec.get("switches"):
        problems.append("spec_switches do not match the spec")
    if payload.get("provider") != spec.get("provider"):
        problems.append("provider does not match the spec")
    if payload.get("quick_model") != spec.get("quick_model"):
        problems.append("quick_model does not match the spec")
    if payload.get("deep_model") != spec.get("deep_model"):
        problems.append("deep_model does not match the spec")

    observed = payload.get("switches_observed_from_graph_setup") or {}
    if "_probe_error" in observed:
        problems.append(f"the switch probe failed: {observed['_probe_error']}")
    elif spec.get("switches"):
        # ``consume_switches_from_setup`` reports what each analyst factory was
        # given, not a flat switch dict; ``verify_switches_consumed`` is the
        # function that knows how to compare the two. Re-implementing the
        # comparison here would drift from it.
        from tradingagents.graph.switch_verification import verify_switches_consumed

        try:
            verify_switches_consumed(spec["switches"], observed=observed)
        except Exception as exc:  # noqa: BLE001 - any disagreement is a failure
            problems.append(
                f"the graph consumed {observed}, which does not match the "
                f"spec's {spec['switches']}: {exc}")

    module = (payload.get("import_provenance") or {}).get("tradingagents_module")
    if expected_root is not None and module:
        try:
            Path(module).resolve().relative_to(Path(expected_root).resolve())
        except ValueError:
            problems.append(
                f"tradingagents was imported from {module}, outside "
                f"{expected_root}")

    if problems:
        raise RuntimeError(
            "effective_config verification failed: " + "; ".join(problems))
    return {"verified": True, "checks": 8}


def _write_effective_config(run_dir: Path, *, config: dict, spec: dict,
                            graph, applied_switches: dict) -> Path:
    """Build, verify and write ``effective_config.json`` for one run."""
    payload = build_effective_config(
        config=config, spec=spec, graph=graph, applied_switches=applied_switches)
    verify_effective_config(payload, spec,
                            expected_root=spec.get("experiment_root"))
    path = Path(run_dir) / EFFECTIVE_CONFIG_FILE
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def _registration_dir_for(spec: dict) -> Path | None:
    """Locate the per-run registration a spec belongs to.

    ``prepare_run_spec`` records the experiment directory in the spec, and the
    registration file lives there. The declared ``experiment_id`` must match, so
    a spec cannot borrow another run's registration.
    """
    raw = spec.get("registration_dir")
    if not raw:
        return None
    path = Path(raw) / "experiment.json"
    if not path.is_file():
        return None
    try:
        registered_id = _load_json(path).get("experiment_id")
    except Exception:  # noqa: BLE001 - a broken registration is not usable
        return None
    if registered_id != spec.get("experiment_id"):
        return None
    return path


#: Active batch under test. V2 stays the default so historical commands are
#: unchanged; a re-registered version selects its own directory explicitly.
DEFAULT_BATCH_REL = "token_benchmarks/live_pilot_2x2/cand01_batch_16run_v2"


def _frozen_batch_rel() -> str:
    value = str(os.environ.get("TRADINGAGENTS_C3_BATCH") or DEFAULT_BATCH_REL)
    # An absolute override (used by tests and by an out-of-tree registration)
    # must stay absolute; a repo-relative one is normalised.
    return value if os.path.isabs(value) else value.strip("/")


def _freeze_tag() -> str:
    return os.environ.get("C3_FREEZE_TAG") or "c3-final-freeze"


def _freeze_protocol_name() -> str:
    return os.environ.get("C3_PROTOCOL_NAME") or "CAND01_BATCH_2X2_PROTOCOL_V2.md"


def _freeze_generator_rel() -> str:
    return os.environ.get("C3_GENERATOR") or "scripts/gen_cand01_batch_16run_specs_v2.py"


def _frozen_batch_dir() -> Path:
    """The registered batch directory that owns the Run IDs."""
    return Path(__file__).resolve().parent.parent / _frozen_batch_rel()


def _frozen_run_ticker(run_id: str) -> str:
    return _frozen_switch_matrix_rows().get(run_id, {}).get("ticker", "")


def _frozen_run_arm(run_id: str) -> str:
    return _frozen_switch_matrix_rows().get(run_id, {}).get("arm", "")


def _frozen_switch_matrix_rows() -> dict[str, dict]:
    """Every ``SWITCH_MATRIX.csv`` row, as strings, keyed by Run ID."""
    import csv

    path = _frozen_batch_dir() / "SWITCH_MATRIX.csv"
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as fh:
        return {(row.get("run_id") or "").strip(): row
                for row in csv.DictReader(fh) if (row.get("run_id") or "").strip()}


def _spec_belongs_to_frozen_batch(spec: dict) -> bool:
    """Does this spec claim to be one of the 16 registered runs?

    Two independent signals, and either is enough: the ``registration_dir`` the
    spec names, and the location of the spec file itself. Using only the first
    would let a spec *delete* the field to escape the strict field set that
    audit H-B required.
    """
    registration = _registration_dir_for(spec)
    if registration is not None and _is_frozen_batch_registration(
            Path(registration).parent):
        return True
    raw = spec.get("_spec_path")
    if raw:
        try:
            Path(raw).resolve().relative_to((_frozen_batch_dir() / "specs").resolve())
            return True
        except (ValueError, OSError):
            pass
    return False


def _run_id_for_spec(spec: dict) -> str | None:
    """The Run ID a spec belongs to: its registration directory's name prefix.

    ``R01_NVDA_C0`` -> ``R01``. The name is the only place a Run ID appears;
    the spec body carries a case and an index, not the study's identifier.
    """
    registration = _registration_dir_for(spec)
    if registration is None:
        return None
    return Path(registration).parent.name.split("_", 1)[0] or None


def _frozen_switch_matrix() -> dict[str, dict]:
    """``{run_id: switches}`` from the tracked ``SWITCH_MATRIX.csv``.

    Written when the batch was registered (``b00dd00``) and covered by the
    tracked tree the freeze fingerprint hashes. It is the authority for *which
    arm a Run ID runs*; the per-run ``experiment.json`` is only a restatement,
    and a restatement that agrees with itself proves nothing (audit B-10).
    """
    rows = _frozen_switch_matrix_rows()
    out: dict[str, dict] = {}
    for run_id, row in rows.items():
        if True:
            out[run_id] = {
                key: (row.get(key) or "").strip().lower() in {"true", "1", "yes"}
                for key in ("batch_macro", "single_pass", "structured", "s2_downstream")
            }
    return out


def _preflight_gate(spec: dict, *, memory_attempt_dir: Path | None = None) -> dict:
    """Refuse a spec that cannot be a valid sample, before any paid call.

    Every condition here is one the study registered and a run must satisfy:
    a declared ``s2_downstream`` that is False (unimplemented, per C2's
    contract), a news scope other than the frozen Finnhub-only one, and a
    switch set that contradicts an explicitly exported environment. Raising
    ``RunRefused`` keeps these distinguishable from a run that started and
    failed, which is a different -- and countable -- kind of evidence.
    """
    from tradingagents.graph.switch_verification import (
        SwitchNotConsumed,
        validate_spec_switches,
    )

    # A spec must prove it is the registration for its run: the recorded hash
    # is *recomputed* from the hashed fields and compared. Merely carrying a
    # ``config_sha256`` string proves nothing -- audit B2 demonstrated a spec
    # with ``"0"*64`` running happily.
    #
    # Every guard below used to be conditional (``if ... is not None``), so
    # *deleting* a field skipped its check entirely: a spec with no
    # ``switches`` was accepted and the graph then fell back to
    # ``DEFAULT_CONFIG``, running the AB arm while the spec called itself R01 /
    # C0 (audit A round 4, H-B). The fields the protocol freezes are now
    # mandatory, and each one must still agree with the registration -- the
    # hash vouches for the registration, not for the spec that points at it.
    # The mandatory-field set is the *registered batch's* contract. A generic
    # measurement (``token_benchmark.py measure`` on any experiment) never opted
    # into switches or a config hash, so requiring them there would refuse a
    # legitimate measurement rather than a malformed one. ``_spec_belongs_to_
    # frozen_batch`` also checks the spec's path, so deleting the field that
    # says "I am R01" cannot downgrade a registered run to a generic one.
    if _spec_belongs_to_frozen_batch(spec):
        missing_required = [key for key in _SPEC_REQUIRED_FIELDS if key not in spec]
        if missing_required:
            raise RunRefused(
                f"spec is missing required field(s) {missing_required}; omitting a "
                f"frozen field is not the same as leaving it at its default"
            )

    declared_hash = spec.get("config_sha256")
    if declared_hash is not None:
        # ``memory`` is hashed only when the definition declares it (V3); a V2
        # spec legitimately has no such field and must still self-hash.
        hash_fields = [field for field in REGISTERED_HASH_FIELDS
                       if field != "memory" or "memory" in spec]
        definition = {key: spec[key] for key in hash_fields if key in spec}
        missing = [key for key in hash_fields if key not in spec]
        if missing:
            # Fall back to the registration on disk: the run spec is a subset
            # of the definition, so it cannot hash itself.
            registration = _registration_dir_for(spec)
            if registration is None:
                raise RunRefused(
                    f"spec declares config_sha256 but carries no definition "
                    f"(missing {missing}) and no registration was found"
                )
            definition = _load_json(registration)
        # ``registration_sha256(definition)`` is independent of the spec, so on
        # its own it cannot notice that the spec file disagrees with the
        # registration it points at. Compare every field the two share.
        if isinstance(definition, dict):
            # ``memory`` is declared by the registration and *specialised* by
            # the attempt (run copy path/hash, pending counts). Compare only
            # the declared fields; the run-specific ones are validated by
            # ``validate_memory_spec`` against the snapshot itself.
            spec_view, definition_view = spec, definition
            if isinstance(spec.get("memory"), dict) and isinstance(definition.get("memory"), dict):
                declared = ("mode", "baseline_relpath", "baseline_sha256")
                spec_view = dict(spec, memory={k: spec["memory"].get(k) for k in declared})
                definition_view = dict(definition,
                                       memory={k: definition["memory"].get(k) for k in declared})
            disagreement = {
                key: (spec_view[key], definition_view[key])
                for key in set(spec_view) & set(definition_view)
                if key not in _SPEC_VOLATILE_FIELDS
                and spec_view[key] != definition_view[key]
            }
            if disagreement:
                raise RunRefused(
                    f"spec disagrees with its registration on {sorted(disagreement)}; "
                    f"the registration is the frozen definition and the spec may "
                    f"only repeat it"
                )
            # A run spec carries its case as ``case``; the registration lists
            # them as ``cases``, so the loop above never compares them and any
            # trade date, ticker or analyst set was accepted (audit A round 5,
            # H-C). That is the one substitution that silently changes *what*
            # is measured, so it is compared field by field.
            if "case" in spec and isinstance(definition.get("cases"), list):
                registered = [c for c in definition["cases"]
                              if isinstance(c, dict)
                              and c.get("case_id") == spec["case"].get("case_id")]
                if len(registered) != 1:
                    raise RunRefused(
                        f"spec case {spec['case'].get('case_id')!r} is not one of "
                        f"the registration's cases "
                        f"{[c.get('case_id') for c in definition['cases']]}"
                    )
                case_diff = {
                    key: (spec["case"].get(key), registered[0].get(key))
                    for key in set(spec["case"]) | set(registered[0])
                    if spec["case"].get(key) != registered[0].get(key)
                }
                if case_diff:
                    raise RunRefused(
                        f"spec case disagrees with its registration on "
                        f"{sorted(case_diff)}; the ticker, trade date and analyst "
                        f"set are the experiment, not parameters of it"
                    )
        actual = registration_sha256(definition)
        if actual != declared_hash:
            raise RunRefused(
                f"config_sha256 mismatch: spec declares {declared_hash[:12]}…, "
                f"registration hashes to {actual[:12]}…; the definition changed "
                f"after it was registered"
            )

    switches = spec.get("switches")
    if switches is not None:
        try:
            validate_spec_switches(switches)
        except SwitchNotConsumed as exc:
            raise RunRefused(f"spec switches rejected: {exc}") from None
        # The arm must be the one SWITCH_MATRIX.csv froze for this Run ID.
        # Recomputing ``config_sha256`` above proves the definition agrees with
        # itself and nothing more: audit B-10 showed that editing the switches
        # and rehashing yields a self-consistent file that runs another arm.
        # The matrix is tracked and covered by the freeze fingerprint.
        run_id = _run_id_for_spec(spec)
        frozen = _frozen_switch_matrix().get(run_id) if run_id else None
        if frozen is not None and switches != frozen:
            raise RunRefused(
                f"SWITCH_MATRIX.csv froze {frozen} for {run_id}, but the spec "
                f"declares {switches}"
            )
        # ...and the spec must come from that run's registered directory. A
        # copied experiment carries the same name, switches and hash; only the
        # path distinguishes a real sample from a duplicate (audit B-06).
        registration = _registration_dir_for(spec)
        if frozen is not None and registration is not None:
            expected = (_frozen_batch_dir() / "specs" / f"{run_id}_"
                        f"{_frozen_run_ticker(run_id)}_"
                        f"{_frozen_run_arm(run_id)}")
            actual = Path(registration).parent.resolve()
            if actual != expected.resolve():
                raise RunRefused(
                    f"spec for {run_id} was prepared from {actual}, not from "
                    f"that run's registered directory ({expected}); a Run ID "
                    f"names exactly one run"
                )
        # Mirror the ambient check ``_apply_spec_switches`` performs, but fail
        # here so the refusal happens before a graph is constructed.
        from tradingagents.default_config import DEFAULT_CONFIG
        from tradingagents.graph.switch_verification import SWITCH_CONFIG_KEYS

        for name, key in SWITCH_CONFIG_KEYS.items():
            if key is None:
                continue
            if key in _exported_switch_keys():
                ambient = DEFAULT_CONFIG.get(key)
                if isinstance(ambient, bool) and ambient is not switches[name]:
                    raise RunRefused(
                        f"spec declares {name}={switches[name]} but the "
                        f"environment exported {key}={ambient}"
                    )

    # V3: a run must prove it starts from the immutable snapshot in its own
    # copy. This is the last guard before the graph is constructed.
    registration_path = _registration_dir_for(spec)
    registration = None
    if registration_path is not None:
        try:
            registration = _load_json(registration_path)
        except Exception:  # noqa: BLE001 - unreadable registration is refused below
            registration = None
    if "memory" in spec:
        attempt_dir = memory_attempt_dir
        if attempt_dir is None and spec.get("_spec_path"):
            attempt_dir = Path(spec["_spec_path"]).parent
        validate_memory_spec(spec, attempt_dir=attempt_dir)
    elif (_requires_memory_isolation(registration)
          or (registration_path is not None
              and _batch_requires_memory_isolation(registration_path))):
        raise RunRefused(
            "spec carries no memory isolation block; a V3 run must start from "
            "its own copy of the immutable snapshot")

    scope = spec.get("news_scope")
    if scope is not None:
        # The frozen contract, as the V2 generator records it: company news is
        # Finnhub, global news is Finnhub with the feature explicitly disabled
        # (never silently routed elsewhere), and GDELT is excluded outright.
        if scope.get("company_news") != "finnhub":
            raise RunRefused(
                f"news_scope.company_news={scope.get('company_news')!r} is not "
                f"the frozen Finnhub-only scope"
            )
        if not str(scope.get("global_news", "")).startswith("finnhub"):
            raise RunRefused(
                f"news_scope.global_news={scope.get('global_news')!r} must be "
                f"the explicitly disabled Finnhub path"
            )
        if scope.get("gdelt") != "excluded":
            raise RunRefused(
                f"news_scope.gdelt={scope.get('gdelt')!r} must be 'excluded'"
            )
        forbidden = {"gdelt", "alpha_vantage", "yahoo"}
        for field, got in scope.items():
            if isinstance(got, str) and got.lower() in forbidden:
                raise RunRefused(
                    f"news scope field {field}={got!r} names a forbidden vendor"
                )
    # U-2: the spec's budget block must be interpretable. Reading it as a bare
    # ``.get("max_total_tokens")`` made null, absent and malformed identical,
    # so a broken registration would have run as if it were uncapped.
    if "budget" in spec:
        require_budget_state(
            spec, source=str(spec.get("registration_dir") or "<spec>"))
    elif _spec_belongs_to_frozen_batch(spec):
        raise RunRefused(
            "spec carries no budget block; a run of the frozen batch must state "
            "whether it is capped, and null is only 'uncapped' by declaration"
        )
    return {"checked": True}


def verify_frozen_tree(spec_path: str | Path | None = None) -> None:
    """Refuse to spend money on a tree that is not the frozen release.

    The freeze checks lived only in ``scripts/c3_preflight_gate.py``, which the
    operator runs as a separate step. Nothing on the spending path enforced
    them, so a run could start from any checkout; Audit A round 4 (H-A) reached
    ``propagate`` from a dirty tree that had never passed the gate. A separate
    gate that the paying process does not consult is advice, not a control.

    This is deliberately the same two facts the gate checks -- HEAD is the
    frozen commit, and the working tree hashes to the recorded fingerprint --
    recomputed here rather than delegated, so the child refuses on its own even
    when nobody ran the gate beforehand.
    """
    import os
    import subprocess

    # The only way past this is an explicit, test-scoped opt-out, and it
    # announces itself on every use so that it can never be set quietly
    # (audit B round 5, B-26: an undocumented escape hatch on the one check
    # that decides whether money is spent). The suite sets it only in tests
    # that run the child outside a frozen release, and the flag's presence is
    # itself asserted there.
    if os.environ.get("TRADINGAGENTS_SKIP_FREEZE_CHECK") == "1":
        # The seam exists for tests that exercise the child outside a frozen
        # release. It must never be usable for a run of *this* batch: a paid
        # result produced with the check disabled is not evidence from the
        # audited release, so it is refused rather than warned about (audit A
        # round 5, R-5-C: a warning is not a guard).
        if spec_path is not None and _is_frozen_batch_registration(
                Path(spec_path).parent):
            raise RunRefused(
                "TRADINGAGENTS_SKIP_FREEZE_CHECK=1 is set, but this is a run of "
                "the frozen batch: the frozen-release check cannot be disabled "
                "for a paid run, whatever the environment says"
            )
        print("WARNING: TRADINGAGENTS_SKIP_FREEZE_CHECK=1 -- the frozen-release "
              "check is DISABLED; any result from this process is not evidence "
              "from the audited release", file=sys.stderr)
        return

    batch = _frozen_batch_dir()
    frozen_file = batch / "c3" / "FROZEN_COMMIT"
    record_file = batch / "c3" / "code_freeze.txt"
    if not frozen_file.is_file():
        raise RunRefused(
            f"no frozen commit recorded at {frozen_file}; a paid run must be "
            f"evidence from a frozen release, not from whatever is checked out"
        )
    expected = frozen_file.read_text(encoding="utf-8").strip()
    if not expected:
        raise RunRefused(f"{frozen_file} is empty")
    head = subprocess.run(["git", "-C", str(_PROJECT_ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=False).stdout.strip()
    if head != expected:
        raise RunRefused(
            f"HEAD is {head[:12] or 'unknown'}, but the frozen commit is "
            f"{expected[:12]}; the code that would run is not the code that "
            f"was audited"
        )
    # ``FROZEN_COMMIT`` is untracked and therefore rewritable by the same act
    # that rewrites the record, which made the whole check circular: Audit A
    # round 5 (R-5-B) committed a tampered tree, re-ran the freeze writer, wrote
    # the new hash into ``FROZEN_COMMIT`` and both this function and the gate
    # passed. The designation is now an append-only history whose *first* entry
    # names the commit, and which later entries cannot retract.
    try:
        from c3_attest import check_head_is_designated
    except ImportError:  # imported as scripts.token_benchmark, not from scripts/
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "c3_attest", Path(__file__).resolve().parent / "c3_attest.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        check_head_is_designated = module.check_head_is_designated
    try:
        check_head_is_designated(head)
    except Exception as exc:  # noqa: BLE001 - any failure here means "refuse"
        raise RunRefused(str(exc)) from None
    dirty = subprocess.run(["git", "-C", str(_PROJECT_ROOT), "status",
                            "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, check=False).stdout.strip()
    if dirty:
        raise RunRefused(
            f"the tracked tree has uncommitted changes:\n{dirty}"
        )
    if not record_file.is_file():
        raise RunRefused(f"no freeze record at {record_file}")
    declared = None
    for line in record_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("working_tree_sha256") and "=" not in stripped:
            declared = stripped.split(":", 1)[-1].strip()
            break
    if not declared:
        raise RunRefused(f"{record_file.name} records no working_tree_sha256")
    everything = json.loads((batch / "experiment.json").read_text(encoding="utf-8"))
    actual = compute_code_state(batch, everything).get("working_tree_sha256")
    if actual != declared:
        raise RunRefused(
            f"this tree fingerprints to {actual[:16]}…, but the freeze record "
            f"declares {declared[:16]}…; the code is not the frozen release"
        )

    # The local checks above give the operator a precise message for the common
    # failures. The full certification -- tag, manifest, every spec hash, the
    # budget contract, the spec paths -- is one shared check so the gate and the
    # spending child cannot drift apart on what "frozen" means.
    try:
        from c3_verify_final_freeze import verify as _verify_final_freeze
    except ImportError:  # imported as scripts.token_benchmark, not from scripts/
        import importlib.util

        module_spec = importlib.util.spec_from_file_location(
            "c3_verify_final_freeze",
            Path(__file__).resolve().parent / "c3_verify_final_freeze.py")
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        _verify_final_freeze = module.verify
    result = _verify_final_freeze(
        _PROJECT_ROOT, batch_rel=_frozen_batch_rel(), tag=_freeze_tag())
    if not result["ok"]:
        raise RunRefused(
            "this tree is not the certified final freeze: "
            + "; ".join(result["failures"][:3])
            + (f" (+{len(result['failures']) - 3} more)" if len(result["failures"]) > 3 else "")
        )


def _config_for_spec(spec: dict) -> tuple[dict, dict]:
    """Resolve the process config for one run, applying the spec's switches."""
    from tradingagents.default_config import DEFAULT_CONFIG

    case = spec["case"]
    config = dict(DEFAULT_CONFIG)
    config["results_dir"] = spec.get("results_dir")
    # V3 memory isolation: the graph reads and writes this run's copy, never the
    # shared developer log. Set before construction so nothing can capture the
    # default path.
    memory = spec.get("memory") or {}
    if memory.get("run_memory_path"):
        config["memory_log_path"] = memory["run_memory_path"]
    config["llm_provider"] = spec.get("provider")
    config["quick_think_llm"] = spec.get("quick_model")
    config["deep_think_llm"] = spec.get("deep_model")
    config["max_debate_rounds"] = case.get("research_rounds")
    config["max_risk_discuss_rounds"] = case.get("risk_rounds")
    config["output_language"] = spec.get("output_language")
    # checkpoint disabled for benchmarks (each run is an independent sample).
    config["checkpoint_enabled"] = False

    # CAND-01 arms. The ablation switches reach the config through two paths —
    # the ambient ``TRADINGAGENTS_*`` vars (``default_config``) and the spec
    # itself. Only the spec path is self-describing: independent audit B1
    # measured that without it 12/16 specs run under a neutral environment with
    # switches that contradict their own arm label (every C0 and CC run, plus
    # every B run). The spec is the record of what was registered, so it wins;
    # the ambient value is only used as an *agreement* check, never a source.
    applied = _apply_spec_switches(
        spec, config, DEFAULT_CONFIG,
        explicitly_exported=frozenset(_exported_switch_keys()),
    )
    return config, applied


def _construct_graph(spec: dict, config: dict):
    """Construct exactly one graph for one run.

    Exactly one, because an earlier revision built a second graph purely to run
    the switch check and threw the first away, which doubled client construction
    and left two live handlers that could each record usage. The seam exists so
    an offline rehearsal can substitute a stub graph without changing the
    verification logic.
    """
    from cli.stats_handler import StatsCallbackHandler
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    handler = StatsCallbackHandler()
    return TradingAgentsGraph(
        selected_analysts=tuple(spec["case"].get("analysts") or ()),
        config=config,
        callbacks=[handler],
    )


def _verify_graph_consumed_switches(spec: dict, graph, applied: dict) -> dict:
    """Ask the constructed ``GraphSetup`` what it derived, and require the arm."""
    from tradingagents.graph.switch_verification import (
        consume_switches_from_setup,
        verify_switches_consumed,
    )

    observed = consume_switches_from_setup(graph.graph_setup)
    if applied:
        verify_switches_consumed(spec["switches"], observed=observed)
    return observed


def _guard_spending_path(spec: dict, spec_path: Path | None = None, *,
                         memory_attempt_dir: Path | None = None) -> None:
    """Everything that can disqualify a run, before a single paid call.

    Import provenance (A-00), the frozen-release check (H-A) and the spec-level
    refusals (s2, news scope, budget, arm) all live here so the rehearsal and
    the paid path cannot diverge.
    """
    verify_import_root(spec.get("experiment_root") or _PROJECT_ROOT)
    # The frozen-release check is a property of the registered batch: those are
    # the runs whose evidence must come from the audited release. A generic
    # measurement of another experiment does not claim to be that release (and
    # refusing it for lacking a release tag would make `measure` unusable
    # outside the study), but it still gets every other guard.
    if _spec_belongs_to_frozen_batch(spec):
        verify_frozen_tree(spec_path)
    _preflight_gate(spec, memory_attempt_dir=memory_attempt_dir)


def _rehearsal_spec_path(spec: dict, spec_path: Path | None) -> Path | None:
    """Where this spec *would* live, for the freeze seam's batch test.

    ``verify_frozen_tree`` decides whether ``TRADINGAGENTS_SKIP_FREEZE_CHECK``
    may disable the frozen-release check by looking at the spec's path. A
    rehearsal built in memory has no path, so passing ``None`` would let a
    batch rehearsal disable the check that a paid run may never disable. The
    registration directory is an equally good signal and cannot be omitted for
    a registered spec.
    """
    if spec_path is not None:
        return Path(spec_path)
    recorded = spec.get("_spec_path")
    if recorded:
        # A spec loaded by the child carries its own path; use it rather than
        # inventing one.
        return Path(recorded)
    registration = _registration_dir_for(spec)
    if registration is not None:
        return Path(registration).parent / "spec.json"
    return None


def rehearse_run_spec(spec: dict, *, spec_path: Path | None = None) -> dict:
    """Offline rehearsal of one paid run: everything except the LLM call.

    A rehearsal that cannot fail is not a rehearsal. This builds the *real*
    spec, resolves the *real* config, constructs the *real* graph and asserts
    that the graph consumed exactly the registered arm, then verifies the
    ``effective_config`` record that a paid run would write. No client is
    asked for a completion, no tool runs, and nothing is left on disk: the
    graph's own directories are redirected into a temporary sandbox that is
    removed afterwards (constructing the real graph creates
    ``results_dir``, ``data_cache_dir`` and the memory log's parent, and a
    rehearsal must not leave those behind).

    A V3 spec additionally rehearses the memory contract: its snapshot is
    re-hashed, a temporary per-run copy is made inside the sandbox, and the
    copy is proven byte-identical to the baseline before the graph is built.
    The sandbox copy is what the containment check sees, so a dry run leaves
    the certified tree untouched.
    """
    import shutil
    import tempfile

    sandbox = Path(tempfile.mkdtemp(prefix="c3-rehearsal-"))
    spec = dict(spec)
    memory = spec.get("memory")
    if isinstance(memory, dict) and memory.get("baseline_path"):
        memory_dir = sandbox / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        run_copy = memory_dir / MEMORY_FILE
        shutil.copyfile(memory["baseline_path"], run_copy)
        summary = memory_summary(run_copy)
        spec["memory"] = {
            **memory,
            "run_memory_path": str(run_copy),
            "run_initial_sha256": summary["sha256"],
            "pending_before": summary["pending_count"],
            "entry_count_before": summary["entry_count"],
        }
    _guard_spending_path(spec, _rehearsal_spec_path(spec, spec_path),
                         memory_attempt_dir=sandbox)
    config, applied = _config_for_spec(spec)
    if not (spec.get("provider") and spec.get("quick_model")
            and spec.get("deep_model")):
        # There is no provider/model to build a client from, so there is no
        # graph to interrogate. Everything that does not need one has already
        # run; say so instead of silently skipping the strongest check. A
        # *registered* spec cannot reach this branch: its required fields
        # include the provider and both models.
        return {
            "rehearsed": True,
            "graph_rehearsed": False,
            "reason": "spec declares no provider/models; no graph constructed",
            "switches_applied": applied,
            "switches_observed": None,
            "effective_config_verified": {"verified": False},
            "effective_config_sha256": None,
        }
    # The *rehearsal* runs against a scratch tree. A paid run keeps the spec's
    # own results_dir, which is what makes its telemetry land in the attempt.
    config["results_dir"] = str(sandbox / "results")
    config["data_cache_dir"] = str(sandbox / "cache")
    config["memory_log_path"] = str(sandbox / "memory" / "trading_memory.md")
    try:
        graph = _construct_graph(spec, config)
        observed = _verify_graph_consumed_switches(spec, graph, applied)
        record = build_effective_config(
            config=config, spec=spec, graph=graph, applied_switches=applied)
        verification = verify_effective_config(
            record, spec, expected_root=spec.get("experiment_root"))
    except Exception as exc:  # noqa: BLE001 - a rehearsal failure is a refusal
        raise RunRefused(
            f"offline rehearsal failed: {type(exc).__name__}: {exc}") from None
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    return {
        "rehearsed": True,
        "graph_rehearsed": True,
        "sandbox": "temporary (removed)",
        "switches_applied": applied,
        "switches_observed": observed,
        "effective_config_verified": verification,
        "effective_config_sha256": hashlib.sha256(
            canonical_json(record).encode("utf-8")).hexdigest(),
    }


def _run_single(spec_path: str) -> int:
    """Execute ONE measured TradingAgents run inside the current process.

    This is invoked by ``run`` in a fresh Python subprocess to isolate global
    state / ContextVars / callbacks between measured runs. Imports the real
    TradingAgents execution path here (lazily) so the orchestrator can stay
    lightweight and run validation/summarize/compare without business imports.
    """
    spec = _load_json(Path(spec_path))
    # Record where this spec came from: it is the second, independent signal of
    # whether the spec is a registered batch run (see
    # ``_spec_belongs_to_frozen_batch``).
    spec["_spec_path"] = str(Path(spec_path).resolve())
    case = spec["case"]
    run_index = spec.get("run_index")

    # Everything that can disqualify this run is checked before a client is
    # built, so a refusal costs nothing and is never recorded as an attempt.
    try:
        _guard_spending_path(spec, Path(spec_path))
    except (RunRefused, RuntimeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        (Path(spec_path).parent / REFUSAL_FILE).write_text(
            json.dumps({"refused": True, "reason": reason,
                        "spec_switches": spec.get("switches")},
                       indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        print(f"refused: {reason}", file=sys.stderr)
        return 2

    import traceback

    config, applied_switches = _config_for_spec(spec)

    # Exactly one graph is constructed per measured run.
    graph = _construct_graph(spec, config)

    # The spec's switches are now in ``config``, but "in config" is not the same
    # as "consumed by the graph". Ask the constructed ``GraphSetup`` what it
    # derived from that config and require it to equal what the arm declares.
    # The check runs before ``propagate``, so a mislabelled arm costs nothing.
    _verify_graph_consumed_switches(spec, graph, applied_switches)

    # Record the configuration this process is *actually* running with, after
    # every override has been folded in, and verify it against the spec before
    # the paid call. Written before ``propagate`` so a run that crashes still
    # leaves its configuration on disk.
    _write_effective_config(
        Path(spec_path).parent,
        config=config,
        spec=spec,
        graph=graph,
        applied_switches=applied_switches,
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

    # V3 memory isolation evidence: the snapshot must be byte-identical after
    # the run, and the run's own copy is the only thing that may have changed.
    memory_state = memory_state_after_run(spec)
    if memory_state:
        (Path(spec_path).parent / MEMORY_STATE_FILE).write_text(
            json.dumps(memory_state, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        if not memory_state.get("baseline_unchanged"):
            status = "failed"
            error = error or "memory snapshot was modified during the run"

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
        "memory": memory_state,
        "ticker": case.get("ticker"),
        "trade_date": case.get("trade_date"),
        "status": status,
        "run_status": status,
        "error": error,
        # ``_portable_path`` output is documented as relative to the experiment
        # directory (see ``_portable_path`` / ``_resolve_report_path``), and the
        # consumer resolves it against ``exp_dir``. ``spec.json`` lives at
        # ``<exp>/runs/run_NN/attempt_NN/``, so the base is four levels up, not
        # three: using ``parent.parent.parent`` yielded ``<exp>/runs`` and
        # dropped the ``runs/`` component, so every run was rejected as a
        # ``status_mismatch`` even though its telemetry was the only new file.
        "telemetry_path": _portable_path(telemetry_path, Path(spec_path).parent.parent.parent.parent),
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

# Non-CityU app variables the harness passes through from the same secrets file
# when the shell does not already set them. The app reads these from the process
# environment (e.g. ``fred.get_api_key``), so a value in the file alone reached
# the app only if the caller happened to export it. Only mapped names are copied
# — a stray variable in the file still cannot change the benchmark's config.
#: Spec switch name -> the env var ``default_config`` reads it from.
#: ``s2_downstream`` is deliberately absent: it has no implementation, so there
#: is no env var for it and ``validate_spec_switches`` refuses anything but True.
SPEC_SWITCH_ENV = (
    ("batch_macro", "TRADINGAGENTS_BATCH_MACRO_ENABLED"),
    ("structured", "TRADINGAGENTS_STRUCTURED_ANALYST_OUTPUT_ENABLED"),
    ("single_pass", "TRADINGAGENTS_SINGLE_PASS_FINALIZATION_ENABLED"),
)

_PASSTHROUGH_ENV = (
    "FRED_API_KEY",          # dataflows/fred.py: the macro_data vendor
    "SEC_EDGAR_USER_AGENT",  # dataflows/sec_edgar.py: optional filings vendor
    # The study's *only* news vendor. Without this the child process sees no
    # key and every one of the 16 runs renders AUTH_MISSING while the config
    # still claims a Finnhub-only news path (independent audit A-01).
    "FINNHUB_API_KEY",
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
    # A template that names an arm must keep naming it. ``_TEMPLATE_KEYS``
    # covers the plain configuration, and leaving the switch block out here
    # made ``measure`` silently derive an armless experiment from an armed
    # template -- the derived run would then be refused (or, before the
    # refusal existed, measured under DEFAULT_CONFIG while the operator
    # believed it ran the registered arm). Carried verbatim; the pre-flight
    # validates it like any other registration.
    for key in ("switches", "switches_required"):
        if key in template:
            exp[key] = template[key]
    # The news scope is part of the frozen definition too. Deriving a
    # measurement that dropped it produced a registration the child refused,
    # because `news_scope` is a required spec field (audit A round 4, H-B).
    if "news_scope" in template:
        exp["news_scope"] = template["news_scope"]
    if isinstance(template.get("budget"), dict):
        # Carried verbatim, including the budget_mode that makes a null cap
        # mean "uncapped" rather than "unconfigured" (U-2). A template whose
        # budget is null has no contract to carry.
        exp["budget"] = template["budget"]
    if "checkpoint_enabled" in template:
        exp["checkpoint_enabled"] = template["checkpoint_enabled"]
    # The hash names this *derived* definition, which differs from the template
    # in its id and case, so the template's value cannot be copied -- it would
    # describe a definition that is not this one. A legacy template that does
    # not carry the full frozen field set has no hash to give; it is left
    # unhashed rather than hashed over defaults nobody registered.
    try:
        exp["config_sha256"] = registration_sha256(exp)
    except KeyError:
        exp.pop("config_sha256", None)
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
        value = _unquote(value.strip())
        values[key] = value
    return values


def _unquote(value: str) -> str:
    """Strip one matching quote pair, tolerating a doubled wrapper.

    Editors and shell wrappers sometimes leave ``""sk-…""`` behind after a
    re-quote; the inner quote pair is then the real one. Only quotes are
    touched — the value itself is never evaluated or expanded.
    """
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def apply_cityu_env(env: MutableMapping[str, str], secrets_path: Path) -> list[str]:
    """Map the CityU secrets onto the app's env vars. Returns the names applied.

    Values from the *explicitly named* secrets file win over the ambient
    environment. The opposite precedence (ambient wins) meant a shell that
    happened to export ``CITYU_FOUNDRY_BASE_URL`` silently redirected a
    measurement away from the endpoint its operator named on the command line:
    a probe pointed at ``http://127.0.0.1:9`` was observed dialling the real
    paid endpoint on port 443, because the ambient value took precedence. The
    file the operator passed is the authority; the environment is only a
    fallback for names the file does not mention.
    """
    file_values = _env_file_values(Path(secrets_path))
    applied = []
    for source, target in _CITYU_ENV_MAP:
        value = file_values.get(source)
        if value:
            env[target] = value
            applied.append(target)
    for name in _PASSTHROUGH_ENV:
        value = file_values.get(name)
        if value:
            env[name] = value
            applied.append(name)
    return applied


def credential_state(env: Mapping[str, str]) -> list[dict]:
    """Report which optional data credentials are configured. Never prints values."""
    return [
        {"variable": name, "configured": bool(env.get(name))}
        for name in _PASSTHROUGH_ENV
    ]


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
        # A rehearsal that is refused must leave the directory exactly as it
        # found it. Writing ``code_state.json`` here, before the pre-flight,
        # left a refused dry run looking like the start of a measurement --
        # the same impurity the per-case pre-flight was moved to fix (audit
        # B-07), just one layer further out. ``run_experiment`` computes the
        # fingerprint without persisting it.
        try:
            result = run_experiment(exp_dir, experiment, dry_run=True)
        except RunRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            print(f"dry run refused; nothing was written")
            return 2
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
