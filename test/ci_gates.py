"""Executable governance checks and transcript export.

Contract: docs/code-governance/verification-constraints.md.
This module inspects data and Git history; it never executes registry commands.
Missing evidence fails closed. It does not issue human approvals.
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
import urllib.error
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


def runtime_changes(root: Path, base: str, head: str) -> set[str]:
    result = {p for p in changes(root, base, head) if p.startswith("src/")}
    for ref in [base, head]:
        git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    docs = [tomllib.loads(blob(root, ref, "pyproject.toml")) for ref in [base, head]]

    def dependencies(doc):
        project = doc.get("project", {})
        return (project.get("dependencies"), project.get("requires-python"),
                {k: v for k, v in project.get("optional-dependencies", {}).items() if k != "dev"})

    if dependencies(docs[0]) != dependencies(docs[1]):
        result.add("pyproject.toml")
    return result


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


class GitHub:
    """Read-only review metadata. Never accept local approval files as authority."""

    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise GateError("Invalid GitHub repository")
        self.repository = repository
        self.token = token

    def get(self, route):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{route}",
            headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {self.token}",
                     "User-Agent": "TradingAgents-governance"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except (urllib.error.URLError, ValueError) as exc:
            raise GateError(f"GitHub review metadata unavailable: {type(exc).__name__}") from exc

    def reviews(self, number: int):
        records = []
        for page in range(1, 101):
            batch = self.get(f"pulls/{number}/reviews?per_page=100&page={page}")
            records.extend(batch)
            if len(batch) < 100:
                return records
        raise GateError("Review pagination limit exceeded")

    def trusted(self, review: dict, author: str) -> bool:
        user = review.get("user", {})
        login = user.get("login", "")
        if user.get("type") != "User" or login.lower() == author.lower():
            return False
        permission = self.get(f"collaborators/{login}/permission").get("permission")
        return permission in {"admin", "maintain", "write"}


def is_ancestor(root: Path, earlier: str, later: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", earlier, later],
                          cwd=root, capture_output=True, check=False).returncode == 0


def check_prior_approval(root: Path, base: str, head: str, reviews: list[dict]) -> None:
    """Bind an earlier test-only reviewed tree to unchanged final test contents."""
    if not runtime_changes(root, base, head):
        return
    current = tree(root, head)
    for path in ["docs/req/requirements.yaml", "architecture-blueprint.md"]:
        if path not in current or not blob(root, head, path).strip():
            raise GateError(f"Product implementation needs a nonempty approved design artifact: {path}")
    bound = {p: h for p, h in current.items() if p.startswith("test/") or
             p in {"docs/req/requirements.yaml", "architecture-blueprint.md"}}
    for review in reviews:
        reviewed = review.get("commit_id", "")
        # A dedicated COMMENTED plan review survives automatic dismissal of
        # stale code approvals. It approves tests, not the final code merge.
        if review.get("state") not in {"COMMENTED", "APPROVED"} or "[test-plan-approved]" not in review.get("body", ""):
            continue
        if not reviewed or not is_ancestor(root, reviewed, head):
            continue
        if runtime_changes(root, base, reviewed):
            continue
        snapshot = tree(root, reviewed)
        if {p: h for p, h in snapshot.items() if p in bound or p.startswith("test/")} != bound:
            continue
        commits = git(root, "rev-list", "--reverse", f"{reviewed}..{head}").splitlines()
        first = next((c for c in commits if runtime_changes(root, base, c)), None)
        if first:
            implementation_time = datetime.fromisoformat(git(root, "show", "-s", "--format=%cI", first).strip())
            approval_time = datetime.fromisoformat(review["submitted_at"].replace("Z", "+00:00"))
            if approval_time < implementation_time:
                return
    raise GateError("Missing earlier human [test-plan-approved] review of unchanged tests/requirements/plan, before product implementation")


def check_pull_request(root: Path, base: str, head: str, number: int, client: GitHub) -> None:
    request = client.get(f"pulls/{number}")
    if request["head"]["sha"] != head or request["base"]["sha"] != base:
        raise GateError("PR changed while checking reviews; rerun at its current base/head")
    reviews = [r for r in client.reviews(number) if client.trusted(r, request["user"]["login"])]
    latest = {}
    for review in reviews:
        if review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
            latest[review["user"]["login"]] = review
    if any(r["state"] == "CHANGES_REQUESTED" for r in latest.values()):
        raise GateError("A trusted reviewer still requests changes")
    check_prior_approval(root, base, head, reviews)
    changed = changes(root, base, head)
    safety = runtime_changes(root, base, head)
    controls = any(p.startswith((".github/", ".agent/", ".opencode/")) or p in
                   {"AGENTS.md", "Prompt.md", "test/ci_gates.py", "pyproject.toml", "docs/req/req-schema.json"}
                   for p in changed)
    for required, marker in [(bool(safety), "[safety-approved]"), (controls, "[governance-approved]")]:
        if required and not any(r["state"] == "APPROVED" and r["commit_id"] == head and
                                marker in r.get("body", "") for r in latest.values()):
            raise GateError(f"Current head needs a human {marker} approval")
    if safety:
        adrs = [p for p in changed if p.startswith("docs/architecture/adr/") and p.endswith(".md")]
        if not any(len(blob(root, head, p).strip()) >= 100 and all(
                heading in blob(root, head, p) for heading in ["Context", "Decision", "Consequences"])
                for p in adrs if p in tree(root, head)):
            raise GateError("Safety-relevant changes need an accompanying ADR with Context, Decision, and Consequences")


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


def check_semantic(root: Path, base: str, head: str) -> None:
    """Replay an evaluator and dataset approved on the base, with Python sockets disabled."""
    if not semantic_needed(root, base, head):
        print("Semantic evaluation: no runtime prompt/model change")
        return
    policy = tomllib.loads(blob(root, base, "pyproject.toml")).get("tool", {}).get(
        "tradingagents", {}).get("ci", {}).get("semantic_evaluation", {})
    if not all(policy.get(k) for k in ["evaluator", "dataset", "thresholds"]):
        raise GateError("Prompt/model change blocked: no base-approved evaluator, fixed dataset, and thresholds")
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
        environment = {k: v for k, v in os.environ.items() if not re.search(
            r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|COOKIE", k, re.I)}
        environment["PYTHONPATH"] = str(root / "src")
        launcher = ("import runpy,sys; from pytest_socket import disable_socket; "
                    "disable_socket(allow_unix_socket=True); "
                    "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')")
        result = subprocess.run([sys.executable, "-c", launcher, str(evaluator),
                                 "--dataset", str(dataset), "--output", str(output)],
                                cwd=directory, env=environment, capture_output=True,
                                text=True, check=False, timeout=120)
        if result.returncode or not output.is_file():
            raise GateError("Approved semantic evaluator failed or produced no report")
        report = json.loads(output.read_text())
    if report.get("dataset_sha256") != digest or report.get("sample_count") != len(cases):
        raise GateError("Semantic report does not cover the exact fixed dataset")
    operators = {"eq": lambda a, b: a == b, "lte": lambda a, b: a <= b, "gte": lambda a, b: a >= b}
    for metric, rule in policy["thresholds"].items():
        actual = report.get("metrics", {}).get(metric)
        expected = rule.get("threshold")
        comparison = operators.get(rule.get("comparison"))
        if (isinstance(actual, bool) or not isinstance(actual, (int, float)) or
                not math.isfinite(actual) or isinstance(expected, bool) or
                not isinstance(expected, (int, float)) or not math.isfinite(expected) or
                comparison is None or not comparison(actual, expected)):
            raise GateError(f"Semantic threshold failed or missing: {metric}")


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
    versions = {}
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
    parser.add_argument("gate", choices=["schema", "permissions", "structure", "ai-log", "approval", "semantic", "transcript", "dependencies"])
    parser.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--session")
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        if args.gate == "schema":
            validate_registry(root)
        elif args.gate == "permissions":
            validate_permissions(root)
        elif args.gate == "structure":
            structural_checks(root)
        elif args.gate == "dependencies":
            audit_dependencies()
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
            elif args.gate == "semantic":
                check_semantic(root, args.base, args.head)
            else:
                event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
                request = event.get("pull_request")
                if not request:
                    # The workflow reports branch-checks, never blocking-gate,
                    # outside PR/review events. This is not merge approval.
                    print("No PR approval context: branch checks only; require the PR blocking-gate before merge")
                else:
                    client = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"])
                    check_pull_request(root, args.base, args.head, request["number"], client)
        print(f"PASS: {args.gate}")
        return 0
    except (GateError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"BLOCKED: {args.gate}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
