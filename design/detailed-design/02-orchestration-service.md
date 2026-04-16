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
3. 执行声明式线性 workflow
4. 在必要时引入重试、降级和 Guide
5. 把一次 run 收敛成明确终态
6. 生成人类可读摘要和结构化运行痕迹
7. 规范化 orchestration 的创建、读取、更新和删除语义
8. 规范化 role definition 的创建、读取、更新和删除语义

## 4. Role Model

角色边界必须保持为：

- `Builder`：负责改变工作区并推进实现
- `Inspector`：负责收集证据、运行测试和 benchmark
- `GateKeeper`：负责根据证据做通过裁决
- `Guide`：负责在停滞或回退时提出方向偏移

设计关键点：

- `Guide` 不是稳定每轮都运行的主路径角色；它默认只在停滞信号出现时生效
- `GateKeeper` 是唯一通过裁决入口
- 角色职责边界稳定，但每条 loop 的步骤顺序不再固定
- prompt 是资产文件，不再硬编码在 service 中

## 5. Lifecycle Ownership

### 5.1 Loop

loop 表示“可复用运行模板”。

本模块只关心它包含：

- orchestration 引用
- spec 快照
- executor 选择
- 运行控制参数
- 完成模式与轮次间隔
- workflow 清单
- prompt 文件快照

orchestration 表示“可编辑、可复用的 workflow 资产”。

role definition 表示“可编辑、可复用的角色模版资产”。

本模块必须保证：

- custom orchestration 可被更新
- built-in orchestration 不可被原地修改
- built-in orchestration 可以作为复制源进入同一个编辑器
- custom role definition 可被更新
- built-in role definition 不可被原地修改
- built-in role definition 可以作为复制源进入同一个编辑器

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

- 单次 iteration 只支持线性 step 顺序，不支持 DAG
- workflow 必须至少包含一个可收敛的 `GateKeeper`
- `Guide` 只在停滞/回退分支出现
- 每个 run 只能收敛到一个终态
- 终态必须伴随可读摘要
- run 的状态变化必须可被外部观察
- gatekeeper completion mode 依赖 GateKeeper finish step
- rounds completion mode 允许没有 GateKeeper，并在达到计划轮数后成功结束
- 非零 iteration interval 必须可被 stop 信号打断

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
- workflow 结构变化
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
