# Bundles And Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。bundle 是 Loop 的内部交换单元；它必须承载可运行的长期任务编排，而不是退化成裸 YAML 或角色配置包。

## 1. 模块职责

本文档定义两条稳定边界：

- Alignment 如何作为一种场景，把当前任务的人类判断收敛成候选 human-shaped Loop。
- Loopora 如何消费 bundle 并把它物化为可运行 Loop 资产。

它不定义具体对话话术，也不定义某个 provider 的调用细节。

## 2. 核心分工

| 边界 | 负责方 | 稳定职责 |
|------|--------|----------|
| 任务访谈与对齐 | Web alignment session | 后台 Agent 主导语义对话，与用户确认成功面、假完成、证据、风险和判断方式，把未来纠偏提前为候选 Loop |
| bundle 生成 | Web alignment session | 在后端阶段门槛承认 working agreement 后，输出单文件 YAML bundle |
| bundle 生命周期 | Loopora 本体 | 导入、导出、派生、删除，并把 bundle 物化为本地 Loop 资产 |
| run 执行 | Loopora 本体 | 从 Loop 的 `spec / role definitions / workflow` 自动迭代并留下证据 |

稳定规则：

- `working agreement` 是编译期中间产物，不是运行期资产。
- Alignment 必须先说明 Loopora fit：这次为什么需要可运行治理 Loop，而不是一次 Agent 执行加一次人工 review、直接聊天或 benchmark-first 简单循环。
- Loopora 不执行独立 agreement 文件。
- 最终运行输入仍然是 `spec / role definitions / workflow / loop`。
- 外部 Agent Skill 不再是一等 bundle 编译入口；YAML 导入 / 导出仍是专家交换格式，但判断显影和候选 bundle 编译默认由 Web alignment 的受控 compiler 完成。
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

校验规则：

- bundle 顶层 `version` 目前只支持整数 `1`；缺失或空值可按当前版本处理，但显式 `0`、布尔值、小数、非数字或未来版本必须失败关闭，不能被默认值覆盖。
- Web alignment 的最终产物必须是 raw YAML document，首个非空行必须是 `version: 1`，而不是 fenced Markdown、解释性回答、注释前缀或 confirmation summary。用户可见协议是编译期对话面，不能被混进最终 bundle 文本。
- legacy `metadata.revision` 若存在，必须是正整数；Loopora 可以在导入后忽略 lineage/revision 历史，但不得把非法显式值静默改成默认值。
- `spec.markdown` 必须能通过 Loopora 正常 spec 编译器。
- `loop` 运行参数必须满足与普通 Loop 创建相同的有限值和范围边界，不能通过 YAML 导入绕过服务层数值契约。
- Web alignment 生成的默认 bundle 必须使用 `gatekeeper` completion mode，使任务裁决来自证据和 GateKeeper 判断，而不是只来自 run 生命周期收束；专家手动导入仍可使用其他 completion mode。
- Web alignment 生成的新候选 bundle 必须省略 `metadata.source_bundle_id` 与显式 `metadata.revision`；改进入口还不得把来源 bundle id 复用为 `metadata.bundle_id`。来源 bundle、run evidence 与反馈只作为对话期输入，不写成系统级 lineage 或候选身份。
- `gatekeeper` completion mode 必须包含可 `finish_run` 的 GateKeeper step。
- 最终 bundle 的治理文本不能与 Loopora fit 自相矛盾：若候选文件声称单轮 Agent、一次 Agent + human review、直接聊天、后续轮次不会产生新证据、稳定 benchmark 或 benchmark-only 路径已经足够，就不能同时被 Web alignment 当作 human-shaped Loop 接受。
- Web alignment 生成的 bundle 必须额外通过语义 linter，但 linter 只承担粗颗粒护栏职责：结构 section 是否存在、raw YAML / metadata / completion mode 是否合约正确、workflow handoff 与 evidence query 是否断链、是否出现全局人格记忆等明确反模式。具体表达是否“足够好”、某个判断是否用了特定词汇、role posture 是否符合某组动词，不应靠正则硬阻断；这些属于 prompt 指导、working agreement 确认和后续人工 / GateKeeper 判断。
- Web alignment 生成的 `workflow.collaboration_intent` 必须说明证据如何流动、GateKeeper 如何收束，以及证据薄弱、偏差或假完成会在哪里尽早暴露；只有顺序和角色名不足以证明 Loop 是 human-shaped。
- Web alignment 在交付 working agreement 或 bundle 前，应私下彩排一条完整运行路径：Builder 产出和 handoff、Inspector / Custom 取证、可选 Guide 修复方向、第二轮 Builder、GateKeeper 裁决和用户证据审计，都必须能通过显式 handoff、evidence query、角色姿态和证据桶串起来；否则应继续对齐或调整候选 Loop。
- Web alignment 在交付 working agreement 或 bundle 前，应私下用一个可能的失败轮次压测候选 Loop：看似完成但证据弱、覆盖缺失、标准漂移或残余风险不可接受的结果，必须能被 `spec / roles / workflow / evidence` 暴露、修复或阻断；否则应继续对齐或调整候选 Loop，而不是交付 YAML。
- Web alignment 在交付 working agreement 或 bundle 前，应私下完成 agreement-to-bundle traceability checklist：用户已确认的 Loopora fit、任务范围、成功面、假完成、证据偏好、残余风险、判断取舍、角色姿态和 workflow 判断，都必须能映射到 `collaboration_summary`、`spec.markdown`、role prompt / posture、`workflow.collaboration_intent`、step `inputs`、workflow controls 或 GateKeeper evidence 规则；若某项只存在于 `agreement_summary`、readiness evidence、transcript、metadata / loop 名称或隐性推理中，应继续对齐或调整候选 Loop。后端校验应使用已确认 working agreement 作为锚点，检查任务特异判断是否出现在最终 bundle 的治理 surface 中；bundle 自身的 traceability projection 只能证明候选文件内部有 surface，不能替代这道编译边界。
- Web alignment 必须结合主动注入与被动检测：每轮 prompt 注入当前 compiler gate、候选阶段和输出纪律；后端只把通过 stage gate、readiness evidence、traceability、语义 linter 与 bundle 校验的结果承认为下一阶段。
- 方案预览和导入校验应提供非阻断 bundle diagnostics projection，用于暴露旧 bundle 或弱 workflow 的迁移风险，例如显式 Guide 没有读取上游 handoff / evidence、finishing GateKeeper 没有 evidence fan-in、review 后的 Builder 未读取 review handoff、或 traceability 缺口。diagnostics 不替代 Web alignment 的硬 linter，也不能静默改写用户 bundle；需要改变 bundle 时必须走用户主动编辑、对话改进或重新导入。
- 若 Workdir Snapshot 暴露 `AGENTS.md`、`design/README.md`、`design/` 或 `tests/` 等项目本地治理入口，alignment 不应发明其内容，但应在相关任务中把这些入口编译为运行责任：Builder 读取适用规则 / design，Inspector 或 Custom review 检查相关 design / test 契约，GateKeeper 将跳过本地规则或缺少预期验证视为 Weak、Unproven 或 Blocking。最终 bundle 只复述 marker 名称不算编译完成。

## 4. Loop 承载规则

长期任务编排不能只存在于一个字段或一段 prompt。它必须把 task-scoped human judgment 同时投影到可运行 surface。

| surface | 承载内容 |
|---------|----------|
| `spec` | 成功面、假完成、证据偏好、guardrails、残余风险 |
| `role definitions` | 每个角色如何构建、取证、裁决、移交或阻断 |
| `workflow` | 谁先做、何时并行取证、哪些信息流向下游、何时 GateKeeper 裁决、何时自动迭代、何时用受控 trigger 检查空转、失败或拒绝，以及如何收束或修复 |

稳定规则：

- 三个 surface 缺一不可。
- 用户在 working agreement 中确认的判断取舍必须进入最终 bundle 的可运行 surface：例如哪类不完美结果应拒绝、证明何时优先于速度、严格阻断何时优先于务实推进。这些取舍可以由 `spec`、角色 posture、`workflow` 或 GateKeeper 严格度承载，但不能只停留在对话摘要里。
- bundle 不能退化成 prompt pack、role zoo、loop script、benchmark grinder 或 personality memory；更长提示词、更多角色、更多轮次、单一 benchmark 或全局人格 / 偏好记忆都不能替代 task-scoped 证据流、handoff 和 GateKeeper 裁决。
- bundle 是交换单元，不是版本控制单元。Loopora 不维护 Loop 演化历史、lineage、diff 或回滚。
- 手动微调允许分别编辑 surface，但导出后的 bundle 必须重新表达同一份治理结构。
- Web alignment 生成的用户可见名称与说明也属于治理表面；`metadata.name`、`metadata.description`、`loop.name` 与 `role_definitions[].name` 应跟随用户语言，同时保留 `Builder`、`Inspector`、`GateKeeper` 等 Loopora 术语。
- 当任务需要多个证据视角时，alignment 应优先生成带明确 Inspector 责任、`parallel_group`、`inputs.handoffs_from`、`inputs.evidence_query` 和必要 `inputs.iteration_memory` 的有界 fan-out / fan-in workflow，而不是复制多个泛化 reviewer。
- 当任务需要多个阶段性产物时，alignment 应优先生成长链 workflow，而不是引入嵌套 Loop、任意分支或把阶段藏进单个超大 Builder prompt。长链可以包含多个 task-specific Builder / Inspector / Guide step，但每个新增角色或 step 都必须对应新的证据责任、handoff 边界或裁决输入。
- 多 Builder 串联应表达阶段边界，例如探索 / 设计、实现、接线、修复或证据补强；后续 Builder 必须读取前序 review 或 Guide handoff，最终 GateKeeper 必须能汇总关键阶段证据。
- `workflow.controls[]` 是高级治理字段，只能表达 run 内部的误差控制信号；它不得退化成通用 cron、webhook、文件监听或自动 Builder 修复。
- controls 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper，并且必须能解释它控制的具体误差风险，例如无证据进展、角色失败、超时或 GateKeeper 拒绝。
- control 的触发次数上限必须是有界正整数；显式 `0` 不表示禁用，而是不合法配置。

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
- 当用户在同一 workdir 再次进入 Web alignment 时，Loopora 可以发现同目录 `.loopora` 中的历史 alignment、Loop、run 或 spec 产物，并让用户选择继续、改进或重新生成。这个选择只提供编译期 source context；它不改变 bundle 是 standalone 交换单元的规则，也不把目录中的旧产物变成默认 lineage。
- READY 预览与 bundle detail 不展示系统级版本历史、surface diff 或回滚入口；若需要比较，属于用户主动导出后在系统外完成的判断。bundle detail 仍必须保留当前 bundle projection 的 agreement-to-surface traceability 和非阻断 diagnostics，让用户在运行或改进前能继续审计弱 workflow。
- 方案包兼容入口可以展示失败模式、证据风格、workflow 形状和 GateKeeper 严格度，但这些内容必须来自 bundle projection，不能成为独立标签系统，也不能取代已有 Loop 高频浏览入口。

## 6. 入口语义

推荐编排场景：

`创建 Loop -> 对话编排 -> READY 预览 -> 创建并运行`

专家入口：

`创建 Loop -> 手动编排 / 导入方案文件 -> 选择 spec / roles / workflow，或导入已有 bundle YAML`

稳定承诺：

- 顶层“编排”入口的对话编排工作台不要求用户先理解 bundle；导入方案文件和手动编排作为同一编排工作台的二级入口保留。
- `bundle` 是内部交换单元和专家导入 / 导出格式。
- 方案详情和 run 详情可以提供“对话改进方案”入口；它复用 Web alignment session，把当前 bundle 或 run evidence 作为临时输入生成独立候选 Loop，随后仍走 READY 预览和导入 / 运行。
- READY 预览必须包含从 bundle 派生的控制摘要，至少覆盖主要风险、证据路径、workflow 形状、GateKeeper 门禁、agreement-to-bundle traceability 投影、bundle diagnostics 和可选 runtime controls；这些摘要是 projection，不是新的事实源。
- 两条路径必须能互相转换：bundle 可以导入成底层资产，手动 loop 也可以导出成 bundle。
- 方案包兼容入口负责管理、导出、复制为候选和整包删除；列表卡片应优先呈现治理摘要，详情页保留专家 surface、当前 traceability / diagnostics projection 和 YAML 入口。

## 7. 变更触发

以下变化需要更新本文档：

- bundle 不再是单文件 YAML
- working agreement 的运行期地位变化
- bundle 生命周期语义变化
- Web alignment 与 Loopora 本体的边界变化
- 治理结构不再由 `spec / role definitions / workflow` 共同承载

以下变化通常不需要更新本文档：

- bundle 字段小幅扩展
- 对齐话术调整
- Web / CLI 页面布局调整
