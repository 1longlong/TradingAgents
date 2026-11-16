# 独立审计记录

三个独立只读 Subagent 在同一代码版本上审计。审计者不修改工作树；主执行者根据发现做了一轮针对性修复，并对修复后的版本做了增量复核。

## 版本

| 阶段 | commit | tree | 指纹 |
| --- | --- | --- | --- |
| 初始候选 | `e0ea1b0` | `8dae49de…` | `b8ba9547…` |
| 审计后修复候选 | `e9eed04` | `ddfde66c…` | `a0f6b06c…` |
| 计数/文档修复候选 | `51edd41` | `3123f54f…` | `d18a6229…` |
| **最终候选** | `eaeebab` | `6f949634…` | `e8905252…` |

## Audit A — 产品逻辑（R12 fallback、DSML、single-pass、下游）

**结论：产品行为 PASS；文档一致性在最终版本修复后 PASS。**

首轮发现（`e0ea1b0`）：

| 级别 | 发现 | 处理 |
| --- | --- | --- |
| HIGH | 直接 prose 出口（无 tool_calls 的 markup 回复）未 sanitize | 已修：`finalize_single_pass` prose 分支调用 sanitizer |
| MEDIUM | 两段式 `structured_llm is None` 出口未 sanitize | 已修：两个 finalizer 的该出口都 sanitize |
| MEDIUM | mixed data+schema 轮次把未执行的 schema call 留在 assistant turn，下一次请求悬空 | 已修：mixed 时剥离 schema call |
| MEDIUM | sanitizer 有损：分析+尾部 markup 整段丢弃、字段白名单过窄 | 已修：保留 markup 前的 prose；白名单扩展到 interpretation/risks/key_levels/… |
| LOW | 全失败轮次仍记 `status="ok"` | 已修：全失败记 `status="error"` |
| — | 探测：direct prose、structured_llm=None、mixed、prose-preserve 均通过；19→20 项测试 | 通过 |

最终复核（`51edd41`）：产品行为全部通过；仅剩两处文档与新计数矛盾（“只进日志”/“无字段变更”）—— 已在 `eaeebab` 修复（run_totals 增加 `structured_markup_sanitized`，两份文档改为“向后兼容的聚合字段”）。

## Audit B — 遥测与实验基础设施

**结论：PASS。** `tool_rounds` 是忠实计数（每批 1 轮、空批 0、全失败仍 1 轮），不会与图 `ToolNode` 重复计数；usage/budget/memory/PIT 未变。

| 级别 | 发现 | 处理 |
| --- | --- | --- |
| MEDIUM | `markup_sanitized` 额外记一条 structured event → `structured_attempts` 虚高 | 已修：独立计数 `structured_markup_sanitized`，不计入 attempts/fallbacks；`attempts == success+failure+unsupported` |
| MEDIUM | markup 在 3 个出口漏出（prose / 两个 `structured_llm is None`） | 已修（同 Audit A） |
| MEDIUM | 提交的 probe 缺 `invoke` shim | 已修：`8536274` 提交；对 `e3b5cca` 运行 4/4 detected |
| LOW | system 作用域 round 会落在 unattributed（无生产路径） | 记录、接受 |
| LOW | 全失败轮次 status ok；single-pass 无 per-tool 事件 | status 已修；per-tool 为既有缺口，记录 |
| LOW | 四文件门禁不含新测试文件 | 完整套件已包含 `test_final_remediation.py` |

最终复核：markup fallback 恰好一条 failure + 一条 markup_sanitized，attempts=1，成功+失败+不支持=1；252 passed。

## Audit C — 回归与数据安全

**结论：PASS。**

| 级别 | 发现 | 处理 |
| --- | --- | --- |
| HIGH | 提交的 probe 无法在 pre-fix 树运行（缺 invoke） | 已修（`8536274`）；对 pristine `e3b5cca` 运行 4/4 detected |
| MEDIUM | 审计期间 worktree 因 mutation 测试变脏/变动 | 最终版本 tree 干净、全部提交 |
| LOW | 文档未跟踪 | 已全部提交 |

最终复核（`e9eed04`）：HEAD/tree 正确、`git status` 为空；`c3-v3-final-freeze`、`c3-final-freeze`、`rc1` 未变；两个历史 MANIFEST 30/30 通过；完整套件 4 failed / 2226 passed（现在为 2227）/ 2 skipped / 319 subtests，0 新增失败；无密钥泄漏；Finnhub-only/GDELT 禁用/PF-01 通过。

## 汇总

| 审计 | 结论 |
| --- | --- |
| A | PASS（最终版本） |
| B | PASS |
| C | PASS |

未解决的 High/Critical：**无**。Low/Process 级残留已在 `REGRESSION_AUDIT.md` 中记录并接受。
