# Executor Subsystem

> 最高原则：遵循 `../core-ideas/product-principle.md`。执行器只是把已冻结的 Loop step 交给本机 AI Agent CLI 执行，不负责替代 Loop 编排、裁决或 bundle 调整。

## 1. Purpose

本模块把“抽象角色请求”翻译成“具体 agent CLI 调用”。

它的价值不在于封装某一个 provider，而在于隔离两层变化：

- 上层编排语义的稳定性
- 下层 provider 参数与输出格式的易变性

## 2. Owned Boundary

本模块拥有以下边界：

1. 统一执行请求与 provider 具体命令之间的边界
2. provider 原始输出与结构化角色结果之间的边界
3. 编排层的 stop / timeout 信号与子进程生命周期之间的边界

它是一个适配层，不是业务层。

## 3. Responsibilities

本模块负责：

1. 定义统一的角色执行请求
2. 归一化 provider 名称与能力差异
3. 支持稳定模式与直通模式两种调用方式
4. 监督子进程执行
5. 将外部输出收敛为结构化结果或明确失败

本模块不负责：

- 决定角色顺序
- 决定 run 是否通过
- 维护数据库状态

## 4. Stable Contract

对上层暴露的稳定面只有两个：

1. `RoleRequest`
2. `CodexExecutor.execute(...) -> dict`

设计要求：

- 上层不感知 provider 私有输出格式
- 下层不感知 run 生命周期语义

## 5. Execution Modes

### 5.1 Preset Mode

由系统维护稳定调用模板。

适用场景：

- 默认用户路径
- 需要减少 provider 细节泄漏

### 5.2 Command Mode

允许接口层直接传入命令模板。

适用场景：

- provider 参数快速演化
- 用户需要接入外层包装命令

设计原则：

- command mode 是 escape hatch
- 但仍必须经过最小可运行性校验
- 参数模板只接受执行器声明的运行时占位符；无法识别的 `{name}` 形式占位符必须在启动子进程前失败
- command mode 仍必须把输出收敛为结构化对象，不能把未受限的大块文件内容当作角色结果吞入内存

## 6. Provider Abstraction Rules

每个 provider 适配必须回答四个问题：

1. 如何构造命令
2. 如何表达模型 / 推理参数
3. 如何获得结构化结果
4. 如何把失败统一映射为执行错误

如果一个新 provider 无法满足这四点，它不应进入核心适配层。

模型字段在预设模式下是可选 pin：空值表示继承对应 CLI 的当前默认模型，只有显式填写时才向 provider 命令传递模型参数。Loopora 不把会随上游工具迭代的模型名写成默认契约。

## 7. Invariants

- 所有 provider 最终都必须向上层返回同构的结构化对象
- provider 私有输出必须在本层被消化
- provider 写入的结构化输出文件必须是有界、可解码的文本；过大、非 UTF-8 或无法解析为对象时必须映射为明确执行错误
- 子进程必须受 stop 与 timeout 控制；stream/handler 内部失败时也必须先终止子进程，再向上抛出错误
- command mode 不得绕过结构化输出要求

## 8. Dependency Direction

依赖方向必须保持为：

`orchestration service -> executor subsystem -> external CLI`

禁止：

- provider 直接回调编排层状态机
- UI 直接拼装 provider 私有协议

## 9. Testability Boundary

本模块必须支持 fake executor。

原因：

- 编排层测试不应依赖真实 provider
- 恢复、停滞、安全守卫等逻辑必须可被稳定模拟

fake executor 的职责是模拟边界，不是复制真实 provider 行为。

因为 fake executor 的结构化输出会被编排测试、证据账本和本地演示直接消费，它的 canned payload 仍必须保留最小运行期语义：角色输出不能暗示可以降低已冻结的 Task / Done When / checks / guardrails；GateKeeper 成功样例必须来自 evidence refs 或可测量 evidence claims，而不是 run 生命周期本身；失败样例应把缺口表达为 weak / unproven / blocking evidence，而不是把“未通过”伪装成普通完成状态。

## 10. Change Triggers

以下变化需要更新本文档：

- 新增一种执行模式
- 新增或删除 provider 抽象层
- 上层统一请求契约变化

以下变化通常不需要更新本文档：

- 某个 provider 的具体参数变化
- 输出解析的局部细节变化
- 默认模型和默认 effort 调整

## 11. Non-Goals

- 不追求 provider 能力完全等价
- 不做底层 CLI 的安装管理
- 不在这里承载产品语义
