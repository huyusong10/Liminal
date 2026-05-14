# Agent-First Loopora Requirement

## 1. 文档定位

本文记录当前已经进入产品契约的 Agent-first 图景：

`Coding Agent 作为主入口和执行主体，Loopora 作为上层 Loop 编排与治理系统，Web 作为观察、编辑和控制台。`

它不是某个宿主的实现说明，不把 slash command、plugin、hook、MCP、skill、扩展协议或某个 Coding Agent 的临时能力写成产品本质。已落地的接口、ownership、context capsule、evidence 回填和验证责任见 `../detailed-design/10-agent-adapters.md`，跨入口语言与 Web/CLI/API 边界见 `../detailed-design/05-interfaces.md`。

本文优先回答：

- 用户为什么应该从 Coding Agent 进入 Loopora？
- Coding Agent、Loopora CLI/Core 和 Web 分别承担什么心智角色？
- `/loopora-gen` 与 `/loopora-loop` 应该表达什么产品语义？
- 当 Coding Agent 成为执行主体时，Loopora 还必须守住哪些治理边界？

## 2. 背景判断

Loopora 当前的核心价值不是一个独立 Web 应用，也不是一组 prompt 模板，而是把长期 AI Agent 任务中的反复判断、纠偏、取证和阻断编排成可运行的 human-shaped Loop。

用户做 coding 任务时，天然已经处在 Coding Agent 中。若要求用户先离开 Coding Agent，再到额外 Web 入口里重新描述任务、编排 Loop、启动运行，会增加明显心智负担：

- 用户需要在两个工作入口之间切换。
- 用户需要重新判断“现在该问 Agent，还是该打开 Loopora？”
- Web 成为默认起点时，Loopora 容易被理解成另一个任务管理工具，而不是 Coding Agent 工作流里的治理层。

更自然的产品心智是：

> 我正在使用 Coding Agent 做一项长期或高风险任务；当我担心假完成、证据不足、标准漂移或需要多轮判断时，我用 `/loopora-gen` 把这件事编译成 Loop，再用 `/loopora-loop` 让当前 Coding Agent 在这个 Loop 协议下推进。

因此，Agent-first 不是把 Loopora 缩减成 prompt pack，而是把 Loopora 放到用户已经工作的入口之上。

## 3. 目标图景

Agent-first Loopora 的稳定产品结构是：

```text
Coding Agent = 用户主入口 + 任务执行主体
Loopora CLI/Core = Loop 状态机 + 配置/契约管理 + 上下文注入 + 证据/裁决事实源
Web = 观察台 + 专家编辑器 + 历史与资源控制台
```

这三者不是替代关系，而是交织关系：

- 用户可以完全通过 Web 完成编排、运行、观察和编辑。
- 用户也可以在 Coding Agent 中用 slash command 触发编排和启动 Loop。
- 不管入口来自 Web 还是 Coding Agent，后台都必须走同一套 Loopora CLI/Core 语义，避免出现双重产品模型。
- Web 不再必须是默认入口；它是可随时打开的状态、证据、配置和专家操作界面。

## 4. 核心用户路径

### 4.1 先生成，再运行

Agent-first 的默认路径必须坚持：

`/loopora-gen -> Web 预览 / 审查 / 可选编辑 -> /loopora-loop`

`/loopora-loop` 不应在缺少已生成候选 Loop 的情况下直接把一句话任务自动编译并运行。这个约束保护 Loopora 的核心价值：

- 运行前必须有可审查的 bundle / Loop 治理结构。
- 用户应能在 Web 中查看、审查或修改候选 Loop。
- 运行不是“再问一次 Agent”，而是进入一个已编译的判断协议。

### 4.2 `/loopora-gen`

`/loopora-gen` 的用户语义是：

> 把当前 coding 任务、上下文和用户判断编译成候选 Loop。

它应该完成：

- 捕捉当前任务目标、约束、风险和用户关心的假完成模式。
- 生成或更新候选 bundle。
- 让 Loopora Core 完成校验、诊断和 READY 判断。
- 拉起或复用本地 Web 服务。
- 返回候选 Loop 的 Web URL，让用户查看、审查或修改。

`/loopora-gen` 不默认启动 run。

### 4.3 `/loopora-loop`

`/loopora-loop` 的用户语义是：

> 用已审查或已接受的 Loop 协议启动或推进当前任务。

它应该完成：

- 找到当前 workdir / 当前会话关联的 READY bundle 或已导入 Loop。
- 若不存在可运行 Loop，提示用户先运行 `/loopora-gen`。
- 启动 Loopora 管理的 Loop 状态。
- 让 Coding Agent 在当前 Loop step 的治理上下文中执行任务。
- 拉起或复用本地 Web 服务。
- 返回 run / Loop 的 Web URL，方便用户查看状态、证据和裁决。

当前 Agent-first 路径不维护一个独立的“已确认 preview”持久状态。Core 强制的是 READY 校验和当前会话 / workdir 绑定；用户在 Web 中审查或调整候选后主动调用 `/loopora-loop`，就是接受该 preview 进入运行的动作。若后续引入硬确认状态，必须同步改变 adapter 合约、Web 流程和测试。

`/loopora-loop` 不要求 Web 作为执行主界面。用户从 slash command 启动后，Web 通常只是观察台；控制和专家编辑能力仍然存在，但不应强行打断 Coding Agent 里的工作流。

## 5. Coding Agent 的角色

在 Agent-first 图景中，Coding Agent 不是薄入口，也不只是对话和展示层。

Coding Agent 是实际执行主体：

- 读取代码和本地规则。
- 修改工作区。
- 运行测试、构建、检查和其他工具。
- 与用户对话并解释当前执行过程。
- 在 Loopora 注入的当前 step 语境下扮演 Builder、Inspector、Guide、GateKeeper 或任务专属角色姿态。

Loopora 不应该强行规定 Coding Agent 在聊天里如何排版、如何描述思路、如何展示执行过程。Agent 的自然执行流仍属于宿主 Coding Agent。

Loopora 需要约束的是：

- 当前属于哪个 Loop、iteration、role 和 step。
- 当前 step 要证明或交接什么。
- 当前 step 应遵守哪些行动边界。
- 当前 step 必须如何留下 handoff、evidence 或 artifact refs。
- 什么时候可以推进到下一个 step。
- GateKeeper 是否有足够证据给出 task verdict。

换句话说：

```text
Loopora 不运行 Agent。
Loopora 运行 Loop 状态。
Coding Agent 运行任务。
```

## 6. Loopora 的角色

Agent-first 不削弱 Loopora 的核心边界。相反，Loopora 必须从“执行器调度者”收敛成更清晰的“Loop 协议治理者”。

Loopora 负责：

- 管理 bundle、spec、roles、workflow、prompt / markdown 资产。
- 维护 Loop、run、iteration、step、handoff、evidence、verdict 的事实源。
- 在合适阶段向 Coding Agent 注入当前 Loop 上下文。
- 校验候选 bundle 是否能表达 task-scoped judgment。
- 维护 READY、running、blocked、rejected、passed 等状态投影。
- 记录 evidence ledger、coverage、artifact refs 和 GateKeeper 裁决。
- 区分 run lifecycle 与 task verdict。
- 把 Web 和 Coding Agent 入口统一到同一套底层语义。

Loopora 不负责：

- 替代 Coding Agent 的普通工具执行体验。
- 规定 Coding Agent 的聊天输出格式。
- 把所有状态塞进 Agent 对话框。
- 把 Web 做成强制起点。
- 让用户一开始理解全部内部字段。

## 7. Web 的角色

Web 在 Agent-first 图景中仍然是完整产品面，但它的默认心智从“唯一主入口”调整为：

```text
观察台 + 专家编辑器 + 历史和资源控制台
```

Web 必须能完整承担：

- 查看有哪些 Loop 正在运行。
- 查看历史 Loop、run、evidence、verdict。
- 查看和编辑 bundle、spec、roles、workflow。
- 处理 READY 预览、diagnostics、traceability 和专家修改。
- 停止 run、查看阻断、接受结果、导出 bundle。
- 在用户选择 Web-only 路径时，一站式完成编排和运行。

当用户从 Coding Agent 的 slash command 启动 Loop 时，Web 默认只是观察和审计入口。用户可以打开 URL 看大概状态，也可以在需要时进入专家编辑或控制动作，但不应被迫从 Web 继续主流程。

## 8. CLI/Core 的角色

所有入口都应复用同一套 Loopora CLI/Core 语义。

产品上可以理解为：

- Coding Agent 调用 Loopora CLI/Core。
- Web 调用 Loopora CLI/Core 或同等服务边界。
- CLI/Core 负责本地服务的拉起、复用和状态一致性。

用户不应需要先手动启动 Web 服务。发起 `/loopora-gen` 或 `/loopora-loop` 时，系统应自动确保本地 Loopora 服务可用：

- 已有可用服务时复用。
- 没有服务时后台拉起。
- 默认端口不可用时选择可用端口。
- 返回用户可打开的 Web URL。

初始化入口应表达为“把 Loopora 接到这个 Coding Agent 里”，而不是暴露宿主扩展细节。概念上可以是：

```text
loopora init codex
loopora init claude
loopora init opencode
```

这些命令的产品语义是安装或更新对应 Coding Agent 入口，使用户能在该环境里使用 `/loopora-gen` 和 `/loopora-loop`。具体如何落地不属于本文范围。

## 9. Loop 上下文胶囊

Agent-first 的关键不是“注入关键词”，而是注入一个状态化的 Loop 上下文胶囊。

每次 Coding Agent 需要在 Loopora 管理下推进时，Loopora 应提供一个当前 step 的治理上下文。它至少应表达：

| 内容 | 用户语义 |
| --- | --- |
| 当前 Loop | 这次任务受哪份治理结构约束 |
| 当前 iteration | 这是第几轮，为什么进入这一轮 |
| 当前 role / step | 现在应该构建、取证、引导还是裁决 |
| 当前目标 | 本 step 要推进或证明什么 |
| 行动边界 | 当前是否允许改工作区、是否只读、是否可以裁决 |
| 输入范围 | 应读取哪些上游 handoff、evidence、上一轮记忆 |
| 输出义务 | 必须留下哪些 handoff、evidence、artifact refs 或 blocker |
| 推进条件 | 什么情况下可以进入下一步或结束 |
| Web URL | 用户可在哪里查看完整状态 |

Coding Agent 可以自由组织执行过程，但如果要推进 Loopora 状态，就必须把本 step 的结果回填到 Loopora 的事实源。

## 10. 变更归因与证据挂载

当 Coding Agent 是执行主体时，工作区写入不是异常情况，而是 Loopora 预期的一部分。真正需要治理的不是“是否写文件”，而是：

> 工作区变化是否能归因到某个 Loop step，并且是否被挂载到 evidence / handoff / artifact。

Agent-first 的风险模型应从“禁止外部写入”调整为“未归因变化不得伪装成强证据”。

稳定规则：

- Builder 或获得写权限的 step 可以修改工作区，但应留下 handoff 和必要 artifact refs。
- Inspector、Guide、GateKeeper 默认不应把自己的判断和工作区写入混在一起。
- 如果出现无法归因到当前 Loop step 的改动，Loopora 应把它记录为外部贡献、未归因变化或需要用户确认的风险。
- GateKeeper 不应把未归因变化当成强证据。
- 用户可以在 Web 中查看这类变化，并选择吸收、停止、重新运行或继续但保留风险。

这个规则保护的是 Loopora 的核心可信度：

```text
不是所有变化都必须由 Loopora 独占产生；
但最终通过必须能解释哪些变化被谁产生、如何证明、由谁裁决。
```

## 11. 证据与裁决

Agent-first 不能把 Loopora 降级成“提醒 Agent 多检查一下”。

即使 Coding Agent 是执行主体，Loopora 仍必须拥有：

- 结构化 handoff。
- evidence ledger。
- artifact refs。
- coverage / proof projection。
- GateKeeper verdict。
- task verdict。

GateKeeper 可以由同一个 Coding Agent 在不同 step 姿态下完成，但 GateKeeper 通过不能只依赖自然语言信心。Loopora 必须保留 evidence-backed closure 的原则：

- 通过要能引用支持性 evidence。
- required evidence 缺失时不能强通过。
- residual risk 必须显式可见。
- run status 不能替代 task verdict。

## 12. 用户心智

Agent-first Loopora 的用户心智应尽量简单：

```text
我在 Coding Agent 里工作。
任务需要治理时，先 /loopora-gen 生成 Loop。
我去 Web 看一眼候选 Loop，必要时改一下。
然后 /loopora-loop 让 Agent 在这个 Loop 下推进。
Web 随时可看状态、证据、历史和细节。
```

这个心智比 Web-first 更轻，因为用户不用离开当前 coding 工作流来决定是否使用 Loopora。Web 像 CI 页面、Actions 页面或部署观察页：它很重要，但不一定是用户发起动作的地方。

## 13. 非目标

Agent-first 不意味着：

- 把 Loopora 做成宿主 Coding Agent 的普通 prompt pack。
- 让宿主会话上下文成为唯一事实源。
- 删除 Web。
- 删除 CLI。
- 让 `/loopora-loop` 跳过 `/loopora-gen` 直接执行一句话任务。
- 把所有观察、编辑和诊断都塞进聊天框。
- 要求不同 Coding Agent 的体验完全一致。
- 用 Loopora 替代宿主 Coding Agent 的正常执行流。

## 14. 与现有设计的关系

历史上，Web alignment 是默认对话编排入口，CLI 是自动化和专家入口。当前 README 已把 Coding Agent 入口提升为 coding 场景的推荐 first-use path，因此稳定关系调整为：

- Web 仍可一站式完成所有能力。
- Web 不再必须是默认发起入口。
- Coding Agent slash command 成为 coding 场景下更自然的主入口。
- CLI/Core 成为 Web 和 Coding Agent 的共同底座。
- Agent-first 候选入口、Web 对话编排、手动编排和 YAML 导入都必须进入同一套 Core 校验、READY 预览、bundle 导入、run/evidence/capsule 语义。
- Loopora 的稳定职责从“调度底层 Agent CLI 执行每个 role”收敛为“管理 Loop 状态并向执行主体注入当前治理上下文”；明确 headless run 才使用 executor 子进程。

若后续宿主能力改变，优先更新 `10-agent-adapters.md`、`05-interfaces.md`、`06-workflow-and-prompts.md`、`07-observability-and-diagnostics.md` 和相关 contract / real probe，而不是把这里退回成 Web-first 或 prompt-pack 图景。

## 15. 待进一步演进的问题

第一阶段已回答 READY 绑定、agent-native run、context capsule、host dispatch proof、evidence 回填和多宿主安装 ownership；后续演进仍需持续收敛：

- `/loopora-gen` 如何更可靠地从不同 Coding Agent 当前上下文取得任务材料，而不把宿主会话当成唯一事实源？
- `/loopora-loop` 遇到多个候选 Loop 或 Web 修改后的候选时，如何让用户选择而不增加默认心智负担？
- 变更归因如何对用户可见，哪些情况必须阻断 GateKeeper 通过？
- Web 修改 bundle 后，Coding Agent 侧如何感知最新确认版本？
- 各宿主的 per-turn 注入、subagent / task agent 能力和真实 session identity 如何在不破坏 Core 契约的前提下继续增强？

## 16. 参考资料

- `codex-goal-reference.md` 记录 Codex `/goal` 的持久目标、受限模型工具、自动续跑和 TUI 状态面机制。该文档只作为外部机制参考，不构成 Agent-first Loopora 的产品契约。
- `trellis-agent-orchestration-reference.md` 记录 Trellis 的 Agent-first、本地编排、多平台 adapter、session-scoped active task 和 per-turn workflow breadcrumb 机制。该文档只作为外部实现参考，不构成 Agent-first Loopora 的产品契约。
- 第一阶段 Codex、Claude Code、OpenCode adapter 的实现边界、managed 文件 ownership 和 `/loopora-gen` / `/loopora-loop` 接口落点见 `../detailed-design/10-agent-adapters.md`。
