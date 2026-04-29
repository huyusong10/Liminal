# Interfaces

> 最高原则：遵循 `../core-ideas/product-principle.md`。接口层默认表达“任务、循环方案、证据、修订”，把 `bundle / spec / roles / workflow` 等内部资产留给专家路径。

## 1. 模块职责

接口层存在的唯一理由：

- 让 Web、CLI、HTTP API 以一致语义访问同一套任务治理、loop 编排和 run 观察能力。

它负责输入规范化、边缘校验、可视投影和权限边界，不负责业务编排本身。

## 2. 统一对象模型

| 对象 | 用户目的 | 稳定语义 |
|------|----------|----------|
| `loop` | 保存一套可重复执行的任务治理配置 | 绑定 workdir、spec、runtime 策略与 orchestration |
| `bundle` | 导入、导出或派生循环方案 | 把 `spec / role definitions / workflow / loop` 组织成单文件生命周期单元 |
| `orchestration` | 编辑可复用 workflow | 管理角色快照、步骤顺序与收敛规则 |
| `role definition` | 定义可复用角色模版 | 供 orchestration 复制成角色快照，并定义默认执行配置 |
| `run` | 观察一次具体执行 | 提供状态、事件、摘要、证据产物与终态 |
| `alignment session` | 把任务对话编译成循环方案 | 调用本机 AI Agent CLI，在 bundle 通过校验后提供 READY 预览与创建运行 |
| `skill installer` | 分发 repo-local Skill 到外部 AI Agent 工具 | 只做文件安装 / 下载辅助，不改变 Web 内置 alignment 的语义 |

## 3. 入口职责

| 入口 | 负责内容 | 不负责内容 |
|------|----------|------------|
| Web UI | 任务工作台、对话生成循环方案、方案库、专家资源编辑、run 观察 | 直接实现业务编排 |
| CLI | 自动化、脚本化创建 / 运行 / 校验 / 导入导出 | 维护独立业务状态 |
| HTTP API | Web 与集成调用方的结构化访问面 | 暴露底层存储实现 |

Web 顶层信息架构按用户任务组织：

| 顶层入口 | 稳定目的 | 路由 |
|----------|----------|------|
| 工作台 / Workbench | 查看当前任务、loop 与最近 run 状态 | `/` |
| 新建任务 / New Task | 通过对话生成循环方案并创建运行 | `/loops/new/bundle` |
| 方案库 / Plans | 管理可复用循环方案与 bundle 文件 | `/bundles` |

角色定义、workflow / orchestration、手动创建、工具与 Skill、教程、主题和语言设置属于资源与设置入口。它们保留独立路由与对象管理能力，但不作为默认顶层任务导航词。

## 3.1 默认语言与专家语言

接口层必须把默认主路径压成五个用户动作：

`描述任务 -> 确认循环方案 -> 运行 -> 看证据结论 -> 修订方案`

稳定语言边界：

| 场景 | 默认语言 | 可出现的专家语言 |
|------|----------|------------------|
| 新建任务主路径 | 任务、循环方案、证据、裁决、修订 | 只在展开的专家视图、tab 标签或源文件操作中出现 `spec / roles / workflow` |
| READY 预览 | 任务目标、主要风险、证据路径、裁决方式、运行目录 | YAML、bundle、import、orchestration 只属于专家操作或调试材料 |
| run 详情首屏 | 关键结论、证据覆盖、GateKeeper 裁决、下一步建议 | ledger、artifact、event stream、raw output 只属于追查入口 |
| 方案库默认列表 | 方案、修订、导出、删除 | Bundle ID、surface diff、YAML、linked assets 属于详情页专家区 |

稳定规则：

- 默认路径不要求用户先理解 `bundle / orchestration / workflow controls / YAML`。
- `READY` 可以作为内部状态或小状态标识，但默认主动作表达为“方案已准备好，可以创建并运行”。
- 专家语言必须保留可达性；隐藏只是信息层级调整，不能删除导入、导出、派生、surface 编辑或源文件同步能力。
- 页面测试优先断言用户动作、可达区域和 `data-testid`，不要把具体中英文文案锁成契约。

## 4. 跨入口一致性

以下能力必须跨入口保持同一语义：

| 能力 | 一致性要求 |
|------|------------|
| 创建 loop | 相同参数表达相同 loop definition |
| 导入 / 导出 / 派生 / 删除 bundle | 表达同一整包生命周期语义 |
| 预览 bundle | 只读校验与投影，不创建底层资产 |
| 选择 orchestration | 引用同一编排资产 |
| 编辑 role definition | 角色模版、权限边界、执行配置与 prompt 语义一致 |
| 配置 completion mode | `gatekeeper` 与 `rounds` 的收敛语义一致 |
| 启动、停止、删除 run | 生命周期语义一致 |
| 观察 run artifacts / evidence | artifact 列表用于追查细节，`evidence/ledger.jsonl` 是证明项与 GateKeeper verdict 的事实源 |
| 安装 task-alignment Skill | 只分发 repo-local Skill，不改变 bundle 或 run 契约 |

允许交互形态不同，例如 Web 可以提供可视化 workflow 编辑器、对话式 alignment、主题和语言偏好；CLI 可以提供同步等待与后台执行开关。但这些差异不能改变底层语义。

CLI 对高阶 workflow 的稳定承诺：

- 通过 `--workflow-preset` 选择少数内置治理形状。
- 通过 `--workflow-file` 承载完整 `workflow` contract，包括 `parallel_group` 与 `inputs`。
- 不为每个 workflow 字段提供一组顶层 flags，避免 CLI 变成难维护的流程编程界面。

## 5. Web 路由心智

| 路由 | 用户心智 | 稳定职责 |
|------|----------|----------|
| `/` | 工作台 | 当前任务、loop 与 run 状态入口 |
| `/loops/new/bundle` | 新建任务 | 对话生成循环方案、READY 预览、创建并运行 |
| `/loops/new/manual` | 专家手动创建 | 手动选择 spec、workflow、executor，或导入已有 bundle YAML |
| `/bundles` | 方案库 | 管理可复用循环方案、导出、删除、派生和 revision 入口 |
| `/roles` / `/orchestrations` | 资源库 | 编辑可复用角色与 workflow 资产 |
| `/tools` | 工具与 Skill | 管理外部 AI Agent Skill 安装与下载 |
| `/tutorial` | 使用教程 | 帮用户判断何时使用 Loopora，以及从哪条路径开始 |

旧路由可以保持兼容跳转，但新的默认心智不得再要求新手先理解内部对象。

## 6. 安全边界

| 边界 | 接口层责任 |
|------|------------|
| 本地与网络访问 | 本地默认安全优先；网络暴露必须显式开启 |
| 文件系统访问 | 所有路径必须受允许根范围约束 |
| 文件预览 | 按不可信内容处理，不能直接执行 |
| 输入规范化 | 坏 JSON、缺失字段、越界参数必须返回明确 4xx |
| workdir 操作 | 不得绕过 workspace safety guard 或 run lock |
| 本地化 | 文案可变；测试锚点和接口契约不能绑定某种展示语言 |

## 7. 依赖方向

依赖方向必须保持为：

`用户交互 -> 接口层 -> orchestration service`

禁止：

- Web 直接实现业务编排
- CLI 维护独立状态模型
- API 直接暴露持久化层细节
- 页面预览行为与实际提交行为不一致

## 8. 变更触发

以下变化需要更新本文档：

- 新增或删除顶层入口
- 跨入口能力模型变化
- 某个核心对象只能在单一入口创建或编辑
- 角色定义 / 编排 / 创建循环的责任边界变化
- 安全边界变化

以下变化通常不需要更新本文档：

- 页面改版
- 帮助文案调整
- 局部字段扩展

## 9. 非目标

- 不把 Web 做成通用 IDE。
- 不让 CLI 承担复杂可视化职责。
- 不把 HTTP API 扩张成公网平台接口。
