# Runtime Policy Catalog

This catalog lists the deterministic policy/config surface that controls the
CS5351 feature behavior. It is the reference for the settings that are
validated before graph execution, plus their safe defaults. The authoritative
default values live in the source; this document records their meaning.

## Data Quality Gate policy (evidence)

`tradingagents/evidence/policy.py` defines `MarketPolicy`, `MarketRecordPolicy`,
and `MetricTolerance` using quantized `Decimal`. The `policy_version` is carried
on every `GateDecision` for auditability (`NFR-AUD-001`).

| Setting | Meaning | Default |
| --- | --- | --- |
| `policy_version` | Stamped policy version on every gate verdict | (recorded on the policy object) |
| `min_independent_sources` | Independently credible sources required for a `High` group | see `DEFAULT_MARKET_POLICY` |
| threshold tolerances | Per-metric Decimal tolerances for cross-source consistency | see `MetricTolerance` |

Semantics are confirmed by the policy object; the exact numeric defaults are in
`tradingagents/evidence/policy.py` and are not re-invented here.

## Debate termination policy (config)

`tradingagents/debate/config.py` defines `DEFAULT_DEBATE_TERMINATION_CONFIG`
(tuned by `resolve_debate_termination_config`). All fields are validated by
`DebateTerminationConfig.validate`; a frozen instance cannot diverge afterward.

| Setting | Meaning | Default |
| --- | --- | --- |
| `enabled` | `True` uses dynamic rules; `False` reproduces legacy fixed-round routing | `True` |
| `no_new_evidence_patience` | Rounds of no-new-valid-evidence before `no_new_evidence` stop | `1` |
| `stance_distance_threshold` | Max rating distance for "stances close" | `1.0` |
| `confidence_delta_threshold` | Max confidence delta for "close" and "material change" | `0.25` |
| `max_calls` | Hard limit on LLM calls | `2_000_000` |
| `max_tokens` | Hard limit on tokens | `2_000_000` |
| `max_time` | Hard limit on elapsed seconds | `600.0` |
| `reserved_summary_tokens` | Reserved summary token reserve | `4_000` |
| `reserved_summary_seconds` | Reserved summary time reserve | `90.0` |
| `next_round_estimate_tokens` | Estimated next-round token cost for budget accounting | `2_000` |
| `next_round_estimate_seconds` | Estimated next-round time cost for budget accounting | `60.0` |
| `max_debate_rounds` | Legacy fixed-round cap (used when `enabled=False` / rule ordering) | `1` |
| `evidence_manifest_field` | AgentState field holding gate manifest evidence records | `data_quality_evidence_records` |
| `trace_field` | AgentState field holding the termination decision trace | `debate_termination_decision` |

## Budget accounting

`tradingagents/debate/budget.py` estimates and accounts for token/time/call
usage deterministically. The summary reserve is checked before a `continue`
verdict so a run can never exhaust budget mid-debate without its report
(`NFR-BUD-001`, `FR-DDT-003`).

## Enforcement

A misconfigured `debate_termination` block raises `ValueError` in `validate`
before graph execution, so a bad config is reported explicitly rather than
silently degrading to a default (`FR-DDT-004`, `NFR-BC-001`).