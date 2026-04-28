# Bundles And Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。bundle 是循环方案的内部交换单元；它必须承载外部任务治理，而不是退化成裸 YAML 或角色配置包。

## 1. 模块职责

本文档定义两条稳定边界：

- Alignment 如何把当前任务治理问题收敛成循环方案。
- Loopora 如何消费 bundle 并把它物化为可运行资产。

它不定义具体对话话术，也不定义某个 provider 的调用细节。

## 2. 核心分工

| 边界 | 负责方 | 稳定职责 |
|------|--------|----------|
| 任务访谈与对齐 | Web alignment session，或外部 AI Agent + repo-local Skill | 与用户确认成功面、假完成、证据、风险和判断方式 |
| bundle 生成 | Web alignment session，或外部 AI Agent + repo-local Skill | 输出单文件 YAML bundle |
| bundle 生命周期 | Loopora 本体 | 导入、导出、派生、删除，并把 bundle 物化为本地资产 |
| run 执行 | Loopora 本体 | 从导入后的 `spec / role definitions / workflow` 运行 loop 并留下证据 |
| bundle revision | Web alignment session + bundle 生命周期 | 读取旧 bundle、run evidence 和用户反馈，产出下一版完整 bundle |

稳定规则：

- `working agreement` 是编译期中间产物，不是运行期资产。
- Loopora 不执行独立 agreement 文件。
- 最终运行输入仍然是 `spec / role definitions / workflow / loop`。
- 外部 Skill 与 Web 内置对齐必须产出同一种 bundle，避免形成两套产品。

## 3. Bundle 契约

bundle 是可读、可运行、可修订的单文件交换单元。

它至少包含：

| 区域 | 作用 |
|------|------|
| metadata | 名称、描述、revision、来源 |
| collaboration summary | 本次任务治理结构的可读摘要 |
| loop | workdir、运行参数和 loop 入口 |
| spec | task contract |
| role definitions | 角色模板、task-scoped 判断姿态与证据责任 |
| workflow | 角色顺序、步骤结构、handoff、`collaboration_intent` 与可选误差控制触发器 |

校验规则：

- `spec.markdown` 必须能通过 Loopora 正常 spec 编译器。
- `gatekeeper` completion mode 必须包含可 `finish_run` 的 GateKeeper step。
- Web alignment 生成的 bundle 必须额外通过语义 linter，保护新手路径不被通用模板或假完成污染。

## 4. 治理承载规则

任务治理不能只存在于一个字段或一段 prompt。

| surface | 承载内容 |
|---------|----------|
| `spec` | 成功面、假完成、证据偏好、guardrails、残余风险 |
| `role definitions` | 每个角色如何构建、取证、裁决、移交或阻断 |
| `workflow` | 谁先做、何时并行取证、哪些信息流向下游、何时 GateKeeper 裁决、何时用受控 trigger 检查空转、失败或拒绝，以及如何收束或修复 |

稳定规则：

- 三个 surface 缺一不可。
- bundle revision 默认按整包重编译，而不是只改某一个 surface。
- 手动微调允许分别编辑 surface，但导出后的 bundle 必须重新表达同一份治理结构。
- 当任务需要多个证据视角时，alignment 应优先生成带明确 Inspector 责任、`parallel_group` 和 `inputs` 的有界 fan-out / fan-in workflow，而不是复制多个泛化 reviewer。
- `workflow.controls[]` 是高级治理字段，只能表达 run 内部的误差控制信号；它不得退化成通用 cron、webhook、文件监听或自动 Builder 修复。
- controls 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper，并且必须能解释它控制的具体误差风险，例如无证据进展、角色失败、超时或 GateKeeper 拒绝。

## 5. 生命周期

bundle 生命周期按整包表达：

`导入 -> 查看 -> 运行 -> 证据 -> 对话修订 / 手动修订 -> 下一版 bundle -> 再运行`

稳定规则：

- 导入后的 spec、role definitions、orchestration、loop 默认属于同一 bundle。
- 删除 bundle 默认清理它拥有的底层资产，但不得影响无关手动资产。
- 被 bundle 拥有的底层资产不应被鼓励为互相漂移的零散对象。
- 从现有 loop 派生 bundle 时，派生结果必须回到单文件 YAML。
- 当用户修改 bundle-owned surface 时，bundle revision 也应前进。
- 对话修订必须生成新的完整 bundle revision，不能只把反馈追加成聊天记录。
- 对话修订的输入可以来自 bundle detail、run detail 或导入后的方案；这些入口必须复用同一个 alignment session 能力。
- 从 run 修订时必须带入 source bundle、run evidence ledger、GateKeeper verdict 和用户反馈摘要。

## 6. 入口语义

推荐入口：

`新建任务 -> 循环方案对话页 -> READY 预览 -> 创建并运行`

专家入口：

`资源与设置 -> 手动创建 -> 选择 spec / roles / workflow，或导入已有 bundle YAML`

稳定承诺：

- 顶层“新建任务”不要求用户先理解 bundle。
- `bundle` 是内部交换单元和专家导入 / 导出格式。
- READY 预览必须包含从 bundle 派生的控制摘要，至少覆盖主要风险、证据路径、workflow 形状、GateKeeper 门禁和可选 runtime controls；该摘要是 projection，不是新的事实源。
- 两条路径必须能互相转换：bundle 可以导入成底层资产，手动 loop 也可以派生回 bundle。
- 方案库负责管理、导出、派生、整包删除和 revision 入口；用户从任何方案详情都应能进入“用对话修订方案”。

## 7. 变更触发

以下变化需要更新本文档：

- bundle 不再是单文件 YAML
- working agreement 的运行期地位变化
- bundle 生命周期语义变化
- Web alignment、外部 Skill 与 Loopora 本体的边界变化
- 治理结构不再由 `spec / role definitions / workflow` 共同承载

以下变化通常不需要更新本文档：

- bundle 字段小幅扩展
- 对齐话术调整
- Web / CLI 页面布局调整
