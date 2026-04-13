**简体中文** | [English](./README.md)

<p align="center">
  <img src="./src/liminal/assets/logo/logo-with-text-horizontal.svg" alt="Liminal" width="560" />
</p>

<p align="center">
  <a href="https://www.python.org/">
    <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  </a>
  <a href="https://fastapi.tiangolo.com/">
    <img alt="FastAPI" src="https://img.shields.io/badge/web-FastAPI-009688?logo=fastapi&logoColor=white">
  </a>
  <img alt="Local first" src="https://img.shields.io/badge/local--first-本地优先-0D7C66">
  <img alt="Status" src="https://img.shields.io/badge/status-实验中-D66A36">
</p>

<p align="center">
  Liminal 是一个面向 agentic 构建循环的本地优先编排工具。
  你给它一个 Markdown 版 <code>spec</code> 和一个工作目录，它会运行
  <strong>Generator → Tester → Verifier → Challenger</strong>
  的循环，并提供实时 Web 控制台。
</p>

![Liminal 概览](./.github/assets/readme-overview.svg)

## 为什么是 Liminal

- 让目标保持稳定，同时让每次 run 围绕具体 checks 持续迭代。
- 同时支持显式 checks 和探索模式下的自动生成 checks。
- 把运行产物写进 `.liminal/`，方便回放、排查和比较。
- 用本地 Web 控制台统一查看进度、控制台输出、时间线和关键产物。
- 同一套 loop 定义可以切换由 Codex、Claude Code 或 OpenCode 执行，并自动适配各自的模型/推理选项。

## 它是怎么工作的

![Liminal 流程](./.github/assets/readme-flow.svg)

每次 run 都会先把 Markdown spec 编译成一份冻结快照，然后修改工作区、收集证据、做通过裁决；只有在停滞或退化时才会触发 Challenger。

## 功能特性

- CLI 支持 `run`、`serve`、`loops list`、`loops status`、`loops stop`、`loops rerun`、`spec init`
- 本地 FastAPI 控制台支持创建循环、监控运行、查看关键产物、安装 skill
- 每次 run 都会产出结构化文件，例如 `compiled_spec.json`、`tester_output.json`、`verifier_verdict.json`、`events.jsonl`、`summary.md`
- 支持 fake executor，方便本地 smoke test 和演示
- 内置 `liminal-spec` skill，帮助你生成符合要求的 `spec.md`

## 安装

```bash
python3 -m pip install -e .
```

如果要走真实执行链路，请确保你要使用的 CLI 已经在环境里可用：

- `codex`
- `claude`
- `opencode`

## 快速开始

1. 先创建一个 spec 模板：

```bash
liminal spec init ./demo-spec.md
```

2. 把它改成具体需求：

```md
# Goal

做一个有用的英语学习网站首页。

# Checks

### 主路径清晰
- When: 新用户打开页面并尝试开始学习
- Expect: 主行动路径清楚，第一步容易开始
- Fail if: 页面意图模糊，用户不知道下一步做什么

# Constraints

- 先做前端原型
```

3. 启动一个循环：

```bash
liminal run \
  --spec ./demo-spec.md \
  --workdir /absolute/path/to/project \
  --executor codex \
  --model gpt-5.4 \
  --max-iters 8
```

如果你想换工具，可以用 `--executor claude` 或 `--executor opencode`。其中 Claude Code 的 effort 是 `low/medium/high/max`，OpenCode 则使用 provider-specific variant。

4. 启动本地 Web 控制台：

```bash
liminal serve --host 127.0.0.1 --port 8742
```

然后打开 [http://127.0.0.1:8742](http://127.0.0.1:8742)。

## Spec 模型

Liminal 使用 Markdown spec，顶层结构如下：

- `# Goal` 必填
- `# Checks` 选填
- `# Constraints` 选填

如果省略 `# Checks`，Liminal 会在 run 开始时自动生成一组冻结 checks。  
如果显式提供 checks，则每条 check 应该使用 `###` 标题，并包含 `When`、`Expect`、`Fail if`。

## Web 控制台

本地控制台包括：

- 循环列表页：查看状态、模型、最近运行和常用操作
- 创建循环页：校验 spec，并提供辅助工具
- 运行详情页：实时进度、阶段说明、控制台流、时间线和关键产物
- 工具页：安装内置的 `liminal-spec` skill

## 存储结构

全局状态位于 `~/.liminal/`：

- `app.db`
- `settings.json`
- `logs/service.log`
- `recent_workdirs.json`

项目内状态位于 `<workdir>/.liminal/`：

- `loops/<loop_id>/spec.md`
- `loops/<loop_id>/compiled_spec.json`
- `runs/<run_id>/events.jsonl`
- `runs/<run_id>/tester_output.json`
- `runs/<run_id>/verifier_verdict.json`
- `runs/<run_id>/iteration_log.jsonl`
- `runs/<run_id>/stagnation.json`
- `runs/<run_id>/summary.md`

## Fake Executor

如果你只是想做 smoke test 或演示，可以切换到 fake executor：

```bash
LIMINAL_FAKE_EXECUTOR=success liminal run --spec ./demo-spec.md --workdir /tmp/project
```

支持的场景：

- `success`
- `plateau`
- `role_failure`

也可以人为加一点延迟：

```bash
LIMINAL_FAKE_EXECUTOR=success LIMINAL_FAKE_DELAY=0.5 liminal serve
```

## 项目结构

- `src/liminal/`：正式产品代码、模板、静态资源、内置 skills、logo 资产
- `tests/`：解析、运行、恢复、Web 和浏览器测试
- `pyproject.toml`：打包配置、CLI 入口和测试配置

## 开发

运行测试：

```bash
python3 -m pytest -q
```
