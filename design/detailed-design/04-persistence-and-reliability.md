# Persistence and Reliability

> 最高原则：遵循 `../core-ideas/product-principle.md`。持久化与可靠性设计必须保护长期任务的事实源、证据链和 Loop / bundle 来源，而不是只保存临时运行状态。

## 1. 模块职责

模块存在的唯一理由：

- 把运行中的临时状态收敛成可恢复、可观察、可约束的持久事实。

它负责“保存什么、何时可恢复、何时必须保护用户资产”，不负责编排决策与界面投影。

## 2. 持久化契约

| 持久对象 | 保存内容 | 对外承诺 |
|----------|----------|----------|
| loop definition | 可执行模板、runtime 策略、编排引用 | 可被重新读取并复用 |
| orchestration definition | workflow 与 prompt 资产 | 可被列出、复制、编辑与复用 |
| role definition | 角色模版、默认执行配置、prompt 资产 | 可被列出、复制、编辑与复用 |
| run record | 生命周期状态、当前轮次、终态摘要、最近裁决 | 可被恢复、查询、停止与复盘 |
| run event stream | 关键状态转换与角色阶段事件 | 外部观察面可增量消费 |
| workspace lock | 当前工作区是否被活动 run 占用 | 同一工作区不会被多个活动 run 并发驱动 |

持久层采用“两层事实”：

- 全局应用状态：可跨项目查询与管理的定义、索引和运行事实
- 项目局部状态：与具体 workdir 绑定的运行快照与复盘产物

补充约束：

- run event stream 是业务时间线，不等于系统诊断日志。
- application log 的结构与分级规则由 `07-observability-and-diagnostics.md` 统一定义。

## 3. 数据流转

| 输入 | 持久化处理 | 输出 |
|------|------------|------|
| 创建 loop / orchestration / role definition | 规范化输入并写入 durable record | 可复用定义 |
| 启动 run | 申请工作区锁并创建 run record | 可执行的活动实例 |
| 运行中事件 | 追加关键事件并更新 run 状态 | 可流式观察的时间线 |
| 终态或异常 | 释放工作区锁并写入终态摘要 | 可恢复、可解释的结束状态 |

补充约束：

- role definition 的执行配置与 prompt 一起持久化，供 orchestration 复制成角色快照
- orchestration 保存的是角色快照与步骤，不直接回写 role definition
- loop definition 保存的是运行策略与 orchestration 引用，不重新定义角色默认执行配置

## 4. Canonical Run Layout

run 目录使用统一 canonical layout：

- `summary.md`
- `contract/spec.md`
- `contract/compiled_spec.json`
- `contract/workflow.json`
- `contract/run_contract.json`
- `contract/workspace_baseline.json`
- `contract/prompts/<prompt_ref>.md`
- `context/role_requests.jsonl`
- `context/latest_state.json`
- `context/latest_iteration_summary.json`
- `timeline/events.jsonl`
- `timeline/iterations.jsonl`
- `timeline/metrics.jsonl`
- `timeline/stagnation.json`
- `evidence/ledger.jsonl`
- `evidence/coverage.json`
- `iterations/iter_XXX/summary.json`
- `iterations/iter_XXX/steps/NN__<step_id>/{metadata,input.context,prompt,output.raw,output.normalized,handoff}.json|md`

兼容镜像策略：

- `events.jsonl`
- `iteration_log.jsonl`
- `metrics_history.jsonl`
- `builder_output.json / tester_output.json / verifier_verdict.json` 等 root 文件

这些 legacy mirrors 可以继续被读取，但不再承担真实上下文流转语义。

## 5. 可靠性控制件

| 控制件 | 触发时机 | 承诺 |
|--------|----------|------|
| stop flag | 用户请求停止 | 活动 run 可被外部打断并收敛 |
| retry / degrade | 角色执行失败或不稳定 | 失败会转化为明确事件与结果，而不是悬空状态 |
| stagnation detection | 多轮效果停滞或回退 | 系统能触发额外引导分支，而不是无限重复主路径 |
| stale/orphan recovery | 进程异常退出或状态失联 | 重启后会先把活动状态收敛为可理解状态 |
| workspace safety guard | 检测到破坏性工作区改动 | 用户项目安全优先于继续执行 |

## 6. 核心约束

- 单个 workdir 同时最多一个活动 run。
- 活动 run 必须能被停止。
- 终态 run 不得继续持有工作区锁。
- 关键状态变化必须写成持久事实。
- 工作区安全优先于继续执行。
- 界面辅助状态只能是 best-effort，不得污染核心持久语义。

## 7. 恢复哲学

恢复遵循以下优先级：

1. 先消除悬空状态
2. 再保留尽可能多的复盘线索

因此“恢复”的目标不是无条件续跑，而是把 run 收敛成对系统和用户都可解释的状态。

## 8. 边界约束

依赖方向必须保持为：

`orchestration service → 持久化 / reliability controls`

禁止：

- 持久化层主动编排 run 生命周期
- 接口层直接操作底层锁语义
- executor 直接定义恢复策略

## 9. 配置与辅助状态

配置与最近使用记录属于可靠性边界的一部分，但不属于业务契约本身。

稳定承诺：

- 损坏、缺失或越界的辅助状态必须回退到安全默认值
- 自愈过程不能阻止系统启动
- 辅助状态只能改善体验，不能改变最终提交到服务层的定义

## 10. 变更触发

以下变化需要更新本文档：

- 持久化对象种类变化
- 锁模型变化
- 恢复哲学变化
- 工作区安全责任迁移

以下变化通常不需要更新本文档：

- 字段扩展
- 阈值调整

## 11. 非目标

- 不做分布式一致性系统
- 不承诺崩溃后自动续跑到原位置
- 不把可靠性控制件暴露成用户可编排语言
