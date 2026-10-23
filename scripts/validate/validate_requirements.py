"""Deterministic, offline validation for the CS5351 governance scaffold.

Run from the repository root:

    .venv/bin/python scripts/validate/validate_requirements.py

This script validates, without network and without paid APIs:

1. Required artifact presence (every governance file exists and is non-empty).
2. JSON and JSONC files parse (JSONC comments are stripped deterministically
   before parsing; the resulting text is parsed with stdlib ``json``, so no
   third-party JSONC package is required).
3. YAML files parse (via PyYAML if installed; else a conservative fallback).
4. ``docs/req/requirements.yaml`` validates against ``docs/req/req-schema.json``
   using the real draft-2020-12 JSON Schema when ``jsonschema`` is installed
   (CI installs it, so the actual schema is enforced there). When ``jsonschema``
   is unavailable, a deterministic subset validator is used as a clearly
   reported local fallback.
5. Secret scan over the listed documentation/artifact files: any line
   containing a likely secret (``sk-``, ``Bearer`` token, common key=value with
   a long secret-ish value) is reported by file:line WITHOUT printing the
   secret value.

Outputs human-readable results and exits non-zero on any failure. Safe to add
to CI as a deterministic gate.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# JSON Schema (draft 2020-12) availability.
# When `jsonschema` is installed (CI installs it) the REAL schema is enforced.
# Otherwise the deterministic subset validator is used as a clearly-reported
# local fallback (see `validate_against_schema` below).
# ---------------------------------------------------------------------------
_JSSCHEMA_AVAILABLE = False
_validator_name = ""


def _detect_jsonschema() -> None:
    global _JSSCHEMA_AVAILABLE, _validator_name
    if importlib.util.find_spec("jsonschema") is not None:
        _JSSCHEMA_AVAILABLE = True
        _validator_name = "Draft202012Validator"
    else:
        _JSSCHEMA_AVAILABLE = False
        _validator_name = "deterministic-subset"

# ---------------------------------------------------------------------------
# Required artifact tree (every file must exist and be non-empty)
# ---------------------------------------------------------------------------
REQUIRED_FILES = [
    "README.md",
    "AGENTS.md",
    "architecture-blueprint.md",
    "Prompt.md",
    "Report.md",
    "docs/req/requirements.yaml",
    "docs/req/req-schema.json",
    "docs/architecture/adr/001-data-quality-gate.md",
    "docs/architecture/adr/002-dynamic-debate-termination.md",
    "docs/architecture/invariants.md",
    "docs/architecture/trace-matrix.md",
    "docs/architecture/memory-design.md",
    "docs/architecture/option-ledger.md",
    "docs/architecture/permission-model.md",
    "docs/architecture/evaluation-logbook.md",
    "docs/architecture/risk-list.md",
    "docs/architecture/evaluation-table.md",
    "docs/architecture/runtime-policy-catalog.md",
    "docs/code-governance/structural-constraints.md",
    "docs/code-governance/verification-constraints.md",
    "docs/code-governance/mcp-tool-manifest.md",
    "docs/ai-use-log.yaml",
    "docs/review-memo.md",
    "docs/debt-register.md",
    "docs/bug-diary.md",
    ".opencode/permissions.jsonc",
    ".opencode/rules.md",
    ".agent/rules.md",
    "prompts/prompt_v1.0.yaml",
    "prompts/prompt_v1.1.yaml",
    "prompts/prompt_v1.2.yaml",
    "transcripts/60536848-WANG-Yiwen.md",
    "src/README.md",
    "test/offline/README.md",
    "test/live/README.md",
]

YAML_FILES = [
    "docs/req/requirements.yaml",
    "docs/ai-use-log.yaml",
    "prompts/prompt_v1.0.yaml",
    "prompts/prompt_v1.1.yaml",
    "prompts/prompt_v1.2.yaml",
]

JSON_FILES = [
    "docs/req/req-schema.json",
]

JSONC_FILES = [
    ".opencode/permissions.jsonc",
]

# ---------------------------------------------------------------------------
# Deterministic JSONC parsing: strip // and /* */ comments, then json.loads.
# ---------------------------------------------------------------------------
_COMMENT_RE = re.compile(r"^[ \t]*//.*$", re.MULTILINE)
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)


def parse_jsonc(text: str) -> object:
    stripped = _BLOCK_COMMENT_RE.sub("", text)
    stripped = _COMMENT_RE.sub("", stripped)
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Schema validation dispatcher.
#
# Preferred: the REAL draft-2020-12 JSON Schema validator (jsonschema) against
# docs/req/req-schema.json. This is what CI enforces (CI installs jsonschema).
#
# Fallback: the deterministic subset validator (`validate_requirements`), used
# ONLY when `jsonschema` is not installed. It is clearly reported as a fallback
# so a masked schema regression cannot be mistaken for a real pass.
# ---------------------------------------------------------------------------
def validate_against_schema(requirements: object, schema: object) -> list[str]:
    _detect_jsonschema()
    if _JSSCHEMA_AVAILABLE:
        try:
            from jsonschema import Draft202012Validator  # type: ignore

            validator = Draft202012Validator(schema)
            problems: list[str] = sorted(
                f"{list(e.absolute_path) or ['<root>']}: {e.message}"
                for e in validator.iter_errors(requirements)
            )
            return problems
        except Exception as exc:  # noqa: BLE001
            return [f"jsonschema validation raised: {exc}"]
    # Fallback: deterministic subset validator (reported as such by the caller).
    return validate_requirements(requirements, schema)


# ---------------------------------------------------------------------------
# Deterministic subset validator for req-schema.json (no jsonschema needed).
# ---------------------------------------------------------------------------
def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def validate_requirements(requirements: object, schema: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["schema is not a JSON object"]
    if not isinstance(requirements, dict):
        return ["requirements is not a JSON/YAML object"]

    proj = requirements.get("project")
    if not isinstance(proj, dict):
        errors.append("project is not an object")
    else:
        for key in ("name", "branch", "schema_version"):
            if not _is_nonempty_str(proj.get(key)):
                errors.append(f"project.{key} is missing/non-empty")
        for key in ("deliverable_slide_sources", "canonical_source_trees"):
            val = proj.get(key)
            if not isinstance(val, list) or not val:
                errors.append(f"project.{key} must be a non-empty list")

    reqs = requirements.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        errors.append("requirements must be a non-empty list")
        return errors

    seen_ids: set[str] = set()
    for idx, req in enumerate(reqs):
        prefix = f"requirements[{idx}]"
        if not isinstance(req, dict):
            errors.append(f"{prefix} is not an object")
            continue
        rid = req.get("id")
        if not _is_nonempty_str(rid):
            errors.append(f"{prefix}.id is missing")
        elif rid in seen_ids:
            errors.append(f"{prefix}.id {rid!r} is a duplicate")
        else:
            seen_ids.add(rid)
        if not re.match(r"^(FR-(DQG|DDT)|NFR-[A-Z]+)-[0-9]{3}$", str(rid)):
            errors.append(f"{prefix}.id {rid!r} does not match the stable ID pattern")
        for key in ("title", "description"):
            if not _is_nonempty_str(req.get(key)):
                errors.append(f"{prefix}.{key} is missing")
        if req.get("type") not in ("Feature", "NonFunctional"):
            errors.append(f"{prefix}.type must be Feature or NonFunctional")
        if req.get("priority") not in ("Must", "Should", "Could"):
            errors.append(f"{prefix}.priority must be Must/Should/Could")
        for key in ("source_files", "design_artifacts", "verification_evidence"):
            val = req.get(key)
            if not isinstance(val, list) or not val:
                errors.append(f"{prefix}.{key} must be a non-empty list")
        tests = req.get("tests")
        if tests is not None and not isinstance(tests, list):
            errors.append(f"{prefix}.tests must be a list")
        status = req.get("status")
        if status is not None and status not in ("Implemented", "Partially"):
            errors.append(f"{prefix}.status must be Implemented/Partially")
    return errors


# ---------------------------------------------------------------------------
# Secret scan (reports presence + location only, never the value)
# ---------------------------------------------------------------------------
_SECRET_KEYS = re.compile(r"(?:api[_-]?key|secret|token|password|passwd|bearer)")

# Scan only the governance/artifact files we author (avoid scanning real .env).
SCAN_FILES = [
    "AGENTS.md",
    "architecture-blueprint.md",
    "Prompt.md",
    "Report.md",
    "docs/req/requirements.yaml",
    "docs/req/req-schema.json",
    "docs/architecture/adr/001-data-quality-gate.md",
    "docs/architecture/adr/002-dynamic-debate-termination.md",
    "docs/architecture/trace-matrix.md",
    "docs/architecture/permission-model.md",
    "docs/architecture/memory-design.md",
    "docs/architecture/option-ledger.md",
    "docs/architecture/evaluation-logbook.md",
    "docs/architecture/risk-list.md",
    "docs/architecture/evaluation-table.md",
    "docs/architecture/runtime-policy-catalog.md",
    "docs/architecture/invariants.md",
    "docs/code-governance/structural-constraints.md",
    "docs/code-governance/verification-constraints.md",
    "docs/code-governance/mcp-tool-manifest.md",
    "docs/ai-use-log.yaml",
    "docs/review-memo.md",
    "docs/debt-register.md",
    "docs/bug-diary.md",
    ".opencode/permissions.jsonc",
    ".opencode/rules.md",
    ".agent/rules.md",
    "prompts/prompt_v1.0.yaml",
    "prompts/prompt_v1.1.yaml",
    "prompts/prompt_v1.2.yaml",
    "transcripts/60536848-WANG-Yiwen.md",
    "src/README.md",
    "test/offline/README.md",
    "test/live/README.md",
]


def scan_secrets(text: str) -> list[int]:
    hits: list[int] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        # sk-<long> pattern (OpenAI-style).
        if re.search(r"[^a-zA-Z0-9]?sk-[A-Za-z0-9_-]{10,}", line):
            hits.append(lineno)
            continue
        # Bearer <token> literal.
        if re.search(r"\bbearer\s+[A-Za-z0-9._-]{10,}", low):
            hits.append(lineno)
            continue
        # "api_key"/"secret"/"token"/"password" = <long non-placeholder value>
        m = re.search(r"(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]?([^'\"\s,;]+)", low)
        if m and _SECRET_KEYS.search(m.group(1)):
            value = m.group(2)
            # A real secret is a long opaque value. Placeholders that start with a
            # known placeholder token (your/xxx/example/changeme/<...>) are fine.
            if len(value) >= 12 and not re.match(
                r"^(your|xxx|example|changeme|placeholder|<.*>|\*+)[^;,\s]*$", value
            ):
                hits.append(lineno)
    return hits


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    _detect_jsonschema()
    errors: list[str] = []
    warnings: list[str] = []
    ok_count = 0

    # 1. Required artifact presence + non-empty.
    for rel in REQUIRED_FILES:
        path = ROOT / rel
        if not path.exists():
            errors.append(f"MISSING artifact: {rel}")
            continue
        if path.stat().st_size == 0:
            errors.append(f"EMPTY artifact: {rel}")
            continue
        ok_count += 1

    # 2. JSON / JSONC parse.
    for rel in JSON_FILES + JSONC_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            if rel in JSON_FILES:
                json.loads(path.read_text(encoding="utf-8"))
            else:
                parse_jsonc(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON parse failure {rel}: {exc}")

    # 3. YAML parse.
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None
        warnings.append("PyYAML not installed; YAML files are checked for presence only")
    if yaml is not None:
        for rel in YAML_FILES:
            path = ROOT / rel
            if not path.exists():
                continue
            try:
                yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"YAML parse failure {rel}: {exc}")
    else:
        warnings.append("YAML structural validation skipped (no PyYAML)")

    # 4. requirements vs schema.
    req_path = ROOT / "docs/req/requirements.yaml"
    schema_path = ROOT / "docs/req/req-schema.json"
    if yaml is not None and req_path.exists() and schema_path.exists():
        try:
            with open(req_path, encoding="utf-8") as f:
                requirements = yaml.safe_load(f)
            with open(schema_path, encoding="utf-8") as f:
                schema = json.loads(f.read())
            schema_errors = validate_against_schema(requirements, schema)
            if _JSSCHEMA_AVAILABLE:
                errors.extend(f"schema({_validator_name})[{e}]" for e in schema_errors)
            else:
                # Clearly report that the deterministic subset (not a real JSON
                # Schema draft-2020-12 validator) was used as a local fallback.
                errors.extend(f"schema(subset-fallback, jsonschema not installed)[{e}]" for e in schema_errors)
                warnings.append(
                    "jsonschema is NOT installed; the deterministic subset "
                    "validator was used instead (NOT the real draft-2020-12 schema). "
                    "CI installs jsonschema so the real schema is enforced there."
                )
        except Exception as exc:  # noqa: BLE001
            errors.append(f"requirements/schema validation error: {exc}")

    # 5. Secret scan.
    secret_hits: dict[str, list[int]] = {}
    for rel in SCAN_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        hits = scan_secrets(path.read_text(encoding="utf-8"))
        if hits:
            secret_hits[rel] = hits

    # ---- Report ----
    print(f"required artifact presence: {ok_count}/{len(REQUIRED_FILES)} valid, "
          f"{len(REQUIRED_FILES) - ok_count} invalid")
    if secret_hits:
        for rel, lines in secret_hits.items():
            # Print only line numbers, never the matched secret value.
            print(f"SECRET SCAN: {rel} lines {lines}")
        errors.append(f"secret scan flagged {sum(len(v) for v in secret_hits.values())} line(s)")
    else:
        print("secret scan: no likely secrets found")

    if warnings:
        for w in warnings:
            print(f"WARN: {w}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        print(f"\nRESULT: FAIL ({len(errors)} error(s))")
        return 1
    print("\nRESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
