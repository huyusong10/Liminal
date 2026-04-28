# Web Task Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。Web 对话页的主任务是把用户的长期 AI Agent 任务对齐成外部治理方案，并从 READY 方案进入运行、证据和修订闭环。

## 1. 模块职责

本文档定义 Web 内置的循环方案对齐入口。

它的唯一理由是：

- 让新手用户直接在 Web 里描述需求
- 由后端调用本机 AI Agent CLI 完成多轮治理对齐
- 在生成物通过硬校验后，把方案预览、创建 loop 和运行收敛成一条主流程

它不是：

- 新的 CLI 命令
- 新的 bundle 格式
- 通用聊天系统
- 独立于 `spec / role definitions / workflow` 的第四种运行资产

## 2. 产品判断

Web alignment 要解决的问题不是“少写一段 YAML”，而是让用户不必把任务治理长期维持在 Agent 对话上下文里。

推荐路径是：

`用户描述任务 -> Web alignment session -> 后端 Agent CLI -> YAML bundle -> READY 方案预览 -> 创建循环并运行`

同一能力也承担修订路径：

`已有方案 / run evidence -> Web alignment revision session -> revised YAML bundle -> READY 方案预览 -> 创建循环并运行`

稳定承诺：

- 用户可以完全不理解 Skill 安装、prompt 拼装或外部 Agent 操作。
- 用户也不需要先理解 `bundle / spec / roles / workflow`，但 READY 预览必须让这些治理 surface 可检查。
- 最终产物仍然必须是单文件 YAML bundle。
- READY 只表示 bundle 文件已经存在并通过硬校验，不表示 loop 已经导入或运行成功。
- 外部 Skill 安装路径继续保留，作为高级或跨工具路径。

## 3. Web 入口

Web 只提供一个可视入口，不新增 CLI 能力。

Web 创建入口拆成三条路由：

| 路由 | 职责 |
|------|------|
| `/loops/new` | 兼容旧入口的轻量选择页，解释循环方案对话与手动专家模式的区别 |
| `/loops/new/bundle` | 顶层“新建任务”的默认入口；对话生成循环方案、READY 方案预览与创建运行 |
| `/loops/new/manual` | 右侧资源 / 设置菜单里的专家入口；手动创建 loop，直接选择 spec、workdir、workflow 和运行参数；也承载已有 bundle YAML / 文件导入 |

循环方案对话页首帧采用主流 LLM 对话界面：极简输入框为主，配置和日志只作为按需展开能力。页面默认表达为：

| 控件 | 语义 |
|------|------|
| 左侧历史栏 | 新建对话、最近 alignment sessions；每条历史可删除 |
| 中央 composer | 用户描述需求；默认 placeholder 类似 `你想让 Loopora 做什么？` |
| Composer chips | 选择 workdir、打开 Agent 设置，并展示当前 Agent、workdir 简名和状态 |
| 设置浮层 | 由 chips 打开，必须可关闭，支持点击外部和 Esc 关闭 |

补充规则：

- Workdir 仍是必填运行环境字段，但默认隐藏在轻量 chip 背后的设置浮层里；用户未选择 workdir 就发送时，页面应保留输入内容并打开 workdir 设置提示。
- 模型、推理强度、自定义命令参数属于 Agent 设置，默认隐藏在弹层或抽屉里，不作为独立“高级”入口暴露。
- 执行工具配置语义与角色定义页一致：预设模式只暴露模型与推理强度；自定义命令模式直接维护 CLI 与参数模板，并让模型 / 推理强度成为不可编辑参考；`Custom Command` 只支持自定义命令，OpenCode 默认推理强度为空。
- “已有 bundle YAML / 文件”的导入路径属于 `/loops/new/manual`，不进入对话页，避免把生成式对齐和专家手工导入混在同一 surface。
- 顶层 Web 导航中的“新建任务”直接进入 `/loops/new/bundle`；`/loops/new`、旧 import hash 与手动入口只承担兼容和专家分流，不再是新手主路径。
- 页面文案不应要求用户理解“spec / roles / workflow”才能开始。
- 循环方案对话页必须提供“新建对话”和历史对话入口；历史来自后端 alignment sessions。
- 历史删除只删除 alignment session 及其事件 / 临时 artifact，不删除已经导入的 bundle、loop 或 run。
- 手动创建页不承载 bundle 对齐逻辑，避免把 posture 对话和人工规则编排混在同一个 surface。
- 对话页的滚动边界应稳定：桌面端左侧历史栏和底部 composer 不随主内容滚动，浏览器外层不出现第二条滚动轴，只有右侧对话 / artifact 内容区滚动。
- Composer 中 Enter 默认发送，Shift+Enter 才插入换行，并且输入法组合态不应误触发送。

## 4. Alignment Session

alignment session 是 Web 内置对齐流程的最小状态单元。

它保存：

| 字段 | 作用 |
|------|------|
| session id | Web 对话与后端任务的稳定标识 |
| executor settings | 当前选择的 CLI 工具与高级执行参数 |
| target workdir | bundle 中的目标项目目录 |
| message transcript | 用户消息与 Agent 可见回复 |
| live events | CLI 原始输出和系统状态事件 |
| bundle path | 本 session 期望生成的 bundle 文件路径 |
| validation result | 最近一次 bundle 硬校验结果 |
| alignment stage | 服务端掌控的对齐阶段，不以 Agent 自报为准 |
| working agreement | 最近一次等待确认或已确认的工作协议摘要与 checklist |
| executor session ref | 后端 CLI 原生 session / rollout 引用，用于后续对话继承上下文 |
| linked bundle / loop / run | 导入并运行后关联到现有对象 |
| revision source | 修订模式下的来源 bundle、来源 run、evidence 摘要和 GateKeeper verdict |

Session artifact 必须落在目标 workdir 下，并按事实源、事件流和调试材料分区：

`.loopora/alignment_sessions/<session_id>/`

目录契约：

```text
.loopora/alignment_sessions/<session_id>/
  manifest.json
  conversation/transcript.jsonl
  agreement/current.json
  artifacts/bundle.yml
  artifacts/validation.json
  events/events.jsonl
  invocations/0001/
    prompt.md
    schema.json
    output.json
    stdout.log
    stderr.log
```

单一事实源：

| 文件 | 作用 |
|------|------|
| `artifacts/bundle.yml` | READY bundle 的唯一事实源 |
| `conversation/transcript.jsonl` | 用户与 Agent 对话的唯一文件事实源 |
| `agreement/current.json` | 最近一次工作协议的唯一文件事实源 |
| `artifacts/validation.json` | 当前 bundle 校验结果的唯一文件事实源 |
| `manifest.json` | 轻量索引，只保存状态、路径、时间、摘要和关联 id，不复制 transcript / validation / working agreement |
| `events/events.jsonl` | UI live/recovery 事件流，只保存轻量事件 |
| `invocations/<n>/` | 每次 Agent 调用的调试材料，包括 prompt、schema、结构化输出摘要和 stdout/stderr |

补充规则：

- 新 session 只写上述结构，不再在 session 根目录平铺文件。
- `invocations/<n>/output.json` 不保存完整 `bundle_yaml` 副本；若本轮产生 bundle，只保存 `bundle_path`、`bundle_sha256`、`bundle_written` 和响应摘要。
- `events/events.jsonl` 不是完整调试日志，不能内嵌完整 prompt、schema、bundle YAML 或超长 CLI 命令；完整调试材料通过 `invocation_id` 指向 `invocations/`。
- 旧平铺 session 可兼容读取；首次加载时可迁移到新结构，并把旧文件保留或移动到 `legacy/`，但业务读取只看 canonical 文件。

状态机：

| 状态 | 含义 |
|------|------|
| `idle` | 尚未发送需求 |
| `running` | 后端 CLI 正在执行 |
| `waiting_user` | Agent 已返回澄清问题，需要用户继续回答 |
| `validating` | 检查指定位置的 bundle 文件 |
| `repairing` | bundle 校验失败后自动回灌错误，让 Agent 修复一轮 |
| `ready` | bundle 文件存在且通过硬校验 |
| `failed` | CLI 失败、超时、被取消或自动修复后仍无效 |
| `imported` | bundle 已物化为 Loopora 资产 |
| `running_loop` | 导入后已启动 run |

补充规则：

- 不做版本管理；用户需要重新开始时主动新建 session。
- revision 不是独立聊天系统；它是带有来源上下文的 alignment session。
- revision session 必须把当前 bundle 写入 session `artifacts/bundle.yml` 作为 seed，并在 prompt 中明确这是“修订 harness”而不是从零创建。
- 从 bundle 修订时带入 source bundle id；从 run 修订时还要带入 evidence ledger 摘要和 GateKeeper verdict。
- revised bundle 应作为新 bundle revision 输出，保留 `source_bundle_id` lineage；导入运行仍走现有 bundle 生命周期。
- 页面刷新后应能恢复当前 session 的 transcript、状态和 READY bundle。
- 后续用户回复和自动修复默认继承同一 CLI session；若 provider resume 失败，系统回退到 transcript prompt，并记录可见事件。
- 活动 session 必须能取消；取消应停止子进程并收敛为可解释状态。
- 后端维护独立于运行状态的 alignment stage：`clarifying -> agreement_ready -> confirmed -> compiling -> ready`。Agent 可以提交阶段候选，但不能自己把 session 推进到 confirmed。
- `agreement_ready` 之后，只有用户回复被服务端识别为明确确认时才进入 `confirmed`；否则回到 `clarifying` 并继续对齐。

## 5. Agent 调用

后端调用 Agent CLI 时，不要求目标工具安装 Skill。

系统 prompt 由以下内容装配：

1. `loopora-task-alignment/SKILL.md`
2. `references/product-primer.md`
3. `references/alignment-playbook.md`
4. `references/quality-rubric.md`
5. `references/bundle-contract.md`
6. `references/examples.md`
7. 若是修订或优化，追加 `references/feedback-revision.md`
8. 当前 session transcript
9. 目标 workdir 的轻量只读 snapshot、bundle 输出路径、当前校验结果
10. 输出纪律：若尚需澄清，直接提问；若 bundle 已成形，必须把完整 YAML 放入结构化字段 `bundle_yaml`

稳定规则：

- 这里的 Skill 内容只是 prompt 输入，不是外部工具安装或运行时 Skill 调用。
- Product Primer 必须作为 Web alignment Agent 的首要上下文。它负责说明 Loopora 是外部任务治理 harness、bundle 是 error-control contract、alignment Agent 必须理解完整产品语义，而下游执行角色只需做好本 role 的窄任务。
- Agent 可以进行多轮澄清，但 READY 前必须返回单文件 YAML bundle 的完整文本。
- Agent 不直接写入 session canonical 文件；服务层从结构化 `bundle_yaml` 写入 session `artifacts/bundle.yml`。
- 后端不接受模型自由声明“已经生成好了”作为 READY 依据。
- READY 的唯一依据是指定路径存在 YAML，且通过 `load_bundle_text / normalize_bundle` 与 `spec.markdown` 编译校验。
- 结构化输出包含 `session_ref`；为兼容严格 structured-output 校验，它结构上必填、语义上可空，只接受少量字符串键（如 `session_id / thread_id / conversation_id / provider / raw_json`）。没有原生引用时这些键使用空字符串。服务层会和 executor 捕获到的 session ref 合并保存。
- 结构化输出还包含 alignment phase、readiness checklist 与 readiness evidence。Agent 必须先澄清任务，再给出有证据的 working agreement，等待用户确认，最后才能输出 bundle。服务层会拒绝任何未进入后端 `confirmed` stage 的 bundle 输出，也会拒绝只有 boolean checklist、缺少具体 evidence 的 bundle 输出，并把 session 留在等待用户回复状态。
- readiness evidence 必须说明任务范围、成功面、假完成、证据偏好、角色姿态、workflow 形状和 workdir 事实 / 假设；这些内容是防止弱模型过早生成的后端门槛。
- Custom CLI 通过 `{resume_session_id}`、`{session_ref_json}`、`{alignment_session_id}` 等参数模板占位符接入自己的 resume 协议；不强制要求所有自定义命令实现原生 session。

## 6. 硬校验与自动修复

bundle 检查器必须复用现有 bundle 契约校验。

检查流程：

1. Agent 执行结束。
2. 后端读取结构化输出：`assistant_message`、`needs_user_input`、`bundle_yaml`。
3. 若 `bundle_yaml` 为空，session 进入 `waiting_user` 或 `failed`，取决于 Agent 是否提出了澄清问题。
4. 若 `bundle_yaml` 非空，服务层写入 session bundle path。
5. 对写入的 bundle YAML 运行硬校验，包括 bundle 结构、目标 workdir、`spec.markdown` 可编译性，以及 Web alignment 的语义 linter。
6. 校验通过，session 进入 `ready`。
7. 校验失败，默认把错误、原 YAML 和输出要求回灌给同一 Agent 自动修复一轮。
8. 自动修复仍失败，session 进入 `failed`，并展示可读错误与重试入口。

补充规则：

- 自动修复轮数默认 1 次，避免无限消耗。
- 校验错误展示给用户时应摘要化，原始错误可折叠查看。
- 校验通过后，系统应重新规范化导出 YAML，保证预览与导入消费的是同一份 bundle。
- 若 `loop.completion_mode` 是 `gatekeeper`，硬校验必须要求 workflow 中存在 GateKeeper role 且至少有一个 GateKeeper step 可以 `finish_run`；否则不能进入 READY。
- Web alignment 的语义 linter 至少要求 spec 中包含 Success Surface、Fake Done、Evidence Preferences，workflow 有 task-specific `collaboration_intent`，workflow 使用的 role definition 带 task-scoped `posture_notes`，角色 prompt 表达证据 / 验证 / handoff / blocker 行为，且 GateKeeper 模式具备可阻断并可 finish 的 GateKeeper role。

## 7. LIVE 输出

聊天窗必须反馈 CLI 的实时状态，但不默认铺开原始日志。

可复用现有 run console 的视觉语言：

- Status：系统状态、READY、校验、自动修复、导入运行
- Actions：CLI 命令、工具调用、文件写入、检查动作
- Result：Agent 的自然语言回复、澄清问题、最终摘要

但 alignment session 不是 run：

- 它不创建 loop run record。
- 它不占用 workdir run lock。
- 它可以复用终端组件样式和流式事件机制，但事件对象应归属于 alignment session。
- 默认只显示轻量状态文案，例如 `Codex 思考中 12s`、`正在校验方案`、`正在自动修复`。
- 原始 live events / CLI 输出应放在“执行详情”折叠区里，用户主动展开后再查看。
- 执行详情展开不应让主对话流、composer 或 READY artifact 大幅重新排版；可使用固定高度浮层、抽屉或等价稳定布局。
- 失败卡片应给出下一步动作：继续修复、查看执行详情、调整 Agent 设置；不能只把原始红色错误长期压在页面上。

## 8. READY 方案预览

session 进入 READY 后，页面自动展示循环方案 artifact。

预览面按用户心智命名，而不是优先暴露内部术语：

| 预览区 | 数据来源 | 用户语义 |
|--------|----------|----------|
| 摘要 | metadata、roles、workflow、workdir | 这是一份可以运行的循环方案 |
| 控制摘要 | bundle preview projection | 这套方案主要控制哪些误差、靠什么证据、由谁收束 |
| `spec` | `spec.markdown` | 这次要做什么、什么算完成、哪些假完成不可接受 |
| `roles` | `role_definitions` | 每个 role 在本任务里的完整工作姿态 |
| `workflow` | `workflow.roles / workflow.steps / collaboration_intent` | 谁先做、谁取证、谁裁决、何时收束 |
| 源文件操作 | session bundle path | 可在资源管理器中打开，并在用户手动修改后重新同步 |

补充规则：

- Artifact 默认只展示摘要和主操作；主体只保留 `spec / roles / workflow` 三个稳定视图。
- 控制摘要必须由后端 bundle projection 生成，不能由前端临时猜测；它不是新的事实源，只是把 `spec / roles / workflow` 的误差控制结构投影给用户。
- 中文界面也不翻译 `spec / roles / workflow` 这些 Loopora 专业术语。
- YAML 不作为页面主要预览视图展示；需要时通过“打开源文件”进入资源管理器。
- 若用户手动修改 READY `artifacts/bundle.yml`，页面应提供“重新同步源文件”能力：重新读取、硬校验、刷新 Artifact，并把同步成功或失败写入当前对话 transcript。
- `roles` 视图必须能展开单个 role 的全量信息，再次点击收起。

流程图规则：

- 图中的节点必须来自当前 bundle 的 `workflow.steps`。
- 节点展示对应 role 的用户可读名称和 archetype。
- GateKeeper `on_pass=finish_run` 应可视化为收束出口。
- 图不能按固定 archetype 写死，必须按 bundle workflow 渲染。
- 节点 hover / focus 不应移动图形本体、改变预览区尺寸或推动聊天输入区；角色概要应通过脱离文档流的浮层展示。

- 源文件查看只读即可；继续优化优先通过下一轮对话完成。
- 若用户需要手动改 YAML，应通过源文件操作进入文件系统，并通过“重新同步源文件”回到页面校验；这不是默认新手路径。

手动创建页的已有 bundle YAML / 文件导入也应提供同样的只读预览结构，但它属于专家导入路径，不属于对话页。

## 9. 创建并运行

READY 后提供主操作：

`创建循环并运行`

该操作在实现上必须复用现有 bundle 导入能力，但界面不把“导入”作为新手主概念：

- 从 session bundle path 或规范化后的 YAML 导入
- 物化 bundle、role definitions、orchestration 与 loop
- 若用户选择“创建循环并运行”，立即创建 run 并跳转到 run 详情
- 若只导入，则跳转到 loop 或 bundle 详情

稳定规则：

- 导入后的资产仍属于同一 bundle 生命周期。
- 后续删除、导出、派生、surface 编辑和 revision bump 继续沿用现有 bundle 语义。
- alignment session 只是上游生成入口，不改变 bundle 导入后的生命周期。

## 10. HTTP API

Web alignment 暴露 session 级 API，不新增 CLI interface。

| API | 语义 |
|-----|------|
| `POST /api/alignments/sessions` | 创建 session，可带首条用户需求并立即启动 |
| `GET /api/alignments/sessions` | 返回最近 alignment sessions，用于历史对话列表 |
| `GET /api/alignments/sessions/{id}` | 读取 session、状态、transcript 与校验摘要 |
| `DELETE /api/alignments/sessions/{id}` | 删除非活动 alignment session、事件和临时 artifact |
| `POST /api/alignments/sessions/{id}/messages` | 追加用户回复并继续对话 |
| `POST /api/alignments/sessions/{id}/cancel` | 停止当前活动 CLI |
| `GET /api/alignments/sessions/{id}/events?after_id=` | 轮询 session 事件 |
| `GET /api/alignments/sessions/{id}/stream?after_id=` | SSE live 输出 |
| `GET /api/alignments/sessions/{id}/bundle` | 返回 normalized bundle、YAML、spec HTML、workflow preview 与 validation |
| `POST /api/alignments/sessions/{id}/bundle/sync` | 从 READY `artifacts/bundle.yml` 重新读取、校验并同步到 session transcript |
| `POST /api/alignments/sessions/{id}/import` | 物化 READY 方案，可选择立即启动 run；接口名沿用 import 以复用 bundle 生命周期 |
| `POST /api/bundles/{id}/revise` | 从已有 bundle 创建 revision alignment session |
| `POST /api/runs/{id}/revise` | 从 run evidence 创建 revision alignment session |
| `POST /api/bundles/preview` | 对用户提供的 bundle YAML 或路径做只读校验与预览投影 |

稳定规则：

- 这些 API 归属于 Web 内置入口；不要求 CLI 提供同构命令。
- `GET /api/alignments/sessions/{id}` 返回的 `working_agreement` 可以包含 `readiness_checklist` 与 `readiness_evidence`；旧 session 没有 evidence 时仍可读取，但新 Web alignment 生成前必须具备 evidence。
- `/api/alignments/*/import` 必须复用现有 bundle import 服务，不直接绕过 bundle 生命周期物化底层资产。
- `/api/bundles/preview` 不创建 bundle、loop 或 run；它只复用 bundle 契约校验和预览投影。

## 11. 错误与恢复

用户可理解的错误面至少包括：

| 错误 | 处理 |
|------|------|
| CLI 不存在 | 提示安装或切换工具 |
| CLI 执行失败 | 保留 live 输出，允许重试 |
| Agent 需要澄清 | 进入 `waiting_user`，显示问题并保留输入框 |
| bundle 文件不存在 | 提示 Agent 尚未写出 bundle，可继续对话或重试 |
| bundle 校验失败 | 自动修复一轮；失败后展示摘要错误 |
| 导入失败 | 保留 READY bundle，不清空 session，允许用户修正后重试导入 |

补充规则：

- 失败不得吞掉 session transcript。
- READY bundle 不应因为导入失败而被删除。
- 用户取消活动 CLI 后，应能继续发送新消息重启同一个 session。

## 12. 非目标

- 不新增 CLI 命令。
- 不要求安装 `loopora-task-alignment` Skill 才能使用 Web 内置入口。
- 不做 bundle 版本历史、diff 或回滚。
- 不把 alignment session 变成长期用户人格建模。
- 不让 Agent 在 READY 前直接物化 loop。
- 不让 Web 直接绕过 bundle 导入流程创建底层资产。

## 13. 验收标准

最小可接受版本必须满足：

- 顶层“新建任务”能直接进入循环方案对话页；旧创建入口仍能兼容进入该页面；对话页能从“输入需求”启动 alignment session。
- 聊天窗能实时展示 CLI 输出，并能继续多轮回答。
- 多轮回答默认继承 provider CLI session；不支持或失败时有 transcript prompt fallback。
- Agent 生成的 `bundle_yaml` 必须由服务层写入 session 指定路径。
- READY 只在 bundle 文件存在且硬校验通过后出现。
- READY 后自动展示 `spec / roles / workflow` 与源文件操作入口。
- 用户可以一键创建循环并启动 run；实现仍走 bundle 生命周期。
- 外部 Skill 安装路径仍可用，且不与 Web 内置入口互相依赖。
