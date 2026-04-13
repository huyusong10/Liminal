# Liminal 开发计划（v0.1）

> 目标：在不偏离已确认设计原则的前提下，先做“可跑、可审计、可恢复”的最小闭环。

## 0. 已确认前提（输入约束）

- 主循环由外部编排脚本负责。
- 不使用 Skill/Plugin 作为实现主路径。
- 硬 reset 语义：仅新建 session。
- 观测产物优先给 Agent 消费，格式为文本原语（JSON/JSONL/PlantUML/Mermaid/Excalidraw JSON）。
- 失败恢复：角色级重试 → 降级策略 → 退出。
- 不启用 token 预算闸门。

---

## 1. 里程碑规划

## M1：文件契约与目录骨架（1 天）

交付物：
- 创建目录：`spec/`、`state/`、`handoff/`、`workspace/src/`、`state/agent_views/`
- 初始化文件：
  - `spec/test_cases.json`
  - `spec/acceptance_criteria.json`
  - `spec/constraints.md`
  - `state/metrics_history.jsonl`（空）
  - `state/iteration_log.jsonl`（空）
  - `state/stagnation.json`（iter=0）
  - `handoff/tester_output.json`（模板）
  - `handoff/verifier_verdict.json`（模板）
  - `handoff/challenger_seed.json`（空模板）
  - `state/agent_views/agent_brief.json`（模板）

验收标准：
- 所有 JSON 文件通过 schema 校验。
- README 中明确每个文件的读写责任主体。

## M2：编排器主循环（2~3 天）

交付物：
- `orchestrator.py`（或同等入口），支持：
  - `run_once(iter_id)`
  - `run_loop(max_iters)`
- 串接 4 角色执行顺序：Generator → Tester → Verifier → (可选 Challenger)
- 统一事件日志：`state/run_events.jsonl`

验收标准：
- 单轮可完整跑通并产出 `handoff/*` 与 `state/*` 更新。
- 异常可被捕获并记录 machine-readable 错误码。

## M3：停滞检测与 Challenger 触发（1~2 天）

交付物：
- stagnation 计算模块：
  - `delta_threshold`
  - `trigger_window`
  - `regression_window`
- 触发策略：
  - plateau/regression 模式识别
  - 写入 `handoff/challenger_seed.json`

验收标准：
- 可通过回放历史分数验证触发行为符合预期。
- `stagnation.json` 仅由 Verifier 子流程写入。

## M4：失败恢复链路（1~2 天）

交付物：
- 角色级重试（可配置次数，如 `max_role_retries=2`）
- 降级策略（示例）：
  - 缩小上下文输入
  - 切换到保守提示模板
  - 跳过非关键动态测试
- 最终退出并上报失败摘要

验收标准：
- 人工注入故障时，执行路径稳定遵循“重试→降级→退出”。
- 每一步决策都可在 `run_events.jsonl` 中回放。

## M5：Agent 可消费观测层（1~2 天）

交付物：
- 每角色执行后增量刷新：
  - `state/agent_views/agent_brief.json`
  - `state/agent_views/score_trend.mmd`（或 `.puml`）
  - `state/agent_views/current_mode.mmd`
- 每轮结束生成汇总快照。

验收标准：
- 下一角色仅依赖 `agent_views/*` + 白名单 handoff 即可获取关键上下文。
- 不依赖人工图形界面即可被 Agent 自动解析。

## M6：端到端演练与回归基线（1 天）

交付物：
- `examples/` 下提供至少 2 组回放数据：
  - 正常收敛案例
  - plateau 触发 Challenger 案例
- 一键演练脚本（仅本地）：`scripts/replay_demo.sh`

验收标准：
- 两组案例均能稳定重放。
- 关键状态文件变更与预期一致。

---

## 2. 技术切分（模块建议）

- `orchestrator/engine.py`：主状态机
- `orchestrator/io_contracts.py`：JSON schema 与读写校验
- `orchestrator/retry_policy.py`：重试/降级/退出
- `orchestrator/stagnation.py`：停滞检测
- `orchestrator/session_manager.py`：新 session 生命周期
- `orchestrator/agent_views.py`：观测文件生成

---

## 3. 风险与缓解

1. **契约漂移风险**：角色输出字段不稳定
   - 缓解：所有 handoff 写入前做 schema 校验，失败即拒绝写入。
2. **重试风暴风险**：失败后无限重试
   - 缓解：硬性上限 + 降级后直接退出。
3. **观测噪声过大**：agent_views 信息冗余
   - 缓解：固定摘要字段，图表只保留最近 N 轮。

---

## 4. 第一周执行顺序（建议）

- Day 1：M1
- Day 2~3：M2
- Day 4：M3
- Day 5：M4 + M5（最小版）
- Day 6：M6 + 文档收口

---

## 5. Definition of Done（v0.1）

满足以下条件即视为 v0.1 完成：

- 能稳定跑通至少 10 轮迭代模拟。
- 停滞触发与 Challenger 介入逻辑可复现。
- 故障路径具备“重试→降级→退出”的完整链路。
- 所有关键状态文件可追溯、可回放、可校验。
- Agent 在无 GUI 前提下可通过文本观测文件完成下一步决策。
