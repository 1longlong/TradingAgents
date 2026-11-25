"""Executable governance checks and transcript export.

Contract: docs/code-governance/verification-constraints.md.
This module inspects data and Git history; it never executes registry commands.
Semantic checks fail closed on absent policy or candidate evidence (ADR-030 / INV-29).
Prior test-plan reviews are verified separately from native merge reviews; no approval is issued.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import importlib.metadata
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any

import json5
import yaml
from jsonschema import Draft202012Validator

from scripts.validate.validate_requirements import validate_canonical_semantics

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


class GateError(ValueError):
    """An actionable verification failure, never an implicit exemption."""


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate YAML keys instead of silently taking the last value."""


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        parsed = loader.construct_object(key, deep=deep)
        if parsed in result:
            raise GateError(f"Duplicate YAML key: {parsed!r}")
        result[parsed] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def load_yaml(text: str) -> Any:
    try:
        return yaml.load(text, Loader=UniqueLoader)
    except yaml.YAMLError as exc:
        raise GateError(f"Invalid YAML: {exc}") from exc


def local_path(root: Path, value: str) -> Path:
    """Resolve a repository-relative path without escapes or symlink traversal."""
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise GateError(f"Not a repository-relative path: {value!r}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise GateError(f"Path escapes repository: {value!r}")
    return resolved


def validate_registry(root: Path) -> dict:
    """Validate shape, identifiers, dependencies, and explicit file references."""
    schema = json.loads((root / "docs/req/req-schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    data = load_yaml((root / "docs/req/requirements.yaml").read_text())
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: str(e.path))
    if errors:
        details = "\n".join(f"{list(e.path)}: {e.message}" for e in errors[:12])
        raise GateError(f"Requirements registry is incomplete or invalid:\n{details}")
    seen: set[str] = set()
    criteria: set[str] = set()
    for req in data["requirements"]:
        if req["id"] in seen:
            raise GateError(f"Duplicate requirement ID: {req['id']}")
        seen.add(req["id"])
        for fit in req["fit_criteria"]:
            if fit["id"] in criteria:
                raise GateError(f"Duplicate acceptance criterion ID: {fit['id']}")
            criteria.add(fit["id"])
        for source in req["sources"]:
            if (source["kind"] in {"repository", "process_document"} and
                    not local_path(root, source["reference"]).is_file()):
                raise GateError(f"Missing requirement source: {source['reference']}")
        for ref in req.get("architecture_refs", []):
            p = local_path(root, ref.split("#", 1)[0])
            if not p.is_file() or not p.read_text().strip():
                raise GateError(f"Missing/empty architecture reference: {ref}")
        invariants = (root / "docs/architecture/invariants.md").read_text()
        for ref in req.get("invariant_refs", []):
            if not re.search(rf"\b{re.escape(ref)}\b", invariants):
                raise GateError(f"Unknown invariant reference: {ref}")
        if req["status"] in {"implemented", "verified"}:
            for fit in req["fit_criteria"]:
                for evidence in fit["verification"]["evidence"]:
                    if not local_path(root, evidence.split("::", 1)[0]).is_file():
                        raise GateError(f"Missing evidence: {evidence}")
    graph = {r["id"]: r.get("depends_on", []) for r in data["requirements"]}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node):
        if node not in seen:
            raise GateError(f"Unknown requirement dependency: {node}")
        if node in visiting:
            raise GateError(f"Requirement dependency cycle at {node}")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit(dependency)
        visiting.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    semantic_errors = validate_canonical_semantics(data)
    if semantic_errors:
        raise GateError("Requirements semantic validation failed: " + "; ".join(semantic_errors))
    return data


def permission_effect(config: dict, role: str, tool: str, resource: str) -> str:
    """Evaluate the ordered V1 policy represented by this project configuration."""
    effect = "deny"
    for policy in [config["permission"], config["agent"][role].get("permission", {})]:
        value = policy.get(tool, policy.get("*"))
        if isinstance(value, str):
            effect = value
        elif isinstance(value, dict):
            for pattern, action in value.items():
                # V1 Read/Edit use canonical slashless paths; this models the same
                # repository-relative rights after the explicit launch-root binding.
                if tool in {"read", "edit"}:
                    pattern = pattern.removeprefix("{env:TRADINGAGENTS_PERMISSION_ROOT}/")
                if fnmatch.fnmatchcase(resource, pattern):
                    effect = action
    return effect


def validate_permissions(root: Path) -> None:
    config = json5.loads((root / ".opencode/permissions.jsonc").read_text())
    if config.get("default_agent") != "plan" or config["permission"].get("*") != "deny":
        raise GateError("Permissions must default to Plan and deny unknown actions")
    for role in ["plan", "build", "verify", "docs"]:
        if role not in config["agent"]:
            raise GateError(f"Missing role: {role}")
        for tool, resource in [("read", ".env"), ("read", "src/private.key"),
                               ("read", "not-allowlisted.txt"), ("edit", ".opencode/rules.md"),
                               ("edit", ".opencode/permissions.jsonc"),
                               ("task", "general"), ("external_directory", "/outside/project/")]:
            if permission_effect(config, role, tool, resource) != "deny":
                raise GateError(f"Unsafe permission: {role} {tool} {resource}")
    for role in ["plan", "verify"]:
        for path in ["src/new.py", "test/offline/test_new.py", "docs/req/requirements.yaml"]:
            if permission_effect(config, role, "edit", path) != "deny":
                raise GateError(f"Read-only role {role} may edit {path}")
    for path in ["src/tradingagents/portfolio.py", "src/cli/main.py", "pyproject.toml"]:
        if permission_effect(config, "build", "edit", path) not in {"ask", "deny"}:
            raise GateError(f"Protected Build path is not guarded: {path}")


def structural_checks(root: Path) -> None:
    """Check layout, permission boundaries, and core-to-presentation imports."""
    for name in ["tradingagents", "cli", "tests", "demo", "src/demo"]:
        if (root / name).exists():
            raise GateError(f"Unexpected obsolete source directory: {name}")
    for name in ["src/tradingagents", "src/cli", "test/offline", "test/live"]:
        if not (root / name).is_dir():
            raise GateError(f"Missing source/test directory: {name}")
    forbidden = {"cli", "fastapi", "starlette", "flask", "django"}
    for p in (root / "src/tradingagents").rglob("*.py"):
        for node in ast.walk(ast.parse(p.read_text(), filename=str(p))):
            names = []
            if isinstance(node, ast.Import):
                names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                names = [node.module]
            if any(name.split(".")[0] in forbidden for name in names):
                raise GateError(f"Core imports presentation layer: {p.relative_to(root)}")
    validate_permissions(root)


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    if result.returncode:
        raise GateError(f"Git inspection failed: {result.stderr.strip()}")
    return result.stdout


def canonical_name(path: str) -> str:
    """Recognize the approved mechanical source/test relocation."""
    if path.startswith(("tradingagents/", "cli/")) or path == "main.py":
        return "src/" + path
    if path.startswith("tests/"):
        name = path.removeprefix("tests/")
        if name.startswith("trading/live/"):
            return "test/live/trading/" + name.removeprefix("trading/live/")
        if name in {"conftest.py", "__init__.py"}:
            return "test/" + name
        if name == "test_no_data_handling.py":
            return "test/live/" + name
        return "test/offline/" + name
    return path


def tree(root: Path, ref: str) -> dict[str, str]:
    result = {}
    for line in git(root, "ls-tree", "-rz", "--full-tree", ref).split("\0"):
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        _, kind, digest = metadata.split()
        if kind == "blob":
            name = canonical_name(path)
            if name in result:
                raise GateError(f"Duplicate logical source after relocation: {name}")
            result[name] = digest
    return result


def blob(root: Path, ref: str, path: str) -> str:
    return git(root, "show", f"{ref}:{path}")


def changes(root: Path, base: str, head: str) -> set[str]:
    left, right = tree(root, base), tree(root, head)
    return {p for p in left.keys() | right.keys() if left.get(p) != right.get(p)}


def check_ai_log(root: Path, base: str, head: str) -> None:
    changed = changes(root, base, head)
    covered = {p for p in changed if p.startswith(("src/", "test/", "prompts/", ".github/"))
               or p == "pyproject.toml"}
    if not covered:
        return
    path = "docs/ai-use-log.yaml"
    if path not in changed:
        raise GateError("Code/prompt/tooling changes must update docs/ai-use-log.yaml")
    current = load_yaml(blob(root, head, path))
    if not isinstance(current, dict) or not isinstance(current.get("entries"), list):
        raise GateError("AI-use log must have an entries list")
    try:
        previous = load_yaml(blob(root, base, path)) or {}
    except GateError:
        previous = {}
    # Release history used a top-level list; the WebUI uses an entries envelope.
    # Read either base representation without exempting new candidate records.
    prior_entries = previous.get("entries", []) if isinstance(previous, dict) else previous
    if not isinstance(prior_entries, list):
        raise GateError("Previous AI-use log must contain an entry list")
    prior = {e.get("id") for e in prior_entries if isinstance(e, dict)}
    entries = current["entries"]
    identifiers = [e.get("id") for e in entries if isinstance(e, dict)]
    if len(identifiers) != len(entries) or len(identifiers) != len(set(identifiers)):
        raise GateError("AI-use log needs unique entry IDs")
    paths: set[str] = set()
    for entry in entries:
        if entry.get("id") in prior:
            continue
        for field in ["id", "date", "tool", "purpose", "human_review"]:
            if not entry.get(field):
                raise GateError(f"AI-use entry lacks {field}")
        if not isinstance(entry.get("paths"), list):
            raise GateError("AI-use entries need explicit paths")
        paths.update(entry["paths"])
    if covered - paths:
        raise GateError(f"New AI-use entries do not cover: {sorted(covered - paths)}")


# NFR-GOV-001 / INV-28 / ADR-029: this module verifies, never issues, approval.
TEST_APPROVAL_POLICY_VERSION = 1
TEST_APPROVAL_BOOTSTRAP_BASE = "ac47e1f07bcf13508be83b4f6276afc80cc449a5"
_APPROVAL_BODY = re.compile(
    r"Test plan approved for commit ([0-9a-f]{40})\.\r?\n"
    r"Scope: ([A-Za-z0-9][A-Za-z0-9 ._-]{0,159})\s*"
)
_APPROVAL_BOOTSTRAP_FILES = {
    "AGENTS.md", "README.md", "architecture-blueprint.md", "pyproject.toml",
    "test/ci_gates.py", "test/offline/test_ci_gates.py", "test/offline/test_governance_scaffold.py",
    ".github/workflows/ci.yml",
    "docs/req/requirements.yaml", "docs/architecture/adr/029-test-plan-approval.md",
    "docs/architecture/invariants.md", "docs/architecture/trace-matrix.md",
    "docs/architecture/permission-model.md", "docs/architecture/runtime-policy-catalog.md",
    "docs/code-governance/verification-constraints.md", "docs/code-governance/ci-gate-matrix.md",
    "docs/code-governance/mcp-tool-manifest.md", "docs/review-memo.md", "docs/ai-use-log.yaml",
    "docs/architecture/evaluation-logbook.md", "docs/architecture/risk-list.md", "docs/debt-register.md",
}


def approval_test_path(path: str) -> bool:
    """Include fixtures/config and colocated frontend tests; exclude the verifier."""
    frontend = "src/tradingagents_web/frontend/"
    return ((path.startswith("test/") and path != "test/ci_gates.py")
            or path.startswith((frontend + "tests/", frontend + "e2e/"))
            or path in {frontend + "src/test-setup.ts", frontend + "vitest.config.ts",
                        frontend + "playwright.config.ts"})


def _approval_toml(root: Path, ref: str) -> dict:
    data = tomllib.loads(blob(root, ref, "pyproject.toml"))
    if not isinstance(data, dict):
        raise GateError("Invalid test approval policy document")
    return data


def read_test_approval_policy(root: Path, ref: str) -> set[int]:
    """Trust the base's explicit human database IDs, never head-provided authority."""
    policy = _approval_toml(root, ref).get("tool", {}).get("tradingagents", {}).get(
        "ci", {}).get("test_approval")
    if (not isinstance(policy, dict) or set(policy) != {"version", "reviewer_ids"}
            or type(policy.get("version")) is not int or policy["version"] != 1):
        raise GateError("Missing or unsupported test approval policy")
    reviewers = policy.get("reviewer_ids")
    if (not isinstance(reviewers, list) or not reviewers
            or any(type(item) is not int or item <= 0 for item in reviewers)
            or len(set(reviewers)) != len(reviewers)):
        raise GateError("Test approval policy requires unique human reviewer IDs")
    return set(reviewers)


def _approval_configuration(root: Path, ref: str) -> dict:
    """Test configuration is review-bound separately from executable configuration."""
    data = _approval_toml(root, ref)
    data.get("tool", {}).pop("pytest", None)
    return data


def approval_implementation_change(root: Path, left: str, right: str, base: str) -> bool:
    baseline, current = tree(root, base), tree(root, right)
    for path in changes(root, left, right):
        # Incoming trusted base content is not newly introduced PR implementation.
        if current.get(path) == baseline.get(path) or approval_test_path(path):
            continue
        if path == "pyproject.toml":
            if _approval_configuration(root, left) != _approval_configuration(root, right):
                return True
        elif (path.startswith(("src/", "scripts/", "prompts/", ".github/workflows/", ".github/actions/"))
              or path in {"test/ci_gates.py", ".env.example", ".env.enterprise.example",
                          "Dockerfile", "docker-compose.yml", "requirements.txt", "setup.py",
                          "setup.cfg", "Makefile", ".dockerignore"}):
            return True
    return False


def _approval_contract(value):
    """Do not turn verification/status bookkeeping into a new acceptance contract."""
    if isinstance(value, dict):
        return {key: _approval_contract(item) for key, item in value.items()
                if key not in {"status", "source_status", "verification_evidence"}}
    if isinstance(value, list):
        return [_approval_contract(item) for item in value]
    return value


def approval_snapshot(root: Path, ref: str) -> dict[str, str]:
    snapshot = {path: digest for path, digest in tree(root, ref).items()
                if approval_test_path(path) or path == "architecture-blueprint.md"}
    paths = tree(root, ref)
    if "docs/req/requirements.yaml" in paths:
        contract = _approval_contract(load_yaml(blob(root, ref, "docs/req/requirements.yaml")))
        snapshot["docs/req/requirements.yaml"] = hashlib.sha256(
            json.dumps(contract, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    tests_config = _approval_toml(root, ref).get("tool", {}).get("pytest", {})
    snapshot["pyproject.toml::pytest"] = hashlib.sha256(
        json.dumps(tests_config, sort_keys=True).encode()).hexdigest()
    return snapshot


def _approval_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Missing timestamp")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Timestamp needs a timezone")
    return result


def _approval_ancestor(root: Path, earlier: str, later: str) -> bool:
    result = subprocess.run(["git", "merge-base", "--is-ancestor", earlier, later],
                            cwd=root, capture_output=True, check=False)
    if result.returncode not in {0, 1}:
        return False
    return result.returncode == 0


def _approval_review(root: Path, base: str, head: str, record: dict, reviewers: set[int]):
    """A dedicated COMMENTED review survives normal stale merge-approval dismissal."""
    author = record.get("author") or {}
    body = record.get("body")
    match = _APPROVAL_BODY.fullmatch(body) if isinstance(body, str) else None
    if (record.get("state") != "COMMENTED" or author.get("__typename") != "User"
            or type(author.get("databaseId")) is not int or author["databaseId"] not in reviewers
            or not match or (record.get("commit") or {}).get("oid") != match[1]):
        return None
    ref = match[1]
    # A release advance must not erase genuine reviews on the PR's own ancestry.
    if _approval_ancestor(root, ref, base) or not _approval_ancestor(root, ref, head):
        return None
    try:
        effective_at = max(_approval_time(record.get("submittedAt")), _approval_time(record.get("updatedAt")))
        committed_at = _approval_time(git(root, "show", "-s", "--format=%cI", ref).strip())
        if effective_at < committed_at:
            return None
        parents = git(root, "show", "-s", "--format=%P", ref).split()
        if not parents or approval_implementation_change(root, parents[0], ref, base):
            return None
        return {"commit": ref, "at": effective_at, "snapshot": approval_snapshot(root, ref),
                "reviewer": author.get("login", ""), "scope": match[2], "url": record.get("url", "")}
    except (GateError, ValueError, TypeError):
        return None


def check_prior_test_approval(root: Path, base: str, head: str, pr: dict,
                              reviews: list[dict], reviewers: set[int]) -> dict:
    """Validate all implementation epochs and the final review-bound snapshot."""
    if pr.get("baseRefOid") != base or pr.get("headRefOid") != head or pr.get("state") != "OPEN":
        raise GateError("PR base/head changed or PR is not open; rerun its current checks")
    commits = git(root, "rev-list", "--reverse", "--topo-order", f"{base}..{head}").splitlines()
    if len(commits) > 1000:
        raise GateError("Test approval history exceeds the bounded review scope")
    implementation = []
    for ref in commits:
        parents = git(root, "show", "-s", "--format=%P", ref).split()
        if parents and approval_implementation_change(root, parents[0], ref, base):
            implementation.append(ref)
    if not implementation:
        return {"status": "not_required", "reviews": [], "implementation_commits": []}
    approved = [item for record in reviews
                if (item := _approval_review(root, base, head, record, reviewers)) is not None]
    used = {}
    for ref in implementation:
        snapshot = approval_snapshot(root, ref)
        committed_at = _approval_time(git(root, "show", "-s", "--format=%cI", ref).strip())
        match = next((item for item in approved if item["snapshot"] == snapshot
                      and item["at"] < committed_at
                      and _approval_ancestor(root, item["commit"], ref)
                      and item["commit"] != ref), None)
        if match is None:
            raise GateError(f"Missing prior test approval for implementation commit {ref[:12]}")
        used[match["commit"]] = match
    final = next((item for item in approved if item["snapshot"] == approval_snapshot(root, head)), None)
    if final is None:
        raise GateError("Final tests/design changed without a matching test approval")
    used[final["commit"]] = final
    return {"status": "approved", "implementation_commits": implementation,
            "reviews": [{key: value for key, value in item.items() if key != "snapshot"}
                        for item in used.values()]}


_REVIEW_QUERY = """query($owner:String!,$name:String!,$number:Int!,$cursor:String) {
  repository(owner:$owner,name:$name) {
    pullRequest(number:$number) {
      number state baseRefOid headRefOid
      reviews(first:100,after:$cursor) {
        nodes { state body submittedAt updatedAt url commit { oid }
          author { __typename login ... on User { databaseId } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}"""


class _ApprovalNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise GateError("GitHub review API redirected unexpectedly")


def github_review_query(query: str, variables: dict, token: str) -> dict:
    """Read only GitHub metadata; never include transport payloads or credentials in errors."""
    if not token:
        raise GateError("GitHub review token is unavailable")
    request = urllib.request.Request("https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "Accept": "application/vnd.github+json", "User-Agent": "TradingAgents-test-approval"},
        method="POST")
    try:
        with urllib.request.build_opener(_ApprovalNoRedirect()).open(request, timeout=30) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or payload.get("errors") or not isinstance(payload.get("data"), dict):
            raise GateError("GitHub review API returned incomplete evidence")
        return payload["data"]
    except (OSError, ValueError) as exc:
        if isinstance(exc, GateError):
            raise
        raise GateError("GitHub review API unavailable; approval cannot be verified") from exc


def fetch_test_plan_reviews(repository: str, number: int, base: str, head: str, token: str):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or type(number) is not int or number <= 0:
        raise GateError("Invalid PR repository or number")
    owner, name = repository.split("/")
    cursor = None
    seen = set()
    records = []
    for _ in range(20):
        data = github_review_query(_REVIEW_QUERY,
            {"owner": owner, "name": name, "number": number, "cursor": cursor}, token)
        pr = (data.get("repository") or {}).get("pullRequest")
        if (not isinstance(pr, dict) or pr.get("number") != number or pr.get("state") != "OPEN"
                or pr.get("baseRefOid") != base or pr.get("headRefOid") != head):
            raise GateError("PR metadata is missing or base/head changed")
        page = pr.get("reviews") or {}
        nodes, info = page.get("nodes"), page.get("pageInfo") or {}
        if not isinstance(nodes, list) or any(not isinstance(item, dict) for item in nodes):
            raise GateError("GitHub review API returned invalid review data")
        records.extend(nodes)
        if info.get("hasNextPage") is False:
            return pr, records
        cursor = info.get("endCursor")
        if info.get("hasNextPage") is not True or not cursor or cursor in seen:
            raise GateError("GitHub review pagination is incomplete")
        seen.add(cursor)
    raise GateError("GitHub review pagination limit exceeded; no approval inferred")


def _approval_checker_present(root: Path, ref: str) -> bool:
    try:
        source = ast.parse(blob(root, ref, "test/ci_gates.py"))
    except SyntaxError as exc:
        raise GateError("Invalid test approval checker syntax") from exc
    return any(isinstance(node, ast.Assign) and any(isinstance(target, ast.Name)
               and target.id == "TEST_APPROVAL_POLICY_VERSION" for target in node.targets)
               and isinstance(node.value, ast.Constant) and type(node.value.value) is int
               and node.value.value == 1 for node in source.body)


def check_test_approval_bootstrap(root: Path, base: str, head: str) -> dict:
    """A single disclosed governance installation, never a historical approval verdict."""
    changed = changes(root, base, head)
    if base != TEST_APPROVAL_BOOTSTRAP_BASE or changed - _APPROVAL_BOOTSTRAP_FILES:
        raise GateError("Test approval bootstrap cannot include business or unrelated changes")
    before, after = _approval_toml(root, base), _approval_toml(root, head)
    before.get("tool", {}).get("tradingagents", {}).get("ci", {}).pop("test_approval", None)
    after.get("tool", {}).get("tradingagents", {}).get("ci", {}).pop("test_approval", None)
    if before != after or read_test_approval_policy(root, head) != {66710554} or not _approval_checker_present(root, head):
        raise GateError("Invalid or widened test approval bootstrap policy/configuration")
    previous = load_yaml(blob(root, base, ".github/workflows/ci.yml"))
    candidate = load_yaml(blob(root, head, ".github/workflows/ci.yml"))
    for workflow in (previous, candidate):
        workflow.get("jobs", {}).pop("review-and-log", None)
    if previous != candidate:
        raise GateError("Test approval bootstrap must preserve all other workflow gates")
    return {"status": "bootstrap", "reviews": [], "implementation_commits": []}


def run_test_approval(root: Path, base: str, head: str) -> None:
    """CLI adapter; evidence is server-backed, policy and checker are base-owned."""
    base_config = _approval_toml(root, base).get("tool", {}).get("tradingagents", {}).get("ci", {})
    if "test_approval" not in base_config and not _approval_checker_present(root, base):
        check_test_approval_bootstrap(root, base, head)
        print("::notice title=Test approval installation::BOOTSTRAP: reviewed governance installation "
              "from the named legacy base; enforcement starts after merge. This is not a GitHub test-plan approval.")
        return
    reviewers = read_test_approval_policy(root, base)
    read_test_approval_policy(root, head)
    if not _approval_checker_present(root, head):
        raise GateError("Candidate removes the test approval checker")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise GateError("A real PR event is required for test approval")
    event = json.loads(Path(event_path).read_text())
    number = event.get("pull_request", {}).get("number")
    if type(number) is not int:
        raise GateError("A real PR number is required for test approval")
    pr, reviews = fetch_test_plan_reviews(os.environ.get("GITHUB_REPOSITORY", ""), number,
                                        base, head, os.environ.get("GITHUB_TOKEN", ""))
    result = check_prior_test_approval(root, base, head, pr, reviews, reviewers)
    if result["status"] == "not_required":
        print("Test approval: NOT REQUIRED (test/document preparation only; no approval issued)")
        return
    print("PASS: prior test approval")
    for review in result["reviews"]:
        print(json.dumps({"commit": review["commit"], "reviewer": review["reviewer"],
                          "approved_at": review["at"].isoformat(), "review_url": review["url"]}))


def semantic_needed(root: Path, base: str, head: str) -> bool:
    changed = changes(root, base, head)
    prefixes = ("src/tradingagents/agents/", "src/tradingagents/llm_clients/")
    for path in changed:
        if path.startswith(prefixes) or path in {"src/tradingagents/default_config.py",
                                               "src/tradingagents/graph/reflection.py",
                                               "src/tradingagents/graph/trading_graph.py"}:
            return True
        if path.startswith("prompts/"):
            for ref in [base, head]:
                try:
                    if blob(root, ref, path).strip():
                        return True
                except GateError:
                    pass
    return False


def semantic_source_digest(root: Path, ref: str) -> str:
    """ADR-030 / INV-29: bind evidence to candidate source, prompts and runtime config."""
    relevant = {path: digest for path, digest in tree(root, ref).items()
                if (path.startswith("src/") and path.endswith(".py"))
                or path.startswith("prompts/") or path in {"pyproject.toml", "requirements.txt"}}
    payload = "".join(f"{path}\0{digest}\n" for path, digest in sorted(relevant.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def check_semantic(root: Path, base: str, head: str) -> bool:
    """Replay an evaluator and dataset approved on the base, with Python sockets disabled."""
    if not semantic_needed(root, base, head):
        print("Semantic evaluation: NOT REQUIRED (no runtime prompt/model change)")
        return False
    policy = tomllib.loads(blob(root, base, "pyproject.toml")).get("tool", {}).get(
        "tradingagents", {}).get("ci", {}).get("semantic_evaluation", {})
    if not isinstance(policy, dict):
        raise GateError("Semantic evaluation policy must be a table")
    if not policy:
        raise GateError("Prompt/model change requires a configured base semantic policy")
    if not all(policy.get(k) for k in ["evaluator", "dataset", "observations", "thresholds"]):
        raise GateError("Incomplete semantic policy: configure evaluator, dataset, observations and thresholds")
    if (not isinstance(policy["evaluator"], str) or not isinstance(policy["dataset"], str)
            or not isinstance(policy["observations"], str) or not isinstance(policy["thresholds"], dict)):
        raise GateError("Invalid semantic evaluator, dataset or thresholds")
    approved = {}
    for key in ["evaluator", "dataset"]:
        path = policy[key]
        local_path(root, path)
        approved[key] = blob(root, base, path)
        if blob(root, head, path) != approved[key]:
            raise GateError("Evaluator/dataset changes require a separate approval before use")
    cases = json.loads(approved["dataset"])
    if not isinstance(cases, list) or not cases:
        raise GateError("The fixed evaluation dataset must be a nonempty JSON list")
    digest = hashlib.sha256(approved["dataset"].encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="tradingagents-eval-") as temp:
        directory = Path(temp)
        evaluator = directory / "evaluator.py"
        dataset = directory / "dataset.json"
        output = directory / "report.json"
        evaluator.write_text(approved["evaluator"])
        dataset.write_text(approved["dataset"])
        additional = []
        source_digest = None
        if policy.get("observations"):
            local_path(root, policy["observations"])
            observations = directory / "observations.json"
            try:
                observations.write_text(blob(root, head, policy["observations"]))
            except GateError as exc:
                raise GateError("Missing authentic candidate evaluation observations") from exc
            source_digest = semantic_source_digest(root, head)
            additional = ["--observations", str(observations), "--source-sha256", source_digest]
        environment = {k: v for k, v in os.environ.items() if not re.search(
            r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE", k, re.I)}
        environment["PYTHONPATH"] = str(root / "src")
        environment["PYTHON_DOTENV_DISABLED"] = "1"
        launcher = ("import runpy,sys; from pytest_socket import disable_socket; "
                    "disable_socket(allow_unix_socket=True); "
                    "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')")
        result = subprocess.run([sys.executable, "-c", launcher, str(evaluator),
                                 "--dataset", str(dataset), *additional, "--output", str(output)],
                                cwd=directory, env=environment, capture_output=True,
                                text=True, check=False, timeout=120)
        if result.returncode or not output.is_file():
            raise GateError("Approved semantic evaluator failed or produced no report")
        report = json.loads(output.read_text())
    if not isinstance(report, dict):
        raise GateError("Semantic report must be a JSON object")
    if source_digest is not None and report.get("source_sha256") != source_digest:
        raise GateError("Semantic report does not match candidate source")
    if report.get("dataset_sha256") != digest or report.get("sample_count") != len(cases):
        raise GateError("Semantic report does not cover the exact fixed dataset")
    operators = {"eq": lambda a, b: a == b, "lte": lambda a, b: a <= b, "gte": lambda a, b: a >= b}
    for metric, rule in policy["thresholds"].items():
        if not isinstance(rule, dict) or not isinstance(report.get("metrics"), dict):
            raise GateError("Invalid semantic metric rule or report metrics")
        actual = report["metrics"].get(metric)
        expected = rule.get("threshold")
        operator_name = rule.get("comparison")
        if not isinstance(operator_name, str):
            raise GateError("Invalid semantic comparison operator")
        comparison = operators.get(operator_name)
        if (isinstance(actual, bool) or not isinstance(actual, (int, float)) or
                not math.isfinite(actual) or isinstance(expected, bool) or
                not isinstance(expected, (int, float)) or not math.isfinite(expected) or
                comparison is None or not comparison(actual, expected)):
            raise GateError(f"Semantic threshold failed or missing: {metric}")
    return True


def export_transcript(root: Path, session: str, destination: str) -> None:
    if not re.fullmatch(r"ses_[A-Za-z0-9_-]+", session):
        raise GateError("Supply an explicit OpenCode session ID")
    target = local_path(root, destination)
    if not target.is_relative_to((root / "transcripts").resolve()) or target.suffix != ".md":
        raise GateError("Transcript destination must be a Markdown file under transcripts/")
    if target.exists() or not target.parent.is_dir():
        raise GateError("Transcript export must create a new file in an existing directory")
    # Export outside the project to avoid OpenCode installing plugin SDKs here.
    with tempfile.TemporaryDirectory(prefix="tradingagents-export-") as temp:
        environment = os.environ.copy()
        environment.pop("OPENCODE_CONFIG", None)
        result = subprocess.run(["opencode", "--pure", "export", session, "--sanitize"],
                                cwd=temp, env=environment, capture_output=True, text=True,
                                check=False, timeout=60)
    if result.returncode:
        raise GateError("OpenCode session export failed; no transcript was written")
    data = json.loads(result.stdout)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    fence = "`" * max(3, max((len(x) for x in re.findall(r"`+", payload)), default=0) + 1)
    with target.open("x") as stream:
        stream.write(f"# OpenCode session {session}\n\n"
                     "Complete structured JSON returned by `opencode export --sanitize`; "
                     "native redactions are retained. This is not a reconstructed summary.\n\n"
                     f"{fence}json\n{payload}\n{fence}\n\n"
                     "## Human intervention annotations\n\n"
                     "Add authentic message references, author, time, action, and rationale. "
                     "No approval is implied by this empty annotation section.\n")


def audit_pins(distributions) -> list[str]:
    """Audit exact installed dependency versions, excluding this application."""
    versions: dict[str, str] = {}
    for distribution in distributions:
        name = distribution.metadata["Name"]
        version = distribution.version
        # Editable installs can expose both dist-info and source egg-info.
        # Neither copy of our own application is a third-party PyPI dependency.
        if name.lower() == "tradingagents":
            continue
        direct = json.loads(distribution.read_text("direct_url.json") or "{}")
        if direct.get("dir_info", {}).get("editable"):
            raise GateError(f"Unreviewed editable dependency cannot be audited: {name}")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name) or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_.+!-]*", version):
            raise GateError("Installed dependency has an invalid name/version")
        normalized = re.sub(r"[-_.]+", "-", name).lower()
        if normalized in versions and versions[normalized] != version:
            raise GateError(f"Conflicting installed dependency versions: {name}")
        versions[normalized] = version
    if not versions:
        raise GateError("No installed dependency inventory to audit")
    return [f"{name}=={version}" for name, version in sorted(versions.items())]


def audit_dependencies() -> None:
    pins = audit_pins(importlib.metadata.distributions())
    with tempfile.TemporaryDirectory(prefix="tradingagents-audit-") as temp:
        path = Path(temp) / "requirements.txt"
        path.write_text("\n".join(pins) + "\n")
        result = subprocess.run([sys.executable, "-m", "pip_audit", "--strict", "--no-deps",
                                 "--disable-pip", "--progress-spinner", "off", "-r", str(path)],
                                capture_output=True, text=True, check=False, timeout=180)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        raise GateError("Dependency audit found vulnerabilities or could not obtain complete evidence: " + result.stderr.strip())
    print(f"Audited {len(pins)} exact installed dependency versions")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", choices=["schema", "permissions", "structure", "ai-log", "approval", "semantic", "semantic-source", "transcript", "dependencies"])
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--session")
    parser.add_argument("--output")
    parser.add_argument("--repo-root", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.repo_root is not None:
            if args.gate != "approval":
                raise GateError("--repo-root is supported only for approval")
            root = args.repo_root.resolve()
        if args.gate == "schema":
            validate_registry(root)
        elif args.gate == "permissions":
            validate_permissions(root)
        elif args.gate == "structure":
            structural_checks(root)
        elif args.gate == "dependencies":
            audit_dependencies()
        elif args.gate == "semantic-source":
            ref = git(root, "rev-parse", "--verify", "--end-of-options", f"{args.head}^{{commit}}").strip()
            print(semantic_source_digest(root, ref))
            return 0
        elif args.gate == "transcript":
            if not args.session or not args.output:
                raise GateError("Transcript export needs --session and --output")
            export_transcript(root, args.session, args.output)
        else:
            if not args.base:
                raise GateError("A base commit is required; no empty baseline fallback")
            # Never pass an option-like caller string directly to later Git commands.
            args.base = git(root, "rev-parse", "--verify", "--end-of-options", f"{args.base}^{{commit}}").strip()
            args.head = git(root, "rev-parse", "--verify", "--end-of-options", f"{args.head}^{{commit}}").strip()
            if args.gate == "ai-log":
                check_ai_log(root, args.base, args.head)
            elif args.gate == "approval":
                run_test_approval(root, args.base, args.head)
                return 0
            elif args.gate == "semantic" and not check_semantic(root, args.base, args.head):
                return 0
        print(f"PASS: {args.gate}")
        return 0
    except (GateError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"BLOCKED: {args.gate}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
