# Liminal v0.1 使用手册

Liminal 是一个“指标驱动 + 角色隔离”的外部编排器原型。它按 **Generator → Tester → Verifier → Challenger(可选)** 的流程迭代，并把全部关键状态写入本地文件，便于回放与审计。

## 1. 你会得到什么

- 可运行的最小闭环编排器（外部 control plane）。
- 完整落盘状态：`state/*.jsonl`、`handoff/*.json`、`state/agent_views/*`。
- 停滞检测（plateau/regression）与 Challenger 触发。
- 失败恢复链路：**重试 → 降级 → 中止并输出 machine-readable 错误摘要**。

## 2. 目录说明（只保留使用相关）

```text
.
├── orchestrator.py                # 入口
├── orchestrator/                  # 编排核心实现
├── spec/                          # 规格与阈值
├── state/                         # 历史状态与事件
├── handoff/                       # 角色交接文件
├── workspace/src/                 # Generator 产物
└── scripts/replay_demo.sh         # 一键回放示例
```

## 3. 快速开始

### 3.1 运行 1 轮

```bash
python3 orchestrator.py --max-iters 1 --base .
```

### 3.2 运行 10 轮（推荐）

```bash
python3 orchestrator.py --max-iters 10 --base .
```

### 3.3 一键回放

```bash
bash scripts/replay_demo.sh
```

## 4. 输入任务样例

编辑 `handoff/task.json`（示例）：

```json
{
  "task_type": "build_website",
  "title": "Liminal Demo Site",
  "theme": "dark",
  "prompt": "做一个简单的单页介绍网站"
}
```

运行后会在 `workspace/src/` 看到：

- `index.html`
- `style.css`

## 5. 输出结果怎么读

### 5.1 核心 verdict

- 文件：`handoff/verifier_verdict.json`
- 关键字段：
  - `passed`
  - `composite_score`
  - `metric_scores`
  - `failed_case_ids`
  - `hard_constraint_violations`

### 5.2 历史与事件

- `state/metrics_history.jsonl`：每轮分数与通过状态。
- `state/iteration_log.jsonl`：Generator 每轮决策记录。
- `state/run_events.jsonl`：编排事件流（含重试/降级/中止摘要）。
- `state/stagnation.json`：停滞状态与触发记录。

### 5.3 Agent 观测文件

- `state/agent_views/agent_brief.json`
- `state/agent_views/score_trend.mmd`
- `state/agent_views/current_mode.mmd`

## 6. 常用命令

```bash
# 语法检查
python3 -m py_compile orchestrator.py orchestrator/*.py

# 运行 3 轮
python3 orchestrator.py --max-iters 3 --base .

# 查看最新 verdict
cat handoff/verifier_verdict.json
```

## 7. 失败恢复行为示例

当某角色连续失败时，系统会按顺序执行：

1. 角色级重试（最多 `max_retries + 1` 次）。
2. 启用一次降级策略后再次重试。
3. 若仍失败：写入 `run_aborted` 事件，并在 `verifier_verdict.json` 里输出 `ROLE_EXECUTION_ABORT` 错误摘要。

这使失败路径可回放、可机器解析。
