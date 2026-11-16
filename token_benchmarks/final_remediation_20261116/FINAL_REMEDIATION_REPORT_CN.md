# CAND-01 V3 最终修复报告

**基准：** 冻结 V3 `e3b5cca`（tag `c3-v3-final-freeze`，指纹 `69f46fc1…`）
**修复分支：** `fix/cand01-final-remediation`（worktree `.worktrees/cand01_fix`）
**修复 commit：** `e0ea1b0`（代码） + 最终文档 commit（见 `FINAL_FREEZE_REPORT.md`）
**修复后指纹：** `b8ba95476519366478fc9bcdd5e9db334971f3353bbcad3b63c7a0b7e1861f66`

---

## 1. 三个问题与结论

| # | 问题 | 结论 | 证据 |
| --- | --- | --- | --- |
| P0-1 | R12 结构化 fallback 的 Provider 400 | **已修复** | `R12_FALLBACK_FIX.md`；14 项回归测试；mutation 4/4 被抓 |
| P0-2 | single-pass 的 market_report 泄漏 DSML markup | **已修复** | `DSML_MARKET_REPORT_FIX.md`；R07/R14 夹具；markup 不再进入报告 |
| P1-3 | tool_rounds 恒为 0 | **已修复** | `TOOL_ROUNDS_TELEMETRY_FIX.md`；空批次/单批/多批/失败均覆盖 |

## 2. 修复内容（一句话版）

1. **R12**：`finalize_single_pass` 的失败重试改为 `_free_text_retry` —— 弹掉尾部悬空 tool_call 的 assistant turn，并通过 `prompt | llm` 调用（system prompt 保留）；三处 fallback 出口统一使用。
2. **DSML**：`sanitize_analyst_text` 在报告出口拦截协议 markup；能从 `summary/analysis/evidence/...` 参数恢复分析文本，否则写入明确的 `REPORT UNAVAILABLE`（非空、非 markup），并记录 `markup_sanitized` 事件。
3. **rounds**：`run_data_tools` 每个非空工具批次记录一轮（`observability.record_tool_round`），空批次不计，失败仍计；与图 `ToolNode` 路径不重复计数。

## 3. 测试

| 阶段 | 结果 |
| --- | --- |
| 修复前基线（同一 worktree） | 4 failed / 2207 passed / 2 skipped / 319 subtests（4 个均为该 worktree 固有：2 个跨 worktree 的 V3 规格路径检查 + 2 个 `cli_prefs` 环境耦合） |
| 修复后完整套件 | **4 failed / 2221 passed / 2 skipped / 319 subtests**；**新增失败 0**；通过数 +14 |
| 新增测试 | `tests/test_final_remediation.py` 14 项全部通过 |
| 专项 | observability/token/c3/memory/attribution/remediation **426 passed**；CAND-01+news+PIT+structured **360 passed, 86 subtests** |
| 缺陷可检测性 | pre-fix 探针 **4/4 detected**；修复后 0/4 |
| Mutation | 悬空 turn、丢 system prompt、跳过 sanitize、删除 round hook 全部被测试抓住 |
| 付费调用 / 外部 API | **0 / 0** |

详细命令与数字见 `TEST_RESULTS.md`。

## 4. 保护项

CAND-01 single-pass、PIT、Finnhub-only/GDELT 禁用/PF-01、Memory 隔离、system-component 归因、预算与 Usage、V3 规格与历史数据均未改动；`test_*` 中相关套件全部通过。历史 tag/commit/原始 MANIFEST 未移动（见 `REGRESSION_AUDIT.md`）。

## 5. 独立审计

三个只读 Subagent 在同一 commit（`e0ea1b0`，代码指纹 `b8ba9547…`）上审计：

- **Audit A（产品逻辑）**：见 `INDEPENDENT_AUDIT.md`
- **Audit B（遥测与基础设施）**：见 `INDEPENDENT_AUDIT.md`
- **Audit C（回归与数据安全）**：见 `INDEPENDENT_AUDIT.md`

## 6. 最终冻结

- 代码 commit：`e0ea1b0`；最终（含文档）commit 与 tag 见 `FINAL_FREEZE_REPORT.md`。
- 新 tag：`cand01-v3-final-remediation`（annotated，不移动任何既有 tag）。
- 旧 V3 commit `e3b5cca` 与 tag `c3-v3-final-freeze` 完全保留。

## 7. 能否结束工程工作

三个 P0/P1 缺陷已修复并有可判定测试与 mutation 证据；全量测试无新增失败；受保护功能无回归；三方审计结论见 `INDEPENDENT_AUDIT.md`。若该文件中三个审计均为 PASS 或 PASS_WITH_FINDINGS 且无 High/Critical，则本轮可以正式结束。

## 8. 明确的残留（记录、接受）

1. 跨 worktree 的 V3 规格绝对路径导致该 worktree 的 2 个 infra 测试失败（非本轮引入；原始 `cand01_v3` 中仅 `cli_prefs` 2 项失败）。
2. `markup_sanitized` 事件只进入 `structured_events` 与日志，未新增 summary 列。
3. 历史 V3 的 `tool_rounds=0` 不重写；新运行才有真实值。
4. 没有重新跑任何真实实验；R12 的修复仅由离线夹具验证。
