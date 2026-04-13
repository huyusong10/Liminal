# Liminal v0.1

Liminal 是一个“指标驱动 + 角色隔离”的自主迭代框架原型。当前仓库实现了 **外部编排器（control plane）** 的最小可运行版本，用于验证：

- 角色分离循环（Generator / Tester / Verifier / Challenger）
- 可审计状态写入（`state/*.jsonl` + `handoff/*.json`）
- 停滞检测与 Challenger 触发
- 面向 Agent 的文本观测产物（`state/agent_views/*`）

> 当前版本为 v0.1 bootstrap：角色执行逻辑是可运行模拟器，重点是先打通控制面与契约。

---

## 目录结构

```text
.
├── orchestrator.py                  # 编排入口
├── orchestrator/                    # 核心模块
├── spec/                            # 规格与约束
├── state/                           # 运行状态与历史
├── handoff/                         # 角色交接文件
├── workspace/src/                   # Generator 产物（示例网站）
├── scripts/replay_demo.sh           # 一键回放
└── desgin/                          # 设计与调研文档（按历史命名保留）
```

---

## 快速开始

### 1) 运行一次最小循环

```bash
python3 orchestrator.py --max-iters 1 --base .
```

### 2) 运行回放脚本

```bash
bash scripts/replay_demo.sh
```

脚本会：
1. 执行 5 轮迭代；
2. 输出 `handoff/verifier_verdict.json`；
3. 列出 `workspace/src/` 下生成的网站文件。

---

## 网站生成测试（你要求的“随便做一个网站”）

通过 `handoff/task.json` 注入任务：

```json
{
  "task_type": "build_website",
  "title": "Liminal Demo Site",
  "theme": "dark",
  "prompt": "做一个简单的单页介绍网站"
}
```

当 `task_type=build_website` 时，Generator 会在 `workspace/src/` 生成：

- `index.html`
- `style.css`

---

## 关键文件说明

### `spec/`
- `test_cases.json`：测试用例定义
- `acceptance_criteria.json`：验收指标阈值
- `constraints.md`：Generator 约束

### `handoff/`
- `tester_output.json`：Tester → Verifier
- `verifier_verdict.json`：Verifier → Generator
- `challenger_seed.json`：Challenger → Generator
- `task.json`：外部任务注入（当前包含网站生成任务）

### `state/`
- `metrics_history.jsonl`：指标历史
- `iteration_log.jsonl`：Generator 决策日志
- `stagnation.json`：停滞检测状态
- `run_events.jsonl`：编排事件日志
- `agent_views/*`：Agent 可消费文本观测

---

## 当前策略（已收敛）

- 主循环：外部脚本实现
- Skill：当前不使用
- 硬 reset：仅新建 session
- 失败恢复：角色级重试 → 降级策略 → 退出
- 观测目标：优先给 Agent，而非人类仪表盘

---

## 开发状态

- ✅ 已完成：MVP 外部编排闭环、状态落盘、演示网站生成
- ⏳ 下一步：将模拟角色执行替换为真实 `codex exec --json` 调用

---

## 常见命令

```bash
# 运行 3 轮
python3 orchestrator.py --max-iters 3 --base .

# 语法检查
python3 -m py_compile orchestrator.py orchestrator/*.py

# 回放演示
bash scripts/replay_demo.sh
```
