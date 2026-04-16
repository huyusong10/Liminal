# Workflow And Prompts

## 1. 模块职责

本文档定义两类稳定资产：

- `workflow`
- `prompt`

它回答的是“编排资产对外承诺什么”，而不是“资产如何落盘”。

## 2. 资产契约

| 资产 | 输入 | 输出 | 稳定承诺 |
|------|------|------|----------|
| orchestration asset | 名称、描述、workflow、prompt 资产 | 可复用编排定义 | 可被 loop 引用，也可被复制为新编排 |
| role definition asset | 名称、角色模板、默认执行配置、prompt 资产 | 可复用角色模版 | 在 orchestration 中被选入后，会复制成角色快照 |
| workflow snapshot | roles 与 steps | 运行期角色顺序与依赖关系 | run 开始后不再随外部编辑漂移 |
| prompt asset | 元数据头 + Markdown 正文 | 角色运行提示 | 必须声明版本与适用角色模板 |

补充说明：

- 内置 prompt 资产允许提供按语言区分的内容变体，只要 front matter 版本与 archetype 契约保持一致。

## 3. Workflow 结构

workflow 保持两层结构：

- `roles[]`
- `steps[]`

### 3.1 roles 契约

每个 role 至少包含：

| 字段 | 含义 |
|------|------|
| `id` | role 在当前 workflow 内的稳定标识 |
| `name` | 用户可读名称 |
| `archetype` | 角色模板 |
| `prompt_ref` | 该 role 使用的 prompt 资产内部引用；运行时和持久化会使用它，但角色定义页不要求用户手工命名 |
| `executor_kind` / `executor_mode` | 该 role 默认使用的执行方式；内置执行器支持 `preset` 与 `command`，`custom` 执行器只支持 `command` |
| `command_cli` / `command_args_text` | 可选，仅直接命令模式使用；`custom` 执行器必须依赖它们 |
| `model` | 可选，role 级默认模型 |
| `reasoning_effort` | 可选，role 级默认推理配置 |
| `role_definition_id` | 可选，表明它来源于某个角色定义 |

### 3.2 steps 契约

每个 step 至少包含：

| 字段 | 含义 |
|------|------|
| `id` | step 在当前 workflow 内的稳定标识 |
| `role_id` | 指向某个 role |
| `enabled` | 是否参与执行 |
| `on_pass` | 可选，仅 GateKeeper 使用，用于声明通过后的收敛行为 |
| `model` | 可选，step 级模型覆盖 |

## 4. 角色原型

系统固定支持五种角色模板：

| 模板 | 职责 |
|------|------|
| `builder` | 改动工作区并推进实现 |
| `inspector` | 收集证据并执行检查 |
| `gatekeeper` | 根据证据给出通过裁决 |
| `guide` | 在停滞或回退时给出方向调整 |
| `custom` | 以最低权限读取现状、补充分析并给出建议 |

兼容层仍接受旧别名，但运行时会收敛为上述稳定模板。

## 4.1 执行器契约

系统固定支持四类执行器：

| 执行器 | 模式 | 稳定承诺 |
|--------|------|----------|
| `codex` | `preset` / `command` | 预设模式由系统拼装 CLI；直接命令模式允许用户覆盖 argv 模版 |
| `claude` | `preset` / `command` | 预设模式由系统拼装 CLI；直接命令模式允许用户覆盖 argv 模版 |
| `opencode` | `preset` / `command` | 预设模式由系统拼装 CLI；直接命令模式允许用户覆盖 argv 模版 |
| `custom` | `command` only | 系统不再拼装预设 CLI；调用方必须提供可执行文件与 argv 模版，并在结束前把 JSON 结果写到 `{output_path}` |

补充约束：

- `custom` 执行器保存前必须处于 `command` 模式。
- 直接命令模式下，`command_cli` 与 `command_args_text` 是真正的执行来源；模型和推理强度只能作为只读参考或占位符输入，不再单独驱动命令装配。
- 角色定义页的“最终命令预览”必须与运行时实际命令装配保持同一语义顺序。
- 角色定义页在选择不同角色模板时，必须展示该模板对应的说明、适用建议与约束提醒；这些说明只改变界面引导，不改变底层 archetype 契约。
- 已保存的 role definition 在编辑页必须保持 archetype 固定；只有新建角色流程才能重新选择角色模板。

## 5. 验证规则

### 5.1 Workflow 基础校验

workflow 保存前必须满足：

- 至少 1 个 role
- 至少 1 个 step
- 每个 step 引用的 `role_id` 都存在

### 5.2 Completion Mode 约束

| completion mode | 约束 |
|-----------------|------|
| `gatekeeper` | 必须存在可在通过时结束流程的 GateKeeper 步骤 |
| `rounds` | 允许没有 GateKeeper，达到计划轮数即可收敛 |

额外约束：

- 只有 `gatekeeper` step 可以声明 `on_pass=finish_run`
- `custom` role 可以自由进入编排，但不能成为收敛裁决入口

### 5.3 Prompt 校验

prompt 资产必须满足：

- 包含结构化元数据头
- 声明受支持的版本
- 声明与 role 一致的角色原型
- 正文非空

## 6. 模型解析优先级

模型选择优先级固定为：

| 优先级 | 来源 |
|--------|------|
| 1 | `step.model` |
| 2 | `role.model` |
| 3 | role 默认执行配置中的模型默认值 |

兼容层允许旧 snapshot 在缺少 role 级执行配置时回退到 loop 默认模型，但这不是新的资产归属规则。

## 7. 运行时装配

运行时 prompt 由稳定协议装配，顺序固定为：

`系统安全约束 → 输出契约 → 用户 prompt → run contract 摘要 → 当前轮次/当前 step 说明 → 紧邻上一步 handoff → 本轮已完成步骤摘要 → 上一轮同 step / 同 role handoff → 上一轮总结 → artifact refs`

补充约束：

- 首轮必须显式声明“这是第一轮，没有上一轮结果”。
- 后续轮次必须显式声明“这是第 N 轮，并给出上一轮关键结果”。
- prompt 可以被自定义，但系统安全边界、输出契约和 context packet shape 不能被绕开。
- 当角色定义页加载内置 prompt 时，应优先使用当前语言对应的内置 prompt 变体；若缺失本地化版本，则回退到默认版本。

## 8. Context Protocol

运行时使用以下内部稳定对象：

| 对象 | 作用 | 稳定承诺 |
|------|------|----------|
| `RunContractSnapshot` | 冻结 spec、workflow、prompt refs、runtime 配置 | run 生命周期内不漂移 |
| `StepContextPacket` | 在 step 开始前装配当前轮次、当前步骤、上游 handoff 与 artifact refs | shape 由代码固定生成 |
| `StepHandoff` | 在 step 结束后给下游角色消费的结构化交接包 | 由代码从结构化输出派生 |
| `IterationSummary` | 汇总本轮 handoff、得分、停滞状态与 latest refs | 作为下一轮的统一回看入口 |

## 9. 运行数据流

| 阶段 | 输入 | 输出 |
|------|------|------|
| 编排编辑 | orchestration / role definition | workflow 与 prompt 资产 |
| loop 创建 | workflow、prompt、运行参数 | 冻结后的 loop snapshot |
| run 执行 | snapshot | 分步骤证据、事件、终态摘要 |

补充说明：

- Web 界面可以把 workflow snapshot 投影成循环实例图，只要图中的节点顺序、角色名称和闭环语义仍然严格来自当前 workflow snapshot。

## 10. 跨入口一致性

workflow 与 prompt 资产必须满足：

- 可通过 Web 编辑与复用
- 可通过 CLI 或 API 引用、提交或校验
- 角色定义必须先作为独立资产存在，再被 orchestration 选入
- role definition 缺失 `prompt_ref` 时，系统会自动生成并稳定保留内部引用
- step 级模型覆盖不能只在单一入口可表达
- orchestration 不直接维护角色默认 prompt 与执行配置

## 11. 变更触发

以下变化需要更新本文档：

- workflow 结构变化
- completion mode 语义变化
- prompt 资产契约变化
- 角色原型种类或职责变化
- 角色执行配置的归属边界变化

以下变化通常不需要更新本文档：

- prompt 具体文案调整
- 兼容层实现细节变化

## 12. 非目标

- 不支持 DAG
- 不支持并发 step
- 不支持跳过角色原型校验提交任意 prompt
- 不支持用户自定义任意输出协议
