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
- 把 Codex `/goal`、Trellis task / PRD / workflow 心智写成 Loopora 契约。
- 为尚未实现的平台伪造可运行能力。

## 2. 第一阶段范围

| 平台 | 状态 | 稳定承诺 |
| --- | --- | --- |
| Codex | 已实现 | 安装项目级 Codex skill 入口，提供 `/loopora-gen` 与 `/loopora-loop` 等价触发；底层通过 Loopora CLI/Core 校验 READY bundle 与启动 run |
| Claude Code | 预留 | 类型、状态投影和 Web UI 可显示 coming soon / not implemented；不生成入口文件，不提供可点击安装 |
| OpenCode | 预留 | 类型、状态投影和 Web UI 可显示 coming soon / not implemented；不生成入口文件，不提供可点击安装 |

第一阶段 Codex 选择最稳的当前宿主路径：项目级 skill 文件。Codex 若未提供稳定项目级 slash-command 文件格式，`/loopora-gen` 与 `/loopora-loop` 的用户语义由同名 skill 触发承载；后续可在同一 adapter registry 下增加原生 slash command、hook 或 MCP 入口。

## 3. Entry 语义

### 3.1 `/loopora-gen`

用户语义：

> 把当前 coding 任务、上下文和用户判断编译成候选 Loop。

第一阶段 Codex 路径：

1. Codex skill 读取当前会话中已经可见的任务目标、约束、风险和本地治理入口。
2. Codex 生成候选 bundle YAML。
3. Skill 调用 Loopora CLI adapter entry，把候选 YAML 交给 Core。
4. Core 创建或更新一个 READY alignment session，运行 bundle 结构校验、spec 编译、alignment 语义 linter 与 READY 投影。
5. CLI 确保本地 Web 服务可用，并返回候选 Loop URL。

稳定规则：

- `/loopora-gen` 不启动 run。
- READY 的事实源是 Loopora Core 校验后的 alignment session 和 `artifacts/bundle.yml`，不是 Codex 的自然语言说明。
- Codex 可以生成候选 YAML，但不能自己宣布 READY；READY 只由 Core 校验产生。
- 若宿主入口无法可靠取得完整会话上下文，adapter 可退化为打开 Web alignment 预填入口；该退化必须在结果中暴露为未 READY，不得伪装成可运行 Loop。

### 3.2 `/loopora-loop`

用户语义：

> 用已确认的 Loop 协议启动或推进当前任务。

第一阶段 Codex 路径：

1. CLI/Core 查找当前 Codex session 或 workdir 绑定的 READY alignment session。
2. 若不存在 READY bundle，返回明确错误，提示先运行 `/loopora-gen`。
3. 若 READY session 尚未导入，Core 复用现有 alignment import 路径物化 bundle、Loop、roles 和 workflow。
4. Core 创建或复用 run，并返回 run / Loop URL。
5. 当入口来自 Codex CLI / skill 时，新 run 必须交给现有后台 worker 进程执行，不能依赖即将退出的 CLI 进程内线程。

稳定规则：

- `/loopora-loop` 不从一句话任务直接生成 bundle。
- `/loopora-loop` 不绕过 bundle import、workspace lock、run lifecycle 或 evidence gate。
- 重复调用时返回已绑定 run 的当前状态；非终态 active run 不会被重复创建，同一 workdir 不会静默产生多个活动 run。
- CLI / skill 入口返回 URL 后仍要保证 run 可继续执行；Web 服务内调用可以使用进程内异步执行，短生命周期 CLI 必须使用后台 worker。
- 第一阶段只启动 / 复用 Loopora 管理的 run；持续 per-turn context capsule 与 evidence 回填是后续扩展点。

## 4. Ownership 与安装

Codex adapter 的项目文件分三类：

| 类别 | 路径 | Ownership |
| --- | --- | --- |
| Loopora-managed skill | `.agents/skills/loopora-gen/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Loopora-managed skill | `.agents/skills/loopora-loop/SKILL.md` | Loopora 整文件管理，可由 init/update 替换，可由 uninstall 删除 |
| Loopora manifest | `.loopora/adapters/codex/manifest.json` | Loopora 管理，用于记录模板 hash、版本和已安装文件 |

稳定规则：

- 不覆盖用户已有 `AGENTS.md`、`.codex/config.toml`、`.codex/hooks.json` 或其他宿主配置。
- 安装只写 Loopora 明确拥有的文件；若目标路径存在非 Loopora-managed 内容，安装必须失败关闭并说明冲突。
- 重复安装幂等：当前文件匹配模板时不产生重复内容；旧 managed 模板可升级到当前模板。
- 卸载只删除 manifest 记录或当前模板确认属于 Loopora 的文件；非 Loopora-managed 文件必须保留。
- 卸载后只清理空的 adapter 子目录；不得删除用户 `.agents/`、`.codex/` 或 `.loopora/` 中的其他资产。

## 5. 状态投影

Adapter status 是接口层投影，不是新的业务状态机。

| 状态 | 语义 |
| --- | --- |
| `not_installed` | 没有发现 Loopora-managed Codex adapter 文件 |
| `installed` | manifest 与 managed 文件都匹配当前模板 |
| `needs_update` | manifest 存在且文件缺失，或文件仍可确认是 Loopora-managed 但与当前模板不同 |
| `error` | manifest 损坏、路径冲突、文件被改成无法确认 ownership，或其他无法判断状态 |
| `not_implemented` | 平台预留，第一阶段没有可执行安装能力 |

CLI 和 Web 必须调用同一个 adapter service/helper 获取状态和执行 install/uninstall，避免 Web-only 安装逻辑。

## 6. Web 控制入口

Web Tools 是观察台和控制台，不是新的 Agent 宿主。它可以展示 adapter 状态，并触发与 CLI 相同的安装 / 卸载能力。

稳定规则：

- Web 操作必须显式绑定一个目标项目目录；没有显式输入时可以使用服务进程当前目录作为默认投影，但浏览器 E2E 必须能选择独立临时项目目录来证明真实文件写入边界。
- Web 安装 / 卸载请求只传递目标目录和 adapter kind；实际文件写入、ownership、status 判断仍由 adapter service/helper 负责。
- Web 对 Claude Code / OpenCode 只能展示预留状态，不能提供可执行安装动作。
- Web 不直接生成或删除宿主文件，不读取或修改用户 `AGENTS.md`、`.codex/config.toml` 等配置。

## 7. 验证分层

Agent-first adapter 至少由三层测试保护：

| 层级 | 目的 | 覆盖重点 |
| --- | --- | --- |
| L1 Contract / API | 快速证明公开契约和错误语义 | CLI 幂等安装卸载、managed ownership、不覆盖用户配置、READY binding、`/loopora-loop` 缺 READY 失败、API 状态和未实现平台 |
| L2 Browser / local integration | 用真实浏览器和本地服务证明 Web 用户旅程 | Tools 页选择目标项目、安装 / 状态刷新 / 卸载、冲突错误可见、未来 host 禁用 |
| L3 Real environment | 上线前人工主动运行的最后防线 | 真实 Codex host / slash 或等价 skill 入口能触发 managed entry，并按 `/loopora-gen` 后 `/loopora-loop` 的顺序产生 binding 与 run；真实 `loopora serve` 进程中的 Web Tools 能完成安装 / 更新 / 卸载并展示异常状态 |

稳定规则：

- L1 / L2 是提交前默认质量门槛；L3 是发布或合并到上线分支前的人工 gate。
- L3 可以依赖本机真实 Codex、浏览器和 shell 环境；缺少环境时必须 skip 并给出缺少的显式环境变量或命令模板。
- L3 仍然断言用户可观察结果和落盘资产，不把宿主 CLI 的内部输出格式写成 Loopora 契约。
- L3 Agent 入口测试不得在测试 prompt 中直接给出 `loopora agent codex gen` / `loopora agent codex loop` 的底层命令；这些命令只能来自 Loopora-managed entry 文件。managed entry 应把入口来源写入 Core binding，供测试和排障确认真实入口顺序。
- L3 Web 测试至少覆盖 Codex 的 `not_installed`、`installed`、`needs_update`、`error` 投影和 Claude Code / OpenCode 的 `not_implemented` 预留状态，避免只验证 happy path。

## 8. 依赖边界

依赖方向：

`Codex skill / Web / CLI -> adapter service -> Loopora Core services -> bundle / alignment / run / Web serve`

禁止：

- Web 直接写 Codex adapter 文件。
- Codex adapter 直接创建 run record 或修改 DB。
- Adapter 自己解析或校验 bundle 契约。
- Adapter 为 Claude Code / OpenCode 生成假入口。

## 9. 后续扩展点

- Codex 原生 slash command 文件格式稳定后，可在 Codex adapter registry 中新增 `.codex/commands/*`，仍由 manifest 管理。
- Codex hook 或 MCP 能提供稳定 session identity 后，binding key 应优先使用宿主 thread/session id，而不是 workdir fallback。
- per-turn context capsule 应从 run / step / evidence 事实源生成，并由宿主 hook、skill self-pull 或 MCP tool 注入 Codex。
- Evidence / handoff 回填应成为受限动作：Coding Agent 可以提交当前 step 产物，但不能任意改写 Loop 生命周期或 GateKeeper 裁决。

## 10. 变更触发

以下变化需要更新本文档：

- 新增或删除支持的平台。
- Codex adapter 从 skill fallback 改为原生 slash command、hook 或 MCP。
- managed 文件 ownership 或 manifest 机制变化。
- `/loopora-gen` 与 `/loopora-loop` 的 READY / run 边界变化。
- context capsule 或 evidence 回填进入可运行第一路径。
- L1 / L2 / L3 验证责任迁移。

以下变化通常不需要更新本文档：

- skill 文案调整。
- Web 卡片布局调整。
- manifest 字段的非破坏性扩展。
