# ADR-007 — Measured Debate Budget Accounting and Truthful Participation

- **Status:** Proposed (implementation complete; independent FINAL offline
  verification passed — 644 focused tests / 25/25 external probes / 1822 full
  strict with the 4 known baseline failures — and a bounded school-model
  validation D1/D2 ran on the frozen PRE-FOLLOWUP tree; human acceptance
  pending). The follow-up unknown/quarantine/malformed branches carry fresh
  OFFLINE evidence only — no second live run was performed, no live
  audit-file-persistence claim is made, and the old 214-file fingerprint is not
  claimed unchanged after the follow-up.
- **Date:** 2026-11-10
- **Deciders:** CS5351 project (student); coding-agent implementation; human
  review required before acceptance
- **Trace:** `FR-DDT-003`, `NFR-BUD-001`, `INV-7` (budget accounting);
  `NFR-AUD-001`, `INV-6` (participation truth and sanitized audit);
  `FR-DQG-005` (report artifacts); `NFR-BC-001`/`INV-8` (compatibility).
  No new requirement ID is created merely to name this maintenance correction.

## Context

The 2026-11-06 and 2026-11-10 live runs (logbook 073; DEBT-021/033;
RISK-021/028/029) showed two coupled defects:

1. **Budget accounting used character-based estimates.** `record_call_usage`
   derived both elapsed time and tokens from `prompt+response` characters. In the
   live run the Bull call actually took 19.70 s and used 16,931 provider tokens,
   but the runtime estimated 2,024.4 s / 15,183 tokens. The pre-call guard then
   refused Bear (`budget_exhausted`) although the real 600 s cap was never
   approached. The guard was safe; the accounting *basis* was wrong.
2. **The Research Manager attributed content to a speaker that never ran.** The
   manager prompt unconditionally asserted "the debate always contains
   conflicting arguments", and the live prose said "the bear overplayed its
   hand" although Bear produced no response (Bear was refused pre-call).

Both defects misrepresent runtime facts to a reader of the report.

## Decision

### A. Measured budget accounting (FR-DDT-003 / NFR-BUD-001 / INV-7)

- Each real Bull/Bear `llm.invoke` is timed with an **injectable monotonic
  clock**. Measured elapsed time is the basis; character-based time estimation
  is **not** revived, and a missing elapsed time is recorded as *unavailable*,
  never invented as zero.
- **Invalid / backwards / non-finite clock readings abort (fail closed).** An
  invalid *initial* reading aborts **before** `llm.invoke`; an invalid *end*
  reading persists unavailable telemetry plus a sanitized audit entry, then
  aborts. Monotonic validation is `end >= start` only — a shorter second call is
  not "backwards".
- Provider-reported token usage is preferred. A valid provider `total_tokens`
  alone is usable; missing input/output components stay `null`. An
  input-only/output-only count is **partial** and is not treated as a complete
  exact total (missing side filled with a tagged estimate). Conflicting metadata
  retains originals, sets a conflict flag, and uses a labelled
  **derived/conflicted** conservative total — never presented as provider-exact.
- **Logical invocations** (`calls`) are distinct from **transport attempts**;
  transport attempts are `null`/unknown unless actually observed (SDK retry
  limits are not evidence of retries).
- **Legacy estimated totals are never relabelled measured:** appending a measured
  call to an estimated checkpoint yields an honest *mixed/estimated* aggregate.

### B. Truthful participation and sanitized audit (NFR-AUD-001 / INV-6)

- A pure `tradingagents/debate/participation.py::summarize_participation` derives
  execution from **structured turns**, merging the TOP-LEVEL
  `debate_termination_decision` (including a `refused_speaker` nested in the
  trace) and the gate verdict. **Legacy prose alone does not prove execution**; a
  missing/conflicting structured state is reported `unverified`/`unknown`. A
  blocked run with zero turns reports an explicit `data_quality_blocked` skip.
- The Research Manager receives the authoritative participation block and never
  asserts a two-sided debate when one did not occur. When there is **positive
  evidence the debate was incomplete** (exactly one or zero authoritative
  speakers, e.g. a pre-call refusal), the **trusted** `investment_plan` is
  replaced by a deterministic **SAFE PARTIAL-DEBATE TEMPLATE**: it names the
  executed/unknown/skipped speakers and reason, labels the assessment
  single-sided/incomplete, and preserves the model's **valid rating policy** (no
  automatic Hold coercion). The raw model narrative is quarantined as separate
  redacted, non-authoritative audit text and never enters the trusted
  plan/report/memory.
- Aborted invocations re-raise; a sanitized, append-only **failure ledger**
  records only allow-listed `error_class`/status/constant `reason` and safe
  numeric usage — never exception messages, prompts, response bodies or auth.
  Writing the ledger does **not** advance a failed checkpoint; cross-resume
  hard-budget accounting is an explicit, documented limit.

### C. Reports (FR-DQG-005)

`run_summary.json` and `debate_trace.json` surface per-field usage provenance
(`measured`/`provider`/`estimated`/`mixed`/`unavailable`), participation, stop
reason, and provider split counts only when complete (partial splits reported
`null`/partial). No new global/all-agent instrumentation is claimed.

## Consequences

- **Positive:** the budget guard now acts on measured time; a report cannot claim
  an unexecuted opponent spoke in a positively-partial debate; usage provenance
  is explicit per field; aborts leave a sanitized trail.
- **Tradeoff:** the authoritative partial-debate plan is *less narratively
  detailed* (deterministic template instead of free model prose). Genuine
  two-sided behaviour is unchanged.
- **Explicit limits (not claimed fixed):**
  - Any debate that is NOT an authoritatively-confirmed two-sided debate —
    **partial OR unknown/legacy** — uses the deterministic trusted template, so
    the trusted plan never carries unverified bilateral attribution and there is
    no wrapper-only contradiction. The raw model narrative is quarantined to a
    default durable path derived from `results_dir`/identity when no explicit path
    is configured.
  - A blocked run keeps its existing evidence-insufficient rationale (the
    manager prompt already states there was no normal debate and forbids
    attribution); the deterministic participation block is authoritative in the
    report/summary, and a blocked run that is partial/unknown also uses the
    deterministic trusted template (Hold re-pinned on top), so blocked trusted
    prose is not left carrying invented absent-opponent attribution.
  - The failure ledger does not make failed runs resumable or solve cross-resume
    budget accounting.
  - The live token meter is an *observed-usage* stopping guard, not a provable
    physical upper bound on an unknown future request.

## Alternatives considered

- Raise the production budget thresholds — rejected: hides the accounting defect
  (DEBT-021 action explicitly forbids it).
- Coerce all partial debates to Hold — rejected: changes decision policy; the
  existing rating policy is preserved.
- Rewrite trusted prose with broad pattern replacement — rejected: brittle and
  unable to prove absence of hallucinated attribution; a deterministic template
  for positively-partial runs is safer.
