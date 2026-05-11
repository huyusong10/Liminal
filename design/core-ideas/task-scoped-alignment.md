# Task-Scoped Alignment

> 最高原则：遵循 `product-principle.md`。Alignment 是取得或调整 Loop 的一种场景，不是 Loopora 主工作流本身。它的目标不是尽快产出 YAML，而是把当前长期任务的判断方式编译成可运行、可观察、可裁决的 Loop。

## 1. 目标

本文档定义 Web 问答如何帮助用户编排 Loop。它不是普通需求澄清器，而是帮助用户把隐性判断力显影并编译成 human-shaped Loop 的前端。

一句话：

> Alignment is a compiler front-end for composing a Loop from task-specific judgment.

Alignment 的核心动作是一次沟通的时空转换：把未来执行过程中人类可能反复做的纠偏、验收、阻断和证据追问，提前到 run 之前表达出来。

它服务于主工作流中的第一步：

`编排 Loop`

它不拥有后续主工作流：

`运行 Loop -> 自动迭代并收集证据 -> 输出证据裁决与结果`

## 2. 对齐对象

Alignment 对齐的不是抽象人格，也不是通用最佳实践，而是当前任务的编排判断：

- 这件事是否真的需要 Loopora，而不是一次 Agent 执行加一次人工 review、直接聊天或 benchmark-first 简单循环？
- 后续轮次是否会产生新的 proof、artifact、handoff、观察或裁决上下文？
- 这套判断是否应该活过一次聊天，被 run 继承、导出复用或作为证据审计对象？
- 什么算真实进展？
- 什么是假完成？
- 用户信任哪些证据？
- 哪些残余风险可以接受，哪些必须阻断？
- 谁负责构建，谁负责取证，谁负责裁决？
- workflow 应如何推进、并行检视、纠偏或停止？

这些问题必须先形成 working agreement，再编译成候选 Loop。

这些判断不要求用户一开始就能完全外化成规则。Alignment 的价值之一，是通过案例、对比、失败模式和 tradeoff 问题，把用户隐性的判断姿态转成 `spec / roles / workflow` 可以承载的运行结构；其中 Inspector 可以是 posture-driven 的语义检视者，而不只是执行固定规则的检查器。

编译时必须能回答一张稳定投影表：未来人类会要求证明什么，落到 `spec`；未来人类会要求谁捕捉偏差，落到 `role_definitions`；未来人类会要求何时纠偏、修复或停止，落到 `workflow`；未来人类会要求哪些证明可复盘，落到 handoff、evidence query 和 GateKeeper verdict。若 `collaboration_summary` 无法讲清这个投影，bundle 仍只是配置草稿，不是 human-shaped Loop。

Alignment 在交付 working agreement 或 bundle 前，还应能私下完成一张 agreement-to-bundle traceability checklist：每个已确认的判断项都必须至少落到一个可运行或治理可读 surface，例如 `collaboration_summary`、`spec.markdown`、role prompt / posture、`workflow.collaboration_intent`、step `inputs`、workflow controls 或 GateKeeper evidence 规则。只停留在 `agreement_summary`、readiness evidence、聊天记录、metadata / loop 名称或隐性推理里的判断，不算已经编译进 Loop。

如果目标 workdir 暴露项目本地治理入口，例如 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/`，Alignment 不应发明其内容，但应把这些入口视为可能影响运行责任的证据和契约来源。相关任务中，Builder、Inspector / Custom、Guide 和 GateKeeper 的姿态应说明如何读取、验证或裁决这些本地规则，而不是让 run 只凭自然语言摘要绕过项目自己的约束。

`role_definitions` 不能只写通用协作态度。每个 role 的 prompt / posture 必须承载与 archetype 对应的任务责任：Builder 负责构建或修改，Inspector 负责审查、验证或识别假完成，Guide 负责把证据转成收窄、纠偏或修复方向，GateKeeper 负责最终裁决、阻断或收束。否则角色只是名称不同，判断责任没有真正进入 Loop。

Alignment 的 workflow 判断还必须保护 Loopora 的自治公式：判断结构质量 × 证据反馈质量 × 误差暴露速度。只说 “Builder -> Inspector -> GateKeeper” 不够；必须说明证据薄弱、标准漂移或假完成会在哪里尽早暴露。

后端正则和 linter 是护栏，不是方向盘。它们应保护粗颗粒契约：必要 section、stage gate、raw YAML、metadata、GateKeeper 收束、handoff / evidence query 连通性、语言面、workdir fact grounding，以及明确反模式。它们不应把强模型的自然表达压成固定词表；任务判断、取舍、角色姿态和风险说明的文案质量应主要通过 prompt、可见 working agreement、用户确认和 GateKeeper 证据裁决来治理。

稳定规则：

- 如果 Loopora fit 不清楚，Alignment 必须先过负向门槛：一次 Agent + review 是否足够、下一轮是否有新证据、是否已有稳定 benchmark 能表达判断；不能为了产出 bundle 而把不需要 Loopora 的任务包装成 Loop。
- readiness evidence 不需要用固定句式证明 Loopora fit，但若它显式承认一次 Agent + review 已足够、后续不会产生新证据、已有 benchmark 已完整表达判断，或判断不需要活过本次聊天，后端必须把这视为 fit 矛盾并继续对话，而不是接受 `loop_fit=true`。
- 不问抽象人格问题，也不把用户推到空白页上自想答案。默认 clarifying turn 必须先给出任务语境里的候选判断与推荐答案，再让用户在少量选项中接受、改选或纠正；两个都不完美的结果里，系统应先说明推荐拒绝哪一个以及为什么。
- 不把对齐变成长问卷。默认每轮只问一个最会改变 Loop 形状的问题；弱模型一次抛出多项问卷时，服务层应改写为单个任务风险问题。
- 对齐问题应沿当前决策分支推进，而不是重启固定 checklist。每轮应先解析 transcript、working agreement、已有 bundle / source context 和 Workdir Snapshot；能从这些事实回答的问题不再问用户，只把仍需人类判断、且会改变 Loopora fit、`spec`、角色姿态、workflow 信息流、controls 或 GateKeeper 严格度的问题交还用户。
- 用户接受或纠正推荐选项后，Alignment 应沿该分支继续追问下一个依赖决策；除非出现新的事实冲突、校验诊断或用户主动改口，不应反复打开已解决分支。
- 不把 Loopora 配置术语当作新手问题。默认 Web alignment 必须用任务风险语言提问，而不是让用户决定是否配置 `Builder`、`Inspector`、`GateKeeper`、`parallel_group`、`workflow.controls` 或 YAML 字段；弱模型给出这类机械问题时，服务层应改写成风险取舍问题。
- Web alignment 的结构化输出可携带 `decision_options`。它不是新的运行期资产，只是对话期交互投影：每个 option 表达一个用户可选回答、一个是否推荐的标记和点击后要追加到 transcript 的用户回复。选项帮助用户校正候选判断，不替代 working agreement、bundle 或运行期 evidence。
- 不把“用户确认了”当作充分条件；确认必须足以说明成功面、假完成、证据偏好、角色姿态和 workflow 形状。
- 不把未解决问题藏进 ready agreement。`open_questions` 只能为空、无遗留问题或仅等待确认；仍会改变成功面、证据、残余风险、角色或 workflow 的问题必须继续提问。
- 在交付 working agreement 或 bundle 前，Alignment 应私下彩排一条完整运行路径：Builder 产出和 handoff、Inspector / Custom 取证、可选 Guide 修复方向、第二轮 Builder、GateKeeper 裁决和用户证据审计，都必须能通过显式 handoff、evidence query、角色姿态和证据桶串起来；若某一环只靠聊天上下文或角色名成立，继续追问或调整候选 Loop。
- 在交付 working agreement 或 bundle 前，Alignment 应用一个可能的失败轮次私下压测候选 Loop：看似完成但证据弱、覆盖缺失、标准漂移或残余风险不可接受的结果，必须能被 `spec / roles / workflow / evidence` 暴露、修复或阻断；否则继续追问或调整候选 Loop。
- 不把复杂判断强行压成单一分数；能 benchmark 化的判断交给 benchmark，不能可靠 benchmark 化的判断要结构化成角色责任、证据路径和 GateKeeper 阻断条件。
- 不让 evidence-first 或 benchmark-first 变成名义顺序。若 Builder 排在 Inspector / Custom / benchmark review 之后，且没有 Guide 先把 review 压缩成修复方向，Builder 必须显式读取 review handoff。
- 不让 Guide 变成环境上下文里的泛泛建议者。若 Guide 在 Inspector / Custom review 之后运行，它必须显式读取 review handoff 并查询 review evidence；若后续 Builder 执行修复，它必须显式读取 Guide handoff。
- 不让最终 GateKeeper 跳过已经发生的审查。若 GateKeeper 前存在 Inspector、Custom 或 Guide 的审查 / 纠偏 handoff，最终裁决必须显式读取这些 handoff，并查询对应审查证据；否则只是重新相信 Builder 或环境上下文。
- 不把复杂任务默认升级成嵌套 Loop 或任意分支。若任务由多个会产生新证据的阶段组成，优先编译成长链 workflow：多个窄 Builder / Inspector / Guide step 串联，每个阶段有明确 handoff、证据责任和 GateKeeper fan-in；若新增角色不能说明新的判断或证据边界，应合并而不是扩张。
- Web alignment 以后台 Agent 作为语义对话主导者，但 Loopora 后端只承认符合阶段门槛的候选结果：Agent 可以提出 clarifying / agreement / bundle / blocked 候选，后端负责判断是否接受、回退或要求继续对齐。
- 主动注入与被动检测必须配合：提示词负责让 Agent 理解当前 compiler gate 和下一步约束，后端检测负责拒绝阶段跳过、空泛 agreement、未投影判断、断链 workflow 或未通过校验的 bundle。
- Alignment 只生成候选 Loop；判断结构进入 run 后，仍必须由 runtime evidence 检验。

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

Web alignment Agent 负责：

- 与用户沟通
- 暴露关键 tradeoff
- 收敛 task-scoped judgment
- 产出 working agreement
- 编译 YAML bundle

Web alignment Agent 来自 Loopora 内置 session。用户仍可手动导入 YAML，但外部 Agent Skill 不再是一等 bundle 编译入口；否则判断外化会漂移到 Loopora 无法掌控的上下文里。Loopora 本体不决定用户应该如何演进 Loop；它只负责提供取得 / 调整 Loop 的入口、导入导出、运行和证据记录。

## 7. 调整已有 Loop

用户可以拿着 bundle、run evidence 和自己的判断，通过 Web 对话改进入口、YAML 导入或手工编辑器生成新候选 bundle。这是用户主动编排行为，不是 Loopora 的运行职责，也不是系统持有的 Loop 演化历史。

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
