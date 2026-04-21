---
summary: "场景：企业 SSO onboarding 分支已经接近完成，现在需要 Builder、Inspector 和 GateKeeper 做最后一次发布前收口。"
---

## 场景

企业 onboarding 分支已经快可以发布了。被邀请的管理员应该能够从组织邀请链接进入，通过新的 SSO 设置完成 onboarding，并最终进入组织 dashboard。这个发布分支今天就要收口，所以团队只想再做“一轮 Builder 收尾、一轮 Inspector 验收、最后 GateKeeper 严格裁决”。

## 需求

把企业 SSO onboarding 剩下的已知交付缺口补齐，并且只围绕这一块范围做出干脆的上线判断。

## 适合这个流程，因为

这类任务里，Builder 剩下的是明确的交付缺口，Inspector 面对的是很清楚的验收点，而 GateKeeper 需要给出严格的可发或不可发判断，不该再把问题带回探索阶段。

## 示例 spec

# Task

把企业 SSO onboarding 准备到可发布状态，让被邀请的管理员可以完成配置并进入自己的组织 dashboard。

# Done When

- 被邀请的管理员可以从现有邀请链接出发，成功完成 SSO onboarding 路径。
- onboarding 流程最终会把管理员带到正确的组织 dashboard。
- 有一条项目内检查路径，在至少一个代表性组织和邀请样本上验证这条发布路径。
- 产品约定里要求出现的 onboarding 或审计产物已经被正确记录。
- 这一轮交付范围内不再存在已知阻塞。

# Guardrails

- 保留现有邀请链接契约，以及非 SSO 的认证流程。
- 改动范围只聚焦在 SSO onboarding 这一段发布切片。
- 优先做清晰、可评审的改动，不额外追求可有可无的打磨。

# Role Notes

## Builder Notes

目标是交付完整可验收的切片，而不是停在半成品原型。

## Inspector Notes

只围绕 GateKeeper 下一步会判断的验收点收集证据。

## GateKeeper Notes

对当前范围做干脆的可交付或不可交付判断，不要重新把问题扩大成探索任务。
