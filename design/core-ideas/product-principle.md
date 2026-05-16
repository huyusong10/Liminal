# Product Principle

## 1. 最高产品原则

Loopora 是面向长期 AI Agent 任务的本地任务平台。它的最高产品本质是：

> 把人类在未来多轮任务中原本需要反复做的纠偏、质疑、取证、验收和阻断，提前编译成一个可运行的 human-shaped Loop。

它的核心不是“生成 bundle”，也不是“包装一次 Agent 对话”，而是：

> 让用户把 task-scoped judgment 外化为 `spec / roles / workflow / evidence` 结构，把长期任务交给系统按这个 Loop 自动迭代，并提供白盒、可观测、可追溯的证据和裁决。

英文压缩定义：

> Loopora is a local-first platform for composing human-shaped governance loops for long-running AI Agent tasks.

这不是把人类从 loop 中删除，而是把人类从“每轮实时纠偏者”提升为“循环设计者”和“证据审计者”。模型学习通用能力；Loop 学当前任务的判断方式。复杂判断不应该被静默写进模型权重或全局人格记忆，而应在 Agent / Loop 层以局部、显式、可检查、可丢弃的形式继承。

所有产品、接口、运行时和文档设计都必须服务于这条主工作流：

`编排 Loop -> 运行 Loop -> 自动迭代并收集证据 -> 输出运行状态、Loop 裁决与结果`

若下层文档、界面话术或实现取舍与本节冲突，以本节为准。

更完整的愿景叙事见 `../../HUMAN-SHAPED-LOOP.zh-CN.md`。该文保存 human-shaped Loop 的背景、推理链和长期协作愿景；本文件只保留可作为设计约束的压缩原则。

## 1.0 Human-Shaped Loop 原则

传统 human-in-the-loop 假设人类在执行过程中反复回来纠偏：

`Agent 行动 -> 人类判断 -> Agent 修正 -> 人类再判断`

Loopora 的范式是 human-shaped loop：

`人类先外化判断方式 -> Loopora 编译判断结构 -> Agent 在结构内自动迭代 -> 人类审计证据、裁决和残余风险`

稳定原则：

- Loopora 自动化的不是单纯产出，而是长期任务中可被结构化的一部分人类判断。
- 简单循环延长任务时间；Loopora 的 Loop 约束误差传播路径。
- 没有治理结构的 loop 是开盲盒；有治理结构的 Loop 是误差减速器。
- Loopora 不承诺消灭长期任务误差；它的目标是让误差更早暴露、更难伪装成完成、更容易被下一轮纠正。
- 可量化判断应优先沉淀为 benchmark、contract test、schema、lint 或 proof harness；Loopora 主要处理尚不能可靠标量化、但可以结构化、取证化、角色化和裁决化的复杂判断。
- 复杂判断通常不是单一分数，而是偏序：真实闭环优先于漂亮假完成，强证据优先于乐观叙事，可接受残余风险必须显式暴露，不可接受风险必须阻断。
- Alignment 的价值是帮助用户通过案例、对比和 tradeoff 自省 task-scoped judgment；runtime 的价值是让这份 judgment 真正约束 Agent，而不是停留在 prompt 文案。

Loopora 应把长期任务中反复出现的人类控制信号投影到可运行 surface，而不是只把它们写成说明文字：

| 控制信号 | 产品含义 | 主要投影 |
| --- | --- | --- |
| 拒绝 | 看起来完成但不算完成。 | task contract、fake-done、blocking rules |
| 信任 | 哪些证据足够硬，哪些只是自述。 | evidence path、coverage、artifact refs |
| 转向 | 下一轮应回到哪个缺口。 | execution strategy、workflow handoff、Guide / Inspector feedback |
| 阻断 | 哪些风险不能包装成完成。 | GateKeeper、hard constraints、blocking issues |
| 收尾 | 哪些已证明，哪些只能作为显式残余风险。 | task verdict、residual risk、result summary |

因此，默认产品体验和运行时能力都应能回答同一组问题：这套 Loop 会拒绝什么、信任什么、优先补什么、何时阻断、怎样收尾。不能回答这些问题的功能，即使看起来增强了自动化，也不应进入默认主路径。

## 1.1 主次关系

核心概念必须围绕主工作流和 human-shaped Loop，而不是围绕某个取得 Loop 的场景。

| 层级 | 说明 | 示例 |
|------|------|------|
| 主工作流 | Loopora 必须稳定支持的 Loop 生命周期 | 编排 Loop、运行 Loop、自动迭代、收集证据、运行状态、Loop 裁决 |
| 编排场景 | 用户如何得到或调整 Loop | Web 问答创建、手动编排、导入 YAML、从已有结果对话改进 |
| 交换与调试资产 | 支撑场景和可追溯性的技术对象 | bundle、YAML、READY、alignment session、Bundle ID |

稳定规则：

- `Loop` 是平台主对象；它表达长期任务如何被执行、检查、裁决和停止。
- `bundle` / YAML 是 Loop 的交换格式和专家资产，不是主工作流本身。
- Web 问答、手动编排、导入 YAML、对话改进都是编排或调整 Loop 的场景；它们不改变主工作流。
- run 后用户是否以及如何改变 Loop，是用户掌控的高阶行为。Loopora 可以提供导入、手动编辑和对话改进入口，但不能把这些入口写成默认生命周期阶段。

## 1.2 五分钟上手原则

Loopora 可以越来越强，但默认第一次使用必须仍然像一句话启动长期任务。

稳定原则：

- 新用户只需要理解：Loop、运行、证据、运行状态、Loop 裁决。
- 高级能力必须由 Loopora 编译进 Loop，而不是要求用户手动配置一套 workflow 平台。
- 任何新增能力进入默认主路径前，都必须证明它服务于长期任务的误差控制，并且不增加首次使用心智负担。
- `workflow controls`、触发器、计时器、并行检视、信息流策略和 YAML 操作属于专家预览、方案详情或导入 / 导出路径；它们不应成为新手必学概念。
- README、教程和 Web 首屏必须继续围绕“Loop / 运行 / 证据 / 运行状态 / Loop 裁决”，而不是把内部字段当作入口词。中文 Web 页面只有 `Loop` 作为稳定英文主对象词；`Runs` 必须显示为“运行”。

## 2. 为什么这不是普通 Agent 插件

传统 Agent 插件通常在 Agent 内部增强能力：加入 skill、命令、角色、检查表或优秀协作模式。它们让 Agent 更有纪律，但控制权仍主要留在 Agent 上下文里。

Loopora 的差异在于把长期任务的编排、运行和观察外部化：

| 风险 | 只靠 Agent 上下文 | Loopora 的平台能力 |
|------|-------------------|--------------------|
| 目标漂移 | 依赖模型记住原意 | `spec` 冻结任务契约和边界 |
| 假完成 | 依赖 prompt 要求自查 | `GateKeeper` 与证据门槛阻断收尾 |
| 判断混杂 | 一个 Agent 同时写、查、判 | `roles` 分离构建、检查、裁决和纠偏 |
| 循环空转 | 重复调用但新证据不足 | `workflow` 规定何时取证、何时停止 |
| 黑盒执行 | 只能读日志或模型总结 | evidence ledger、artifacts、coverage 和 verdict 形成白盒观察面 |
| 经验丢失 | 反馈变成下一段聊天 | Loop 与 bundle 可导出，用户可在系统外自行决定如何调整 |

因此，Loopora 不承诺所有任务都比插件更适合。它适合那些需要把长期任务的编排、判断、证据和停止条件从一次对话里外化出来的任务。

## 3. 核心对象

Loopora 的核心对象是 `Loop`。

一个 Loop 必须同时表达三类运行输入，并在 run 中生成证据输出；用户最终看到的结果必须同时区分“系统是否跑完”和“证据是否证明 Loop 达标”：

| 类型 | surface | 职责 |
|------|---------|------|
| 运行输入 | `spec` | 冻结任务范围、成功面、假完成、guardrails、证据偏好、残余风险政策、执行优先级与判断取舍 |
| 运行输入 | `roles` | 冻结各 AI Agent 角色在本任务中的构建、检查、裁决、纠偏姿态和本地治理责任 |
| 运行输入 | `workflow` | 冻结判断顺序、handoff、证据流、本地治理检查点、纠偏入口、自动迭代和收束方式 |
| 观察输出 | `evidence` | 记录每轮行动、检查、裁决、失败原因和未证明内容 |
| 结果投影 | 运行状态 | 说明本次 run 是否正常结束、失败、停止或超时 |
| 结果投影 | Loop 裁决 | 说明证据是否证明 Loop 达标、未达标、证据不足或存在残余风险 |

前三者定义 Loop 如何运行；`evidence` 让用户复盘一次 run 是否可信。运行状态不能替代 Loop 裁决：例如 `rounds` 模式跑满轮数只说明 run 正常收束，不等于 Loop 被证明完成。

`bundle` 是把上述结构文件化、导入、导出和携带版本元数据的交换单元。它服务于 Loop 编排，不替代 Loop 成为用户主对象。

## 4. 默认用户心智

新用户不应该被要求先理解 `bundle`、`spec`、`roles`、`workflow` 或 provider 参数。

默认心智应是：

1. 我有一个长期任务。
2. 我需要编排一个 Loop，让系统知道如何执行、检查、裁决和停止。
3. Loopora 可以通过问答帮我创建 Loop；我也可以手动编排或导入已有 YAML。
4. 我审查并认可 Loop 的任务目标、风险、执行策略、证据路径和裁决方式。
5. Loopora 运行这个 Loop，并按角色和 workflow 自动迭代。
6. 我查看白盒证据、运行状态和 Loop 裁决结果。
7. 如果我不满意，可以手动改 Loop、导入新 YAML，或再次通过对话让 Agent 生成候选改进；这些都是编排场景，不是 run 的默认阶段。

`bundle` 是专家资产和内部交换单元；默认界面应优先使用“Loop / 运行 / 证据 / 运行状态 / Loop 裁决”。

## 5. 反目标

Loopora 不应退化成：

- role zoo：堆角色，但任务判断不可解释。
- prompt pack：写更长提示词，但没有外部运行面和证据闭环。
- loop script：重复执行命令，但缺少 task contract、GateKeeper 和证据闭环。
- chat wrapper：提供通用聊天体验，但绕过 Loop 编排、run 生命周期和 evidence。
- asset CRUD console：暴露大量内部对象，让用户忘记自己是在编排和运行长期任务。

## 6. 设计判断式

任何产品和实现决策都应优先问：

1. 这是否服务于“编排 Loop -> 运行 Loop -> 自动迭代并收集证据 -> 输出运行状态、Loop 裁决与结果”的主工作流？
2. 这是否让“什么算真实进展 / 假完成 / 可接受风险”更可检查？
3. 这是否产生新证据，而不只是更长日志？
4. 这是否增强白盒观察面，让用户知道改了什么、检查了什么、为什么通过或未通过？
5. 这是否把取得或调整 Loop 的场景留在次级层级，而不是误写成主工作流？
6. 这是否避免把内部概念压到新手主路径？

若答案是否定的，它不应进入默认体验。

新增高级能力还必须额外回答：

7. 它是否仍然保持五分钟上手？
8. 它是否只是帮助控制长期任务误差，而不是把 Loopora 推向通用自动化平台？
