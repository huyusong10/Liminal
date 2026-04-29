# Collaboration Posture

> 最高原则：遵循 `product-principle.md`。Posture 不是人格标签，也不是 prompt 风格；它是用户在当前任务里如何判断风险、证据、假完成和停止条件的治理输入。

## 1. 目标

本文档定义 Loopora 如何把用户的隐性判断方式变成可运行、可观察、可裁决的 Loop 编排结构。

一句话：

> Posture is the human judgment signal that Loopora compiles into the `spec / roles / workflow` surfaces of a Loop and tests with evidence.

## 2. Posture 解决什么问题

用户使用 AI Agent 做长期任务时，最累的往往不是告诉 Agent “做什么”，而是反复纠正：

- “这看起来完成，但不是我说的完成。”
- “你太快放行了。”
- “这次应该先证明问题在哪，而不是继续写。”
- “我可以接受这个 residual risk，但不能接受那个。”
- “我不想每一轮都回来重新解释我的判断标准。”

这些反馈不是低质量输入，而是长期任务编排信号。Loopora 的职责是把它们编译进 Loop，而不是让它们只停留在一次对话里。

## 3. Posture 的边界

`collaboration posture` 是任务级的，不是用户永久人格。

它包括：

- 成功面的权重
- 假完成敏感点
- 证据偏好
- 残余风险处理方式
- 对速度、重构、保守放行、探索深度的取舍
- 角色之间如何分担构建、检查、裁决和纠偏

同一个用户在不同任务里可以有不同 posture。系统可以复用历史案例，但不能把它们误写成全局人格定律。

## 4. 编译规则

Loopora 不运行一个抽象的 posture 对象。Posture 必须被编译到三类运行面：

| 运行面 | posture 投影 |
|--------|--------------|
| `spec` | 任务契约、成功面、假完成、证据偏好、残余风险 |
| `roles` | 各角色在本任务中的工作姿态和证据责任 |
| `workflow` | 判断发生的顺序、handoff、纠偏入口和收束方式 |

这三者缺一不可：

- 只放在 `spec`，角色仍可能泛化。
- 只放在 role prompt，完成标准会漂移。
- 只放在 workflow，系统知道顺序却不知道如何判断。

## 5. 与 Contract 的关系

`contract` 提供稳定性，`posture` 提供任务级判断差异。

Posture 可以挑战 contract，例如指出 `Done When` 太窄、workflow 判断太晚、GateKeeper 太松。但它不能在 run 内静默改写：

- `Task`
- 冻结 checks
- 明确 guardrails
- 用户已确认的关键边界

需要改变这些内容时，必须回到 Loop 编辑、手动编排或导入新的 bundle；Loopora 不在 run 内静默改写。

## 6. 证据与系统边界

Posture 不应只在创建 Loop 时出现一次。真实的判断方式常常来自 run 后复盘，但复盘后的 Loop 调整是用户掌控的行为：

`run evidence -> user judgment -> imported, manually edited, or dialogue-improved Loop`

这条链路的意义是：Loopora 负责留下证据和可导出的 Loop 文件；用户或外部 Agent 决定是否以及如何改变 posture。新的候选 Loop 回到系统时，仍然必须通过导入、校验、预览和运行。

## 7. 非目标

- 不是把所有用户压成同一种最佳实践。
- 不是建立长期、全局、不可解释的人格模型。
- 不是把人格化退化成更长的 prompt。
- 不是用模糊姿态替代 task contract。
- 不是为了“更像人”而放弃可复盘、可解释、可追溯。
