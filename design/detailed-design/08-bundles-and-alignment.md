# Bundles And Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。bundle 是 Loop 的内部交换单元；它必须承载可运行的长期任务编排，而不是退化成裸 YAML 或角色配置包。

## 1. 模块职责

本文档定义三条稳定边界：

- Agent-first `/loopora-gen` 如何把当前 Coding Agent 任务提交为候选 human-shaped Loop。
- Web alignment 如何作为一种场景，把当前任务的人类判断收敛成候选 human-shaped Loop。
- Loopora 如何消费 bundle 并把它物化为可运行 Loop 资产。

它不定义具体对话话术，也不定义某个 provider 的调用细节。

## 2. 核心分工

| 边界 | 负责方 | 稳定职责 |
|------|--------|----------|
| Agent-first 候选入口 | Coding Agent entry + Loopora Core | 宿主 Agent 基于当前任务生成候选 YAML，Core 记录候选来源、校验为 READY，并返回 Web 预览 URL |
| Web 任务访谈与对齐 | Web alignment session | 后台 Agent 主导语义对话，与用户确认成功面、假完成、证据、风险和判断方式，把未来纠偏提前为候选 Loop |
| Web bundle 生成 | Web alignment session | 在后端阶段门槛承认 working agreement 后，输出单文件 YAML bundle |
| bundle 生命周期 | Loopora 本体 | 导入、导出、派生、删除，并把 bundle 物化为本地 Loop 资产 |
| run 执行 | Loopora 本体 | 从 Loop 的 `spec / role definitions / workflow` 推进状态、handoff、证据和裁决；Agent-first 使用宿主 Agent 执行 step，显式 headless 路径才调用 executor 子进程 |

稳定规则：

- `working agreement` 是编译期中间产物，不是运行期资产。
- Alignment 必须先判断 Loopora fit：这次为什么需要可运行治理 Loop，而不是一次 Agent 执行加一次人工 review、直接聊天 / 直接回答、一次性任务处理或 benchmark-first 简单循环。默认对话不应把 `Loopora fit` 当成用户术语，而应用普通任务语言给出推荐判断和可选路径。
- Loopora 不执行独立 agreement 文件。
- 最终运行输入仍然是 `spec / role definitions / workflow / loop`。
- Agent-first entry 是 coding 场景的推荐 first-use path；Web alignment 是完整 Web-only 对话编排路径；YAML 导入 / 导出仍是专家交换格式。三者都必须进入同一 Core bundle 校验、READY 预览、导入和 run/evidence 语义。
- 通用外部 alignment Skill 不替代 Loopora Core。宿主 Agent 可以生成候选 YAML，但 READY、导入、run 绑定、context capsule、evidence ledger 和 task verdict 都只能由 Core 产生。
- Web compiler 的对话由后台 Agent 主导，阶段承认由 Loopora 后端负责；Agent 可以提出阶段候选，后端只接受满足当前 compiler gate、working agreement 和 bundle 校验的结果。

## 3. Bundle 契约

bundle 是可读、可运行、可导出、可重新导入的 Loop 交换单元。

它至少包含：

| 区域 | 作用 |
|------|------|
| metadata | 名称、描述和可选标识；不承载系统级演化历史 |
| collaboration summary | 本次 Loop 编排结构的可读摘要 |
| loop | workdir、运行参数和 loop 入口 |
| spec | task contract |
| role definitions | 角色模板、task-scoped 判断姿态与证据责任 |
| workflow | 角色顺序、步骤结构、handoff、evidence query、`collaboration_intent` 与可选误差控制触发器 |

README 这类 first-use 文档可以把方案文件解释为任务契约、Agent 责任、执行策略、运行流程、证据规则和裁决规则这些判断面；默认用户路径应说方案文件结构与运行流程，不把 YAML 校验或 workflow 机制当作默认主语。bundle YAML 不能因此新增新的运行期事实源。它们分别落到 `spec`、`role definitions`、`spec / role definitions / workflow` 的优先级语言、`workflow`、workflow evidence query / runtime evidence，以及 GateKeeper / finish 语义和证据支持的 Loop 裁决投影。

校验规则：

- bundle 顶层 `version` 目前只支持整数 `1`；缺失或空值可按当前版本处理，但显式 `0`、布尔值、小数、非数字或未来版本必须失败关闭，不能被默认值覆盖。
- 受控候选入口的最终产物必须是 raw YAML document，首个非空行必须是 `version: 1`，而不是 fenced Markdown、解释性回答、注释前缀或 confirmation summary。用户可见协议是编译期对话面，不能被混进最终 bundle 文本。
- legacy `metadata.revision` 若存在，必须是正整数；Loopora 可以在导入后忽略 lineage/revision 历史，但不得把非法显式值静默改成默认值。
- `metadata.bundle_id` 与 `metadata.source_bundle_id` 若显式存在，必须是安全字符串标识；布尔值、数字、对象、路径分隔符或 `..` 不能被 `str()` 隐式转成持久化 bundle 身份或本地目录路径。replace/import 目标 id 也使用同一边界。
- `spec.markdown` 必须能通过 Loopora 正常 spec 编译器。
- `loop` 运行参数必须满足与普通 Loop 创建相同的 executor、completion、有限值、整数性和范围边界；未知 executor kind / mode、custom preset mode、缺少 command 参数、非法 reasoning effort、计数、重试次数和窗口类 YAML 小数都必须在 bundle 预览 / READY 校验时失败关闭，不能等到导入创建 Loop 时才暴露。`role_definitions[]` 未显式提供 executor 字段时必须继承 normalized loop executor defaults，不能把 Claude / OpenCode / custom Loop 在角色执行面悄悄改回 Codex。
- Web alignment 和 Agent-first 生成的默认候选 bundle 必须使用 `gatekeeper` completion mode，使 Loop 裁决来自证据和 GateKeeper 判断，而不是只来自 run 生命周期收束；专家手动导入仍可使用受支持的 `rounds`。`completion_mode` 只接受 `gatekeeper` / `rounds`，未知、布尔或数字值必须失败关闭，不能被当成非 GateKeeper 路径或默认值。
- Web alignment 和 Agent-first 生成的新候选 bundle 必须省略 `metadata.source_bundle_id` 与显式 `metadata.revision`；改进入口还不得把来源 bundle id 复用为 `metadata.bundle_id`。来源 bundle、run evidence 与反馈只作为对话期输入，不写成系统级 lineage 或候选身份。
- `gatekeeper` completion mode 必须包含可 `finish_run` 的 GateKeeper step。
- 最终 bundle 的治理文本不能与 Loopora fit 自相矛盾：若候选文件声称单轮 Agent、一次 Agent + human review、直接聊天 / 直接回答、一次性任务无需 Loop、后续轮次不会产生新证据、稳定 benchmark、proof harness、测试套件或 benchmark/test-harness-only 路径已经足够，就不能同时被 Core 当作 human-shaped Loop 候选接受。
- Web alignment 和 Agent-first 生成的 bundle 必须额外通过语义 linter，但 linter 只承担粗颗粒护栏职责：结构 section 是否存在、raw YAML / metadata / completion mode 是否合约正确、`collaboration_summary` 是否保留多轮 Loopora 治理理由而不是只讲一次性执行、workflow handoff 与 evidence query 是否断链、需要跨轮取证或修复的 review / Guide / Builder 是否保留上一轮 GateKeeper summary、Residual Risk 是否只是“有些风险可以留下”这类不可管理占位、是否出现全局人格记忆等明确反模式。具体表达是否“足够好”、某个判断是否用了特定词汇、role posture 是否符合某组动词，不应靠正则硬阻断；这些属于 prompt 指导、Web working agreement 或 Agent 入口提示、用户确认和后续人工 / GateKeeper 判断。
- Web alignment 和 Agent-first 生成的 `workflow.collaboration_intent` 必须说明证据如何流动、GateKeeper 如何收束，以及证据薄弱、偏差或假完成会在哪里尽早暴露；只有顺序和角色名不足以证明 Loop 是 human-shaped。
- Web alignment 在交付 working agreement 或 bundle 前，应私下彩排一条完整运行路径：Builder 产出和 handoff、Inspector / Custom 取证、可选 Guide 修复方向、第二轮 Builder、GateKeeper 裁决和用户证据审计，都必须能通过显式 handoff、evidence query、角色姿态和证据桶串起来；否则应继续对齐或调整候选 Loop。
- Web alignment 在交付 working agreement 或 bundle 前，应私下用一个可能的失败轮次压测候选 Loop：看似完成但证据弱、覆盖缺失、标准漂移或残余风险不可接受的结果，必须能被 `spec / roles / workflow / evidence` 暴露、修复或阻断；否则应继续对齐或调整候选 Loop，而不是交付 YAML。
- Web alignment 在交付 working agreement 或 bundle 前，应私下完成 agreement-to-bundle traceability checklist：用户已确认的 Loopora fit、任务范围、成功面、假完成、证据偏好、执行策略、残余风险、本地治理责任、判断取舍、角色姿态和 workflow 判断，都必须能映射到 `collaboration_summary`、`spec.markdown` / `Role Notes`、role prompt / posture、`workflow.collaboration_intent`、step `inputs`、workflow controls 或 GateKeeper evidence 规则；其中本地治理责任不能只停留在 `collaboration_summary`，必须进入 `spec.markdown` 的 `Role Notes`、role prompt / posture、`workflow.collaboration_intent`、step `inputs`、workflow controls 或 GateKeeper evidence 规则这类运行面。若某项只存在于 `agreement_summary`、readiness evidence、transcript、metadata / loop 名称或隐性推理中，应继续对齐或调整候选 Loop。后端校验应使用已确认 working agreement 作为锚点，检查任务特异判断是否出现在最终 bundle 的治理 surface 中；对成功结果、假完成、证据偏好、执行策略、残余风险和判断取舍，校验还应保留类别语义，不能因为少量对象词命中就放过 notification、audit、permission、owner / follow-up 等已确认类别的丢失。bundle 自身的 traceability projection 只能证明候选文件内部有 surface，不能替代这道编译边界。
- Web alignment 的 working agreement readiness 必须把执行策略作为独立证据面，而不是藏进 workflow 形状或判断取舍：当下一轮应先构建、取证、修根因、收窄范围、扩展功能或暂缓打磨会影响运行结构时，`execution_strategy` 必须在确认前可见，并在 bundle surface 中可追溯。
- Web alignment 必须结合主动注入与被动检测：每轮 prompt 注入当前 compiler gate、候选阶段和输出纪律；后端只把通过 stage gate、readiness evidence、traceability、语义 linter 与 bundle 校验的结果承认为下一阶段。
- READY 只绑定最后一次通过校验的 bundle 内容；READY 预览、导入或 Agent-first `/loopora-loop` 启动前必须重新读取当前 canonical `bundle.yml` 并执行同一套语义校验。若 `bundle.yml` 在 READY 后被人工或宿主改坏，不能沿用旧 ready 状态继续展示为可审查、可导入或可运行；若当前文件仍可通过校验并被导入 / 运行，alignment validation 与 Agent binding 必须记录这次实际规范化文件的哈希和字节数，不能保留旧预览内容的运行 provenance。
- 方案预览和导入校验应提供非阻断 bundle diagnostics projection，用于暴露旧 bundle 或弱 workflow 的迁移风险，例如显式 Guide 没有读取上游 handoff / evidence、finishing GateKeeper 没有 evidence fan-in、并行检视后的 GateKeeper 没有读取每条 peer review handoff / evidence、review 后的 Builder 未读取 review handoff、执行策略或判断取舍没有进入 `collaboration_summary` / `spec` / 角色 posture / `workflow`，本地治理责任没有进入 `Role Notes` / 角色 prompt / posture / `workflow` 等运行面，或其他 traceability 缺口。control summary 应把成功面、假完成风险、证据偏好、执行策略、判断取舍、残余风险策略与本地治理责任作为独立投影项展示，不能只把它们混进通用协作摘要、主要风险摘要、证据标题或 workdir marker 名称；role posture 只有角色责任、姿态或 prompt 内容可见时才算映射，角色名、archetype 或编号本身不能证明人的判断已进入角色执行面；其中残余风险策略只有命名可接受风险及其负责人 / 跟踪 / 后续 / 接受路径，或明确失败关闭时才算已映射，`Some risk is fine` 这类空泛策略只能作为 warning 和 traceability 缺口出现；本地治理责任的预览卡片只展示已形成 Builder 读取、Inspector / Custom 验证、GateKeeper 阻断 / 弱证据处理完整运行责任链的证据，summary-only 或 partial 信号只能作为 traceability 缺口 / diagnostics 出现。diagnostics 不替代 Web alignment 的硬 linter，也不能静默改写用户 bundle；需要改变 bundle 时必须走用户主动编辑、对话改进或重新导入。
- 若 Workdir Snapshot 暴露 `AGENTS.md`、适用于所选子目录的父级 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/` 等项目本地治理入口，alignment 不应发明其内容，但应在相关任务中把这些入口编译为运行责任：Builder 读取适用规则 / design，Inspector 或 Custom review 检查相关 design / test 契约，GateKeeper 将跳过本地规则或缺少预期验证视为 Weak、Unproven 或 Blocking。最终 bundle 只复述 marker 名称不算编译完成。
- Agent-first 候选若在宿主任务摘要中收到显式判断取舍，例如证明优先于速度、先阻断假完成再美化界面、严格阻断优先于务实推进，最终 bundle 必须把该取舍落到 `spec`、角色 posture、`workflow` 或 GateKeeper 严格度；后端 traceability 可以用轻量类别检查阻止候选只留下通用证据 / 风险词。
- Agent-first 候选若在宿主任务摘要中收到显式执行策略，例如先修根因、先补证据、先收窄范围、再扩功能或暂缓 UI 打磨，最终 bundle 必须把同类优先级落到 `spec`、角色 posture、`workflow` 或 step `inputs`；后端 traceability 可以用轻量类别检查阻止候选只保留任务对象而丢掉“下一轮先做什么 / 暂缓什么”。
- Agent-first 候选若在宿主任务摘要中收到显式残余风险策略，最终 bundle 必须保留相同管理语义：哪些风险可接受、由 owner / follow-up / acceptance path 接手，或哪些风险必须失败关闭。只把 `residual risk`、`manual`、`visible` 这类词搬进 bundle 不能证明风险已经可管理。
- Agent-first 候选若在宿主任务摘要中收到显式成功标准，最终 bundle 必须保留相同 outcome 语义：谁能完成什么动作、哪些通知 / 审计 / 权限 / 支付 / 数据 / 无障碍 / 多语言结果必须成立。只把任务对象写进 `Task`，但丢掉用户确认的验收结果，不能算完成判断外化。
- Agent-first 候选若在宿主任务摘要中收到显式假完成风险或证据偏好，最终 bundle 必须保留相同类别语义：例如 permission / audit 假完成、download/export-only 假完成、payment / refund / billing proof、data / export / report proof、browser journey、audit log command、contract test 等必须进入 `spec`、Inspector / GateKeeper posture、`workflow` 或 evidence 规则。只把任务对象写进 `Task`，但丢掉“什么会假完成”和“什么证据才可信”，不能算完成判断外化。

## 4. Loop 承载规则

长期任务编排不能只存在于一个字段或一段 prompt。它必须把 task-scoped human judgment 同时投影到可运行 surface。

| surface | 承载内容 |
|---------|----------|
| `spec` | 成功面、假完成、证据偏好、guardrails、执行策略、残余风险策略、判断取舍 |
| `role definitions` | 每个角色如何构建、取证、裁决、移交、执行本地治理责任或阻断 |
| `workflow` | 谁先做、何时并行取证、哪些证据流向下游、何时执行本地治理 checkpoint、何时 GateKeeper 裁决、何时自动迭代、何时用受控 trigger 检查空转、失败或拒绝，以及如何收束或修复 |

稳定规则：

- 三个 surface 缺一不可。
- 用户在 working agreement 中确认的判断取舍必须进入最终 bundle 的可运行 surface：例如哪类不完美结果应拒绝、证明何时优先于速度、严格阻断何时优先于务实推进。这些取舍可以由 `spec`、角色 posture、`workflow` 或 GateKeeper 严格度承载，但不能只停留在对话摘要里。
- bundle 不能退化成 prompt pack、role zoo、loop script、benchmark grinder 或 personality memory；更长提示词、更多角色、更多轮次、单一 benchmark 或全局人格 / 偏好记忆都不能替代 task-scoped 证据流、handoff 和 GateKeeper 裁决。
- bundle 是交换单元，不是版本控制单元。Loopora 不维护 Loop 演化历史、lineage、diff 或回滚。
- 手动微调允许分别编辑 surface，但导出后的 bundle 必须重新表达同一份治理结构。
- Web alignment 和 Agent-first 生成的用户可见名称与说明也属于治理表面；`metadata.name`、`metadata.description`、`loop.name` 与 `role_definitions[].name` 应跟随用户语言，同时保留 `Builder`、`Inspector`、`GateKeeper` 等 Loopora 术语。
- 当任务需要多个证据视角时，alignment 应优先生成带明确 Inspector 责任、`parallel_group`、`inputs.handoffs_from`、`inputs.evidence_query` 和必要 `inputs.iteration_memory` 的有界 fan-out / fan-in workflow，而不是复制多个泛化 reviewer。
- 当任务需要多个阶段性产物时，alignment 应优先生成长链 workflow，而不是引入嵌套 Loop、任意分支或把阶段藏进单个超大 Builder prompt。长链可以包含多个 task-specific Builder / Inspector / Guide step，但每个新增角色或 step 都必须对应新的证据责任、handoff 边界或裁决输入。
- 多 Builder 串联应表达阶段边界，例如探索 / 设计、实现、接线、修复或证据补强；后续 Builder 必须读取前序 review 或 Guide handoff，最终 GateKeeper 必须能汇总关键阶段证据。
- `workflow.controls[]` 是高级治理字段，只能表达 run 内部的误差控制信号；它不得退化成通用 cron、webhook、文件监听或自动 Builder 修复。
- controls 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper，并且必须能解释它控制的具体误差风险，例如无证据进展、角色失败、超时或 GateKeeper 拒绝。
- control 的触发次数上限必须是有界正整数；显式 `0` 不表示禁用，字符串数字也不是合法整数。

## 5. 生命周期

bundle 生命周期服务于 Loop 编排和交换：

`导入 / 生成 / 复制为候选 -> 校验和预览 -> 物化为 Loop -> 运行 -> 可选导出 bundle 或证据`

稳定规则：

- 导入后的 spec、role definitions、orchestration、loop 默认属于同一 bundle。
- 导入、导出和从现有 Loop 派生 bundle 必须保留显式 runtime 值；`0` 这类合法值不能被默认值覆盖。
- 删除或替换 bundle 默认只处理它明确拥有的底层资产，不得影响无关手动资产；durable bundle graph（bundle record、linked loop、runs、orchestration、role definitions 与 ownership）必须在同一 repository transaction 内删除或替换，本地 managed dir 与 loop/run artifacts 只能在 durable transaction 成功后 best-effort 清理。
- bundle replace 不得走逐个 service delete 路径。它必须与 delete 共享 ownership preflight：旧资产缺失 ownership、归属其他 bundle、存在外部引用或有 active run 时返回 conflict，并保留旧 graph 与本地目录。
- 被 bundle 拥有的底层资产不应被鼓励为互相漂移的零散对象。
- bundle 文件导入与预览只接受 UTF-8 YAML；编码或 YAML 解析失败属于输入错误，不得越过领域错误处理导致 CLI / API 崩溃。
- 从现有 loop 复制出候选 bundle 时，结果必须回到单文件 YAML，并被视为独立候选，而不是被写入系统级 lineage。
- 用户如何基于证据迭代 bundle 属于系统外部行为；Loopora 可提供从已有 bundle 或 run evidence 发起的对话改进入口，但该入口只产出独立候选 bundle，不成为 bundle 生命周期的必经阶段。
- 当用户在同一 workdir 再次进入 Web alignment 时，Loopora 可以发现同目录 `.loopora` 中的历史 alignment、Loop、run 或 spec 产物，并让用户选择继续、改进或重新生成。历史 READY alignment bundle 只有在当前 canonical 文件仍可通过结构与语义校验，且 bundle `loop.workdir` 仍匹配当前 workdir 时才可作为 source context；旧 `validation.json` 或 DB validation 不能让已被改坏或指向其他目录的文件继续成为候选来源。这个选择只提供编译期 source context；它不改变 bundle 是 standalone 交换单元的规则，也不把目录中的旧产物变成默认 lineage。
- READY 预览与 bundle detail 不展示系统级版本历史、surface diff 或回滚入口；若需要比较，属于用户主动导出后在系统外完成的判断。bundle detail 仍必须保留当前 bundle projection 的 agreement-to-surface traceability 和非阻断 diagnostics，让用户在运行或改进前能继续审计弱 workflow。
- 方案包兼容入口可以展示失败模式、证据风格、残余风险策略、执行策略、本地治理责任、workflow 形状和 GateKeeper 严格度，但这些内容必须来自 bundle projection，不能成为独立标签系统，也不能取代已有 Loop 高频浏览入口。

## 6. 入口语义

推荐 Agent-first 编排场景：

`/loopora-gen -> READY 预览 -> /loopora-loop`

Web 编排场景：

`创建 Loop -> 对话编排 -> READY 预览 -> 创建并运行`

专家入口：

`创建 Loop -> 手动编排 / 导入方案文件 -> 选择 spec / roles / workflow，或导入已有 bundle YAML`

稳定承诺：

- 顶层“编排”入口的对话编排工作台不要求用户先理解 bundle；导入方案文件和手动编排作为同一编排工作台的二级入口保留。
- Agent-first `/loopora-gen` 生成或发现候选后必须回到同一 READY 预览；用户从 Web 查看或修改候选，但继续执行时仍可回到 `/loopora-loop`。
- Agent-first READY 预览的主操作是回到宿主 Agent 执行 `/loopora-loop`，而不是 Web 一键启动 headless run；Web 可以展示和复制 `/loopora-loop` 交接命令，但不得把 Agent-first 候选通过 Web import/run 直接变成后台 executor 运行。`/loopora-loop` 负责在同一 Core 校验后导入并启动 Agent-native run。
- Agent-first `/loopora-gen` 若没有随请求提交候选 YAML，只能创建带当前任务摘要的 Web 对齐预填入口，并明确标记为未 READY；Core 不得替宿主 Agent 自动启动后端 Web compiler 来伪造 Agent-first 候选。
- Agent-first 候选 YAML 是后续 READY 校验的输入事实；Core 必须同时记录宿主原始提交哈希，以及 READY 后实际用于预览、导入和后续 run 的规范化文件哈希与字节数，写入 alignment event 与 adapter binding，让审计能区分“宿主提交了什么”和“Core 最终运行了哪份规范化方案文件”。
- Agent-first 受管入口在生成候选 YAML 前必须先判断 Loopora fit：如果一次 Agent 执行、一次 review、直接聊天 / 直接回答、一次性任务无需 Loop 或 benchmark/test-harness-only 验证已经足够，或后续轮次不会产生新的证据 / handoff / GateKeeper 裁决，就应解释 not-fit、追问或退到 Web review 预填入口，不能为了通过 READY 而发明长期治理理由。
- Agent-first 候选 YAML 还必须通过非空宿主任务摘要到运行 surface 的轻量 traceability 检查：当前任务中的高信号对象、风险或证据词必须出现在 `collaboration_summary`、`spec.markdown`、role prompt / posture、`workflow.collaboration_intent`、step `inputs`、workflow controls 或 GateKeeper evidence 规则中；metadata、loop 名称和 CLI `--message` 本身不能证明候选已经编译了本次判断，缺少宿主任务摘要的候选请求应在写入候选前被拒绝。
- 若 Agent-first 宿主任务摘要或目标 workdir 的 Workdir Snapshot 把 `AGENTS.md`、适用于所选子目录的父级 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/` 作为本地治理事实交给 Core，traceability 不能只靠候选文本复述这些 marker 通过；候选必须把它们编译成 Builder 读取、Inspector / Custom 验证和 GateKeeper 弱证据 / 未证明 / 阻断责任。
- 若 Agent-first 宿主任务摘要给出显式执行策略，Core traceability 必须按类别检查修根因、取证、收窄范围、扩展功能、UI / polish 等优先级是否进入运行 surface；否则该候选不能 READY，应回到 YAML 修复、用户追问或 Web review。
- 若 Agent-first 宿主任务摘要把残余风险说成可接受或不可接受，Core traceability 必须按类别检查接受、owner / follow-up 和失败关闭语义是否进入运行 surface；否则该候选不能 READY，应回到 YAML 修复、用户追问或 Web review。
- 若 Agent-first 宿主任务摘要明确给出成功标准，Core traceability 必须按类别检查 actor / notification / audit / permission / payment / data / accessibility / locale 等 outcome 是否进入运行 surface；否则该候选不能 READY，应回到 YAML 修复、用户追问或 Web review。
- 若 Agent-first 宿主任务摘要明确给出假完成或证据偏好，Core traceability 必须按类别检查这些风险与 browser / command / audit / permission / payment / refund / billing / data / export / report / accessibility / locale 等 proof mode 是否进入运行 surface；否则该候选不能 READY，应回到 YAML 修复、用户追问或 Web review。
- `bundle` 是内部交换单元和专家导入 / 导出格式。
- 方案详情和 run 详情可以提供“对话改进方案”入口；它复用 Web alignment session，把当前 bundle 或 run evidence 作为临时输入生成独立候选 Loop，随后仍走 READY 预览和导入 / 运行。
- READY 预览必须包含从 bundle 派生的控制摘要，至少覆盖 Loopora fit、成功面、假完成风险、证据偏好、coverage target trace、主要风险、残余风险策略、证据路径、执行策略、判断取舍、本地治理责任、role posture、workflow 形状、GateKeeper 门禁、agreement-to-bundle traceability 投影、bundle diagnostics 和可选 runtime controls；coverage target trace 必须按 bundle 的 `completion_mode` 派生，不能让 rounds 模式显示 `gatekeeper.finish` 这类不存在的收束门禁。这些摘要是 projection，不是新的事实源。本地治理责任卡片只代表已进入完整运行责任链的证据，未成链的 summary-only 或 partial 信号应进入 traceability missing / diagnostics，而不是作为可执行承诺展示。导入后启动 `loopora loop` 时，bundle `collaboration_summary`、可投影的 `loop_fit_reasons`、`execution_strategy`、已进入运行责任链的本地治理责任、`role_postures`、`judgment_tradeoffs`、success surface、fake done、evidence preferences、residual-risk stance、check / completion mode 与 coverage targets 必须冻结进 run contract、出现在每个 step prompt 中，并被 run key takeaways / accepted event 投影为验收期判断契约；run contract 还应记录本次 run 所属 bundle 记录的轻量 provenance（id、name、revision、source bundle id、导入路径、由 bundle 记录导出的 YAML 哈希和字节数），用于审计“这次执行来自哪份 bundle 记录 / 内容指纹”，但不能替代已冻结的 spec、workflow 与 prompt 内容。否则预览可见的治理故事不能算执行期判断输入。
- 两条路径必须能互相转换：bundle 可以导入成底层资产，手动 loop 也可以导出成 bundle。
- 方案包兼容入口负责管理、导出、复制为候选和整包删除；列表卡片应优先呈现成功面、假完成、证据偏好、执行策略、残余风险、判断取舍、本地治理和 GateKeeper 等治理摘要，详情页保留专家 surface、当前 traceability / diagnostics projection 和 YAML 入口。

## 7. 变更触发

以下变化需要更新本文档：

- bundle 不再是单文件 YAML
- working agreement 的运行期地位变化
- bundle 生命周期语义变化
- Web alignment 与 Loopora 本体的边界变化
- Agent-first candidate intake 与 Web alignment 的共同 Core 校验边界变化
- 治理结构不再由 `spec / role definitions / workflow` 共同承载

以下变化通常不需要更新本文档：

- bundle 字段小幅扩展
- 对齐话术调整
- Web / CLI 页面布局调整
