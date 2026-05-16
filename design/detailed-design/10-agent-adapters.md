# Agent Adapters

> 最高原则：遵循 `../core-ideas/product-principle.md` 与 `../core-ideas/agent-first-loopora.md`。Coding Agent 是用户主入口和执行主体；Loopora 只持有 Loop、bundle、run、上下文胶囊、证据与裁决事实源。

## 1. 模块职责

Agent adapter 层存在的唯一理由：

- 把宿主 Coding Agent 的项目级入口接到 Loopora CLI/Core。
- 让 `/loopora-gen` 与 `/loopora-loop` 进入同一套 bundle、READY、run 与 Web 观察语义。
- 管理宿主项目文件的安装、升级、状态检测和卸载 ownership。

它不负责：

- 替代 Coding Agent 的普通对话或工具执行。
- 复制 bundle 校验、导入、run 启动或 Web 服务语义。
- 把 Codex `/goal`、Claude Code plan mode、Trellis task / PRD / workflow 心智写成 Loopora 契约。
- 为尚未实现的平台伪造可运行能力。

## 2. 第一阶段范围

| 平台 | 状态 | 稳定承诺 |
| --- | --- | --- |
| Codex | 已实现 | 安装项目级 Codex skill 入口和 Loopora role custom agents；`/loopora-gen` 校验并返回 READY Loop 预览，`/loopora-loop` 创建或复用 agent-native run，并让 Codex 用原生 subagent / thread 机制推进 step |
| Claude Code | 已实现 | 安装项目级 Claude Code command / skill 入口和 Loopora subagents；`/loopora-gen` 校验并返回 READY Loop 预览，`/loopora-loop` 创建或复用 agent-native run，并让 Claude Code 用原生 Agent / subagent 机制推进 step |
| OpenCode | 已实现 | 安装项目级 OpenCode command 入口和 Loopora subagents；`/loopora-gen` 校验并返回 READY Loop 预览，`/loopora-loop` 创建或复用 agent-native run，并让 OpenCode 用原生 Task / subagent 机制推进 step |

Codex 选择项目级 skill 文件承载用户入口，并安装符合 Codex custom agent schema 的 `.codex/agents/*.toml` 承载 Loopora role posture；custom agent 文件必须使用宿主原生字段表达 agent name、description 与 developer instructions。Codex app / CLI 中 enabled skills 可进入 slash 列表；若宿主只支持 skill invocation，`/loopora-gen` 与 `/loopora-loop` 的用户语义由同名 skill 触发承载。

Claude Code 同时安装项目级 command、skill、subagent 与受管 SessionStart hook：`.claude/commands/*` 提供稳定 slash 入口，`.claude/skills/*` 提供可复用工作流说明，`.claude/agents/*` 用原生 frontmatter 表达 role-specific subagents 的工具面，`.claude/hooks/*` 与 `.claude/settings.json` 中的 Loopora-managed hook handler 用于把宿主 session id 注入后续 CLI entry。Claude Code 的 MCP prompt 和 agent teams 是后续增强点，不能替代当前 command / subagent / CLI 第一路径。

OpenCode 选择官方项目级 custom command 路径：`.opencode/commands/<command>.md`，并安装 `.opencode/agents/*` subagents。`/loopora-loop` command 应使用 OpenCode 原生 `agent` / `subtask` 字段把入口交给 Loopora orchestrator subagent；role agent 文件应使用 `mode: subagent` 与 `permission.task` 表达调用边界，而不是只靠自然语言约束。OpenCode 的 server command/message API 可用于 real probe 仿真，但其业务语义必须与 TUI command 入口一致。

## 3. Entry 语义

### 3.1 `/loopora-gen`

用户语义：

> 把当前 coding 任务、上下文和用户判断编译成候选 Loop。

当前 Agent entry 路径：

1. 宿主 skill / command 读取当前会话中已经可见的任务目标、约束、风险和本地治理入口。
2. 宿主 Agent 生成候选方案文件（内部仍使用 bundle 结构）。
3. Skill 调用 Loopora CLI adapter entry，把候选方案文件交给 Core。
4. Core 创建或更新一个 READY alignment session，运行 bundle 结构校验、spec 编译、alignment 语义 linter 与 READY 投影。
5. CLI 确保本地 Web 服务可用，并返回 Loop 预览 URL。

稳定规则：

- `/loopora-gen` 不启动 run。
- READY 的事实源是 Loopora Core 校验后的 alignment session 和 `artifacts/bundle.yml`，不是 Codex 的自然语言说明。
- Coding Agent 可以生成候选方案文件，但不能自己宣布 READY；READY 只由 Core 校验产生。
- Managed Agent 入口在编写候选方案文件前必须先做 Loopora fit 与 judgment sufficiency 检查：必须能说明为什么一次 Agent 执行、一次 review、直接聊天 / 直接回答、一次性任务无需 Loop 或 benchmark/test-harness-only 验证不足，以及后续轮次会产生哪些新证据、handoff 或 GateKeeper 裁决；成功面、假完成、证据偏好、执行策略、判断取舍、残余风险和本地治理责任若仍缺少会改变 Loop 形状的人类判断，应先追问一个聚焦问题，或退到无 `--bundle-file` 的 Web review 预填入口；若 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/` 等本地治理入口相关，受管入口必须提示宿主 Agent 把它们转成 Builder 读取、Inspector / Custom 验证和 GateKeeper 弱证据 / 未证明 / 阻断责任，而不是只列 marker；不得用通用最佳实践发明用户判断或为了生成候选而合成 Loopora fit。
- Agent-first 候选不能只把当前任务写进 CLI `--message` 或候选文件名；Core 会用宿主任务摘要做轻量 traceability 检查，要求高信号任务对象、风险或证据词投影到候选 bundle 的可运行 surface。
- 若宿主任务摘要明确承认一次 Agent + review、直接聊天 / 直接回答、一次性任务、无后续新证据、稳定 benchmark 或“不需要 Loopora”已经足够，Core 不得接受候选方案文件为 READY；这类输入必须回到提问、解释 not-fit，或 Web review，而不是被包装成可运行 Loop。
- 若宿主任务摘要显式提到，或目标 workdir 的 Workdir Snapshot 暴露 `AGENTS.md`、适用于所选子目录的父级 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/` 这类本地治理入口，Core 不能只接受 bundle 对 marker 的复述；候选必须把它们转成 Builder 读取、Inspector / Custom 验证和 GateKeeper 弱证据 / 未证明 / 阻断责任。
- 若宿主任务摘要显式表达判断取舍，例如证明优先于速度、先阻断假完成再打磨界面，Core 应要求候选 bundle 在 `spec`、角色 posture、`workflow` 或 GateKeeper 严格度中保留该取舍；只保留通用证据 / 风险词不算投影完成。
- 若宿主任务摘要显式表达执行策略，例如先修根因、先补证据、先收窄范围、再扩功能或暂缓 UI 打磨，Core 应要求候选 bundle 在 `spec`、角色 posture、`workflow` 或 step `inputs` 中保留这些优先级；只保留任务对象不算投影完成。
- 若宿主任务摘要显式表达残余风险策略，Core 应要求候选 bundle 保留相同管理语义：哪些风险可接受、由 owner / follow-up / acceptance path 接手，或哪些风险必须失败关闭；`manual` / `visible` 这类描述词不能单独证明风险已经被接管。
- 若宿主任务摘要显式表达成功标准，Core 应要求候选 bundle 保留相同 outcome 语义：actor、notification、audit、permission、payment、data / export、accessibility / a11y、locale / i18n 等验收类别必须进入 `spec`、角色 posture、`workflow` 或 evidence 规则；只保留任务对象不算投影完成。
- 若宿主任务摘要显式表达假完成风险或证据偏好，Core 应要求候选 bundle 保留相同类别语义：具体假完成类型、browser / command / audit / permission / payment / refund / billing / data / export / report / accessibility / locale 等 proof mode 必须进入 `spec`、角色 posture、`workflow` 或 evidence 规则；只把任务对象写进 `Task` 不算投影完成。
- `loopora agent <adapter> gen` 必须提供非空宿主任务摘要。提交候选方案文件时该摘要用于 Core traceability；未提交候选方案文件时该摘要是 Web review prefill 的最小任务锚点。缺少摘要时 Core 在创建候选或 fallback session 前拒绝请求，而不是生成无任务内容的审查入口或降级为无 traceability 检查。
- 宿主入口和 CLI 的人类可读输出应把结果说成 Loop 预览与 preview URL；`READY`、`candidate`、bundle hash 和候选字节数是 Core/JSON/诊断事实，不是用户默认要阅读的成功主语。
- 宿主入口提交了候选方案文件但 Core 校验失败时，人类可读输出必须表达为 Loop 预览需要修复方案文件，且在修复前不能 `/loopora-loop`；不能只暴露内部 `failed` 状态。若失败同时带有 `loopora_fit_contradiction`，输出还必须明确这是 not-fit / reframe 问题，需要重新说明后续证据、handoff 或 GateKeeper 价值，而不是暗示只要修文件结构就能运行。
- 宿主入口提交了候选方案文件但 Core 校验失败时，返回的 preview URL 必须打开 Web 修复面，而不是只打开一条失败对话：如果当前 `artifacts/bundle.yml` 仍可读取，Web 应展示它的治理投影和源文件入口；如果读取失败，Web 应展示源文件错误与重新同步入口；两种情况都不得显示创建运行动作，直到重新校验为 READY。
- 宿主入口提交候选方案文件时，Core binding 必须同时记录宿主原始提交的 `candidate_sha256` / `candidate_bytes`，以及 READY 后实际用于预览、导入和运行的规范化文件 `ready_candidate_sha256` / `ready_candidate_bytes`；`agent_candidate_received` event 先记录原始提交供 READY 校验识别 Agent-first 边界，READY 成功后再用 `agent_candidate_ready_content` event 记录规范化文件哈希。未提交候选方案文件或候选未通过 READY 校验时，READY 哈希字段为空哈希 / `0` 字节，并与 `requires_web_alignment` / `requires_candidate_repair` 一起说明当前不是可运行输入。若 canonical `bundle.yml` 在 READY 后被改成另一份仍可通过校验的文件，导入校验记录的规范化文件哈希必须覆盖旧 binding 哈希，避免 binding 继续声称运行的是旧预览内容。
- 宿主入口提交候选方案文件但 Core 校验失败时，JSON/API 与 binding 必须用 `requires_candidate_repair` 明确表达当前需要修复候选文件；该字段不替代 validation error，也不能把有候选文件的失败混同为无候选文件的 Web review fallback。
- 若宿主入口无法可靠取得完整会话上下文或没有提交候选方案文件，adapter 只能退化为打开 Web Loop setup / review 预填入口；该入口保留用户消息与来源 provenance，并在 transcript 中可见说明当前只是 Web review、尚非可运行 Loop，以及需要补齐成功标准、假完成、证据预期、执行策略、判断取舍、残余风险和本地治理责任；若宿主消息已经表达一次性任务、直接回答、不需要 Loop 或后续不会产生新证据，transcript、binding / JSON 与 CLI 输出必须优先解释 not-fit 与需要重新定义后续证据 / handoff / GateKeeper 裁决，不能只给通用补齐清单；默认 transcript 和托管入口说明应说“候选方案文件 / candidate plan file”，不把 YAML 当作用户默认主语；不得自动启动后端 alignment Agent，也不得伪装成 READY 或可运行 Loop。JSON/API 字段可继续使用 `requires_web_alignment` 表达内部状态；`loopora_fit_contradiction` 只表达当前无候选 fallback 的 not-fit 诊断，原始信号由 `agent_candidate_received` event 保留用于排障。
- `requires_web_alignment` 与 `loopora_fit_contradiction` 表达当前 binding 仍只是预填 / not-fit 审查入口；同一 alignment session 经过 Web review、文件同步或导入成为可运行 Loop 后，`/loopora-loop` 必须在 binding 中清除这些当前态标记，避免旧 fallback 状态覆盖 READY / imported / running 事实。

### 3.2 `/loopora-loop`

用户语义：

> 用已审查或已接受的 Loop 协议启动或推进当前任务。

Agent-native entry 路径：

1. CLI/Core 查找当前宿主 session 或 workdir 绑定的 READY alignment session。
2. 若不存在 ready Loop preview，返回明确错误，提示先运行 `/loopora-gen`；人类可读错误不把 `READY bundle` 当作默认主语。
3. 若 READY session 尚未导入，Core 复用现有 alignment import 路径物化 bundle、Loop、roles 和 workflow。
4. Core 创建或复用 `agent_native` run，并返回 run URL 与下一个 execution capsule。
5. 宿主 Agent 读取 capsule 的 `role_dispatch.target_agent`，并把完整 `next_step.prompt`、`next_step.judgment_contract`、`next_step.required_coverage`、`next_step.output_schema`、`next_step.action_policy`、`next_step.known_evidence_ids` 与 `context_path` / `context_absolute_path` 一起交给该命名原生 subagent / task agent 执行；不能用主对话 inline 完成角色工作，也不能把 prompt、判断契约、覆盖缺口、动作权限、输出契约或 evidence ref 闭集裁剪、改写后再派发。
6. 宿主 Agent 或 subagent 把带 `loopora_host_dispatch` 证明块的 wrapper JSON 提交回 Loopora Core；Core 校验 dispatch proof、入账 evidence / handoff / verdict 并推进下一个 step。

稳定规则：

- `/loopora-loop` 不从一句话任务直接生成 bundle。
- `/loopora-loop` 不绕过 bundle import、workspace lock、run lifecycle 或 evidence gate。
- `/loopora-loop` 的硬门槛是当前 session / workdir 存在 READY Loop 预览或已导入 Loop；用户审查或接受 preview 的动作由主动调用 `/loopora-loop` 表达，不另设一个隐式 confirmed-preview 状态。
- `/loopora-loop` 发现当前 binding 仍处于 `requires_candidate_repair`、`requires_web_alignment` 或 `loopora_fit_contradiction` 时，错误必须保留对应状态语义：候选文件失败应提示修复方案文件，无候选 fallback 应提示 Web review，not-fit fallback 或 not-fit candidate failure 应提示重新定义后续证据 / handoff / GateKeeper 价值；不能把这些状态都压成泛泛的“没有 ready preview”。
- `/loopora-loop` 读取宿主 binding 后必须确认 binding 与 alignment session 的 workdir 都等于当前 adapter root；复制、手工改写或残留的 binding 不能让当前项目启动另一个 workdir 的 Loop。
- READY 只证明上次校验过的 `artifacts/bundle.yml` 内容可导入；若 `/loopora-loop` 即将从 READY session 导入，Core 必须重新读取当前 bundle 文件并执行同一套结构、语义与 traceability 校验，不能用旧 READY 状态运行已被人工或宿主改坏的文件。重校通过后，binding 中的 `ready_candidate_sha256` / `ready_candidate_bytes` 必须刷新为本次实际导入和运行的规范化文件。
- 重复调用时返回已绑定 run 的当前状态；非终态 active run 不会被重复创建，同一 workdir 不会静默产生多个活动 run。
- Agent-first 路径不启动 Codex / Claude Code / OpenCode CLI 子进程来模拟角色；宿主 Agent 是执行主体，Loopora Core 只出租下一步 capsule 与接收结果。
- `headless` / legacy 路径可继续由 Loopora worker 调 executor 子进程，用于 CI、无人值守、custom command 或没有可用宿主 Agent 的场景；该路径不能被 `/loopora-loop` 默认使用。
- Claude Code skill 可使用 `${CLAUDE_SESSION_ID}` 作为 `--context-id`；Loopora-managed SessionStart hook 应从宿主 hook input 中导出该变量和 `LOOPORA_AGENT_SESSION_ID`。不可用时仍回落到 workdir 绑定；该回落必须被 binding 标明，不能伪装成宿主 session 绑定。
- OpenCode command 当前不依赖用户 `opencode.json`，可使用显式 `--context-id` 或未来宿主暴露的 `OPENCODE_SESSION_ID`；不可用时回落到 workdir 绑定，并在 binding 中标明来源。
- Managed entry 必须把入口来源写入 Core binding；宿主命令可通过 hidden `--entry-source` 或 Loopora-managed 环境标记传递来源，但这两者都只用于 provenance，不改变 bundle / run 业务语义。
- execution capsule 至少包含 step identity、role / archetype、role prompt ref / posture notes、role dispatch contract、action policy、required coverage 摘要、冻结 `judgment_contract` 投影、完整 step prompt、输入裁剪后的上下文与 context refs、输出 schema、evidence rules、evidence ref contract、提交入口和可观察 run URL。required coverage 摘要必须暴露 coverage status、covered / missing check count、missing check ids 与 top coverage gaps；capsule 内的 `judgment_contract` 必须从 StepContextPacket contract 投影出完整运行字段，并与 run-level JSON 摘要同源，使宿主能把下一步拉回具体判断契约与证据缺口；当旧版或裁剪后的 StepContextPacket 缺少 Loopora fit、执行策略、判断取舍、本地治理、成功面、假完成、证据偏好或残余风险字段时，Core 必须从冻结 run contract 派生这些字段，不能用空 context 覆盖已冻结判断；capsule 不能包含必须由宿主外部重新推断的隐式状态，宿主不得把长 prompt 文案解析当作发现角色判断姿态、本步行动权限、冻结判断契约或 required coverage 缺口的唯一方式。
- `role_dispatch` 是硬提交契约，不只是提示文案：它声明 required、target_agent、inline_allowed、accepted_dispatch_modes、proof_field 和 result_field。宿主提交时必须带 `loopora_host_dispatch`，且 run id、step id、adapter、target agent、actual agent、dispatch mode 必须与 capsule 匹配；`inline` 必须作为 literal JSON boolean 明确提交。缺失、inline 或 agent 不匹配时 Core 必须拒绝 submit。`required` 与 `inline_allowed` 必须按 literal JSON boolean 解释；声明了 `role_dispatch` 但 `required` 不是 literal `true` 时，Core 必须拒绝而不是把 malformed capsule 当作无需 proof。`schema_version` 缺失或空值时默认 `1`，但显式布尔值、小数或非整数不能被 `int()` 提升成有效 proof 版本。
- Agent-native submit 必须把 `next_step.output_schema`、`action_policy`、`judgment_contract`、`required_coverage` 与 `known_evidence_ids` 当成 Core 边界，而不是只作为宿主提示：缺少这些 capsule 字段、`known_evidence_ids` 不是字符串数组、`action_policy.workspace` 不是 `read_only` / `workspace_write`，或 `can_block` / `can_finish_run` 不是 literal boolean 时必须失败关闭；必填字段、稳定类型、enum、嵌套 object / array item 和 `additionalProperties=false` 都必须在入账前校验；`action_policy.workspace=read_only` 的 step 不得提交 `changed_files` / generated artifact / proof artifact / artifact path 等 workspace artifact 声称。失败请求不能写入 raw output、handoff 或 evidence ledger。
- evidence rules 是宿主执行 step 时必须遵守的语义约束，不是文案契约；例如 GateKeeper pass 必须引用支持性的上游 evidence refs，blocked / failed evidence 不能支撑 pass，finish coverage 由 Loopora Core 根据 verdict 派生。
- `coverage_results.status` 使用覆盖状态词汇 `covered` / `weak` / `blocked` / `missing`；`Proven` / `Weak` / `Unproven` / `Blocking` / `Residual risk` 是 verdict / note bucket，不是 coverage status。`coverage_results[].target_id` 也必须逐字来自 `judgment_contract.coverage_targets[].id`，不能让宿主通过新造 target 绕开 bundle 已编译的判断面。历史 ledger projection 可继续兼容旧 alias，但 Agent-native 新 submit 必须按 capsule schema 与 coverage target 闭集失败关闭。
- `known_evidence_ids` 是闭集。宿主提交的 `evidence_refs`，包括 `coverage_results[].evidence_refs`，只能逐字复制该列表中的 ID；派生子 ID、artifact label 或文件名都必须写入 claims / notes，未知 evidence refs 由 Core 当作 blocking evidence gate 失败处理。非 GateKeeper step 的未知引用应在 submit 边界被拒绝，避免无效 ref 写入 ledger；GateKeeper pass 的未知引用则进入 GateKeeper evidence gate 并把 pass 改写为 blocking verdict。
- submit proof 或非 GateKeeper evidence ref 闭集校验失败时，Core 不得写入 canonical step output、handoff 或 evidence ledger；失败请求只能作为接口错误返回，不能污染后续 step 的事实源。
- Evidence / handoff 回填是受限动作：宿主可以提交当前已 claim step 的结构化结果，不能任意改写 Loop 生命周期或 GateKeeper 裁决。
- `agent_native` 进入 `parallel_group` 时，每个同组 capsule 的 StepContextPacket 与 `known_evidence_ids` 必须来自同一个组起点快照；同组 peer 的提交可以即时落账，但不能出现在后续 peer 的上下文或可引用 evidence 闭集中，组后的下游 step 才能 fan-in 已落账的 peer handoff / evidence。
- `agent_native` 必须与 headless 使用同一组并行检视白盒事件：进入组时写 `parallel_group_started`，组内最后一个 peer 提交后写 `parallel_group_finished`；这些事件表达 workflow 形状，不替代 step 自身的 context / handoff / evidence。
- `agent_native` run 触发 workflow control 时，Core 必须把 control invocation 作为宿主可 claim 的 execution capsule 返回，而不是回退到 headless executor 或只记录 deferred 事件。该 capsule 仍必须遵守 `role_dispatch` 证明、不能调用 Builder、不插入 canonical workflow 顺序；control 完成后必须写入 control event 与 `evidence_kind=control` 的 ledger item。
- `agent_native` 的 control queue 与 fire count 是本地运行状态，不是外部输入；缺失字段可按初始状态恢复，但损坏的队列游标、step order 或 fire count 不能被字符串 / 布尔 / 小数提升为有效计数。损坏队列项应跳过，损坏 fire count 应按已达到触发上限处理，避免重放 control 或越过 fire limit。
- `loopora agent <adapter> loop/next/submit` 的人类可读输出必须在 run artifacts 可用时投影冻结的 run contract：至少包含 `run_contract_path`、source plan provenance、判断摘要、Loopora fit、执行策略、本地治理责任、判断取舍、成功面、假完成、证据偏好、残余风险，以及 check mode、completion mode、workflow preset 与 coverage target trace；JSON `judgment_contract` 也必须保留同一组执行锚点（含 `source_bundle` provenance），使 run-level 投影和 step capsule 不会在覆盖目标上分叉；在终态完成时还必须同时报告 run lifecycle 与 task verdict。宿主 Agent 或用户不能只根据 `succeeded` 判断任务已被证据证明。
- `loopora agent <adapter> loop/next/submit --json` 也必须返回同一语义的 `judgment_contract` 投影；managed entry 不能只依赖非 JSON 终端文案来知道被冻结的判断输入。

### 3.3 Agent-native 与 headless 边界

| 平面 | 执行主体 | 入口 | 适用场景 |
| --- | --- | --- | --- |
| `agent_native` | 当前 Coding Agent 及其原生 subagent / task agent | `/loopora-gen`、`/loopora-loop`、`loopora agent <adapter> next/submit` CLI entry | 默认 Agent-first 用户路径 |
| `headless` | Loopora worker 调用 executor 子进程 | `loopora loops run`、后台 worker、CI / custom command | 无宿主 Agent、自动化回归、legacy run |

稳定规则：

- `agent_native` run 可以进入 `awaiting_agent` 状态，表示 Loopora 正等待宿主领取或提交 step；它不是终态，也不是后台 worker 正在执行。
- `agent_native` 不使用 `executor_kind` 触发 provider CLI；bundle 中保留 executor fields 只作为兼容投影和 headless fallback 配置。
- `headless` 仍必须使用 `03-executor-subsystem.md` 的结构化输出、timeout、stop 和 fake executor 安全网。
- Web 可以观察两类 run，但必须把 `awaiting_agent` 与普通后台 `running` 区分开。

## 4. Ownership 与安装

Agent adapter 的项目文件分三类：

| 平台 | 类别 | 路径 | Ownership |
| --- | --- | --- |
| Codex | Loopora-managed skill | `.agents/skills/loopora-gen/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Codex | Loopora-managed skill | `.agents/skills/loopora-loop/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Codex | Loopora-managed custom agent | `.codex/agents/loopora-*.toml` | Loopora 整文件管理，用于 Codex subagent role posture |
| Codex | Loopora-managed orchestrator agent | `.codex/agents/loopora-orchestrator.toml` | Loopora 整文件管理，用于宿主侧 step dispatch posture |
| Codex | Loopora manifest | `.loopora/adapters/codex/manifest.json` | Loopora 管理，用于记录模板 hash、版本和已安装文件 |
| Claude Code | Loopora-managed command | `.claude/commands/loopora-gen.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Claude Code | Loopora-managed command | `.claude/commands/loopora-loop.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Claude Code | Loopora-managed skill | `.claude/skills/loopora-gen/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Claude Code | Loopora-managed skill | `.claude/skills/loopora-loop/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Claude Code | Loopora-managed hook script | `.claude/hooks/loopora-session-context.py` | Loopora 整文件管理，用于把宿主 session identity 注入 CLI entry 环境 |
| Claude Code | Loopora-managed hook handler | `.claude/settings.json#hooks.SessionStart.loopora` | Loopora 只管理这一条 hook handler；保留用户 settings 的其他字段和其他 hooks |
| Claude Code | Loopora-managed subagent | `.claude/agents/loopora-*.md` | Loopora 整文件管理，用于 Claude Code subagent role posture |
| Claude Code | Loopora-managed orchestrator agent | `.claude/agents/loopora-orchestrator.md` | Loopora 整文件管理，用于宿主侧 step dispatch posture |
| Claude Code | Loopora manifest | `.loopora/adapters/claude/manifest.json` | Loopora 管理，用于记录模板 hash、版本和已安装文件 |
| OpenCode | Loopora-managed command | `.opencode/commands/loopora-gen.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| OpenCode | Loopora-managed command | `.opencode/commands/loopora-loop.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| OpenCode | Loopora-managed subagent | `.opencode/agents/loopora-*.md` | Loopora 整文件管理，用于 OpenCode Task / subagent role posture |
| OpenCode | Loopora-managed orchestrator agent | `.opencode/agents/loopora-orchestrator.md` | Loopora 整文件管理，用于宿主侧 step dispatch posture |
| OpenCode | Loopora manifest | `.loopora/adapters/opencode/manifest.json` | Loopora 管理，用于记录模板 hash、版本和已安装文件 |

稳定规则：

- 不覆盖用户已有 `AGENTS.md`、`CLAUDE.md`、`.codex/config.toml`、`.codex/hooks.json`、`.claude/commands/*`、`opencode.json`、`.opencode/opencode.json*`、`.opencode/agents/*`、`.opencode/skills/*`、`.opencode/plugins/*`、`.opencode/tools/*` 或其他宿主配置。`.claude/settings.json` 是唯一例外：Loopora 可以结构化合并或删除自己的 SessionStart hook handler，但不得改写用户已有 permissions、其他 hooks 或无关字段。
- 安装只写 Loopora 明确拥有的文件；若目标路径存在非 Loopora-managed 内容，安装必须失败关闭并说明冲突。
- 重复安装幂等：当前文件匹配模板时不产生重复内容；旧 managed 模板可升级到当前模板。
- 卸载只删除 manifest 记录或当前模板确认属于 Loopora 的文件；非 Loopora-managed 文件必须保留。
- 卸载后只清理空的 adapter 子目录；不得删除用户 `.agents/`、`.codex/`、`.claude/`、`.opencode/` 或 `.loopora/` 中的其他资产。

## 5. 状态投影

Adapter status 是接口层投影，不是新的业务状态机。

| 状态 | 语义 |
| --- | --- |
| `not_installed` | 没有发现该平台的 Loopora-managed adapter 文件 |
| `installed` | manifest 与 managed 文件都匹配当前模板 |
| `needs_update` | manifest 存在且文件缺失，或文件仍可确认是 Loopora-managed 但与当前模板不同 |
| `error` | manifest 损坏、路径冲突、文件被改成无法确认 ownership，或其他无法判断状态 |
| `not_implemented` | 平台预留，当前没有可执行安装能力 |

CLI 和 Web 必须调用同一个 adapter service/helper 获取状态和执行 install/uninstall，避免 Web-only 安装逻辑。

## 6. Web 控制入口

Web Tools 是观察台和控制台，不是新的 Agent 宿主。它可以展示 adapter 状态，并触发与 CLI 相同的安装 / 卸载能力。

稳定规则：

- Web 操作必须显式绑定一个目标项目目录；没有显式输入时可以使用服务进程当前目录作为默认投影，但浏览器 journey 必须能选择独立临时项目目录来证明真实文件写入边界。
- Web 与 CLI 的安装成功反馈必须把实际目标目录和下一步用户动作投影出来：回到对应 Coding Agent，先运行 `/loopora-gen` 生成并审查 Loop 预览，再运行 `/loopora-loop` 启动或继续任务。JSON 输出仍只承载结构化状态，不把提示文案变成接口契约。
- CLI 人类可读安装反馈应把“Coding Agent 入口已安装、目标项目、下一步动作”放在文件清单之前；managed files、manifest、adapter status 等 ownership 细节只作为诊断信息，不能盖过 `/loopora-gen -> Loop preview -> /loopora-loop` 的默认路径。
- `loopora init` / `loopora uninstall` 这类 first-use CLI help 也属于用户入口面，应默认说项目入口 / project entry 和目标项目目录；`adapter`、manifest、binding 等实现词只用于内部 runtime、JSON、错误诊断或设计文档上下文。
- Web Tools 是首页和教程里“安装 Coding Agent 入口”的默认落点；Agent adapter panel 必须排在防休眠和本地资产健康这类维护面板之前，并直接呈现安装后的 `/loopora-gen -> /loopora-loop` 下一步。
- Web 安装 / 卸载请求只传递目标目录和 adapter kind；实际文件写入、ownership、status 判断仍由 adapter service/helper 负责。
- Web 对 Codex / Claude Code / OpenCode 提供安装、更新、卸载。
- Web 不直接生成或删除宿主文件，不读取或修改用户 `AGENTS.md`、`CLAUDE.md`、`.codex/config.toml`、`opencode.json`、`.opencode/opencode.json*` 等配置；Claude Code 的 settings hook 合并也必须经由同一 adapter service/helper，而不是 Web-only 逻辑。

## 7. 验证责任

Agent-first adapter 的验证按证据类型组织，而不是按旧的 L1/L2/L3 层级组织：

| 类型 | 运行画像 | 覆盖重点 |
| --- | --- | --- |
| Contract checks | default / focused | CLI 幂等安装卸载、managed ownership、不覆盖用户配置、READY binding、`/loopora-loop` 缺 READY 失败、agent-native next/submit、parallel_group capsule 快照隔离、API 状态和未实现平台 |
| Journey checks | focused / release | Tools 页选择目标项目、Codex / Claude / OpenCode 安装 / 状态刷新 / 卸载、冲突错误可见 |
| Real probes | opt-in / release | 真实 Codex / Claude Code / OpenCode host / slash、skill 或 command 入口能把对话 brief 编译成 READY bundle，并按 `/loopora-gen` 后 `/loopora-loop` 的顺序产生 binding、agent-native run、runtime activity、step evidence 与终态；真实 `loopora serve` 进程中的 Web Tools 能完成安装 / 更新 / 卸载并展示异常状态 |
| Review cases | opt-in | Agent-native 运行是否仍读起来像 Loopora-managed 入口，而不是 inline shortcut、prompt pack 或 role zoo |

稳定规则：

- Contract checks 是本地 default-fast 和普通 CI job 的提交前默认质量门槛；journey checks 在 touched UI、浏览器/container CI job 或 release profile 中运行；real probes 是发布或合并到上线分支前的主动 gate。
- Real probe 的入口是 handbook，而不是单个 pytest 文件；运行或解释前应先读 `tests/probes/real_environment/README.md`，再选择 runner suite、目标 Agent 与等待/排障策略。测试代码只断言稳定契约，说明书承载等待、并行、日志追踪和模糊语义排障经验。
- Real probe 可以依赖本机真实 Codex、浏览器和 shell 环境；缺少环境时必须 skip 并给出缺少的显式环境变量或命令模板。
- Real probe 仍然断言用户可观察结果和落盘资产，不把宿主 CLI 的内部输出格式写成 Loopora 契约。
- Real Agent 入口测试不得在测试 prompt 中直接给出 `loopora agent <adapter> gen` / `loopora agent <adapter> loop` 的底层命令；这些命令只能来自 Loopora-managed entry 文件。managed entry 应把入口来源写入 Core binding，供测试和排障确认真实入口顺序；直接凭记忆调用底层 CLI 不能算作通过 Agent-first 入口。
- Real Agent 入口测试必须覆盖从对话引导生成候选方案文件的路径：harness 可以提供确定性 conversation brief、目标 candidate path 和必须满足的运行契约要求，但不得预先写好 candidate plan file、不得在 prompt 中嵌入完整候选文件再让宿主照抄导入；通过条件必须包括宿主创建的 candidate file、alignment transcript / manifest、READY validation、linked bundle / loop / run。
- Real Agent-native 测试必须放置会失败的 sentinel `codex`、`claude`、`opencode` 子进程命令或等价进程追踪，证明 Loopora run 内没有反向调用宿主 Agent CLI。
- Real probe 应证明至少一个 role step 通过 `role_dispatch.target_agent` 路径提交，并且 `loopora_host_dispatch.inline=false`、`actual_agent=target_agent`；在宿主支持 subagent 的场景，测试应优先要求使用 subagent / task agent，而不是只让主对话 inline 完成所有 step。
- Codex real probe 通过原生 `spawn_agent` 验证 `role_dispatch.target_agent` 时，managed entry 必须提示宿主使用目标 agent type、避免 full-history fork、只传递当前 step 必需上下文、`next_step.judgment_contract`、required coverage、output schema、action policy 与 evidence ids，并用短于外层命令的有限等待；宿主不得无限等待子 agent，也不得在子 agent 未返回时用 inline work 伪造提交。
- Codex / Claude Code / OpenCode 的 Agent-host real probe 目标互不共享 workdir、Loopora home、Web port 和 binding state；发布验证入口可以把每个 host 目标拆成独立 pytest 子进程并行运行，并在等待期间输出 heartbeat 与可追踪日志路径。real Agent-host harness 还应在 workdir 下写 `.loopora/real-probes/real-agent-phase-report.json`，把 candidate、validation、binding、runtime activity、run events、agent-native state、coverage、task verdict、role output 与 sentinel log 压成诊断投影。默认发布路径还必须把 Claude Code 的 `Kimi-K2.6` 与 OpenCode 的 `minimax-token-plan/MiniMax-M2.7` 作为可见模型断言；若要验证模型覆盖，必须通过显式 override 开关让本次 real probe 失去默认模型证明含义。并行、heartbeat 与 phase report 只属于 harness 调度 / 观察优化，不得削弱 sentinel、entry provenance、subagent dispatch proof 或终态断言。
- Real probe 的测试 bundle 使用最小覆盖模型：bundle 内只验证 Agent entry、binding、一个上游 step supporting evidence 与 GateKeeper terminal decision；Builder step 必须留下可被 GateKeeper 引用的 proof artifact 或 measured evidence，不能只用普通 handoff 自述支撑 pass。run 最终终态由测试 harness 外层断言，不应写成 Loop task 的 Done When，也不应为了证明入口契约引入额外 Inspector 长链路。harness 应在宿主命令运行期间轮询 runtime activity，并在完成后断言 run events 至少覆盖 context preparation、role request、agent-native claim/submit、handoff、summary 与 terminal task verdict。
- Release Web real probe 至少覆盖 Codex / Claude Code / OpenCode 的 `not_installed`、`installed`、`needs_update` 与 `error` 投影，避免只验证 happy path；harness 应写出轻量 phase report，记录真实 `loopora serve` 命令、base URL、每个 adapter 的状态迁移与关键文件状态，便于失败时区分服务启动、浏览器路径和文件所有权问题。

## 8. 依赖边界

依赖方向：

`Agent skill / Web / CLI -> adapter service -> Loopora Core services -> bundle / alignment / run / Web serve`

禁止：

- Web 直接写 Agent adapter 文件。
- Agent adapter 直接创建 run record 或修改 DB。
- Adapter 自己解析或校验 bundle 契约。
- Adapter 为未实现平台生成假入口。

## 9. 后续扩展点

- Codex 原生 slash command 文件格式稳定后，可在 Codex adapter registry 中新增 `.codex/commands/*`，仍由 manifest 管理。
- Codex hook 若能提供稳定 session identity，binding key 应优先使用宿主 thread/session id，而不是 workdir fallback。
- Claude Code hook / slash-command 变量若提供更稳定的 session 或 transcript identity，可由 skill 显式传入 `--context-id`，仍复用同一 binding 写入边界。
- OpenCode server command API 或 custom tool 若提供稳定 session identity，可由 command / tool 显式传入 `--context-id`，仍复用同一 binding 写入边界。
- per-turn context capsule 应从 run / step / evidence 事实源生成，并由宿主 hook 或 skill / command self-pull 注入 Coding Agent；Loopora CLI/Core 仍是唯一后端一致性入口。
- Evidence / handoff 回填应成为受限动作：Coding Agent 可以提交当前 step 产物，但不能任意改写 Loop 生命周期或 GateKeeper 裁决。

## 10. 变更触发

以下变化需要更新本文档：

- 新增或删除支持的平台。
- Codex / Claude / OpenCode adapter 从当前 entry 路径改为原生 slash command、hook、server API 或 MCP。
- managed 文件 ownership 或 manifest 机制变化。
- `/loopora-gen` 与 `/loopora-loop` 的 READY / run 边界变化。
- context capsule 或 evidence 回填进入可运行第一路径。
- Contract / journey / real probe / review case 验证责任迁移。

以下变化通常不需要更新本文档：

- skill 文案调整。
- Web 卡片布局调整。
- manifest 字段的非破坏性扩展。
