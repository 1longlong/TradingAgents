# R12 fallback 修复（Provider 400）

**结论：已修复，并有可判定回归测试与 mutation 证据。**

## 1. 根因（在冻结版本上复核）

`finalize_single_pass` 在 `structured.py:797` 先 `history.append(result)`，再在 823 行校验 schema。校验失败时，旧代码在 849 行：

```python
response = llm.invoke(_single_pass_messages(history))
```

两个缺陷同时存在：

1. `history[-1]` 是携带 schema `tool_calls`、却没有对应 `ToolMessage` 的 assistant 消息；`_single_pass_messages` 只追加 HumanMessage、不删除它 → 悬空 tool_call 被重放 → provider 400（R12 两次尝试，均为第 5 个请求）。
2. 裸 `llm` 而不是 `prompt | llm` → analyst system prompt 丢失（R12 fallback 请求 674/655 B，而正常首调用 6,741 B）。

## 2. 修复

新增 `_free_text_retry(prompt, llm, history, agent_name)`：

- 仅当 `history[-1]` 是 `type == "ai"` 且带 `tool_calls` 时弹掉它（不误删正常 prose 回复、不误删带 ToolMessage 的历史）；
- 通过调用方传入的 `prompt` 发起请求（`(prompt | llm).invoke(...)`），system prompt 保留；
- 返回值统一经过 `sanitize_analyst_text`（见 DSML 修复）。

三处 fallback 调用点全部改用它：

| 位置 | 场景 |
| --- | --- |
| schema 校验失败分支（原 849） | R12 的 400 路径 |
| `_single_pass_free_text`（prose 为空 / 轮次耗尽） | fallback 的 system prompt |
| `finalize_analyst_report` 的失败分支 | 两段式路径的 fallback 文本也会 sanitize |
| `finalize_analyst_report` / `finalize_single_pass` 的 `structured_llm is None` 分支 | 无结构化能力时返回的 prose 也会 sanitize |

另外修复了审计 A 的 mixed-turn 悬空调用：schema+data 同一轮时，只保留 data calls 在 assistant turn 上（schema call 被剥离），避免下一次请求重放未解析的 schema call id。

`_terminal_messages` 未改：它只保留带已执行 ToolMessage 的 assistant turn，悬空 schema turn 本来就会被跳过。

## 3. 测试（`tests/test_final_remediation.py`）

| 测试 | 断言 |
| --- | --- |
| `test_invalid_stance_retry_has_no_dangling_tool_call` | 重试请求中没有任何未配对的 tool_call id |
| `test_retry_keeps_the_analyst_system_prompt` | 重试请求含 `SystemMessage`（原文 "ANALYST SYSTEM PROMPT"） |
| `test_a_complete_tool_pairing_is_not_broken` | 正常的 tool_call/ToolMessage 配对不被破坏，且成功结构化只调用一次 |
| `test_a_second_failure_is_reported_not_swallowed` | 第二次失败抛出真实异常（`RuntimeError`），不吞掉 |
| `test_normal_structured_output_is_unchanged` | 合法 schema 输出仍直接返回，无额外调用 |
| `test_markup_in_the_single_pass_fallback_never_reaches_the_report` | fallback 的 markup 不会进入报告 |
| `test_a_mixed_schema_plus_data_turn_leaves_no_dangling_call` | mixed（schema+data）轮次：只执行 data calls，schema call 从 assistant turn 剥离，下一次请求无悬空 id |
| `test_a_non_empty_prose_turn_is_sanitized_too` | 模型直接在 prose 里返回 markup 时也会被 sanitize（审计 A 的 HIGH） |

## 4. 证明测试能抓到缺陷

**Pre-fix 探针**（`tests/pre_fix_detection_probe.py`，用 HEAD~1 的代码在临时目录运行）：

```
DETECTED: retry carries dangling tool_call ids ['s1']
DETECTED: retry dropped the system prompt
DETECTED: protocol markup reached the report text
DETECTED: tool round was not recorded
defects detected: 4/4
```

修复后同一探针：`defects detected: 0/4`。

**Mutation**（在修复版本上逐项注入缺陷后运行对应测试）：

| Mutation | 结果 |
| --- | --- |
| 不弹掉悬空 turn | `test_invalid_stance_retry_has_no_dangling_tool_call` **FAILED** |
| 改回裸 `llm.invoke` | `test_retry_keeps_the_analyst_system_prompt` **FAILED** |
| 跳过 sanitize | `test_markup_in_the_single_pass_fallback_never_reaches_the_report` **FAILED** |
| 删除 round hook | `TestToolRounds` 4 个测试 **FAILED** |

## 5. 兼容性

- 模型、temperature、prompt 语义、schema、正常 tool 调用逻辑均未改。
- 失败仍记录 `structured failure` 事件；新增的仅是一次“合法的、带 system prompt、无悬空 call”的重试。
- 不把 fallback 伪装成结构化成功（`report_obj` 仍为 `None`）。
