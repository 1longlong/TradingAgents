# tool_rounds 遥测修复

**结论：已修复。单次 pass 的进程内工具循环现在按“每个模型轮次的工具批次 = 1 round”记录；空批次不计；失败调用仍计一轮。**

## 1. 问题

V3 中所有 single-pass 运行 `tool_rounds = 0`，尽管它们执行了 23–35 次工具调用。原因：round 事件只由图 `ToolNode` 的 `attrib_tool_round` 发出（`graph/setup.py`），而 single-pass 在 `run_data_tools` 内就地执行工具，没有经过 `ToolNode`。这是**仪表缺口**，不是“零轮”。

## 2. 定义与实现

- **LLM call**：一次模型请求。
- **Tool call**：一次工具执行。
- **Tool round**：模型发出**一组**工具调用、系统执行并把结果返回模型的**一个完整交互周期**。

实现：

1. `observability.record_tool_round(...)`：公开 API，用当前 agent 作用域归因，写入 `ToolRoundEvent`。
2. `run_data_tools._run(calls)` 在每次非空批次执行时记录一轮：`number_of_tool_calls=len(calls)`，`status/error_type` 由异常传播决定；空批次直接返回、不记轮。

## 3. 测试

| 场景 | 预期 | 测试 |
| --- | --- | --- |
| 没有工具调用 | 0 | `test_no_tool_call_is_no_round` |
| 一次回复含 2 个工具调用 | 1 轮、2 calls | `test_one_model_turn_with_two_calls_is_one_round` |
| 两轮（1 个 + 2 个调用） | 2 轮、[1, 2] | `test_two_rounds_are_two_rounds` |
| 工具失败 | 仍记 1 轮，ToolMessage status=error | `test_a_failing_tool_still_counts_as_a_round` |
| 聚合到遥测 | `run_totals.tool_rounds == 1`、per-agent 一致 | `test_rounds_reach_the_telemetry_payload` |

## 4. 不重复计数

- 两段式（B/AB）走图 `ToolNode` → 由 `attrib_tool_round` 记录；`run_data_tools` 不在该路径上运行。
- single-pass（C0/CC）走 `run_data_tools` → 只由新 hook 记录。
- 同一批次不会同时经过两者；`_run` 的 try/finally 每条路径只调用一次 `record_tool_round`。

## 5. schema 兼容

只新增一种事件调用方式（`ToolRoundEvent` 结构未变，`tool_rounds` 字段早已存在），**不需要 schema 版本升级**；旧 telemetry 的 `tool_rounds=0` 仍按原样可读，新运行才有真实值。
