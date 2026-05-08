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
- 持久化 prompt artifact 必须是 UTF-8 Markdown；读盘或编码失败在展示投影中降级为空 prompt 投影，在 run 启动或执行契约中必须失败关闭，不能静默换用 fallback prompt。

## 3. Workflow 结构

workflow 保持两层结构：

- `roles[]`
- `steps[]`

workflow 可携带顶层 `collaboration_intent`，用于表达本任务整体判断方式，例如“先取证再推进”或“尽快收束到签字判断”。

workflow 还可以携带可选 `controls[]`。它是高级误差控制机制，不是通用事件自动化。默认 starter 不要求用户理解 controls；只有当任务存在可解释的长程误差风险时，alignment 或专家编辑才应加入。

workflow `version` 目前只支持整数 `1`。缺失或空值可按当前版本处理；显式 `0`、布尔值、小数、非数字或未来版本必须在保存、预览或导入边界失败关闭，不能被 truthy/default 逻辑吞成当前版本。

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

稳定标识规则：

- workflow `role.id`、`step.id`、`controls[].id` 与 `parallel_group` 必须使用安全稳定标识：字母、数字、点、下划线或短横线，长度 1-80。
- 缺失的 role / step id 仍可由系统生成 `role_001` / `step_001` 这类安全标识。
- 非法标识必须在 workflow 或 bundle 保存 / 预览前失败，不能进入 run artifact 路径或持久化事实源。

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
- command mode 参数模板是每行一个 argv 参数，只能使用 executor 公开声明的运行时占位符；未知 `{name}` 占位符在保存、预览或启动前失败，`{extra_cli_args}` 只能作为独立 argv 插入点。
- `parallel_group` 第一阶段只支持连续的 Inspector / Custom step，用于 fan-out / fan-in 检视；它不是任意 DAG 语法。
- 同一 `parallel_group` 内的 step 看到相同的上游快照，不读取彼此输出；组结束后按 workflow 原顺序汇聚 handoff 和 evidence。
- 复杂任务可以编译成长链 workflow：多个窄 Builder 或多个 Builder step 串联推进不同证据阶段，例如设计收敛、后端实现、前端接线、验证补强。长链不新增运行实体，也不表达嵌套循环；它仍是同一轮内的线性 step 序列，由外层 run iteration 负责自动迭代。
- 长链中的每个 Builder 必须有明确阶段产物、handoff 和下游读取者；若某个 Builder 只重复“继续推进”而没有新的证据责任或交接边界，应合并到相邻 Builder，避免退化成 role zoo 或 loop script。
- 当 Builder 排在另一个 Builder 之后，若中间存在 Inspector、Custom 或 Guide，后一个 Builder 必须显式读取对应 handoff；若两个 Builder 直接相邻，也应通过 task-specific role posture 或 step input 说明阶段边界，避免依赖 ambient context。
- Guide step 是只读的方向转换步骤，不会因当前未停滞而被服务层自动跳过。若 workflow 显式安排 Guide，它必须通过 `inputs.handoffs_from` / `inputs.evidence_query` 读取上游审查、阻断或未证明证据；条件式 Guide 应通过 `controls[]` 表达。
- `inputs.handoffs_from` 可按 step id、role id、runtime role、archetype 或 role name 选择当前轮上游 handoff。
- `inputs.evidence_query` 可按 evidence 生产角色、验证目标和数量上限裁剪 evidence ledger 摘要；显式声明时，下游 prompt 中可引用的 evidence ids 也必须跟随裁剪结果，避免角色绕过 workflow 信息流引用未路由证据。完整 ledger 仍是 canonical source。
- `inputs.iteration_memory` 可选择 `default / none / same_step / same_role / summary_only`，用于控制轮次间信息传递。
- `controls[].when.signal` v1 只允许 `no_evidence_progress / role_timeout / step_failed / gatekeeper_rejected`。
- `no_evidence_progress` 不只表示 composite score 停滞；当多轮后 required `Done When` coverage count 没有增加且仍有缺失 check 时，也应触发同一控制信号，让系统尽早暴露“故事在动但证明没动”。
- control 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper；不能调用 Builder，避免自动修复污染工作区。
- control invocation 是控制检查调用，不插入 canonical workflow 顺序；它只产生 evidence、handoff、blocker 或修复建议。
- `controls[].max_fires_per_run` 必须是 `1..20` 的有界正整数；显式 `0` 不能在 Web 编辑器、bundle projection 或运行装配中被默认值隐藏。
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
| `guide` | 把上游审查、阻断、未证明或停滞证据转成最小修复 / 收窄方向 |
| `custom` | 以最低权限读取现状、补充分析并给出建议 |

系统固定支持四类执行器：

| 执行器 | 模式 | 稳定承诺 |
|--------|------|----------|
| `codex` | `preset` / `command` | 预设模式由系统拼装 CLI；直接命令模式允许覆盖 argv 模版 |
| `claude` | `preset` / `command` | 同上 |
| `opencode` | `preset` / `command` | 同上 |
| `custom` | `command` only | 调用方必须提供可执行文件与 argv 模版，并按输出契约写出结果 |

稳定规则：

- 内置 archetype 的契约值保持英文原文；中文 Web UI 展示为“构建者 / 巡检者 / 守门者 / 引导者 / 自定义角色”。
- 用户自定义 role 名称按用户输入原样展示。
- 已保存 role definition 的 archetype 固定；更新入口不能改变它。
- 预设执行配置中的 `model` 是可选 pin；空值表示使用所选 Agent CLI 的当前默认模型，只有用户、导入资产或 step 覆盖显式填写时才固定模型。
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
- GateKeeper 输出通过时必须引用上游支持性 `evidence_refs`；Inspector / Custom / control 输出可以作为取证或检视支持，Builder handoff 只有在携带 proof artifact 或 measured evidence 时才可以作为支持。普通 Builder 自述、GateKeeper verdict、blocked / failed / rejected 的上游 evidence 不能作为通过依据。如果 GateKeeper 是本轮第一个证据读取者，则必须提供可度量 `metric_scores` 和具体 `evidence_claims`。自然语言 claims 单独不能结束 run。
- GateKeeper 输出契约必须包含 `residual_risks` 数组；无残余风险时返回空数组，有可接受残余风险时逐项命名。通过态的有意义 residual risk 会进入 task verdict 的 `passed_with_residual_risk`，不能只藏在 `decision_summary` 自由文本里。
- GateKeeper 与 Inspector 一样可以通过 `coverage_results` 明确覆盖或拒绝 coverage target；这主要用于 Fake Done 与 Evidence Preferences 这类裁决期风险 / 证据偏好。ledger item 必须保留每条 `coverage_results` 的 `target_id / status / evidence_refs / note`，不能只把 refs 压平成 item 级关系。positive coverage 必须由当前支持性 item、measured evidence，或当前 target 自己的 `coverage_results.evidence_refs` 指向的支持性 evidence 支撑，否则 projection 只能标记为 weak。schema、prompt 与 ledger `verifies` 必须保持一致，不能提示模型输出一个会被 schema 拒绝的字段。
- `custom` role 可以进入编排，但不能成为收敛裁决入口。
- 并行组必须是连续 step，且每组至少 2 个 step。
- 并行组内第一阶段只允许 `inspector` 与 `custom`，不允许 `builder`、`gatekeeper` 或 `guide`，避免并发写入和并发收敛污染 run 状态。
- 并行 review step（Inspector 或 Custom）应表达不同证据责任，例如 contract、evidence、regression、benchmark、posture 或任务专属检视面，而不是只复制多个同名 reviewer。
- Custom 若作为只读专项 review 出现在 Builder、Guide 或 GateKeeper 之前，信息流规则与 Inspector review 相同：下游必须显式读取对应 handoff，并在需要裁决或修复方向时查询 Custom evidence。
- workflow controls 必须服务于误差控制，不能表达任意 cron、webhook、文件监听、外部事件、动态 DAG 或隐式 Builder 修复。
- control signal 必须来自稳定枚举；未知 signal、未知 role、Builder target、无效 mode 或不受限触发配置必须被拒绝。运行期重新装配冻结 workflow 时若发现损坏的 controls 配置，必须失败关闭，而不是按默认值执行。
- action policy 必须与 archetype 和 workflow 语义兼容；并行检视组内不得出现写入工作区或收束 run 的 step。

prompt 资产必须满足：

- 包含结构化元数据头。
- 声明受支持版本。
- 声明与 role 一致的角色原型。
- 正文非空。
- `prompt_ref` 是安全相对引用，不允许绝对路径、空段或 `.` / `..` 段。
- 内置 prompt 必须解释 Inspector 的广义证据生产者语义、Custom 在并行 review 中的只读专门检视语义、并行检视时的分工、GateKeeper 对多证据分支的 fan-in 责任，以及 Builder 在并行检视前应留下可检查 handoff。
- 中英文内置 prompt 必须在核心运行语义上保持一致，尤其是并行 review、GateKeeper fan-in、环境阻断后的 fallback 证据策略、run contract 冻结边界，以及不能用主观信心替代证据的规则。
- 内置 prompt 应引导角色使用稳定证据投影桶：`Proven / Weak / Unproven / Blocking / Residual risk`。这些桶帮助 Builder handoff、Inspector review、Guide repair direction、Custom review 和 GateKeeper verdict 把自然语言观察投影到用户最终能审计的 Loop 裁决面；中文 prompt 使用等价语义即可。
- 内置 prompt 应把项目本地指令、design 文档和 tests 视为存在时的契约与证据输入：Builder 不应绕过它们改动，Inspector / Custom 应把相关 design 或测试契约纳入检视，Guide 的修复方向不应绕过它们，GateKeeper 不应让跳过本地规则或缺失预期验证的 run 仅凭自然语言摘要通过。

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

长链 workflow 的推荐使用边界：

- 适合：任务天然分成多个会产生新 artifact、proof 或 handoff 的阶段，且每个阶段之后的人类判断可以提前外化。
- 不适合：只是为了“更稳”而复制多个 Builder / Inspector，或把一个可由单个 Builder 完成的连续实现拆成无证据边界的角色队列。
- GateKeeper 必须能从最终裁决 step 追溯到关键阶段的 Builder、Inspector、Custom 或 Guide handoff 与 evidence；长链不能让最终裁决只看最后一个 Builder。
- Alignment 和 starter 可以生成 5+ role / step 的长链，但默认新手路径不要求用户手动理解这些字段。

## 8. 运行时装配

运行时 prompt 由稳定协议装配，顺序固定为：

`系统安全约束 -> 输出契约 -> 用户 prompt -> run contract 摘要 -> 当前角色 note -> 当前轮次 / step 说明 -> step input policy -> 被选中的上游 handoff -> 被选中的上一轮信息 -> 被选中的 evidence ledger 摘要 -> artifact refs`

稳定规则：

- 首轮必须显式声明没有上一轮结果。
- 后续轮次必须显式声明轮次编号和上一轮关键结果。
- 后续轮次必须显式继承 evidence progress 状态：当 required coverage 没有新增证明且仍有缺口时，当前 step prompt 与上一轮 summary 都应暴露 `evidence_progress_mode`、covered / missing check count 和连续无覆盖增量，避免模型只看到分数变化而看不到“故事在动但证明没动”。
- 系统安全边界、输出契约和 context packet shape 不能被自定义 prompt 绕开。
- evidence ledger 摘要只传递近期 item、已知 evidence id 列表、ledger 路径和当前 step 可引用 claims 的 manifest proof-strength 摘要，避免把证据账本或 manifest 全文复制进每个 prompt。服务层校验 GateKeeper `evidence_refs` 时必须回到 canonical ledger 补全已允许 id 的完整 evidence item；不能因为 prompt 摘要裁剪掉旧 item 就把仍在信息流权限内的 evidence ref 误判为未知或非支持。
- `inputs.evidence_query` 裁剪 evidence 时，prompt 中的 known ids、manifest claim rows 与 proof-strength summary 都必须跟随同一可引用集合；proof-strength 不得泄露裁剪外证据，也不得让 UI 事后投影成为 GateKeeper 决策时看不到的事实。
- `inputs` 只能裁剪当前 prompt 的可见上下文，不能改变 run 的 canonical evidence ledger、step output、handoff 或 iteration summary。
- Guide 的运行时 prompt 与输出契约必须把 Blocking、Unproven 或停滞信号转成最小修复 / 收窄方向；Weak 证据只有在会改变裁决时才优先补强，Residual risk 必须保持可见。
- control prompt 必须显式说明触发信号、原因、读取的 evidence refs 和模式；它产生的 ledger item 使用 `evidence_kind=control`。
- `Role Notes` / `posture_notes` / `collaboration_intent` 可以影响角色工作姿态，但不能改写 `Task / Done When / Guardrails`。
- 所有运行期 archetype 的 system prompt 前缀都必须提醒角色：run contract 已冻结；若发现 `Task / Done When / Guardrails` 过窄、过松或冲突，应作为 evidence gap / blocker / Loop 调整建议暴露，而不能在 run 内静默降级或改写。
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
Builder 输出契约必须允许并要求空数组形式的 `proof_files`、`proof_artifacts` 与 `artifact_paths`，让实际 proof artifact 能稳定进入 evidence ledger / manifest，而不是依赖未声明的额外字段。
运行期角色 prompt 与结构化输出 schema 必须枚举相同的顶层必填字段；数组型证据、反馈或度量字段即使为空也应明确返回空数组，避免真实执行器按 prompt 省略 schema 所需字段。

信息流分两层：

- **角色间信息流**：由当前轮已完成 step 的 `StepHandoff` 与 `inputs.handoffs_from` 决定。
- **轮次间信息流**：由上一轮同 step / 同 role / iteration summary 与 `inputs.iteration_memory` 决定。

这两层只影响 prompt 可见范围，不改变底层 artifact 留存。这样可以让 10+ 角色的复杂 workflow 保持可检查，而不是把全部上下文无差别塞给每个角色。

## 10. 跨入口一致性

workflow 与 prompt 资产必须：

- 可通过 Web 编辑与复用。
- 可通过 CLI 或 API 引用、提交或校验；CLI 对 `parallel_group` 与 `inputs` 的专家入口是 `--workflow-file`，默认不提供大量逐字段 flags。
- `--workflow-file` 只接受 UTF-8 JSON / YAML；编码或解析失败属于 workflow 输入错误，必须进入统一错误语义。
- prompt 文件入口只接受 UTF-8 Markdown；front matter 与编码错误都属于 workflow / prompt 输入错误。
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
