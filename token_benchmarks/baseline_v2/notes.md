# baseline_v2

## Purpose

Repeat the token-consumption baseline on the fixed observability harness
(tool-call attribution, single telemetry artifact per measured run).

Configuration is identical to `baseline_v1`; only `experiment_id` differs.

## Changes

No token optimization.
Observability/integration fixes only:

- tool-call callbacks now reach the tool nodes (tool calls are attributed);
- one telemetry artifact per run, selected from a pre-run snapshot;
- a run with an unaccounted LLM call (no provider usage) is not a measured
  sample;
- an invalid attempt is retried in a fresh `runs/run_NN/attempt_MM` directory
  (earlier attempts are preserved as evidence, never overwritten);
- `openai_compatible` now honours the configured SDK retry budget.

## Attempts

- run_01: valid, reused as-is. `attempt_02` was started and then interrupted
  before it produced telemetry; it is kept on disk but is not a sample (the
  finished `attempt_01` remains the measured attempt).
- run_02 attempt_01: not a measured sample — one `OpenAITimeoutError` call left
  the run with a failed LLM call (`llm_call_errors`); kept on disk as evidence.
- run_02 attempt_02+: retries of the same measured run.

## Provenance and reproducibility caveat

These results are a **historical experiment**, not a measurement of the current
working tree. Do not cite them as "produced by HEAD".

- `code_state.json` (the recorded environment snapshot) was written before the
  final observability and benchmark-harness edits landed. Its
  `git_diff_sha256` does **not** match the current working-tree diff, and no
  per-run `code_state.json` was captured, so the exact tree that produced each
  run cannot be verified from the files on disk. The snapshot is left untouched
  rather than rewritten — overwriting it would fabricate provenance.
- The reports were regenerated from the stored telemetry in `runs/` (not from a
  new LLM run) to drop host absolute paths. All numeric fields are unchanged
  from the original run; only `telemetry_path` (now relative to this directory)
  and the added `invalid_reason` / `llm_errors` fields differ.
- `runs/`, `summary_index.json`, and `code_state.json` stay unversioned: they are
  large, machine-specific, or environment-specific. The committed `summary.*`
  files are the reviewed, de-identified artifact.

## Hypothesis

N/A — baseline measurement.

## Compared with

`baseline_v1` (same configuration; not directly comparable per-token because
the earlier harness could not attribute all tool calls).
