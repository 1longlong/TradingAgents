# Student-annotated transcript — WangTianQi (60726054)

> **STATUS: AI-PREPARED DRAFT — NOT SIGNED, NOT FINAL.**
> This file was drafted on 2026-11-21 by DeepSeek Harness (dsh) from committed
> evidence and the recorded AI-coding sessions, at the project owner's request.
> It is structurally complete and evidence-grounded, but the personal decisions,
> reasoning and reflections belong to the student. Every place that needs a real
> personal annotation is marked
> `HUMAN_CONFIRMATION_REQUIRED`. The final attestation at the end is **unsigned**.
> Do not treat this draft as a completed human-authored transcript.

| Field | Value |
| --- | --- |
| Student ID | 60726054 |
| Student name | WangTianQi |
| Course | CS5351 |
| Submission date | `PENDING_HUMAN_CONFIRMATION` (not yet supplied) |
| Repository | `TradingAgents`; integration worktree branch `integrate/token-into-release-20261121`, base `24adf97`, merging personal feature `57b93df` (personal final code `50b2ca3`) |
| AI tools used | **OpenCode** (2026-10-20 → 2026-11-15) and **DeepSeek Harness / dsh** (2026-11-16 → 2026-11-21), as separate coding applications. The model id `CS5351/DeepSeek-V4-Flash` is a model, not a tool. |
| Evidence basis | `docs/ai-use-log.yaml` (`AUL-074`–`AUL-108`), `docs/ai-use-session-audit.md`, `docs/architecture/evaluation-logbook.md`, `docs/bug-diary.md`, `docs/review-memo.md`, `git log` of `2d17df8..50b2ca3`, and the recorded sessions |

## How to read this draft

- **Paraphrase, not quotation.** Where the exact human prompt was not accessible in
  a form that can be quoted, the request is paraphrased and labelled. No literal
  prompt quote is invented.
- **Evidence first.** Each entry names the repository path, commit, log record or
  session identifier that supports it. A claim without an anchor is labelled
  `NOT_VERIFIED`.
- **Failures are kept.** Rejected optimisations, invalid runs, rollbacks and
  process incidents are recorded, not smoothed over.
- **Two tools, two periods.** OpenCode produced the work recorded from 2026-10-20 to
  2026-11-15; DeepSeek Harness produced the 2026-11-16 freeze, the paid batches, the
  remediation and the 2026-11-21 documentation rounds. This split is evidenced by
  the two session stores, the commit timestamps and the commit content; it is not
  inferred from a model name.
- **Unresolved authorship.** Git authors `WTQ`, `Plan C3`, `C3 Engine`, `dsh-agent`
  and `t` appear in the history. Only `dsh-agent` is partly explained (the
  2026-11-16 00:22–01:28 dsh session). `t` is git's default single-character
  `user.name`. Do not read a commit-author string as a person's identity.
- **No credentials.** No key, token or `.env` value appears here, and none may be
  pasted in.

---

## Entry 01 — Host environment inspection before any project work (2026-09-06/07)

- **Context / goal.** Check that the host had the toolchain needed for a Python
  project with a Node-based coding agent, before starting work.
- **Request context (paraphrased).** A read-only environment check: list Python,
  pip, Node.js, npm and Git with versions and paths; a second pass re-checked
  command availability and reported that the `nodejs` command name is absent while
  `node` exists via nvm.
- **What the AI produced.** Version/path listings (Python 3.14.x, pip 25.x, Node
  v24.20.0, npm 11.19.0, Git 2.53.x as recorded in the session) and the
  `node`/`nodejs` finding. No repository file was read or modified.
- **What was accepted / rejected / changed.** Nothing to accept: this was a
  read-only environment probe, not repository development.
- **How it was verified.** The agent's own command output in the session; there is
  no committed artefact.
- **Evidence links.** `AUL-096` (integrated personal record AIU-023); OpenCode
  sessions `ses_f893561e…` and `ses_f84573529…`.
- **Remaining doubt.** Exact host versions at later dates were not re-checked; the
  session store is local and mutable.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  that these were your own environment sessions and add why the environment
  mattered for your project.`

## Entry 02 — Checkout, branch and early exploration (2026-10-19/20)

- **Context / goal.** Clone the upstream project and start the token-observability
  line from the upstream base.
- **Request context (paraphrased).** Inspect the repository and its tooling, then
  create the feature branch from upstream base `2d17df8`.
- **What the AI produced.** A working checkout, branch creation, and a
  plugin/skill discovery pass that ended up inspecting the TradingAgents checkout,
  plus a separate read-only exercise that inspected `pyproject.toml`,
  `cli/main.py` and `tradingagents/default_config.py` in sequence.
- **What was accepted / rejected / changed.** The branch was created. The personal
  report records that three early attempts were stashed; the reason is
  `NOT_VERIFIED` and is not invented here.
- **How it was verified.** `git log`/`git show` of the branch base; the read-only
  inspection exercised real files but changed nothing.
- **Evidence links.** `2d17df8`; `AUL-097` (AIU-024); personal `Report.md` §4
  (stash note).
- **Remaining doubt.** Why the three attempts were stashed; which session created
  the branch.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the branch-creation session and, if you remember it, the reason for the three
  stashed attempts.`

## Entry 03 — Observability and measurement foundation (2026-10-20)

- **Context / goal.** Make every provider call attributable and countable before
  attempting any optimisation, without changing trading semantics.
- **Request context (paraphrased).** Across seven sessions the instruction was
  repeatedly that this work is **observability only** and must not change prompts,
  routing or decision behaviour: add per-agent and per-tool scoping, tool rounds,
  prefetch accounting and structured-output telemetry, then exercise the
  measurement surface end to end.
- **What the AI produced.** `tradingagents/observability.py` grew a per-run
  collector, agent scopes and tool-round instrumentation; node wrappers in
  `tradingagents/graph/setup.py` and the pre-graph reflector scope in
  `tradingagents/graph/reflection.py`. The last session found a real runtime
  regression in the first end-to-end smoke test and fixed it rather than
  redesigning the system.
- **What was accepted / rejected / changed.** The observability-only boundary was
  kept; the smoke-test regression was fixed.
- **How it was verified.** Session-level smoke runs and the early offline tests
  (`tests/test_observability.py`, `tests/test_graph_tool_observability.py`). The
  full post-merge suites were re-run on 2026-11-21 (see Entry 20).
- **Evidence links.** `AUL-084` (AIU-011); baseline commit `866133d`;
  `tests/test_observability.py`; `tests/test_graph_tool_observability.py`.
- **Remaining doubt.** The seven sessions were read at human-prompt level; the
  delegated subagents inside them were counted, not individually reviewed.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  which of the seven sessions you personally directed, and add what you wanted to
  learn from the first end-to-end smoke test.`

## Entry 04 — CLI-preference and trader-attribution corrections (2026-10-20)

- **Context / goal.** The new observability layer exposed two side effects: a
  CLI-preference regression and a trader node whose partial name was not attributed.
- **Request context (paraphrased).** Find and fix the regressions introduced by the
  observability change without widening scope.
- **What the AI produced.** A CLI-preferences regression fix and the trader
  partial-node-name attribution fix.
- **What was accepted / rejected / changed.** Both fixes were kept; the
  observability-only boundary still held.
- **How it was verified.** Targeted tests from that period; the host-coupled
  `cli_prefs` weakness later became `DEBT-042`.
- **Evidence links.** `AUL-084` (AIU-011); `tests/test_cli_prefs.py`;
  `tests/test_observability.py`.
- **Remaining doubt.** Which exact commit introduced each regression.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  whether you noticed the CLI regression yourself or it was reported by the agent.`

## Entry 05 — Harness audit and credential-free QA (2026-10-23)

- **Context / goal.** Before spending money on a benchmark, confirm the measurement
  harness exists, works, and does not need credentials for a dry run.
- **Request context (paraphrased).** A read-only audit of the token-benchmark
  harness, then a credential-free QA pass before any paid benchmark.
- **What the AI produced.** A written audit conclusion and a QA pass; no paid call
  was made.
- **What was accepted / rejected / changed.** The harness was confirmed as the
  measurement path; the QA pass became a required step before spend.
- **How it was verified.** Read-only inspection plus the credential-free run.
- **Evidence links.** `AUL-085` (AIU-012); `scripts/token_benchmark.py`;
  `token_benchmarks/README.md`.
- **Remaining doubt.** The audit report itself was not committed as a standalone
  artefact in this tree.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the purpose you had in mind for the credential-free QA gate.`

## Entry 06 — Two telemetry defects found in a real smoke run (2026-10-23/24)

- **Context / goal.** A smoke run's telemetry did not agree with what the run
  appeared to do.
- **Request context (paraphrased).** Investigate (a) a tool-call observability
  discrepancy — 20 reported LLM calls against a different tool-call count — and
  (b) a telemetry re-run conflict where one run directory held two telemetry files
  with different call counts (19 vs 20, and elsewhere 19 vs 28).
- **What the AI produced.** Two defect records and, later, the fixes: tool-round
  attribution for the graph `ToolNode` (`attrib_tool_round`), and a pre-run
  selection rule that chooses exactly one telemetry artifact for a measured attempt
  by a rule fixed before the run, never by file size or mtime.
- **What was accepted / rejected / changed.** Both defects were accepted as real.
  They are now `BUG-018` (graph-path observability) and `BUG-017` (selection
  integrity), with the requirement `FR-OBS-005`.
- **How it was verified.** `tests/test_observability.py::TestAttribToolRound`,
  `tests/test_graph_tool_observability.py`, `tests/test_token_benchmark.py`,
  `tests/test_c3_regressions.py`.
- **Evidence links.** `AUL-085` (AIU-012), `AUL-098` (AIU-025); `BUG-017`,
  `BUG-018`; `FR-OBS-005`.
- **Remaining doubt.** The original 20-call smoke observation is a session
  self-report and was not re-executed for the bug diary.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  your reading of the two defects and whether the selection rule matched what you
  intended.`

## Entry 07 — First real five-run baseline and one-command runner (2026-10-23/24)

- **Context / goal.** Produce a first real baseline measurement and make it
  runnable with one command.
- **Request context (paraphrased).** Run a real five-run end-to-end benchmark into
  `baseline_v2`, stabilise it, audit the whole repository before committing, repair
  the findings minimally, and add a one-command entry point with tests and a README.
- **What the AI produced.** The five-run `baseline_v2`, a whole-repository
  pre-commit audit, a minimal repair pass, `scripts/run_token_benchmark.sh` with a
  `measure` subcommand, 17 new wrapper tests, 29 new harness tests and a README.
  The agent's own final message reported 114 targeted tests passing and 1,178
  passed / 2 skipped / 5 failed for the full suite, naming the 5 as pre-existing
  timezone- and `.env`-dependent tests.
- **What was accepted / rejected / changed.** The baseline and the runner were
  kept. The 5 failures are recorded as pre-existing, not silently waived.
- **How it was verified.** The agent's self-reported test counts; the delivered
  tests exist and the 2026-11-21 focused runs passed (Entry 20). The full 1,178-run
  count was **not** re-executed for this transcript.
- **Evidence links.** `AUL-098` (AIU-025); `scripts/run_token_benchmark.sh`;
  `tests/test_run_token_benchmark_sh.py`; `tests/test_token_benchmark.py`;
  `token_benchmarks/baseline_v2/`.
- **Remaining doubt.** The 114/1,178 figures are session self-reports.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  whether you reviewed the pre-commit audit findings or accepted the agent's repair
  pass.`

## Entry 08 — Reproducible baseline and Stage 0–6 campaign (2026-11-02/03)

- **Context / goal.** Make the baseline reproducible, then systematically test
  token optimisations rather than guessing.
- **Request context (paraphrased).** Create a reproducible baseline commit whose
  code fingerprint covers untracked source files, research the optimisation
  direction, then run an autonomous campaign of staged candidates with real
  measurements and an accept/revert decision per stage.
- **What the AI produced.** Commit `866133d`; Stages 0–6; accepted Stage 1 (report
  deduplication) and Stage 2 (structured one-shot output); rejected Stage 4
  (payload compression, total tokens +3.8 % on five completed measurements) and
  rejected/rolled back Stage 6 after the QA framework found semantic information
  loss.
- **What was accepted / rejected / changed.** Stage 1 and 2 accepted; Stage 4 and 6
  rejected and reverted. The rejected candidates are not presented as
  optimisations.
- **How it was verified.** Per-stage measurements recorded in the campaign output
  (not all delivered in this tree) and the QA framework built after the Stage 6
  finding.
- **Evidence links.** `AUL-086` (AIU-013), `AUL-099` (AIU-026); `866133d`;
  `LOG-001`–`LOG-003` (marked `NOT_VERIFIED` for this tree where the campaign
  outputs are absent); ADR-015 for the later batch-macro decision.
- **Remaining doubt.** Some campaign output directories are not in the delivered
  tree.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must state your
  own reasoning for rejecting Stage 4 and Stage 6; the record shows the measured
  result and the QA finding, not your judgement.`

## Entry 09 — Operator pause, ECONNRESET recovery and the QA framework (2026-11-02/03)

- **Context / goal.** The campaign was interrupted by a controlled pause and a
  provider/network failure.
- **Request context (paraphrased).** Pause the campaign before the operator left
  the machine (allow `run_04` to terminate, start no `run_05`, preserve every
  attempt, commit nothing), then resume from a checkpoint without restarting the
  task; recover from ECONNRESET / "No deployments available".
- **What the AI produced.** A preserved checkpoint and attempts; recovery from the
  network failure; the Quality Assurance framework created after the final QA found
  semantic information loss in Stage 6 evidence packets; an offline Stage 0 / 2 / 6
  historical quality comparison; a Stage 6 rollback and the start of Round 2.
- **What was accepted / rejected / changed.** The pause and the rollback were
  honoured; attempts were preserved rather than overwritten.
- **How it was verified.** The preserved run directories and the QA comparison
  recorded in the campaign material.
- **Evidence links.** `AUL-099` (AIU-026); `LOG-001`–`LOG-003`.
- **Remaining doubt.** The exact wall-clock times of the pause and the outage are
  `NOT_VERIFIED`.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the pause decision and explain what you wanted preserved.`

## Entry 10 — Rounds 6–8, data-source audit and tool loss (2026-11-04–14)

- **Context / goal.** Move from synthetic campaign stages to the real data paths and
  a configuration-matched baseline.
- **Request context (paraphrased).** Audit the data sources and availability, run
  Round 6, then a configuration-matched Round 7, then Round 8 market-analyst
  efficiency work; do not paper over tool failures.
- **What the AI produced.** Round 6 found the FRED key disabled and that yfinance
  could not serve NVDA news for the study date 2026-09-23. Round 7 was a
  configuration-matched baseline; it hit a mid-run loss of shell and filesystem
  tools. The operator refused static reading or simulated output and required
  recovery by Explore-Subagent delegation, with the main agent auditing and only
  the subagent executing. Round 8 followed.
- **What was accepted / rejected / changed.** Static/simulated substitution was
  rejected as verification. The delegation pattern was adopted for the recovery.
- **How it was verified.** The recovered execution is visible in the delegated
  session records and the resulting committed code/tests; the operator's
  instruction is recorded in the session.
- **Evidence links.** `AUL-087` (AIU-015), `AUL-100` (AIU-027); `LOG-004`.
- **Remaining doubt.** The delegated subagent sessions were counted, not read
  individually.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the stop-and-recover instruction and what you would not accept as verification.`

## Entry 11 — Rollback approval, HTTP 429 pivot and Batch-Macro/S2 (2026-11-04–14)

- **Context / goal.** Keep the experiment honest when a vendor starts failing and
  when a candidate optimisation changes behaviour.
- **Request context (paraphrased).** Approve or refuse the Stage-2 rollback, re-run
  the Round 7 clean control against a pinned tree fingerprint, preserve an
  interrupted D1 benchmark attempt, and pivot to configuration-matched replay after
  sustained Yahoo News HTTP 429; then complete the Batch-Macro tool and the S2
  structured-output path.
- **What the AI produced.** A Stage-2 rollback with no Stage 3 start; a clean-control
  re-run against a pinned fingerprint; the 429 pivot; the batch-macro tool
  (`get_macro_indicators_batch`), the typed S2 side channels
  (`agents/utils/s2_context.py`) and the structured-output completion.
- **What was accepted / rejected / changed.** The rollback was approved; the 429
  pivot was adopted; batch macro shipped behind a switch (ADR-015); S2 routing was
  always-on with no OFF arm.
- **How it was verified.** `tests/test_macro_batch.py`,
  `tests/test_ablation_switches.py`, `tests/test_s2_downstream_integration.py`,
  `tests/test_structured_analysis.py`-family tests.
- **Evidence links.** `AUL-088` (AIU-016), `AUL-100` (AIU-027); ADR-015;
  `FR-ANL-006`; `LOG-004`.
- **Remaining doubt.** The 429 incident's exact duration and the vendor state are
  not reconstructable from the tree.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the rollback approval and why batch macro was kept as an ablation switch rather
  than a default.`

## Entry 12 — RC1, CAND-01 and the pre-live audits (2026-11-12–14)

- **Context / goal.** Freeze a release candidate, analyse its token regression, then
  design and audit the single-pass candidate before any paid pilot.
- **Request context (paraphrased).** Freeze RC1 and preserve it; root-cause the RC1
  token regression; design CAND-01 single-pass finalisation; run an independent
  pre-live re-audit and fix the F1/F2/F3 and PF-01 defects before a paid run.
- **What the AI produced.** RC1 `9948bf8` (2026-11-12, tag `rc1`); the single-pass
  design; the F1/F2/F3 fixes (`e33ab2c`, `ebe81e3`, `ec629dd`, `72ae0f8`); the PF-01
  news-status fix (`7832a90`); two CAND-01 audits recorded as
  `READY_WITH_LIMITATIONS` and later READY.
- **What was accepted / rejected / changed.** RC1 was preserved; the single-pass
  path stayed off by default (ADR-014, `INV-22`).
- **How it was verified.** `tests/test_cand01_single_pass_finalization.py`,
  `tests/test_cand01_news_positive_path.py`, and the audit verdicts (session-only,
  see `REC-09`).
- **Evidence links.** `AUL-088` (AIU-015), `AUL-089` (AIU-016); `9948bf8`;
  `e33ab2c`, `ebe81e3`, `ec629dd`, `72ae0f8`, `7832a90`; ADR-014; `REC-09`;
  `BUG-001`–`BUG-004`.
- **Remaining doubt.** No committed review report survives from this period.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  whether you reviewed the CAND-01 audit verdicts before the pilot and what you
  personally checked.`

## Entry 13 — Finnhub + GDELT migration and the Finnhub-only decision (2026-11-15)

- **Context / goal.** The experiment needed a symbol-specific, date-range-capable,
  point-in-time-defensible news path.
- **Request context (paraphrased).** Map the news call chain and the historical-news
  / PIT behaviour, add a Finnhub company-news adapter and keep GDELT as the only
  other active source; then run a quality gate and decide the final scope.
- **What the AI produced.** A Finnhub adapter, shared merge/relevance helpers
  (`news_merge.py`, `news_relevance.py`), a unified news-status model and PIT
  filtering. The quality gate then found repeated GDELT 429s, no real success
  evidence for the GDELT global path, and industry news leaking into XOM because a
  Finnhub `related` ticker match was treated as relevance. The operator approved a
  narrower scope: **GDELT excluded from the 16-run experiment entirely, Finnhub-only
  for all four tickers and all four arms**.
- **What was accepted / rejected / changed.** GDELT was rejected for the experiment
  (ADR-016); Finnhub-only was accepted. The GDELT code remains in the tree but is
  unreachable from the configured route (`INV-24`).
- **How it was verified.** `tests/test_finnhub_news.py`,
  `tests/test_finnhub_only_scope.py`, `tests/test_news_relevance.py`,
  `tests/test_news_status_taxonomy.py`; the 429 and relevance findings are recorded
  in the session.
- **Evidence links.** `AUL-101` (AIU-028); `b00dd00`, `24d488d`, `4eaf8cc`;
  ADR-016; `BUG-014`.
- **Remaining doubt.** The quality-gate session's quoted 243-news-test and
  1,607-passed figures are the agent's self-report and were not re-run.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the Finnhub-only scope decision and your reasoning for excluding GDELT rather
  than fixing it.`

## Entry 14 — Preflight, C3 audit rounds and the self-tamper halt (2026-11-15)

- **Context / goal.** Make the 16-run apparatus safe to spend on.
- **Request context (paraphrased).** Build the V2 protocol, switch matrix,
  config-hash manifest, release seal and freeze record; run the preflight; stop
  before paying if the apparatus is not ready; audit rounds 2–5.
- **What the AI produced.** Five audit rounds (REC-01–REC-04) that found Critical
  and blocking defects, including a child spec with no switch fields (one arm under
  four names), a fingerprint that covered zero registered artefacts, a circular
  freeze designation, and a self-tamper incident: a `cp -a` worktree copy wrote
  `e1d018e`/`d7af7ea` into the branch under audit, after which the gate printed
  "GATE PASSED — safe to spend money". The campaign was halted at **zero paid
  calls**, the incidents were disclosed, and the history was preserved rather than
  rewritten. Plan C reported `BLOCKED` on the lost spec generator and did not
  fabricate replacements; C2 reconstructed it.
- **What was accepted / rejected / changed.** All Critical/blocking findings were
  accepted and fixed; the halt was accepted; U-1/U-2 were deferred to a single
  re-freeze round.
- **How it was verified.** Committed audit reports
  (`C3_HALT_REPORT_20261115.md`, `INCIDENT_20261115B_self_tamper.md`), mutation
  logs, and the preflight 16-condition list. The halt report records zero paid
  calls.
- **Evidence links.** `AUL-074`, `AUL-075`, `AUL-090`, `AUL-102`, `AUL-103`;
  `REC-01`–`REC-04`; `BUG-012`, `BUG-013`, `BUG-015`, `BUG-016`.
- **Remaining doubt.** Rounds 2–4 finding IDs/severities were partly lost with a
  scratch worktree; `t` is git's default identity, not a person.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the halt decision, the disclosure of the self-tamper incident, and who (if
  anyone) authorized the later paid runs.`

## Entry 15 — V2 paid batch and its invalidated runs (2026-11-16)

- **Context / goal.** Execute the V2 2×2 batch on the frozen apparatus.
- **Request context (paraphrased).** Run the V2 batch under the frozen protocol,
  preserve every attempt, and stop if the preflight fails.
- **What the AI produced.** 7 attempts: 5 valid, 1 environment-failed (R05a01) and
  1 invalid (R06, one unattributed call at `global_sequence=0`), consuming
  1,463,791 provider-reported tokens. The batch exposed the unattributed reflector
  call and cross-run memory pollution.
- **What was accepted / rejected / changed.** The invalid runs were kept as
  evidence. The two defects were fixed for V3 (`afa0fc6`): system-component
  attribution for the pre-graph reflector and per-run memory snapshot copies.
- **How it was verified.** Telemetry and the run ledger; `tests/test_system_attribution.py`
  (13 tests), `tests/test_memory_isolation.py` (21 tests).
- **Evidence links.** `AUL-076` (AIU-003), `AUL-077` (AIU-004), `AUL-093` (AIU-020);
  `15270b1`; `REC-05`; `BUG-007`, `BUG-008`; `LOG-005`–`LOG-006`.
- **Remaining doubt.** The raw paid telemetry is git-ignored and not in the
  delivered tree, so the totals are the recorded ledger values.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the authorization and budget under which the V2 batch ran; the repository has no
  dated authorization artefact (`DEBT-052`).`

## Entry 16 — V3 memory isolation, attribution correction, freeze and batch (2026-11-16)

- **Context / goal.** Fix the two V2 defects, re-freeze, and run the full design.
- **Request context (paraphrased).** Add system-component attribution and per-run
  memory isolation, bump the telemetry schema, re-audit, freeze V3, then run the
  16-run batch.
- **What the AI produced.** `afa0fc6` (attribution + memory isolation), `6e66dca`
  (schema 3), `f19d6ed` (auditor findings), `c30700c` (stripped-spec guard), freeze
  `e3b5cca` (tag `c3-v3-final-freeze`). V3 then ran 18 attempts over 16 Run IDs:
  15 valid, 1 environment-failed (R02a01) and 2 invalid (R12a01/a02, provider 400),
  consuming 3,067,669 tokens; valid runs carried 298 LLM and 432 tool calls.
- **What was accepted / rejected / changed.** The fixes were accepted; R12's cell
  remained missing and is not imputed.
- **How it was verified.** Committed V3 audits (REC-06), `MANIFEST.sha256`,
  the freeze verifier, and the delivered tests.
- **Evidence links.** `AUL-077`–`AUL-079`, `AUL-093`; `REC-06`; `LOG-007`,
  `LOG-008`; `e3b5cca`.
- **Remaining doubt.** Raw run telemetry is not in the tree; the V3 numbers predate
  the final remediation and are not re-measured.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  the V3 re-freeze decision and the authorization for the second paid batch
  (`DEBT-052`).`

## Entry 17 — Single-Pass and Batch-Macro: what was accepted, rejected or left exploratory

- **Context / goal.** Decide whether the two candidate optimisations should ship.
- **Request context (paraphrased).** Compare the four arms (B two-call baseline,
  AB two-call + batch macro, C0 single-pass, CC both) and decide what to adopt.
- **What the AI produced.** Single-pass: **−19,589 tokens/run (−8.96 %)** on the
  balanced three-block mean, negative in all three complete blocks, but **n=1 per
  cell** and the V3 data predates the final fixes. Batch macro: mean −17,702
  tokens/run, **not robust** (about −695 excluding the environment-degraded R01;
  AAPL +1,612). CC was the cheapest mean but 2 of 3 valid runs had degraded DSML
  reports and 1 crashed.
- **What was accepted / rejected / changed.** Single-pass was kept behind an
  off-by-default switch (`single_pass_finalization_enabled=False`, ADR-014);
  batch macro was kept only as an ablation switch (ADR-015); neither was adopted as
  a proven general saving. The results are labelled exploratory.
- **How it was verified.** The V2/V3 ledgers and telemetry, `LOG-006`–`LOG-011`,
  and the delivered analysis documents. No significance test exists.
- **Evidence links.** ADR-014, ADR-015; `FR-ANL-005`, `FR-ANL-006`; `FR-CAM-001`;
  `LOG-010`; `DEBT-046`, `DEBT-047`.
- **Remaining doubt.** n=1, one model, one trade date, no ground truth.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must state
  whether you consider the single-pass result strong enough to justify shipping the
  switch, and why batch macro was not adopted.`

## Entry 18 — Final remediation and the three independent technical audits (2026-11-16)

- **Context / goal.** Repair the R12 provider-400 fallback, the DSML markup leakage
  and the single-pass `tool_rounds` gap, then audit the candidate.
- **Request context (paraphrased).** Fix the defects, add regression tests, prove
  the tests are non-vacuous with a pre-fix probe and mutations, then run three
  independent read-only audits.
- **What the AI produced.** `e0ea1b0` and follow-ups (`e9eed04`, `51edd41`,
  `eaeebab`); 20 regression tests; a pre-fix probe detecting 4/4 on `e3b5cca` and
  0/4 after; 6/6 mutations caught; final `50b2ca3`. Three audits (A product logic,
  B telemetry/infrastructure, C regression/data safety) returned PASS with no open
  High/Critical.
- **What was accepted / rejected / changed.** The fixes were accepted offline. No
  paid rerun was performed (`DEBT-046`), so the fixes are `FIXED — NOT VERIFIED
  LIVE`.
- **How it was verified.** `tests/test_final_remediation.py` 20/20; probe and
  mutation evidence; recorded suite 2,227 passed / 4 known failed / 2 skipped / 319
  subtests.
- **Evidence links.** `AUL-080`–`AUL-082`; `REC-07`; `BUG-009`–`BUG-011`;
  `50b2ca3`; `token_benchmarks/final_remediation_20261116/`.
- **Remaining doubt.** The audits are AI-authored and were not reviewed by a human;
  no live rerun exists.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must state
  what you personally verified in the final remediation and whether you accept the
  AI-authored audit conclusions.`

## Entry 19 — Course-deliverable round in the personal worktree (2026-11-19/20)

- **Context / goal.** Turn the delivered code into a course submission: governance,
  requirements, architecture, records, transcripts policy, validator and CI.
- **Request context (paraphrased).** Build the course-deliverable set in the
  personal worktree without changing product code, frozen specs or experiment data;
  make the offline validator and a blocking CI gate.
- **What the AI produced.** `AGENTS.md`, `architecture-blueprint.md`, `Prompt.md`,
  `Report.md`, the `docs/` set (requirements, architecture, code governance,
  records), `prompts/`, pointer READMEs, the transcripts policy/template, the
  offline `validate_submission.py` and the CI gate, in commits `0fddb9f`,
  `3097060`, `57b93df`.
- **What was accepted / rejected / changed.** The submission packaging was accepted
  as a deliverable; it changed no product code or frozen artefact.
- **How it was verified.** The validator ran and reported the required artifacts;
  the personal branch recorded 2,233 passed / 0 failed / 2 skipped / 319 subtests
  after the test-isolation fixes. The merged-tree full suite is `NOT_RUN`
  (`DEBT-054`).
- **Evidence links.** `AUL-094`, `AUL-104`; `0fddb9f`, `3097060`, `57b93df`;
  personal `docs/ai-use-session-audit.md`.
- **Remaining doubt.** The personal governance files were introduced 2026-11-19;
  they did not govern the October/early-November work.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  which submission-round files you authored or reviewed personally.`

## Entry 20 — D1/D2/D3 integration in the Release worktree (2026-11-21)

- **Context / goal.** Integrate the personal token-observability work into the
  team's Release-based merge without losing either side's history.
- **Request context (paraphrased).** Release-first integration: preserve the 32
  Release requirement IDs and schema, integrate the personal requirements with a
  complete mapping, keep both AI-use histories and fix duplicate record IDs, audit
  the architecture/ADR/invariant collisions, and integrate the governance rules.
- **What the AI produced.** The D1–D3 documentation set now in this worktree:
  52 requirements (32 Release + 20 retrospective), 108 unique AI-use records
  after the PR #5 merge (the D1-repaired records are `AUL-106/107/108`; the
  Release PR #5 records use canonical `AUL-071/072/073`), ADR-001–ADR-019,
  INV-1–INV-27 plus INV-TRD, the merged architecture/governance documents and
  `docs/ai-use-session-audit.md`. D4–D6 (this round) added the review memo, bug
  diary, debt register, Report integration and this transcript draft.
- **What was accepted / rejected / changed.** The Release-first mapping was
  accepted by the owner as the integration policy; the personal ADRs' status is
  "human acceptance pending"; no merge commit or push was made.
- **How it was verified.** Draft 2020-12 schema validation (0 errors), 52/52 unique
  requirement IDs, 105/105 unique AI-use records, 18 unique ADRs, INV uniqueness,
  non-conflicted files free of markers, 197 focused invariant tests passing.
  Full submission validation remains blocked by out-of-scope D7–D9 conflicts; the
  full project suite was `NOT_RUN`.
- **Evidence links.** `docs/req/requirements.yaml`, `docs/architecture/adr/`,
  `docs/architecture/invariants.md`, `docs/ai-use-log.yaml`,
  `docs/ai-use-session-audit.md`, `docs/review-memo.md`, `docs/bug-diary.md`,
  `docs/debt-register.md`.
- **Remaining doubt.** The merged-tree full suite has not been run; D7–D9
  conflicts remain.
- **Human confirmation.** `HUMAN_CONFIRMATION_REQUIRED — WangTianQi must confirm
  your role in the 2026-11-21 integration and whether the mapping decisions reflect
  your intent.`

---

## Known gaps and honesty statement

- The pre-V2 sessions were read at human-prompt level. The 509 delegated OpenCode
  sessions and 36 dsh subagent streams were counted and attributed to their parents,
  **not individually reviewed** (`AUL-104`).
- Test counts quoted from session reports (114/1,178; 243 news tests; 1,607 passed)
  are **agent self-reports** and were not re-run for this transcript.
- The V2/V3 raw telemetry is git-ignored and absent from the delivered tree; the
  totals are the recorded ledger values.
- No human sign-off exists for any AI-authored review, ADR, risk or debt item.
- No dated paid-run authorization artefact exists in the repository (`DEBT-052`).
- The commit-author identities `WTQ`, `Plan C3`, `C3 Engine` and `t` are unresolved
  (`DEBT-053`); no person is inferred from them.
- The V3 numbers are exploratory (n=1 per cell), pre-fix and not a general
  cost-saving or trading-alpha claim.
- This transcript contains no credential, key, token or `.env` value.

## What remains for WangTianQi to write personally

1. The personal reasoning in every entry marked `HUMAN_CONFIRMATION_REQUIRED`.
2. The four reflection areas in `Report.md` §7 (motivation; the V2 halt and
   re-freezes; lessons about measurement/evidence/audit independence; whether the
   freeze/audit overhead was justified).
3. The dated paid-run authorization (or an explicit statement that none exists).
4. The session-authorship and commit-author confirmations.
5. The final attestation below.

## Final attestation (UNSIGNED — do not submit as-is)

I confirm that the annotations above are my own account of my work, that I have
not fabricated results, and that I have not included any credential or private
data.

- Signature / typed name: ______________________  (UNSIGNED)
- Date: ______________________  (UNSIGNED)

> The attestation above is a blank template. It has not been filled or signed by
> the student, and this file must not be represented as a signed transcript until
> WangTianQi has completed it.
