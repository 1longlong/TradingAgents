# Architecture Invariants

These invariants are the properties the delivered tree is expected to preserve. They
are stated at the level a test can decide, with a positive test and a negative
(mutation or guard) test. Status meanings:

- **ENFORCED** — a checked-in test or verifier fails if the property is broken on the
  covered path.
- **PARTIAL** — the property is enforced on named paths, but there is no central
  mechanism that makes it hold for every future path. The gap is stated.
- **DOCUMENTED_ONLY** — no executable check; review only. (None of the invariants below
  is DOCUMENTED_ONLY in the delivered tree.)

The requirements baseline is `docs/req/requirements.yaml` (retrospective). The source
hint names the requirement ID and, where relevant, the ADR that explains the decision.
All paths are in this worktree.

---

## INV-1 — Missing provider usage is UNKNOWN, never zero

**Statement.** A provider call that did not report a usage field is recorded with that
field `null`, and the run's totals do not add zero for it. An omitted field is counted
in `calls_missing_input_tokens` / `calls_missing_output_tokens`; it is not converted
into a measured zero. `usage_coverage.complete` is true only when every call reported
usage **and** both token fields were present.

**Source requirement.** FR-011 (U-1 verdict), NFR-001 (measured accounting); ADR-001.

**Enforcer.**
- `tradingagents/observability.py:881-923` (`record_llm_call`: missing fields increment
  counters, the sum is not incremented).
- `tradingagents/observability.py:1474-1700` (`_extract_usage` / metadata parsing:
  absent values stay `None`).
- `tradingagents/observability.py:1900-1930` (usage coverage requires both fields).
- `scripts/token_benchmark.py:569-790` (`usage_verdict`: `MISSING` / `INCOMPLETE`).

**Positive test.**
`tests/test_observability.py::TestTokenUsage::test_missing_usage_is_unknown_not_zero`
and `::TestPartialUsageIsNotZero::test_omitted_input_tokens_are_counted_not_zeroed`;
`tests/test_c3_final_freeze.py::TestUsageVerdict::test_missing_usage_is_missing_and_totals_are_null_not_zero`.

**Negative test (guard).**
`tests/test_observability.py::TestPartialUsageIsNotZero::test_partial_payload_does_not_count_as_complete_coverage`
and `tests/test_c3_final_freeze.py::TestUsageVerdict::test_usage_counts_that_do_not_add_up_are_a_mismatch`
fail if a partial payload is promoted to complete; the mutation "use `or 0` when summing"
is caught by the missing-field assertion in the first test.

**Status.** ENFORCED.

---

## INV-2 — Run totals close over agent + system + unattributed

**Statement.** For every finished run, `run_totals.llm_calls` equals the sum of the
agent buckets, the system-component buckets, and the unattributed bucket; the same
holds for input and output tokens. No provider call is dropped from the total because
of who made it.

**Source requirement.** FR-004 AC-02, NFR-001 AC-02; ADR-001.

**Enforcer.**
- `tradingagents/observability.py:1739-1900` (`_build_telemetry_dict`: every LLM/tool
  event is bucketed exactly once; `run_totals` sums all buckets).
- `tradingagents/observability.py:1925-1972` (`attribution_summary`: agent, system,
  unattributed counts and tokens).
- `scripts/token_benchmark.py:569-790` (the attribution summary must account for every
  call, otherwise `MISMATCH`).

**Positive test.**
`tests/test_system_attribution.py::TestReflectorAttribution::test_totals_close_across_agents_and_system_components`
and `tests/test_observability.py::TestRunAggregates::test_run_totals_are_sum_of_agents`.

**Negative test (guard).**
`tests/test_system_attribution.py::TestAttributionIntegrityGuards::test_a_tampered_flag_cannot_hide_an_unattributed_event`
and `tests/test_c3_final_freeze.py::TestUsageVerdict::test_unattributed_usage_fails_closed`
fail if an event is excluded from the totals or hidden by a flag.

**Status.** ENFORCED.

---

## INV-3 — Every provider call is attributed to an agent or a declared system component

**Statement.** A provider event carries exactly one attribution: a stable agent id
(`agent`), a declared component id (`system`), or `none`. There is no fourth state. An
`agent` id cannot be used as a system component and vice versa, and an event with no
scope remains `none`. A measured run with a `none` event is `INCOMPLETE` and is not
used as evidence.

**Source requirement.** FR-004 (all ACs); ADR-001.

**Enforcer.**
- `tradingagents/observability.py:301-405` (`AttributionContext`, `agent_scoped`,
  `system_component_scoped`, identity guards).
- `tradingagents/observability.py:1850-1972` (separate `system_components` bucket;
  `unattributed` pseudo-agent).
- `scripts/token_benchmark.py:730-770` (an event with `attribution_type="none"`, or a
  schema-1 event with `agent_id="unattributed"`, is `INCOMPLETE`).

**Positive test.**
`tests/test_system_attribution.py::TestReflectorAttribution::test_reflector_call_is_a_system_component_not_an_agent`
and `::test_an_unscoped_call_is_none_and_makes_the_run_incomplete`.

**Negative test (guard).**
`tests/test_system_attribution.py::TestAttributionIntegrityGuards::test_an_agent_id_cannot_be_used_as_a_system_component`
and `::test_a_system_component_id_cannot_be_used_as_an_agent`;
`::TestHarnessAcceptsSystemAttribution::test_an_unattributed_event_still_invalidates_it`.

**Status.** PARTIAL. The product records attribution and exposes the completeness flag;
it does not abort a run on an unattributed call. The measured-run invalidation is
enforced by `scripts/token_benchmark.py`, not by `TradingAgentsGraph`. A production run
that never reads the harness can still proceed with `none` events.

---

## INV-4 — No provider request carries a dangling tool_call

**Statement.** A request sent to a provider must not contain an assistant turn whose
`tool_calls` have no matching `ToolMessage` in the request. This covers the retry after
an invalid schema call, the terminal message sequence returned by a single-pass
analyst, and a mixed schema+data turn.

**Source requirement.** FR-005 AC-03; ADR-006.

**Enforcer.**
- `tradingagents/agents/utils/structured.py:807-854` (`_free_text_retry` drops only a
  trailing assistant turn that carries tool calls, then invokes through `prompt | llm`).
- `tradingagents/agents/utils/structured.py:726-806` (`_terminal_messages`: returns
  executed turns paired with their results and ends on a no-tool-call assistant turn).
- `tradingagents/agents/utils/structured.py:962-1010` (mixed turn: keep only data calls
  on the assistant turn; strip the schema call).
- `tests/test_cand01_single_pass_finalization.py::CompiledGraphLoopTest::test_returned_state_has_no_dangling_tool_call`
  is the executable assertion over a compiled graph.

**Positive test.**
`tests/test_final_remediation.py::TestR12Fallback::test_invalid_stance_retry_has_no_dangling_tool_call`;
`tests/test_final_remediation.py::TestAuditAFollowUps::test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call`;
`tests/test_cand01_single_pass_finalization.py::TerminalMessageRoutingTest::test_schema_after_a_tool_round_keeps_call_and_result_paired`.

**Negative test (mutation/guard).**
`tests/test_final_remediation.py::TestR12Fallback::test_a_complete_tool_pairing_is_not_broken`
guards the over-deletion direction (a legal pairing must survive). The documented
mutation "do not pop the dangling assistant turn" makes
`test_invalid_stance_retry_has_no_dangling_tool_call` fail
(`token_benchmarks/final_remediation_20261116/TEST_RESULTS.md` §5).

**Status.** PARTIAL. The fix and the tests cover the four request-construction points
that exist (retry, terminal sequence, mixed turn, two-call fallback). There is no
global request builder that enforces pairing, so a new provider call path could
reintroduce a dangling call without an existing test failing.

---

## INV-5 — Tool-call protocol markup never becomes an analyst report

**Statement.** `market_report`, `news_report`, and `fundamentals_report` must not be
raw tool-call protocol markup (DeepSeek DSML or equivalent). If a model returns markup,
the report is either recovered analysis text or an explicit
`[REPORT UNAVAILABLE — …]` sentence; it is never the markup and never silently empty
because of markup.

**Source requirement.** FR-003, FR-005 AC-03; ADR-006.

**Enforcer.**
- `tradingagents/agents/utils/structured.py:392-481` (`looks_like_protocol_markup`,
  `sanitize_analyst_text`: prose-before-marker, parameter recovery, explicit
  unavailable template).
- Applied at the single-pass prose exit
  (`structured.py:1028-1050`), the retry
  (`structured.py:807-854`), both `structured_llm is None` exits
  (`structured.py:238-245`, `533-537`), and the two-call fallback
  (`structured.py:552-561`).

**Positive test.**
`tests/test_final_remediation.py::TestDsmlSanitizer::test_r07_markup_is_recovered_without_markers`,
`::test_r14_markup_becomes_an_explicit_unavailable_report`,
`::test_markup_in_the_single_pass_fallback_never_reaches_the_report`;
`::TestAuditAFollowUps::test_a_non_empty_prose_turn_is_sanitized_too`.

**Negative test (mutation/guard).**
`tests/test_final_remediation.py::TestDsmlSanitizer::test_clean_text_is_untouched` and
`::TestAuditAFollowUps::test_analysis_before_markup_is_kept` guard against over-stripping
(clean text and real prose must survive). The documented mutation "skip
`sanitize_analyst_text`" fails the markup-reaches-report test
(`TEST_RESULTS.md` §5).

**Status.** PARTIAL. Sanitation is applied at the four known report exits, not at a
single output chokepoint. A new analyst return path that bypasses those exits would not
be covered by an existing test.

---

## INV-6 — Point-in-time: no dated path may read after the trade date

**Statement.** A run dated `D` may not use market, news, social, fundamentals, macro,
prediction-market, or memory information that was not available by `D`. A model-supplied
later date is clamped to `D`; a news window uses an exclusive upper bound; an undated
item is excluded in a historical run; a present-day company profile is withheld; and a
past lesson is admitted only if its outcome was resolved by `D`.

**Source requirement.** FR-007 (all ACs); ADR-002 (single-pass date injection),
ADR-005 (memory PIT).

**Enforcer.**
- `tradingagents/graph/trading_graph.py:55-66` (canonical, non-future trade date).
- `tradingagents/dataflows/date_window.py:115-138` (`as_of`, `as_of_window`).
- `tradingagents/dataflows/date_window.py:141-162` (`publication_cutoff`).
- `tradingagents/dataflows/date_window.py:24-32` (half-open window; undated only when
  live).
- `tradingagents/dataflows/date_window.py:165-191` (`withhold_live_profile`).
- Injected `trade_date` in every dated tool (`agents/utils/*_tools.py`,
  `structured.py:571-725`).
- `tradingagents/graph/trading_graph.py:423-432` and
  `tradingagents/agents/utils/memory.py:73-110` (memory as-of).

**Positive test.**
`tests/test_tool_date_enforcement.py::test_future_curr_date_from_the_model_is_clamped`,
`::test_future_window_from_the_model_is_clamped`,
`::test_get_news_injects_the_trade_date_as_the_publication_cutoff`,
`::test_propagate_rejects_a_future_date`;
`tests/test_news_lookahead.py::test_window_excludes_future_and_undated_in_backtest`,
`::test_upper_bound_is_exclusive`;
`tests/test_memory_pointintime.py`; `tests/test_fundamentals_lookahead.py`.

**Negative test (guard).**
`tests/test_cand01_single_pass_finalization.py::TradeDatePrecedenceTest::test_model_supplying_a_future_date_cannot_move_the_window`
and `::test_model_supplying_an_earlier_date_cannot_move_the_window` fail if the model's
argument wins over state; `tests/test_news_lookahead.py::test_offset_aware_timestamp_is_converted_not_truncated`
guards against timezone truncation admitting post-cutoff news.

**Status.** PARTIAL. Every dated path exercised by the tests is covered, and the shared
helpers make the rule reusable. There is no global PIT middleware: a new vendor or a
new tool that does not call `as_of`/`as_of_window` or declare `InjectedState("trade_date")`
is not automatically bounded. The requirement is stated as a capability on the delivered
paths, not as a universal runtime guarantee.

---

## INV-7 — Each measured run starts from one immutable memory snapshot and writes only its own copy

**Statement.** In the experiment harness, every run begins from a byte-identical copy
of one registered baseline snapshot; the copy lives inside the run's own attempt
directory, differs from the baseline path, and the baseline hash is unchanged after the
run. A missing snapshot, a changed hash, a modified copy, a copy outside the attempt, or
a V3 registration without a memory block is refused before spending. A changed baseline
after the run marks the sample `INVALID` with `memory_snapshot_modified`.

**Source requirement.** FR-009 (all ACs); ADR-005.

**Enforcer.**
- `scripts/token_benchmark.py:2483+` (`prepare_run_spec`: copy + hash + state).
- `scripts/token_benchmark.py:4161-4180` (`_config_for_spec`: `memory_log_path` is the
  run copy, set before graph construction).
- `scripts/token_benchmark.py:3784+` (`_preflight_gate`) and `4230+`
  (`_guard_spending_path`).
- `scripts/token_benchmark.py:2715`, `2878` (`memory_snapshot_modified` invalidation).
- Memory block hashed into `config_sha256` by `gen_cand01_batch_16run_specs_v3.py`.

**Positive test.**
`tests/test_memory_isolation.py::TestSnapshotAndCopy::test_every_run_gets_its_own_copy_of_the_same_snapshot`,
`::test_a_write_to_one_run_copy_leaves_the_others_untouched`,
`::test_run_order_does_not_change_any_run_initial_state`;
`::TestConfigAndReflector::test_a_pending_entry_in_one_run_copy_does_not_trigger_the_next_runs_reflector`.

**Negative test (guard).**
`tests/test_memory_isolation.py::TestValidationFailsClosed` — changed snapshot, missing
snapshot, modified copy, copy equal to baseline, copy outside the attempt, wrong hash,
missing mode, missing memory block are each refused;
`::TestHarnessRecordsMemory::test_a_modified_baseline_invalidates_the_run`.

**Status.** ENFORCED for the experiment harness. This is not product behaviour: a normal
`propagate()` run still uses one shared `~/.tradingagents/memory/trading_memory.md`.

---

## INV-8 — Frozen specs, manifests, and tags are immutable and independently verified

**Statement.** A frozen batch is reproducible from a commit + annotated tag + freeze
record + per-file manifest + per-run config hashes. The verifier must recompute every
recorded digest from the tree; a tampered manifest, a moved tag, a dirty tree, a
changed spec, or a missing record must fail the verification and block spending.

**Source requirement.** NFR-002 (all ACs); ADR-005 (memory hash participates in the
freeze).

**Enforcer.**
- `scripts/c3_verify_final_freeze.py:1-80` (HEAD/tree/clean-tree/fingerprint/manifest/
  16 config hashes/protocol/generator/budget/path/tag checks).
- `scripts/c3_finalize_freeze.py` (writes the record from the tree).
- `scripts/c3_verify_protocol_freeze.py`, `scripts/c3_preflight_gate.py`,
  `scripts/c3_build_manifest.py`.
- `scripts/token_benchmark.py::verify_frozen_tree` and `verify_import_root`.

**Positive test.**
`tests/test_c3_final_freeze.py::TestFreezeDesignation::test_the_final_freeze_is_generated_from_the_tree_not_typed`,
`::test_the_verifier_recomputes_every_recorded_digest`,
`::TestManifestCoverage::test_the_manifest_covers_every_batch_file_that_ships`;
`tests/test_c3_regressions.py::test_a_sealed_release_is_not_resealed_by_accident`.

**Negative test (guard).**
`tests/test_c3_final_freeze.py::TestFreezeDesignation::test_a_tree_without_a_record_is_not_a_freeze`
and `::test_the_verifier_requires_head_to_equal_the_record`;
`tests/test_c3_final_freeze.py::TestEffectiveConfig::test_a_tampered_hash_is_refused`,
`::test_editing_a_registration_moves_the_fingerprint`,
`::test_deleting_a_frozen_field_is_refused`.

**Status.** ENFORCED. The verifier is executable and the freeze tests fail on tampering.
The residual is operational: the final tag is local (only the branch was pushed; the tags were not), and the verifier's
"clean tree" check means an uncommitted documentation edit can fail a freeze check even
when the code is correct.

---

## INV-9 — Single-pass is off by default and requires structured output

**Statement.** `single_pass_finalization_enabled` defaults to `False`. Enabling it
without `structured_analyst_output_enabled` has no effect: the analyst uses the RC1
two-call path. The shipped configuration is therefore the RC1 behaviour.

**Source requirement.** FR-005; ADR-002.

**Enforcer.**
- `tradingagents/default_config.py:138-143` (default `False`).
- `tradingagents/graph/setup.py:88-93` (single-pass requires structured).
- `tradingagents/agents/analysts/{market,news,fundamentals}_analyst.py` (the switch is
  read at construction; the default argument is `single_pass=False`).

**Positive test.**
`tests/test_cand01_single_pass_finalization.py::RegressionTest::test_single_pass_is_off_by_default_in_the_shipped_config`,
`::test_analyst_factories_default_to_the_two_call_path`,
`::test_setup_requires_structured_before_enabling_single_pass`.

**Negative test (guard).**
`tests/test_ablation_switches.py::StructuredSwitchTest::test_off_binds_no_schema_for_all_three`
and `tests/test_cand01_single_pass_finalization.py::RegressionTest::test_rc1_two_call_functions_are_unchanged_and_still_exported`
fail if the switch leaks into the shipped path or removes RC1.

**Status.** ENFORCED.

---

## INV-10 — The batch-macro switch removes the tool from both the analyst and the ToolNode

**Statement.** When `batch_macro_enabled` is false, the news analyst does not bind
`get_macro_indicators_batch` and does not advertise it in the prompt, and the news
`ToolNode` does not contain it. The single-series `get_macro_indicators` remains
available. An OFF run cannot execute a batch call even if the model emits one.

**Source requirement.** FR-006 (all ACs); ADR-003.

**Enforcer.**
- `tradingagents/graph/setup.py:102-107` (passes the switch to the analyst).
- `tradingagents/agents/analysts/news_analyst.py:173-197` (tool list + prompt hint).
- `tradingagents/graph/trading_graph.py:253-267` (ToolNode list follows the same
  config).
- `tradingagents/graph/switch_verification.py` (the spec's switch value is verified
  against the graph).

**Positive test.**
`tests/test_ablation_switches.py::BatchMacroSwitchTest::test_on_binds_batch_tool`,
`::test_off_does_not_bind_batch_tool`,
`::test_off_keeps_every_other_tool`,
`::ConfigPlumbingTest::test_toolnode_honours_batch_switch`;
`tests/test_macro_batch.py::BindingTest::test_single_series_tool_still_bound_as_fallback`.

**Negative test (guard).**
`tests/test_ablation_switches.py::BatchMacroSwitchTest::test_prompt_does_not_advertise_an_unbound_tool`
fails if the prompt names a tool the OFF arm cannot call;
`tests/test_switch_consumption.py` fails if the graph does not consume the spec's value.

**Status.** ENFORCED. This is a configuration invariant, not a code deletion: the batch
tool still exists in the package and can be enabled explicitly.

---

## INV-11 — The configured news path is Finnhub-only and never contacts GDELT

**Statement.** Under the shipped configuration, company news routes only to
`get_news_finnhub_only`, which has no GDELT dependency; global news under the Finnhub
route returns `CONFIG_DISABLED` and fetches nothing. A Finnhub outage, a missing key, or
a global-news request must not cause a GDELT contact. GDELT remains available only by
explicitly changing the vendor configuration.

**Source requirement.** FR-008 (all ACs); ADR-004.

**Enforcer.**
- `tradingagents/dataflows/interface.py:132-149` (route map).
- `tradingagents/dataflows/finnhub_news.py:700-766` (`get_news_finnhub_only`,
  `get_global_news_finnhub`/`CONFIG_DISABLED`).
- `tradingagents/default_config.py:168-193` (`data_vendors`/`tool_vendors`).

**Positive test.**
`tests/test_finnhub_only_scope.py::test_get_news_never_contacts_gdelt`,
`::test_a_finnhub_outage_is_not_rescued_by_gdelt`,
`::test_global_news_is_explicitly_disabled_not_borrowed`,
`::test_the_disabled_global_path_fetches_nothing` (all use a GDELT tripwire).

**Negative test (guard).**
`tests/test_finnhub_only_scope.py::test_default_config_has_no_gdelt_news_route`
fails if the default is changed to a GDELT route;
`::test_single_provider_header_names_only_that_provider` fails if provenance is
misreported.

**Status.** ENFORCED for the shipped configuration. The GDELT implementation and its
tests still exist; the invariant is about the configured route, not about removing the
source from the repository.

---

## INV-12 — Tool rounds are counted once per non-empty model tool batch on both execution paths

**Statement.** A graph `ToolNode` invocation and a single-pass `run_data_tools` batch
each produce exactly one tool round for the owning agent. An empty batch produces no
round. A batch in which every call failed still produces one round with
`status="error"`. The two paths do not double-count the same batch.

**Source requirement.** NFR-001, FR-005; ADR-002, ADR-006.

**Enforcer.**
- `tradingagents/graph/setup.py:137-142` (graph ToolNode wrapped by
  `attrib_tool_round`).
- `tradingagents/observability.py:2419-2540` (`attrib_tool_round`, `record_tool_round`).
- `tradingagents/agents/utils/structured.py:668-699` (`run_data_tools._run`: one round
  per non-empty batch, error status when all calls failed).

**Positive test.**
`tests/test_final_remediation.py::TestToolRounds::test_one_model_turn_with_two_calls_is_one_round`,
`::test_two_rounds_are_two_rounds`,
`::test_a_failing_tool_still_counts_as_a_round`,
`::test_rounds_reach_the_telemetry_payload`;
`tests/test_observability.py::TestAttribToolRound::test_one_invocation_records_one_round`.

**Negative test (guard).**
`tests/test_final_remediation.py::TestToolRounds::test_no_tool_call_is_no_round`
guards against counting an empty batch; the documented mutation "delete the round hook"
fails four `TestToolRounds` tests (`TEST_RESULTS.md` §5).

**Status.** ENFORCED for runs after the fix. Historical V3 telemetry from `e3b5cca` has
`tool_rounds = 0` and is explicitly not rewritten; the invariant applies to new runs.

---

## INV-13 — A fallback never presents prose as a typed report

**Statement.** When a structured call fails or is unsupported, the report may be
free text, but the parsed report object is `None`. `report_obj` is non-`None` only when
the schema call succeeded and rendered a non-empty report. Downstream code can therefore
branch on the object without mistaking prose for data.

**Source requirement.** FR-003, FR-005; ADR-002, ADR-006.

**Enforcer.**
- `tradingagents/agents/utils/structured.py:486-561` (`finalize_analyst_report`: every
  fallback branch returns `(text, None)`).
- `tradingagents/agents/utils/structured.py:856-1087` (`finalize_single_pass`: every
  non-success return sets `None`).
- `tradingagents/agents/analysts/{market,fundamentals}_analyst.py` (state keys receive
  the returned object unchanged).
- `tradingagents/agents/utils/s2_context.py` (`has_s2_fields` requires a real object).

**Positive test.**
`tests/test_cand01_single_pass_finalization.py::BlankReportResidualTest::test_blank_report_is_never_a_typed_object`,
`::SchemaValidationTest::test_schema_call_produces_the_typed_object`;
`tests/test_structured_agents.py`.

**Negative test (guard).**
`tests/test_cand01_single_pass_finalization.py::FallbackTest::test_prose_answer_is_returned_unchanged_as_in_rc1`
and `::test_structured_off_runs_the_plain_loop` fail if a fallback result is wrapped in
the schema type; the residual test also pins that a blank report stays blank and is not
silently typed.

**Status.** ENFORCED.

---

## INV-14 — Telemetry artifacts contain no raw prompt, message, tool-result, news, or memory content

**Statement.** A telemetry artifact may contain counts, byte sizes, hashes,
fingerprints, ids, model/provider names, error class names, and sanitized usage blobs.
It must not contain prompt text, message content, tool-result bodies, news article text,
agent output, or memory contents.

**Source requirement.** NFR-001 (event-level observability without content);
ADR-001.

**Enforcer.**
- `tradingagents/observability.py:575-714` (event dataclasses store only sizes,
  fingerprints, hashes, ids, error classes).
- `tradingagents/observability.py:1739-2117` (`_build_telemetry_dict` serialises those
  fields only; no body fields exist to serialise).
- `tradingagents/observability.py:1474-1560` (`_sanitize_usage_raw` drops long strings
  and non-numeric values from the preserved usage blob).

**Positive test.**
`tests/test_observability.py::TestPromptDiagnostics::test_no_raw_content_persisted`,
`::TestToolExecution::test_raw_result_not_persisted`,
`::TestTelemetryPersistence::test_privacy_no_raw_content_in_artifact`,
`::test_privacy_excludes_wide_forbidden_content_set`.

**Negative test (guard).**
`tests/test_observability.py::TestTelemetryPersistence::test_privacy_excludes_wide_forbidden_content_set`
scans the artifact for a forbidden-content set (prompt text, tool bodies, state values,
memory text) and fails if any appears; adding a content field to an event would make the
artifact fail the scan.

**Status.** ENFORCED.

---

## Summary

| ID | Property | Status |
| --- | --- | --- |
| INV-1 | Missing usage is UNKNOWN, not zero | ENFORCED |
| INV-2 | Totals close over agent + system + unattributed | ENFORCED |
| INV-3 | Every provider call attributed; `none` voids measured run | PARTIAL (harness-enforced) |
| INV-4 | No dangling `tool_call` in provider requests | PARTIAL (known paths) |
| INV-5 | No protocol markup in analyst reports | PARTIAL (known exits) |
| INV-6 | PIT: no future data on dated paths | PARTIAL (no global middleware) |
| INV-7 | Per-run memory isolation | ENFORCED (harness only) |
| INV-8 | Frozen specs/manifests/tags immutable | ENFORCED |
| INV-9 | Single-pass off by default, structured-only | ENFORCED |
| INV-10 | Batch switch removes tool from analyst and ToolNode | ENFORCED |
| INV-11 | Configured news path is Finnhub-only | ENFORCED (config) |
| INV-12 | Tool rounds counted once per non-empty batch | ENFORCED (new runs) |
| INV-13 | Fallback never presents prose as typed | ENFORCED |
| INV-14 | Telemetry has no raw content | ENFORCED |

The PARTIAL statuses are the honest boundary: the tests prove the named paths, not a
universal property. The ADRs and the trace matrix identify the same boundary.
