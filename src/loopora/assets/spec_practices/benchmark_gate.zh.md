---
summary: "场景：任务已有 benchmark 或 contract proof，loop 应该在改动前后使用同一度量路径。"
---

## 场景

任务已经有可重复 benchmark、contract test 或度量 artifact。主要风险不是 Agent 不努力，而是实现后换了一套更容易的证据标准来宣称进步。

## 需求

先读取 benchmark 证据，再做一个聚焦改动，然后沿同一证据路径复查，最后由 GateKeeper 基于更新后的 proof 裁决。

## 适合这个流程，因为

Benchmark Inspector 建立 baseline。Builder 针对最高杠杆的失败信号修复。Regression Inspector 在改动后复跑或检查同一路径。GateKeeper 只在重复证据足够强、残余风险可接受时收口。

## 为什么不是其他流程

这不是 `Build + Parallel Review`，因为主决策来源已经是 benchmark。也不是 `Evidence First`，因为证据机制已经存在，应当复用。除非第一轮修复必然暴露第二个 blocker，否则也不是 `Repair Loop`。

## 为什么不直接交给 AI Agent

AI Agent 可以优化某个数字，但如果没有外部 loop，它可能更换证据标准、过拟合一个 spot check，或在没有可重复 proof 的情况下总结“已有提升”。Loopora 会把改动前后的证据路径钉住。

## 示例 spec

# Task

使用现有 benchmark 或 contract proof 改善最重要的失败信号，同时不改变证据标准。

# Done When

- 改动前的 benchmark 或 contract 证据已经记录。
- Builder 针对最高杠杆的已测量 blocker 行动。
- 改动后的证据使用同一个 benchmark、contract proof 或度量路径。
- GateKeeper 可以引用重复证据，并说明仍然存在的 residual risk。

# Guardrails

- 实现后不要切换到更容易通过的证据。
- 不要为了优化局部指标而破坏用户可见契约。
- 保留解释 verdict 的 benchmark 输出或 artifact。

# Success Surface

- 已测量 blocker 改善，或被更明确地收窄。
- 改动前后的证据路径保持可比较。

# Fake Done

- 另一个命令通过了，但原始 benchmark 仍然失败。
- 某个数字改善了，但任务契约被破坏。
- 最终 verdict 缺少 benchmark 或 contract evidence refs。

# Evidence Preferences

- 优先使用项目自有 benchmark 输出、contract proof、回归报告或保存的指标 artifact。
- 把轶事式检查当作辅助上下文，而不是主证明。

# Role Notes

## Benchmark Inspector Notes

捕获 baseline 证据，并指出最高杠杆的失败信号。

## Builder Notes

用最小改动修复已测量 blocker，不改变证据标准。

## Regression Inspector Notes

沿同一证据路径复查，并指出回归、过拟合或度量缺口。

## GateKeeper Notes

只有当重复证据足以支撑 verdict，且 residual risk 明确时，才通过。
