# 测试结果（全部为真实命令输出）

环境：worktree `cand01_fix`（基于冻结 `e3b5cca`），解释器
`/home/sky/cs5351/TradingAgents/.venv/bin/python`，`TZ=UTC`，仓库根目录。

## 1. 修复前基线（同一 worktree，未改动任何代码）

```
$ TZ=UTC .venv/bin/python -m pytest -q
4 failed, 2207 passed, 2 skipped, 26 warnings, 319 subtests passed in 25.74s
```

4 个失败全部是**该 worktree 的固有问题**，不是本轮引入：

| 失败 | 原因 |
| --- | --- |
| `test_cand01_batch_16run_v3_infra.py::test_the_generator_reproduces_the_delivered_artifacts` | 冻结 V3 规格里的 `experiment_root`/`results_dir` 指向生成时的 `cand01_v3`；在新 worktree 重算必然不同 |
| `test_cand01_batch_16run_v3_infra.py::test_the_cli_check_mode_passes` | 同上（`--check` 报告 `SPEC DRIFT DETECTED`，差异仅为宿主绝对路径） |
| `test_cli_prefs.py::test_selections_are_remembered_after_a_run` | 既有环境耦合（`~/.tradingagents/cli_prefs.json` 泄入） |
| `test_cli_prefs.py::test_a_remembered_endpoint_is_offered_back` | 同上 |

在原始 V3 worktree（`cand01_v3`）里，后两项是唯一的失败（2 failed / 2163 passed）。本轮未修改这些测试。

**基线代码指纹：** `69f46fc1359c6d941b305b77f4d3966dd95ebd799a54be777ee637f832b056b2`

## 2. 修复后完整套件

```
$ TZ=UTC .venv/bin/python -m pytest -q
4 failed, 2221 passed, 2 skipped, 26 warnings, 319 subtests passed in 22.92s
```

| | 基线 | 修复后 |
| --- | --- | --- |
| passed | 2,207 | **2,221**（+14 新增测试） |
| failed | 4 | **4（同一组）** |
| skipped | 2 | 2 |
| subtests | 319 | 319 |
| 新增失败 | — | **0** |

**修复后代码指纹：** `b8ba95476519366478fc9bcdd5e9db334971f3353bbcad3b63c7a0b7e1861f66`

## 3. 专项套件

| 套件 | 结果 |
| --- | --- |
| `tests/test_final_remediation.py`（新增） | **14 passed** |
| `test_observability.py` + `test_token_benchmark.py` + `test_c3_regressions.py` + `test_c3_final_freeze.py` + `test_memory_isolation.py` + `test_system_attribution.py` + `test_final_remediation.py` | **426 passed** |
| CAND-01 single-pass / news / Finnhub / GDELT / PIT / structured（11 个文件） | **360 passed, 86 subtests passed** |

## 4. 缺陷可检测性（pre-fix 探针）

用 `git archive HEAD~1` 在临时目录运行 `tests/pre_fix_detection_probe.py`：

```
DETECTED: retry carries dangling tool_call ids ['s1']
DETECTED: retry dropped the system prompt
DETECTED: protocol markup reached the report text
DETECTED: tool round was not recorded
defects detected: 4/4
```

同一探针在修复后：`defects detected: 0/4`。

## 5. Mutation 检查

| Mutation | 目标测试 | 结果 |
| --- | --- | --- |
| 不弹掉悬空 assistant turn | `test_invalid_stance_retry_has_no_dangling_tool_call` | FAILED（被抓住） |
| 改回裸 `llm.invoke` | `test_retry_keeps_the_analyst_system_prompt` | FAILED |
| 跳过 `sanitize_analyst_text` | `test_markup_in_the_single_pass_fallback_never_reaches_the_report` | FAILED |
| 删除 `record_tool_round` | `TestToolRounds`（4 项） | 4 FAILED |

每次 mutation 后都用 `git show HEAD:<file>` 恢复并核对 `git status`。

## 6. 离线 Pipeline 验证

没有发起任何付费调用。新增测试用脚本化 chat model + 真实 `ChatPromptTemplate`（与生产一致，含 `MessagesPlaceholder`）驱动 `finalize_single_pass`，覆盖：正常结构化、非法 stance、完整工具配对、二次失败、markup 回退、round 记录；`run_data_tools` 用真实工具桩验证执行与 ToolMessage 生成。

## 7. 统计

| 项 | 值 |
| --- | --- |
| collected（修复后完整套件） | 2,227（2221 passed + 4 failed + 2 skipped） |
| subtests | 319 |
| 新增测试 | 14 |
| 新增失败 | 0 |
| 付费调用 | **0** |
| 外部 API 调用 | **0** |
