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

## 如果真正困难的，不是把补丁写出来呢？

如果真正困难的，不是让 agent 再多跑一轮，而是判断这一轮之后，世界到底发生了什么变化呢？

如果一次 `Builder` 远远不够，你真正需要的是：

- `Inspector` 重看证据
- `GateKeeper` 守住“到底算不算过”
- `Guide` 在停滞时轻轻拨正方向

那么你需要的，往往不是“再来一次自动执行”，而是一套能让多轮行动围绕新证据收敛下来的工作方式。

**Loopora 就是为这种任务而生的本地优先循环编排平台。**

它不是为了让 agent 跑得更久，而是为了让 `Builder`、`Inspector`、`GateKeeper`、`Guide` 在同一个任务里各司其职，把那些一轮做不完、必须看新证据才能决定下一步的任务，稳稳地推向收敛。

<p align="center">
  <img src="./.github/assets/readme-decision-tree.zh.png" alt="Loopora 使用决策板" width="1120" />
</p>

## Loopora 在解决什么

很多 loop 系统之所以让人犹豫，是因为它们只是让 agent 在旧假设上继续往前跑。没有新反馈，loop 往往就会变成漂移、变成盲盒。

Loopora 只做另一件事：

- `Builder` 先把工作区往前推一步
- `Inspector` 从更新后的世界里拿回新证据
- `GateKeeper` 依据证据判断这轮到底有没有过线
- `Guide` 只在卡住或明显走偏时介入

也就是说，Loopora 的核心不是“循环”两个字，而是**循环之后，下一步真的会因为新证据而改变。**

## 什么任务值得交给 Loopora

适合：

- 根因还没钉住，得先让 `Inspector` 把失败形态摸清
- 第一轮修复大概率不够，修完之后还得再看第二个瓶颈
- 必须靠 benchmark 或 evaluation harness 才知道这轮到底有没有推进
- 任务会跨多轮推进，而你希望每轮证据、裁决和 handoff 都能留下来

不适合：

- 小文案
- 小按钮
- 一轮就能安全做完的明显功能切片

## 先记住 5 条核心流程

Loopora 默认收敛到 5 条核心流程，因为真正常见的 loop 任务，通常也就这 5 种不确定性。

- `Build First`
  当最先缺的是第一条真正可运行的实现路径。比如你在接手一个跨 UI / API / 存储的导入链路，目标已经很清楚，但还没有第一版能完整跑通。

- `Inspect First`
  当最先缺的是证据。比如月结账单流水里，部分大租户的发票归档会缺文件，但没人知道问题出在汇总、渲染、打包还是上传。

- `Triage First`
  当连问题定义都还模糊。比如一条接手工单只知道“系统偶尔会重复发邮件”，得先把现象收窄成一个真正可行动的问题。

- `Repair Loop`
  当你一开始就知道一轮修复不太够。比如大型租户的全文检索重建会拖爆发布窗口，而第一轮修复之后大概率还会冒出第二个系统瓶颈。

- `Benchmark Loop`
  当下一步不该靠直觉，而该靠最新 benchmark。比如你在做长期优化，要把评测从 61% 拉到 70%，而不是只把提示词改得更像 benchmark 答案。

教程页会先给你看决策板，流程卡片也可以直接弹出对应样例。你不需要先背规则，先看最接近的那个真实任务就行。

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

先用决策板判断“该不该用 Loopora、该选哪条流程”，再直接打开最接近的流程样例。样例本身已经把 `Builder`、`Inspector`、`GateKeeper`、`Guide` 为什么要这样排好讲清楚了。

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
