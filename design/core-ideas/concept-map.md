# Concept Map and Flow

> 最高原则：遵循 `product-principle.md`。本文只澄清 Loopora 的概念层级和主生命周期，不新增运行契约，也不替代各模块 detailed design。

## 1. 目标

Loopora 的稳定主线只有一条：

`任务输入 -> 对齐循环方案 -> 运行并收集证据 -> 基于证据修订方案`

本文解决的是命名层级问题：同一条主线在产品、对齐、运行、证据和修订层会出现不同术语。阅读或设计新能力时，应先判断一个术语属于哪一层，再决定它是否应该暴露给默认用户路径。

## 2. 概念层级

| 层级 | 默认用户语言 | 内部或专家术语 | 稳定职责 |
| --- | --- | --- | --- |
| 产品心智 | 任务、循环方案、证据、修订、方案库 | harness | 让用户理解自己是在治理长期任务，而不是配置角色或提示词 |
| 对齐编译 | 循环方案对话、确认方案、READY 预览 | `alignment session`, `working agreement`, `bundle` | 把当前任务的判断方式收敛成可校验、可预览的方案文件 |
| 运行资产 | 可运行方案 | `spec`, `role definitions`, `roles`, `workflow`, `orchestration`, `loop definition` | 把 bundle 物化成可重复执行的本地治理资产 |
| 执行复盘 | 一次运行、证据、裁决 | `run`, `run contract`, `StepContextPacket`, `StepHandoff`, `evidence ledger`, `coverage`, `GateKeeper verdict` | 冻结一次执行的事实源，回答证明了什么、没证明什么、为什么过或没过 |
| 修订演进 | 基于证据修订方案 | `revision session`, `source bundle`, `revised bundle`, `lineage` | 用 run evidence 和用户反馈生成下一版 harness，而不是追加一段 prompt |

稳定规则：

- 默认入口优先使用产品心智语言；专家入口可以暴露内部术语。
- Web 可以隐藏内部术语，但每个可见结论必须能追溯到 `spec / roles / workflow / evidence / revision` 中的稳定 surface。
- 内部术语不能变成相互竞争的事实源；它们只是同一治理结构在不同阶段的投影。

## 3. Canonical Lifecycle

```text
用户任务
-> alignment session
-> working agreement
-> YAML bundle
-> READY preview
-> import / materialize loop
-> run
-> evidence ledger
-> GateKeeper verdict
-> revision
-> next bundle
```

逐步语义：

| 阶段 | 语义 | 退出条件 |
| --- | --- | --- |
| 用户任务 | 用户描述长期任务与 workdir | 足以启动对齐，不要求用户理解 bundle |
| `alignment session` | Web 或外部 Agent 与用户对齐治理问题 | 形成需要确认或继续澄清的判断结构 |
| `working agreement` | 编译前的人类可读检查点 | 用户明确确认，或继续澄清 |
| `YAML bundle` | 单文件循环方案交换单元 | bundle 结构、spec 编译和语义 linter 通过 |
| READY preview | 已校验 bundle 的只读投影 | 用户选择导入、创建并运行，或继续修订 |
| import / materialize loop | 把 bundle 物化为 spec、role definitions、workflow、loop | 底层资产创建完成并保持 bundle 生命周期关联 |
| `run` | loop 的一次具体执行 | 收敛到 succeeded、failed、stopped 等单一终态 |
| `evidence ledger` | 本次 run 的证明项事实源 | GateKeeper 与复盘结论能引用具体 evidence item |
| `GateKeeper verdict` | 基于证据的收束裁决 | 通过 evidence gate，或阻断并进入下一轮 / 失败 |
| `revision` | 读取旧 bundle、run evidence 和用户反馈 | 生成下一版完整 bundle，而不是只追加聊天记录 |

## 4. 易混边界

| 容易混淆 | 稳定区分 |
| --- | --- |
| `循环方案` vs `bundle` | 循环方案是用户心智；bundle 是内部和专家路径使用的 YAML 交换单元。 |
| `bundle` vs `loop` | bundle 是整包生命周期资产；loop 是导入后可重复执行的本地模板。 |
| READY vs imported | READY 只表示 bundle 文件存在且通过校验；不表示已经导入、创建 loop 或启动 run。 |
| `workflow` vs `orchestration` | workflow 是角色与步骤结构；orchestration 是保存、复用和编辑该结构的资产边界。 |
| `spec` vs `workflow` | spec 冻结任务契约、成功面、假完成、证据偏好和边界；workflow 决定判断顺序、handoff 和收束方式。 |
| `posture` vs `contract` | posture 是本任务里用户如何判断风险和证据的信号；它必须投影到 `spec / roles / workflow`，不能在 run 内静默改写已确认 contract。 |
| `evidence ledger` vs 日志 | evidence ledger 是裁决和修订的证明事实源；日志、事件和 raw output 是追溯材料。 |
| `revision` vs 再提示 | revision 修改下一版 harness；它不是把反馈追加到同一个 Agent prompt。 |

## 5. 读法

- 讨论产品方向或用户心智时，先读本文和 `product-principle.md`。
- 讨论五个治理 surface 与测试锚点时，读 `core-contract.md`。
- 讨论 alignment、bundle、Web READY 或 revision 细节时，读 `task-scoped-alignment.md`、`../detailed-design/08-bundles-and-alignment.md` 和 `../detailed-design/09-web-bundle-alignment.md`。
- 讨论运行、证据、GateKeeper 和复盘时，读 `../detailed-design/02-orchestration-service.md`、`../detailed-design/04-persistence-and-reliability.md`、`../detailed-design/06-workflow-and-prompts.md` 和 `../detailed-design/07-observability-and-diagnostics.md`。

## 6. 变更触发

以下变化需要更新本文：

- 默认主生命周期改变。
- 用户默认语言与内部术语的边界改变。
- `bundle / loop / run / revision` 等核心概念的层级关系改变。
- 新增一层稳定治理边界。

以下变化通常不需要更新本文：

- 字段小幅扩展。
- 页面文案或布局调整。
- provider 参数、prompt 文案或日志字段细节变化。
