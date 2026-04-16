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
| role definition asset | 名称、原型、默认模型、prompt 资产 | 可复用角色模版 | 在 orchestration 中被选入后，会复制成角色快照 |
| workflow snapshot | roles 与 steps | 运行期角色顺序与依赖关系 | run 开始后不再随外部编辑漂移 |
| prompt asset | 元数据头 + Markdown 正文 | 角色运行提示 | 必须声明版本与适用角色原型 |

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
| `archetype` | 角色原型 |
| `prompt_ref` | 该 role 使用的 prompt 资产引用 |
| `model` | 可选，role 级默认模型 |
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

系统固定支持四种角色原型：

| 原型 | 职责 |
|------|------|
| `builder` | 改动工作区并推进实现 |
| `inspector` | 收集证据并执行检查 |
| `gatekeeper` | 根据证据给出通过裁决 |
| `guide` | 在停滞或回退时给出方向调整 |

兼容层仍接受旧别名，但运行时会收敛为上述稳定原型。

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
| 3 | loop 默认模型 |

该优先级是 workflow 语义的一部分。

## 7. 运行时装配

运行时 prompt 由以下信息共同装配：

`系统安全约束 → 用户 prompt → spec 与限制条件 → 同轮和上一轮证据 → 输出契约`

这意味着 prompt 可以被自定义，但系统安全边界和结构化输出约束不能被绕开。

## 8. 运行数据流

| 阶段 | 输入 | 输出 |
|------|------|------|
| 编排编辑 | orchestration / role definition | workflow 与 prompt 资产 |
| loop 创建 | workflow、prompt、运行参数 | 冻结后的 loop snapshot |
| run 执行 | snapshot | 分步骤证据、事件、终态摘要 |

## 9. 跨入口一致性

workflow 与 prompt 资产必须满足：

- 可通过 Web 编辑与复用
- 可通过 CLI 或 API 引用、提交或校验
- 角色定义必须先作为独立资产存在，再被 orchestration 选入
- step 级模型覆盖不能只在单一入口可表达

## 10. 变更触发

以下变化需要更新本文档：

- workflow 结构变化
- completion mode 语义变化
- prompt 资产契约变化
- 角色原型种类或职责变化

以下变化通常不需要更新本文档：

- prompt 具体文案调整
- 内部落盘路径调整
- 兼容层实现细节变化

## 11. 非目标

- 不支持 DAG
- 不支持并发 step
- 不支持跳过角色原型校验提交任意 prompt
- 不支持用户自定义任意输出协议
