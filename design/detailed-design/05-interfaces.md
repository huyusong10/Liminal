# Interfaces

> 最高原则：遵循 `../core-ideas/product-principle.md`。Web 接口层默认把 `Loop` 作为唯一主对象，表达 Loop、运行、证据、运行状态和 Loop 裁决；`bundle / spec / roles / workflow` 等内部资产留给专家路径或源文件操作。

## 1. 模块职责

接口层存在的唯一理由：

- 让 Web、CLI、HTTP API 以一致语义访问同一套 Loop 编排、运行、自动迭代、运行状态、Loop 裁决和运行观察能力。

它负责输入规范化、边缘校验、可视投影和权限边界，不负责业务编排本身。

## 2. 统一对象模型

| 对象 | 用户目的 | 稳定语义 |
|------|----------|----------|
| `loop` | 保存一套可重复执行的长期工作编排 | 绑定 workdir、spec、runtime 策略与 orchestration |
| `bundle` | 导入、导出或派生 Loop | 把 `spec / role definitions / workflow / loop` 组织成单文件交换单元 |
| `orchestration` | 编辑可复用 workflow | 管理角色快照、步骤顺序与收敛规则 |
| `role definition` | 定义可复用角色模版 | 供 orchestration 复制成角色快照，并定义默认执行配置；本次 step 的实际行动权限由 workflow 决定 |
| `run` | 观察一次具体执行 | 提供运行状态、事件、摘要、证据产物、Loop 裁决与终态原因 |
| `alignment session` | 通过对话编排或调整 Loop | 调用本机 AI Agent CLI，在 bundle 通过校验后提供 READY 预览与创建运行 |

## 3. 入口职责

| 入口 | 负责内容 | 不负责内容 |
|------|----------|------------|
| Web UI | 已有 Loop 日常管理、运行观察、对话编排 Loop、方案文件导入导出、专家资源编辑 | 直接实现业务编排 |
| CLI | 自动化、脚本化创建 / 运行 / 校验 / 导入导出 | 维护独立业务状态 |
| HTTP API | Web 与集成调用方的结构化访问面 | 暴露底层存储实现 |

Coding 场景的推荐 first-use path 是从宿主 Agent 触发 `/loopora-gen` 和 `/loopora-loop`；Web 信息架构仍必须完整支持 Web-only 编排、观察和专家编辑，但默认教程和 README 不应把用户先拉离当前 Coding Agent 才能开始。Tools 页承接“安装 Coding Agent 入口”的 first-run 出口时，Coding Agent 接入必须先于防休眠、本地资产健康等低频维护工具出现，避免用户从默认路径落入维护面板。

CLI 顶层帮助页也属于 first-use surface：即使保留专家命令，帮助描述必须先说明 `loopora init <agent>` -> `/loopora-gen` -> `/loopora-loop` 的默认路径，并让安装入口在子命令列表中先于资源库、角色、流程和 spec 等专家入口出现。

Web 顶层信息架构按用户反复回来的理由组织：

| 顶层入口 | 稳定目的 | 路由 |
|----------|----------|------|
| Loop / Loops | 高频工作台：查看活动 Loop、进入已有 Loop 与最近运行 | `/`、`/loops/{id}` |
| 编排 / Compose | 专业编排工作台：通过对话编排 Loop，并保留导入方案文件与手动编排的二级入口 | `/loops/new/bundle`、`/loops/new/manual` |
| 资源库 / Library | 管理方案文件、可复用角色定义与流程编排 | `/bundles`、`/roles`、`/orchestrations` |
| 工具 / Tools | Coding Agent 入口接入、运行辅助与本机维护 | `/tools` |
| 教程 / Tutorial | 帮用户判断何时使用 Loopora，以及从哪条路径开始 | `/tutorial` |

教程页是顶层 fit 判断的公开投影，必须与 product primer 和 Human-Shaped Loop 的适配门保持同一语义：一次 Agent + review 是否足够、后续是否产生新证据、判断是否已能稳定 benchmark 化、是否存在假完成阻断价值，以及这套判断是否需要活过一次聊天并成为运行继承、导出复用或后续审计的对象。页面可以调整表达和顺序，但不得把“判断是否需要活过一次聊天”从新手判断入口里丢掉。教程页也属于 README first-use 的延伸：首屏必须给出安装 Coding Agent 入口和 Web 对话编排的直接出口，不能让用户必须读完多屏概念解释才能回到默认路径。教程解释 prompt / 可运行判断差异时，默认文案应先使用“判断 / judgment”，只有专家编辑或运行追踪语境才暴露 posture；同时必须保留 `spec / roles / workflow / evidence` 的核心语义，不得把 evidence 降成运行后的附属日志。

创建 Loop 不是单一频率动作：`对话编排 Loop` 是专业主入口，必须是一级导航可达的完整工作台；Loop 工作台不重复编排模式按钮，也不得把它压成内嵌表单。编排工作台稳定提供：

- 对话编排：默认推荐入口，路由 `/loops/new/bundle`。
- 导入方案文件：已有 YAML / bundle 文件入口，路由 `/loops/new/manual#bundle-import-form`。
- 手动编排：专家直接选择 Loop 契约、工作目录、流程和运行策略，路由 `/loops/new/manual#manual-loop-form`。

创建方式选择页属于默认路径：推荐项应表达为用自然语言整理任务判断和证据要求，而不是通用聊天；对话编排空态和 composer placeholder 必须提示用户输入任务、假完成风险、必需证据和阻断风险，不得退回“你想让 Loopora 做什么”这类普通助手输入框心智。手动分支应表达为用户已明确契约、检视角色和运行流程，而不是要求新手理解底层运行资产。

对话编排 composer 是 README-first Web 路径的首个输入控件。窄屏下它必须完整显示默认 placeholder 或已输入的首行任务判断提示，不能因为 `rows=1`、固定高度或发送按钮占位导致文本在控件内部裁切或滚动。

编排工作台的侧栏在桌面承担历史和模式切换；窄屏下不得以整块侧栏占据首屏主要纵向空间。新对话、对话编排、导入方案文件和手动编排入口应压缩成紧凑模式条，使用户进入 Web 编排后优先看到任务判断问题和 composer。

三条编排路径共享同一个工作台导航框架：左侧稳定保留新对话、最近对话和模式入口；右侧根据模式呈现对话编排、方案文件导入或手动编排内容。用户进入导入或手动模式后仍能回到对话编排和历史对话，不应被带到一个脱离编排上下文的普通表单页。

编排模式是互斥内容面：导入方案文件与手动编排不能在同一右侧内容区同时展开；READY 预览、错误态和空态必须有稳定最小宽度，中文标题不得因为容器收缩变成逐字竖排。

方案包 / bundle 是 Loop 的导入、导出和专家交换格式。默认展示优先使用“方案文件 / plan file”，需要解释内部交换格式时才补充 bundle；它属于资源库，不承担“已有 Loop 日常管理”的心智。README 这类 first-use 文档也应先用方案文件 / plan file 解释可审查、可携带的 Loop 形态，避免把 Bundle 作为新手入口词。
方案详情页展示的底层 spec 是专家 source surface；本地 spec 文件不可按 UTF-8 读取时，页面必须保留可打开状态并显示可读错误，允许用户通过表单修正，而不是让详情页 500。

主题和语言设置属于顶栏显示偏好控件，不混入资源或创建菜单。显示偏好是低频辅助动作，顶栏只保留轻量触发器；主题和语言的完整切换控件应放在弹出面板里，不能以两个常驻 segmented control 的面积和选中态抢占主导航优先级。

顶层导航的同级选择必须使用同一套尺寸和状态语法：普通链接、当前项和带二级菜单的入口不能因为实现元素不同而改变宽度、边框、阴影或选中形态。带二级菜单的入口用轻量方向提示表达“可展开”，不得表现成独立卡片或表单按钮。顶栏属于全局 chrome，不能被具体页面 shell 或 `100dvh` 内容区压缩；同一 viewport 下，Loop 工作台、编排工作台、资源库、工具和教程页面的顶栏高度必须一致。常见手机宽度应让所有顶层入口同时可见；更窄设备横向导航装不下所有入口时，当前页面入口仍必须在首屏可见，不能只露出选中背景或要求用户先猜测并横向拖动。

图标型提示控件属于表单辅助动作，不承载主要命令；它们可以比主按钮更轻，但必须保留稳定可点区域、焦点态和明暗主题下相同的视觉语法，不能因为只显示一个符号而退化成不可点击的小字标。

状态胶囊、最近路径快捷项、空态装饰和诊断摘要属于辅助信息层。它们可以帮助用户判断系统状态或快速填充表单，但视觉重量不得接近主操作按钮；默认应使用更轻的背景、较小高度和弱阴影，只在错误、运行中或需要用户关注时提高状态颜色。

可复用流程图是资源库、编排工作台和 READY 预览的共享解释面。任何页面只要渲染 workflow loop 图，就必须同时提供专用图形样式，使线条、节点、标签、中心标识和图例保持可读；不得只加载结构化 SVG / JS，让浏览器默认黑色填充或描边接管图形表现。若 workflow 包含连续 Inspector / Custom `parallel_group`，流程图和摘要必须把它显示成有界并行检视，而不是只呈现为普通线性步骤。

响应式表单、详情页历史列表和专家编辑页不能依赖外层 `overflow: hidden` 掩盖横向溢出；当 viewport 收缩时，字段、辅助动作、时间戳和长路径必须在可见区域内换行、收缩或省略，不能形成被裁掉但无法滚动抵达的内容。

普通 Web 页面共享同一套主容器宽度语义：Loop 工作台、资源库、工具、教程、Loop 详情和运行详情使用统一的页面最大宽度与响应式 gutter，不按页面类型在大屏继续各自扩宽。全宽只属于明确的工作台 shell，例如编排工作台或全屏控制台；即使 shell 全宽，内部表单、预览、阅读和 composer surface 仍应回到共享页面宽度或更窄的阅读宽度。多 DPI 不产生新的布局契约，界面按 CSS viewport、共享容器宽度、gutter 和断点适配。

公开 SVG 资产属于接口层的可视投影边界。Logo 与文档图必须是自包含、可解析的 SVG：logo 变体要能在透明 surface、浅色 surface 和深色替换路径里保持识别，不依赖负字距或固定白底来成立；文档图要提供可访问标题与描述，使用高对比、中性为主且不过度绑定单一页面主题的视觉语法。根目录 README / Human-Shaped Loop 文档引用的图属于 source distribution 公开资产，必须随 `assets/diagrams` 和 `src/loopora/assets/logo` 一起进入 manifest，避免安装包或源码包失去顶层理解入口。验证入口分两类：日常静态 SVG 契约测试与 Web 页面中 logo 引用测试只保护可解析性、可访问元数据、分发声明、脆弱排版和历史 palette 回流，不把具体绘制坐标或文案锁成接口契约；渲染后的拥挤、重叠、裁切和响应式可读性属于 opt-in review case，由 `tests/reviews/` 用同一套 case/runner 覆盖 SVG diagram 与 Web 页面。语言、概念一致性和 Agent-native 体验这类模糊判断也进入同一 review case 机制，通过文本索引、artifact 预览和 machine hints 收集证据，不写成具体文案或 DOM 断言；其中 term hints 只扫描面向用户或 reviewer 的可见文本、可访问标签和本地化字符串，不把 route、DOM id、`data-testid`、变量名或文件路径这类实现标识当作默认语言问题。Logo 资产不进入 review case。

## 3.1 默认语言与专家语言

接口层必须把默认主工作流压成四个用户动作：

`编排 Loop -> 运行 -> 看证据 -> 看运行状态与 Loop 裁决`

稳定语言边界：

| 场景 | 默认语言 | 可出现的专家语言 |
|------|----------|------------------|
| 创建 Loop 主路径 | Loop、运行、证据、运行状态、Loop 裁决 | 只在展开的专家视图、tab 标签或源文件操作中出现 `spec / roles / workflow` |
| READY 预览 | Loop 目标、主要风险、证据路径、覆盖目标、执行策略、裁决方式、运行目录 | YAML、bundle、import、orchestration 只属于专家操作或调试材料 |
| 运行详情首屏 | 运行状态、Loop 裁决、已证明、未证明、阻断问题、残余风险 | ledger、artifact、event stream、raw output 只属于追查入口 |
| 结果后动作 | 接受结果、再次运行、修改 Loop、导出、停止 | 对话改进、YAML、source artifact 只属于用户主动入口 |
| Loop 工作台 | 活动 Loop、已保存 Loop、最近运行、最近裁决、启动运行、进入编排工作台 | Bundle ID、YAML、linked assets 属于方案包详情或专家区 |
| 方案详情 | 方案文件、治理投影、流程风险、运行前审计 | 源 YAML、Bundle ID、底层资产只在专家区出现 |
| 编排工作台 | 对话编排 Loop、运行目录、READY 预览、创建并运行、导入方案文件、手动编排 | 源 YAML 和底层对象只在专家视图或二级入口中出现 |
| 运行详情 | 运行、状态、最近裁决、对应 Loop | 不编辑 Loop 定义，不承担资源管理 |

稳定规则：

- 默认路径不要求用户先理解 `bundle / orchestration / workflow controls / YAML / GateKeeper`；README 与 first-use surfaces 应先使用 Loop 裁决、任务裁决和证据覆盖这类用户级语言，只有在专家编辑、运行追踪或内部角色解释中才暴露角色名。
- Loop 工作台与 Loop 详情页的稳定字段应使用“运行流程 / Run flow”、“Agent 执行 / Agent execution”、“收束方式 / Closure”和“任务契约路径 / Task contract path”这类用户级标签；`orchestration`、`role runtime`、`completion mode`、`spec path` 只属于专家源文件、API、测试 ID 或调试语境。
- 由方案文件导入或派生的 Loop 可以说明“来源方案”和删除时的关联资源清理，但默认卡片不能把 `bundle-managed` 或整包 lifecycle 当成已有 Loop 日常管理的主心智。
- Web 问答、直接导入 bundle 与专家手动创建 Loop 是取得 Loop 的并列场景；默认创建动作可推荐 Web 问答，但不能把它写成唯一主工作流。
- “运行列表”不再作为独立一级页面。运行是 Loop 的一次活动事实：高频查看入口在 Loop 工作台活动区、Loop 详情的运行历史和 run 详情页。
- 方案详情和 run 详情可以提供“对话改进方案”能力；它是用户主动调用的候选 Loop 生成入口，不进入默认主工作流概念。
- `READY` 可以作为内部状态或小状态标识，但默认主动作表达为“Loop 已准备好，可以创建并运行”。
- 专家语言必须保留可达性；隐藏只是信息层级调整，不能删除导入、导出、派生、surface 编辑或源文件同步能力。
- 页面测试优先断言用户动作、可达区域和 `data-testid`，不要把具体中英文文案锁成契约。
- 运行状态与 Loop 裁决必须分开展示；`succeeded`、`failed`、`stopped` 等 run status 不能替代 GateKeeper / evidence 得出的 task verdict。
- 面向用户的 run lifecycle 标签必须使用中性生命周期语义；`succeeded` 可以表示运行正常收束，但不能被展示成任务已完成或已证明。
- run detail 的 progress 阶段、服务端 seed 与终态 chip 也属于 lifecycle 投影；终点只能表达运行收束 / 结束，不能使用 `Done`、`完成` 这类会被读成任务达标的文案。
- run detail 的 progress caption 若解释为什么不显示完成百分比，必须表达为“按阶段耗时展示 / 不猜测完成百分比”的产品语义；不得用实现历史或调试口吻暗示 UI 曾经有“假百分比”。
- run detail 的 queued 提示应表达为等待运行位置或前序工作清空，不把 `executor` 暴露成默认用户心智。
- Loop 工作台卡片可以用运行状态胶囊表达生命周期，但卡片摘要遇到终态 task verdict 时必须优先表达 Loop 裁决，例如证据不足、未通过、带残余风险通过或已通过，避免把 `succeeded` 看成任务已证明。
- 中文 Web 页面只有 `Loop` 作为稳定英文主对象词；`Runs` 必须显示为“运行”，`spec` 显示为“Loop 契约”或专家标签里的“契约”，`bundle` 显示为“方案包 / 方案文件”，`workflow` 显示为“流程 / 流程编排”。代码、API、测试 ID 和英文界面不受此展示语言约束。

## 3.2 CLI 分发与命令入口

CLI 的稳定入口是 Python package metadata 暴露的 `loopora` console script。用户路径必须表达“一次安装，之后直接运行 `loopora`”，而不是要求每次通过项目环境前缀执行。

稳定规则：

- 发布包后推荐以 CLI tool 形态安装，例如 `uv tool install loopora` 或 `pipx install loopora`；`python -m pip install loopora` 只作为已激活虚拟环境中的 pip 路径。
- 从源码试用或贡献时，若目标是得到同一个稳定命令，使用 editable tool install，例如 `uv tool install --editable .`。
- `uv run loopora ...` 只属于开发 fallback，不作为 Quick Start、自动化或用户 CLI 示例的默认表达。
- packaging 契约测试必须保护 console script 名称和入口对象，避免发布包或源码安装丢失 `loopora` 命令。
- CLI 命令回调可以保留公开 option / argument 的完整参数面，用来稳定 help、解析、completion 与脚本兼容性；内部创建、派生、运行等 helper 不应继续复制长参数列表，应通过 typed request object 或同等结构化输入承载。

## 3.3 Agent-first Adapter 入口

Agent-first 入口必须仍然遵守“接口层 -> Core”的依赖方向。CLI 和 Web 可以安装、卸载和展示 Coding Agent adapter，但不得各自实现一套宿主文件逻辑。

第一阶段稳定入口：

| 入口 | 语义 |
|------|------|
| `loopora init codex` | 在当前项目安装或更新 Codex 项目级 Loopora entry |
| `loopora init claude` | 在当前项目安装或更新 Claude Code 项目级 Loopora entry |
| `loopora init opencode` | 在当前项目安装或更新 OpenCode 项目级 Loopora entry |
| `loopora uninstall codex` | 只删除 Loopora 管理的 Codex 项目级入口文件或 manifest |
| `loopora uninstall claude` | 只删除 Loopora 管理的 Claude Code 项目级入口文件或 manifest |
| `loopora uninstall opencode` | 只删除 Loopora 管理的 OpenCode 项目级入口文件或 manifest |
| `loopora agent codex gen` / `loopora agent claude gen` / `loopora agent opencode gen` | 宿主 entry 使用的底层入口，把候选 bundle 交给 Core 校验，并返回 Loop 预览 URL |
| `loopora agent codex loop` / `loopora agent claude loop` / `loopora agent opencode loop` | 宿主 entry 使用的底层入口，查找当前 session / workdir 关联的 READY Loop 预览，创建或复用 agent-native run，并返回 run URL 与首个可执行 step capsule |
| `loopora agent codex next` / `loopora agent claude next` / `loopora agent opencode next` | 宿主 entry 使用的底层入口，领取当前 run 的下一个 step capsule；只分发上下文、输出契约和提交提示，不启动宿主 CLI |
| `loopora agent codex submit` / `loopora agent claude submit` / `loopora agent opencode submit` | 宿主 entry 使用的底层入口，把宿主原生 Agent / subagent 完成的 wrapper result 与 dispatch proof 提交回 Core，推进证据、handoff、裁决和 run 状态 |
| Web Tools Codex / Claude Code / OpenCode card | 调用同一 adapter service/helper 展示目标项目 status，并触发 install/uninstall |

稳定规则：

- 必须坚持 `/loopora-gen -> READY preview -> /loopora-loop`。缺少 ready Loop preview 时，`loopora agent <adapter> loop` 返回明确错误，提示先 gen；人类可读错误不把 `READY bundle` 当作默认主语。
- Tools 页安装 Coding Agent 入口时，目标目录必须表达为 Agent 将实际工作的项目目录；留空使用服务当前目录只是便利默认值，文案必须提醒用户只有服务已从目标项目启动时才适合留空，避免把入口装到 Loopora 服务目录或错误仓库。
- Codex / Claude Code / OpenCode adapter 只负责宿主入口和 binding，不复制 bundle validation、alignment import、run lifecycle、step context assembly、evidence ledger 或 Web serve 逻辑。
- Agent-first 默认执行平面是 `agent_native`：Loopora Core 冻结 run、维护 `awaiting_agent` 状态、分发 step capsule 并接收带 `loopora_host_dispatch` 的结构化 wrapper result；宿主 Agent 用自身 slash command、skill、subagent、task 或等价机制完成具体角色工作。
- Agent-first adapter 不得在 `/loopora-loop`、`next` 或 `submit` 内部再启动 `codex`、`claude`、`opencode` CLI。需要无人值守自动跑完整 run 时，应走明确的 headless run / executor 路径，而不是假装成宿主 Agent-first。
- `loopora agent <adapter> loop` 可以领取首个 step，后续由宿主 entry 循环调用 `submit -> next`；重复调用必须复用同一 READY preview / active run，不创建相互竞争的 run。
- `loopora agent <adapter> gen` 的人类可读输出应把主对象说成 Loop 预览和 preview URL；当它为 preview 或 run URL 自动启动或复用本地 Web 服务时，必须同时显示 Web 状态，避免用户拿到 localhost 链接却不知道服务是否已经可用；`READY`、`candidate` 和 bundle hash 只作为 JSON 字段或诊断事实保留，不能成为默认成功提示的主文案。
- Agent-first runtime 的同步输出必须保留冻结判断契约的可追溯入口；当 run artifacts 可用时，人类可读 `loop/next/submit` 输出应打印 `run_contract_path`、source plan provenance、判断摘要、Loopora fit、执行策略、判断取舍、本地治理责任与角色姿态，JSON 输出应返回同义的 `judgment_contract` 投影，并保留 `source_bundle` provenance、check mode、completion mode、workflow preset 与 coverage target trace 这类执行锚点；在终态完成时继续分开报告 `run_status` 与 `task_verdict`。宿主 Agent 不能只看 `succeeded` 就判断 Loop 已被证据证明。
- `loopora agent <adapter> submit` 只接受当前 capsule 对应的结构化输出和匹配的 host dispatch proof；缺失 step、step 不匹配、run 已终态、dispatch proof 缺失 / inline / agent 不匹配，或输出不满足角色契约时返回领域错误，不让宿主 entry 猜测内部状态。
- 未实现平台可以出现在类型、API 投影和 Web UI 中，但状态必须是未实现，不能生成假入口。
- Web status 只展示 `not_installed / installed / needs_update / error / not_implemented` 这类 adapter 投影，不把它们写成 Loop 或 run 状态。
- Web Tools 必须能显式选择目标项目目录来执行 adapter status / install / uninstall；没有输入时可以投影服务进程当前目录，但浏览器自动化必须能用临时真实项目证明文件边界。
- Agent adapter 项目文件 ownership 由 `10-agent-adapters.md` 定义；接口层不得覆盖用户 `AGENTS.md`、`CLAUDE.md`、`.codex/config.toml`、`opencode.json`、`.opencode/opencode.json*` 或其他宿主配置。Claude Code 的 `.claude/settings.json` 只允许通过 adapter service/helper 合并或删除 Loopora 自己的 SessionStart hook handler。

## 4. 跨入口一致性

以下能力必须跨入口保持同一语义：

| 能力 | 一致性要求 |
|------|------------|
| 创建 loop | 相同参数表达相同 loop definition；executor、completion mode、计数、重试次数和窗口类运行参数不能在 Web / CLI / API / bundle 预览边界绕过同一校验 |
| 导入 / 导出 / 派生 / 删除 bundle | 表达同一整包生命周期语义 |
| 预览 bundle | 只读校验与投影，不创建底层资产 |
| 选择 orchestration | 引用同一编排资产 |
| 编辑 role definition | 角色模版、判断姿态、执行默认值与 prompt 语义一致；写入、只读和收束等本次行动权限属于 workflow step |
| 配置 completion mode | 只接受 `gatekeeper` 与 `rounds`，且二者的收敛语义一致；未知模式必须失败关闭 |
| 启动、停止、删除 run | 生命周期语义一致 |
| 观察 run artifacts / evidence | artifact 列表用于追查细节，`evidence/ledger.jsonl` 是证明项与 GateKeeper verdict 的事实源 |
| 展示 run status / task verdict / judgment contract | run status 表达系统生命周期；task verdict 表达 Loop 达标、未达标、证据不足或残余风险；Web、API 与同步 CLI 输出都应能追到本次运行冻结的判断契约 |

允许交互形态不同，例如 Web 可以提供可视化 workflow 编辑器、对话式 alignment、主题和语言偏好；CLI 可以提供同步等待与后台执行开关。但这些差异不能改变底层语义。

Web 编排编辑器对 `parallel_group` 的稳定承诺：

- 内置并行 starter 应在资源库、编排工作台和创建 Loop 摘要里可被识别为并行检视示例。
- Step settings 必须能查看和编辑当前 step 的 `parallel_group`，并说明它只适用于相邻的 Inspector / Custom 检视 step。
- Web 预校验应暴露常见并行结构错误，例如非 Inspector / Custom step 进入并行组、并行组少于两个 step、同组 step 不连续；最终保存仍以 service 层 workflow 校验为准。
- Web 不提供 Builder 并行开关；多 Builder 只能通过线性阶段边界表达。

CLI 对高阶 workflow 的稳定承诺：

- 通过 `--workflow-preset` 选择少数内置治理形状。
- 通过 `--workflow-file` 承载完整 `workflow` contract，包括 `parallel_group` 与 `inputs`。
- 不为每个 workflow 字段提供一组顶层 flags，避免 CLI 变成难维护的流程编程界面。

## 5. Web 路由心智

| 路由 | 用户心智 | 稳定职责 |
|------|----------|----------|
| `/` | Loop 工作台 | 活动 Loop、已保存 Loop 的日常查看、启动运行、最近运行入口，以及进入专业编排工作台的清晰入口 |
| `/runs` | 兼容跳转 | 旧运行列表入口跳转到 `/#activity`；新的默认心智不提供独立运行列表 |
| `/loops/new/bundle` | 编排工作台 | 默认通过对话编排 Loop、READY 预览、创建并运行；共享侧栏保留导入方案文件与手动编排入口 |
| `/loops/new/manual` | 编排工作台的专家分支 | 在同一侧栏框架内手动选择 spec、workflow、executor，或导入已有 bundle YAML |
| `/bundles` | 资源库里的方案文件 | 查看、导出、删除和派生方案包；服务专家交换与导入导出 |
| `/roles` / `/orchestrations` | 资源库 | 编辑可复用角色与 workflow 资产 |
| `/tools` | 工具 | 管理运行辅助与本机资产诊断 |
| `/tutorial` | 使用教程 | 帮用户判断何时使用 Loopora，以及从哪条路径开始 |

旧路由可以保持兼容跳转，但新的默认心智不得再要求新手先理解内部对象，也不得把创建动作和已有 Loop 高频浏览混成同一个一级页面。

Loop 工作台为空时可以提供两个轻量 first-run 出口：安装 Coding Agent 入口，以及进入 Web 对话编排。它们只服务“还没有任何 Loop 时如何开始”的空态，不把工作台重新变成创建表单或专家资源入口。

## 5.1 Run 观察 API

run 详情页依赖两类稳定接口：

| 接口 | 稳定职责 |
|------|----------|
| `GET /api/runs/{run_id}/observation-snapshot` | 返回 run 详情首屏所需的有界观察投影 |
| `GET /api/runs/{run_id}/events` | 兼容既有调用方，按 `after_id` 顺序读取 run event stream |
| `GET /api/runs/{run_id}/stream` | 按 SSE wire shape 增量推送 run event stream |

`observation-snapshot` 只服务 run 观察投影，不成为新的事实源。响应保持：

- `run`
- `latest_event_id`
- `timeline_events`：最多 40 条格式化里程碑事件
- `console_events`：最多 160 条脱敏原始事件
- `progress_events`：最多 2000 条 progress 相关脱敏事件
- `key_takeaways`

稳定规则：

- run detail HTML 只内联 `runId` 与最小 `initialRun`，不得 seed 大量 event payload。
- snapshot 必须由 service/repository 只读边界构建，route 只做 HTTP 包装和 timeline 展示格式化；接口层不得再次拼装 key takeaways。
- snapshot 必须基于同一次只读 cutoff 构建：读取 run row、当前 `latest_event_id`、timeline / console / progress 投影必须共享同一个观察上界；返回数组里的每条事件都必须满足 `event.id <= latest_event_id`。
- `key_takeaways` 属于 snapshot 观察投影的一部分，必须来自持久化 takeaway projection，并带有不超过本次 cutoff 的真实 `source_event_id`。snapshot 不得现场读取 artifact 文件生成关键结论；没有可用 projection 时可退化为 run status 最小结论，`source_event_id` 设为本次 cutoff。
- 最小 takeaway projection 仍必须保持完整观察 shape：`run_status`、`task_verdict`、`task_verdict_path`、`judgment_contract`、`evidence_buckets`、`evidence_coverage`、`evidence_manifest`、`iterations` 和目录字段都存在；缺少证据或运行契约时使用空 task verdict artifact path、空 judgment contract、空覆盖 / 空 manifest 投影，而不是让调用方猜测字段是否存在。run detail 前端消费旧版 projection 时，空的 `task_verdict.buckets` 不得遮蔽已有 `evidence_buckets`，避免旧投影里的阻断项或残余风险在首屏消失。
- snapshot 读取到旧版持久化 takeaway projection 时，可以只做 shape 归一化和默认字段补齐；不得为补字段现场重读 artifacts 或改变原 projection 的 `source_event_id` 语义。
- 每轮 takeaway 卡片应展示 evidence progress 信号；当 required coverage 停滞或仍有缺口时，用户不需要打开 raw JSON 就能看到 covered / missing check count 和无覆盖增量。
- `GET /api/runs/{run_id}/key-takeaways` 仍表示“当前最新”结论，可以读取最新 artifacts 现算；它和 snapshot projection 的职责不同，不受 snapshot cutoff 约束。
- 页面先拉 snapshot，再用 `latest_event_id` 建立 SSE；cutoff 后追加的事件必须能通过 `/events` 或 `/stream?after_id=<latest_event_id>` 继续读取，重复事件按 event `id` 去重。
- run / alignment `/events` 和 `/stream` 的 `after_id` 必须是非负且处于当前持久化 event id 范围内的游标；`/events` 的 `limit` 必须处于受限正整数范围内，越界请求返回 4xx，不得把非法游标传给存储层形成异常或无界读取。SSE `Last-Event-ID` 只是恢复提示，非法或超过当前 `latest_event_id` 时必须忽略并保留请求游标。
- snapshot 拉取失败只降低观察面质量，不改变 run 生命周期事实。页面必须保留最小 run 信息，并继续从最后已知 `latest_event_id` 或 `0` 建立 SSE。
- run detail 页面通过稳定锚点 `data-testid="run-observation-status"` 暴露观察链路状态；`data-observation-state` 只表达观察质量，取值为 `loading / ready / degraded / stream-stale / stream-error / finished`，不得被 service 层当作 run status。
- run detail 首屏通过稳定锚点 `run-status-card`、`run-task-verdict-card`、`run-latest-event-card` 分开展示生命周期状态、Loop 裁决和最近里程碑；测试应依赖这些语义锚点，不依赖具体文案或布局。
- run detail 必须从结果页直接暴露当前 Loop 的导出入口，让用户在查看 Loop 裁决后可以把本次判断结构带走、复用或丢弃，而不需要先跳转到专家 bundle 列表。
- run detail 的接受动作只记录用户接受当前证据结论的事件，不改变 run status、task verdict、bundle lineage 或 Loop 定义；按钮与事件投影必须表达为接受证据结论，不能暗示接受任务完成或绕过证据不足。它是用户决策出口，不是新的自动演化状态。接受事件必须带上当时可用的 task verdict、coverage、manifest artifact path、证据桶计数、evidence source event id、source bundle provenance，以及完整 normalized `judgment_contract`（含 source bundle provenance、check mode、completion mode、workflow preset 与 coverage targets），让后续审计能知道用户接受的是哪份证据结论和哪套冻结判断契约；若证据摘要因 artifact 损坏不可读取，仍必须保留同一 payload shape，并显式标记 evidence unavailable，不能退化成只有事件 id 的不可审计记录。
- 默认 run detail 文案应把中间执行阶段表达为 Loop steps / middle steps；`workflow`、ledger、raw output 等专家词只作为追查或专家路径语言，不能取代首屏证据与裁决心智。
- run detail 的 timeline、console、progress 与最近事件摘要对事件 payload 中影响成功、降级和通过语义的布尔值必须按 literal JSON boolean 处理；只有 `true` 可以显示为完成 / success / degraded / passed，字符串或其它 truthy 值必须 fail closed。用于展示重试次数、耗时或事件顺序的字段必须是真正的非负 JSON integer，字符串、布尔值或小数不能提升成用户可见的计数或时长。
- run detail 前端渲染 timeline、console、progress 与 key takeaways 时，来自 run event、snapshot 或 projection 的动态文本必须在进入 `innerHTML` 拼接前转义；允许服务端已消毒的 markdown HTML 作为专用 HTML 投影，但不得把未转义的事件 payload 当作可信 HTML。
- SSE `stream_error` 和连接错误只影响观察链路状态。活动 run 可以有限退避重连；终态 run 不因 stream 失败重新连接。
- SSE `stream_error` 事件不能回显后端异常文本、路径、数据库错误或堆栈。run stream payload 固定为 `{"run_id": "...", "after_id": 123, "error": "stream_unavailable", "retryable": true}`；alignment stream payload 固定为 `{"session_id": "...", "after_id": 123, "error": "stream_unavailable", "retryable": true}`。
- snapshot 中的事件仍必须走 run event 写入边界的最终脱敏；接口层不得重新暴露 prompt、schema、token 或完整敏感命令内容。
- unknown run 返回 `404`，错误体仍为 `{"error": "..."}`。
- `/events` 与 `/stream` 的既有语义不因 snapshot 新增而改变。

## 5.2 Local Diagnostics Interfaces

local-first 诊断接口只服务本机维护和测试，不改变 Loop/run 主工作流：

| 接口 | 稳定职责 |
|------|----------|
| `GET /api/diagnostics/local-assets` | 只读扫描本地资产目录与 durable record 的明显不一致 |
| `loopora diagnose event-redaction [--fix]` | 审计历史 run / alignment events 和本地 JSONL 事件文件是否仍含旧敏感 payload；默认 dry-run |

`/api/diagnostics/local-assets` 返回本地资产不一致的只读数组：

- `orphan_alignment_dirs`
- `orphan_bundle_dirs`
- `orphan_run_dirs`
- `record_without_dir`

稳定规则：

- diagnostics API 不自动删除本地目录，不改变任何 durable record；错误体继续保持 `{"error": "..."}`。
- `orphan_run_dirs` 是兼容扩展，item 使用 `{run_id, workdir, path, source}`；`source` 只表达诊断来源，取值为 `registry` 或 `recent_workdir`。
- local asset diagnostics 必须同时消费当前 durable records、本地资产 registry 与最近 workdir 扫描结果；即使 alignment session、bundle record 或 run record 已删除，只要 registry 或 recent workdir 仍能定位未清理目录，仍应能发现 orphan 资产。
- durable record 或 registry active row 指向缺失目录时，必须进入 `record_without_dir`；run 目录缺失使用 `resource_type="run"`。
- Tools 页面可以显示只读健康摘要、计数和问题明细，并可提供定位目录、打开上级目录或复制路径等人工排查动作；不得提供删除按钮、自动修复按钮或把诊断结果变成主工作流阻塞条件。
- Tools 页面属于默认 Web 表面，诊断展示可以把 `orphan_alignment_dirs` 解释成对话编排残留目录、把 `orphan_bundle_dirs` 解释成方案文件残留目录；API key 与 durable record 字段仍保留 alignment / bundle 命名作为兼容内部契约。
- `diagnose event-redaction --fix` 只能使用当前 event redaction 规则重写可确定修复的 DB payload 和本地 JSONL；扫描来源包括 DB run / alignment events、registry 中未 cleaned 的 run / alignment dirs，以及最近 workdir 下的 legacy `.loopora/runs/*` timeline 和 alignment event 文件。无法解析或无法安全判断的条目进入报告，不得猜测修复。
- dry-run 不写 DB 或文件；`--fix` 后仍必须保留 command 摘要等可读观察信息。

## 6. 安全边界

| 边界 | 接口层责任 |
|------|------------|
| 本地与网络访问 | 本地默认安全优先；网络暴露必须显式开启 |
| 文件系统访问 | 所有路径必须受允许根范围约束 |
| 文件预览 | 按不可信内容处理，不能直接执行 |
| 输入规范化 | 坏 JSON、缺失字段、越界参数必须返回明确 4xx |
| workdir 操作 | 不得绕过 workspace safety guard 或 run lock |
| 本地化 | 文案可变；测试锚点和接口契约不能绑定某种展示语言 |

系统级本机动作接口的稳定规则：

- spec 校验、预览、编辑和初始化接口只服务 UTF-8 Loop 契约 Markdown 文件，不是通用本地文件浏览器或文本编辑器；它们必须拒绝非 Markdown 路径、非 UTF-8 内容、二进制内容和超过契约大小上限的输入，保存请求也必须在写盘前执行同一文本边界检查。
- spec 模板预览和初始化若接收 workflow payload，必须复用 workflow validator；无效 workflow 返回 `400 {"error": "..."}`，初始化不得创建部分文件。
- `/api/files` 是只读预览接口，不是下载接口；目录列表和文件内容必须有预览上限，超大文件只返回元数据和明确的预览省略状态，不可读文件或目录返回结构化预览错误而不是 500，完整内容只能通过显式下载入口获取。显式下载入口和 artifact 下载必须复用同一套根目录约束，符号链接或路径解析只要逃逸允许根就失败关闭；下载响应必须作为 attachment 返回，不能让不可信工作区文件按扩展名在应用同源下内联执行。run artifact catalog 的 `available` 也必须基于同一解析后根目录约束，不能把逃逸 run artifact 根的符号链接标为可用 artifact。
- `/api/system/pick-*` 与 `/api/system/reveal-path` 属于副作用接口，只能通过 `POST` 触发；旧 `GET` 不得打开原生对话框或 reveal 文件。
- 这些接口在执行本机动作前必须校验请求来源；存在 `Origin` 或 `Referer` 时必须与当前 Host 同源。
- 网络模式继续禁用原生文件对话与 reveal 动作，并要求访问 token；loopback 模式也不得接受跨站来源触发本机动作。
- 网络模式的 token gate 保护页面和 API；`token` query 参数只作为首次访问的认证引导，不得被内部重定向继续转发；打包的 `/static/` 与 `/logo/` 资产可以无 token 读取，以保证认证页本身能加载共享样式和品牌图形。这些资产不得包含用户项目数据、run 数据或本地路径事实。

API 错误状态码的稳定语义：

| 场景 | 状态码 | 响应体 |
|------|--------|--------|
| 坏 JSON（包括非 UTF-8 JSON body）、缺失字段、非法参数、domain input 不满足当前契约 | `400` | `{"error": "..."}` |
| 请求引用的稳定资源不存在，例如 unknown loop / run / bundle / alignment session / orchestration / role definition | `404` | `{"error": "..."}` |
| 请求与当前生命周期或所有权状态冲突，例如已有 active run 占用 workdir、active alignment session、已终态 run stop、bundle-owned asset 删除、spec 初始化目标文件已存在 | `409` | `{"error": "..."}` |
| API 层未预期异常，例如存储或服务内部异常冒泡 | `500` | `{"error": "internal server error"}` |

稳定规则：

- API 层必须把 FastAPI 请求校验错误也归一为 `400`，避免接口调用方同时处理框架默认 `422` 与 Loopora 自己的 domain input 错误。
- service 层应基于领域错误类型映射 `404 / 409 / 400`，不能通过错误文案前缀猜测资源是否不存在。
- 错误响应体保持 `{"error": "..."}`，新增错误分类不得要求调用方迁移响应 body shape；未预期异常的原始类型、文案和 traceback 只进入诊断日志，不进入 API 响应体。

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
- 角色定义 / 编排 / 创建 Loop 的责任边界变化
- 安全边界变化
- 运行状态与 Loop 裁决的展示边界变化

以下变化通常不需要更新本文档：

- 页面改版
- 帮助文案调整
- 局部字段扩展

## 9. 非目标

- 不把 Web 做成通用 IDE。
- 不让 CLI 承担复杂可视化职责。
- 不把 HTTP API 扩张成公网平台接口。
