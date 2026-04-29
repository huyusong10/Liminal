# Concept Map and Flow

> 最高原则：遵循 `product-principle.md`。本文只澄清 Loopora 的概念层级、主工作流和场景边界，不新增运行契约，也不替代各模块 detailed design。

## 1. 目标

Loopora 的稳定主工作流是：

`编排 Loop -> 运行 Loop -> 自动迭代并收集证据 -> 输出证据裁决与结果`

本文解决两个层级问题：

- 核心概念必须集中在主工作流上：长期任务、Loop、Run、自动迭代、证据、裁决、结果。
- Web 问答创建、手动编排、导入 YAML、对话改进既重要，也必须保留，但它们是取得或调整 Loop 的场景，不是主工作流本身。

## 2. 默认用户概念

| 用户概念 | 稳定含义 | 系统映射 |
| --- | --- | --- |
| 长期任务 | 用户想交给 AI Agent 持续推进、需要多轮判断的工作。 | 用户输入、workdir、后续 `spec` 输入 |
| Loop | 一套可运行的长期任务编排，定义如何执行、检查、裁决、迭代和停止。 | `loop definition` 加上 `spec / roles / workflow` |
| 运行 | 按某个 Loop 执行一次长期任务。 | `run` record、run contract、events、artifacts |
| 自动迭代 | 系统按 Loop 中的 roles 和 workflow 多轮推进，直到收束或失败。 | iteration、workflow steps、controls、completion mode |
| 证据 | run 中留下的可追溯事实，说明做了什么、检查了什么、证明了什么。 | evidence ledger、artifact refs、coverage |
| 裁决 | GateKeeper 或 rounds completion 对 run 是否可收束的判断。 | GateKeeper verdict、runtime evidence gate、run status |
| 结果 | 用户可读的本次运行结论，包括通过、未通过、未证明内容和残余风险。 | key takeaways、coverage projection、verdict context |

稳定规则：

- `Loop` 是默认用户主对象；“循环方案”可以作为中文解释，但文档应避免让 bundle/YAML 看起来比 Loop 更核心。
- `bundle`、YAML、READY、Bundle ID、source bundle id、revision、surface diff 是交换、状态或调试对象，不是默认用户概念。
- `spec / roles / workflow` 是专家可见的 Loop 运行面；默认用户不需要先理解它们才能开始。
- “对话改进方案”是用户主动调整 Loop 的一种场景，不是 run 完成后的默认阶段。

## 3. 专家概念

专家概念不能压成一张无层级列表；应按主对象和支撑对象分组。

| 对象轴 | 一级概念 | 稳定含义 |
| --- | --- | --- |
| 主工作流 | `loop definition` | 可重复运行的长期任务编排模板，绑定 workdir、runtime 策略和治理 surface。 |
| 主工作流 | `run` | 某个 Loop 的一次冻结执行实例。 |
| 主工作流 | `iteration` | run 内部的一轮角色执行和证据积累。 |
| 治理 surface | `spec` | 任务契约、成功面、假完成风险、guardrails、证据偏好与残余风险。 |
| 治理 surface | `role definitions` / `roles` | 各角色在本任务中的构建、取证、裁决、纠偏姿态。 |
| 治理 surface | `workflow` | 步骤顺序、handoff、fan-out / fan-in、controls 与收束方式。 |
| 证据 surface | `evidence` | ledger、coverage、artifact refs 与裁决事实源。 |
| 打包与交换 | `bundle` | 单文件 YAML 交换单元，承载完整 Loop 编排、metadata 与来源关系。 |
| 编排资产 | `orchestration` | 可复用 workflow 与 prompt 资产边界。 |

层级规则：

- `GateKeeper` 不能和 `roles` 并列。它在 `roles` 里是一个 role archetype，在 `workflow` 里可以是 finish step，在 `evidence` / run result 里表现为 verdict。
- `Builder / Inspector / GateKeeper / Guide / Custom Restricted` 是 role archetype，归属于 `roles`。
- `steps / parallel_group / inputs / handoff / controls / finish_run` 归属于 `workflow`。
- `evidence ledger / coverage / artifact refs / GateKeeper verdict` 归属于 `evidence`。
- `Bundle ID / source bundle id / revision / lineage / surface diff` 是 `bundle` 的属性或投影，不是独立概念。

## 4. 内部持有概念

| 内部概念 | 稳定职责 | 默认可见性 |
| --- | --- | --- |
| `alignment session` | Web 问答创建或改进 Loop 的状态容器。 | 默认隐藏为“方案对话”；专家可从历史和调试材料追踪。 |
| `working agreement` | 编译 bundle 前的人类可读检查点。 | 默认显示为确认摘要，不作为运行资产。 |
| `READY` | bundle 文件存在且通过硬校验的内部状态。 | 默认表达为“Loop 已准备好，可以创建并运行”。 |
| `validation result` | bundle 硬校验结果。 | 默认摘要化；调试区可看细节。 |
| `bundle path` | READY bundle 文件事实源。 | 源文件操作区可见。 |
| `run contract` | run 开始时冻结的执行契约。 | 复盘、测试和调试使用。 |
| `StepContextPacket` | 每个 step 的结构化输入。 | 内部持有。 |
| `StepHandoff` | 每个 step 的结构化输出与 evidence refs。 | 内部持有，必要时从证据追查。 |
| `manifest / events / invocations` | alignment 或 run 的恢复与调试材料。 | 执行详情或调试区可见。 |

## 5. 主工作流

主工作流描述 Loopora 作为长期任务平台必须持续成立的生命周期。

```text
编排 Loop
-> 运行 Loop
-> 系统按 roles / workflow 自动迭代
-> 每个 step 和 iteration 留下 evidence
-> GateKeeper 或 completion mode 收束
-> 用户查看证据裁决与结果
```

稳定规则：

- 编排方式可以不同，但进入运行后必须落到同一套 Loop / run / evidence 语义。
- 每个可见结果必须能追溯到 `spec / roles / workflow / evidence`，而不是只追溯到聊天记录或 UI 摘要。
- 自动迭代必须以新证据、handoff 或裁决推进为理由；没有新证据的重复调用不是 Loopora 的核心价值。
- 用户调整 Loop 后再次运行，仍然回到同一主工作流；调整动作本身不成为 run 生命周期的一部分。

## 6. 场景：如何取得 Loop

这些场景服务于“编排 Loop”，不是主工作流的替代品。

### 6.1 Web 问答创建

```text
描述长期任务
-> 回答会影响 Loop 形状的问题
-> 确认 working agreement
-> 生成 bundle
-> READY 预览
-> 创建 Loop 并运行
```

适合新用户或任务判断尚未成形的场景。目标是让用户不需要先理解 YAML、bundle 或 workflow controls。

### 6.2 手动编排

```text
创建或选择 spec
-> 创建或选择 role definitions
-> 创建或选择 workflow / orchestration
-> 创建 Loop
-> 运行
```

适合专家已经知道要如何组织任务契约、角色和 workflow 的场景。

### 6.3 导入 YAML

```text
提供 bundle YAML 或路径
-> 校验和预览
-> 导入并物化为 spec / roles / workflow / loop
-> 运行
```

适合用户已经从外部 Agent、文件系统或其他项目获得 bundle 的场景。

## 7. 场景：如何调整已有 Loop

这些场景服务于“重新编排 Loop”，不是 Loopora 自动 run 生命周期的一部分。

| 场景 | 用户动作 | Loopora 职责 |
| --- | --- | --- |
| 手动修改 | 用户直接编辑 spec、roles、workflow 或相关资源。 | 校验、保存、更新 bundle version 元数据，并保持可导出。 |
| 导入替换 YAML | 用户在系统外得到新 bundle 后导入。 | 校验、预览、显式替换或创建新 Loop。 |
| 对话改进 | 用户从 bundle detail 或 run evidence 发起问答，让 Agent 生成候选 bundle。 | 携带 source context，生成候选 bundle，回到 READY 预览和导入 / 运行。 |

稳定规则：

- Loopora 可以提供调整 Loop 的工具，但不拥有“应该如何迭代 bundle”的产品判断；这个判断由用户掌控。
- 对话改进不能被写成“默认后续动作”“默认后续阶段”或主生命周期。
- 无论通过哪种方式调整，新的候选结果只有在通过校验并导入后才进入主工作流。

## 8. 易混边界

| 容易混淆 | 稳定区分 |
| --- | --- |
| `Loop` vs `bundle` | Loop 是长期任务编排主对象；bundle 是导入、导出和携带完整 Loop 编排的 YAML 交换单元。 |
| `Loop` vs `run` | Loop 是可重复运行模板；run 是一次冻结执行实例。 |
| `bundle` vs `Bundle ID` | bundle 是对象；Bundle ID 只是该对象的标识属性。 |
| `GateKeeper` vs `roles` | roles 是集合 / surface；GateKeeper 是其中一种 role archetype，也可在 workflow 和 evidence 中形成 step / verdict 投影。 |
| READY vs imported | READY 只表示 bundle 文件存在且通过校验；不表示已经导入、创建 Loop 或启动 run。 |
| `workflow` vs `orchestration` | workflow 是角色与步骤结构；orchestration 是可复用资产边界。 |
| `spec` vs `workflow` | spec 冻结任务契约、成功面、假完成、证据偏好和边界；workflow 决定判断顺序、handoff 和收束方式。 |
| `posture` vs `contract` | posture 是本任务里用户如何判断风险和证据的信号；它必须投影到 `spec / roles / workflow`，不能在 run 内静默改写已确认 contract。 |
| `evidence ledger` vs 日志 | evidence ledger 是裁决和证据结论的证明事实源；日志、事件和 raw output 是追溯材料。 |
| `bundle revision` vs 用户迭代行为 | bundle revision 是版本元数据；用户如何迭代 Loop 发生在系统外部或用户主动发起的编排场景中。 |

## 9. 读法

- 讨论产品方向或用户心智时，先读本文和 `product-principle.md`。
- 讨论 Loop 的治理 surface 与测试锚点时，读 `core-contract.md`。
- 讨论 Web 问答创建、bundle、READY 或导入 / 导出入口时，读 `task-scoped-alignment.md`、`../detailed-design/08-bundles-and-alignment.md` 和 `../detailed-design/09-web-bundle-alignment.md`。
- 讨论运行、自动迭代、证据、GateKeeper 和复盘时，读 `../detailed-design/02-orchestration-service.md`、`../detailed-design/04-persistence-and-reliability.md`、`../detailed-design/06-workflow-and-prompts.md` 和 `../detailed-design/07-observability-and-diagnostics.md`。

## 10. 变更触发

以下变化需要更新本文：

- 默认用户概念、专家概念或内部概念的层级关系改变。
- 主工作流发生改变。
- 新增或删除取得 / 调整 Loop 的稳定场景。
- `loop / run / evidence / bundle` 等核心对象的责任边界改变。
- 新增一层稳定治理边界。

以下变化通常不需要更新本文：

- 字段小幅扩展。
- 页面文案或布局调整。
- provider 参数、prompt 文案或日志字段细节变化。
