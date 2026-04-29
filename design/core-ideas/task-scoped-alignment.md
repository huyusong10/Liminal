# Task-Scoped Alignment

> 最高原则：遵循 `product-principle.md`。Alignment 是取得或调整 Loop 的一种场景，不是 Loopora 主工作流本身。它的目标不是尽快产出 YAML，而是把当前长期任务的判断方式编译成可运行、可观察、可裁决的 Loop。

## 1. 目标

本文档定义 Web 问答和外部 Skill 如何帮助用户编排 Loop。

一句话：

> Alignment is a compiler front-end for composing a Loop from task-specific judgment.

它服务于主工作流中的第一步：

`编排 Loop`

它不拥有后续主工作流：

`运行 Loop -> 自动迭代并收集证据 -> 输出证据裁决与结果`

## 2. 对齐对象

Alignment 对齐的不是抽象人格，也不是通用最佳实践，而是当前任务的编排判断：

- 什么算真实进展？
- 什么是假完成？
- 用户信任哪些证据？
- 哪些残余风险可以接受，哪些必须阻断？
- 谁负责构建，谁负责取证，谁负责裁决？
- workflow 应如何推进、并行检视、纠偏或停止？

这些问题必须先形成 working agreement，再编译成候选 Loop。

这些判断不要求用户一开始就能完全外化成规则。Alignment 的价值之一，是通过提问、复述和候选方案，把用户隐性的判断姿态转成 `spec / roles / workflow` 可以承载的运行结构；其中 Inspector 可以是 posture-driven 的语义检视者，而不只是执行固定规则的检查器。

## 3. Working Agreement

`working agreement` 是编译期中间产物，不是运行期资产。

它的作用是：

- 让 alignment agent 有明确收敛目标。
- 让用户确认系统是否理解本次任务的判断方式。
- 给 bundle 编译前提供人类可读检查点。

运行期真正需要执行和复盘的仍然是：

- `loop definition`
- `spec`
- `role definitions`
- `workflow / orchestration`
- `run evidence`

## 4. Bundle 的位置

`bundle` 是候选 Loop 的内部交换单元，不是新手默认心智。

它必须同时是：

- readable plan：用户能看懂为什么这样协作
- runnable package：Loopora 能导入并物化为本地 Loop 资产
- portable exchange file：用户可在系统外保存、编辑或交给其他工具处理后再导入

默认 Web 问答创建场景应表达为：

`任务输入 -> 对齐 Loop -> READY 预览 -> 创建 Loop 并运行`

与它并列的其他编排场景可以继续表达为：

- `YAML bundle -> 校验 / 预览 / 导入 / 导出 / 派生 / 删除`
- `spec / role definitions / workflow -> 创建 Loop -> 运行 -> 可选导出 bundle`

## 5. Runtime surfaces

Loopora 不执行一个独立 agreement 文件。导入 bundle 后，系统必须把编排结构物化到：

| surface | 职责 |
|---------|------|
| `loop definition` | workdir、执行器、运行策略 |
| `spec` | task contract、成功面、假完成、证据偏好、残余风险 |
| `role definitions` | 各角色的 task-scoped posture 与证据责任 |
| `workflow / orchestration` | 角色顺序、handoff、纠偏入口、自动迭代和收束条件 |

这些 surface 是同一个 Loop 的不同投影，不应在后续编辑中彼此漂移。

## 6. Loopora 本体与 Alignment Agent

Loopora 本体负责：

- 管理本地资产
- 导入 / 导出 / 派生 / 删除 bundle
- 物化 `spec / roles / workflow / loop`
- 启动 run
- 调用外部 AI Agent CLI
- 按 Loop 自动迭代
- 记录事件、产物、证据和终态

Alignment agent 负责：

- 与用户沟通
- 暴露关键 tradeoff
- 收敛 task-scoped judgment
- 产出 working agreement
- 编译 YAML bundle

Alignment agent 可以来自 Web 内置 session，也可以来自外部 AI Agent 加载 repo-local Skill。两条路径必须产出同一种可运行 bundle。Loopora 本体不决定用户应该如何演进 Loop；它只负责提供取得 / 调整 Loop 的入口、导入导出、运行和证据记录。

## 7. 调整已有 Loop

用户可以拿着 bundle、run evidence 和自己的判断去外部 Agent、Web 对话改进入口或手工编辑器里生成新 bundle。这是用户主动编排行为，不是 Loopora 的运行职责，也不是系统持有的 Loop 演化历史。

Loopora 需要保证：

- bundle 可以导出成完整 YAML。
- run evidence 和 artifact 可以被追查。
- 从已有 bundle 或 run evidence 发起的对话改进只生成独立候选 bundle。
- 用户带回或生成新 bundle 时，仍通过同一校验、预览、导入和运行路径进入系统。
- Loopora 不记录候选 Loop 与原 Loop 的 lineage、diff 或回滚关系；这些演化判断留在用户系统外。

## 8. 变更触发

以下变化需要更新本文档：

- Web 问答不再是取得 Loop 的一种场景，而变成主工作流本身。
- working agreement 变成运行期资产。
- bundle 不再是单文件 YAML 交换单元。
- Loop 运行结构不再由 `spec / role definitions / workflow` 共同承载。
- Web 内置 alignment 绕过 bundle 导入，直接创建底层资产。

以下变化通常不需要更新本文档：

- 对齐话术调整。
- bundle 字段小幅扩展。
- Web 页面文案和布局调整。
- 内置 workflow 示例调整。
