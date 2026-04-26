# Web Bundle Alignment

## 1. 模块职责

本文档定义 Web 内置的 bundle 对齐入口。

它的唯一理由是：

- 让新手用户直接在 Web 里描述需求
- 由后端调用本机 Agent CLI 完成多轮对齐
- 在生成物通过硬校验后，把 bundle 预览、导入和运行收敛成一条主流程

它不是：

- 新的 CLI 命令
- 新的 bundle 格式
- 通用聊天系统
- 独立于 `spec / role definitions / workflow` 的第四种运行资产

## 2. 产品判断

现有推荐路径是：

`用户描述任务 -> 外部 Agent + loopora-task-alignment Skill -> YAML bundle -> Bundle 对话页导入 -> 运行`

Web bundle alignment 把前半段收进 Loopora Web：

`用户描述任务 -> Web alignment session -> 后端 Agent CLI -> YAML bundle -> READY 预览 -> 一键导入并运行`

稳定承诺：

- 用户可以完全不理解 Skill 安装、prompt 拼装或外部 Agent 操作。
- 最终产物仍然必须是单文件 YAML bundle。
- READY 只表示 bundle 文件已经存在并通过硬校验，不表示 loop 已经导入或运行成功。
- 外部 Skill 安装路径继续保留，作为高级或跨工具路径。

## 3. Web 入口

Web 只提供一个可视入口，不新增 CLI 能力。

Web 创建入口拆成三条路由：

| 路由 | 职责 |
|------|------|
| `/loops/new` | 轻量选择页，解释 Bundle-first 与手动专家模式的区别 |
| `/loops/new/bundle` | 对话生成 bundle、已有 YAML / 文件预览导入、READY 预览与导入运行 |
| `/loops/new/manual` | 手动创建 loop，直接选择 spec、workdir、workflow 和运行参数 |

Bundle 页首帧采用主流 LLM 对话界面：极简输入框为主，配置只作为轻量辅助。页面首帧应表达为：

| 控件 | 语义 |
|------|------|
| CLI 工具选择 | 选择后端要调用的 Agent CLI：`Codex / Claude Code / OpenCode / Custom CLI` |
| 目标项目目录 | 这次 bundle 最终要运行的 workdir；默认使用最近目录或浏览选择 |
| 需求输入框 | 默认 placeholder：`你想做什么需求？` |
| 发送按钮 | 创建或继续当前 alignment session |

补充规则：

- Workdir 是唯一必须暴露的环境字段，因为 bundle 契约要求 `loop.workdir`。
- 模型、推理强度、自定义命令参数属于高级设置，默认折叠。
- 执行工具配置语义与角色定义页一致：预设模式只暴露模型与推理强度；自定义命令模式直接维护 CLI 与参数模板，并让模型 / 推理强度成为不可编辑参考；`Custom Command` 只支持自定义命令，OpenCode 默认推理强度为空。
- 同一张卡片必须保留“已有 bundle YAML / 文件”的导入路径，并与对话生成路径共享 READY / preview 组件。
- 页面文案不应要求用户理解“spec / roles / workflow”才能开始。
- Bundle 页必须提供“新建对话”和历史对话入口；历史来自后端 alignment sessions。
- 手动创建页不承载 bundle 对齐逻辑，避免把 posture 对话和人工规则编排混在同一个 surface。

## 4. Alignment Session

alignment session 是 Web 内置对齐流程的最小状态单元。

它保存：

| 字段 | 作用 |
|------|------|
| session id | Web 对话与后端任务的稳定标识 |
| executor settings | 当前选择的 CLI 工具与高级执行参数 |
| target workdir | bundle 中的目标项目目录 |
| message transcript | 用户消息与 Agent 可见回复 |
| live events | CLI 原始输出和系统状态事件 |
| bundle path | 本 session 期望生成的 bundle 文件路径 |
| validation result | 最近一次 bundle 硬校验结果 |
| executor session ref | 后端 CLI 原生 session / rollout 引用，用于后续对话继承上下文 |
| linked bundle / loop / run | 导入并运行后关联到现有对象 |

状态机：

| 状态 | 含义 |
|------|------|
| `idle` | 尚未发送需求 |
| `running` | 后端 CLI 正在执行 |
| `waiting_user` | Agent 已返回澄清问题，需要用户继续回答 |
| `validating` | 检查指定位置的 bundle 文件 |
| `repairing` | bundle 校验失败后自动回灌错误，让 Agent 修复一轮 |
| `ready` | bundle 文件存在且通过硬校验 |
| `failed` | CLI 失败、超时、被取消或自动修复后仍无效 |
| `imported` | bundle 已物化为 Loopora 资产 |
| `running_loop` | 导入后已启动 run |

补充规则：

- 不做版本管理；用户需要重新开始时主动新建 session。
- 页面刷新后应能恢复当前 session 的 transcript、状态和 READY bundle。
- 后续用户回复和自动修复默认继承同一 CLI session；若 provider resume 失败，系统回退到 transcript prompt，并记录可见事件。
- 活动 session 必须能取消；取消应停止子进程并收敛为可解释状态。

## 5. Agent 调用

后端调用 Agent CLI 时，不要求目标工具安装 Skill。

系统 prompt 由以下内容装配：

1. `loopora-task-alignment/SKILL.md`
2. `references/bundle-contract.md`
3. 若是修订或优化，追加 `references/feedback-revision.md`
4. 当前 session transcript
5. 目标 workdir、bundle 输出路径、当前校验结果
6. 输出纪律：若尚需澄清，直接提问；若 bundle 已成形，必须把完整 YAML 放入结构化字段 `bundle_yaml`

稳定规则：

- 这里的 Skill 内容只是 prompt 输入，不是外部工具安装或运行时 Skill 调用。
- Agent 可以进行多轮澄清，但 READY 前必须返回单文件 YAML bundle 的完整文本。
- Agent 不直接写入 session 文件；服务层从结构化 `bundle_yaml` 写入 session `bundle.yml`。
- 后端不接受模型自由声明“已经生成好了”作为 READY 依据。
- READY 的唯一依据是指定路径存在 YAML，且通过 `load_bundle_text / normalize_bundle` 与 `spec.markdown` 编译校验。
- 结构化输出包含 `session_ref`；为兼容严格 structured-output 校验，它结构上必填、语义上可空，只接受少量字符串键（如 `session_id / thread_id / conversation_id / provider / raw_json`）。没有原生引用时这些键使用空字符串。服务层会和 executor 捕获到的 session ref 合并保存。
- Custom CLI 通过 `{resume_session_id}`、`{session_ref_json}`、`{alignment_session_id}` 等参数模板占位符接入自己的 resume 协议；不强制要求所有自定义命令实现原生 session。

## 6. 硬校验与自动修复

bundle 检查器必须复用现有 bundle 契约校验。

检查流程：

1. Agent 执行结束。
2. 后端读取结构化输出：`assistant_message`、`needs_user_input`、`bundle_yaml`。
3. 若 `bundle_yaml` 为空，session 进入 `waiting_user` 或 `failed`，取决于 Agent 是否提出了澄清问题。
4. 若 `bundle_yaml` 非空，服务层写入 session bundle path。
5. 对写入的 bundle YAML 运行硬校验，包括 bundle 结构、目标 workdir 和 `spec.markdown` 可编译性。
6. 校验通过，session 进入 `ready`。
7. 校验失败，默认把错误、原 YAML 和输出要求回灌给同一 Agent 自动修复一轮。
8. 自动修复仍失败，session 进入 `failed`，并展示可读错误与重试入口。

补充规则：

- 自动修复轮数默认 1 次，避免无限消耗。
- 校验错误展示给用户时应摘要化，原始错误可折叠查看。
- 校验通过后，系统应重新规范化导出 YAML，保证预览与导入消费的是同一份 bundle。

## 7. LIVE 输出

聊天窗必须展示 CLI 的实时返回。

可复用现有 run console 的视觉语言：

- Status：系统状态、READY、校验、自动修复、导入运行
- Actions：CLI 命令、工具调用、文件写入、检查动作
- Result：Agent 的自然语言回复、澄清问题、最终摘要

但 alignment session 不是 run：

- 它不创建 loop run record。
- 它不占用 workdir run lock。
- 它可以复用终端组件样式和流式事件机制，但事件对象应归属于 alignment session。

## 8. Bundle 预览

session 进入 READY 后，页面自动展示 bundle 细节。已有 bundle YAML / 文件也可以先调用同一预览能力，再决定是否导入。

预览面按用户心智命名，而不是优先暴露内部术语：

| 预览区 | 数据来源 | 用户语义 |
|--------|----------|----------|
| 任务契约 | `spec.markdown` | 这次要做什么、什么算完成、哪些假完成不可接受 |
| 协作角色 | `role_definitions` | 每个角色在本任务里的工作姿态 |
| 执行流程 | `workflow.roles / workflow.steps / collaboration_intent` | 谁先做、谁取证、谁裁决、何时收束 |
| 源文件 | session bundle path 或用户输入的 YAML / 文件 | 可直接查看完整 YAML |

流程图规则：

- 图中的节点必须来自当前 bundle 的 `workflow.steps`。
- 节点展示对应 role 的用户可读名称和 archetype。
- GateKeeper `on_pass=finish_run` 应可视化为收束出口。
- 图不能按固定 archetype 写死，必须按 bundle workflow 渲染。
- 节点 hover / focus 不应移动图形本体；角色概要应通过浮层展示。

补充规则：

- 源文件查看只读即可；继续优化优先通过下一轮对话完成。
- 若用户需要手动改 YAML，可以作为高级操作提供“编辑源 YAML 并重新校验”，但这不是默认新手路径。

## 9. 导入并运行

READY 后提供主操作：

`导入 Bundle 并运行`

该操作必须复用现有 bundle 导入能力：

- 从 session bundle path 或规范化后的 YAML 导入
- 物化 bundle、role definitions、orchestration 与 loop
- 若用户选择“导入并运行”，立即创建 run 并跳转到 run 详情
- 若只导入，则跳转到 loop 或 bundle 详情

稳定规则：

- 导入后的资产仍属于同一 bundle 生命周期。
- 后续删除、导出、派生、surface 编辑和 revision bump 继续沿用现有 bundle 语义。
- alignment session 只是上游生成入口，不改变 bundle 导入后的生命周期。

## 10. HTTP API

Web alignment 暴露 session 级 API，不新增 CLI interface。

| API | 语义 |
|-----|------|
| `POST /api/alignments/sessions` | 创建 session，可带首条用户需求并立即启动 |
| `GET /api/alignments/sessions` | 返回最近 alignment sessions，用于历史对话列表 |
| `GET /api/alignments/sessions/{id}` | 读取 session、状态、transcript 与校验摘要 |
| `POST /api/alignments/sessions/{id}/messages` | 追加用户回复并继续对话 |
| `POST /api/alignments/sessions/{id}/cancel` | 停止当前活动 CLI |
| `GET /api/alignments/sessions/{id}/events?after_id=` | 轮询 session 事件 |
| `GET /api/alignments/sessions/{id}/stream?after_id=` | SSE live 输出 |
| `GET /api/alignments/sessions/{id}/bundle` | 返回 normalized bundle、YAML、spec HTML、workflow preview 与 validation |
| `POST /api/alignments/sessions/{id}/import` | 导入 READY bundle，可选择立即启动 run |
| `POST /api/bundles/preview` | 对用户提供的 bundle YAML 或路径做只读校验与预览投影 |

稳定规则：

- 这些 API 归属于 Web 内置入口；不要求 CLI 提供同构命令。
- `/api/alignments/*/import` 必须复用现有 bundle import 服务，不直接物化底层资产。
- `/api/bundles/preview` 不创建 bundle、loop 或 run；它只复用 bundle 契约校验和预览投影。

## 11. 错误与恢复

用户可理解的错误面至少包括：

| 错误 | 处理 |
|------|------|
| CLI 不存在 | 提示安装或切换工具 |
| CLI 执行失败 | 保留 live 输出，允许重试 |
| Agent 需要澄清 | 进入 `waiting_user`，显示问题并保留输入框 |
| bundle 文件不存在 | 提示 Agent 尚未写出 bundle，可继续对话或重试 |
| bundle 校验失败 | 自动修复一轮；失败后展示摘要错误 |
| 导入失败 | 保留 READY bundle，不清空 session，允许用户修正后重试导入 |

补充规则：

- 失败不得吞掉 session transcript。
- READY bundle 不应因为导入失败而被删除。
- 用户取消活动 CLI 后，应能继续发送新消息重启同一个 session。

## 12. 非目标

- 不新增 CLI 命令。
- 不要求安装 `loopora-task-alignment` Skill 才能使用 Web 内置入口。
- 不做 bundle 版本历史、diff 或回滚。
- 不把 alignment session 变成长期用户人格建模。
- 不让 Agent 在 READY 前直接物化 loop。
- 不让 Web 直接绕过 bundle 导入流程创建底层资产。

## 13. 验收标准

最小可接受版本必须满足：

- 创建循环选择页能进入 Bundle 对话页；Bundle 对话页能从“输入需求”启动 alignment session。
- 聊天窗能实时展示 CLI 输出，并能继续多轮回答。
- 多轮回答默认继承 provider CLI session；不支持或失败时有 transcript prompt fallback。
- Agent 生成的 `bundle_yaml` 必须由服务层写入 session 指定路径。
- READY 只在 bundle 文件存在且硬校验通过后出现。
- READY 后自动展示任务契约、协作角色、执行流程图和源 YAML 入口。
- 用户可以一键导入 bundle 并启动 run。
- 外部 Skill 安装路径仍可用，且不与 Web 内置入口互相依赖。
