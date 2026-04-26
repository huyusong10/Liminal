# 核心思想

## 0. 最高产品原则

Loopora 是面向长期 AI Agent 任务的 task-scoped harness compiler + evidence loop runtime。

核心闭环是：

`任务输入 -> 对齐成循环方案 -> 运行并收集证据 -> 基于反馈修订方案`

`product-principle.md` 是本目录的最高原则。下方公理都必须服务于这条主线：Loopora 不是 role zoo、prompt pack、loop script、通用聊天界面或内部资产 CRUD console。

## 1. 设计公理

1. loop 的存在理由必须是“行动后能拿到新证据”。  
   如果下一轮不会看到新的外部反馈，loop 就会从收敛器退化成随机游走。

2. `Task` 必须稳定。  
   run 可以迭代实现方式，不可以在执行中改写任务含义。

3. `Done When / checks` 必须按 run 冻结。  
   显式 `Done When` 直接编译成 checks；探索模式 checks 仅在 run 开始时生成一次。

4. 判定权不属于生成器。  
   `Builder` 负责改动；`Inspector` 负责取证；`GateKeeper` 负责裁决。

5. 证据必须本地可追溯。  
   每次 run 必须留下结构化产物、事件流和摘要；没有产物就等于没有发生。

6. workdir 视为用户资产。  
   Loopora 可以修改，但不得把“重建整个项目”当作默认策略。

7. `Guide` 不是常驻角色。  
   只有停滞或回退时才介入；默认 preset 可以是 `Builder -> Inspector -> GateKeeper`，但线性顺序允许按 loop 定义调整。

8. workflow 是声明式资产。  
   角色原型、步骤顺序、prompt 文件和默认 preset 都必须能被保存、快照和复盘。

9. orchestration 必须先于 loop 存在。  
   loop 负责“在哪个 workdir 上跑、用什么 spec 和 executor”；orchestration 负责“怎么跑”。

10. 接口层必须同构。  
   Web、CLI、API 表达的是同一个 loop 定义，不允许长期存在一边能做、另一边不能做的核心能力差异。

11. 系统首先是本地编排器，不是云端任务平台。  
   状态、锁、日志、产物优先围绕本地目录和本地数据库组织。

## 2. 不变量

- 单个 workdir 同一时刻最多允许一个活动 run。
- run 的主要事实源必须可从 `.loopora/` 与 `app.db` 还原。
- `Inspector` / `GateKeeper` / `Guide` 默认不应修改源文件。
- `GateKeeper` 的通过结论必须可映射到 checks、metrics 或边界约束。
- `Role Notes` 只能改变角色工作姿态，不能改变全局成功标准。
- `.loopora/` 是系统保留空间；业务改动不应写入该目录。

## 3. 反例

| 反例 | 违反规则 | 后果 |
| --- | --- | --- |
| 让 agent 在没有新证据的前提下继续空转几轮 | 违反“loop 的存在理由必须是行动后能拿到新证据” | 叙事漂移，任务变成盲盒 |
| 每轮都重新生成一套 checks | 违反“checks 按 run 冻结” | 分数不可比较，停滞检测失真 |
| Builder 自己宣布“已经完成” | 违反“判定权不属于生成器” | 通过条件退化成自我报告 |
| Inspector 为了让测试通过而直接改代码 | 违反“角色职责分离” | 证据与修复混杂，责任边界消失 |
| 删除整个 workdir 后重新生成项目 | 违反“workdir 视为用户资产” | 用户文件丢失，loop 破坏性过强 |
| Web 能保存 loop，CLI 不能 | 违反“接口层必须同构” | 同一系统出现双重能力模型 |
| 只在数据库记状态，不落地产物 | 违反“证据必须本地可追溯” | 无法复盘、对比、排查 |

## 4. 非目标

- 不是通用 DAG 编排引擎。
- 不是多租户远程 SaaS。
- 不是长期记忆系统。
- 不是 benchmark 刷分器。
- 不是替代底层 agent CLI 的二次聊天界面。

## 5. 压缩判断式

- 如果某条信息不能帮助“冻结任务 / 冻结检查 / 冻结边界 / 复盘证据”，它就不属于核心设计。
- 如果某个能力只能在一个入口存在，它就不是完成态。
- 如果一个 run 结束后不能回答“改了什么、怎么测的、为什么没过/过了”，该设计就是不合格的。
