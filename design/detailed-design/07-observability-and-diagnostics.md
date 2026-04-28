# Observability and Diagnostics

> 最高原则：遵循 `../core-ideas/product-principle.md`。观察面必须优先回答“这轮产生了什么证据、为什么过或没过、下一版 harness 应如何修订”，而不是只堆日志。

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
| evidence ledger | 记录本次 run 的证明项、未覆盖风险和对应 artifact refs | 作为 GateKeeper verdict、run 复盘和后续 revision 的 canonical 证据事实源 |

稳定规则：

- application log、run event stream、run artifacts 与 evidence ledger 必须并存，不能互相替代。
- 同一诊断场景优先用共享关联字段串联三者，而不是复制大段内容。
- evidence ledger 的 canonical 文件是 `evidence/ledger.jsonl`；它不是 timeline、metrics 或 raw output 的复制品。
- 每个 evidence item 至少要能表达 claim、method、result、artifact refs、produced by、verifies 与 residual risk。
- Step handoff 可以摘要证据，但必须通过 `evidence_refs` 指回 ledger item；面向用户的结论不能只停留在自由文本。
- 并行检视组中的多个 evidence producer 共享同一上游快照；ledger 按 workflow step 顺序落账，并保留各自的 `step_id / role_id / archetype / iter`。
- GateKeeper pass 必须能回到 evidence ledger；没有 evidence refs 或可落账 evidence claims 的 pass 不能成为新 run 的强收敛条件。
- Web 终端必须把关键系统动作白盒化投影出来，不能只展示底层命令输出。
- 面向用户的 run 详情页应优先消费 run artifacts 中已经冻结的 handoff / iteration summary 来生成“关键结论”，而不是把原始 artifact 文件逐个暴露为主界面导航；原始 artifact 仍保留在 `.loopora` 中供追查与下载。
- 当新的 `step_handoff_written`、`control_completed`、`control_failed`、`iteration_summary_written` 或 `run_finished` 事件到达时，run 详情页里的“关键结论”必须在当前会话内自动拉取最新 artifacts 并刷新；不能要求用户手动刷新整页后才能看到最新轮次结论。
- 提供给角色 prompt 的 artifact refs 必须能从 workspace 直接定位到 `.loopora/runs/...` 下的真实文件，不能只暴露对 run 目录内部才有意义的短相对路径。
- 当角色尝试获取浏览器或截图证据失败时，诊断线索必须保留在 run event stream 与 step handoff 中，便于后续角色区分“产品问题”与“宿主环境阻断”。
- run 详情页的证据不应成为孤立终点。稳定目标是提供“基于本次证据修订方案”的入口，把 GateKeeper verdict、关键 blocker、残余风险和用户反馈带回 alignment revision；若当前实现暂未接入完整 API，也必须在设计上保留这条闭环，不把用户重新推回手工 prompt 编辑。

## 2.1 真实 CLI 集成验证

为了覆盖预设执行器与真实 workspace 的组合，仓库允许存在 opt-in 的真实 CLI 集成测试：

- 必须显式打 `real_cli` 标记，并默认跳过。
- 必须使用真实 provider CLI 与真实 workspace fixture 副本，不能退化为 `FakeCodexExecutor`。
- 断言应优先锁定基础设施契约，例如 run 能终结、角色 structured output 可读、resume 命令不再携带无效参数，而不是锁定模型审美或实现细节。
- 至少保留一个两轮以上的真实用例，用 `completion_mode=rounds` 强制走到第二轮 Builder `resume` 分支，覆盖跨轮次会话续接这条高风险链路。
- 当前真实 provider E2E 只覆盖 `preset` 模式，不覆盖 `command` 模式；若后续需要扩展，必须单独评估矩阵膨胀成本。
- 统一开关为 `LOOPORA_ENABLE_REAL_CLI_E2E=1`；默认关闭。
- `LOOPORA_REAL_CLI_TARGETS=codex,claude,opencode` 可缩小 provider 范围。若未设置，则按本机实际存在的 CLI 自动过滤。
- `LOOPORA_REAL_CLI_TIMEOUT_SECONDS` 控制单条 run 的最长等待时间。
- provider 模型覆盖通过可选环境变量注入：`LOOPORA_REAL_CLI_CODEX_MODEL`、`LOOPORA_REAL_CLI_CLAUDE_MODEL`、`LOOPORA_REAL_CLI_OPENCODE_MODEL`。
- 若环境缺少 CLI、浏览器或宿主权限，这类用例应明确 skip，而不是伪造成功结果。
- 除基础设施矩阵外，仓库还允许保留 scenario-driven 的真实 workflow 用例；这类用例应围绕教程里的真实样例场景组织，并把复制后的 workspace、`.loopora` 运行目录、proof 结果和 review 摘要落到 `artifacts/real_search_loop_e2e/<run-id>/...`，避免真实 run 结束后被清理。
- 这类 scenario fixture 可以是小型但真实的多模块 workspace，而不是单文件谜题；proof 应同时要求代码结果、设计说明和方向/复盘产物成立，避免模型只靠补报告或单点 hack 通过。

最小高风险矩阵如下：

| case | provider | workflow | completion mode | 关键断言 |
|------|----------|----------|-----------------|----------|
| Baseline pass | `codex / claude / opencode` | `fast_lane` | `gatekeeper` | run 正常结束；Builder / GateKeeper `ok=true`；无 `run_aborted` |
| Resume regression | `codex / claude / opencode` | `fast_lane` | `rounds` + `max_iters=2` | 第二轮 `builder_step.resume_session_id` 非空；provider resume argv 正确；最终 `rounds_completed` |
| Step isolation | `codex` | `repair_loop` | `rounds` + `max_iters=2` | `builder_step` 与 `builder_repair_step` 在第二轮分别恢复自己的 session，且不会串线 |

补充约束：

- 这些用例属于重型回归，不进入默认快速测试路径；设计目标是“手动触发或专门 CI 触发”，不是每次改动都跑。
- fixture 内必须自带可重复执行的本地 proof harness（例如 `tests/contract/*.mjs -> tests/evidence/*.json`）。真实 provider 跑完后，用例仍需重新执行 proof harness，确认工作区证据保持可读且可复验。

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
| `db` | 连接重试、schema 就绪、写路径完成、镜像失败、锁获取/释放、stop 信号投递结果与跳过原因 | 编排决策解释 |
| `service` | loop/run 生命周期、轮次推进、步骤开始结束、恢复、自我保护、终态 | HTTP 请求明细 |
| `web` | 请求完成、认证拒绝、SSE 故障、接口层领域错误、重放游标等非法输入被纠正 | 持久化细节 |
| `cli` | 命令触发、后台 worker 启停、CLI 失败 | Web 请求语义 |

run event stream 中，以下事件属于稳定白盒事件：

- `role_request_prepared`
- `step_context_prepared`
- `step_handoff_written`
- `parallel_group_started`
- `parallel_group_finished`
- `control_triggered`
- `control_completed`
- `control_failed`
- `control_skipped`
- `iteration_summary_written`

这些事件必须能被终端观察面直接订阅并渲染。
其中 `step_handoff_written` 必须携带 evidence ledger 路径和本 step 的 evidence refs，方便 UI 与调试工具从事件回到 canonical 证据源。
`parallel_group_started / finished` 只表达执行形状，不替代各 step 自己的 context、handoff 与 evidence 事件。
`control_*` 事件只表达受控误差机制的生命周期：为什么触发、调用了谁、引用了哪些 evidence refs、是否阻断或失败。control 完成时还必须在 evidence ledger 写入 `evidence_kind=control` 的 item；control 失败不能被静默吞掉。

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
