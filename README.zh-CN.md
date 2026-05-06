**简体中文** | [English](./README.md)

<p align="center">
  <img src="./src/loopora/assets/logo/logo-with-text-horizontal.svg" alt="Loopora" width="720" />
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/web-FastAPI-009688?logo=fastapi&logoColor=white">
  </a>
  <img alt="Local first" src="https://img.shields.io/badge/local--first-AI%20Agent%20governance%20loops-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-实验中-D66A36">
</p>

第一次了解 Loopora，建议先读：[Human-Shaped Loop：Loopora 的判断力哲学](./docs/human-shaped-loop.zh-CN.md)。

Loopora 是面向长期 AI Agent 任务的本地任务平台，用来编排 **human-shaped governance loop**。

它解决的是这样一个时刻：只是“再问一次 Agent”已经不够了，因为缺的已经不是努力，而是判断。

## 为什么需要它？

如果一次 AI Agent 执行加一轮人工 review 就足够，那你不需要 Loopora。

但长期任务的瓶颈经常不是第一版生成，而是人类会不断被拉回来判断：

- 这一轮证明了正确的东西吗？
- 结果是真的完成，还是只是局部看起来合理？
- 哪些假进展必须被拒绝？
- 哪个角色应该构建、检查、修复、收窄范围，或者停止？
- 哪些证据应该保留下来，供 run 外部复盘？

当这些问题反复出现，瓶颈就不再是生成，而是反复把人类判断力应用到任务推进中。

**Loopora 把这些判断提前。它帮助用户外化“这次任务应该如何被判断”，把这份判断编译成可运行的 Loop，让 Agent 在 Loop 内自动迭代，并留下白盒证据和裁决结果。**

一句话：

> human-in-the-loop -> human-shaped loop

人类没有消失，而是从“每轮实时纠偏者”变成“循环设计者”和“证据审计者”。

## 它和 Agent 插件有什么不同？

大多数 Agent 插件是在一个 Agent 上下文内部增强行为：skill、命令、检查表、角色、协作模式。这很有用，很多任务也确实够用了。

Loopora 站在 Agent 外围那一层。模型学习通用能力，Loop 继承当前任务的判断方式。

| 在插件式 Agent 上下文里 | 在 Loopora 里 |
| --- | --- |
| prompt 里写“什么算好” | `spec` 冻结任务契约、假完成、证据和残余风险 |
| 某个角色提醒 Agent review | `roles` 分离构建、检查、裁决和纠偏责任 |
| checklist 依赖模型自觉执行 | `workflow` 决定何时判断、证据如何流动、什么条件能结束 run |
| 日志解释发生了什么 | `evidence` 成为 review 的事实源 |
| 反馈变成下一段 prompt | bundle 导入 / 导出让用户拥有的改动保持显式 |
| 简单循环延长任务时间 | Loop 约束误差如何跨轮传播 |

Loopora 不试图替代你的 AI Agent。它给 AI Agent 一个可运行、被人类判断塑形的 Loop，也给用户一个外部可观察的证据面。

## 核心概念

Loopora 面向用户的核心对象是 **Loop**。

Loop 不是更长的 prompt，而是“这次任务应该如何被判断”的可运行形状，包含三个运行输入面和一个观察输出面：

| 运行面 | 职责 |
| --- | --- |
| `spec` | 定义范围、成功面、假完成、guardrails、证据偏好和残余风险 |
| `roles` | 定义每个 AI Agent 角色在本任务中如何构建、检查、裁决或纠偏 |
| `workflow` | 定义顺序、handoff、证据路由、自动迭代、并行检视、controls 和停止条件 |
| `evidence` | 记录每次 run 改了什么、检查了什么、证明了什么、没证明什么、如何裁决 |

在内部，Loopora 可以把可运行 Loop 保存或交换为 YAML **bundle**。用户不需要一开始理解这个格式。Web UI 会让你描述任务、通过对话编排 Loop、预览治理结构，并且只有在候选 Loop 通过校验后才创建 run。

这在复杂判断里尤其重要。如果判断已经能稳定量化，就应该优先沉淀为 benchmark、contract test、schema、lint 或 proof harness。Loopora 更适合那些还不能可靠打成一个分数，但可以被结构化成成功面、假完成、证据偏好、角色责任和 GateKeeper 阻断条件的任务。

## 一个具体例子

假设你说：

> 做一个英语学习网站。

普通 AI Agent 很可能直接开始做页面：落地页、单词卡片、练习题、按钮和漂亮视觉。它可能看起来已经完成，但没有证明学习者真的能完成一轮学习。

Loopora 会先问判断问题：

- 第一版到底是可运行学习路径，还是产品草图？
- 什么是假完成？只是页面好看但没有真实学习闭环？
- 什么证据能证明用户可以选择目标、学习、练习并看到进度？
- 即使 UI 好看，GateKeeper 是否也应该拒绝浅层 polish？

这可能被编译成：

```text
Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper
```

- `Builder` 实现第一条端到端学习切片。
- `Contract Inspector` 检查任务承诺和 fake-done 风险。
- `Evidence Inspector` 独立证明学习路径是否真实、可重复。
- `GateKeeper` 只有在证据支持时才允许收束。

## 五分钟上手原则

Loopora 可以越来越强，但第一次使用必须保持简单：

> 描述任务，选择 workdir，确认 Loop，运行，看证据。

并行 Inspector、证据路由、workflow controls、触发规则和 provider 执行差异，只有在它们确实能控制长期任务误差时，才由 Loopora 编译进方案。它们不是新用户开始前必须手动配置的概念。

默认的对话编排入口不是 YAML 生成器，而是一段短 alignment：通过具体 tradeoff 帮用户把隐性判断力显影，例如什么算真实进展、什么是假完成、GateKeeper 应该相信什么证据，以及哪些 residual risk 可以接受。

## Web 流程

```mermaid
flowchart LR
    A["编排 Loop"] --> B["运行 Loop"]
    B --> C["自动迭代"]
    C --> D["收集证据"]
    D --> E["查看裁决"]
```

在本地 Web UI 中：

1. **Loop** 展示已有 Loop、最近运行状态和继续运行入口。
2. **编排** 打开对话优先的 Loop 编排工作台，并保留导入方案文件和手动编排入口。
3. Loopora 调用本机智能体命令行，只追问会改变 Loop 的问题。
4. READY Loop 会展示 Loop 契约、角色、流程图和源文件操作。
5. **创建并运行** 会物化 Loop 并启动运行。
6. **资源库** 管理方案文件、角色定义和流程编排，供专家复用。

手动编排仍然存在，但它是专家路径，适合你已经明确知道要改哪个 `spec`、`roles` 或 `workflow` 运行面。方案包仍可导入导出，但它是专家交换格式，不再是日常查看已有 Loop 的主入口。

导入 YAML，或从已有方案包 / 运行证据发起对话改进，也是编排 Loop 的场景。它们很有用，但不是主工作流；候选 Loop 通过校验后，仍然进入同一条运行、证据和裁决路径。

## 快速开始

在 Loopora 发布为 Python 包之前，先在仓库根目录安装 CLI：

```bash
uv tool install --editable .
```

如果 uv 提示工具 bin 目录不在 `PATH`，执行一次 `uv tool update-shell`，然后重启 shell。

启动本地 Web 控制台：

```bash
loopora serve --host 127.0.0.1 --port 8742
```

打开 [http://127.0.0.1:8742](http://127.0.0.1:8742)，选择顶栏 **编排**，选择工作目录，然后描述这次 Loop。

## 什么时候该用？

先反过来问：

> 一次 AI Agent 执行加一轮人工 review 够不够？

如果够，就别用 Loopora。

再问：

> 如果不用 Loopora，人类会不会在每个关键轮次之后都回来判断结果意味着什么？

再问得更锋利一点：

> 原本未来才会发生的人类判断，能不能在 Loop 开始前先塑形？

适合 Loopora 的任务通常是：

- 足够长，一轮无法定案
- 足够有状态，每轮都会改变证据
- 足够模糊，成功不只是“测试通过”
- 足够有风险，不能把假完成放过去
- 足够可复用，任务判断方式不应该只活在一次聊天里

如果再跑一轮也不会产生新证据，就不要开 loop。简单循环只是延长时间；Loopora 只有在证据和判断能让下一轮“错得更慢”时才有价值。没有证据的 loop 只会漂移。

<p align="center">
  <img src="./.github/assets/readme-decision-tree.zh.png" alt="Loopora 使用决策板" width="1120" />
</p>

## 外部 AI Agent 路径

Web UI 是推荐路径，因为它把 Loop 编排、校验、预览、运行和证据放在同一条引导流程里。

如果你更喜欢在 Web 之外做对齐，可以打开 **工具 -> 对齐技能安装**，把 repo-local `loopora-task-alignment` 技能安装到 Codex、Claude Code、OpenCode 或其他兼容智能体命令行。

这个 Skill 现在内置 Product Primer，所以 alignment Agent 不需要预先知道 Loopora 是什么。它产出的仍是同一种 YAML bundle，需要运行时从 expert 手动路径导入为 Loop 即可。

## CLI

CLI 仍然保留，适合自动化和 expert usage：

```bash
loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model <model> \
  --max-iters 8
```

未来 Loopora 发布为 Python 包后，推荐用 CLI tool 方式安装，例如 `uv tool install loopora` 或 `pipx install loopora`。在已激活虚拟环境里使用 `python -m pip install loopora` 也可以，但 tool install 更符合“一次安装，随处直接运行 `loopora`”的体验。

## 项目状态

Loopora 仍处于实验阶段，并坚持 local-first。

稳定承诺：

- Loopora 把 task-scoped human judgment 编译成显式、可检查的 Loop 运行面
- 长期任务编排应该存在于单次 AI Agent 对话之外
- Loop 保持可检查、文件化
- bundle 导入 / 导出保持显式、本地
- run 必须产生证据，而不只是日志
- bundle 改动应通过导入 / 导出显式发生，而不是隐藏的 prompt 漂移

## 开发

运行本地检查：

```bash
uv sync
uv run ruff check .
uv build --out-dir tmp/package-check
uv run pytest -q
```
