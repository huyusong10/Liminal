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
  <img alt="Local first" src="https://img.shields.io/badge/local--first-AI%20Agent%20loops-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-实验中-D66A36">
</p>

Loopora 把一个模糊任务变成可运行、可复盘的本地 AI Agent 证据循环。

它帮助你决定：什么才算真实进展，下一步该由哪个 AI Agent 角色处理，什么证据足够，以及什么时候应该停止。

## AI Agent 已经能做，为什么还要用 Loopora？

这是 Loopora 必须先回答的问题。

如果任务很小、很明确、一轮就能 review 完，那大概率不该用 Loopora。让 AI Agent 做一次，人类 review 一次，然后结束。

但如果难点不是第一版答案呢？

如果真正麻烦的是，总有人要反复回来问：

- 这次改动证明了正确的东西吗？
- 结果是真的完成了，还是只是局部看起来合理？
- 下一轮应该继续写、先检查、收窄切口、再修一轮，还是停止？
- 这个残余风险在这次任务里能接受，还是必须卡住？

当这些问题在每个关键阶段反复出现，人类注意力就会变成瓶颈。

**Loopora 就是为这个时刻存在的：把任务级判断变成可运行的本地循环。**

## 快速开始

在仓库根目录安装：

```bash
uv sync
```

启动本地 Web 控制台：

```bash
uv run loopora serve --host 127.0.0.1 --port 8742
```

打开 [http://127.0.0.1:8742](http://127.0.0.1:8742)，点击 **新建任务**，选择 workdir，然后描述你想让 Loopora 做什么。

推荐使用 Web 路径：

```text
描述任务 -> 对话对齐 -> READY 循环方案 -> 预览 -> 创建并运行 -> 根据证据修订
```

## 一个具体例子

假设你输入：

> 做一个英语学习网站。

普通 AI Agent 路径可能会直接开始做页面：落地页、单词卡片、几个按钮，也许 UI 看起来还不错。但它可能在没有证明“学习者真的能完成一轮学习”的情况下，就显得已经完成。

Loopora 会先换一种方式问：这次任务真正需要什么判断？

- 第一版是可运行的学习路径，还是产品草图？
- 什么是假完成？只是页面漂亮但没有真实学习闭环？
- 什么证据能证明用户可以选择目标、学习单词、完成练习并看到进度？
- 即使页面好看，最终裁决是否也应该拒绝浅层 UI polish？

对齐之后，Loopora 会生成一份 **循环方案**。运行前你可以预览：

- `spec`：任务契约、成功面、假完成、证据偏好和 guardrails。
- `roles`：为当前任务塑形的 AI Agent 角色，例如 `Builder`、`Inspector`、`GateKeeper`。
- `workflow`：判断发生的顺序，例如 `Builder -> Inspector -> GateKeeper`。

然后 Loopora 才会创建并运行循环。`Builder` 负责实现，`Inspector` 检查真实学习路径，`GateKeeper` 裁决证据是否足够完成。

## Loopora 会生成什么？

Loopora 首先生成一份人能读懂的 **循环方案**。

在内部，这份方案会保存成一个 YAML **bundle**：它是单文件、可导入的产物，包含任务契约、AI Agent 角色姿态、workflow 和运行参数。

你不需要一开始手写 bundle。Web UI 会通过对话生成它、校验它，并且只有当文件通过 Loopora 的 bundle 契约后才显示 READY。

bundle 重要，是因为它同时是：

- 可读的：你能检查这次为什么要这样协作
- 可运行的：Loopora 能把它物化成本地资产并启动 run
- 可修订的：后续反馈可以生成下一版，而不是随机手改字段

## Web 流程如何工作？

```mermaid
flowchart LR
    A["描述任务"] --> B["对话对齐"]
    B --> C["READY 循环方案"]
    C --> D["预览 spec / roles / workflow"]
    D --> E["创建并运行"]
    E --> F["run 证据"]
    F --> G["修订方案"]
```

在 Web UI 中：

1. **工作台** 展示当前任务和运行状态。
2. **新建任务** 打开对话式 alignment 页面。
3. Loopora 调用本机 AI AI Agent CLI，提出澄清问题，并在多轮对话中继承 session。
4. 方案 READY 后，页面会展示任务契约、角色卡片、workflow 图和源文件操作。
5. **创建并运行** 会通过正常 bundle 生命周期导入方案并启动 loop。
6. **方案库** 保存可复用循环方案和 bundle revision。

手动创建仍然存在，但它是 expert path，适合你已经明确知道要改哪个 `spec`、`roles` 或 `workflow` 运行面。

## 为什么不只写一段更好的 prompt？

因为判断不是一段 prompt。

如果只放进 `spec`，角色仍然是泛化角色。  
如果只放进角色 prompt，通过标准会漂移。  
如果只放进 workflow，系统知道顺序，却不知道如何判断。

Loopora 把任务姿态拆到三种运行面：

| 运行面 | 承载内容 |
|--------|----------|
| `spec` | 成功标准、证据、假完成、guardrails、残余风险 |
| `roles` | 每个 AI Agent 角色在这次任务中如何构建、检查、裁决或纠偏 |
| `workflow` | 每种判断什么时候发生，以及 run 如何结束 |

loop 再用新证据检验这些运行面，而不是相信自我报告。

## 什么时候该用 Loopora？

先反过来问：

> 一次 AI Agent 执行加一轮人工 review 够不够？

如果够，就别用 Loopora。

再正着问：

> 如果不用 Loopora，人类会不会在每轮之后都回来判断结果意味着什么？

如果会，Loopora 可能适合。

适合的任务通常是：

- 足够长，一轮无法定案
- 足够有状态，每轮都会改变证据
- 足够不确定，需要把 build、inspect、gate、redirect 拆开
- 足够重要，不能把“看起来完成”当成“完成”

如果再跑一轮也不会产生新证据，就不要开 loop。没有新证据的 loop 只会漂移。

<p align="center">
  <img src="./.github/assets/readme-decision-tree.zh.png" alt="Loopora 使用决策板" width="1120" />
</p>

## 常见 workflow 形状

别先背 preset。先问：人类原本最先要回来判断什么？

| 形状 | 适合场景 |
|------|----------|
| `Build First` | 需要第一条端到端路径，才谈得上判断 |
| `Inspect First` | 需要先证明失败层，再写更多代码 |
| `Triage First` | 多个症状混在一起，先要收窄成一个修复切片 |
| `Repair Loop` | 已经知道一轮修复不够 |
| `Benchmark Loop` | 下一步应该由最新评测结果决定 |

这些形状都在回答同一个问题：

> 哪种判断应该先被 loop 暴露出来，避免人类再回来补做？

## 外部 AI Agent 路径

Web UI 是默认入口，因为它把对齐、bundle 校验、预览、导入、run 证据和修订放在同一个地方。

如果你更喜欢在 Web 之外做对齐，可以打开 **资源与设置 -> 工具与 Skill**，把 repo-local `loopora-task-alignment` Skill 安装到 Codex、Claude Code 或 OpenCode。

这个路径产出的仍是同一种 YAML bundle。需要运行时，从 **资源与设置 -> 手动创建** 导入即可。

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

Loopora 仍处于实验阶段，并坚持 local-first。Web 流程、bundle alignment 质量和长期真实用例覆盖都会持续迭代。

核心承诺：

- bundle 导入 / 导出保持文件化、可检查
- Web alignment 不绕过 bundle 生命周期
- run evidence 保存在 Loopora 管理的本地 artifacts 中
- `spec / roles / workflow` 的 expert routes 继续保留

## 开发

运行测试：

```bash
uv run pytest -q
```
