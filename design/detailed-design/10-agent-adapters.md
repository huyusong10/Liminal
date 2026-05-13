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
| Codex | 已实现 | 安装项目级 Codex skill 入口和 Loopora role custom agents；`/loopora-gen` 校验 READY bundle，`/loopora-loop` 创建或复用 agent-native run，并让 Codex 用原生 subagent / thread 机制推进 step |
| Claude Code | 已实现 | 安装项目级 Claude Code command / skill 入口和 Loopora subagents；`/loopora-gen` 校验 READY bundle，`/loopora-loop` 创建或复用 agent-native run，并让 Claude Code 用原生 Agent / subagent 机制推进 step |
| OpenCode | 已实现 | 安装项目级 OpenCode command 入口和 Loopora subagents；`/loopora-gen` 校验 READY bundle，`/loopora-loop` 创建或复用 agent-native run，并让 OpenCode 用原生 Task / subagent 机制推进 step |

Codex 选择项目级 skill 文件承载用户入口，并安装符合 Codex custom agent schema 的 `.codex/agents/*.toml` 承载 Loopora role posture；custom agent 文件必须使用宿主原生字段表达 agent name、description 与 developer instructions。Codex app / CLI 中 enabled skills 可进入 slash 列表；若宿主只支持 skill invocation，`/loopora-gen` 与 `/loopora-loop` 的用户语义由同名 skill 触发承载。

Claude Code 同时安装项目级 command、skill、subagent 与受管 SessionStart hook：`.claude/commands/*` 提供稳定 slash 入口，`.claude/skills/*` 提供可复用工作流说明，`.claude/agents/*` 用原生 frontmatter 表达 role-specific subagents 的工具面，`.claude/hooks/*` 与 `.claude/settings.json` 中的 Loopora-managed hook handler 用于把宿主 session id 注入后续 CLI entry。Claude Code 的 MCP prompt 和 agent teams 是后续增强点，不能替代当前 command / subagent / CLI 第一路径。

OpenCode 选择官方项目级 custom command 路径：`.opencode/commands/<command>.md`，并安装 `.opencode/agents/*` subagents。`/loopora-loop` command 应使用 OpenCode 原生 `agent` / `subtask` 字段把入口交给 Loopora orchestrator subagent；role agent 文件应使用 `mode: subagent` 与 `permission.task` 表达调用边界，而不是只靠自然语言约束。OpenCode 的 server command/message API 可用于 real probe 仿真，但其业务语义必须与 TUI command 入口一致。

## 3. Entry 语义

### 3.1 `/loopora-gen`

用户语义：

> 把当前 coding 任务、上下文和用户判断编译成候选 Loop。

当前 Agent entry 路径：

1. 宿主 skill / command 读取当前会话中已经可见的任务目标、约束、风险和本地治理入口。
2. 宿主 Agent 生成候选 bundle YAML。
3. Skill 调用 Loopora CLI adapter entry，把候选 YAML 交给 Core。
4. Core 创建或更新一个 READY alignment session，运行 bundle 结构校验、spec 编译、alignment 语义 linter 与 READY 投影。
5. CLI 确保本地 Web 服务可用，并返回候选 Loop URL。

稳定规则：

- `/loopora-gen` 不启动 run。
- READY 的事实源是 Loopora Core 校验后的 alignment session 和 `artifacts/bundle.yml`，不是 Codex 的自然语言说明。
- Coding Agent 可以生成候选 YAML，但不能自己宣布 READY；READY 只由 Core 校验产生。
- 若宿主入口无法可靠取得完整会话上下文，adapter 可退化为打开 Web alignment 预填入口；该退化必须在结果中暴露为未 READY，不得伪装成可运行 Loop。

### 3.2 `/loopora-loop`

用户语义：

> 用已确认的 Loop 协议启动或推进当前任务。

Agent-native entry 路径：

1. CLI/Core 查找当前宿主 session 或 workdir 绑定的 READY alignment session。
2. 若不存在 READY bundle，返回明确错误，提示先运行 `/loopora-gen`。
3. 若 READY session 尚未导入，Core 复用现有 alignment import 路径物化 bundle、Loop、roles 和 workflow。
4. Core 创建或复用 `agent_native` run，并返回 run URL 与下一个 execution capsule。
5. 宿主 Agent 读取 capsule 的 `role_dispatch.target_agent`，把当前 step 交给该命名原生 subagent / task agent 执行；不能用主对话 inline 完成角色工作。
6. 宿主 Agent 或 subagent 把带 `loopora_host_dispatch` 证明块的 wrapper JSON 提交回 Loopora Core；Core 校验 dispatch proof、入账 evidence / handoff / verdict 并推进下一个 step。

稳定规则：

- `/loopora-loop` 不从一句话任务直接生成 bundle。
- `/loopora-loop` 不绕过 bundle import、workspace lock、run lifecycle 或 evidence gate。
- 重复调用时返回已绑定 run 的当前状态；非终态 active run 不会被重复创建，同一 workdir 不会静默产生多个活动 run。
- Agent-first 路径不启动 Codex / Claude Code / OpenCode CLI 子进程来模拟角色；宿主 Agent 是执行主体，Loopora Core 只出租下一步 capsule 与接收结果。
- `headless` / legacy 路径可继续由 Loopora worker 调 executor 子进程，用于 CI、无人值守、custom command 或没有可用宿主 Agent 的场景；该路径不能被 `/loopora-loop` 默认使用。
- Claude Code skill 可使用 `${CLAUDE_SESSION_ID}` 作为 `--context-id`；Loopora-managed SessionStart hook 应从宿主 hook input 中导出该变量和 `LOOPORA_AGENT_SESSION_ID`。不可用时仍回落到 workdir 绑定；该回落必须被 binding 标明，不能伪装成宿主 session 绑定。
- OpenCode command 当前不依赖用户 `opencode.json`，可使用显式 `--context-id` 或未来宿主暴露的 `OPENCODE_SESSION_ID`；不可用时回落到 workdir 绑定，并在 binding 中标明来源。
- Managed entry 必须把入口来源写入 Core binding；宿主命令可通过 hidden `--entry-source` 或 Loopora-managed 环境标记传递来源，但这两者都只用于 provenance，不改变 bundle / run 业务语义。
- execution capsule 至少包含 step identity、role / archetype、role dispatch contract、action policy、输入裁剪后的上下文、输出 schema、evidence rules、evidence ref contract、提交入口和可观察 run URL。它不能包含必须由宿主外部重新推断的隐式状态。
- `role_dispatch` 是硬提交契约，不只是提示文案：它声明 required、target_agent、inline_allowed、accepted_dispatch_modes、proof_field 和 result_field。宿主提交时必须带 `loopora_host_dispatch`，且 run id、step id、adapter、target agent、actual agent、dispatch mode 必须与 capsule 匹配；`inline` 必须作为 literal JSON boolean 明确提交。缺失、inline 或 agent 不匹配时 Core 必须拒绝 submit。`required` 与 `inline_allowed` 必须按 literal JSON boolean 解释；声明了 `role_dispatch` 但 `required` 不是 literal `true` 时，Core 必须拒绝而不是把 malformed capsule 当作无需 proof。`schema_version` 缺失或空值时默认 `1`，但显式布尔值、小数或非整数不能被 `int()` 提升成有效 proof 版本。
- evidence rules 是宿主执行 step 时必须遵守的语义约束，不是文案契约；例如 GateKeeper pass 必须引用支持性的上游 evidence refs，blocked / failed evidence 不能支撑 pass，finish coverage 由 Loopora Core 根据 verdict 派生。
- `known_evidence_ids` 是闭集。宿主提交的 `evidence_refs`，包括 `coverage_results[].evidence_refs`，只能逐字复制该列表中的 ID；派生子 ID、artifact label 或文件名都必须写入 claims / notes，未知 evidence refs 由 Core 当作 blocking evidence gate 失败处理。非 GateKeeper step 的未知引用应在 submit 边界被拒绝，避免无效 ref 写入 ledger；GateKeeper pass 的未知引用则进入 GateKeeper evidence gate 并把 pass 改写为 blocking verdict。
- submit proof 或非 GateKeeper evidence ref 闭集校验失败时，Core 不得写入 canonical step output、handoff 或 evidence ledger；失败请求只能作为接口错误返回，不能污染后续 step 的事实源。
- Evidence / handoff 回填是受限动作：宿主可以提交当前已 claim step 的结构化结果，不能任意改写 Loop 生命周期或 GateKeeper 裁决。
- `agent_native` 进入 `parallel_group` 时，每个同组 capsule 的 StepContextPacket 与 `known_evidence_ids` 必须来自同一个组起点快照；同组 peer 的提交可以即时落账，但不能出现在后续 peer 的上下文或可引用 evidence 闭集中，组后的下游 step 才能 fan-in 已落账的 peer handoff / evidence。
- `agent_native` 必须与 headless 使用同一组并行检视白盒事件：进入组时写 `parallel_group_started`，组内最后一个 peer 提交后写 `parallel_group_finished`；这些事件表达 workflow 形状，不替代 step 自身的 context / handoff / evidence。
- `agent_native` run 触发 workflow control 时，Core 必须把 control invocation 作为宿主可 claim 的 execution capsule 返回，而不是回退到 headless executor 或只记录 deferred 事件。该 capsule 仍必须遵守 `role_dispatch` 证明、不能调用 Builder、不插入 canonical workflow 顺序；control 完成后必须写入 control event 与 `evidence_kind=control` 的 ledger item。
- `agent_native` 的 control queue 与 fire count 是本地运行状态，不是外部输入；缺失字段可按初始状态恢复，但损坏的队列游标、step order 或 fire count 不能被字符串 / 布尔 / 小数提升为有效计数。损坏队列项应跳过，损坏 fire count 应按已达到触发上限处理，避免重放 control 或越过 fire limit。
- `loopora agent <adapter> loop/next/submit` 的人类可读输出在终态完成时必须同时报告 run lifecycle 与 task verdict；宿主 Agent 或用户不能只根据 `succeeded` 判断任务已被证据证明。

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
- Real Agent 入口测试必须覆盖从对话引导生成 bundle 的路径：harness 可以提供确定性 conversation brief 和目标 candidate path，但不得预先写好 candidate YAML 再让宿主导入；通过条件必须包括宿主创建的 candidate file、alignment transcript / manifest、READY validation、linked bundle / loop / run。
- Real Agent-native 测试必须放置会失败的 sentinel `codex`、`claude`、`opencode` 子进程命令或等价进程追踪，证明 Loopora run 内没有反向调用宿主 Agent CLI。
- Real probe 应证明至少一个 role step 通过 `role_dispatch.target_agent` 路径提交，并且 `loopora_host_dispatch.inline=false`、`actual_agent=target_agent`；在宿主支持 subagent 的场景，测试应优先要求使用 subagent / task agent，而不是只让主对话 inline 完成所有 step。
- Codex real probe 通过原生 `spawn_agent` 验证 `role_dispatch.target_agent` 时，managed entry 必须提示宿主使用目标 agent type、避免 full-history fork、只传递当前 step 必需上下文，并用短于外层命令的有限等待；宿主不得无限等待子 agent，也不得在子 agent 未返回时用 inline work 伪造提交。
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
