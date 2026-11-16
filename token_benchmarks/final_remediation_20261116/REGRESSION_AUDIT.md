# 回归审计（主执行者自查）

## 1. 改动范围

```
$ git diff e3b5cca --stat
 tradingagents/agents/utils/structured.py | +153/-10
 tradingagents/observability.py           |  +24
 tests/test_final_remediation.py          | +new
 token_benchmarks/final_remediation_20261116/… (docs/tests/manifest)
```

- 没有改动任何 experiment spec、protocol、V3 batch 数据、MANIFEST、freeze 记录。
- `git diff e3b5cca -- token_benchmarks/live_pilot_2x2` 只包含新增的 `final_remediation_20261116/`。

## 2. 受保护功能逐项核对

| 功能 | 核对方式 | 结果 |
| --- | --- | --- |
| CAND-01 single-pass | `test_cand01_single_pass_finalization.py` 等 | 通过 |
| 单次结构化 finalization / 不重复生成 | `test_structured_*`、`test_normal_structured_output_is_unchanged` | 通过 |
| prose fallback | 新增测试 + 既有 structured 测试 | 通过 |
| 下游兼容 | `test_structured_agents.py`、`test_structured_analyst_output.py` | 通过 |
| PIT | `test_pit_notice.py` 等 | 通过 |
| 新闻 Finnhub-only / GDELT 禁用 | `test_finnhub_only_scope.py`、`test_gdelt_news.py`、`test_news_*` | 通过 |
| PF-01 新闻来源分类 | `test_cand01_news_positive_path.py`、`test_news_audit_regressions.py` | 通过 |
| Memory 隔离 | `test_memory_isolation.py`（21） | 通过 |
| Attribution（system component） | `test_system_attribution.py`（13） | 通过 |
| Budget / Usage | `test_token_benchmark.py`（106） | 通过 |
| V3 规格不可变 | `git diff e3b5cca -- token_benchmarks/live_pilot_2x2/cand01_batch_16run_v3` 为空 | 通过 |

## 3. 历史与数据

| 检查 | 结果 |
| --- | --- |
| V3 冻结 commit `e3b5cca` / tag `c3-v3-final-freeze` | 未移动、未重建 |
| V2 tag `c3-final-freeze` → `15270b1` | 未移动 |
| `rc1` → `9948bf8` | 未移动 |
| 主 worktree HEAD | 未变 |
| 原始实验 MANIFEST（30 文件） | `sha256sum -c` 通过 |
| 分析目录 MANIFEST（30 文件） | `sha256sum -c` 通过 |
| `.env` | 未读取、未复制、未提交 |

## 4. 语义边界（明确未改）

- 模型、temperature、prompt 文本、schema 定义、single-pass 的轮次预算（`SINGLE_PASS_MAX_ROUNDS`）均未改。
- 只改“失败后如何重试”“报告文本如何清理”“轮次如何记录”三处。
- `markup_sanitized` 是新的事件 kind，不参与 success/failure/unsupported 计数；telemetry schema 版本不需要升级（无字段变更）。

## 5. 已知残留（记录、接受）

1. 该 worktree 的 2 个 V3 infra 测试因规格内嵌绝对路径而失败（跨 worktree 固有问题，非本轮引入）。
2. markup 清理只写 warning 日志，不新增 structured event（避免 `structured_*` 重复计数）；如需聚合，可在下一版加专用计数列。
3. 单次 pass 的 `tool_rounds` 现在与图路径语义一致，但历史 V3 数据的 `tool_rounds=0` 保持原样（不重写历史）。
