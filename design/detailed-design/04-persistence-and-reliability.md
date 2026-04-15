# Persistence and Reliability

## 1. Purpose

本模块的职责是让 run 具备“可恢复、可观察、可约束”的工程属性。

它不创造业务语义，但负责把运行语义变成稳定事实。

## 2. Owned Boundary

本模块拥有三类边界：

1. 内存态与持久态之间的边界
2. 正常执行与异常恢复之间的边界
3. 允许的工作区修改与破坏性操作之间的边界

## 3. Responsibilities

本模块负责：

1. 保存 loop / run / event 的持久事实
2. 管理 workdir 级互斥
3. 为 run 提供停止、恢复、重启后的收敛能力
4. 提供 retry / stagnation / safety guard 这类可靠性控制件

## 4. Storage Design

持久化分为两层：

- 全局状态：跨项目共享
- workdir 局部状态：与具体项目绑定

设计意图：

- 全局数据库负责索引和状态查询
- workdir 内产物负责复盘、迁移和就地排查

这两层不是互斥关系，而是各司其职。

## 5. Durable Ownership

### 5.1 Repository Layer

Repository 只拥有：

- 持久化事实
- 事务边界
- 查询接口
- 锁记录

它不拥有：

- run 生命周期决策
- provider 调用
- UI 投影逻辑

### 5.2 Reliability Controls

可靠性控制件包括：

- stop flag
- retry / degrade
- stagnation detection
- stale/orphan recovery
- workspace safety guard

这些控制件的共同目标是：把“不确定执行”收敛成“可解释状态”。

## 6. Invariants

- 单个 workdir 同时最多一个活动 run
- 活动 run 必须能被外部停止
- 终态 run 不得持有活动锁
- 关键事件必须持久化
- 工作区安全优先于继续执行

## 7. Dependency Direction

依赖方向必须保持为：

`orchestration service -> repository / reliability controls`

禁止：

- repository 主动编排 run 生命周期
- UI 直接读写底层锁语义
- executor 直接定义恢复策略

## 8. Recovery Philosophy

恢复策略遵循两个优先级：

1. 先保证系统状态不悬空
2. 再尽量保留复盘线索

因此，恢复的目标不是“继续执行”，而是“把 run 收敛成可理解终态”。

## 9. Workspace Safety Philosophy

Liminal 允许改动用户项目，但不允许默认走“破坏式重建”。

安全守卫的设计意图是：

- 拦截明显越界的删除行为
- 把用户资产保护提升到系统级约束

具体阈值是实现细节；“存在破坏性边界”才是设计要点。

## 10. Change Triggers

以下变化需要更新本文档：

- 持久化层级改变
- 锁模型改变
- 恢复策略从“安全收敛”变为其他哲学
- 安全守卫责任转移到别的模块

以下变化通常不需要更新本文档：

- 数据表字段扩展
- 恢复启发式阈值调整
- retry 参数调整
- 日志镜像细节调整

## 11. Non-Goals

- 不做分布式一致性系统
- 不追求崩溃后自动续跑
- 不把 reliability controls 暴露成用户可编排 DSL
