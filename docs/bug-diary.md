# Bug Diary

Records defects detected during development and the corrections requested by
review. Only defects with observed evidence are listed; unknown defect details
are marked `TODO` rather than invented. Cross-references review in
`docs/review-memo.md` and `docs/ai-use-log.yaml`.

## Phase 3B — detected and corrected during review

The following defect classes were raised during the Codex/human review of the
Phase 3B debate work and addressed in the corresponding implementation pass.
They are recorded at class level because the detailed per-bed stack traces are
available in the annotated transcript
(`transcripts/60536848-WANG-Yiwen.md`).

- **Router fall-through crash risk (#1088-family).** A conditional router that
  can return a speaker label absent from the edge map would crash LangGraph on
  a fall-through. Corrected by making `DEBATE_PATH_MAP` and
  `DEBATE_EVALUATOR_PATH_MAP` complete so any fall-through maps to a registered
  node.
- **Non-deterministic / float-noisy comparisons.** Normalized financial
  comparisons were unreliable. Corrected by quantizing to `Decimal` via
  `quantize_decimal` and using deterministic ordering.
- **Acyclic serialization risk.** A nested `SourceAttempt` inside
  `EvidenceRecord` (or a back-reference cycle in `ValidationResult`) would break
  round-tripping. Corrected by keeping `SourceAttempt` separate (7 fields),
  referencing by `evidence_id` string only, and writing only `to_dict()` forms
  into `AgentState`.
- **Missing summary budget reserve.** A debate could continue until it exhausted
  budget mid-debate and lose its report. Corrected by reserving summary
  tokens/time before any `continue` verdict and enforcing hard max
  tokens/time/calls.
- **Debate continuing with zero new valid evidence.** Repeated rounds with no
  new evidence wasted cost. Corrected by the `no_new_evidence` rule (respecting
  `no_new_evidence_patience`).

## Known / open bug-like behaviors (not hidden)

- Date-sensitive cache tests (`DEBT-001`) and the network-reachability-dependent
  baseline test (`DEBT-002`) produce non-green full-suite results on some
  days/environments. These are behaviors to stabilize or document, not
  silent defects.

## TODO

- `TODO (60536848-WANG-Yiwen): Capture any additional per-defect stack-trace
  detail in the final annotated transcript if required for submission, without
  copying secrets.`