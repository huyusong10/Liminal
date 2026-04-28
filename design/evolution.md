# Loopora Evolution

## 1. 目标

本文档定义 Loopora 从当前实现继续演进的主航道。

最高原则见 `core-ideas/product-principle.md`：

> Loopora 是面向长期 AI Agent 任务的外部任务治理层。它把任务治理从 Agent 的上下文里拿出来，变成外部、持久、可检查、可运行、可修订的控制系统。

因此，后续演进不应围绕“生成更多 YAML / 增加更多角色 / 包装更多 CLI”展开，而应围绕一个问题展开：

> 如何让 AI Agent 能更久地自主推进，同时把误差压在用户可接受范围内？

## 2. 当前主要 GAP

| GAP | 当前风险 | 目标状态 |
|-----|----------|----------|
| bundle 像配置文件 | 用户看到的是 `spec / roles / workflow` 拼装结果，而不是清晰的误差控制契约 | bundle 明确表达任务风险、证据门槛、角色 handoff、GateKeeper 阻断标准和 revision 入口 |
| evidence 不是一等公民 | run 结束后有日志和 artifact，但用户仍要自己判断哪些事实重要 | 每次 run 形成 evidence ledger，可回答“证明了什么 / 没证明什么 / 哪些风险仍在” |
| GateKeeper 不够硬 | GateKeeper 可能退化成一个会总结的角色名 | GateKeeper 是可执行门禁：没有证据覆盖和明确裁决，就不能结束 |
| revision loop 不够核心 | 结果不满意时容易回到“再 prompt 一次” | run evidence 和用户反馈能生成下一版 harness，而不是只修代码或聊天 |
| Web 没有展示控制机制 | 页面展示方案内容，但用户不一定看出系统如何控制误差 | Web 显示本任务的风险、证据、门禁、角色对抗和修订状态 |
| prompt 强，runtime enforcement 弱 | prompt 能要求 Agent 更谨慎，但控制仍可能依赖模型自觉 | 服务层和运行时用结构化契约、linter、状态机和门禁做硬约束 |
| 方案库像 YAML 列表 | 方案可保存，但复用价值不突出 | 方案库成为可复用任务治理模式库，按风险、证据和 workflow 形状组织 |
| workflow 表达能力偏线性 | 多个检视视角只能串行跑，且信息流默认全量下传 | 支持有限 fan-out / fan-in 检视组，并把角色间与轮次间信息流显式化 |

## 3. 演进原则

1. **治理外部化优先于 prompt 优化。**
   prompt 可以引导，但核心判断必须落到可检查的数据、状态机、artifact 和 UI。

2. **证据优先于叙事。**
   Agent 的自然语言解释不能替代 evidence ledger。解释必须引用证据。

3. **GateKeeper 是门禁，不是 reviewer。**
   GateKeeper 的职责是决定是否可以结束；它必须能阻断假完成，并明确说明缺哪些证据。

4. **revision 修 harness，不只是修产物。**
   如果 run 暴露的是 spec、role、workflow 或证据门槛错误，系统应引导用户修订循环方案。

5. **跨 Agent 是控制层价值。**
   Loopora 的 harness 不能绑定某个具体 provider。Codex、Claude Code、OpenCode 或自定义 CLI 都应服从同一份治理契约。

6. **新手看任务治理，专家看底层 surface。**
   默认 Web 语言仍应是“任务 / 循环方案 / 证据 / 修订”；`bundle / YAML / spec / roles / workflow` 留给预览、专家编辑和导出。

## 4. 对现有功能的冲击

这些演进不是在现有系统旁边新增功能，而是会改变多个既有能力的语义重心。每次实现必须同步处理下表里的影响，避免系统腐化成“双轨产品”。

| 现有功能 | 需要同步收口 | 不允许的腐化形态 |
|----------|--------------|------------------|
| Web 新建任务 | 从“对话生成 bundle”收敛为“对齐任务治理方案” | 新增一个独立 evidence / revision 页面，却让新建任务仍只展示 YAML 或角色列表 |
| READY Artifact | 默认展示控制摘要、风险、证据门槛、GateKeeper 标准 | 在现有 `spec / roles / workflow` 旁边再加一张无来源的说明卡 |
| bundle import/export | 继续作为文件化交换单元，但导入后要能投影治理语义 | 为 governance 另建一套不可导入导出的私有格式 |
| bundle detail / 方案库 | 从 YAML 资产管理升级为治理模式管理 | 只在列表里加标签，不改变详情页和 revision 语义 |
| 手动创建 | 仍保留专家路径，但必须能表达同一套治理 surface | 手动路径生成的 loop 无法进入 evidence / revision 闭环 |
| role / workflow 编辑器 | 支持专家修改治理 surface，并保持 bundle revision 一致 | 允许 role、workflow、bundle 各自漂移，无法回到同一方案 |
| run lifecycle | run 结束时形成 evidence ledger、GateKeeper verdict、revision seed | 保留旧 run 详情为日志浏览器，evidence 只作为附属报告 |
| diagnostics / logs | application log、event stream、evidence ledger 分层协作 | 把 evidence ledger 做成另一份复制日志 |
| executor providers | provider 差异显式记录为 capability / degradation | 为不同 provider 写不同治理逻辑或静默降级标准 |
| Skill / prompt | 继续引导 posture interview，但输出必须被 runtime gate 校验 | 依赖 prompt 自觉实现 GateKeeper、evidence、revision |
| tests / scenarios | 行为测试锁定治理契约，scenario 覆盖长任务闭环 | 只更新 UI 文案断言，缺少 evidence / revision 契约覆盖 |

## 5. 防腐规则

0. **5 分钟上手是硬门槛。**
   新用户默认只需要描述任务、选择 workdir、确认方案、运行、看证据、修订。新增 workflow 能力必须由系统编译进循环方案，不能把首屏变成自动化配置台。

1. **不新增平行事实源。**
   Evidence ledger 必须从 run artifacts、handoff、verdict 和测试 / 命令结果中派生或引用，不能复制出另一套无人维护的“总结数据库”。

2. **不绕过 bundle 生命周期。**
   新的治理字段可以逐步扩展 bundle，但 READY、导入、导出、删除、派生仍必须复用同一整包生命周期。

3. **不让 Web 和底层语义分叉。**
   Web 可以隐藏内部术语，但每个可视结论都必须能回到 `spec / roles / workflow / evidence / revision` 的稳定来源。

4. **不让 GateKeeper 只停留在 prompt。**
   GateKeeper 的硬门禁必须有服务层或运行时校验；自然语言 verdict 只能作为解释，不是唯一事实。

5. **不让 revision 退化成复制一份新聊天。**
   Revision 必须读取旧 bundle、run evidence、GateKeeper verdict 和用户反馈，并产出可比较的新 bundle revision。

6. **不让 provider 能力差异污染治理契约。**
   provider 缺少 resume、schema、浏览器或文件能力时，应记录 degradation，并让 UI / run evidence 可见，而不是改变成功标准。

7. **不把旧功能孤立废弃。**
   手动创建、外部 Skill、CLI、方案库和 role / workflow 编辑仍应保留，但它们必须逐步接入同一套治理、证据和修订语义。

8. **不把 workflow 升级成通用 DAG 引擎。**
   Loopora 的目标是任务误差控制，不是可视化流程编程。并行、信息选择和 10+ 角色能力都必须服务于 evidence coverage、GateKeeper 判定和 revision，而不是为了展示复杂图。

## 6. 目标能力

### 6.1 Bundle 作为 Error-Control Contract

目标：

- bundle 不只是可运行配置，而是一次长期任务的误差控制契约。

应表达的稳定语义：

| 区域 | 必须回答 |
|------|----------|
| task contract | 这次任务到底要推进什么，不推进什么 |
| fake done | 哪些结果看起来完成但必须被拒绝 |
| evidence preferences | 用户信任哪些证据，不信任哪些自我报告 |
| role responsibilities | 每个角色如何降低不同类型误差 |
| workflow controls | 判断何时发生，如何循环，如何停止 |
| GateKeeper criteria | 哪些证据缺失会阻断结束 |
| revision hooks | run 后反馈应该改哪类 surface |

改进方向：

- alignment READY 预览默认展示“控制结构摘要”：风险、证据、门禁、角色分工。
- `workflow.controls` 只做受控误差触发：无新证据、角色失败、GateKeeper 拒绝、超时。它不是 cron、webhook、文件监听或通用自动化。
- control 只能调用既有 Inspector / Guide / GateKeeper 产出检查、建议或阻断；不能隐式调用 Builder 修复。
- semantic linter 不只检查字段存在，还检查是否有任务特定 tradeoff、证据路径和阻断标准。
- bundle 详情页从“YAML 资产详情”升级为“循环方案治理详情”，YAML 只作为专家源文件。

同步重构：

- `bundles.py` / bundle import service 增加治理摘要投影，而不是让 Web 自己解析 YAML。
- manual import、Web alignment、外部 Skill 输出必须共享同一个 preview projection。
- 旧 bundle 可导入，但缺少治理字段时应显示“未声明 / legacy”状态，而不是伪造完整控制结构。

验收信号：

- 用户不打开 YAML，也能看懂这份方案如何防止假完成。
- 任意 READY bundle 都能回答“GateKeeper 凭什么允许结束”。

### 6.2 Runtime Evidence Ledger

目标：

- run 之后不只留下日志，而是形成可复盘、可引用、可修订的 evidence ledger。

Evidence item 应至少表达：

| 字段 | 含义 |
|------|------|
| claim | 本条证据声称证明什么 |
| source | 来自测试、浏览器、文件 diff、命令输出、人工反馈还是角色判断 |
| method | 如何取得证据 |
| result | 通过、失败、部分成立或无法验证 |
| artifact refs | 对应本地文件、截图、报告、日志片段 |
| produced by | 哪个 step / role / iteration 产生 |
| verifies | 对应 spec check、fake-done 风险或 GateKeeper criterion |
| residual risk | 仍未覆盖的风险 |

改进方向：

- 在 run artifact 中新增稳定 evidence ledger，区别于 application log 和 raw output；canonical 路径为 `evidence/ledger.jsonl`。
- Inspector、GateKeeper 与其他 step 的 handoff 必须写入最小 evidence item，并标记 evidence kind。
- GateKeeper 的通过 verdict 必须引用上游 ledger item；首步门禁场景必须提供可度量证据。自然语言 claims 单独不能作为结束 run 的凭据。
- run 详情页默认展示 evidence coverage，而不是 raw artifact 浏览。

同步重构：

- `07-observability-and-diagnostics.md` 的 application log / event stream / run artifacts 分层需要补 evidence ledger 位置。
- run detail 页面需要从“浏览 artifact”转为“证据覆盖主视图 + 原始 artifact 作为追查入口”。
- 现有 fake executor、real CLI scenario、run fixture 必须产出最小 evidence item，避免测试只验证日志存在。

验收信号：

- run 结束后能回答“哪些成功标准被证据覆盖，哪些没有”。
- 后续 revision 能直接读取 ledger，而不是重新解析自然语言日志。

### 6.3 GateKeeper Hard Gate

目标：

- GateKeeper 成为运行收敛的硬门禁。

稳定语义：

- 只有 GateKeeper step 可以结束 `gatekeeper` mode run。
- GateKeeper 必须基于 evidence ledger 做 verdict。
- 通过 verdict 必须列出覆盖的 checks、仍有的 residual risk 和放行理由。
- 未通过 verdict 必须列出 blocker、缺失证据和下一步建议。
- 如果证据不足，默认不能用“看起来不错”放行。

改进方向：

- GateKeeper 输出契约升级为 verdict envelope：`decision / evidence_refs / blockers / residual_risks / next_action`。
- 服务层校验 GateKeeper verdict 是否引用 evidence refs；若模型返回 `passed=true` 但没有证据引用或具体证据声明，服务层必须改写为未通过。
- Web 上把 GateKeeper verdict 展示为“是否允许结束”的主结论，而不是普通角色摘要。

同步重构：

- `gatekeeper` completion mode 的成功条件需要从“模型说 ok”升级为“verdict envelope 通过 runtime 校验”。
- 旧 run / legacy verdict 需要兼容展示，但不能作为新 run 的强通过样式。
- Inspector 与 GateKeeper 的 prompt、输出 schema、service parser、tests 必须同批更新。

验收信号：

- 没有 evidence refs 的 GateKeeper pass 不能让 run 成功。
- 用户能一眼看到 run 为什么被放行或阻断。

### 6.4 Run -> Failure Analysis -> Harness Revision

目标：

- 运行失败或用户不满意时，默认进入 harness revision，而不是随手追加 prompt。

稳定流程：

`run evidence -> failure analysis -> user feedback -> proposed harness delta -> new bundle revision`

Failure analysis 应区分：

| 类型 | 处理方式 |
|------|----------|
| implementation failure | 代码或产物没做好，继续 run 或修复 |
| evidence failure | 没有证明该证明的事，强化 Inspector / evidence requirements |
| gate failure | GateKeeper 太松或太严，修订阻断标准 |
| spec failure | 成功标准或假完成定义不准，修订 spec |
| workflow failure | 判断顺序不对，修订 workflow |
| role failure | 角色职责或 handoff 不清，修订 role definitions |

改进方向：

- run 详情页提供“基于本次证据修订方案”入口。
- revision session 自动带入旧 bundle、evidence ledger、GateKeeper verdict 和用户反馈。
- revision 输出新 bundle revision，并展示差异摘要：spec 变了什么、roles 变了什么、workflow 变了什么。

同步重构：

- alignment session 需要支持 revision mode，而不是另建一套 revision chat。
- bundle revision 需要保留 lineage：来源 bundle、来源 run、关键 evidence refs、用户反馈。
- 方案库和 bundle detail 需要展示 revision lineage，避免用户只看到多份孤立 YAML。

验收信号：

- 用户说“这次太草率 / 太保守 / 没抓住重点”时，系统能转成具体 harness delta。
- revision 后的新 run 能继承上一轮证据，而不是从零开始聊天。

### 6.5 Cross-Agent Execution

目标：

- 同一份 harness 可以交给不同 AI Agent CLI 执行，而治理语义保持一致。

稳定语义：

- executor 是执行能力，不是任务治理本体。
- provider 差异必须收敛到统一的 `RoleRequest`、结构化输出、session resume 和 artifact refs。
- 如果某个 provider 缺少原生能力，系统可以降级，但必须显式记录能力缺口。

改进方向：

- 为每个 provider 维护 capability summary：结构化输出、resume、文件写入、浏览器能力、命令模式限制。
- Web 允许在方案级或角色级切换 executor，但不改变 `spec / roles / workflow` 的治理语义。
- 支持同一 bundle 在不同 provider 下做对照 run，比较 evidence coverage 和 GateKeeper verdict。

同步重构：

- executor 配置 UI、role definition、alignment Agent 设置要共享 provider capability 解释。
- command mode / custom CLI 必须保留 escape hatch，但它的 capability 缺口要能进入 run evidence。
- 真实 CLI E2E 应覆盖至少一个“同 harness 不同 provider”的基础可运行性场景。

验收信号：

- 切换 provider 不要求用户重新生成循环方案。
- provider 降级不会静默改变完成标准。

### 6.6 Workflow Governance Expansion

目标：

- 让 workflow 能表达更真实的任务治理结构，同时保持可运行、可复盘和可修订。

稳定语义：

| 能力 | 用途 | 第一阶段边界 |
|------|------|--------------|
| generalized Inspector | 把 Inspector 从“测试者”扩展为证据生产者，可覆盖规则检查、语义 posture、专家审阅和人工反馈 | 仍必须输出结构化 evidence，不能绕开 ledger |
| bounded parallel groups | Build 后允许多个 Inspector / Custom 分支基于同一快照并行检视 | 只支持连续 step 的 fan-out / fan-in，不支持任意 DAG |
| role-to-role inputs | 当前 step 显式选择读取哪些上游 handoff | 只裁剪 prompt 可见范围，不删除 artifact |
| iteration memory policy | 当前 step 显式选择读取哪些上一轮信息 | 支持 default / none / same_step / same_role / summary_only |
| 10+ role support | 支持复杂任务的多视角检视和专家分工 | UI 必须用分组、折叠和 evidence coverage 呈现，不推荐默认 starter 过度复杂 |

改进方向：

- workflow step 增加 `parallel_group` 与 `inputs`，把并行形状和信息流写入外部契约。
- GateKeeper 默认 fan-in 到 evidence ledger，而不是依赖某个单一 Inspector 的自由文本总结。
- role archetype 与 role instance 解耦：`Inspector` 是证据职责，具体实例可以是 accessibility inspector、contract inspector、semantic posture reviewer 等。
- Web 方案预览和 run 详情应能把同一并行组显示为 inspection pack，并展示每个分支覆盖了哪些风险。

同步重构：

- normalize / import / export / run contract 必须保留新增 workflow 字段，避免 bundle 与手工编排分叉。
- run event stream 必须暴露 parallel group start / finish，但每个 step 自己的 context、handoff、evidence 仍是事实源。
- workflow diagram 需要避免 10+ 角色时拥挤；复杂 workflow 优先显示分组与列表，再展开细节。

验收信号：

- 同一 Builder 产物可以被两个 Inspector 并行检视，GateKeeper 能看到两条 evidence refs。
- 用户能用 `inputs` 限制 GateKeeper 只看特定 handoff 或 evidence 摘要，且完整 artifact 仍可复盘。
- 复杂 workflow 不会把所有信息无差别塞进每个 prompt。

### 6.7 Web Error-Control Visualization

目标：

- Web 不只展示方案内容，还展示“这套方案如何控制误差”。

建议视图：

| 视图 | 展示内容 |
|------|----------|
| Control Summary | 本任务的主要风险、假完成、证据门槛、GateKeeper 严格度 |
| Workflow Map | 角色顺序、handoff、取证点、GateKeeper 收束点 |
| Evidence Coverage | 哪些 checks / 风险已有证据，哪些仍缺失 |
| Gate Verdict | 当前 run 是否允许结束，以及 blocker / residual risk |
| Revision Delta | 这一版 harness 相比上一版改了哪些治理判断 |

改进方向：

- READY Artifact 默认显示控制摘要，而不是先展示 YAML 或长文本。
- run 详情页默认显示 evidence coverage 和 GateKeeper verdict。
- 方案库卡片显示治理模式摘要：风险类型、证据风格、workflow 形状、适合任务。

同步重构：

- Web 不能新增一套仅前端推导的“控制摘要”；摘要必须来自 bundle projection、evidence ledger 或 revision diff。
- READY Artifact、bundle detail、run detail、方案库卡片要共享同一组 projection helpers。
- 移动端和桌面端都要避免把原始 YAML / log 重新推成主信息层。

验收信号：

- 新用户能看懂 Loopora 为什么比“让 Agent 再跑一遍”更可控。
- 专家用户能从 UI 直接判断该改 `spec`、`roles` 还是 `workflow`。

### 6.8 Plans Library as Governance Pattern Library

目标：

- 方案库不是 YAML 列表，而是可复用任务治理模式库。

组织维度：

| 维度 | 示例 |
|------|------|
| failure mode | 假完成、目标漂移、证据不足、过度设计、回归风险 |
| evidence style | 浏览器可运行证据、测试证据、benchmark、设计文档、人工验收 |
| workflow shape | build-then-parallel-review、evidence-first、repair-loop、benchmark-gate |
| GateKeeper strictness | 快速放行、证据优先、保守签字 |
| task domain | Web 产品、重构、调研、迁移、性能优化 |

改进方向：

- 方案库卡片突出治理摘要，而不是文件名和 YAML 元数据。
- 支持从成功 run 派生治理模式。
- 支持把用户反馈沉淀为方案 revision notes。

同步重构：

- 方案库列表、详情、删除、导出、派生都继续走 bundle 生命周期。
- 筛选维度应来自 bundle projection 或 revision metadata，不在 UI 本地维护第二套标签真相。
- 从 run 派生方案时，必须带入 evidence 和 verdict 摘要，不能只复制当时的 YAML。

验收信号：

- 用户能按“我怕什么失败”找到方案，而不只是按名字找 YAML。
- 方案复用后仍能被当前任务 alignment 调整，而不是僵硬套模板。

### 6.8 Runtime Enforcement Beyond Prompt

目标：

- Prompt 负责引导，runtime 负责 enforce。

需要硬化的地方：

- alignment stage gate：未形成足够 readiness evidence 时不能生成 READY。
- semantic linter：拒绝通用模板式 bundle。
- evidence gate：GateKeeper pass 必须引用 evidence ledger。
- revision gate：run 后反馈必须能进入 harness revision path。
- provider gate：provider 降级必须可见，不能静默减少控制能力。

验收信号：

- 弱模型即使想提前收尾，也会被服务层状态机和 linter 拦住。
- 运行时事实源来自 artifact 和 ledger，而不是模型自述。

同步重构：

- Prompt / Skill 变更必须同时检查 schema、linter、service stage gate 和 fake executor。
- 新 enforcement 规则先作为新路径硬约束；legacy 数据用兼容读取，不伪造合格状态。
- 测试应覆盖“模型试图提前生成 / 试图无证据 pass / provider 降级”这类负例。

## 7. 推荐路线

### P0: 术语与契约收口

目标：

- 所有文档、README、Web 主文案统一到“外部任务治理 / 证据 / 修订”。
- 删除把 Loopora 讲成 YAML 生成器、角色集合或通用聊天工具的残留心智。

交付：

- README 和 design 总纲完成收口。
- 设计文档明确 bundle 是内部交换单元，循环方案是用户心智。
- Web 主入口不要求用户先理解 bundle。
- 建立本文档中的冲击矩阵，后续实现按矩阵同步重构。

### P1: Evidence Ledger 与 GateKeeper 硬门禁

目标：

- run 之后形成 evidence ledger。
- GateKeeper verdict 必须引用 evidence refs。
- run 详情页以 evidence coverage 和 Gate verdict 为主视图。

交付：

- 稳定 evidence item schema。
- Inspector / GateKeeper 输出契约更新。
- 服务层 GateKeeper pass 校验。
- Web evidence coverage 视图。
- 旧 run 兼容展示为 legacy evidence，不与新 ledger 混成同一质量等级。

当前落点：

- 新 run 已写入 `evidence/ledger.jsonl`。
- `StepHandoff.evidence_refs` 已指向 step evidence item。
- GateKeeper `passed=true` 已经需要上游 evidence refs；首步门禁只接受带可度量 `metric_scores` 的直接证据 claims，缺失时服务层会阻断。
- READY 预览已从 bundle projection 展示控制摘要，避免用户只看到配置结构。
- 后续仍需把 run detail 的默认视图升级为 evidence coverage，而不是只把 ledger 暴露为 artifact。

### P2: Harness Revision Loop

目标：

- run 详情页能基于本次证据启动方案修订。
- revision session 能带入旧 bundle、ledger、verdict 和用户反馈。

交付：

- `run -> revision` 入口。
- revision prompt 与 structured output。
- bundle revision diff 摘要。
- 新 revision 可再次创建并运行。
- 方案库展示 revision lineage，避免 revision 变成孤立 bundle 副本。

当前落点：

- bundle detail 和 run detail 已能创建 revision alignment session。
- revision session 复用 Web alignment，对 bundle 修订带入 source bundle，对 run 修订额外带入 evidence ledger 摘要和 GateKeeper verdict。
- session seed bundle 会写入 `artifacts/bundle.yml`，导入运行继续复用 bundle 生命周期。
- 后续仍需补 revision diff 摘要和方案库 lineage 视图，避免多份 revision 在列表里难以区分。

### P3: Governance Pattern Library

目标：

- 方案库升级成可复用治理模式库。

交付：

- 方案卡片展示 failure mode、evidence style、workflow shape、GateKeeper strictness。
- 支持从 run evidence 派生或标注治理模式。
- 支持按风险和证据类型筛选。
- 方案库、bundle detail、manual import 共享同一 bundle projection。

### P4: Cross-Agent Comparison

目标：

- 同一 harness 可由不同 AI Agent CLI 执行，并比较 evidence coverage。

交付：

- provider capability summary。
- 方案级 / 角色级 executor 切换不改变治理语义。
- provider 降级事件可见。
- 对照 run 报告能比较证据覆盖和 GateKeeper verdict。

## 8. 迁移与兼容策略

| 旧对象 / 旧行为 | 兼容方式 | 新语义 |
|-----------------|----------|--------|
| 旧 bundle 缺少治理摘要 | 可导入、可运行，预览中标记 legacy / 未声明 | 新 bundle 必须能投影 error-control contract |
| 旧 run 没有 evidence ledger | 可继续查看原日志和 artifact，必要时生成 best-effort evidence summary | 新 run 必须写 ledger |
| 旧 GateKeeper verdict 没有 refs | 保留原 verdict 文本，但不显示为强门禁通过 | 新 verdict 必须引用 evidence refs |
| 旧方案库卡片只显示 YAML metadata | 仍可列出，但新 projection 优先展示治理模式 | 新方案卡以风险、证据和 workflow 组织 |
| 外部 Skill 旧输出 | 仍按 bundle contract 校验；缺少新语义时提示建议修订 | 新 Skill 输出应满足 semantic linter |
| 手动创建的 loop | 继续可运行；导出 bundle 时补齐可推导治理 projection | 新手默认不从这里开始 |

迁移原则：

- 优先 lazy migration，不做会阻塞启动的批量迁移。
- 旧数据不伪装成新质量等级。
- 新 UI 可以降低旧数据展示丰富度，但不能让旧数据不可访问。
- 新 API 字段优先 additive；删除或改变语义前必须有兼容期。

## 9. 测试与场景要求

每个演进阶段都必须补充对应的契约测试，而不是只改 UI。

| 阶段 | 必测内容 |
|------|----------|
| Error-control bundle | READY bundle projection、semantic linter、legacy bundle fallback |
| Evidence ledger | evidence item schema、artifact refs、coverage projection |
| GateKeeper hard gate | 无 evidence refs 不能 pass；blocker / residual risk 可见 |
| Harness revision | run evidence + feedback 生成 bundle revision；lineage 可追溯 |
| Web visualization | READY / run detail / 方案库共享 projection，不依赖具体文案 |
| Cross-Agent | provider capability / degradation 可见；同 harness 切换 provider 不改变治理语义 |

场景测试应覆盖完整长期闭环：

`新建任务 -> READY 方案 -> run -> evidence ledger -> GateKeeper verdict -> 用户反馈 -> revision -> 新 run`

## 10. 非目标

- 不把 Loopora 做成通用项目管理系统。
- 不把 evidence ledger 退化成全文日志索引。
- 不把 GateKeeper 变成模型自我感觉总结。
- 不要求所有任务都进入 Loopora。
- 不把方案库变成不可调整的模板市场。
- 不为了跨 Agent 抹平 provider 真实能力差异；差异必须可见。
- 不把旧功能直接废弃换新壳；旧路径必须被收口到同一语义。

## 11. 变更触发

以下变化需要更新本文档：

- 最高产品原则变化。
- bundle 不再是循环方案的内部交换单元。
- evidence ledger 的地位改变。
- GateKeeper 不再承担硬门禁语义。
- run -> revision 不再是核心闭环。
- Web 默认入口不再围绕任务治理展开。
- 任一核心能力改为独立平行系统，而不再复用现有 bundle / run / artifact 生命周期。

以下变化通常不需要更新本文档：

- 页面布局调整。
- prompt 具体文案调整。
- provider 参数细节调整。
- 局部字段扩展。
