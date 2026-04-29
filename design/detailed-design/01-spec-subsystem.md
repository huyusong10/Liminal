# Spec Subsystem

> 最高原则：遵循 `../core-ideas/product-principle.md`。本模块服务于长期任务 Loop 的运行契约，只负责冻结任务契约，不把 spec 误扩展成完整 Loop 或 prompt 包。

## 1. Purpose

本模块负责把“人写的目标描述”变成“运行时可消费的任务契约”。

这里关注的不是 Markdown 细节，而是边界：

- 哪些内容由用户表达
- 哪些内容由系统冻结
- 哪些内容可以留给运行期推导

## 2. Owned Boundary

本模块拥有两条边界：

1. `spec.md` 到 `compiled_spec` 的编译边界
2. “没有显式 checks”到“本次 run 的冻结 checks” 的生成边界

因此，它是：

- 人类意图的入口
- 运行契约的出口

它不是：

- 执行引擎
- 判定引擎
- 工作区改动引擎

## 3. Responsibilities

本模块只负责以下职责：

1. 定义可接受的 spec 结构
2. 判断 spec 是否足够成形，能否进入运行期
3. 生成 run 级别稳定的 checks 视图
4. 保证同一 run 内 checks 不漂移

## 4. Upstream / Downstream

### 4.1 Upstream

- 人工编写的 `spec.md`
- Web / CLI 提供的 spec 文件路径
- Web 可编辑 spec 工作台当前缓冲区中的 Markdown 文本

### 4.2 Downstream

- `LooporaService`
- run artifact 持久化
- `Tester` / `Verifier` / `Generator` prompt 输入

## 5. Design Rules

1. `Task` 是必需的最小锚点。
2. `Done When` 可以缺失，但一旦进入某次 run，系统必须冻结一份 checks 集合。
3. `Guardrails` 只是边界声明，不是执行计划。
4. `Role Notes` 只能影响角色 prompt 的附加上下文，不能成为隐藏通过条件。
5. `Success Surface`、`Fake Done`、`Evidence Preferences` 与 `Residual Risk` 属于 task contract 的稳定组成部分；它们表达任务级治理判断，但不单独替代 role posture 或 workflow 形状。
6. 编译结果必须比原始 Markdown 更稳定、更可枚举。
7. 探索模式的自由度只能发生在 run 开始前，不得延续到 iteration 内部。
8. UI 可以提供 spec 的读取、编辑、模板生成与渲染预览，但保存后的内容仍必须回到同一条 `spec.md -> compiled_spec` 编译边界；预览不能绕过编译器直接构造运行期 spec。
9. 当 spec 来自 bundle 编译时，它仍然只是 task contract 的一个运行面；bundle 级 posture 还必须继续由 role definition 与 workflow 共同承载。

## 6. Invariants

- 同一个 run 只允许拥有一份有效的 checks 集合。
- 显式 checks 与自动生成 checks 在运行期必须拥有统一的消费形态。
- 用户可以写得松，但系统输出必须是结构化的。
- spec 的职责是定义“任务、判断标准、边界，以及角色附加提示”，而不是定义完整工作流。
- 角色附加提示只能改变角色工作姿态，不能改变全局 pass/fail。
- task contract 可以表达成功面、假完成、证据偏好与残余风险，但不能单独取代 role posture 或 workflow 的治理语义。

## 7. Dependency Direction

依赖方向必须保持为：

`spec authoring -> spec compiler -> orchestration service -> runtime roles`

禁止反向依赖：

- 运行角色不得反过来修改原始 spec
- `Verifier` 不得重新定义 checks
- UI 层不得绕过编译器直接拼运行时 spec

## 8. Change Triggers

以下变化需要更新本文档：

- 新增一种 spec 级核心语义
- 改变 checks 冻结时机
- 改变“显式 / 自动生成”两种模式的边界
- 改变 role notes 的注入或裁决边界

以下变化通常不需要更新本文档：

- Markdown 解析细节调整
- 模板文案或按 workflow 生成模板的占位文本调整
- 编译结果的辅助字段扩展

## 9. Non-Goals

- 不把 spec 演化成通用 DSL
- 不在这里决定评分逻辑
- 不在这里决定执行顺序
