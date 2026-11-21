# market_report 的 DSML markup 修复

**结论：已修复。markup 不再进入最终报告；可恢复的分析文本被保留；无法恢复时给出明确错误状态，而不是空字符串。**

## 1. 现象与根因

V3 的 R07（AAPL/CC）与 R14（XOM/CC）中，`market_report` 字段是模型的原生工具调用文本：

```
<｜｜DSML｜｜ calls> <｜｜DSML｜｜ invoke name="get_verified_market_snapshot"> ...
<｜｜DSML｜｜ parameter name="summary" ...>...分析文本...</｜｜DSML｜｜ parameter>
```

R14 只有 346 字符（仅一次 snapshot 调用，无分析），R07 有 1,922 字符（`final_report` 调用，`summary` 里是真实分析）。下游因此引用不到 SMA/MACD/RSI。

**根因链：** single-pass 的 schema 调用校验失败 → fallback 请求（无工具绑定）→ 模型把工具调用写成文本 → 旧代码把该文本原样作为 `market_report` 返回 → 节点写入状态 → 下游读取。

## 2. 修复

`sanitize_analyst_text(text, agent_name=...)`：

| 输入 | 输出 |
| --- | --- |
| 不含协议标记的文本 | 原样返回 |
| 含标记、且能提取到分析参数（`summary`/`analysis`/`evidence`/`thesis`/…） | 提取这些参数值，拼接为可读报告；markup 全部丢弃 |
| 含标记、但没有可用的分析参数（R14 式） | 明确的 `[REPORT UNAVAILABLE — …]` 文本（非空、非 markup） |

- 不做“删除所有尖括号”的粗暴过滤：只提取有语义的参数值，其余丢弃；没有分析时明确报不可用。
- 每次 sanitize 都记录 `markup_sanitized` 结构化事件（`used_fallback=True`）并写 warning，原始错误/长度信息保留在日志与事件里。
- 应用点：`_free_text_retry`（single-pass 的全部 fallback 出口）、`finalize_single_pass` 的**直接 prose 出口**、以及 `finalize_analyst_report` / `finalize_single_pass` 的两处 `structured_llm is None` 出口。审计 A/B 指出这些出口原先会漏出 markup，已全部覆盖。
- 混合文本（分析 + 尾部 markup）保留第一个协议标记之前的全部 prose，而不是整段丢弃。
- 参数白名单扩展到 schema 的真实字段：`interpretation`、`risks`、`key_levels`、`key_figures`、`invalidation`、`scenario_set`、`catalysts`、`valuation` 等。
- 遥测：markup 清理写 warning 日志，并记录一条 `markup_sanitized` structured event；该事件有**独立计数** `structured_markup_sanitized`，**不**计入 `structured_attempts`/`structured_fallbacks`，因此 `attempts == success + failure + unsupported` 仍成立（同时满足审计 A 的“必须记录”与审计 B 的“不得重复计数”）。

## 3. 测试（R07/R14 脱敏历史）

| 测试 | 断言 |
| --- | --- |
| `test_clean_text_is_untouched` | 纯文本不变 |
| `test_r07_markup_is_recovered_without_markers` | 恢复出含 AAPL/336.76/SMA/MACD/RSI 的文本，且无 `｜｜DSML｜｜` |
| `test_r14_markup_becomes_an_explicit_unavailable_report` | 输出等于 `REPORT_UNAVAILABLE_TEMPLATE`，非空、无 markup |
| `test_markup_in_the_single_pass_fallback_never_reaches_the_report` | 端到端：fallback 返回 markup 时，报告里不含 markup 且保留 SMA |
| `test_a_non_empty_prose_turn_is_sanitized_too` | 直接在 prose 里返回 markup 的出口 |
| `test_structured_llm_none_still_sanitizes_the_two_call_fallback` | 无结构化能力的两段式出口 |
| `test_analysis_before_markup_is_kept` | 分析 + 尾部 markup：prose 全保留 |
| `test_schema_fields_beyond_summary_are_recovered` | `interpretation`/`risks`/`key_levels` 等字段可恢复 |

R07/R14 的夹具是从原始 `full_states_log` 中抽取的 markup 结构（脱敏、不含真实决策文本之外的内容）。

## 4. 未做的事（明确）

- 没有尝试“修复模型输出”：模型仍可能返回 markup；本修复保证它不会成为报告。
- 没有把不可用的 market 报告替换成编造的分析；下游会看到明确的 `REPORT UNAVAILABLE`。
- 没有改 prompt 语义；R07/R14 的根因在解析/回退路径，不在 prompt。
