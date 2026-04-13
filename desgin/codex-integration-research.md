# Liminal for Codex：集成方案调研与决策收敛（2026-04-13）

## 已确认决策（根据你最新回复）

1. **主循环由外部脚本实现**（控制面在外部）。
2. **不使用 Skill 方案**（至少当前阶段不作为实现路径）。
3. **硬 reset 语义：仅创建新 session**（不强制 new worktree/new thread）。
4. **观测对象是 Agent 而不是人**；图形与看板输出使用底层文本格式（如 PlantUML / Excalidraw JSON / Mermaid）。

> 这四点已经把实现路径从“混合探索”收敛到“外部编排优先”的明确方案。

---

## 方案重述（基于已确认决策）

## A. 控制面（外部编排脚本）

负责：
- 迭代状态机（Generator → Tester → Verifier → [Challenger]）。
- 停滞检测与触发（`delta_threshold`, `trigger_window`, `regression_window`）。
- reset 策略执行（当触发硬 reset 时，只新建 session）。
- 全量审计日志与失败回放。

建议：
- 对外部编排器定义唯一 `run_id` / `iter_id`。
- `state/` 作为权威状态区；关键文件只允许特定子流程写入。

## B. 执行面（Codex CLI）

负责：
- 通过 `codex exec --json` 执行单步任务并返回结构化事件流。
- 将各角色产物标准化回写至 `handoff/*.json`。
- 在失败时返回 machine-readable 的错误事件，供编排器做重试/降级。

明确不做：
- 不把主状态机放在 App Automations。
- 当前不依赖 Skill/Plugin 封装层。

---

## 针对“给 Agent 看”的观测设计

你强调“关键不是给你看，而是给 Agent 看”，这非常关键。建议观测产物都输出为**文本原语**：

## 1) 趋势图（PlantUML / Mermaid）
- `state/agent_views/score_trend.puml`
- `state/agent_views/stagnation_signal.mmd`

内容来自：
- `metrics_history.jsonl`
- `stagnation.json`

## 2) 结构图（Excalidraw JSON 或 Mermaid flowchart）
- `state/agent_views/pipeline_flow.excalidraw.json`
- `state/agent_views/current_mode.mmd`

内容来自：
- 当前迭代模式（normal / plateau / regression）
- 是否触发 Challenger

## 3) Agent 摘要卡（纯 JSON）
- `state/agent_views/agent_brief.json`

建议字段：
- `current_iter`
- `top_failures`
- `delta_3_iter`
- `seed_adoption_rate`
- `recommended_next_action`

> 这些文件由编排脚本自动生成，作为每轮注入上下文的标准输入。

---

## 硬 reset 已收敛后的实现定义

你已确认“仅新 session 即可”，因此建议固定成以下规范：

- 触发条件：`consecutive_low_delta >= trigger_window` 或显式策略命中。
- reset 动作：
  1. 关闭当前 session；
  2. 创建新 session；
  3. 仅注入白名单上下文（例如 `verifier_verdict.json` + `constraints.md` + 最新 `challenger_seed.json`）。
- 不强制动作：
  - 不要求新 worktree；
  - 不要求新 thread（如编排器不区分 thread）。

---

## 决策矩阵（已确认）

| 议题 | 最终决策 | 说明 |
|---|---|---|
| 并发策略 | 允许并发预计算 | 同一 `iter` 内允许并发（例如 Tester/Challenger 预计算），但最终写入顺序由编排器仲裁。 |
| 失败恢复 | 角色级重试 → 降级策略 → 退出 | 先重试当前角色；失败后执行降级策略；仍失败则退出本轮并上报。 |
| `stagnation.json` 写入仲裁 | Verifier 子流程唯一写入 | 与“角色边界 + 评判职责单点化”一致，编排器只读并据此触发策略。 |
| `agent_views/*` 刷新频率 | 每个角色执行后增量刷新 | 保持对 Agent 的上下文即时性，且每轮结束再做一次汇总快照。 |
| Token 预算闸门 | 不启用 | 当前阶段不引入 token 预算约束，仅保留失败/停滞相关控制。 |

## 与核心设计精神的一致性说明

- **单一职责与上下文隔离**：`stagnation.json` 继续由 Verifier 维护，避免编排器与评判角色职责混合。
- **可审计与可恢复**：失败路径明确为“重试 → 降级 → 退出”，每一步均可结构化记录。
- **对 Agent 友好而非对人友好**：`agent_views/*` 增量刷新，确保下一角色拿到最新机器可读上下文。

---

## 参考资料（官方）

- Codex 产品页
  - https://openai.com/codex/
- Codex 在 ChatGPT 的说明
  - https://help.openai.com/en/articles/11369540-codex-in-chatgpt
- Codex 开发者文档
  - https://developers.openai.com/codex
- Non-interactive（`codex exec`）
  - https://developers.openai.com/codex/noninteractive
- App Automations / Features / Worktrees
  - https://developers.openai.com/codex/app/automations
  - https://developers.openai.com/codex/app/features
  - https://developers.openai.com/codex/app/worktrees
