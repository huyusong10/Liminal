# Executor Subsystem

> 最高原则：遵循 `../core-ideas/product-principle.md`。执行器只是把已冻结的循环方案交给本机 AI Agent CLI 执行，不负责替代 alignment、裁决或方案 revision。

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

## 6. Provider Abstraction Rules

每个 provider 适配必须回答四个问题：

1. 如何构造命令
2. 如何表达模型 / 推理参数
3. 如何获得结构化结果
4. 如何把失败统一映射为执行错误

如果一个新 provider 无法满足这四点，它不应进入核心适配层。

## 7. Invariants

- 所有 provider 最终都必须向上层返回同构的结构化对象
- provider 私有输出必须在本层被消化
- 子进程必须受 stop 与 timeout 控制
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
