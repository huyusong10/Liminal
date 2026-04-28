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

Loopora 是面向长期 AI Agent 任务的本地任务治理系统。

它把原本脆弱地藏在 Agent 对话上下文里的东西，也就是任务契约、用户判断、证据偏好、角色边界和停止规则，变成一个外部的、持久的、可检查的、可运行的、可修订的控制系统。

## AI Agent 已经能做，为什么还要用 Loopora？

这是 Loopora 必须先回答的问题。

如果任务很小、很明确、一轮就能 review 完，那大概率不该用 Loopora。直接让 AI Agent 做一次，人类 review 一次，然后结束。

但如果难点不是第一版答案呢？

如果真正麻烦的是，你总要反复回来判断：

- 这一轮证明了正确的东西吗？
- 结果是真的完成，还是只是局部看起来合理？
- 下一轮应该继续写、先检查、再修一轮、收窄切口，还是停止？
- 哪些证据足以让这个结果可信？
- 这次 run 暴露出来的问题，应该怎样改变下一版执行系统？

当这些问题反复出现，瓶颈就不再是生成，而是治理。

**Loopora 的存在理由，就是把任务治理从 Agent 的上下文里拿出来，变成一个持久的误差控制 harness。**

## 为什么不只是用一个更好的 Agent 插件？

大多数 Agent 插件是在对话内部增强 Agent：加入 skill、命令、角色、检查表，或者模拟优秀协作模式。这很有用，很多任务也确实够用了。

Loopora 站在另一层。

它不只是告诉 Agent 要更自律，而是把 Agent 外围的控制系统外部化：

| 只在 Agent 上下文里 | 在 Loopora 里 |
| --- | --- |
| prompt 里写“什么算好” | 任务契约冻结成功面、假完成、证据和残余风险 |
| 某个角色提醒 Agent review | 多个角色以明确 handoff 承担构建、检查、裁决和纠偏 |
| checklist 依赖模型自觉执行 | workflow gate 决定何时判断、何时允许结束 |
| 日志事后解释发生了什么 | 证据产物成为 review 和 revision 的事实源 |
| 反馈变成下一段 prompt | 反馈修订 harness 本身 |

其他系统可以让 Agent 更有纪律。Loopora 要做的是让任务的控制结构不只依赖 Agent 自律。

## Loopora 真正管理什么？

Loopora 的核心单元是 **循环方案**。

循环方案不是更长的 prompt，而是一份任务治理契约，包含五个运行面：

| 运行面 | 保护什么 |
| --- | --- |
| `spec` | 任务范围、成功面、假完成、guardrails、证据偏好 |
| `roles` | 每个 AI Agent 角色在本任务中如何构建、检查、裁决或纠偏 |
| `workflow` | 这些判断何时发生，什么条件能结束 run |
| `evidence` | 每次 run 实际改了什么、检查了什么、证明了什么、没证明什么 |
| `revision` | 反馈如何改变下一版 harness |

在内部，Loopora 会把可运行方案保存成 YAML **bundle**。用户不需要一开始理解这个格式。Web UI 会让你描述任务、通过对话对齐方案、预览治理结构，并且只有在方案通过校验后才创建 run。

## 五分钟上手原则

Loopora 可以越来越强，但第一次使用必须保持简单：

> 描述任务，选择 workdir，确认循环方案，运行，看证据，修订。

并行检视、证据路由、workflow controls、触发规则这些高级能力，只有在它们确实能控制长期任务误差时，才由 Loopora 编译进方案。它们不是新用户开始前必须手动配置的概念。

## 一个具体例子

假设你说：

> 做一个英语学习网站。

普通 AI Agent 路径可能会直接开始做页面：落地页、单词卡片、几个按钮，也许 UI 看起来还不错。但它可能在没有证明“学习者真的能完成一轮学习”的情况下，就显得已经完成。

Loopora 会先在治理层慢下来：

- 第一版到底是可运行的学习路径，还是产品草图？
- 什么是假完成？只是页面漂亮但没有真实学习闭环？
- 什么证据能证明用户可以选择目标、学习、练习并看到进度？
- 即使 UI 好看，GateKeeper 是否也应该拒绝浅层 polish？

最后生成的循环方案可能是：

```text
Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper
```

`Builder` 实现第一条端到端学习切片。
`Contract Inspector` 检查它是否符合学习任务承诺和 fake-done 风险。
`Evidence Inspector` 独立证明学习路径是否真实、可重复。
`GateKeeper` 汇总两条证据分支，裁决 run 能否结束，还是必须继续循环。

如果结果仍然不对，下一步不应该是随机改 prompt。下一步应该是根据 run 证据修订方案。

## Web 流程如何工作？

```mermaid
flowchart LR
    A["描述任务"] --> B["对齐循环方案"]
    B --> C["预览治理结构"]
    C --> D["创建并运行"]
    D --> E["收集证据"]
    E --> F["修订 harness"]
```

在本地 Web UI 中：

1. **工作台** 展示当前任务和运行状态。
2. **新建任务** 打开对话式循环方案页面。
3. Loopora 调用本机 AI Agent CLI，并提出形成任务级 harness 所需的问题。
4. READY 方案会展示任务契约、角色、workflow 图和源文件操作。
5. **创建并运行** 会物化方案并启动 loop。
6. **方案库** 保存可复用的治理模式和它们对应的 bundle 文件。

手动创建仍然存在，但它是 expert path，适合你已经明确知道要改哪个 `spec`、`roles` 或 `workflow` 运行面。

## 快速开始

在仓库根目录安装：

```bash
uv sync
```

启动本地 Web 控制台：

```bash
uv run loopora serve --host 127.0.0.1 --port 8742
```

打开 [http://127.0.0.1:8742](http://127.0.0.1:8742)，选择 **新建任务**，选择 workdir，然后描述这次长期任务。

## 什么时候该用 Loopora？

先反过来问：

> 一次 AI Agent 执行加一轮人工 review 够不够？

如果够，就别用 Loopora。

再正着问：

> 如果不用 Loopora，人类会不会在每个关键轮次之后都回来判断结果意味着什么？

如果会，Loopora 可能适合。

适合的任务通常是：

- 足够长，一轮无法定案
- 足够有状态，每轮都会改变证据
- 足够模糊，成功不只是“测试通过”
- 足够有风险，不能把假完成放过去
- 足够可复用，任务判断方式不应该只活在一次聊天里

如果再跑一轮也不会产生新证据，就不要开 loop。没有新证据的 loop 只会漂移。

<p align="center">
  <img src="./.github/assets/readme-decision-tree.zh.png" alt="Loopora 使用决策板" width="1120" />
</p>

## 外部 AI Agent 路径

Web UI 是推荐路径，因为它把对齐、校验、预览、运行、证据和修订放在同一条引导流程里。

如果你更喜欢在 Web 之外做对齐，可以打开 **资源与设置 -> 工具与 Skill**，把 repo-local `loopora-task-alignment` Skill 安装到 Codex、Claude Code、OpenCode 或其他兼容 AI Agent CLI。

这个路径产出的仍是同一种 YAML bundle。需要运行时，从 expert 手动创建路径导入即可。

## CLI

CLI 仍然保留，适合自动化和 expert usage：

```bash
uv run loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

## 项目状态

Loopora 仍处于实验阶段，并坚持 local-first。

稳定承诺：

- 任务治理应该存在于单次 Agent 对话之外
- 循环方案保持可检查、文件化
- bundle 导入 / 导出保持显式、本地
- run 必须产生证据，而不只是日志
- 后续 revision 应来自证据和反馈，而不是隐藏的 prompt 漂移

## 开发

运行测试：

```bash
uv run pytest -q
```
