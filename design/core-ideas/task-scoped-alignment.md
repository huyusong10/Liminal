# Task-Scoped Alignment

## 1. 目标

本文档定义 Loopora 的默认入口如何从“手工选择 workflow”演进为“任务驱动对齐，再导入 bundle 运行”。

一句话概括：

> 外部 Agent + Skill 负责对齐当前任务的 collaboration posture；Loopora 本体负责消费 bundle，并把它作为本地证据循环运行。

这不是在现有编排系统旁边新增一套系统，而是把现有 `spec / role definitions / workflow / loop` 解释为同一份任务姿态的不同运行面。

## 2. 核心判断

### 2.1 对齐对象是当前任务，不是抽象人格

人类在不同任务、不同风险和不同时间里的偏好并不完全稳定。

因此，Loopora 不建立一个长期、统一、全局的人格模型，而是回答更具体的问题：

- 在这次任务里，用户最在意什么？
- 在这次任务里，用户最担心哪类失败？
- 在这次任务里，用户如何接受或拒绝残余风险？
- 在这次任务里，哪些判断不应继续由人类反复回场完成？

新系统的理解对象是：

> 当前任务语境下，用户希望 AI 如何行动、取证、裁决和纠偏。

### 2.2 Alignment 是编译前端

用户通常无法直接写出完整的 runtime surfaces。

更自然的路径是：

1. 用户描述任务。
2. 外部 Agent + Skill 追问成功面、风险、证据、假完成和判断风格。
3. Skill 产出 working agreement，让用户确认姿态理解。
4. Skill 编译 YAML bundle。
5. Loopora 导入 bundle 并物化运行资产。

这意味着 Skill 的职责不是替用户运行任务，而是把任务姿态编译成 Loopora 能运行的资产。

### 2.3 Bundle 是默认入口

bundle 是对齐结果的稳定交换单元。

它必须同时是：

- readable agreement：用户能读懂为什么这样协作
- runnable config：Loopora 能直接导入运行
- revisable unit：后续反馈能生成下一版

默认入口应是：

`任务输入 -> 外部 Agent + Skill -> working agreement -> YAML bundle -> 创建循环导入 -> run`

手动入口继续存在，但它是 expert mode：

`spec / role definitions / workflow / loop 手动编辑`

两条路径导向同一套底层资产，不形成两套产品。

## 3. Working Agreement 的地位

`working agreement` 是编译时中间产物，不是运行期资产。

它的作用是：

- 让外部 Agent + Skill 有明确收敛目标。
- 让用户在生成最终 bundle 前确认“系统理解的协作方式是否正确”。
- 作为 bundle 编译前的人类可读检查点。

它不需要被 Loopora 本体长期保存为第四类运行面。

运行期真正需要被执行和复盘的仍然是：

- `spec`
- `role definitions`
- `workflow / orchestration`
- `loop / run evidence`

因此：

> agreement 用来确认理解；bundle 用来交换；runtime surfaces 用来执行；run evidence 用来修订。

## 4. Bundle 的角色

### 4.1 Bundle 是整包生命周期单元

bundle 不只是参数集合，而是一次任务姿态的完整编译结果。

它至少包含：

| 区域 | 作用 |
|------|------|
| metadata | 名称、描述、revision、来源 |
| collaboration summary | 这次任务姿态的可读摘要 |
| loop | workdir、运行参数和 loop 入口 |
| spec | task contract |
| role definitions | 各角色的 task-scoped posture |
| workflow | 角色顺序、步骤结构和 collaboration intent |

### 4.2 Bundle 必须能回到三种运行面

Loopora 本体不执行“姿态”这个抽象对象。

导入 bundle 时，系统必须把它物化为：

- `spec`，用于冻结任务合同和 checks
- `role definitions`，用于冻结角色姿态
- `workflow / orchestration`，用于冻结协作骨架
- `loop definition`，用于绑定 workdir、执行器和运行策略

这就是 bundle-first 与老编排系统的衔接点：bundle 是更高层入口，老资产是运行形态。

### 4.3 Bundle revision 是姿态微调的主要对象

用户对 run 的反馈不应被迫翻译成底层字段改动。

合理路径是：

1. 读取旧 bundle。
2. 读取 run evidence。
3. 读取用户模糊反馈。
4. Skill 解释 posture delta。
5. 产出下一版 agreement 和 bundle。

例如：

- “这次太偷懒了。”可能加强 Inspector 和 GateKeeper 对证据与完整性的要求。
- “这次不够重视重构。”可能改变 spec 的 fake-done 描述和 Builder 姿态。
- “我可以接受这个 residual risk。”可能调整 GateKeeper 的放行解释方式。

## 5. Runtime surfaces 的分工

### 5.1 Spec 是 task contract

`spec` 不只是任务描述，而是本次任务的稳定合同。

它承载：

- `Task`
- `Done When / checks`
- `Guardrails`
- 成功面
- 假完成
- 证据偏好
- 残余风险姿态

它不负责定义完整流程，也不能单独替代 role posture。

### 5.2 Role definitions 是角色姿态投影

角色定义不只是 archetype。

它承载某个角色在本次任务中的姿态，例如：

- `Inspector` 更重视可重复证据。
- `GateKeeper` 更保守地处理残余风险。
- `Builder` 更愿意做内部清理而不是只追求最短路径。
- `Guide` 更倾向收窄切口而不是扩大目标。

### 5.3 Workflow 是协作骨架

workflow 不是旧系统遗留，而是 posture 的时间结构。

它表达：

- 谁先介入
- 何时取证
- 何时裁决
- 是否需要 triage
- 是否需要 repair loop
- 是否需要 benchmark 先行
- Guide 何时介入

因此，workflow 仍然是核心资产，但它的产品解释从“用户先手工拼流程”转为“posture 被编译后的协作骨架”。

## 6. Loopora 本体与外部 Skill 的边界

### 6.1 Loopora 本体

Loopora 本体负责：

- 管理本地资产
- 导入 / 导出 / 派生 / 删除 bundle
- 物化 `spec / roles / workflow / loop`
- 启动 run
- 调用外部 LLM / Agent
- 记录事件、产物、证据和终态

Loopora 本体不负责：

- 内置聊天式任务访谈
- 在运行期执行独立 agreement 文件
- 替用户静默改写 task contract

### 6.2 外部 Agent + Skill

外部 Agent + Skill 负责：

- 与用户沟通
- 暴露关键 tradeoff
- 收敛 task-scoped posture
- 产出 working agreement
- 编译 YAML bundle
- 基于 run evidence 和反馈产出下一版 bundle

Skill 的输出不是一句建议，而是一份可导入、可运行、可修订的 bundle。

## 7. UX 演进方向

### 7.1 默认心智：从 bundle 开始

新用户默认不应先理解所有内部资产。

推荐路径应持续表达为：

- 去 Tools 安装对齐 Skill
- 让外部 Agent 生成 bundle
- 在 Create Loop 导入 bundle
- 从 run 结果和反馈生成下一版 bundle

### 7.2 Expert 心智：知道 surface 才手动改

手动编辑仍然重要，但应以 surface 责任为入口：

- 任务合同错了，改 `spec`
- 角色行为错了，改 role definition
- 判断时机错了，改 workflow
- 整体姿态要改，回到 bundle revision

### 7.3 Bundle 生命周期应保持整包语义

导入后的 bundle-owned 资产默认属于同一组。

删除、导出、派生和 revision 应优先按 bundle 生命周期表达，避免用户把同一份姿态拆成互相漂移的零散对象。

## 8. 变更触发

以下变化需要更新本文档：

- 默认入口不再是 task alignment -> bundle -> import
- working agreement 变成运行期资产
- bundle 不再是单文件 YAML
- posture 不再由 `spec / role definitions / workflow` 共同承载
- Loopora 本体开始承担内置聊天式任务对齐

以下变化通常不需要更新本文档：

- 对齐话术调整
- bundle 字段小幅扩展
- Web 页面文案和布局调整
- 内置 workflow 示例调整
