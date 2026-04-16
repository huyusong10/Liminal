# Orchestration Service

## 1. 模块职责

模块存在的唯一理由：

- 把可编辑资产、可复用配置与一次性运行实例收敛成同一套编排语义。

它负责“如何把一次 loop 跑起来并收束到终态”，不负责底层执行工具、存储实现或界面呈现。

## 2. 对外契约

| 对象 | 输入 | 输出 | 稳定承诺 |
|------|------|------|----------|
| `orchestration` | 名称、描述、workflow、prompt 资产 | 可复用编排定义 | 可创建、读取、更新、列出、删除；内置编排只能复制，不能原地改写 |
| `role definition` | 名称、角色原型、默认模型、prompt 资产 | 可复用角色模版 | 可创建、读取、更新、列出、删除；内置角色定义只能复制，不能原地改写 |
| `loop definition` | workdir、spec、执行参数、completion mode、编排引用 | 可执行模板 | 创建时完成输入规范化与快照冻结 |
| `run` | loop definition | 运行状态、事件流、终态摘要、结构化产物 | 同一 run 只有一个终态，且终态必须可观察、可复盘 |

## 3. 角色职责边界

| 角色原型 | 职责 | 不负责 |
|----------|------|--------|
| `Builder` | 改动工作区并推进实现 | 终态裁决 |
| `Inspector` | 收集证据、执行检查、整理结果 | 改写通过标准 |
| `GateKeeper` | 根据证据判断是否通过 | 直接产出实现 |
| `Guide` | 在停滞或回退时提供方向调整 | 作为每轮固定主路径 |

稳定规则：

- 角色职责边界稳定，步骤顺序可配置。
- `Guide` 只应出现在停滞相关分支，不应成为每轮必跑步骤。
- `GateKeeper` 是 `gatekeeper` completion mode 的唯一收敛裁决入口。

## 4. 运行数据流

### 4.1 Loop 创建

`用户输入 → 编排解析与校验 → spec 编译 → loop definition`

服务层必须完成：

- 解析 orchestration 或内联 workflow
- 解析 role definition 选入后的角色快照
- 校验 completion mode 与 workflow 是否匹配
- 冻结运行所需的 spec、workflow 与 prompt 资产

### 4.2 Run 执行

`loop definition → 线性步骤执行 → 事件与产物汇聚 → run 状态更新`

服务层必须完成：

- 保持单轮内步骤为线性顺序
- 维护当前活动角色与轮次状态
- 在步骤之间传递上一轮证据
- 汇聚结构化结果与人类可读摘要

### 4.3 终态收敛

| completion mode | 收敛条件 | 结果 |
|-----------------|----------|------|
| `gatekeeper` | 存在可结束流程的 GateKeeper 步骤，且该步骤给出通过裁决 | `succeeded` |
| `rounds` | 达到计划轮数 | `succeeded` |

失败与停止同样必须收敛为明确终态，并带可读原因。

## 5. 模型解析契约

同一步骤的模型选择优先级固定为：

`step.model → role.model → loop 默认模型`

该优先级是编排语义的一部分；更换底层执行工具时也不能改变。

## 6. 核心约束

- 单次 iteration 只支持线性步骤，不支持 DAG。
- 同一时刻只允许一个活动角色写入当前 run 状态。
- `gatekeeper` completion mode 必须依赖可结束流程的 GateKeeper 步骤。
- `rounds` completion mode 允许没有 GateKeeper。
- 非零轮次间隔必须可被 stop 请求打断。
- 每个 run 只能落到一个终态。
- 每次状态变化都必须能投影到外部观察面。

## 7. 依赖边界

依赖方向必须保持为：

`接口层 → orchestration service → executor / 持久化 / spec 子系统`

禁止：

- 接口层直接编排角色生命周期
- executor 直接决定全局 run 成败
- 持久化层直接定义编排规则

## 8. 变更触发

以下变化需要更新本文档：

- 新增或删除角色原型
- completion mode 语义变化
- loop / orchestration / role definition / run 的责任边界变化
- 运行收敛规则变化

以下变化通常不需要更新本文档：

- prompt 文案调整
- 日志字段补充
- 重试阈值与启发式调整

## 9. 非目标

- 不支持任意图结构编排
- 不支持多角色并发改写同一工作区
- 不在这里表达底层执行工具的私有参数
