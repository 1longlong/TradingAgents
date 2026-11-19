# Verification Constraints

Status: **established 2026-11-19** for the CS5351 final-submission tree (base
commit `50b2ca3`). This document defines how verification must be performed and
what evidence must be retained. It records both what was run and what failed;
a command that runs but fails is still a result, not a pass.

Related: `docs/code-governance/structural-constraints.md` and `AGENTS.md` §9.

## 1. Principles

1. **Offline by default.** The verification of record is the deterministic,
   LLM-free pytest suite. No network, vendor, or paid call is part of a normal
   run.
2. **Reproduce before claiming.** Every reported number must name the command,
   working directory, commit, environment, exit code, and time.
3. **Never fabricate or repair.** Missing data stays missing; a failing test is
   reported, not deleted, skipped, or `xfail`-ed to green.
4. **Separate baseline debt from new findings.** A pre-existing failure/lint
   finding is not an excuse to add more, and is not hidden either.
5. **Read-only audits.** Auditors inspect and execute; they do not edit product
   code, tests, specs, or git history.

## 2. Environment and determinism

- Python: project declares `>=3.10` (`pyproject.toml`); CI matrix is
  3.10–3.13. The local `.venv` used here is Python 3.14.7.
- Run from the repository root (the worktree root), not from `tradingagents/`.
- `PYTHONPATH=.` makes the checkout importable even when the package is not
  installed in the active interpreter.
- `TZ=UTC` fixes date handling; tests that depend on "today" must not inherit the
  developer's local zone.
- Dummy API keys are injected by `tests/conftest.py`; a real key in the
  environment is not required and must not be used.
- Network to news vendors is blocked by autouse fixtures in `tests/conftest.py`.
  Live tests are marked `@pytest.mark.integration` and skip without a real key.
- No test may read `.env`, `.env.enterprise`, or real credentials.

## 3. Commands

Run from the repository root. These are the commands this submission was
verified with; each was actually executed on 2026-11-19 (UTC), HEAD `50b2ca3`
with the D7 test-isolation changes included in this submission.

| ID | Command | Purpose | Observed |
| --- | --- | --- | --- |
| VC-01 | `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests -q` | Full offline suite | `2233 passed, 2 skipped, 319 subtests passed` in 28.59 s, exit 0 |
| VC-02 | `TZ=UTC PYTHONPATH=. .venv/bin/python -m pytest tests/test_prompt_integrity.py tests/test_structured_agent_prompts.py tests/test_cand01_single_pass_finalization.py -q` | Prompt/structured-output guard tests | `90 passed, 16 subtests passed` in 0.78 s, exit 0 |
| VC-03 | `.venv/bin/python -m ruff check .` | Whole-repo lint baseline measurement (not a CI gate; see DEBT-010) | 233 findings on the current tree (ruff 0.17.1, 2026-11-19 22:45 HKT / 14:45 UTC) |
| VC-04 | `ruff check scripts/validate tests/test_submission_compliance.py tests/test_cand01_batch_16run_v3_infra.py tests/test_cli_prefs.py` | CI lint gate (the files this submission adds/changes) | `All checks passed!`, exit 0 |
| VC-05 | `TZ=UTC PYTHONPATH=. .venv/bin/python scripts/token_benchmark.py validate --experiment token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/experiment.json` | Experiment schema validation (schemas 1/2/3) | `experiment is valid`, exit 0 |
| VC-06 | `.venv/bin/python scripts/c3_verify_protocol_freeze.py` | Protocol freeze: arm table, 16 registrations, constants, coverage, order | `PROTOCOL FREEZE VERIFIED`, exit 0 |
| VC-07 | `.venv/bin/python scripts/c3_verify_final_freeze.py --json` | Certified final-freeze check for the checked-out tree | **fails**: v2 `c3/FREEZE_RECORD.json` missing; this tree is not the certified v2 freeze |
| VC-08 | `cd token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3 && sha256sum -c MANIFEST.sha256` | Byte-integrity of the 55 frozen batch files | all 55 `OK`, exit 0 |
| VC-09 | `git diff --check` | Whitespace/conflict-marker hygiene | exit 0 |
| VC-10 | `.venv/bin/python -c "import tradingagents, cli.main; print('clean-install import OK')"` | Clean-install/import smoke (CI uses a fresh install) | `clean-install import OK`, exit 0 |
| VC-11 | `.venv/bin/python scripts/validate/validate_submission.py` | Course-compliance gate: 34 required artifacts, YAML/JSONC parsing, requirements schema, trace-matrix paths, prompt metadata, ADR IDs, docs secret scan | at 2026-11-19 22:45 HKT: `PASS: submission compliance`, `34/34` artifacts, exit 0; 2 warnings (human transcript pending, jsonschema fallback). Re-run before submission. |

Notes:

- VC-01's count includes the D7 test-isolation patch in `tests/`. On a pristine
  `50b2ca3` checkout the same command reported **4 failed, 2227 passed, 2
  skipped**: two `tests/test_cand01_batch_16run_v3_infra.py` failures because the
  frozen specs embed an absolute `experiment_root`, and two
  `tests/test_cli_prefs.py` failures caused by ambient CLI prefs/environment.
  Those are environment/path-isolation failures, not product regressions; the
  remediation must make the tests checkout-independent, not edit the specs.
- VC-03 is real baseline debt under ruff 0.17.1, including generated audit
  scripts under `token_benchmarks/**/logs/audit/`. Do not mass-fix unrelated
  files; fix touched files and record the remaining count.

## 4. Schema and structure validation

`scripts/validate/validate_submission.py` is the closest thing to a single
"validate everything" gate, but it covers submission structure, not runtime
behavior. Use it together with the focused checks:

1. **Submission structure** — VC-11. It checks the 34 required artifacts,
   parses the YAML/JSONC deliverables (including the prompt files and
   `.opencode/permissions.jsonc`), validates `docs/req/requirements.yaml` against
   `docs/req/req-schema.json` (real `jsonschema` when installed, deterministic
   fallback otherwise), resolves requirement/trace paths, checks prompt
   `version`/`source_commit`, checks ADR IDs, and scans new docs for obvious
   secrets. It is offline.
2. **Experiment schema** — VC-05 (the benchmark validator accepts schemas 1, 2,
   3 and rejects unknown/missing fields).
3. **Frozen bytes** — VC-08 (`sha256sum -c MANIFEST.sha256`).
4. **Protocol registration** — VC-06.
5. **Import boundaries** — the three greps in
   `docs/code-governance/structural-constraints.md` §2.
6. **Referenced paths** — every path named in `AGENTS.md`, `Prompt.md`,
   `.opencode/rules.md`, and `.agent/rules.md` must exist:

   ```bash
   python - <<'PY'
   from pathlib import Path
   import re
   files = ["AGENTS.md", "Prompt.md", ".opencode/rules.md", ".agent/rules.md"]
   missing = []
   for f in files:
       for p in re.findall(r"`([^`\s]+\.(?:md|yaml|jsonc|py|toml))`", Path(f).read_text()):
           if not Path(p).exists():
               missing.append(f"{f}: {p}")
   print("MISSING:", missing or "none")
   PY
   ```

7. **YAML parse** (must return a dict with the required keys):

   ```bash
   .venv/bin/python - <<'PY'
   import yaml
   for f in ["prompts/prompt_v1.0.yaml", "prompts/prompt_v1.1.yaml"]:
       d = yaml.safe_load(open(f, encoding="utf-8"))
       assert isinstance(d, dict), f
       for k in ("version", "source_commit", "source_file", "prompt",
                 "variables", "intended_agent", "historical_usage_status",
                 "change_rationale", "evidence"):
           assert k in d, (f, k)
       print(f, "OK", d["version"], len(d["prompt"]))
   PY
   ```

8. **JSONC parse as JSON after comment stripping**:

   ```bash
   .venv/bin/python - <<'PY'
   import json, re
   text = open(".opencode/permissions.jsonc", encoding="utf-8").read()
   stripped = re.sub(r"//[^\n]*", "", text)
   data = json.loads(stripped)
   assert isinstance(data.get("permission"), dict)
   print("permissions.jsonc OK", sorted(data["permission"]))
   PY
   ```

The JSONC check proves syntax only; it does **not** prove OpenCode loads this
file or accepts every rule (see `docs/code-governance/mcp-tool-manifest.md` and the
file's comments).

## 5. No live APIs in CI

- CI (`.github/workflows/ci.yml`) runs plain `pytest -q` with no provider keys.
  `tests/conftest.py` injects dummy keys and replaces the Finnhub/GDELT
  transports with deterministic failures, so the offline suite cannot spend
  money or depend on vendor uptime.
- Tests that genuinely need a live provider must be marked
  `@pytest.mark.integration`, must skip when the key is absent, and are not part
  of the default gate.
- A benchmark run is never CI work. It requires explicit authorization and the
  preflight gate (`scripts/c3_preflight_gate.py`), and its evidence is stored
  under `token_benchmarks/**`.

## 6. Known-failure policy

1. Before claiming completion, run VC-01 and capture the tail verbatim.
2. If failures exist, classify each one:
   - **product regression** — introduced by the change; must be fixed before
     done;
   - **environment/path** — reproducible only on this host/checkout (absolute
     paths, user prefs, missing optional dependency); record the cause and the
     isolation fix, do not edit frozen artifacts to hide it;
   - **pre-existing baseline** — reproduce on the base commit and record it as
     debt.
3. Never delete, skip, `xfail`, or weaken a test to remove a failure. Never
   regenerate a frozen spec to match a host path.
4. Report the exact command and the count of failures. "All tests pass" is only
   allowed when the run ends with exit code 0 and no failures.
5. A known failure that gets fixed must be re-verified; a known failure that
   remains must be listed in the final report and in
   `docs/code-governance/verification-constraints.md` (or the risk list).

Current baselines and status (2026-11-19):

- Pristine `50b2ca3`: 2 V3 spec-reproduction failures (absolute
  `experiment_root`/`results_dir` embedded in delivered specs) and 2 CLI-prefs
  failures (ambient user prefs / CLI environment). The D7 test-isolation patch
  normalizes host paths and isolates prefs; with it, VC-01 is green.
- The hermetic check is run from a working directory outside the repository (so no
  parent `.env` is discoverable); with the D7 patch it reports `2233 passed, 2
  skipped, 0 failed, 319 subtests`.
- `ruff check .`: 233 findings on the current tree at 22:45 HKT (14:45 UTC). This is
  the recorded whole-repo baseline (DEBT-010), not a CI gate; CI lints only the
  submission files (VC-04, green).
- VC-11 now passes (`34/34`, 2 warnings); the transcript remains a
  human-pending warning, not a failure.

## 7. Mutation tests for critical guards

`scripts/c3_mutation_evidence.py` re-introduces nine known defects and requires
the named tests to fail, restoring each file and re-checking its SHA-256 before
the next mutation. It mutates tracked source, so it is **manual, not CI**, and
must only run on a clean, authorized tree with the evidence log committed under
`token_benchmarks/**/logs/`:

```bash
TZ=UTC PYTHONPATH=. .venv/bin/python scripts/c3_mutation_evidence.py
```

Critical guards covered: usage verdict (missing ≠ 0), budget mode, gate import
root, dry-run rehearsal, effective-config verification, negative token counts,
empty-run attribution, and the freeze verifier's `HEAD == record` requirement.
Do **not** run it as part of a normal test pass; it modifies source files.

## 8. Read-only audits

- An audit may run tests, read files, run `git show`/`git diff`/`git status`,
  and compute hashes.
- An audit may not edit the tree, commit, push, or change tags.
- Audit findings are written to `docs/` (or the audit logs under
  `token_benchmarks/**/logs/`) with file:line references and the command used.
- If an audit needs a write to prove a point, it must request a separate
  authorized change instead.

## 9. Evidence retention

Store evidence with the artifact it describes:

- test/lint output: `token_benchmarks/**/logs/` or a dated `docs/` report;
- benchmark runs: the experiment's `logs/`, `summary.json`, `summary.csv`, and
  `MANIFEST.sha256`;
- prompt exports: `prompts/prompt_v1.0.yaml` and `prompts/prompt_v1.1.yaml` with
  source commit, SHA-256, and extraction method;
- governance checks: command + result in the final report.

Evidence records must include: UTC timestamp, cwd, `git rev-parse HEAD`,
`git status --porcelain` (or a note that the tree is clean), command, exit code,
and a short output tail. Redact credentials, absolute home paths where they are
not relevant, and anything that could be a secret.

## 10. Verification status summary

| Check | Status |
| --- | --- |
| Offline pytest (VC-01) | verified green: 2233 passed, 2 skipped; pristine base had 4 environment failures |
| Prompt/structured guards (VC-02) | verified green |
| Experiment schema (VC-05) | verified green |
| Protocol freeze (VC-06) | verified green |
| Final-freeze certificate (VC-07) | verified failing (v2 record absent; this is not the v2-certified tree) |
| Frozen manifest (VC-08) | verified green (55/55) |
| Ruff (VC-03/VC-04) | whole-repo baseline 233 findings (DEBT-010); CI gates the submission files only (green) |
| Submission validator (VC-11) | verified PASS, 34/34 artifacts, 2 warnings (22:45 HKT) |
| YAML/JSONC syntax | checked by VC-11 and the scripts in §4 |
| OpenCode permission loading | `NOT_VERIFIED` — see `.opencode/permissions.jsonc` |
