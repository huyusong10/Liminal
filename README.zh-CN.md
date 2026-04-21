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
  <img alt="Local first" src="https://img.shields.io/badge/local--first-循环编排平台-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-实验中-D66A36">
</p>

## 如果最稀缺的，不是模型能力，而是人类注意力呢？

强 Agent 往往能把补丁写出来。

真正的瓶颈，常常出现在下一步。

总得有人回来问：

- 这条路径现在到底够不够真，能不能当基线？
- 这一轮到底是不是修在了对的层？
- 是继续推、先停下，还是该换方向？

问一次，没什么。
如果每个关键阶段都要回来问一遍，人类注意力就会变成真正的流量瓶颈。

**Loopora 就是为这种任务而生的本地优先循环编排平台。**

它不是因为 agent 完全做不到，而是因为有些端到端任务，会把人类不断拉回来确认、裁决和纠偏。Loopora 把这些重复出现的确认点，收进 `Builder → Inspector → GateKeeper → Guide` 的流程里，让人类更少介入，但每次介入都建立在更完整的新证据上。

<p align="center">
  <img src="./.github/assets/readme-decision-tree.zh.png" alt="Loopora 使用决策板" width="1120" />
</p>

## Loopora 在解决什么

很多 loop 系统之所以让人犹豫，是因为它们只是让 agent 在旧假设上继续往前跑。没有新反馈，loop 就会慢慢变成漂移，变成盲盒。

Loopora 只做另一件事：

- `Builder` 先把工作区往前推一步
- `Inspector` 从更新后的世界里重新拿证据
- `GateKeeper` 依据证据判断这轮到底有没有过线
- `Guide` 只在卡住或明显走偏时介入

它想解决的，不是“让 agent 想得更久”，而是把那些原本要由人类反复回来做的检查、裁决和纠偏，变成流程本身的一部分。

## 同一个项目里的 5 种 loop

想象一个很具体的项目：一个知识库产品，正把旧的 keyword-only 搜索升级成新的 hybrid search。同一个项目里，会自然出现 5 类长程任务：

- `Build First`
  先把帮助中心内容域的第一条完整路径接起来，让 `GateKeeper` 能判断它到底够不够资格进入 shadow。

- `Inspect First`
  帮助中心已经进了 shadow，但一小组高价值查询开始退化。先让 `Inspector` 钉住问题第一次出在采集、索引、召回、重排还是权限过滤，再让 `Builder` 动手。

- `Triage First`
  rollout 扩到 API 文档和内部手册后，同时冒出结果陈旧、排序飘、筛选失效、权限错漏。这一轮不是“全修”，而是先收敛出一个最值得修的阻塞切片。

- `Repair Loop`
  全量索引重建把维护窗口拖爆，团队从一开始就知道一轮修不完。第一轮先打掉主瓶颈，再根据新结果决定第二轮怎么修。

- `Benchmark Loop`
  系统已经接近可发，但是否继续 rollout 还取决于 relevance benchmark。每一轮都先让 `GateKeeper` 看最新评测，再决定 `Builder` 下一步继续压 retrieval、reranking 还是 query rewrite。

这些都不是小需求，而是长程、端到端、要求明确的任务。强 Agent 的确能帮上大忙，但如果没有 Loopora，人类仍然会在每个关键阶段被反复拉回来确认和纠偏。

教程页会先给你看决策板，流程卡片也可以直接弹出对应样例。你不需要先背规则，先看最接近的那个真实任务就行。

## 什么时候别用

如果一位强 Agent 加上一轮人工 review 就够了，就别开 loop。

不适合的典型任务：

- 小文案
- 小按钮
- 一轮就能安全做完的明显功能切片

只有当任务长到会把人类一遍遍拉回来确认、裁决和改方向时，Loopora 才会真的省事。

## 最快上手

1. 安装

```bash
python3 -m pip install -e .
```

2. 启动本地 Web 控制台

```bash
loopora serve --host 127.0.0.1 --port 8742
```

然后打开 [http://127.0.0.1:8742](http://127.0.0.1:8742)。

3. 先看教程页和流程编排页

先用决策板判断“该不该用 Loopora、该选哪条流程”，再直接打开最接近的流程样例。样例本身已经把 `Builder`、`Inspector`、`GateKeeper`、`Guide` 为什么要这样排，以及它们分别替人类吸收了哪类确认工作，讲清楚了。

4. 改你的 spec，再创建 loop

Loopora 的 spec 很短，只围绕 4 段：

- `# Task`
- `# Done When`
- `# Guardrails`
- `# Role Notes`

最省力的方式不是从零写，而是从最接近的内置样例改起。

## Web UI 优先，CLI 仍然可用

Web UI 是推荐入口，因为它把这些事情放在了同一个地方：

- 选流程
- 看真实样例
- 改 spec
- 创建 loop
- 观察每轮产物、证据和 GateKeeper 裁决

如果你已经很清楚要跑哪条 loop，也可以直接走 CLI：

```bash
loopora run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

## 开发

运行测试：

```bash
python3 -m pytest -q
```
