# Observability and Diagnostics

## 1. 模块职责

模块存在的唯一理由：

- 把 Loopora 的运行诊断收敛成统一、可关联、可机器消费的观察面。

它负责“系统如何留下诊断线索”，不负责业务状态机本身，也不替代 run event stream。

## 2. 诊断对象分层

| 观察面 | 作用 | 稳定承诺 |
|--------|------|----------|
| application log | 记录模块动作、异常、自愈、入口请求与运行里程碑 | 采用统一结构、统一事件命名、统一分级规则 |
| run event stream | 面向 run 时间线与 UI 增量观察 | 保持业务事件语义，不承担全局系统诊断职责 |
| run artifacts | 记录 prompt、输出、summary、metrics 等复盘材料 | 用于还原单次 run 的细节，不替代系统级日志 |

稳定规则：

- application log 与 run event stream 必须并存，不能互相替代。
- 同一诊断场景优先用共享关联字段串联三者，而不是复制大段内容。
- Web 终端必须把关键系统动作白盒化投影出来，不能只展示底层命令输出。

## 3. 标准日志结构

每条 application log 都必须输出为同一结构对象：

| 字段 | 是否必填 | 含义 |
|------|----------|------|
| `schema_version` | 是 | 日志契约版本 |
| `ts` | 是 | 事件时间，统一使用 UTC 时间戳字符串 |
| `level` | 是 | `INFO / WARNING / ERROR` 等分级 |
| `logger` | 是 | 产生日志的模块标识 |
| `component` | 是 | 归属边界，如 `service / db / web / cli / settings` |
| `event` | 是 | 稳定事件名，用于检索与告警 |
| `message` | 是 | 面向人的简短解释 |
| `pid` | 是 | 当前进程标识 |
| `thread` | 是 | 当前线程标识 |
| `loop_id` | 否 | 已知时必须带上 |
| `run_id` | 否 | 已知时必须带上 |
| `step_id` | 否 | 已知时必须带上 |
| `role` | 否 | 已知时必须带上 |
| `archetype` | 否 | 已知时必须带上 |
| `orchestration_id` | 否 | 已知时必须带上 |
| `role_definition_id` | 否 | 已知时必须带上 |
| `workdir` | 否 | 与具体项目目录相关时必须带上 |
| `context` | 否 | 其余结构化上下文 |
| `error` | 否 | 失败场景下的错误类型、错误信息与堆栈 |

稳定规则：

- 允许新增 `context` 子字段，但不得移除既有必填字段。
- 关联字段已知时必须透传，不能改写成自由文本。
- `message` 面向人，`event` 面向机器；两者职责不能混淆。

## 4. 事件命名规则

事件名必须采用分层命名：

`边界.对象.动作`

示例：

- `service.loop.created`
- `service.run.execution.started`
- `service.workflow.step.completed`
- `service.workflow.step.context_prepared`
- `service.workflow.iteration.summary_written`
- `db.connect.retry`
- `web.request.completed`
- `cli.background_worker.spawned`
- `settings.normalize.invalid_value`

命名约束：

- 第一段必须表达边界：`settings / db / service / web / cli`
- 第二段开始表达对象与生命周期，不使用自由缩写
- 动作统一使用稳定动词，如 `requested / created / updated / started / completed / finished / failed / recovered / skipped`
- 同一语义在不同模块中必须复用同一动作词，不要一处叫 `done` 一处叫 `complete`

## 5. 分级规则

| 级别 | 触发条件 | 示例 |
|------|----------|------|
| `INFO` | 正常生命周期里程碑、持久化写入完成、入口请求完成 | 创建 loop、注册 run、步骤完成、HTTP 请求完成 |
| `WARNING` | 可恢复异常、自愈、降级、非法输入被纠正、安全拦截、认证拒绝 | 配置回退默认值、数据库重试、孤儿 run 恢复、角色降级 |
| `ERROR` | 结果已经改变、需要人工关注、流程无法按原计划完成 | run 崩溃、步骤中止、工作区安全守卫触发、后台 worker 启动失败 |

稳定规则：

- 不把正常主路径记成 `WARNING`。
- 不把会改变最终结果的失败记成 `INFO`。
- 同一失败若已进入 `ERROR`，可以额外写业务事件，但不要再降级成较轻级别。

## 6. 打印规则

打印必须遵守以下规则：

- 只记录诊断所需的摘要，不记录完整 prompt、spec 正文、workflow 正文或认证 token。
- 命令行参数、请求信息与运行配置只记录足以定位问题的摘要字段。
- 任何异常日志都必须带 `event`，并在可能时附带 `error` 对象。
- 同一次动作只记录一个主里程碑日志，避免 repository、service、web 在同一层级重复记录相同语义。
- request 级日志只记录方法、路径、状态码和耗时，不回显敏感 query 参数。

## 7. 模块分工

| 边界 | 必须记录的内容 | 不应承担的内容 |
|------|----------------|----------------|
| `settings` | 配置读取、自愈回退、持久化失败、日志初始化 | 业务运行里程碑 |
| `db` | 连接重试、schema 就绪、写路径完成、镜像失败、锁获取/释放 | 编排决策解释 |
| `service` | loop/run 生命周期、轮次推进、步骤开始结束、恢复、自我保护、终态 | HTTP 请求明细 |
| `web` | 请求完成、认证拒绝、SSE 故障、接口层领域错误 | 持久化细节 |
| `cli` | 命令触发、后台 worker 启停、CLI 失败 | Web 请求语义 |

run event stream 中，以下事件属于稳定白盒事件：

- `role_request_prepared`
- `step_context_prepared`
- `step_handoff_written`
- `iteration_summary_written`

这些事件必须能被终端观察面直接订阅并渲染。

## 8. 边界约束

依赖方向必须保持为：

`入口 / 持久化 / 服务模块 → 统一日志契约`

禁止：

- 每个模块自行定义字段名或时间格式
- 用字符串拼接代替结构化上下文
- 把 run event stream 直接当成 application log
- 在日志中泄露 prompt 正文、认证 token 或完整敏感命令输入

## 9. 变更触发

以下变化需要更新本文档：

- 必填日志字段变化
- 事件命名规则变化
- 分级规则变化
- application log 与 run event stream 的职责边界变化
- 新增一个需要稳定输出诊断日志的顶层边界

以下变化通常不需要更新本文档：

- 新增某个具体事件名
- `context` 中新增兼容字段
- 文案微调

## 10. 非目标

- 不把 application log 当作业务数据库
- 不在日志中保存完整大对象快照
- 不要求每个内部 helper 都产生日志
