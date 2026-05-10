# Trellis Agent Orchestration Reference

## 1. 文档定位

本文是 `agent-first-loopora.md` 的参考资料，用来记录 Trellis 这类 Agent-first、本地后台编排系统对 Loopora 的启发。

本文不是 Loopora 产品契约，不要求 Loopora 复刻 Trellis 的任务模型、目录结构、脚本命令、hook 文案或平台接入方式。它只回答：

> 一个以 Coding Agent 为用户入口、以本地文件和脚本为事实源、以 hooks / skills / sub-agents 为接入层的系统，哪些模式值得 Loopora 借鉴？

资料基于本地 Trellis checkout，记录日期为 2026-05-09。文中路径均相对 Trellis 仓库根目录。

## 2. 一句话结论

Trellis 证明了一个更贴近 Loopora 的 Agent-first 图景：

```text
用户仍在 Coding Agent 里工作；
后台系统持有任务、流程、规范和会话状态；
每轮通过 hook / skill / sub-agent prelude 把当前状态注入 Agent；
多平台差异由 adapter 层吸收，而不是让核心工作流分裂。
```

它与 Codex `/goal` 的差异是：

| 参考对象 | 核心形态 | 对 Loopora 的启发 |
| --- | --- | --- |
| Codex `/goal` | 宿主 runtime 原生持久 goal + 自动续跑 | 证明长期目标需要 runtime-owned state 和受限模型工具 |
| Trellis | 外部本地编排器 + 多平台 hooks / skills / scripts | 证明非宿主原生能力也可以通过统一 CLI/Core + adapter 进入 Agent 工作流 |

## 3. Trellis 的核心结构

Trellis 的稳定结构可以抽象成：

```text
.trellis/ = 本地事实源
Trellis scripts = 状态读写与上下文生成
platform adapters = hooks / skills / slash commands / sub-agents
Coding Agent = 用户入口与执行主体
```

典型目录：

```text
.trellis/
├── workflow.md          # workflow、phase、per-turn breadcrumb 的来源
├── config.yaml          # 项目级配置
├── tasks/               # task PRD、jsonl context、task.json 状态
├── workspace/           # developer journal / session continuity
├── spec/                # 项目规范和分层指南
├── .runtime/sessions/   # session-scoped active task pointer
└── scripts/             # task.py / get_context.py / add_session.py 等后台命令
```

平台接入文件由 `trellis init --codex --opencode --cursor ...` 生成，例如：

```text
.codex/       # Codex hooks、agents、config
.claude/      # Claude Code agents、hooks、settings
.opencode/    # OpenCode plugins、agents、runtime helpers
.cursor/      # Cursor commands、agents、hooks
.agents/skills/ # 多平台共享 skill 层
```

这个结构值得 Loopora 借鉴的一点是：平台入口很多，但事实源只有一个。

## 4. 工作流状态注入

Trellis 最值得借鉴的机制是 per-turn workflow breadcrumb。

`workflow.md` 里嵌入形如 `[workflow-state:STATUS]...[/workflow-state:STATUS]` 的块。hook 每轮解析当前 active task 的 `task.json.status`，再从 `workflow.md` 取对应块，注入：

```text
<workflow-state>
Task: <task-id> (<status>)
Source: session:<context-key>
<该状态下 Agent 下一步应该做什么>
</workflow-state>
```

关键设计点：

- breadcrumb 每轮注入，防止长对话中流程漂移。
- breadcrumb 文案来自 `workflow.md`，不是硬编码在 hook 里。
- 缺少对应状态块时，hook 显式降级为“参考 workflow.md”，让问题暴露，而不是静默掩盖。
- `workflow.md` 同时包含 phase index、step 说明、状态块和平台差异块，脚本只解析这些稳定标记。

对 Loopora 的启发：

```text
Loop 上下文胶囊也应是每轮可重新注入的 runtime projection，
而不是一次性启动 prompt。
```

但 Loopora 不应照搬 markdown 作为唯一事实源。Loopora 的事实源仍应是 bundle / run / step / evidence / verdict 状态；markdown 或模板只负责把状态投影成适合宿主 Agent 的上下文胶囊。

## 5. Session-Scoped Active Task

Trellis 不把 active task 简单存成全局 `.trellis/.current-task`。它优先按 AI 会话 / thread / transcript / run id 解析 context key，并把当前任务指针写到：

```text
.trellis/.runtime/sessions/<context-key>.json
```

这样同一个仓库可以同时开多个 AI session，各自有独立 active task。缺少 session identity 时，`task.py start` 会失败并提示用户设置 `TRELLIS_CONTEXT_ID`。

对 Loopora 的启发：

- `/loopora-gen` 和 `/loopora-loop` 不应只靠 workdir 选择当前 Loop。
- 至少需要区分 `workdir active loop` 与 `session/thread active loop`。
- 当宿主无法提供稳定 session identity 时，应有显式 fallback，例如环境变量、手动选择、Web 选择，而不是猜最近一个 run。
- Web 观察台需要展示“这个 Agent session 当前绑定哪个 Loop”，避免多窗口混淆。

## 6. Gen-Before-Run 的相似物

Trellis 的流程不是直接让 Agent 写代码，而是：

```text
task.py create -> prd.md / research / context jsonl -> task.py start -> implement/check -> finish/archive/journal
```

这与 Loopora 的 Agent-first 路径非常相似：

```text
/loopora-gen -> bundle preview / READY -> /loopora-loop -> evidence-backed execution / verdict
```

可借鉴点不是 `prd.md` 这个文件，而是两个阶段的硬边界：

| Trellis | Loopora |
| --- | --- |
| `task.py create` 进入 planning | `/loopora-gen` 生成候选 Loop |
| PRD / research / jsonl context 被补齐 | bundle / spec / roles / workflow / evidence 要求被确认 |
| `task.py start` 才进入 in_progress | `/loopora-loop` 才进入运行 |
| start 后 breadcrumb 改为执行态 | loop 后上下文胶囊改为 step 执行态 |

这支持 Loopora 继续坚持“先 gen，再 run”。

## 7. Role-Specific Context Curation

Trellis 在任务目录里维护：

```text
implement.jsonl
check.jsonl
```

每行是一个要注入给特定 agent 的上下文引用：

```json
{"file": ".trellis/spec/cli/backend/index.md", "reason": "why this matters"}
```

实现 agent 和检查 agent 读取不同 jsonl，从而避免把全部 spec、全部研究和全部历史塞进每个 agent。

对 Loopora 的启发：

- bundle 不应只有一个“大 prompt”。
- 每个 role / step 应有自己的 context refs、evidence refs、handoff refs 和行动边界。
- `/loopora-gen` 可以先生成候选 context refs；Web 允许用户审查和调整。
- `/loopora-loop` 注入当前 step 所需最小上下文，而不是重复注入整个 Loop 世界观。

这与 Loopora 的“上下文胶囊”高度一致。

## 8. 多平台 Adapter 能力矩阵

Trellis 把平台能力分成几类：

| 平台能力 | 接入方式 |
| --- | --- |
| 有每轮 hook | hook 自动注入 breadcrumb |
| 有 sub-agent hook | spawn 前自动注入 task context |
| 没有 sub-agent hook | sub-agent 自己 pull context |
| 没有合适 hook | skill / command 手动拉取 context |
| Codex 可选 inline | main session 直接执行，不强制 sub-agent |

它为 Codex 特别处理了 “class-2 / pull-based” 问题：当不能在 spawn_agent 前可靠注入时，custom agent 的 developer instructions 要求它自己先解析 active task，再读取 `prd.md`、`implement.jsonl` / `check.jsonl`。

对 Loopora 的启发：

```text
Loopora adapter 不应假设所有 Coding Agent 都能 push 注入。
同一套 Loopora Core 应同时支持 push-based capsule、pull-based capsule 和 manual skill fallback。
```

这也说明 `/loopora-gen` 与 `/loopora-loop` 的产品语义应该稳定，而具体接入可以因宿主不同而变化。

## 9. Inline vs Sub-Agent Dispatch

Trellis 后来加入了 `codex.dispatch_mode: inline`，允许 Codex 用户选择：

| 模式 | 执行方式 |
| --- | --- |
| sub-agent | main session 派发 `trellis-implement` / `trellis-check` |
| inline | main session 读取 spec、直接改代码、再自检 |

这个设计很贴近当前 Loopora 讨论里的关键修正：

> Coding Agent 不只是入口和展示，它可以是执行主体。

对 Loopora 的启发：

- 不要把“编排”误解为必须替用户管理一组子 Agent。
- Loopora 可以只管理 Loop 状态、上下文胶囊、证据和裁决，让当前 Coding Agent 直接执行。
- 子 Agent 是可选执行策略，不是产品心智的核心。
- 用户对“Agent 自己执行 vs 派生 sub-agent 执行”会有偏好，Loopora 应把这作为 adapter / run strategy，而不是改变 Loop 语义。

## 10. 安装与升级治理

Trellis 的 CLI 有一套值得借鉴的安装/升级治理：

- 平台注册表是单一事实源，新增平台要同时注册 data、configurator、templates。
- 生成文件有 managed paths 和 template hashes，用于判断用户是否改过模板。
- `AGENTS.md` 使用 `TRELLIS:START/END` managed block，只替换受管理区，保留用户内容。
- `workflow.md` 的 `[workflow-state:*]` block 作为 managed block 更新，保留其他叙述内容。
- `.trellis/spec/`、`.trellis/tasks/`、`.trellis/workspace/` 被视为用户资产，update 不应覆盖。

对 Loopora 的启发：

- `loopora init codex/claude/opencode` 需要明确哪些文件是 Loopora 管理、哪些是用户资产。
- 生成的 hooks / skills / command 文件需要可升级、可检测冲突、可保留用户编辑。
- `AGENTS.md` 或宿主配置里的 Loopora block 应使用可识别边界，而不是覆盖整个文件。
- Web / CLI / Agent adapter 共享的模板变更需要有升级路径，不能靠用户手动复制。

## 11. Recursion Guard 与 Sub-Agent 风险

Trellis 对 Codex sub-agent 做了很强的递归保护：

- 自定义 agent instructions 明确禁止再 spawn `trellis-implement` / `trellis-check`。
- 子 agent 禁用 Codex multi-agent features，结构上减少自递归和 wait deadlock。
- main session 被要求等待所有 sub-agent 到 terminal status。
- dispatch prompt 必须包含 `Active task: <path>`，作为 hook 失败时的 fallback。

对 Loopora 的启发：

- 如果 Loopora 后续支持让宿主派生子 Agent，必须有“谁能派生、谁不能派生”的结构化边界。
- 子 Agent 不应继承会导致它误判自己也要执行完整 Loop 的上层流程。
- Loopora 注入的上下文胶囊需要区分 main session、role agent、review agent、research agent。
- 不能把“等待子 Agent 完成”交给模型自由发挥；如果需要并行，必须有可观测的完成与失败语义。

这条很重要，但它不是 Agent-first Loopora 的第一落点。第一落点仍应是：当前 Coding Agent 作为执行主体，Loopora 管理 Loop 状态。

## 12. 不应照搬的地方

Trellis 很有参考价值，但它不是 Loopora 的目标形态。

| Trellis 做法 | Loopora 不应照搬的原因 |
| --- | --- |
| 以 PRD/task/workflow 为核心对象 | Loopora 的核心对象是 Loop / bundle / evidence / verdict |
| 主要靠 breadcrumb 和 skill discipline 推进 | Loopora 需要状态机、证据账本和裁决，不应只靠 Agent 自律 |
| 线性 Plan / Execute / Finish | Loopora 需要多轮迭代、role handoff、GateKeeper 和 blocked / rejected / passed 投影 |
| Markdown 是大量流程语义的来源 | Loopora 可以用 markdown 做人类可编辑面，但 Core 应拥有结构化语义 |
| 质量检查偏工程流程 | Loopora 的检查必须绑定 task-specific evidence 和 verdict |
| 没有 Web 观察台 | Loopora 明确需要 Web 作为观察、编辑、历史和控制台 |

压缩判断：

```text
Trellis 是 Agent 工作流治理器；
Loopora 是长期 Agent 任务的 Loop 证据治理器。
```

## 13. 对 Loopora 的具体借鉴清单

Agent-first Loopora 后续设计可优先吸收这些点：

1. `session-scoped active loop`：不要只按 workdir 绑定当前 Loop。
2. `per-turn context capsule`：每轮注入当前 Loop step 的最小治理上下文。
3. `push / pull / manual fallback`：按宿主能力选择 hook 注入、agent 自取或 skill 手动读取。
4. `role-specific context refs`：bundle 里按 role / step 管理 context refs 和 evidence refs。
5. `gen-before-run boundary`：生成候选治理结构和启动执行必须分离。
6. `adapter registry`：codex / claude / opencode 的平台能力、安装路径、生成模板和升级路径要来自同一注册表。
7. `managed block upgrade`：宿主配置、AGENTS、skills、hooks 需要可升级且不覆盖用户内容。
8. `sub-agent recursion guard`：如支持子 Agent，必须区分 main agent 与 role agent 的权限。
9. `runtime visibility`：Web 显示当前 session 绑定、active Loop、step、evidence 和阻断，而不是解析聊天文本。
10. `inline-first option`：默认产品心智可以是当前 Coding Agent 直接执行；子 Agent 只是策略，不是必要模型。

## 14. 对现有 Agent-First 图景的修正

Trellis 让 `agent-first-loopora.md` 里的一个观点更清楚：

```text
Loopora 的关键不是“把 slash command 接到 CLI”。
关键是：slash command 只是入口，Loopora Core 必须能在每轮把当前 Loop 状态投影回 Agent。
```

因此，`/loopora-loop` 不应只做一次启动动作。它应该建立或恢复一个 session-to-loop 绑定，并让后续 Agent 回合能持续拿到当前 Loop capsule。不同平台可以通过 hook、skill、MCP、plugin、手动命令或 agent self-pull 实现这一点。

也就是说：

```text
/loopora-gen 生成治理结构；
/loopora-loop 绑定并启动治理状态；
Loopora capsule 持续把状态带回 Coding Agent；
Web 观察和编辑同一份状态。
```

## 15. 参考源

- `README_CN.md`：产品定位、多平台接入、`.trellis/` 结构。
- `AGENTS.md`：Trellis 管理块、Agent-facing 工作规则。
- `.trellis/workflow.md`：phase、workflow-state blocks、skill routing、inline/sub-agent 模式。
- `.trellis/scripts/task.py`：task lifecycle CLI。
- `.trellis/scripts/common/active_task.py`：session-scoped active task resolution。
- `.trellis/scripts/common/session_context.py`：session context generation。
- `.trellis/scripts/common/workflow_phase.py`：workflow step extraction and platform filtering。
- `.codex/hooks/inject-workflow-state.py`：Codex per-turn breadcrumb injection。
- `.codex/agents/trellis-implement.toml` and `.codex/agents/trellis-check.toml`：pull-based context loading and recursion guard。
- `.opencode/plugins/inject-workflow-state.js` and `.opencode/plugins/inject-subagent-context.js`：OpenCode push-based plugin examples。
- `packages/cli/src/configurators/codex.ts`：Codex adapter install path。
- `packages/cli/src/configurators/index.ts` and `packages/cli/src/types/ai-tools.ts`：platform registry。
- `packages/cli/src/commands/update.ts` and `packages/cli/src/utils/template-hash.ts`：managed update and template hash strategy。
