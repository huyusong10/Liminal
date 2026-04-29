# Workflow And Prompts

> 最高原则：遵循 `../core-ideas/product-principle.md`。workflow 与 prompt 只是外部任务治理的运行投影；它们必须服务于证据循环，不能变成独立的 role zoo 或 prompt pack。

## 1. 模块职责

本文档定义两类稳定资产：

- `workflow`
- `prompt`

它回答的是“编排资产对外承诺什么”，而不是具体页面如何展示它们。

## 2. 资产契约

专家模式的三阶分层不是“任务文档 / 角色列表 / 流程图”，而是三种治理能力：

| 层 | 核心问题 | 稳定能力 |
|----|----------|----------|
| `spec` | 什么算对，什么不能放过？ | 定义判断对象：任务契约、成功面、假完成、证据偏好和残余风险 |
| `roles` | 谁以什么判断姿态看问题？ | 定义判断主体：构建、检查、裁决、纠偏的责任与 posture |
| `workflow` | 这些判断何时发生、如何影响推进？ | 定义判断机制：顺序、信息流、行动权限、迭代、阻断和收束 |

`spec` 写“什么必须被证明”；`roles` 写“这个角色如何判断和寻找证明”；`workflow` 写“什么时候让它判断，以及判断结果如何改变流程”。

| 资产 | 输入 | 输出 | 稳定承诺 |
|------|------|------|----------|
| orchestration asset | 名称、描述、workflow、prompt 资产 | 可复用编排定义 | 可被 loop 引用，也可复制为新编排 |
| role definition asset | 名称、角色模板、默认执行配置、prompt 资产 | 可复用角色模版 | 被 orchestration 选入后复制成角色快照；本次行动权限由 workflow step 冻结 |
| workflow snapshot | roles 与 steps | 运行期角色顺序与依赖关系 | run 开始后不随外部编辑漂移 |
| prompt asset | 元数据头 + Markdown 正文 | 角色运行提示 | 声明版本与适用角色模板 |

稳定规则：

- 内置 prompt 可提供多语言变体，只要 front matter 版本与 archetype 契约保持一致。
- orchestration 保存或更新时，只保留当前 workflow 实际引用的 prompt 资产。
- 运行期只消费冻结后的 workflow snapshot 和 prompt snapshot。

## 3. Workflow 结构

workflow 保持两层结构：

- `roles[]`
- `steps[]`

workflow 可携带顶层 `collaboration_intent`，用于表达本任务整体判断方式，例如“先取证再推进”或“尽快收束到签字判断”。

workflow 还可以携带可选 `controls[]`。它是高级误差控制机制，不是通用事件自动化。默认 starter 不要求用户理解 controls；只有当任务存在可解释的长程误差风险时，alignment 或专家编辑才应加入。

每个 role 至少表达：

| 字段 | 含义 |
|------|------|
| `id` | 当前 workflow 内稳定标识 |
| `name` | 用户可读名称 |
| `archetype` | 角色模板 |
| `prompt_ref` | 使用的 prompt 资产内部引用 |
| `executor_kind` / `executor_mode` | 默认执行方式 |
| `model` / `reasoning_effort` | 可选默认执行配置 |
| `posture_notes` | 可选，本任务里的角色判断姿态 |
| `role_definition_id` | 可选，来源 role definition |

role 不表达本次 step 的写入、只读、收束或控制权限。权限随 workflow step 冻结，使同一 role 可以在不同步骤里承担不同行动边界，并让用户从流程图审计“哪一步会动手、哪一步只判断”。

每个 step 至少表达：

| 字段 | 含义 |
|------|------|
| `id` | 当前 workflow 内稳定标识 |
| `role_id` | 指向某个 role |
| `on_pass` | 可选，仅 GateKeeper 用于声明收敛行为 |
| `model` | 可选 step 级模型覆盖 |
| `inherit_session` | 可选，当前 step 跨轮次续接自己的 CLI session |
| `extra_cli_args` | 可选，当前 step CLI 调用的附加参数 |
| `parallel_group` | 可选，把连续的只读检视 step 标记为同一并行组 |
| `inputs` | 可选，声明当前 step 读取哪些 handoff、evidence 与上轮记忆 |
| `action_policy` | 可选，声明当前 step 的行动权限，例如写入工作区、只读取证、可产生阻断或可收束 |

每个 control 至少表达：

| 字段 | 含义 |
|------|------|
| `id` | 当前 workflow 内稳定标识 |
| `when.signal` | 受控触发信号 |
| `when.after` | run 内 elapsed time 门槛，不是 calendar cron |
| `call.role_id` | 要调用的既有 Inspector / Guide / GateKeeper role |
| `mode` | `advisory / blocking / repair_guidance` |
| `max_fires_per_run` | 单次 run 内最多触发次数，默认 `1` |

稳定规则：

- `inherit_session` 按“同一个 step 跨轮次续接自己的会话”解释，不按“当前目录最近一次会话”解释。
- Builder step 默认继承 session；Inspector、GateKeeper、Guide 与 Custom step 默认不继承，除非显式打开。
- `posture_notes` 是 task-scoped 治理注入位，不是 archetype 本身，也不是全局 task contract 的替代品。
- posture 可以承载用户难以完全规则化的隐性判断；Inspector 可以按 posture 做语义检视，只要输出能落到 evidence、handoff、blocker 或 residual risk。
- `action_policy` 归属于 step。Builder archetype 通常获得写入权限，Inspector / GateKeeper / Guide / Custom 通常只读或只产出判断；例外必须在 workflow 中显式表达。
- `extra_cli_args` 必须是可被 shell 风格分词解析的字符串。
- `parallel_group` 第一阶段只支持连续的 Inspector / Custom step，用于 fan-out / fan-in 检视；它不是任意 DAG 语法。
- 同一 `parallel_group` 内的 step 看到相同的上游快照，不读取彼此输出；组结束后按 workflow 原顺序汇聚 handoff 和 evidence。
- `inputs.handoffs_from` 可按 step id、role id、runtime role、archetype 或 role name 选择当前轮上游 handoff。
- `inputs.evidence_query` 可按 evidence 生产角色、验证目标和数量上限裁剪 evidence ledger 摘要；完整 ledger 仍是 canonical source。
- `inputs.iteration_memory` 可选择 `default / none / same_step / same_role / summary_only`，用于控制轮次间信息传递。
- `controls[].when.signal` v1 只允许 `no_evidence_progress / role_timeout / step_failed / gatekeeper_rejected`。
- control 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper；不能调用 Builder，避免自动修复污染工作区。
- control invocation 是控制检查调用，不插入 canonical workflow 顺序；它只产生 evidence、handoff、blocker 或修复建议。
- control 自身失败必须写入 run event stream，不能静默吞掉。

## 4. 内置 starter orchestration

系统默认提供以下 starter：

| 预设 | 稳定流程 |
|------|----------|
| `build_then_parallel_review` | `Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper` |
| `evidence_first` | `Inspector -> Builder -> GateKeeper` |
| `benchmark_gate` | `Benchmark Inspector -> Builder -> Regression Inspector -> GateKeeper` |
| `repair_loop` | `Builder -> [Regression Inspector + Contract Inspector] -> Guide -> Builder -> GateKeeper` |

稳定规则：

- starter 是内置资产，只能复制后形成自定义编排。
- `build_first`、`inspect_first`、`triage_first`、`benchmark_loop`、`quality_gate` 与 `fast_lane` 可作为兼容旧数据的内置 preset 保留，但不再属于默认推荐目录。
- starter 场景说明必须描述值得进入 loop 的任务，解释为什么当前角色顺序有意义。
- 默认 starter 总数必须保持少而强；新增 starter 前应先判断能否通过上述四类治理形状表达，避免把用户入口扩张成 role zoo。

## 5. 角色原型与执行器

系统固定支持五种角色模板：

| 模板 | 职责 |
|------|------|
| `builder` | 改动工作区并推进实现 |
| `inspector` | 广义证据生产者：可执行规则检查，也可按用户 posture 做语义检视；具体实例应按证据责任或判断姿态命名 |
| `gatekeeper` | 根据 evidence ledger 给出通过裁决 |
| `guide` | 在停滞或回退时给出方向调整 |
| `custom` | 以最低权限读取现状、补充分析并给出建议 |

系统固定支持四类执行器：

| 执行器 | 模式 | 稳定承诺 |
|--------|------|----------|
| `codex` | `preset` / `command` | 预设模式由系统拼装 CLI；直接命令模式允许覆盖 argv 模版 |
| `claude` | `preset` / `command` | 同上 |
| `opencode` | `preset` / `command` | 同上 |
| `custom` | `command` only | 调用方必须提供可执行文件与 argv 模版，并按输出契约写出结果 |

稳定规则：

- 内置 archetype 的展示名在所有 locale 下保持英文原文：`Builder`、`Inspector`、`GateKeeper`、`Guide`、`Custom Role`。
- 用户自定义 role 名称按用户输入原样展示。
- 已保存 role definition 的 archetype 固定；更新入口不能改变它。
- `custom` 执行器保存前必须处于 `command` 模式。

## 6. 验证规则

workflow 保存前必须满足：

- 至少 1 个 role。
- 至少 1 个 step。
- 每个 step 引用的 `role_id` 都存在。
- `gatekeeper` completion mode 必须存在可在通过时结束流程的 GateKeeper step。
- `rounds` completion mode 允许没有 GateKeeper。
- 只有 GateKeeper step 可以声明 `on_pass=finish_run`。
- evidence ledger item 必须标记证据类型，例如 `handoff`、`inspection`、`verdict`、`advisory` 或 `observation`。
- GateKeeper 输出通过时必须引用上游 `evidence_refs`；如果 GateKeeper 是本轮第一个证据读取者，则必须提供可度量 `metric_scores` 和具体 `evidence_claims`。自然语言 claims 单独不能结束 run。
- `custom` role 可以进入编排，但不能成为收敛裁决入口。
- 并行组必须是连续 step，且每组至少 2 个 step。
- 并行组内第一阶段只允许 `inspector` 与 `custom`，不允许 `builder`、`gatekeeper` 或 `guide`，避免并发写入和并发收敛污染 run 状态。
- 并行 Inspector 应表达不同证据责任，例如 contract、evidence、regression、benchmark 或 posture，而不是只复制多个同名 Inspector。
- workflow controls 必须服务于误差控制，不能表达任意 cron、webhook、文件监听、外部事件、动态 DAG 或隐式 Builder 修复。
- control signal 必须来自稳定枚举；未知 signal、未知 role、Builder target、无效 mode 或不受限触发配置必须被拒绝。
- action policy 必须与 archetype 和 workflow 语义兼容；并行检视组内不得出现写入工作区或收束 run 的 step。

prompt 资产必须满足：

- 包含结构化元数据头。
- 声明受支持版本。
- 声明与 role 一致的角色原型。
- 正文非空。
- `prompt_ref` 是安全相对引用，不允许绝对路径、空段或 `.` / `..` 段。
- 内置 prompt 必须解释 Inspector 的广义证据生产者语义、并行检视时的分工、GateKeeper 对多证据分支的 fan-in 责任，以及 Builder 在并行检视前应留下可检查 handoff。

## 7. 模型与 step 覆盖优先级

模型选择优先级固定为：

`step.model -> role.model -> role 默认执行配置`

step 级执行附加项只影响当前 step：

| 字段 | 稳定承诺 |
|------|----------|
| `inherit_session` | 只控制当前 step 的 CLI session 恢复策略 |
| `extra_cli_args` | 只附加到当前 step 的 CLI 调用 |
| `parallel_group` | 只控制当前连续组的并行 fan-out；不授予额外行动权限 |
| `inputs` | 只裁剪当前 step 的上下文输入；不删除 canonical artifact |
| `controls` | 只在运行时误差风险出现时触发额外检查；不改变 canonical workflow 顺序 |
| `action_policy` | 只控制当前 step 的行动权限；不改变 role definition 或全局 task contract |

预设执行器可以把 `inherit_session` 映射到各自原生恢复语义；直接命令模式不承诺能自动恢复任意第三方命令的上下文。

## 8. 运行时装配

运行时 prompt 由稳定协议装配，顺序固定为：

`系统安全约束 -> 输出契约 -> 用户 prompt -> run contract 摘要 -> 当前角色 note -> 当前轮次 / step 说明 -> step input policy -> 被选中的上游 handoff -> 被选中的上一轮信息 -> 被选中的 evidence ledger 摘要 -> artifact refs`

稳定规则：

- 首轮必须显式声明没有上一轮结果。
- 后续轮次必须显式声明轮次编号和上一轮关键结果。
- 系统安全边界、输出契约和 context packet shape 不能被自定义 prompt 绕开。
- evidence ledger 摘要只传递近期 item、已知 evidence id 列表和 ledger 路径，避免把证据账本全文复制进每个 prompt。
- `inputs` 只能裁剪当前 prompt 的可见上下文，不能改变 run 的 canonical evidence ledger、step output、handoff 或 iteration summary。
- control prompt 必须显式说明触发信号、原因、读取的 evidence refs 和模式；它产生的 ledger item 使用 `evidence_kind=control`。
- `Role Notes` / `posture_notes` / `collaboration_intent` 可以影响角色工作姿态，但不能改写 `Task / Done When / Guardrails`。
- step `action_policy` 可以收窄或授予当前调用的行动边界，但不能让角色越过系统安全约束、workspace guard 或 completion mode 语义。
- 当环境阻断浏览器、截图或桌面控制能力时，prompt 应引导角色切换到可重复 fallback 证据，并把环境限制写入 handoff。

## 9. Context Protocol

运行时使用以下内部稳定对象：

| 对象 | 作用 | 稳定承诺 |
|------|------|----------|
| `RunContractSnapshot` | 冻结 spec、workflow、prompt refs、runtime 配置 | run 生命周期内不漂移 |
| `StepContextPacket` | step 开始前装配当前轮次、步骤、上游 handoff 与 artifact refs | shape 由代码固定生成 |
| `StepHandoff` | step 结束后给下游角色消费的结构化交接包 | 至少稳定包含 `status / summary / blocking_items / recommended_next_action` |
| `IterationSummary` | 汇总本轮 handoff、得分、停滞状态与 latest refs | 作为下一轮统一回看入口 |

`artifact_refs` 必须同时提供 run 内相对路径与 workspace 可直达路径，保证角色能定位 `.loopora/runs/...` 下的冻结产物。

信息流分两层：

- **角色间信息流**：由当前轮已完成 step 的 `StepHandoff` 与 `inputs.handoffs_from` 决定。
- **轮次间信息流**：由上一轮同 step / 同 role / iteration summary 与 `inputs.iteration_memory` 决定。

这两层只影响 prompt 可见范围，不改变底层 artifact 留存。这样可以让 10+ 角色的复杂 workflow 保持可检查，而不是把全部上下文无差别塞给每个角色。

## 10. 跨入口一致性

workflow 与 prompt 资产必须：

- 可通过 Web 编辑与复用。
- 可通过 CLI 或 API 引用、提交或校验；CLI 对 `parallel_group` 与 `inputs` 的专家入口是 `--workflow-file`，默认不提供大量逐字段 flags。
- 保持 role definition 先独立存在，再被 orchestration 选入的边界。
- 保持 step 级模型覆盖、session 继承与附加 CLI 参数的跨入口表达能力。
- 保持 orchestration 不直接维护角色默认 prompt 与执行配置。

## 11. 变更触发

以下变化需要更新本文档：

- workflow 结构变化。
- completion mode 语义变化。
- prompt 资产契约变化。
- 角色原型种类或职责变化。
- 角色执行配置的归属边界变化。

以下变化通常不需要更新本文档：

- prompt 具体文案调整。
- 局部 UI 呈现调整。
- 兼容层实现细节变化。

## 12. 非目标

- 不支持任意 DAG。
- 不支持会并发写入工作区或并发收敛的 step。
- 不支持跳过角色原型校验提交任意 prompt。
- 不支持用户自定义任意输出协议。
