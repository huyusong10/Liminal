# Bundles And Alignment

> 最高原则：遵循 `../core-ideas/product-principle.md`。bundle 是 Loop 的内部交换单元；它必须承载可运行的长期任务编排，而不是退化成裸 YAML 或角色配置包。

## 1. 模块职责

本文档定义两条稳定边界：

- Alignment 如何作为一种场景，把当前任务判断收敛成候选 Loop。
- Loopora 如何消费 bundle 并把它物化为可运行 Loop 资产。

它不定义具体对话话术，也不定义某个 provider 的调用细节。

## 2. 核心分工

| 边界 | 负责方 | 稳定职责 |
|------|--------|----------|
| 任务访谈与对齐 | Web alignment session，或外部 AI Agent + repo-local Skill | 与用户确认成功面、假完成、证据、风险和判断方式，产出候选 Loop |
| bundle 生成 | Web alignment session，或外部 AI Agent + repo-local Skill | 输出单文件 YAML bundle |
| bundle 生命周期 | Loopora 本体 | 导入、导出、派生、删除，并把 bundle 物化为本地 Loop 资产 |
| run 执行 | Loopora 本体 | 从 Loop 的 `spec / role definitions / workflow` 自动迭代并留下证据 |

稳定规则：

- `working agreement` 是编译期中间产物，不是运行期资产。
- Loopora 不执行独立 agreement 文件。
- 最终运行输入仍然是 `spec / role definitions / workflow / loop`。
- 外部 Skill 与 Web 内置对齐必须产出同一种 bundle，避免形成两套产品。
- repo-local Skill 是开发态事实源；安装包内必须携带等价 packaged copy，保证从 wheel 安装后仍能安装 / 下载同一份 task-alignment Skill。

## 3. Bundle 契约

bundle 是可读、可运行、可导出、可重新导入的 Loop 交换单元。

它至少包含：

| 区域 | 作用 |
|------|------|
| metadata | 名称、描述、revision、来源 |
| collaboration summary | 本次 Loop 编排结构的可读摘要 |
| loop | workdir、运行参数和 loop 入口 |
| spec | task contract |
| role definitions | 角色模板、task-scoped 判断姿态与证据责任 |
| workflow | 角色顺序、步骤结构、handoff、`collaboration_intent` 与可选误差控制触发器 |

校验规则：

- `spec.markdown` 必须能通过 Loopora 正常 spec 编译器。
- `gatekeeper` completion mode 必须包含可 `finish_run` 的 GateKeeper step。
- Web alignment 生成的 bundle 必须额外通过语义 linter，保护新手路径不被通用模板或假完成污染。

## 4. Loop 承载规则

长期任务编排不能只存在于一个字段或一段 prompt。

| surface | 承载内容 |
|---------|----------|
| `spec` | 成功面、假完成、证据偏好、guardrails、残余风险 |
| `role definitions` | 每个角色如何构建、取证、裁决、移交或阻断 |
| `workflow` | 谁先做、何时并行取证、哪些信息流向下游、何时 GateKeeper 裁决、何时自动迭代、何时用受控 trigger 检查空转、失败或拒绝，以及如何收束或修复 |

稳定规则：

- 三个 surface 缺一不可。
- bundle revision 是版本元数据，不代表 Loopora 拥有用户的 bundle 迭代行为。
- 手动微调允许分别编辑 surface，但导出后的 bundle 必须重新表达同一份治理结构。
- 当任务需要多个证据视角时，alignment 应优先生成带明确 Inspector 责任、`parallel_group` 和 `inputs` 的有界 fan-out / fan-in workflow，而不是复制多个泛化 reviewer。
- `workflow.controls[]` 是高级治理字段，只能表达 run 内部的误差控制信号；它不得退化成通用 cron、webhook、文件监听或自动 Builder 修复。
- controls 只能调用当前 workflow 中已有的 Inspector、Guide 或 GateKeeper，并且必须能解释它控制的具体误差风险，例如无证据进展、角色失败、超时或 GateKeeper 拒绝。

## 5. 生命周期

bundle 生命周期服务于 Loop 编排和交换：

`导入 / 生成 / 派生 -> 校验和预览 -> 物化为 Loop -> 运行 -> 可选导出 bundle 或证据`

稳定规则：

- 导入后的 spec、role definitions、orchestration、loop 默认属于同一 bundle。
- 删除 bundle 默认清理它拥有的底层资产，但不得影响无关手动资产。
- 被 bundle 拥有的底层资产不应被鼓励为互相漂移的零散对象。
- 从现有 loop 派生 bundle 时，派生结果必须回到单文件 YAML。
- 当用户修改 bundle-owned surface 时，bundle revision 也应前进。
- 用户如何基于证据迭代 bundle 属于系统外部行为；Loopora 可提供从已有 bundle 或 run evidence 发起的对话改进入口，但该入口只产出新的候选 bundle，不成为 bundle 生命周期的必经阶段。
- READY 预览与 bundle detail 可以展示版本元数据和 surface diff，但这些内容必须由 source bundle 与当前 bundle 投影得出，不能成为新的事实源。
- 方案库列表可以展示失败模式、证据风格、workflow 形状、GateKeeper 严格度和 version 摘要，但这些内容必须来自 bundle projection，不能成为独立标签系统。

## 6. 入口语义

推荐编排场景：

`新建任务 -> Loop 对话页 -> READY 预览 -> 创建并运行`

专家入口：

`资源与设置 -> 手动创建 -> 选择 spec / roles / workflow，或导入已有 bundle YAML`

稳定承诺：

- 顶层“新建任务”不要求用户先理解 bundle。
- `bundle` 是内部交换单元和专家导入 / 导出格式。
- 方案详情和 run 详情可以提供“对话改进方案”入口；它复用 Web alignment session，从当前 bundle 或 run evidence 生成候选 Loop，随后仍走 READY 预览和导入 / 运行。
- READY 预览必须包含从 bundle 派生的控制摘要，至少覆盖主要风险、证据路径、workflow 形状、GateKeeper 门禁和可选 runtime controls；该摘要是 projection，不是新的事实源。
- 两条路径必须能互相转换：bundle 可以导入成底层资产，手动 loop 也可以派生回 bundle。
- 方案库负责管理、导出、派生和整包删除；列表卡片应优先呈现治理摘要，详情页保留专家 surface 和 YAML 入口。

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
