# Collaboration Posture

## 1. 目标

本文档定义 Loopora 的核心产品解释：

- Loopora 不是单纯的 workflow 编排工具。
- Loopora 也不是长期人格建模系统。
- Loopora 是把当前任务里的协作姿态编译成可运行证据循环的本地系统。

一句话概括：

> Loopora 是 collaboration posture compiler + evidence loop runtime。

这里的重点不是在“姿态”和“循环”之间选一个，而是明确它们的关系：

- posture 说明这次任务应该如何判断。
- bundle 保存 posture 被编译后的协作约定。
- `spec / role definitions / workflow` 是 posture 的运行投影。
- loop 通过每轮行动、取证与裁决，让这些投影接受新证据检验。

## 2. 问题判断

用户想用 Loopora，通常不是因为他已经掌握一套可直接运行的 `spec / role definitions / workflow` 规则，也不是因为底层 Agent 完全不能独立做事。

更常见的原因是：

- 任务足够长，单次输出之后还会出现新的判断点。
- 用户对“什么算完成”有稳定直觉，但很难一开始写成规则。
- 用户知道自己会反复追问证据、反复纠正偷懒、反复决定下一轮方向。
- 用户希望减少这些回场次数，但又不能放弃可解释、可复盘、可停止的边界。

因此，Loopora 要自动化的不是抽象人格，而是当前任务里的判断负担：

- 默认怀疑什么？
- 最信任哪类证据？
- 哪些状态属于 fake done？
- 残余风险可以如何被接受或拒绝？
- 下一轮应该继续推进、先检查、交给 GateKeeper 裁决，还是让 Guide 收窄方向？

## 3. 核心模型

### 3.1 Posture 是任务级判断模型

`collaboration posture` 指当前任务中的协作判断方式，而不是用户的永久人格。

它包括：

- 成功面的权重
- 风险和残余风险的处理方式
- 证据偏好
- 对重构、速度、保守放行、探索深度的偏好
- 对“看起来完成但其实不够”的敏感点
- 角色之间如何分担行动、取证、裁决和纠偏

同一个用户在不同任务里可以拥有不同 posture。Loopora 可以复用案例和偏好，但不能把它们误写成全局人格定律。

### 3.2 Bundle 是编译结果

posture 需要先被外部 Agent + Skill 对齐，然后编译成 bundle。

`working agreement` 是编译期中间表示，用来让用户确认“系统是否理解这次任务该如何被监督”。它不是运行期资产。

`bundle` 才是稳定交换单元。它必须同时是：

- 可读的协作协议投影
- 可运行的 Loopora 配置集合
- 可修订的 posture 版本

### 3.3 Runtime surfaces 是执行投影

Loopora 运行时不执行一个叫 posture 的神秘对象。它执行三类投影：

| 运行面 | posture 投影 |
|--------|--------------|
| `spec` | 任务契约、成功面、边界、证据偏好、残余风险 |
| `role definitions` | 各角色在本次任务中的工作姿态 |
| `workflow` | 角色顺序、判断时机、纠偏入口和收束方式 |

这三者共同表达 posture，缺一不可。

### 3.4 Loop 是证据机制

loop 的价值不是重复调用 Agent，而是在每一轮行动后产生新证据。

角色分离是核心不变量：

- `Builder` 负责改动。
- `Inspector` 负责从更新后的世界取证。
- `GateKeeper` 负责裁决。
- `Guide` 只在停滞、回退或方向需要收窄时介入。

这使 posture 不会退化成 Builder 的自我感觉，而是被每轮新证据检验。

## 4. Posture 的表达原则

### 4.1 不以规则为唯一入口

规则有效，但不是用户最自然的表达方式。

用户更容易表达的是：

- “这次太保守了。”
- “这次完全没重视重构。”
- “这个 residual risk 我可以接受。”
- “它虽然能跑，但我不认为这算完成。”

这些模糊反馈不是低质量输入，而是高价值 posture 信号。

### 4.2 用案例校准抽象偏好

纯规则容易僵硬，纯人格容易漂移。

更稳定的表达由四部分组成：

- 任务合同：目标、成功面、边界、不可接受状态。
- 角色姿态：每个角色该如何权衡证据、速度、风险与质量。
- 流程形状：判断应该在哪个阶段发生。
- 具体判例：哪些结果像用户会放行，哪些结果像用户会卡住。

判例可以来自内置示例、历史 run、用户对 verdict 的修改或用户对结果的模糊评价。

### 4.3 Posture 只能挑战 contract，不能静默改写 contract

posture 可以让系统提出：

- 当前 `Done When` 可能过窄。
- 当前目标可能忽略了更大的风险。
- 当前 workflow 可能把判断放得太晚。

但它不能在 run 内静默改写：

- `Task`
- 冻结 checks
- 明确 Guardrails
- 用户已确认的关键边界

如果 posture 想改变这些内容，必须变成显式的 bundle revision 或待确认偏移。

## 5. Posture 与 Prompt / Workflow 的关系

### 5.1 Prompt 只是注入方式

prompt 不是 posture 本体。

posture 至少会影响：

- workflow 形状
- role prompt 编译
- 证据优先级
- verdict 风格
- 继续推进、暂停、转向的时机
- 系统向用户解释结果的方式

如果 posture 只停留在 prompt 文案，Loopora 就会重新退回手工调 prompt 的工具。

### 5.2 Workflow 不是旧系统残留

workflow 不是和 posture 竞争的旧抽象。

workflow 是 posture 的时间结构：它回答判断发生在什么时候、由谁承担、是否需要先取证、是否允许 Guide 介入、是否需要 repair loop。

因此，workflow 仍然是一等资产，但它不应再被解释为用户手工拼装的起点，而应被解释为 posture 的运行投影。

### 5.3 Role 是 posture 的分面

同一份任务姿态会在不同角色中呈现不同侧面：

- `Inspector` 体现证据洁癖、风险排序、可重复验证偏好。
- `GateKeeper` 体现签字保守度、残余风险容忍度、质量敏感度。
- `Guide` 体现停滞时换方向还是缩小切口。
- `Builder` 体现推进速度、重构深度、最小可用切片的取舍。

因此，系统不能只保存一段总提示词，而必须允许姿态按角色编译。

## 6. Posture 与 Contract 的关系

`contract` 提供稳定性，`posture` 提供任务级判断差异。

稳定性来自：

- `Task` 不在 run 内改写。
- checks 按 run 冻结。
- Guardrails 不被角色绕过。
- 证据必须落地并可复盘。

差异来自：

- 哪些证据优先
- 哪些风险被认为阻塞
- 何时重构比速度重要
- 何时继续推进或暂停

看不见来源的变化是漂移；看得见来源的变化才是 posture。因此，当 posture 影响运行结果时，系统应尽量让用户能追溯：

- 为什么这次更重视重构？
- 为什么这次更保守或更激进？
- 为什么没有直接放行？
- 哪些 bundle / role / workflow 信号影响了本轮 verdict？

## 7. 持续学习

Loopora 不应把 posture 生成当成一次性 onboarding。

真实的姿态常常来自 run 后纠偏：

- 用户看到结果后才知道自己不接受哪类捷径。
- 用户看到残余风险后才知道自己愿意接受哪类解释。
- 用户看到 GateKeeper verdict 后才知道系统太松还是太严。

合理路径是：

`run evidence -> fuzzy feedback -> posture delta -> updated working agreement -> next bundle revision`

这不是“重新生成一套东西”，而是在同一份任务姿态上做可追溯微调。

## 8. 产品判断

如果 Loopora 只强调 workflow 编排，它会是强但偏冷的 expert tool。

如果 Loopora 只强调协作姿态，它会变成不可执行的抽象叙事。

真正的差异化来自两者结合：

- 帮助用户外化当前任务的判断方式。
- 把判断方式编译成可读、可运行、可修订的 bundle。
- 让 `spec / roles / workflow` 承载同一份姿态。
- 用 evidence loop 检验每一轮行动。
- 用用户反馈生成下一版 posture，而不是让用户从零重来。

## 9. 非目标

- 不是把所有用户压成同一种最佳实践。
- 不是建立长期、全局、不可解释的人格模型。
- 不是把人格化退化成更长的 prompt 文案。
- 不是用模糊姿态替代 task contract。
- 不是为了“更像人”而放弃可复盘、可解释、可追溯。
- 不是要求用户第一次使用时就完整认识自己。
