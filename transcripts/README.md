# Transcripts (deliverable D5)

This directory holds the **student-annotated transcript** required by the course
submission. It is a human-authored record of how AI assistance was used on the
project: the prompts that mattered, the outputs that mattered, what the human
accepted or rejected, and how the claimed work was verified. It is not a raw
chat-log dump and it is not a replacement for the code, tests, or evidence.

## Status

**PENDING_HUMAN_CONFIRMATION.** No real student-annotated transcript is committed
yet. The only file besides this README is
[`TEMPLATE_student-id-student-name.md`](TEMPLATE_student-id-student-name.md),
which contains placeholders only. A human must:

1. copy the template to `<student-id>-<student-name>.md`;
2. fill it with real, dated, first-person annotations from their own work;
3. remove every `PENDING_HUMAN_CONFIRMATION` / placeholder marker;
4. confirm the identity and the content before submission.

The validator reports the missing real transcript as a **warning**, not a failure,
because this is a human deliverable. It must not be faked with generated content.

## D5 requirements

A compliant transcript:

- **Identifies the student.** File name `<student-id>-<student-name>.md`; the
  header repeats the student ID, name, course (CS5351), and submission date.
- **Is annotated, not raw.** Each entry says what the human asked, what the AI
  produced, what the human decided, and *why*. Unedited model output is not
  sufficient.
- **Covers the real work.** It discusses the requirements, the observability and
  single-pass work, the CAND-01 experiments, verification, and any correction or
  rejected suggestion. It does not claim work the student did not do.
- **Separates claim from evidence.** Every non-trivial claim points to a file,
  test, command, commit, or recorded result. If something was not verified, the
  transcript says `NOT_VERIFIED`.
- **Is honest about failures.** Known failures, limitations, and abandoned ideas
  are recorded, not hidden. Results are not fabricated or "repaired".
- **Contains no secrets.** Never paste an API key, bearer token, `.env` value, or
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
| `<student-id>-<student-name>.md` | The real human-annotated transcript (to be added). |
