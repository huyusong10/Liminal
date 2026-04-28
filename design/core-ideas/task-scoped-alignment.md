# Task-Scoped Alignment

> 最高原则：遵循 `product-principle.md`。Alignment 的目标不是尽快产出 YAML，而是把当前长期任务的治理结构对齐成可预览、可运行、可取证、可修订的循环方案。

## 1. 目标

本文档定义 Loopora 的默认新建路径如何从“用户手工拼 workflow”变成“先对齐任务治理，再运行循环方案”。

一句话：

> Alignment is the compiler front-end for Loopora's external task-governance harness.

## 2. 对齐对象

Alignment 对齐的不是抽象人格，也不是通用最佳实践，而是当前任务的治理问题：

- 什么算真实进展？
- 什么是假完成？
- 用户信任哪些证据？
- 哪些残余风险可以接受，哪些必须阻断？
- 谁负责构建，谁负责取证，谁负责裁决？
- 什么时候应继续推进、修复、收窄，或停止？

这些问题必须先形成 working agreement，再编译成循环方案。

## 3. Working Agreement

`working agreement` 是编译期中间产物，不是运行期资产。

它的作用是：

- 让 alignment agent 有明确收敛目标。
- 让用户确认系统是否理解本次任务的判断方式。
- 给 bundle 编译前提供人类可读检查点。

运行期真正需要执行和复盘的仍然是：

- `spec`
- `role definitions`
- `workflow / orchestration`
- `loop / run evidence`

## 4. Bundle 的位置

`bundle` 是循环方案的内部交换单元，不是新手默认心智。

它必须同时是：

- readable agreement：用户能看懂为什么这样协作
- runnable config：Loopora 能导入并物化为本地资产
- revisable unit：后续反馈能生成下一版 harness

默认路径应表达为：

`任务输入 -> 对齐循环方案 -> READY 预览 -> 创建并运行 -> 证据 -> 修订`

专家路径可以继续表达为：

`YAML bundle -> 导入 / 导出 / 派生 / 删除`

## 5. Runtime surfaces

Loopora 不执行一个独立 agreement 文件。导入 bundle 后，系统必须把治理结构物化到：

| surface | 职责 |
|---------|------|
| `spec` | task contract、成功面、假完成、证据偏好、残余风险 |
| `role definitions` | 各角色的 task-scoped posture 与证据责任 |
| `workflow / orchestration` | 角色顺序、handoff、纠偏入口、收束条件 |
| `loop definition` | workdir、执行器、运行策略 |

这些 surface 是同一份治理结构的不同投影，不应在后续编辑中彼此漂移。

## 6. Loopora 本体与 Alignment Agent

Loopora 本体负责：

- 管理本地资产
- 导入 / 导出 / 派生 / 删除 bundle
- 物化 `spec / roles / workflow / loop`
- 启动 run
- 调用外部 AI Agent CLI
- 记录事件、产物、证据和终态

Alignment agent 负责：

- 与用户沟通
- 暴露关键 tradeoff
- 收敛 task-scoped governance
- 产出 working agreement
- 编译 YAML bundle
- 基于 run evidence 和反馈产出下一版 bundle

Alignment agent 可以来自 Web 内置 session，也可以来自外部 AI Agent 加载 repo-local Skill。两条路径必须产出同一种可运行 bundle。

## 7. Revision

用户对 run 的反馈不应被迫翻译成底层字段改动。

合理路径是：

1. 读取旧 bundle。
2. 读取 run evidence。
3. 读取用户反馈。
4. 解释治理偏移。
5. 产出下一版 working agreement 和 bundle。

例如：

- “这次太偷懒了。”可能加强 Inspector 和 GateKeeper 的证据要求。
- “这次不够重视重构。”可能改变 spec 的 fake-done 描述和 Builder 姿态。
- “这个 residual risk 我可以接受。”可能调整 GateKeeper 的放行解释方式。

## 8. 变更触发

以下变化需要更新本文档：

- 默认新建路径不再是 task alignment -> loop plan -> run
- working agreement 变成运行期资产
- bundle 不再是单文件 YAML 交换单元
- 治理结构不再由 `spec / role definitions / workflow` 共同承载
- Web 内置 alignment 绕过 bundle 导入，直接创建底层资产

以下变化通常不需要更新本文档：

- 对齐话术调整
- bundle 字段小幅扩展
- Web 页面文案和布局调整
- 内置 workflow 示例调整
