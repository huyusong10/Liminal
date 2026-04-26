---
summary: "场景：在更大范围 rollout 前，hybrid-search 项目需要用一轮 benchmark 驱动的优化，决定下一次人工复核还该继续盯 retrieval、reranking 还是 query rewrite。"
---

## 场景

hybrid-search rollout 已经逐步接近要不要继续扩灰的判断点。发布被一组 relevance benchmark 和锁定分数门槛卡住。现在的工作已经不再是修单个缺陷，而是要一轮轮判断：下一轮应该继续压 retrieval、reranking，还是 query rewrite。这次 loop 的任务，就是把最新 benchmark 证据翻译成下一个明确动作。

## 需求

完成一轮由 benchmark 驱动的优化，并留下足够新的证据，判断下一轮应该继续压同一子系统，还是切到别的子系统。

## 适合这个流程，因为

这类任务每一轮都该从测量结果出发，而不是从直觉出发。先让 GateKeeper 读 benchmark 产物，再让 Builder 围绕这个裁决继续优化；只有当最新分数和 breakdown 真正改变了下一步判断，下一轮才有意义。

## 为什么不是其他流程

这不是 `Build First`，因为系统已经存在了，现在决定下一步的也不再是“能不能跑起来”。它也不是 `Inspect First`，因为目标不是钉住某条失败路径，而是根据 benchmark 结果决定下一轮优化方向。它更不是 `Repair Loop`，因为每一轮真正的主驱动仍然是最新评测结果，而不是某次修复后的残余缺口。

## 为什么不直接交给 AI Agent

如果没有 Loopora，AI Agent 可以沿着一个方向一直优化下去，但人类仍然得在每次 benchmark 之后回来确认：这次提分是不是提在了对的地方、残余损失还在不在同一子系统、下一轮是不是该换方向。这种重复性的人工回看，正是 Loopora 想减少的流量。Loopora 先让 `GateKeeper` 读 benchmark，再让 `Builder` 围绕它行动，同时把下一轮决策需要的证据保留下来，不用让人类每次都重新把上下文讲一遍。

## 示例 spec

# Task

用一轮 benchmark 引导的优化，把 hybrid-search 质量继续往前推进，并留下新的分数证据，决定下一轮应该继续压同一子系统还是切换方向。

# Done When

- relevance benchmark 可以在仓库里端到端重跑。
- 最新评估产物来自当前工作区，并保持可检查。
- 这一轮要么让 benchmark 相对锁定基线继续提升，要么把最大的残余损失收敛到一个已验证的子系统。
- 最新 benchmark breakdown 已经足够具体，能判断下一轮该继续压 retrieval、reranking 还是 query rewrite。
- 声称的收益能追溯到真实产品改进，而不是只服务于 benchmark 的取巧技巧。

# Guardrails

- 不要硬编码 benchmark 答案、标签或一次性缓存。
- 在优化过程中保留线上搜索的真实产品契约。
- 保持报告、分数 breakdown 和 benchmark 输入可检查，方便下一轮接力。

# Role Notes

## GateKeeper Notes

先看最新 benchmark 产物；如果 harness 自身还不可信，要先保守判定。

## Builder Notes

优先修改真实子系统，不要追逐对 rollout 没有价值的一次性分数尖峰。
