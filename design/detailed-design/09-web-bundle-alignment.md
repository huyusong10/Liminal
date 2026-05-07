# Web Task Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。Web 对话页是编排 Loop 的一种默认场景：它把用户的长期 AI Agent 任务对齐成候选 Loop，并从 READY 预览进入运行与证据裁决。

## 1. 模块职责

本文档定义 Web 内置的 Loop 对齐入口。

它的唯一理由是：

- 让新手用户直接在 Web 里描述需求
- 由后端调用本机 AI Agent CLI 完成多轮治理对齐
- 在生成物通过硬校验后，把 Loop 预览、创建 loop 和运行收敛成一条引导路径

它不是：

- 新的 CLI 命令
- 新的 bundle 格式
- 通用聊天系统
- 独立于 `spec / role definitions / workflow` 的第四种运行资产

## 2. 产品判断

Web alignment 要解决的问题不是“少写一段 YAML”，而是帮助用户把未来任务中本来会反复发生的人类判断提前显影，并编排成一个可运行、可观察、可裁决的 human-shaped Loop。

推荐路径是：

`用户描述任务 -> Web alignment session -> 后端 Agent CLI -> YAML bundle -> READY Loop 预览 -> 创建 Loop 并运行`

稳定承诺：

- 用户可以完全不理解 Skill 安装、prompt 拼装或外部 Agent 操作。
- 用户也不需要先理解 `bundle / spec / roles / workflow`，但 READY 预览必须让这些治理 surface 可检查。
- 对话问题必须优先围绕能改变 Loop 形状的 task-scoped judgment：成功面、假完成、证据偏好、残余风险、角色姿态、workflow 形状和信息流。
- 最终产物仍然必须是单文件 YAML bundle；这是候选 Loop 的交换格式。
- READY 只表示 bundle 文件已经存在并通过硬校验，不表示 loop 已经导入或运行成功。
- READY 在默认界面中的主语义是“Loop 已准备好，可以创建并运行”；`bundle`、`import` 和 YAML 只在专家源文件操作或错误调试中出现。
- 外部 Skill 安装路径继续保留，作为高级或跨工具路径。

## 3. Web 入口

Web 只提供一个可视入口，不新增 CLI 能力。

Web 创建入口拆成三条路由：

| 路由 | 职责 |
|------|------|
| `/loops/new` | 兼容旧入口的轻量选择页，解释 Web 问答编排与手动专家模式的区别 |
| `/loops/new/bundle` | 顶层“编排”的默认对话编排工作台；READY 预览与创建运行 |
| `/loops/new/manual` | 编排工作台的手动编排 / 导入方案文件专家入口；直接选择 spec、workdir、workflow 和运行参数；也承载已有 bundle YAML / 文件导入 |

编排工作台采用共享侧栏 + 右侧模式内容的结构。侧栏是稳定上下文，承载新对话、最近 alignment sessions、对话编排、导入方案文件和手动编排入口；右侧模式可以是对话式 composer、方案文件导入预览，或专家手动表单。同一时刻只能展示一个右侧模式，不能把导入表单和手动表单上下堆叠。用户从任一模式都应能直接回到对话编排或最近历史，而不需要重新从顶栏寻找入口。

对话编排模式首帧采用主流 LLM 对话界面：极简输入框为主，配置和日志只作为按需展开能力。页面默认表达为：

| 控件 | 语义 |
|------|------|
| 左侧历史栏 | 新建对话、最近 alignment sessions、三种编排模式入口；对话模式下每条历史可删除 |
| 中央 composer | 用户描述需求；默认 placeholder 类似 `你想让 Loopora 做什么？` |
| Composer chips | 选择 workdir、打开 Agent 设置，并展示当前 Agent、workdir 简名和状态 |
| 设置浮层 | 由 chips 打开，必须可关闭，支持点击外部和 Esc 关闭 |

补充规则：

- Workdir 仍是必填运行环境字段，但默认隐藏在轻量 chip 背后的设置浮层里；用户未选择 workdir 就发送时，页面应保留输入内容并打开 workdir 设置提示。
- 模型、推理强度、自定义命令参数属于 Agent 设置，默认隐藏在弹层或抽屉里，不作为独立“高级”入口暴露。预设模式的模型可留空，语义是继承当前 Agent CLI 默认模型，而不是由 Loopora 固定某个易过期模型名。
- 执行工具配置语义与角色定义页一致：预设模式只暴露模型与推理强度；自定义命令模式直接维护 CLI 与参数模板，并让模型 / 推理强度成为不可编辑参考；`Custom Command` 只支持自定义命令，OpenCode 默认推理强度为空。
- “已有 bundle YAML / 文件”的导入路径属于 `/loops/new/manual` 的导入模式，不进入对话消息流，避免把生成式对齐和专家手工导入混在同一内容面。
- 顶栏 Web 导航中的“编排”一级入口直接进入 `/loops/new/bundle`；Loop 工作台只承载已有 Loop 与运行回访，不重复放置编排模式按钮或目标 / workdir 表单。编排工作台共享侧栏提供 `/loops/new/manual#bundle-import-form` 与 `/loops/new/manual#manual-loop-form` 二级入口；`/loops/new`、旧 import hash 与手动入口只承担兼容和专家分流，不再是新手主路径。
- 页面文案不应要求用户理解“spec / roles / workflow”才能开始。
- Loop 对话页必须提供“新建对话”和历史对话入口；历史来自后端 alignment sessions。
- 历史删除只删除 alignment session 及其事件 / 临时 artifact，不删除已经导入的 bundle、loop 或 run。
- 手动编排模式不承载 bundle 对齐逻辑，避免把 Web 问答编排和人工规则编排混在同一个内容面；但它仍属于同一个编排工作台，以保留回到对话编排和历史对话的路径。
- 对话页的滚动边界应稳定：桌面端左侧历史栏和底部 composer 不随主内容滚动，浏览器外层不出现第二条滚动轴，只有右侧对话 / artifact 内容区滚动。
- 编排工作台是全宽 shell，但不是所有内容都铺满视口：左侧侧栏和历史区利用全宽工作台保持上下文，右侧导入方案文件、手动编排、READY 预览和 artifact surface 仍应使用全站共享页面宽度节奏；对话 composer 和长文本阅读区可以使用更窄的阅读宽度。
- READY 预览、加载失败和源文件错误态必须保持可读横向排版。标题、状态和主操作不能因为 flex/grid 收缩变成逐字竖排；不可执行的主操作必须隐藏或禁用。
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
| working agreement | 最近一次等待确认或已确认的工作协议摘要、checklist 与 readiness evidence，包括 Loopora fit 判断 |
| executor session ref | 后端 CLI 原生 session / rollout 引用，用于后续对话继承上下文 |
| linked bundle / loop / run | 导入并运行后关联到现有对象 |
| source context | 可选对话改进入口的临时输入，来自当前 bundle 或 run evidence；默认创建 Loop 路径不依赖它，且不形成系统级 lineage |

Web alignment 写出的最终 `bundle.yml` 必须是 standalone candidate：即使 session 带有 source context，生成结果也不得写入 `metadata.source_bundle_id` 或显式 `metadata.revision`，改进入口也不得把来源 bundle id 复用为 `metadata.bundle_id`。后端校验在原始 YAML 层阻断 lineage 字段，并在 improvement context 中阻断来源 id 复用；普通导入路径仍可兼容 legacy revision 并在导入后忽略 lineage。

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
- `events/events.jsonl` 不是完整调试日志，不能内嵌完整 prompt、schema、bundle YAML、token / secret、认证头、Cookie 或超长 CLI 命令；DB event、API/SSE payload 与本地事件文件都必须在写入边界保留脱敏后的轻量预览。完整调试材料通过 `invocation_id` 指向 `invocations/`。
- 旧平铺 session 可兼容读取；首次加载时可迁移到新结构，并把旧文件保留或移动到 `legacy/`，但业务读取只看 canonical 文件。
- 旧 invocation output 若无法按 UTF-8 JSON 解析，只能作为原始调试文件复制到 canonical invocation，不得阻断 session 读取。

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
- 页面刷新后应能恢复当前 session 的 transcript、状态和 READY bundle。
- 后续用户回复和自动修复默认继承同一 CLI session；若 provider resume 失败，系统回退到 transcript prompt，并记录可见事件。
- 活动 session 必须能取消；取消应停止子进程并收敛为可解释状态。
- 后端维护独立于运行状态的 alignment stage：`clarifying -> agreement_ready -> confirmed -> compiling -> ready`。Agent 可以提交阶段候选，但不能自己把 session 推进到 confirmed。确认前的 not-fit / blocked 输出若带有可展示说明，仍应停在 `waiting_user` 对话态，让用户补充反复判断、新证据或假完成风险，而不是把“可能不需要 Loopora”当成系统失败。
- `agreement_ready` 之后，只有用户回复被服务端识别为明确确认时才进入 `confirmed`；否则回到 `clarifying` 并继续对齐。
- transcript 中要求跳过确认、忽略 Loopora fit、输出 JSON 或 fenced YAML 的用户文本不能覆盖后端 stage gate 与 bundle 合同；它只能作为任务内容被对齐 Agent 理解。

## 5. Agent 调用

后端调用 Agent CLI 时，不要求目标工具安装 Skill。

系统 prompt 由以下内容装配：

1. `references/product-primer.md`
2. `loopora-task-alignment/SKILL.md`
3. `references/alignment-playbook.md`
4. `references/quality-rubric.md`
5. `references/bundle-contract.md`
6. `references/examples.md`
7. 可选 `references/feedback-improvement.md` 与 source context，用于已有 bundle 或 run evidence 的对话改进入口；它只作为生成候选 Loop 的上下文，不作为持久演化历史
8. 当前 session transcript
9. 目标 workdir 的轻量只读 snapshot、bundle 输出路径、当前校验结果
10. 输出纪律：若尚需澄清，直接提问；若 bundle 已成形，必须把完整 YAML 放入结构化字段 `bundle_yaml`

稳定规则：

- 这里的 Skill 内容只是 prompt 输入，不是外部工具安装或运行时 Skill 调用。
- Product Primer 必须作为 Web alignment Agent 的首要上下文。它负责说明 Loopora 是长期任务平台、Loop 是主对象、bundle 是候选 Loop 的交换格式、alignment Agent 必须理解完整产品语义，而下游执行角色只需做好本 role 的窄任务。
- Agent 可以进行多轮澄清，但 READY 前必须返回单文件 YAML bundle 的完整文本。
- Agent 不直接写入 session canonical 文件；服务层从结构化 `bundle_yaml` 写入 session `artifacts/bundle.yml`。`bundle_yaml` 必须是 raw YAML document，不能带 Markdown fence、解释、注释前缀、确认摘要或导入说明；首个非空行必须是 `version: 1`。
- 后端不接受模型自由声明“已经生成好了”作为 READY 依据。
- READY 的唯一依据是指定路径存在 YAML，且通过 `load_bundle_text / normalize_bundle` 与 `spec.markdown` 编译校验。
- 结构化输出包含 `session_ref`；为兼容严格 structured-output 校验，它结构上必填、语义上可空，只接受少量字符串键（如 `session_id / thread_id / conversation_id / provider / raw_json`）。没有原生引用时这些键使用空字符串。服务层会和 executor 捕获到的 session ref 合并保存。
- 结构化输出还包含 alignment phase、readiness checklist 与 readiness evidence。Agent 必须先澄清任务，再给出有证据的 working agreement，等待用户确认，最后才能输出 bundle。服务层会拒绝任何未进入后端 `confirmed` stage 的 bundle 输出，也会拒绝只有 boolean checklist、缺少 evidence 字段、空泛占位值或明显反模式的 bundle 输出，并把 session 留在等待用户回复状态；服务层不应靠细粒度关键词判断每个 evidence 字段的表达质量。
- 澄清问题必须使用任务风险语言，并默认每轮只问一个最会改变 Loop 形状的问题。若 Agent 在默认 Web alignment 中把问题表述成抽象偏好 / 质量风格调查、是否配置 `Builder`、`Inspector`、`GateKeeper`、`parallel_group`、`workflow.controls` 或 YAML 字段，且没有连接到证据、假完成、风险或阻断语义，或一次抛出多项问卷式澄清，服务层应改写成单个风险取舍问题并记录事件。
- Agent 在展示 working agreement 或输出 bundle 前，应私下彩排一条完整运行路径：Builder 产出候选和 handoff，Inspector / Custom 读取承诺的 handoff 与 evidence，可选 Guide 把 Blocking 或 Unproven 发现转成修复方向，第二轮 Builder 读取该方向，GateKeeper 读取相关 handoff 与 evidence 后裁决，用户能通过 Proven / Weak / Unproven / Blocking / Residual risk 证据桶审计结果。若某一环只靠聊天上下文、角色名或隐含记忆成立，Agent 应继续追问或调整候选 Loop surface。
- Agent 在展示 working agreement 或输出 bundle 前，应私下做一次失败轮次压力测试：假设未来 Builder 产出一个看起来完成但证据弱、覆盖缺失、标准漂移或残余风险不可接受的结果，检查当前 `spec`、角色姿态、workflow、handoff、evidence query 与 GateKeeper 规则是否会暴露、修复或阻断它。若不能，Agent 应继续追问或调整候选 Loop surface，而不是把未受压测的配置交给用户确认。
- Agent 在展示 working agreement 或输出 bundle 前，应私下做 agreement-to-bundle traceability checklist：每个已确认判断项必须落到 `collaboration_summary`、`spec.markdown`、role prompt / posture、`workflow.collaboration_intent`、step `inputs` 或 GateKeeper evidence 规则。只存在于 `agreement_summary`、readiness evidence、transcript 或隐性推理里的判断，不能作为 READY 前的已编译判断。
- readiness evidence 必须覆盖 Loopora fit、任务范围、成功面、假完成、证据偏好、残余风险策略、判断取舍、角色姿态、workflow 形状和 workdir 事实 / 假设，并且在用户确认前显式说明最终证据会如何投影到 Proven / Weak / Unproven / Blocking / Residual risk（中文可用等价语义）。这些字段是后端门槛，但门槛只检查字段存在、非占位、证据桶投影、task-scoped 反模式、open questions 和 workdir fact grounding；具体文字是否充分、是否用了某些关键词、是否以固定句式说明 Loopora fit，不应由正则硬阻断。readiness evidence 的质量主要由 prompt、可见确认摘要和用户确认来治理。`open_questions` 只能为空、无遗留问题或仅等待确认，不能把仍会改变成功面、证据、残余风险、角色或 workflow 的问题藏进 ready agreement。
- 若 Workdir Snapshot 显示 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/`，Agent 不能声称其内容已被观察，除非 snapshot 或对话真的提供了内容；但这些 marker 应被视为项目本地治理入口，并在相关 bundle 中转成角色责任或验证期望。
- `agreement_ready` 也必须满足除 `explicit_confirmation` 以外的 readiness checklist；`explicit_confirmation` 只能由服务端根据用户确认写入，确认前保持 false，确认后同步为 true，不接受 Agent 在确认前自报完成。用户消息同时包含确认与修改 / 调整意图时，必须视为 agreement adjustment，重新进入对齐而不是生成 bundle；但明确表达“不需要修改 / no changes”的确认短语应被视为确认，而不是被连接词误判为修正。
- 用户确认的对象必须是可见工作协议。进入 `agreement_ready` 时，服务层以结构化 `agreement_summary` 和 `readiness_evidence` 生成聊天流中的确认摘要，避免弱模型只把判断模型藏在 JSON 字段里让用户盲确认。若 transcript 中的实质性用户任务或对齐内容明确使用中文，确认摘要、`assistant_message`、服务层生成的阻断 / 改写提示、bundle 阶段的 agreement summary、会被展示的 readiness evidence，以及 bundle 中的 `metadata.name`、`metadata.description`、`loop.name`、`collaboration_summary`、`spec.markdown`、role names / prose 和 `workflow.collaboration_intent` 也必须含中文；纯确认类短消息不改变语言偏好。Loopora 术语可保留原文。服务层应在记录 transcript 前改写不符合语言偏好的 `assistant_message`，并记录语言不匹配事件。
- Workdir Snapshot 只表达用户工作区的轻量观察，不应把 Loopora 自己的 managed state 目录当成项目事实列给 Agent。
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
- Web alignment 生成的 bundle 必须使用 `loop.completion_mode: "gatekeeper"`，让 READY 后的默认运行路径以 evidence-backed GateKeeper verdict 作为任务裁决，而不是只用 rounds 生命周期收束。专家手动编排 / 导入路径可以继续使用其他 completion mode。
- `gatekeeper` 模式下，硬校验必须要求 workflow 中存在 GateKeeper role 且至少有一个 GateKeeper step 可以 `finish_run`；否则不能进入 READY。
- 当 session 使用 command/custom executor 设置时，Web alignment 校验必须要求最终 bundle 的 `loop` 与所有 `role_definitions[]` 保留同一组 executor fields；否则用户在入口选择的运行时会被 bundle 悄悄改写。
- Web alignment 的硬语义 linter 分层处理。硬阻断只覆盖粗颗粒契约：`collaboration_summary` 非占位且提到证据与 GateKeeper 裁决姿态；bundle 把任务裁决证据投影到稳定证据桶 Proven / Weak / Unproven / Blocking / Residual risk（中文可用等价语义）；spec `# Task` 不是通用占位，且存在 `Done When`、Success Surface、Fake Done、Evidence Preferences 和 Residual Risk section；workflow 有非占位 `collaboration_intent`；任何排在 Builder 后的 Inspector / Custom review step 显式读取 Builder handoff 并查询 Builder evidence；Builder / Guide / GateKeeper 的后续步骤显式读取上游 handoff、查询相关 evidence，并在需要跨轮证据时声明 `inputs.iteration_memory`；并行 review 使用不同 `role_definition_key`、同一个上游 handoff，并让 finishing GateKeeper 汇总每个并行 handoff 和对应 evidence；bundle prose 不能声称 Workdir Snapshot 观察到未被 marker 支撑的技术栈、测试套件或构建能力，也不能把 task-scoped judgment 写成全局人格记忆、永久偏好或跨任务用户画像；GateKeeper 模式具备可 finish 的 GateKeeper role。是否用某些词表达判断取舍、role posture 是否包含特定动词、Success Surface / Fake Done / Evidence Preferences / Residual Risk 的句子是否满足某组关键词，不属于硬正则阻断；这些质量要求仍写在 prompt、Skill、rubric 和 working agreement 中，由生成模型、用户确认和运行期 GateKeeper 共同治理。

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
- 默认只显示轻量状态文案，例如 `Codex 思考中 12s`、`正在校验 Loop`、`正在自动修复`。
- 原始 live events / CLI 输出应放在“执行详情”折叠区里，用户主动展开后再查看。
- 执行详情展开不应让主对话流、composer 或 READY artifact 大幅重新排版；可使用固定高度浮层、抽屉或等价稳定布局。
- 失败卡片应给出后续动作：继续修复、查看执行详情、调整 Agent 设置；不能只把原始红色错误长期压在页面上。
- 前端必须从 session status 派生统一执行态；`running / validating / repairing` 同步驱动顶部状态、左侧历史项、主消息流工作中占位、composer 停止动作和执行详情摘要。
- 执行中反馈只能表达真实生命周期和耗时，不得伪造百分比进度；如果后端没有阶段事件，只展示当前阶段与 live event 入口。
- 执行动效应轻量且可降级；在 reduced motion 下保留状态文字、状态点和可停止入口，不依赖动画本身传达语义。

## 8. READY Loop 预览

session 进入 READY 后，页面自动展示 Loop artifact。

预览面按用户心智命名，而不是优先暴露内部术语：

| 预览区 | 数据来源 | 用户语义 |
|--------|----------|----------|
| 流程图 | workflow projection | 谁执行、谁取证、谁裁决，以及 Loop 如何收束 |
| 关键信息条 | metadata、control projection、workdir、session bundle path | 最高风险、证据是否挂载、裁决方式和运行目录 |
| 专家 `spec` | `spec.markdown` | 这次要做什么、什么算完成、哪些假完成不可接受 |
| 专家 `roles` | `role_definitions` | 每个 role 在本任务里的完整工作姿态 |
| 源文件操作 | session bundle path | 可在资源管理器中打开，并在用户手动修改后重新同步 |

补充规则：

- Artifact 默认首屏应直接展示 workflow 流程图和主操作；流程图下方只保留轻量关键信息条，不重复展示图中已表达的执行顺序，也不铺开完整目标、完整风险、完整证据路径或完整源文件路径。
- 控制摘要必须由后端 bundle projection 生成，不能由前端临时猜测；它不是新的事实源，只能被压缩成关键信息条中的少量状态，不再作为一组重复卡片展示。
- 专家 `spec / roles` 入口平铺在 READY artifact 的检查区；默认选中 `spec`，但检查区位于流程图和关键信息条之后，不能抢占首屏决策面。
- 中文界面默认把 `spec / roles / workflow` 展示为“Loop 契约 / 角色 / 流程”；底层字段名只留在专家源文件、API 或调试材料中。
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

手动创建页的已有 bundle YAML / 文件导入也应提供同样的只读预览结构，但它属于专家导入场景，不属于 Web 问答场景。

## 9. 创建并运行

READY 后提供主操作：

`创建 Loop 并运行`

该操作在实现上必须复用现有 bundle 导入能力，但界面不把“导入”作为新手主概念：

- 从 session bundle path 或规范化后的 YAML 导入
- 物化 bundle、role definitions、orchestration 与 loop
- 若用户选择“创建 Loop 并运行”，立即创建 run 并跳转到 run 详情
- 若只导入，则跳转到 loop 或 bundle 详情

稳定规则：

- 导入后的资产仍属于同一 bundle 生命周期。
- 后续删除、导出、复制为候选和 surface 编辑继续沿用现有 bundle 语义；Loopora 不维护 bundle 版本历史、diff 或回滚。
- alignment session 只是上游生成入口，不改变 bundle 导入后的生命周期。
- 方案详情和 run 详情可以创建 user-directed improvement session；兼容路由仍可命名为 `/revise`，但界面语义必须表达为“对话改进方案”或“用证据改进方案”，不得把它描述成默认阶段。

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
| `POST /api/alignments/sessions/{id}/import` | 物化 READY Loop，可选择立即启动 run；接口名沿用 import 以复用 bundle 生命周期 |
| `POST /api/bundles/{id}/revise` | 兼容命名；从已有 bundle 创建可选对话改进 session |
| `POST /api/runs/{id}/revise` | 兼容命名；从 run evidence 创建可选对话改进 session |
| `POST /api/bundles/preview` | 对用户提供的 bundle YAML 或路径做只读校验与预览投影 |

稳定规则：

- 这些 API 归属于 Web 内置入口；不要求 CLI 提供同构命令。
- `GET /api/alignments/sessions/{id}` 返回的 `working_agreement` 可以包含 `readiness_checklist` 与 `readiness_evidence`；旧 session 没有 evidence 或缺少新增 evidence 维度时仍可读取，但新 Web alignment 生成前必须具备完整 evidence，包括 Loopora fit 和残余风险策略。
- alignment session 列表和事件读取接口的分页参数必须有明确上界；事件 `after_id` 必须是非负游标，`limit` 必须是受限正整数，越界请求返回 4xx。
- `/api/alignments/*/import` 必须复用现有 bundle import 服务，不直接绕过 bundle 生命周期物化底层资产。
- `/api/bundles/{id}/revise` 与 `/api/runs/{id}/revise` 是向后兼容的 API 名称；产品语言不得把它们包装成 Loopora 的默认后续阶段，也不得暗示系统会记录候选 Loop 与原 Loop 的演化关系。
- 从 run evidence 创建改进 session 时，source context 是 best-effort 摘要；损坏或不可读的 evidence artifact 只能降级为空摘要，不得阻断 session 创建。
- 改进 session 的 working agreement 必须同时说明 preservation policy 与 feedback-driven delta：哪些稳定任务意图、workdir、executor 默认值或有用角色姿态应保留，哪些 `spec`、`roles`、`workflow`、证据期望或 GateKeeper 严格度应因反馈 / run evidence 改变。若 source Loop 使用非 `gatekeeper` completion mode，Web 对话改进必须把转为 evidence-backed GateKeeper task verdict 明确写成治理 delta，不得静默声称保留来源收束语义。来自 run evidence 的改进必须把 evidence / coverage / GateKeeper verdict 转译为 bundle 变化，而不是只给代码建议。
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
| READY bundle 源文件不可按 UTF-8 YAML 读取 | 预览与同步返回可读 source file 错误；导入失败时保留 READY session 供用户修正后重试 |
| 导入失败 | 保留 READY bundle，不清空 session，允许用户修正后重试导入 |

补充规则：

- 失败不得吞掉 session transcript。
- READY bundle 不应因为导入失败而被删除。
- 后续对话构造 prompt 时，READY bundle 当前内容只是 best-effort context；源文件不可读时必须降级成可读错误摘要，而不是让 alignment worker 失败。
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

- 顶层“编排”和 Loop 工作台入口都能直接进入 Loop 对话页；旧创建入口仍能兼容进入该页面；对话页能从输入启动 alignment session。
- 聊天窗能实时展示 CLI 输出，并能继续多轮回答。
- 多轮回答默认继承 provider CLI session；不支持或失败时有 transcript prompt fallback。
- Agent 生成的 `bundle_yaml` 必须由服务层写入 session 指定路径。
- READY 只在 bundle 文件存在且硬校验通过后出现。
- READY 后自动展示 `spec / roles / workflow` 与源文件操作入口。
- 用户可以一键创建 Loop 并启动 run；实现仍走 bundle 生命周期。
- 外部 Skill 安装路径仍可用，且不与 Web 内置入口互相依赖。
