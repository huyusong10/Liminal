# Orchestration Service

## 1. Purpose

本模块是系统的中枢控制层。

它的任务不是“做某一类具体工作”，而是把以下对象串成稳定的生命周期：

- loop definition
- run
- roles
- artifacts
- failure / stop / recovery 分支

## 2. Owned Boundary

本模块拥有以下边界：

1. loop 定义和 run 实例之间的边界
2. 角色执行顺序和角色职责之间的边界
3. “局部角色结果”与“整次 run 状态”之间的边界
4. 内部执行过程与外部观察面之间的边界

因此它是：

- 生命周期协调器
- 状态汇聚器
- 失败收敛器

它不是：

- provider 适配层
- 底层存储层
- UI 组装层

## 3. Responsibilities

本模块负责：

1. 创建与复制可运行的 loop 配置
2. 驱动 run 从排队到结束
3. 执行固定角色链路
4. 在必要时引入重试、降级和 challenger
5. 把一次 run 收敛成明确终态
6. 生成人类可读摘要和结构化运行痕迹

## 4. Role Model

角色边界必须保持为：

- `Generator`：负责改变工作区
- `Tester`：负责收集证据
- `Verifier`：负责做通过裁决
- `Challenger`：负责在停滞时提出方向偏移

设计关键点：

- `Challenger` 不是主路径角色
- `Verifier` 是唯一通过裁决入口
- 角色链路是稳定的；具体 prompt 可以演化，边界不能漂移

## 5. Lifecycle Ownership

### 5.1 Loop

loop 表示“可复用运行模板”。

本模块只关心它包含：

- spec 快照
- executor 选择
- 运行控制参数

### 5.2 Run

run 表示“某次具体执行实例”。

本模块必须保证 run 具有：

- 清晰状态
- 单一活动角色
- 可追溯产物
- 明确终态

## 6. Dependency Direction

依赖方向必须保持为：

`interfaces -> orchestration service -> executor / repository / spec subsystem`

不允许：

- UI 直接编排 roles
- executor 直接更新全局 run 生命周期
- repository 直接决定 run 成败

## 7. Invariants

- 单次 iteration 的主链顺序固定：`Generator -> Tester -> Verifier`
- `Challenger` 只在停滞/回退分支出现
- 每个 run 只能收敛到一个终态
- 终态必须伴随可读摘要
- run 的状态变化必须可被外部观察

## 8. Reliability Responsibilities

本模块拥有但不细化实现的可靠性职责：

- stop 收敛
- role retry / degrade
- stagnation 分支触发
- 安全守卫触发后的失败收敛
- 非预期异常的失败收敛

这里强调的是“谁负责把失败变成系统可理解的状态”，而不是每个异常如何编码。

## 9. Artifact Responsibilities

本模块必须产出两类结果：

1. 机器可消费的结构化记录
2. 人可消费的摘要与导航信息

设计要求：

- 摘要只负责导航，不负责替代原始证据
- 结构化记录必须支持复盘和比较

## 10. Change Triggers

以下变化需要更新本文档：

- 角色链路变化
- run 生命周期变化
- 终态定义变化
- 编排层与其他模块的责任转移

以下变化通常不需要更新本文档：

- prompt 内容调整
- artifact 文件细节扩展
- 日志字段增加
- 重试参数调整

## 11. Non-Goals

- 不支持任意 DAG 编排
- 不支持多角色并发写同一工作区
- 不在这里表达 provider 特性
