# 项目完成度与设计匹配性审查（2026-04-13）

## 结论（先看）
- **结论：未完全做完**（v0.1 Definition of Done 尚未全部满足）。
- **匹配度：部分匹配**（M1/M2/M3/M5/M6 基本具备，M4“失败恢复链路”与部分验收细则未达标）。

## 对照《desgin/development-plan.md》逐项检查

### M1 文件契约与目录骨架
- 目录与核心文件存在：`spec/`、`state/`、`handoff/`、`workspace/src/`、`state/agent_views/`。
- 代码具备 JSON 读写与键校验工具（`orchestrator/io_contracts.py`）。
- **状态：基本完成**。

### M2 编排器主循环
- 存在入口 `orchestrator.py`，并调用 `Orchestrator.run_loop(max_iters)`。
- 执行顺序为 Generator → Tester → Verifier → （按停滞条件）Challenger。
- 事件日志写入 `state/run_events.jsonl`。
- **状态：完成**。

### M3 停滞检测与 Challenger 触发
- `orchestrator/stagnation.py` 实现 `delta_threshold`、`trigger_window`、`regression_window`。
- plateau/regression 会触发 `_run_challenger` 并写 `handoff/challenger_seed.json`。
- **状态：完成**。

### M4 失败恢复链路（重试→降级→退出）
- 已实现：统一重试（`execute_with_retry` + `RetryConfig(max_retries=2)`）。
- **缺失**：降级策略分支（如缩小上下文、保守模板、跳过非关键动态测试）未见实现。
- **缺失**：退出时 machine-readable 失败摘要/错误码框架不完整（仅抛异常）。
- **状态：未完成**。

### M5 Agent 可消费观测层
- 可生成 `agent_brief.json`、`score_trend.mmd`、`current_mode.mmd`。
- **状态：完成（最小版）**。

### M6 端到端演练与回归基线
- 存在 `examples/normal`、`examples/plateau` 与 `scripts/replay_demo.sh`。
- 回放脚本可执行并产生预期文件。
- **状态：完成（最小版）**。

## 对照 Definition of Done（v0.1）

1. 能稳定跑通至少 10 轮迭代模拟
   - `python3 orchestrator.py --max-iters 10 --base .` 可运行。
   - **结果：满足“可跑通”**。

2. 停滞触发与 Challenger 介入逻辑可复现
   - 逻辑存在，且 replay 中可看到 challenger 相关产物。
   - **结果：满足**。

3. 故障路径具备“重试→降级→退出”完整链路
   - 仅看到“重试”；降级与规范化退出路径不足。
   - **结果：不满足**。

4. 所有关键状态文件可追溯、可回放、可校验
   - 追溯/回放基本可行（json/jsonl 落盘）。
   - 校验层仅有 `require_keys` 的轻量键检查，尚非完整 schema 校验。
   - **结果：部分满足**。

5. Agent 无 GUI 下可通过文本观测文件完成下一步决策
   - 已提供结构化观测文件。
   - **结果：满足（最小版）**。

## 关键偏差（与设计/规格不一致）
- 验收标准中 `composite_score.pass_threshold = 0.9`，但当前 composite 公式在各单项指标都过线时上限约 **0.898**（由当前 latency 归一化方式导致），导致系统几乎不可能 `passed=true`。
- Verifier 的 `failed_case_ids` 固定逻辑偏简化（`edge_cov < 1.0` 就写 `case_002`），与“基于实际 case_results 严格裁决”仍有距离。

## 建议优先级
1. **P0：修复 composite 计算与阈值一致性**，保证“满足全部指标时可通过”。
2. **P0：补齐 M4 降级策略与退出错误码**（满足 DoD 必备链路）。
3. **P1：引入真正 schema 校验**（而非仅键存在性检查）。
4. **P1：让 Verifier 从 `case_results` 真实归因失败用例**，减少硬编码。
