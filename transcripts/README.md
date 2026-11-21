# Transcripts (course deliverable D5)

This directory holds the student-annotated transcript required by the course
submission. It records how AI assistance was used on the project: the requests
that mattered, what the AI produced, what the human accepted, rejected or
changed, and how the work was verified. It is not a raw chat-log dump and it is
not a replacement for the code, tests or evidence.

## Status

**NO SIGNED STUDENT TRANSCRIPT HAS BEEN DELIVERED YET.**

- [`60726054-WangTianQi.md`](60726054-WangTianQi.md) is an **AI-assisted
  transcript reviewed and confirmed by WangTianQi (60726054) on 2026-11-21**.
  It is structurally complete and evidence-grounded; the formal final
  attestation/signature remains **unsigned**. It must not be represented as a
  signed transcript, and content review is not an independent experimental
  reproduction.
- [`60536848-WANG-Yiwen.md`](60536848-WANG-Yiwen.md) is the teammate's existing
  human-supervision transcript. It is preserved **unchanged** and is not part of
  WangTianQi's personal deliverable.
- [`TEMPLATE_student-id-student-name.md`](TEMPLATE_student-id-student-name.md) is
  the reusable placeholder template; it is not a transcript.

## What WangTianQi must still do before this is final

Open `transcripts/60726054-WangTianQi.md` and complete:

1. Every entry marked `HUMAN_CONFIRMATION_REQUIRED` — your own reasoning for the
   decisions, especially the Stage 4/6 rejections, the Stage-2 rollback, the
   V2 halt, the Finnhub-only scope, and the Single-Pass/Batch-Macro decisions.
2. The four reflection areas referenced in `Report.md` §7 (motivation; the V2
   halt and re-freezes; lessons about measurement, evidence and audit
   independence; whether the freeze/audit overhead was justified).
3. The dated paid-run authorization for the V2/V3 batches, or an explicit
   statement that no dated artefact exists (`DEBT-052`).
4. The session-authorship and commit-author confirmations (`DEBT-053`).
5. The final attestation and date (currently blank and unsigned).

Content review is complete (2026-11-21); the final signature remains
`PENDING_HUMAN_CONFIRMATION`.

## D5 requirements

A compliant transcript:

- **Identifies the student.** File name `<student-id>-<student-name>.md`; the
  header repeats the student ID, name, course (CS5351) and submission date.
- **Is annotated, not raw.** Each entry says what the human asked, what the AI
  produced, what the human decided, and *why*. Unedited model output is not
  sufficient.
- **Covers the real work,** including the pre-V2 period (September–November),
  the CAND-01 experiments, verification, corrections and rejected suggestions.
  It does not claim work the student did not do.
- **Separates claim from evidence.** Every non-trivial claim points to a file,
  test, command, commit, or recorded result. If something was not verified, the
  transcript says `NOT_VERIFIED`.
- **Is honest about failures.** Known failures, invalid runs, limitations and
  abandoned ideas are recorded, not hidden.
- **Contains no secrets.** Never paste an API key, bearer token, `.env` value or
  private key. Redact keys as `[REDACTED]`.
- **Is in English** and is readable by the course staff without running the code.

## Privacy and secrets

Do not paste credentials, private data, or full third-party news/prompt content.
Quote short excerpts only where they are needed to explain a decision. The
compliance validator scans this directory for obvious secret patterns and will
fail if it finds one.

## File map

| File | Purpose |
| --- | --- |
| `README.md` | This policy and status. |
| `TEMPLATE_student-id-student-name.md` | Placeholder template; not a transcript. |
| `60726054-WangTianQi.md` | AI-assisted; content reviewed/confirmed by WangTianQi (2026-11-21); signature pending. |
| `60536848-WANG-Yiwen.md` | The teammate's preserved human-supervision transcript. Do not edit. |
| `<student-id>-<student-name>.md` | A real human-annotated transcript. None is signed yet. |
