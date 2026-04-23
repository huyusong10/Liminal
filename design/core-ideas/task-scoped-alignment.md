# Task-Scoped Alignment

## 1. 目标

本文档定义 Loopora 下一阶段的系统演进方向：

- 保留现有 Loopora 作为本地编排与执行入口。
- 新增一条“任务驱动对齐 -> 生成 bundle -> 导入运行”的默认入口。
- 让 `collaboration posture` 通过 `spec / role definitions / workflow` 三者共同承载，而不是只落在单一 prompt 或单一配置上。

一句话概括：

> Loopora 继续做编排器；外部 Agent + Skill 负责与用户对齐，并把对齐结果编译成可导入的协作 bundle。

## 2. 核心判断

### 2.1 不建模抽象人格，改为建模任务中的协作方式

人类在不同时间、不同任务、不同风险面前表现出来的偏好并不稳定。

因此，Loopora 不应试图建立一个长期、统一、全局的人格模型，而应回答更具体的问题：

- 在这次任务里，用户最在意什么？
- 在这次任务里，用户最担心哪类失败？
- 在这次任务里，用户希望 AI 如何取证、如何裁决、如何推进？

因此，新系统的理解对象不是 “who the user is”，而是：

> 在当前任务语境下，用户希望如何与 AI 协作。

### 2.2 collaboration posture 不是单点配置

`collaboration posture` 不能只由 `spec` 承载，也不能只由 prompt 承载。

它需要同时体现在三类产物里：

- `spec`
  表达这次任务的目标边界、成功面、最不能糊弄的部分、最信任的证据类型、允许和不允许的残余风险。
- `role definitions`
  表达不同角色在本次任务中的工作姿态，例如更保守的 GateKeeper、更注重证据链的 Inspector、更倾向收缩范围的 Guide。
- `workflow / orchestration`
  表达这次任务中角色顺序、判定时机、介入方式、是否优先 inspect、是否需要 repair loop 等协作骨架。

缺少其中任一项，posture 都无法被完整执行。

### 2.3 working agreement 是编译时中间产物

`working agreement` 是这套新系统里的一个关键概念，但它不是 Loopora 的最终运行输入。

它的作用是：

- 让外部 Agent + Skill 在与用户沟通时有一个明确的收敛目标。
- 让用户在生成最终 bundle 前确认“系统理解的协作方式是否正确”。
- 作为 bundle 编译前的人类可确认中间表示。

它不需要在 Loopora 运行期作为第四类独立资产长期存在。

运行期真正需要被导入并执行的，仍然是：

- `spec`
- `role definitions`
- `workflow / orchestration`

因此：

> `working agreement` 是对齐阶段的中间表示；`bundle` 才是导入 Loopora 的最终产物。

## 3. 系统边界

### 3.1 Loopora 本体的职责不变

Loopora 仍然是一个写死骨架的本地编排系统。

它的职责仍然是：

- 管理资产
- 导入 / 导出编排产物
- 启动 run
- 调用外部 LLM / Agent 执行
- 记录事件、产物与终态

Loopora 本体不需要内置“与用户多轮沟通”的 Agent 能力。

### 3.2 外部 Agent + Skill 负责对齐

与用户沟通、理解任务、举例提问、解释模糊反馈、生成中间 agreement 的，是外部 Agent 加载的 Skill。

因此，这套新系统的默认入口应变为：

`任务输入 -> 外部 Agent + Skill 对话 -> 确认 working agreement -> 生成 bundle -> 导入 Loopora -> 运行`

这意味着：

- Loopora 不需要自己变成聊天产品。
- Loopora 需要能够接收由外部 Agent 编译出来的 bundle。
- Skill 成为“理解与编译”的主要入口。

### 3.3 手动编排模式继续保留

现有手动编排系统仍然保留，并继续作为 expert mode 存在。

原因：

- 高级用户仍可能希望直接编辑 `spec / roles / workflow`。
- 手动模式本身也是 bundle 的最终可编辑形态。
- 新入口不应替代现有系统，而应降低默认使用门槛。

## 4. 演进后的用户路径

### 4.1 默认路径：任务驱动

面向大多数用户的推荐路径应是：

1. 用户描述任务。
2. 外部 Agent + Skill 识别任务形状与关键分歧点。
3. Skill 通过多轮沟通，与用户对齐本次任务里的协作方式。
4. Skill 显式产出 `working agreement` 并请求用户确认。
5. Skill 根据 agreement 生成 bundle。
6. 用户将 bundle 导入 Loopora，一键运行，必要时再局部编辑。

### 4.2 专家路径：直接编排

面向熟悉 Loopora 的用户，仍然保留：

- 直接写 `spec`
- 直接编辑 role definitions
- 直接编辑 orchestration / workflow
- 直接启动 run

这两条路径应导向同一套底层资产模型，而不是形成两套割裂系统。

## 5. bundle 的角色

### 5.1 bundle 是最终导入单位

新系统应引入一个统一、可读、可导入、可导出的 bundle 形态。

这份 bundle 的角色不是“再定义一层抽象”，而是作为：

- 外部 Skill 编译结果
- Loopora 导入输入
- 用户复用 / 分享 / 修改的标准单元

bundle 可以采用简单 `yml` 作为主格式。

### 5.2 bundle 必须同时是 runnable config 和 readable agreement

如果 bundle 只是若干运行参数的集合，它就无法承载 posture。

因此 bundle 必须同时满足两件事：

- 对 Loopora 来说，它是可执行的配置集合。
- 对用户来说，它是可读的协作协议投影。

这意味着 bundle 内部不能只存放“怎么跑”，还必须显式表达：

- 这次任务的目标理解
- 这次任务中最重要的成功面
- 最担心的失败方式
- 证据偏好
- 角色姿态
- 为什么采用这套流程

### 5.3 bundle 是后续微调的主要对象

后续迭代时，用户不应被迫从零开始重新生成整套配置。

更合理的路径是：

- 读取现有 bundle
- 读取用户对本次 run 的模糊反馈
- 外部 Skill 重新解释这次任务中的 posture 偏移
- 更新 agreement
- 重新编译下一版 bundle

因此，bundle 不是一次性产物，而是持续演化的工作单元。

## 6. spec / role / workflow 的演进方向

### 6.1 spec 需要承载任务级协作意图

`spec` 不再只是任务描述与验收项。

它还应逐步承载：

- 本次任务中最不能被糊弄的部分
- 本次任务中最重要的证据类型
- 残余风险的接受方式
- 何种结果虽然“能跑”但仍不应被视为完成

也就是说，`spec` 需要从“任务说明”演进为“任务合同”。

### 6.2 role definitions 需要承载角色姿态

role definition 不应只表达 archetype 的静态职责，还应能表达本次任务里的姿态偏向。

例如：

- Inspector 是否更强调证据链完整性
- GateKeeper 是否更强调 maintainability
- Guide 是否优先建议收缩范围

也就是说，role definition 需要从“固定角色模板”演进为“角色姿态投影点”。

### 6.3 workflow 需要承载协作骨架

workflow 仍然表达步骤顺序，但它也不只是单纯的执行图。

它需要继续作为 posture 的结构化结果，表达：

- 哪个角色先介入
- 哪个角色负责首次收束
- 是否需要 Guide 在主路径外介入
- 哪类任务更适合 inspect-first / repair-loop / fast-lane

因此，workflow 仍然是协作意图的重要承载面，而不是单纯流程图。

## 7. 外部 Skill 的作用

### 7.1 Skill 是“协作编译器”的入口

这套 Skill 的职责不是“替用户写代码”，而是：

- 与用户沟通
- 理解任务
- 暴露关键分歧点
- 收敛 posture
- 生成 agreement
- 最终编译 bundle

### 7.2 Skill 的输出不是一句建议，而是一份可执行 bundle

Skill 的价值不在于给出一个口头建议，而在于：

- 产出一份 Loopora 可直接导入的 bundle
- 让用户确认后就能一键运行
- 让后续微调围绕同一份 bundle 继续演进

### 7.3 Skill 也应成为后续纠偏入口

用户对 run 的反馈，例如：

- “这次太偷懒了。”
- “这次不够重视重构。”
- “这次太保守了。”

不应直接被用户手工翻译成 workflow 改动。

更合理的路径是：

- 用户把这类模糊反馈交给 Skill
- Skill 基于旧 bundle 与 run 结果重新理解 posture 偏移
- Skill 输出新的 bundle 版本

因此，Skill 不只是 onboarding 工具，也应是后续微调的统一入口。

## 8. UX 演进方向

### 8.1 从“逐资产管理”转向“以 bundle 为中心”

如果用户导入的是一个由 `spec + roles + workflow` 组成的 bundle，那么用户心智也应围绕 bundle，而不是围绕单个孤立资产。

因此，系统在易用性上应逐步支持：

- 整包导入
- 整包查看
- 导入后快速修改
- 整包删除
- 局部派生另存

### 8.2 导入后的修改应尽量顺滑

用户导入 bundle 后，常见需求不是“从头重写”，而是：

- 调一个角色姿态
- 改一处流程顺序
- 缩一缩 spec 的成功面

因此，导入后的编辑体验应优先支持“快速微调”，而不是重新走完整编排流程。

### 8.3 删除语义应贴近用户心智

用户删除一个“循环”时，通常希望删除的是本次导入的整套协作包，而不是留下散落角色定义与流程资产等待手工清理。

因此，系统 UX 需要逐步从“删除单个流程”演进到“删除整个 bundle 相关内容”的心智模型。

## 9. 系统演进路径

### 第一阶段：引入 bundle 作为标准导入导出单元

目标：

- 让 Loopora 能稳定导出当前编排结果为 bundle
- 让 Loopora 能从 bundle 导入 `spec / roles / workflow`
- 让 bundle 成为可读、可分享、可复用的标准单元

这一阶段的重点不是对话，而是先确立统一产物边界。

### 第二阶段：引入对话型 Skill

目标：

- 让外部 Agent + Skill 能围绕任务与用户沟通
- 显式生成 `working agreement`
- 根据 agreement 编译 bundle

这一阶段的重点是把“任务输入 -> bundle 输出”的路径打通。

### 第三阶段：引入基于 Skill 的微调迭代

目标：

- 允许用户基于实际 run 给出模糊反馈
- 让 Skill 使用旧 bundle + 反馈生成新版本 bundle
- 让“纠偏”成为常规路径，而不是从零重建

这一阶段的重点是让 bundle 成为持续演化的协作资产。

### 第四阶段：以 bundle 为中心优化 UX

目标：

- 围绕 bundle 做导入、删除、复制、修改
- 降低用户在“资产散落”上的管理成本
- 让 Guided Mode 与 Manual Mode 长期共存

这一阶段的重点是让整套心智在产品里真正顺滑可用。

## 10. 非目标

- 不把 Loopora 本体改造成内置聊天 Agent。
- 不建立一个长期、统一、永久有效的全局人格模型。
- 不把 posture 简化成单一 prompt 文案。
- 不让 spec 单独承担全部 posture 语义。
- 不移除现有手动编排模式。
