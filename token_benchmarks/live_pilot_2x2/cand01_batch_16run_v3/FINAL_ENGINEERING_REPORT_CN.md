# CAND-01 V3 工程修复最终报告

**日期：** 2026-11-16 · **基线：** `15270b1` / tree `c827f414…` / 指纹 `03c76db6…`
**结论：** 两个根因均已修复并有测试证据；新增 46 个测试全部通过；全量测试无新增失败；等待三方独立审计对新冻结版本的结论。

## 1. 两个根因是否彻底解决

### 1.1 根因一：Reflector 调用不可归属

**根因（已确认）：** `propagate()` 在 `graph.invoke()` 之前调用 `_resolve_pending_entries()` → `Reflector.reflect_on_final_decision()` → `quick_thinking_llm.invoke()`。Agent 作用域只由图节点包装器 `attrib_agent_node` 建立，图外的这次调用没有任何作用域，因此被记录为 `unattributed`。

**修复：** 用统一的归因上下文（`AttributionContext`，`ContextVar`）替换单一 agent 变量：
- `agent_scoped()` → `attribution_type="agent"`；
- 新增 `system_component_scoped()` → `attribution_type="system"` + `component_id`；
- 无作用域 → `"none"`，仍判 INVALID；
- `Reflector` 只把 `invoke` 包进 `system_component_scoped("pre_graph_reflector")`，prompt/模型/temperature/调用逻辑完全不变，**没有伪装成任何 Analyst**；
- 遥测 schema 升到 2，逐事件记录 `attribution_type`/`component_id`，系统组件单独成桶，`attribution` 汇总 agent/system/unattributed 的调用数与 token；
- `run_totals` 对三个桶求和，任何调用都不会因归属不同而丢失。

**证据：** `tests/test_system_attribution.py` 10/10 通过（真实 callback 路径 + fake chat model 携带 provider usage）：系统调用只进入 `system_components`；总量闭合（15+15+0=30）；成功/异常后作用域正确恢复；Agent 作用域内的系统调用不被误记为 Agent；无作用域调用仍为 `none` 且 run INVALID；harness 接受合法 system 事件、拒绝 unattributed。

### 1.2 根因二：Pipeline 之间共享 Memory

**根因（已确认）：** 单一开发日志跨运行共享；一次运行写入的 pending 条目会让下一次运行在进入图之前执行 Reflector 反思，改变那次运行的 prompt 上下文与 token 消耗（R05 → R06 即如此）。

**修复：**
- 唯一不可变快照 `memory/baseline_v3.md`（sha256 `e3b0c442…b855`（空快照，与所有 ticker 对称），0 条条目，0 pending（对称空快照，理由见 provenance））；来源、保留/排除项和哈希记录在 `memory/baseline_v3.provenance.json` 与 `MEMORY_SNAPSHOT_PROVENANCE.md`；
- 每个 Run 在 `…/attempt_MM/memory/trading_memory.md` 获得自己的副本；
- `_config_for_spec` 在构图前把 `memory_log_path` 指向该副本；
- 运行前 gate 校验：快照哈希、副本哈希==快照、副本位于自己的 attempt 目录、副本不是快照；运行后 `memory_state.json` 证明快照未变；快照被改动则 run INVALID（`memory_snapshot_modified`）；
- `memory` 进入 `config_sha256`，快照变化即改变全部 16 个哈希。

**证据：** `tests/test_memory_isolation.py` 17/17；其中顺序无关性测试用产品自己的 `_resolve_pending_entries` 证明：A 的 pending 只让 A 反思一次，B 从快照开始、反射调用 0 次。

## 2. 新增测试与实际通过数

| 文件 | 数量 | 通过 |
| --- | --- | --- |
| `tests/test_system_attribution.py` | 13 | 13 |
| `tests/test_memory_isolation.py` | 21 | 21 |
| `tests/test_cand01_batch_16run_v3_infra.py` | 12 | 12 |
| **合计** | **46** | **46** |

## 3. 完整测试结果

| | 基线 `15270b1` | 本候选 |
| --- | --- | --- |
| passed | 2,163 | **2,209**（+46） |
| failed | 2 | 2（同一组） |
| skipped | 2 | 2 |
| subtests | 319 | 319 |
| 新增失败 | — | **0** |

两个失败均为 `tests/test_cli_prefs.py` 的既有环境耦合（`~/.tradingagents/cli_prefs.json` 把开发者记住的选择带进测试），在冻结基线上以相同方式复现；按“不得修改无关测试消除既有失败”的要求未改动。`compileall` 通过；ruff 发现集合与基线**完全相同**（121 项，delta 0，非门禁）；新增文件自身 ruff 无告警。

## 4. 三方独立审计

三个只读 Subagent 在独立上下文中审计了候选 `6e66dca`（tree `3119b075`），
并在修复后对 `f19d6ed`（tree `5f6640ac`）做了增量复核。

| 审计 | 结论 | 主要发现（均已在冻结前修复） |
| --- | --- | --- |
| A（产品代码与 Memory） | PASS_WITH_FINDINGS | 无 memory_state.json 时 fail-open；scope API 可把 agent 伪装成 system；U-1 信任自报标志；NVDA/AAPL 快照不对称 |
| B（Harness 与协议） | PASS_WITH_FINDINGS | schema 3 被拒、gate 比较 9 vs 3 字段（已在 6e66dca 修）；通用子进程绕过；臂矩阵硬编码 V2；文档断言 |
| C（Usage、遥测与安全） | PASS_WITH_FINDINGS | 无状态文件时 fail-open；U-1 只看聚合标志；`.env`/历史/密钥未受影响 |

修复项：M1 缺证据即 INVALID；A1/A2 归因完整性加固；L1 臂矩阵随活动批次；
L2/L4/L5 文档更正；快照改为**空且对称**（两条日志条目都是本研究先前运行
生成的，保留 NVDA 会让唯一完整 2×2 块获得记忆优势；见 provenance 的
`empty_baseline/empty_reason`）。完整报告见同目录 `INDEPENDENT_AUDIT_A/B/C.md`。

## 5. 新 commit / tag

见 `FINAL_FREEZE_REPORT.md` 与 `c3/FREEZE_RECORD.json`（commit、tree、指纹、tag、协议哈希、生成器哈希、快照哈希、MANIFEST）。

## 6. 新实验协议与规格路径

- 协议：`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/CAND01_BATCH_2X2_PROTOCOL_V3.md`
- 16 份规格：`token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3/specs/R01…R16/{experiment.json,spec.json}`
- 快照：`…/cand01_batch_16run_v3/memory/baseline_v3.md`
- 哈希清单：`CONFIG_HASH_MANIFEST.csv`（16 个新 `config_sha256`）

## 7. 是否可以开始下一轮 16 次真实实验

满足停止条件后为 **READY_FOR_FULL_EXPERIMENT**（最终结论以三方审计与冻结验证完成为准，见 `RUN_READINESS.md`）。

本轮**没有**启动任何付费 Pipeline，没有访问 CityU/Finnhub/FRED，未读取或复制 `.env`，未修改/覆盖 V2、RC1 或历史审计记录。
