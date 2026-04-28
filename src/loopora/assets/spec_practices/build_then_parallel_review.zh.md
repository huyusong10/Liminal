---
summary: "场景：一个产品任务需要先形成真实实现，再用两个独立证据视角检视后才能安全收口。"
---

## 场景

团队希望 AI Agent 推进一个有一定规模的产品改动。目标已经足够清楚，可以先做出第一版实现，但误差风险不是单一的：结果可能不符合用户契约，也可能缺少可复验证据。单一 reviewer 很容易漏掉其中一面。

## 需求

先构建一个可检视的结果，再分别从契约和证据两个视角复查，最后决定这次 loop 是否可以结束。

## 适合这个流程，因为

Builder 先创建一个具体状态。Contract Inspector 检查它是否符合任务契约、guardrails 和 fake-done 风险。Evidence Inspector 独立检查主路径是否有可重复证据。GateKeeper 最后只在两条检视面都支持时收束。

## 为什么不是其他流程

这不是 `Evidence First`，因为目标已经足够清楚，可以先尝试实现。也不是 `Repair Loop`，因为任务还没有预设一定要做第二轮修复。除非已有稳定 benchmark 或 contract proof 是主判断依据，否则也不是 `Benchmark Gate`。

## 为什么不直接交给 AI Agent

AI Agent 可以直接做第一版，但人类通常会在之后回来问两个不同问题：它真的满足任务了吗？证据够可信吗？Loopora 把这两个检查外化成有界并行检视组，再让 GateKeeper 基于汇总证据裁决。

## 示例 spec

# Task

交付所请求功能的第一版可用实现，并让结果能同时从用户契约和证据两个角度被检视。

# Done When

- 用户可感知的主路径已经存在，并且可以被实际操作或执行。
- 实现遵守任务契约和 guardrails。
- 至少有一条可重复证据证明主路径或核心行为。
- GateKeeper 可以引用契约检视和证据检视两方面的 evidence 后再结束。

# Guardrails

- 不要只凭截图、静态页面或乐观总结宣称完成。
- 第一版应该聚焦一个连贯切片，不要散落地修改很多无关点。
- Builder 必须留下足够清楚的 handoff，让两个 Inspector 能检查同一个产物。

# Success Surface

- 结果像一个真实可用的第一版切片，而不是演示外壳。
- 主行为可以通过具体文件、命令、artifact 或浏览器可见行为解释清楚。

# Fake Done

- UI 看起来完整，但主路径不能工作。
- 测试或 artifact 存在，但没有覆盖用户真正关心的承诺。
- 实现只偶然跑通一次，却没有留下 GateKeeper 可复核的证据。

# Evidence Preferences

- 优先使用项目自有命令、浏览器路径、contract test 或可重新生成的 artifact。
- 除非任务明确是视觉任务，否则静态外观只能作为次级证据。

# Role Notes

## Builder Notes

创建一个连贯、可检视的结果，并留下两个 Inspector 可以独立复查的简洁 handoff。

## Contract Inspector Notes

先检查结果是否符合任务契约、guardrails 和 fake-done 风险，再讨论次要 polish。

## Evidence Inspector Notes

为主路径收集可重复证据，并明确标出弱证据、间接证据或缺失证据。

## GateKeeper Notes

只有当两个检视面都支持 verdict，并且 evidence ledger 足以解释为什么可以收口时，才结束 run。
