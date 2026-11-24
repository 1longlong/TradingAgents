"""Deterministic, offline validation for the CS5351 governance scaffold.

Run from the repository root:

    .venv/bin/python scripts/validate/validate_requirements.py

This script validates, without network and without paid APIs:

1. Required artifact presence (every governance file exists and is non-empty).
2. JSON and JSONC files parse (JSONC comments are stripped deterministically
   before parsing; the resulting text is parsed with stdlib ``json``, so no
   third-party JSONC package is required).
3. YAML files parse with SafeLoader and duplicate-key rejection. Missing PyYAML
   blocks validation rather than treating unchecked YAML as passing.
4. ``docs/req/requirements.yaml`` validates against ``docs/req/req-schema.json``
   using the real draft-2020-12 JSON Schema when ``jsonschema`` is installed
   (the governance CI job installs it, so the actual schema is enforced there).
   When ``jsonschema`` is unavailable, a deterministic subset validator is used as a clearly reported
   local fallback. The subset validator is NOT a general JSON Schema
   implementation; it checks the per-requirement and ``project`` rules the real
   registry depends on, including ``project.schema_version`` matching the
   *pattern read from the actual schema* (not a hardcoded version), so a
   non-empty-but-invalid version such as ``"1.0"`` is rejected on BOTH paths.

   Pure JSON Schema alone cannot guarantee two registry contracts, so the
   *combined* validation entry point (``validate_against_schema``, and the
   fallback ``validate_requirements``) runs two shared semantic checks on BOTH
   paths, in addition to the schema:
   - ``validate_unique_requirement_ids`` — ``requirements[].id`` uniqueness
     (``uniqueItems`` compares whole objects, so two same-ID rows differing in
     any field would otherwise both pass);
   - ``validate_requirement_references`` — narrow dangling-reference resolution
     for the ``product.priorities[].requirement_id`` /
     ``product.tradeoffs[].requirement_id`` contract (a no-op when the registry
     omits those blocks, so minimal schemas stay valid).
   Unified 1.1 registries additionally enforce criterion-ID uniqueness,
   dependency integrity, finite thresholds and historical-evidence scope. The
   fallback covers this repository's explicit schema vocabulary and rejects
   unsupported validation keywords. Legacy release fixture format remains
   readable for its historical contract tests; the on-disk registry uses only
   the canonical WebUI-based format.
5. Secret scan over the listed documentation/artifact files: any line
   containing a likely secret (``sk-``, ``Bearer`` token, common key=value with
   a long secret-ish value) is reported by file:line WITHOUT printing the
   secret value.

Outputs human-readable results and exits non-zero on any failure. Safe to add
to CI as a deterministic gate.

Traceability: NFR-SEC-001, INV-1/10, core ADR-006 schema fail-closed contract.
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
    "docs/architecture/adr/003-phase4a-offline-comparison.md",
    "docs/architecture/adr/004-governance-context-design.proposed.md",
    "docs/architecture/adr/005-blocked-output-multiline-containment.md",
    "docs/architecture/adr/006-validator-fail-closed-schema-version.md",
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
    "prompts/prompt_v1.3.yaml",
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
    "prompts/prompt_v1.3.yaml",
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
def parse_jsonc(text: str) -> object:
    # Globs and URLs inside strings may contain /* or //; these are data.
    output = []
    index = 0
    quoted = escaped = False
    while index < len(text):
        char = text[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
        elif char == '"':
            quoted = True
            output.append(char)
            index += 1
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                raise ValueError("unterminated JSONC block comment")
            output.extend("\n" if c == "\n" else " " for c in text[index:end + 2])
            index = end + 2
        else:
            output.append(char)
            index += 1
    return json.loads("".join(output))


def load_registry_yaml(text: str) -> object:
    """Read data with SafeLoader and reject duplicate mapping keys."""
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key, value in node.value:
            parsed = loader.construct_object(key, deep=deep)
            if parsed in result:
                raise ValueError(f"duplicate YAML key at line {key.start_mark.line + 1}")
            result[parsed] = loader.construct_object(value, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(text, Loader=UniqueLoader)


# ---------------------------------------------------------------------------
# Shared semantic ID uniqueness.
#
# ``requirements[].id`` must be unique. JSON Schema ``uniqueItems`` alone is NOT
# sufficient: it compares whole objects, so two requirement objects that share an
# ``id`` but differ in any other field are each unique and both pass. The real
# ``jsonschema`` path therefore accepted duplicate IDs that the deterministic
# subset validator rejected. Both entry paths call this single shared check so
# they can never disagree. Malformed input (non-object registry, non-list
# ``requirements``, non-dict rows, missing/non-string IDs) is ignored here and
# handled by the per-path validation, so this helper never crashes.
# ---------------------------------------------------------------------------
def validate_unique_requirement_ids(requirements: object) -> list[str]:
    """Return duplicate-ID errors (empty when every requirement ID is unique)."""
    if not isinstance(requirements, dict):
        return []
    reqs = requirements.get("requirements")
    if not isinstance(reqs, list):
        return []
    seen: set[str] = set()
    errors: list[str] = []
    for idx, req in enumerate(reqs):
        if not isinstance(req, dict):
            continue
        rid = req.get("id")
        if not isinstance(rid, str) or not rid.strip():
            continue
        if rid in seen:
            errors.append(f"requirements[{idx}].id {rid!r} is a duplicate")
        else:
            seen.add(rid)
    return errors


# ---------------------------------------------------------------------------
# Narrow semantic reference validation (dangling-reference check).
#
# The real JSON Schema only checks the PATTERN of a product ``requirement_id``
# reference (e.g. ``FR-DQG-001``); it cannot assert that the referenced ID
# actually EXISTS in the registry. The combined validation entry point therefore
# also resolves product ``priorities``/``tradeoffs`` references against the
# requirement IDs. It is deliberately NARROW: it only checks the reference
# contract the real registry supplies (``product.priorities[].requirement_id``
# and ``product.tradeoffs[].requirement_id``) and is a no-op for minimal schemas
# that omit those blocks, so existing minimal-schema tests stay valid. Malformed
# rows are skipped here (shape errors are reported by the schema path).
# ---------------------------------------------------------------------------
_REFERENCE_BLOCKS = (("product", "priorities"), ("product", "tradeoffs"))


def validate_requirement_references(requirements: object) -> list[str]:
    """Return dangling-reference errors for known product reference blocks.

    Empty when there are none, or when the relevant blocks are absent (so a
    minimal schema/registry without product references is unaffected).
    """
    if not isinstance(requirements, dict):
        return []
    reqs = requirements.get("requirements")
    if not isinstance(reqs, list):
        return []
    known = {
        r.get("id")
        for r in reqs
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }
    product = requirements.get("product")
    if not isinstance(product, dict):
        return []
    errors: list[str] = []
    for parent, key in _REFERENCE_BLOCKS:
        del parent  # both reference blocks live under `product`
        block = product.get(key)
        if not isinstance(block, list):
            continue
        for idx, entry in enumerate(block):
            if not isinstance(entry, dict):
                continue
            ref = entry.get("requirement_id")
            if not isinstance(ref, str) or not ref.strip():
                continue
            if ref not in known:
                errors.append(
                    f"product.{key}[{idx}].requirement_id {ref!r} does not "
                    "resolve to a requirement ID"
                )
    return errors


# Canonical 1.1 contract support. This is shared with the second CI entry point.
# Registry commands are treated as text and never executed by validation.
_CANONICAL_ID = re.compile(r"^(?:REQ-[A-Z][A-Z0-9]*-?[0-9]{2,4}|FR-(?:DQG|DDT|TRD|ANL|OBS|HAR|CAM)-[0-9]{3}|INV-TRD-[0-9]{3}|NFR-[A-Z]+-[0-9]{3})$")


def is_canonical_registry(data: object) -> bool:
    if not isinstance(data, dict):
        return False
    rows = data.get("requirements")
    return "schema_version" in data or (
        isinstance(rows, list) and any(isinstance(row, dict) and "fit_criteria" in row for row in rows)
    )


def validate_canonical_semantics(data: object) -> list[str]:
    """Preserve criterion identity, dependency integrity and historical evidence scope."""
    import math

    if not isinstance(data, dict) or not isinstance(data.get("requirements"), list):
        return ["requirements must be a list"]
    errors = validate_unique_requirement_ids(data) + validate_requirement_references(data)
    rows = data["requirements"]
    known = {row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)}
    criteria: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        prefix = f"requirements[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        rid = row.get("id")
        if not isinstance(rid, str) or not _CANONICAL_ID.fullmatch(rid):
            errors.append(f"{prefix}.id is not a valid stable requirement id")
        deps = row.get("depends_on", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) for dep in deps):
            errors.append(f"{prefix}.depends_on must be a string list")
        elif isinstance(rid, str):
            dependencies[rid] = deps
            errors.extend(f"{prefix} has unknown dependency {dep}" for dep in deps if dep not in known)
        fits = row.get("fit_criteria")
        if not isinstance(fits, list) or not fits:
            errors.append(f"{prefix}.fit_criteria must be a non-empty list")
            continue
        for fit in fits:
            if not isinstance(fit, dict):
                errors.append(f"{prefix}.fit_criteria item must be an object")
                continue
            identifier = fit.get("id")
            if not isinstance(identifier, str):
                errors.append(f"{prefix} criterion id must be a string")
            elif identifier in criteria:
                errors.append(f"duplicate acceptance criterion id: {identifier}")
            else:
                criteria.add(identifier)
            threshold = fit.get("threshold")
            values = threshold if isinstance(threshold, list) else [threshold]
            if any(isinstance(value, float) and not math.isfinite(value) for value in values):
                errors.append(f"{prefix} threshold must be finite")
            status = fit.get("status", {})
            if (row.get("status") == "verified" and isinstance(status, dict)
                    and status.get("evidence_scope") == "historical-release"):
                errors.append(f"{prefix}: historical-release evidence cannot certify a newly verified requirement")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting:
            errors.append(f"requirement dependency cycle at {node}")
            return
        if node in visited:
            return
        visiting.add(node)
        for dependency in dependencies.get(node, []):
            if dependency in dependencies:
                visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)
    return errors


def _canonical_schema_subset(data: object, schema: dict) -> list[str]:
    """Offline fallback for this repository's explicit schema vocabulary only.

    This is not a general JSON Schema implementation. Unsupported validation
    keywords fail closed; metadata is ignored. CI still uses jsonschema's real
    Draft202012Validator. No schema reference may read a file or a URL.
    """
    import math

    metadata = {"$schema", "$id", "$comment", "$defs", "title", "description", "default", "examples"}
    supported = {"$ref", "type", "const", "enum", "required", "properties", "additionalProperties",
                 "pattern", "minLength", "minimum", "maximum", "minItems", "uniqueItems", "items",
                 "oneOf", "allOf", "if", "then", "else"}

    def matches_type(value: object, name: str) -> bool:
        if name == "object":
            return isinstance(value, dict)
        if name == "array":
            return isinstance(value, list)
        if name == "string":
            return isinstance(value, str)
        if name == "boolean":
            return isinstance(value, bool)
        if name == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if name == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        if name == "null":
            return value is None
        return False

    def same(left: object, right: object) -> bool:
        # JSON's boolean true is not the numeric value one.
        return (isinstance(left, bool) == isinstance(right, bool)) and left == right

    def check(value: object, rule: object, path: str, depth: int = 0) -> list[str]:
        if depth > 80:
            return [f"{path}: schema nesting limit exceeded"]
        if rule is True:
            return []
        if rule is False:
            return [f"{path}: schema forbids this value"]
        if not isinstance(rule, dict):
            return [f"{path}: invalid schema object"]
        unknown = set(rule) - supported - metadata
        if unknown:
            return [f"{path}: unsupported fallback schema keywords: {sorted(unknown)}"]
        out = []
        if "$ref" in rule:
            ref = rule["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/"):
                return [f"{path}: only local schema references are supported"]
            target = schema
            try:
                for key in ref[2:].split("/"):
                    target = target[key.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                return [f"{path}: unresolved schema reference {ref}"]
            out += check(value, target, path, depth + 1)
        if "type" in rule:
            types = rule["type"] if isinstance(rule["type"], list) else [rule["type"]]
            if not any(matches_type(value, name) for name in types):
                return out + [f"{path}: invalid type, expected {types}"]
        if "const" in rule and not same(value, rule["const"]):
            out.append(f"{path}: invalid constant")
        if "enum" in rule and not any(same(value, item) for item in rule["enum"]):
            out.append(f"{path}: invalid enum value")
        if isinstance(value, dict):
            for key in rule.get("required", []):
                if key not in value:
                    out.append(f"{path}.{key}: required property missing")
            properties = rule.get("properties", {})
            for key, child in value.items():
                if key in properties:
                    out += check(child, properties[key], f"{path}.{key}", depth + 1)
                elif rule.get("additionalProperties") is False:
                    out.append(f"{path}.{key}: unexpected property")
        if isinstance(value, str):
            if len(value) < rule.get("minLength", 0):
                out.append(f"{path}: string is too short")
            if "pattern" in rule and re.search(rule["pattern"], value) is None:
                out.append(f"{path}: does not match pattern {rule['pattern']}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                out.append(f"{path}: below minimum")
            if "maximum" in rule and value > rule["maximum"]:
                out.append(f"{path}: above maximum")
        if isinstance(value, list):
            if len(value) < rule.get("minItems", 0):
                out.append(f"{path}: too few items")
            if rule.get("uniqueItems") and any(
                same(item, earlier) for i, item in enumerate(value) for earlier in value[:i]
            ):
                out.append(f"{path}: duplicate array item")
            if "items" in rule:
                for i, item in enumerate(value):
                    out += check(item, rule["items"], f"{path}[{i}]", depth + 1)
        if "oneOf" in rule and sum(not check(value, branch, path, depth + 1) for branch in rule["oneOf"]) != 1:
            out.append(f"{path}: must match exactly one schema alternative")
        for branch in rule.get("allOf", []):
            out += check(value, branch, path, depth + 1)
        if "if" in rule:
            branch = "then" if not check(value, rule["if"], path, depth + 1) else "else"
            if branch in rule:
                out += check(value, rule[branch], path, depth + 1)
        return out

    return check(data, schema, "registry")



# ---------------------------------------------------------------------------
# Schema validation dispatcher.
#
# Preferred: the REAL draft-2020-12 JSON Schema validator (jsonschema) against
# docs/req/req-schema.json. This is what CI enforces (CI installs jsonschema).
#
# Fallback: the deterministic subset validator (`validate_requirements`), used
# ONLY when `jsonschema` is not installed. It is clearly reported as a fallback
# so a masked schema regression cannot be mistaken for a real pass.
#
# Both paths additionally run the shared semantic checks (ID uniqueness AND
# dangling-reference resolution) so a duplicate ID or a reference to a
# non-existent requirement is rejected regardless of which validator is in force.
# Pure JSON Schema alone cannot express either cross-object contract.
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
            # The real schema cannot express cross-object ID uniqueness
            # (uniqueItems compares whole objects) or dangling-reference
            # resolution, so enforce both explicitly via the shared checks.
            return (
                problems
                + validate_unique_requirement_ids(requirements)
                + validate_requirement_references(requirements)
                + (validate_canonical_semantics(requirements) if is_canonical_registry(requirements) else [])
            )
        except Exception as exc:  # noqa: BLE001
            return [f"jsonschema validation raised: {exc}"]
    # Fallback: deterministic subset validator (reported as such by the caller).
    return validate_requirements(requirements, schema)


# ---------------------------------------------------------------------------
# Deterministic subset validator for req-schema.json (no jsonschema needed).
# ---------------------------------------------------------------------------
def _is_nonempty_str(value: object) -> bool:
    return isinstance(value, str) and len(value.strip()) > 0


def _schema_string_pattern(schema: object, *path: str) -> str | None:
    """Return the ``pattern`` declared for a property path in the real schema.

    The subset fallback must enforce the same constraints the real draft-2020-12
    validator enforces, so it reads the actual pattern from ``docs/req/req-schema.json``
    rather than hardcoding one version/format. Returns ``None`` when the schema
    path (or its ``pattern``) is absent, in which case the fallback only requires a
    non-empty string — it must never invent a stricter rule than the schema.
    """
    node: object = schema
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if not isinstance(node, dict):
        return None
    pattern = node.get("pattern")
    return pattern if isinstance(pattern, str) else None


def validate_requirements(requirements: object, schema: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(schema, dict):
        return ["schema is not a JSON object"]
    if not isinstance(requirements, dict):
        return ["requirements is not a JSON/YAML object"]

    if is_canonical_registry(requirements):
        return _canonical_schema_subset(requirements, schema) + validate_canonical_semantics(requirements)

    proj = requirements.get("project")
    if not isinstance(proj, dict):
        errors.append("project is not an object")
    else:
        for key in ("name", "branch", "schema_version"):
            if not _is_nonempty_str(proj.get(key)):
                errors.append(f"project.{key} is missing/non-empty")
        # Fallback fail-closed: `schema_version` is a pattern-constrained string
        # in the real schema, not merely "non-empty". A non-empty-but-wrong value
        # such as "1.0" (the schema requires `^v[0-9]+\.[0-9]+$`) passed the
        # subset check while the real schema rejects it, so the CI (no-jsonschema)
        # jobs accepted a value the governance job rejects. Read the actual
        # pattern from the schema so the two paths agree; when the schema omits
        # the pattern, only non-emptiness is required (no invented constraint).
        schema_version = proj.get("schema_version")
        pattern = _schema_string_pattern(
            schema, "properties", "project", "properties", "schema_version"
        )
        if (
            pattern is not None
            and _is_nonempty_str(schema_version)
            and re.fullmatch(pattern, schema_version) is None
        ):
            errors.append(
                f"project.schema_version {schema_version!r} does not match the "
                f"schema pattern {pattern!r}"
            )
        for key in ("deliverable_slide_sources", "canonical_source_trees"):
            val = proj.get(key)
            if not isinstance(val, list) or not val:
                errors.append(f"project.{key} must be a non-empty list")

    reqs = requirements.get("requirements")
    if not isinstance(reqs, list) or not reqs:
        errors.append("requirements must be a non-empty list")
        return errors

    # Shared semantic ID uniqueness (identical to the real-schema path); the
    # per-row loop below only checks each ID's presence and shape.
    errors.extend(validate_unique_requirement_ids(requirements))
    # Narrow dangling-reference resolution (identical to the real-schema path);
    # a no-op when the registry has no product reference blocks.
    errors.extend(validate_requirement_references(requirements))
    for idx, req in enumerate(reqs):
        prefix = f"requirements[{idx}]"
        if not isinstance(req, dict):
            errors.append(f"{prefix} is not an object")
            continue
        rid = req.get("id")
        if not _is_nonempty_str(rid):
            errors.append(f"{prefix}.id is missing")
        # Read the ID pattern from the real schema so the subset fallback cannot
        # drift from it when a namespace is added (v1.3 added FR-ANL/OBS/HAR/CAM
        # and, under the existing NFR-[A-Z]+ branch, NFR-VER). The schema declares
        # it on $defs.requirement.properties.id. A minimal schema without that
        # path keeps the historical fallback set rather than inventing a stricter
        # rule, matching the helper's documented contract.
        id_pattern = _schema_string_pattern(
            schema, "$defs", "requirement", "properties", "id"
        ) or r"^(FR-(DQG|DDT|TRD|ANL|OBS|HAR|CAM)|INV-TRD|NFR-[A-Z]+)-[0-9]{3}$"
        if re.fullmatch(id_pattern, str(rid)) is None:
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
    "docs/architecture/adr/003-phase4a-offline-comparison.md",
    "docs/architecture/adr/004-governance-context-design.proposed.md",
    "docs/architecture/adr/005-blocked-output-multiline-containment.md",
    "docs/architecture/adr/006-validator-fail-closed-schema-version.md",
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
    "prompts/prompt_v1.3.yaml",
    "transcripts/60536848-WANG-Yiwen.md",
    "src/README.md",
    "test/offline/README.md",
    "test/live/README.md",
]


def scan_secrets(text: str) -> list[int]:
    hits: list[int] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        # sk-<long> pattern (OpenAI-style). The boundary must be
        # non-alphanumeric. The previous optional-prefix form
        # `[^a-zA-Z0-9]?sk-...` also matched the substring inside ordinary
        # hyphenated words ("risk-management", "disk-usage-..."), so the scanner
        # could not distinguish prose from key material.
        if re.search(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{10,}", line):
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
        errors.append("PyYAML is required; YAML/schema validation was not performed")
    if yaml is not None:
        for rel in YAML_FILES:
            path = ROOT / rel
            if not path.exists():
                continue
            try:
                load_registry_yaml(path.read_text(encoding="utf-8"))
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
                requirements = load_registry_yaml(f.read())
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
