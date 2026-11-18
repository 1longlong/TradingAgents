# CI Gate Matrix — Implementation-Ready Design (DOCUMENT ONLY)

> **Status:** This document is a **design/specification**, not enforcement.
> Writing it here does **not** implement any gate, does not change
> `.github/workflows/ci.yml`, and does not prove branch protection. Each gate
> records two things separately: **ACTUAL status/trigger** (what the current
> workflow really does) and **TARGET contract** (what an authorized
> implementation round must build). Branch protection is `UNVERIFIED` and cannot
> be certified from local YAML.
>
> The current local validator (`scripts/validate/validate_requirements.py`) is a
> **deterministic presence/parse/schema/subset check**, not a full proof of the
> assignment's semantic criteria. Its schema enforces `fit_criterion` structure
> only when `jsonschema` is installed; the subset fallback does **not** enforce
> the per-requirement `fit_criterion`/`priority_rationale`/`tradeoff` rules.
> Passing it is necessary, not sufficient.

## ACTUAL current workflow (facts, from `.github/workflows/ci.yml`)

- Triggers: `push` on **`main` only**; `pull_request` on **all** PRs. Feature-
  branch pushes are **NOT** triggered.
- Jobs: `test` (`pytest -q`, py3.10–3.13), `smoke-install` (clean install import),
  `lint` (`ruff check .`), `governance-validation` (`validate_requirements.py`
  with `jsonschema` + `pyyaml`).
- There is **no** type check, dependency/vulnerability scan, pre-approved-test
  gate, structural/API/permission gate, prompt/model semantic eval, diff-aware
  AI-use-log gate, or branch-protection verification.
- The full `pytest -q` is **not all-green** (known date-sensitive cache +
  network-reachability baselines), so a "green gate" cannot be claimed.

Each row below states **ACTUAL trigger** (truth today) and **TARGET trigger**
(what the gate must use when implemented).

---

## Gate matrix

### G1 — Requirements schema gate

- **ACTUAL trigger:** `governance-validation` job runs on push to `main` and on
  all PRs (NOT on feature-branch pushes).
- **TARGET trigger:** on any change to `docs/req/**` for push (any branch) and
  PR.
- Inputs: `docs/req/requirements.yaml`, `docs/req/req-schema.json`.
- Check: `python scripts/validate/validate_requirements.py` with `jsonschema`
  installed (real draft-2020-12 validation). The **combined validation entry
  point** (`validate_against_schema`, and the fallback `validate_requirements`)
  additionally runs two shared semantic checks that pure JSON Schema cannot
  express: `requirements[].id` uniqueness and resolution of
  `product.priorities[].requirement_id` / `product.tradeoffs[].requirement_id`
  against the registry. These are the only reference contracts checked; the
  subset fallback still does NOT enforce the extended `fit_criterion`
  conditionals.
- Pass/fail: pass = 0 schema errors AND 0 uniqueness/dangling-reference errors
  AND 0 presence/parse/secret errors.
- Blocking: fail blocks merge (once protection is on — UNVERIFIED).
- Evidence: validator stdout (artifact count, schema result, secret scan).
- Owner: student author.
- **ACTUAL status: PARTIAL.** Presence/parse/schema runs on `main`-push + PRs;
  feature pushes not covered; subset fallback (no `jsonschema`) is weaker.

### G2 — Lint gate

- **ACTUAL trigger:** `lint` job on push to `main` and all PRs.
- **TARGET trigger:** all pushes (any branch) and PRs.
- Inputs: Python sources.
- Check: `ruff check .` (strict select from `pyproject.toml`).
- Pass/fail: pass = 0 findings.
- Blocking: fail blocks.
- Evidence: ruff output.
- Owner: student author.
- **ACTUAL status: PARTIAL** (implemented for `main`-push + PRs; feature pushes
  not covered).

### G3 — Type-check gate (TARGET; NOT INSTALLED / NOT CONFIGURED)

- **ACTUAL trigger:** none (no job).
- **TARGET trigger:** all pushes (any branch) and PRs.
- Inputs: `tradingagents/`, `cli/`.
- **Proposed exact command / config (not installed):**
  ```bash
  pip install "mypy>=1.11" "types-requests"
  mypy --strict --ignore-missing-imports tradingagents cli
  ```
  with a `[tool.mypy]` block (e.g. `python_version = "3.10"`,
  `warn_unused_ignores = true`) added in the authorized round.
- Pass/fail: pass = **0 type errors** (`mypy` exit 0). Any error blocks.
- Blocking: fail blocks.
- Evidence: mypy report artifact.
- Owner: student author.
- **ACTUAL status: MISSING — NOT INSTALLED / NOT CONFIGURED.**

### G4 — Dependency consistency / vulnerability gate

- **ACTUAL trigger:** `smoke-install` job (import-only) on `main`-push + PRs.
- **TARGET trigger:** all pushes + PRs, plus a scheduled scan.
- Inputs: `pyproject.toml`, `requirements.txt`, installed env.
- **Proposed exact commands (not installed / not configured):**
  ```bash
  pip install "pip-audit>=2.7" "deptry>=0.20"
  pip check                       # installed-env consistency (missing/mismatched deps)
  deptry .                        # declared-vs-imported dependency scanner
  pip-audit --strict --desc on    # vulnerability scan
  python -c "import tradingagents, cli.main"   # import smoke (NOT sufficient alone)
  ```
- **Why the import smoke alone is insufficient:** a bare `python -c "import ..."`
  can pass because a **transitive** dependency happens to be installed, masking
  an undeclared direct dependency. `pip check` catches installed-env
  inconsistencies and `deptry` catches imports not declared in
  `pyproject.toml`; both are required.
- Pass/fail:
  - `pip check` reports any inconsistency → **fail** (blocking).
  - `deptry .` reports any **undeclared** (or otherwise inconsistent) dependency
    → **fail** (blocking), except for a **human-approved scoped false-positive
    config** (a named, reviewed ignore list with justification; not a blanket
    suppression).
  - any **high/critical** vulnerability → **fail (blocking)** **unless** a
    reviewed waiver exists (see Waiver rule). Medium/low: advisory only.
- **Waiver rule (mandatory):** a vulnerability exception is a **reviewed waiver**
  recording the advisory id, justification, owner, and an **expiry date**; an
  expired waiver becomes blocking again. No open-ended "advisory-only" for
  high/critical.
- Blocking: as above.
- Evidence: audit report + waiver file (if any) + smoke log.
- Owner: student author (waiver also requires human reviewer sign-off).
- **ACTUAL status: PARTIAL — import smoke only; audit MISSING.**

### G5 — Pre-approved test gate (approval must PREDATE implementation)

- **ACTUAL trigger:** none.
- **TARGET trigger:** every PR that changes feature code or tests.
- Inputs: the PR's tests, the **approval record**, the approved plan/test
  revision hashes.
- **Check contract (must prove approval PRECEDES implementation, tamper-evidently):**
  - **Commit timestamps and self-authored YAML actor names are NOT tamperproof.**
    A local `git commit` timestamp can be set arbitrarily, and a name written in
    a YAML/markdown "approval" can be authored by the agent itself. Neither alone
    proves a human approved before code existed.
  - Target provenance must be **genuine platform/human approval provenance**:
    e.g. a platform record (PR review approval / signed commit / server-side
    approval event) tied to (a) the **approved plan/test-case revision** (content
    hash) and (b) an **external/server-side timestamp** that is not settable by
    the authoring agent.
  - The gate requires: the approval is a real human review (not the authoring
    agent; not a self-approval), bound to the approved revision hash, with an
    external timestamp **strictly before** the first implementation of those
    tests, and the approved revision hash **matches** what is implemented (a
    post-approval test change requires reapproval).
  - **Reject (fail closed) on missing or ambiguous provenance:** no external
    approval event; approval actor equals the authoring agent; approval before/after
    ordering unprovable; hash missing/mismatched; local-timestamp-only proof.
- Pass/fail: pass only with verifiable external human approval bound to the
  approved revision, ordered before implementation, hash-matched. Otherwise
  **fail (blocking)**.
- Blocking: fail blocks.
- Evidence: external approval record + revision hash comparison + external
  timestamps.
- Owner: human reviewer + student author.
- **Do not invent retrospective preapproval:** no prior 2026-11-06 work is
  backfilled with a fabricated pre-approval; old work remains "awaiting human
  review" as already recorded.
- **ACTUAL status: MISSING — NOT IMPLEMENTED.**

### G6 — Structural / API / security / permission-change gate

- **ACTUAL trigger:** none.
- **TARGET trigger:** PRs touching `docs/architecture/**`, `adr/**`,
  `.opencode/**`, `.agent/**`, permission files, or public API signatures.
- Inputs: changed paths + API surface diff.
- Check: path-based detection; require an ADR + human approval for
  safety-critical paths (per `structural-constraints.md`); flag permission/API
  diffs for mandatory human review.
- Pass/fail: pass = required ADR/approval present AND flagged diffs reviewed.
- Blocking: fail blocks.
- Evidence: changed-path report + ADR link + review decision.
- Owner: human reviewer.
- **ACTUAL status: MISSING — NOT IMPLEMENTED.**

### G7 — Fixed-set prompt / model semantic evaluation gate (TARGET; PROPOSED)

- **ACTUAL trigger:** none.
- **TARGET trigger:** PRs touching `prompts/**` or model/prompt behavior.
- **Fixed-set manifest / case / version contract (proposed):**
  - A versioned manifest, e.g. `evaluation/prompt-eval/manifest.yaml` with
    `eval_set_version`, and a fixed case list. Each case records: input identity,
    the expected structured outcome (stop_reason / route / blocked-Hold / quality
    verdict), and whether it is a positive or negative scenario.
  - **Required coverage (minimum):** **≥ 3 positive** and **≥ 3 negative**
    scenarios across the gate and debate, including at least one blocked-Hold
    case and at least one genuine stop_reason case (e.g. `no_new_evidence`,
    `budget_exhausted`).
  - The manifest pins `prompt_version` and event/evaluator `policy_version` so a
    prompt change is evaluated against the same set.
- **Thresholds (PROPOSED — awaiting human approval; not benchmark results):**
  - **Zero-tolerance:** **0 safety escapes** (a blocked run that is not Hold; a
    fail-open on missing/error).
  - **100% exact required cases:** every required structured outcome (blocked →
    Hold; required stop_reason; required route) matches exactly.
  - **No regression** vs an **approved quality baseline** (the approved baseline
    is a human-approved artifact; a candidate must be ≥ baseline on every
    required metric).
- **Fail-closed when inputs are missing:** if the eval set, the threshold, the
  approved baseline, or the human approval is missing/unparseable → the gate
  **fails closed (blocking)** and reports which input is missing. It never
  defaults to pass.
- Blocking: fail blocks.
- Evidence: per-case result table + aggregate + baseline diff + threshold.
- Owner: student author; thresholds/baseline require human approval.
- **ACTUAL status: MISSING — NOT IMPLEMENTED; thresholds/baseline are PROPOSED,
  not measured.**

### G8 — Negative / invariant regression gate

- **ACTUAL trigger:** `test` job runs `pytest -q` (not all-green) on
  `main`-push + PRs.
- **TARGET trigger:** all pushes + PRs.
- Inputs: tests.
- Check: run invariant-violating negative tests (fail-closed, look-ahead, budget,
  allowlist) as a distinct named set + the full prior regression suite.
- Pass/fail: **pass = zero test failures and pytest exits 0.** A **nonzero
  full-regression exit BLOCKS by default**. Merely "recording" a baseline failure
  does NOT make the suite green and does NOT satisfy the gate.
  - A **restricted acceptance profile** is the only exception, and only when a
    **separately human-approved, named, time-limited exception policy** exists
    that lists the exact known-failing test IDs, an owner, and an expiry — and
    even then the profile is **NOT green** and must be labelled as such. There is
    **no automatic waiver** just because a failure is documented.
- Blocking: any nonzero exit blocks unless covered by an approved exception
  profile (which is still not green).
- Evidence: test run + (if used) the approved exception profile.
- Owner: student author; exception profile requires human approval.
- **ACTUAL status: PARTIAL — regression runs but is NOT green (4 known baseline
  failures: 3 date-sensitive cache + 1 network-reachability). No exception policy
  is approved. These 4 failures remain UNRESOLVED and NO new exception is
  granted; the gate would BLOCK today.**

### G9 — Diff-aware AI-use-log update gate

- **ACTUAL trigger:** none.
- **TARGET trigger:** every PR.
- Inputs: the PR diff + `docs/ai-use-log.yaml`.
- **Check contract:**
  - If code/prompt/test files changed, require a **NEW** `ai-use-log` entry added
    in the **same diff**.
  - The new entry must be **linked to the actual diff scope** (the same changed
    paths/requirement IDs) and name the **prompt/model version** involved.
  - **Reject:** an unrelated pre-existing log edit, a whitespace-only change, or
    an entry that does not mention the changed scope or the prompt/model version.
- Pass/fail: pass = a new, scope-linked, version-named entry exists for the
  changed files. Otherwise **fail (blocking)**.
- Blocking: fail blocks.
- Evidence: diff analysis + entry/scope match.
- Owner: student author.
- **ACTUAL status: MISSING — NOT IMPLEMENTED.**

### G10 — Required remote branch protection + real human review

- **ACTUAL trigger:** none locally observable.
- **TARGET trigger:** PR merge into the protected branch.
- Inputs: GitHub repository settings.
- Check: branch protection requires all status checks **and** at least one
  **genuine human** review (no self-approval; agent approvals do not count). If a
  safety-critical path changed, require the human safety-review approval.
- Pass/fail: pass = all required checks + human approval present.
- Blocking: merge blocked.
- Evidence: GitHub branch-protection settings + PR review record.
- Owner: repository human owner.
- **ACTUAL status: UNVERIFIED** — cannot be certified from local YAML; the human
  must check GitHub settings.

---

## PR review template (exact identity + verdicts)

Recorded per PR. **Verdict (human-entered only):** `APPROVE` /
`CHANGES REQUIRED` / `REJECT`.

- **PR identity:** PR number/title, **base commit SHA**, **head commit SHA**,
  related requirement/invariant IDs.
- **Spec/architecture alignment:** implements an approved requirement; matches
  blueprint/invariants/ADRs.
- **Code quality:** structure, naming, no untraced functions.
- **Tests:** positive + ≥1 negative test; requirement/invariant IDs in tests;
  human-approved test cases **predate** implementation (G5).
- **Operations:** fail-closed behavior, budget/observability, migration impact.
- **Security:** no secrets, no unauthorized network, permission boundaries
  (G4/waivers, G6).
- **Efficiency:** determinism preserved; no unbounded cost.
- **AI-use-log:** new scope-linked entry present (G9).
- **Unresolved findings:** list every open finding from earlier reviews with
  status (must be empty or explicitly accepted with an expiry/owner).
- **Verdict:** APPROVE / CHANGES REQUIRED / REJECT.

## Eight course debt categories (mapped to real records; no invented debt)

The course lists exactly eight AI-era debt categories. Genuine records are mapped;
a category with no genuine instance is marked so — no debt is invented.

| Category | Genuine mapping | Status |
| --- | --- | --- |
| **prompt rot** | `prompts/` versions retained but `.opencode/rules.md` (human-only) still references v1.2; prompt/rule drift. DEBT-024. | Observed |
| **hallucinated dependencies** | Clean-install smoke guards undeclared runtime deps; no dependency/vuln scan yet. No confirmed hallucinated dependency found. | No observed instance (scan MISSING) |
| **untouchable code** | `evidence/` + `debate/` pure modules isolated and unit-tested. | No observed instance |
| **hidden dependencies** | `memory.py` imports `output_guard.HOLD`; guard/rating shared recognizer coupling. DEBT-025. | Observed (documented) |
| **agent-induced bloat** | Backtracking-regex + descriptor-cap churn corrected in-pass (logbook 067). DEBT-026. | Observed (resolved) |
| **evaluation debt** | Full suite not all-green; no type/dep/semantic-eval gates; schema fallback limitation. DEBT-001/002/023. | Observed |
| **guardrail debt** | Permissions not path-scoped / not probe-verified; plan-first + CI gates not enforced. DEBT-004/027. | Observed |
| **human/cognitive debt** | Traceability scores pending; no approved perf thresholds; team deliverables pending. DEBT-011/014/028. | Observed (pending human) |

## Source/test folder mapping (upstream-layout exception)

`src/`, `test/offline/`, `test/live/` are README pointers; real source is
`tradingagents/` + `cli/`, tests are in `tests/`. This mapping **remains an
upstream-layout exception pending instructor agreement** — it is **not**
automatic compliance, and no code is relocated/duplicated to fake the tree.
