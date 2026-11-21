# `prompts/archive/` — historical Market Analyst prompt snapshots

> **Archival evidence only. These files are not Coding-Agent startup prompts and
> are not loaded as runtime configuration.**

The two YAML files in this directory are byte-preserving exports of the
**Market Analyst** runtime system prompt (`tradingagents/agents/analysts/
market_analyst.py`), taken at two historical commits. They are kept here because
their original filenames (`prompts/prompt_v1.0.yaml`, `prompts/prompt_v1.1.yaml`)
collided with the CS5351 **Coding-Agent startup prompt** lineage, which is a
different kind of artifact. The collision was resolved by keeping the Coding-Agent
prompts at their canonical paths and moving these Market Analyst snapshots here.

## What the files are

| Archive file | Historical version | Source commit | Source symbol |
| --- | --- | --- | --- |
| [`market-analyst-rc1-v1.0.yaml`](market-analyst-rc1-v1.0.yaml) | RC1 freeze, pre-single-pass | `9948bf8` (`9948bf8545cceeb0d7a60cda913a04826a06c007`) | `create_market_analyst().market_analyst_node.system_message` |
| [`market-analyst-final-v1.1.yaml`](market-analyst-final-v1.1.yaml) | Final remediation, single-pass era | `50b2ca3` (`50b2ca332a660531837d7c12e108141862651d97`) | same, plus the single-pass terminal instruction in `structured.py` |

Each file's YAML content is identical to the personal worktree's latest
`prompts/prompt_v1.0.yaml` / `prompts/prompt_v1.1.yaml`; the **only** difference is
that one trailing blank line was removed so the file ends with a single newline
for `git diff --check` cleanliness. The delta was verified with `diff` (one blank
line at EOF only).

| Archive file | Source SHA-256 (personal worktree) | Archive SHA-256 (this tree) |
| --- | --- | --- |
| `market-analyst-rc1-v1.0.yaml` | `22d739518e7c3d926755cf4273269dc3bcbafa3d26c6d2cf03ca2331b5ea45d0` | `8dc013ab1264fac197f919bac5511534be167f24dced8534f4b94bdcfb8b1de1` |
| `market-analyst-final-v1.1.yaml` | `aa852fb442f2069c37b3bb5ddb5c585d1119c73762cae6f8e0d90bd4006864ab` | `f08c041e23aa523126cd0ff236bc941f1d1882c009bd502ae04b79c1962727ff` |

Their internal `evidence.prompt_sha256` records the hash of the extracted
**prompt text**, not of the YAML file.

## What they are not

- They are **not** the Coding-Agent governance startup prompts. Those remain at
  [`../prompt_v1.0.yaml`](../prompt_v1.0.yaml) (read-only analysis, historical),
  [`../prompt_v1.1.yaml`](../prompt_v1.1.yaml) (implementation, historical),
  [`../prompt_v1.2.yaml`](../prompt_v1.2.yaml) (prior authoritative), and
  [`../prompt_v1.3.yaml`](../prompt_v1.3.yaml) (**current authoritative**).
- They are **not** read by the application, the graph, or any loader. The runtime
  prompt is hardcoded in `tradingagents/agents/analysts/market_analyst.py`; that
  file was not modified by this archive.
- Copying or editing these YAML files does **not** change any runtime prompt.

## Why the two snapshots exist

`v1.0` records the RC1 two-call market-analyst brief. `v1.1` records the same
brief in the single-pass era; its `identity_check` states that the analyst brief
text is byte-identical (`sha256 9f7a07aa…`) and that the version delta is the
single-pass execution path and its terminal instruction, not a rewritten brief.
They are evidence for the historical claim, not configuration.

## Safe to delete?

No. They are referenced as design/evidence artifacts by the token-observability
requirements and ADRs (ADR-013–ADR-018) and by the evaluation record. Removing
them would break that historical traceability.
