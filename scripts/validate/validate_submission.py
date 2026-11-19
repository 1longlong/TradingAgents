#!/usr/bin/env python3
"""Deterministic, offline CS5351 submission-compliance gate.

Run from the repository root::

    python scripts/validate/validate_submission.py

The gate performs only local reads; it never uses the network, an LLM, or a
paid API. It checks:

1. The 34 required course artifacts exist and are non-empty (three of them are
   directory items mapped to their README files; the transcript item requires
   the README and template and only *warns* about the human-pending file).
2. Required YAML/JSON/JSONC files parse.
3. ``docs/req/requirements.yaml`` passes the real draft-2020-12 schema when
   ``jsonschema`` is installed, or a deterministic manual fallback otherwise;
   requirement and acceptance-criterion IDs are unique and their implementation,
   test and evidence paths resolve.
4. ``docs/architecture/trace-matrix.md`` references resolve: every requirement
   ID it names exists, and every backticked repository path it names exists.
5. Every prompt YAML carries ``version`` and ``source_commit``.
6. ADR files exist and their numeric IDs are unique.
7. New documentation contains no obvious secrets (reported by file:line, never
   by value).
8. A real student-annotated transcript is present or explicitly reported as
   ``PENDING_HUMAN_CONFIRMATION`` (warning, never a hard failure: a human must
   write it).

Exit codes: 0 = PASS (warnings allowed), 1 = FAIL.
"""

from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# The audit checklist: 30 file items (one is the ADR glob), 3 directory items
# mapped to their README, and the transcript item = 34 total.
# ---------------------------------------------------------------------------
REQUIRED = [
    ("file", "README.md"),
    ("file", "AGENTS.md"),
    ("file", "architecture-blueprint.md"),
    ("file", "Prompt.md"),
    ("file", "Report.md"),
    ("file", "docs/req/requirements.yaml"),
    ("file", "docs/req/req-schema.json"),
    ("adr", "docs/architecture/adr/00*.md"),
    ("file", "docs/architecture/invariants.md"),
    ("file", "docs/architecture/trace-matrix.md"),
    ("file", "docs/architecture/memory-design.md"),
    ("file", "docs/architecture/option-ledger.md"),
    ("file", "docs/architecture/permission-model.md"),
    ("file", "docs/architecture/evaluation-logbook.md"),
    ("file", "docs/architecture/risk-list.md"),
    ("file", "docs/architecture/evaluation-table.md"),
    ("file", "docs/architecture/runtime-policy-catalog.md"),
    ("file", "docs/code-governance/structural-constraints.md"),
    ("file", "docs/code-governance/verification-constraints.md"),
    ("file", "docs/code-governance/mcp-tool-manifest.md"),
    ("file", "docs/ai-use-log.yaml"),
    ("file", "docs/review-memo.md"),
    ("file", "docs/debt-register.md"),
    ("file", "docs/bug-diary.md"),
    ("file", ".opencode/permissions.jsonc"),
    ("file", ".opencode/rules.md"),
    ("file", ".agent/rules.md"),
    ("file", ".github/workflows/ci.yml"),
    ("file", "prompts/prompt_v1.0.yaml"),
    ("file", "prompts/prompt_v1.1.yaml"),
    ("dir", "src", "src/README.md"),
    ("dir", "test/offline", "test/offline/README.md"),
    ("dir", "test/live", "test/live/README.md"),
    ("transcripts", "transcripts"),
]

if len(REQUIRED) != 34:  # pragma: no cover - a programming error, not data
    raise SystemExit(f"REQUIRED must have 34 items, found {len(REQUIRED)}")

YAML_FILES = [
    "docs/req/requirements.yaml",
    "docs/ai-use-log.yaml",
    "prompts/prompt_v1.0.yaml",
    "prompts/prompt_v1.1.yaml",
]
JSONC_FILES = [".opencode/permissions.jsonc"]

TRANSCRIPT_README = "transcripts/README.md"
TRANSCRIPT_TEMPLATE = "transcripts/TEMPLATE_student-id-student-name.md"
PROMPT_FILES = ("prompts/prompt_v1.0.yaml", "prompts/prompt_v1.1.yaml")

#: Files included in the deterministic secret scan. Only documentation, prompts,
#: governance and the workflow are scanned; the sealed experiment tree is not
#: (it is large and already covered by its own MANIFEST).
SCAN_PATHS = [
    "README.md",
    "AGENTS.md",
    "architecture-blueprint.md",
    "Prompt.md",
    "Report.md",
    "src/README.md",
    "test/offline/README.md",
    "test/live/README.md",
    "transcripts/README.md",
    TRANSCRIPT_TEMPLATE,
    ".github/workflows/ci.yml",
]
SCAN_TREES = ["docs", "prompts", ".opencode", ".agent", "transcripts"]

#: (label, compiled pattern). Values are never printed.
SECRET_PATTERNS = [
    ("OpenAI-style key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),
    ("GitHub personal token", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("PEM private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
]

REQUIREMENT_KEYS = (
    "id", "title", "type", "priority", "description", "acceptance_criteria",
    "implementation", "tests", "status", "evidence",
)
VALID_TYPES = {"functional", "non-functional"}
VALID_PRIORITIES = {"Must", "Should", "Could"}
VALID_STATUS = {"implemented", "partial", "not_implemented"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _nonempty_file(rel: str) -> bool:
    path = ROOT / rel
    return path.is_file() and bool(path.read_text(encoding="utf-8", errors="replace").strip())


def _path_exists(value: str) -> bool:
    """Resolve a repository-relative evidence path, tolerating ``file::test``."""
    candidate = value.split("::", 1)[0].strip()
    if not candidate or candidate.startswith(("commit ", "tag ")) or "://" in candidate:
        return True  # not a path-shaped evidence entry
    return (ROOT / candidate).exists()


def strip_jsonc(text: str) -> str:
    """Strip // and /* */ comments without touching string contents."""
    out: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue
        if char == "/" and i + 1 < len(text) and text[i + 1] == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue
        if char == "/" and i + 1 < len(text) and text[i + 1] == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def _load_yaml(rel: str, errors: list[str]):
    try:
        import yaml
    except ImportError:  # pragma: no cover - CI installs PyYAML
        errors.append("PyYAML is not installed; cannot parse YAML artifacts")
        return None
    try:
        return yaml.safe_load((ROOT / rel).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"{rel}: YAML parse failed: {exc}")
        return None


def _find_key(value, key: str):
    if isinstance(value, dict):
        if key in value:
            return value[key]
        for child in value.values():
            found = _find_key(child, key)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_key(child, key)
            if found is not None:
                return found
    return None


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
def check_required(errors: list[str], warnings: list[str]) -> int:
    present = 0
    for item in REQUIRED:
        kind = item[0]
        if kind == "file":
            rel = item[1]
            if _nonempty_file(rel):
                present += 1
            else:
                errors.append(f"required artifact missing or empty: {rel}")
        elif kind == "adr":
            pattern = item[1]
            matches = sorted(ROOT.glob(pattern))
            if matches and all(_nonempty_file(_rel(path)) for path in matches):
                present += 1
            else:
                errors.append(f"required artifact group missing or empty: {pattern}")
        elif kind == "dir":
            directory, readme = item[1], item[2]
            if (ROOT / directory).is_dir() and _nonempty_file(readme):
                present += 1
            else:
                errors.append(f"required directory/README missing: {directory} -> {readme}")
        elif kind == "transcripts":
            readme_ok = _nonempty_file(TRANSCRIPT_README)
            template_ok = _nonempty_file(TRANSCRIPT_TEMPLATE)
            if (ROOT / "transcripts").is_dir() and readme_ok and template_ok:
                present += 1
            else:
                errors.append(
                    "required transcripts item needs transcripts/README.md and "
                    f"{TRANSCRIPT_TEMPLATE}"
                )
            students = [
                path for path in (ROOT / "transcripts").glob("*.md")
                if path.name not in {"README.md"}
                and not path.name.startswith("TEMPLATE")
            ]
            if not students:
                warnings.append(
                    "no real student-annotated transcript found; "
                    "PENDING_HUMAN_CONFIRMATION (a human must complete "
                    f"{TRANSCRIPT_TEMPLATE} and rename it <student-id>-<student-name>.md)"
                )
            for path in students:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "PENDING_HUMAN_CONFIRMATION" in text or "student-id" in path.name:
                    warnings.append(f"{_rel(path)} is still a placeholder/PENDING")
    return present


def check_parsing(errors: list[str], warnings: list[str]) -> None:
    for rel in YAML_FILES:
        _load_yaml(rel, errors)
    for extra in sorted((ROOT / "docs/code-governance").glob("*.yaml")):
        _load_yaml(_rel(extra), errors)
    for rel in JSONC_FILES:
        path = ROOT / rel
        try:
            json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            errors.append(f"{rel}: JSONC parse failed: {exc}")
    schema_path = ROOT / "docs/req/req-schema.json"
    try:
        json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        errors.append(f"docs/req/req-schema.json: JSON parse failed: {exc}")


def _manual_requirement_errors(data) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["requirements.yaml: root must be a mapping"]
    if data.get("schema_version") != "1.0":
        errors.append("requirements.yaml: schema_version must be '1.0'")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        return errors + ["requirements.yaml: requirements must be a list"]
    if len(requirements) < 16:
        errors.append(f"requirements.yaml: expected >=16 requirements, found {len(requirements)}")
    seen: set[str] = set()
    ac_seen: set[str] = set()
    for index, req in enumerate(requirements):
        where = f"requirements[{index}]"
        if not isinstance(req, dict):
            errors.append(f"{where}: must be a mapping")
            continue
        for key in REQUIREMENT_KEYS:
            if key not in req:
                errors.append(f"{where}: missing field {key!r}")
        rid = req.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"(FR|NFR)-[0-9]{3}", rid or ""):
            errors.append(f"{where}: invalid requirement id {rid!r}")
            continue
        if rid in seen:
            errors.append(f"{where}: duplicate requirement id {rid!r}")
        seen.add(rid)
        rtype = req.get("type")
        if rtype not in VALID_TYPES:
            errors.append(f"{where}: type must be one of {sorted(VALID_TYPES)}")
        elif rtype == "functional" and not rid.startswith("FR-"):
            errors.append(f"{where}: functional requirement id must start FR-")
        elif rtype == "non-functional" and not rid.startswith("NFR-"):
            errors.append(f"{where}: non-functional requirement id must start NFR-")
        if req.get("priority") not in VALID_PRIORITIES:
            errors.append(f"{where}: priority must be one of {sorted(VALID_PRIORITIES)}")
        if req.get("status") not in VALID_STATUS:
            errors.append(f"{where}: status must be one of {sorted(VALID_STATUS)}")
        title = req.get("title")
        if not isinstance(title, str) or not 8 <= len(title) <= 120:
            errors.append(f"{where}: title must be a string of 8..120 characters")
        description = req.get("description")
        if not isinstance(description, str) or len(description) < 80:
            errors.append(f"{where}: description must be a string of >=80 characters")
        criteria = req.get("acceptance_criteria")
        minimum = 3 if req.get("priority") == "Must" else 2
        if not isinstance(criteria, list) or len(criteria) < minimum:
            errors.append(f"{where}: expected >={minimum} acceptance criteria")
        else:
            for cindex, criterion in enumerate(criteria):
                cwhere = f"{where}.acceptance_criteria[{cindex}]"
                if not isinstance(criterion, dict):
                    errors.append(f"{cwhere}: must be a mapping")
                    continue
                for key in ("id", "statement"):
                    if not criterion.get(key):
                        errors.append(f"{cwhere}: missing field {key!r}")
                cid = criterion.get("id")
                if isinstance(cid, str):
                    if cid in ac_seen:
                        errors.append(f"{cwhere}: duplicate acceptance id {cid!r}")
                    ac_seen.add(cid)
                    if not re.fullmatch(r"AC-(FR|NFR)-[0-9]{3}-[0-9]{2}", cid):
                        errors.append(f"{cwhere}: invalid acceptance id {cid!r}")
                    elif not cid.startswith(f"AC-{rid}-"):
                        errors.append(f"{cwhere}: acceptance id must derive from {rid}")
                statement = criterion.get("statement")
                if not isinstance(statement, str) or len(statement) < 20:
                    errors.append(f"{cwhere}: statement must be >=20 characters")
                verification = criterion.get("verification")
                if verification is not None and not _path_exists(str(verification)):
                    errors.append(f"{cwhere}: verification path does not exist: {verification}")
        for key in ("implementation", "tests"):
            values = req.get(key)
            if not isinstance(values, list) or not values:
                errors.append(f"{where}: {key} must be a non-empty list")
                continue
            if len(set(map(str, values))) != len(values):
                errors.append(f"{where}: {key} has duplicate entries")
            for value in values:
                if not isinstance(value, str) or not _path_exists(value):
                    errors.append(f"{where}: {key} path does not exist: {value!r}")
        evidence = req.get("evidence")
        required_evidence = 2 if req.get("status") == "implemented" else 1
        if not isinstance(evidence, list) or len(evidence) < required_evidence:
            errors.append(
                f"{where}: evidence must contain >={required_evidence} entries"
            )
        else:
            if len(set(map(str, evidence))) != len(evidence):
                errors.append(f"{where}: evidence has duplicate entries")
            for value in evidence:
                if isinstance(value, str) and not _path_exists(value):
                    errors.append(f"{where}: evidence path does not exist: {value!r}")
    return errors


def check_requirements(errors: list[str], warnings: list[str]) -> None:
    data = _load_yaml("docs/req/requirements.yaml", errors)
    if data is None:
        return
    schema_path = ROOT / "docs/req/req-schema.json"
    schema = None
    # Parse failures are already reported by check_parsing; this lookup only
    # supplies the schema object to the optional validator.
    with contextlib.suppress(OSError, ValueError):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema  # noqa: PLC0415 - optional dependency by design
    except ImportError:
        warnings.append(
            "jsonschema not installed; requirements validated with the deterministic "
            "manual fallback (CI installs jsonschema and enforces the real schema)"
        )
    else:
        if schema is not None:
            try:
                validator_cls = jsonschema.validators.validator_for(schema)
                validator_cls.check_schema(schema)
                for issue in sorted(
                    validator_cls(schema).iter_errors(data),
                    key=lambda err: list(err.absolute_path),
                ):
                    location = ".".join(str(part) for part in issue.absolute_path) or "<root>"
                    errors.append(f"requirements.yaml schema: {location}: {issue.message}")
            except jsonschema.exceptions.SchemaError as exc:
                errors.append(f"docs/req/req-schema.json: invalid schema: {exc.message}")
    # Manual checks run on both paths: they cover the ID/field contracts a
    # generic JSON Schema cannot express (unique IDs, prefix consistency).
    errors.extend(_manual_requirement_errors(data))


def check_trace_matrix(errors: list[str], warnings: list[str]) -> None:
    path = ROOT / "docs/architecture/trace-matrix.md"
    if not path.is_file():
        return  # already a required-path failure
    text = path.read_text(encoding="utf-8", errors="replace")
    requirements = _load_yaml("docs/req/requirements.yaml", [])
    known = set()
    if isinstance(requirements, dict) and isinstance(requirements.get("requirements"), list):
        known = {
            req.get("id") for req in requirements["requirements"]
            if isinstance(req, dict) and isinstance(req.get("id"), str)
        }
    referenced = set(re.findall(r"\b(?:FR|NFR)-[0-9]{3}\b", text))
    for rid in sorted(referenced - known):
        errors.append(f"docs/architecture/trace-matrix.md: unresolved requirement id {rid}")
    missing = sorted(known - referenced)
    if missing:
        warnings.append(
            "trace matrix does not mention requirement id(s): " + ", ".join(missing)
        )
    # Only repository-relative paths under a real top-level directory are
    # resolved. This deliberately skips the matrix's documented ``.../`` prefix
    # shorthand, branch names such as ``fix/cs5351-final-submission``, and bare
    # basenames used as abbreviations.
    known_roots = {
        "tradingagents", "cli", "tests", "test", "docs", "scripts", "prompts",
        "transcripts", "src", "token_benchmarks", "assets", ".github", ".agent",
        ".opencode",
    }
    for raw in re.findall(r"`([^`]+)`", text):
        ref = raw.strip()
        if (
            not ref
            or ref.startswith(".../")
            or "://" in ref
            or " " in ref
            or any(ch in ref for ch in "*?{}")
            or "/" not in ref
            or ref.split("/", 1)[0] not in known_roots
        ):
            continue
        ref = ref.split("::", 1)[0].split("#", 1)[0].rstrip(":,")
        if not ref or (ROOT / ref).exists():
            continue
        if ref.startswith("transcripts/") and ref not in {
            TRANSCRIPT_README, TRANSCRIPT_TEMPLATE
        }:
            warnings.append(
                f"trace matrix names a human-pending transcript path: {ref} "
                "(PENDING_HUMAN_CONFIRMATION)"
            )
        else:
            errors.append(f"docs/architecture/trace-matrix.md: unresolved path {ref}")


def check_prompts(errors: list[str]) -> None:
    for rel in PROMPT_FILES:
        if not (ROOT / rel).is_file():
            continue
        data = _load_yaml(rel, errors)
        if data is None:
            continue
        for key in ("version", "source_commit"):
            value = _find_key(data, key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{rel}: missing or empty {key!r}")


def check_adrs(errors: list[str]) -> None:
    adr_dir = ROOT / "docs/architecture/adr"
    if not adr_dir.is_dir():
        return
    seen: dict[str, str] = {}
    for path in sorted(adr_dir.glob("*.md")):
        match = re.match(r"(\d{3,})", path.name)
        if not match:
            errors.append(f"docs/architecture/adr/{path.name}: filename has no numeric id")
            continue
        number = match.group(1)
        if number in seen:
            errors.append(
                f"duplicate ADR id {number}: {path.name} and {seen[number]}"
            )
        else:
            seen[number] = path.name


def check_secrets(errors: list[str]) -> None:
    files: list[Path] = []
    for rel in SCAN_PATHS:
        path = ROOT / rel
        if path.is_file():
            files.append(path)
    for tree in SCAN_TREES:
        base = ROOT / tree
        if base.is_dir():
            files.extend(
                path for path in base.rglob("*")
                if path.is_file() and path.suffix in {".md", ".yaml", ".yml", ".json", ".jsonc"}
            )
    seen: set[Path] = set()
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            errors.append(f"{_rel(path)}: cannot read for secret scan: {exc}")
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    # Never echo the matched value.
                    errors.append(f"{_rel(path)}:{lineno}: possible {label}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    present = check_required(errors, warnings)
    check_parsing(errors, warnings)
    check_requirements(errors, warnings)
    check_trace_matrix(errors, warnings)
    check_prompts(errors)
    check_adrs(errors)
    check_secrets(errors)

    print("== required artifacts ==")
    print(f"required artifacts: {present}/{len(REQUIRED)} present and non-empty")
    print("== checks ==")
    print(
        "YAML/JSONC parsed; requirements validated; trace matrix checked; "
        "prompts checked; ADRs checked; documentation scanned for secrets"
    )
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        print(f"FAIL: {len(errors)} error(s)")
        for error in errors:
            print(f"  ERROR: {error}")
        return 1
    print("PASS: submission compliance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
