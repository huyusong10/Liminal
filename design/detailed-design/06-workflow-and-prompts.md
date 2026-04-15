# Workflow And Prompts

## 1. Purpose

本文档定义平台化 v1 的两类核心资产：

- `workflow_json`
- prompt Markdown 文件

目标是把原本硬编码在 orchestration service 中的角色顺序与 prompt 文案，升级为可保存、可快照、可跨入口编辑的稳定配置。

## 2. Workflow Model

`workflow_json` 是 loop definition 的 canonical workflow 结构。

结构固定为两层：

- `roles[]`
- `steps[]`

在平台化 v1 中，`workflow_json` 由独立的 `orchestration` 持有；loop 通过 `orchestration_id` 引用它，再在 run 开始时冻结到 run 目录。

### 2.1 roles

每个 role 至少包含：

- `id`
- `name`
- `archetype`
- `prompt_ref`
- 可选 `model`

### 2.2 steps

每个 step 至少包含：

- `id`
- `role_id`
- `enabled`
- 可选 `on_pass`

`on_pass` 仅对 `gatekeeper` archetype 生效，允许：

- `continue`
- `finish_run`

## 3. Archetypes

v1 固定支持 4 个 archetype：

- `builder`
- `inspector`
- `gatekeeper`
- `guide`

它们分别映射到工坊叙事：

- `Builder`：改动工作区并推进实现
- `Inspector`：取证、运行测试、收集 benchmark 结果
- `GateKeeper`：根据证据决定是否放行
- `Guide`：停滞时给出方向调整

兼容层仍接受旧名字：

- `generator -> builder`
- `tester -> inspector`
- `verifier -> gatekeeper`
- `challenger -> guide`

## 4. Presets

内置 preset：

- `build_first`
- `inspect_first`
- `benchmark_loop`

其中：

- `build_first` 对应 `Builder -> Inspector -> GateKeeper -> Guide`
- `inspect_first` 对应 `Inspector -> Builder -> GateKeeper -> Guide`
- `benchmark_loop` 对应 `GateKeeper(benchmark prompt) -> Builder`

`Guide` step 在运行时只在停滞或回退信号出现时真正执行；它不是稳定的每轮主路径角色。

这些 slug 是存储和接口层的稳定标识，不应该直接作为主要 UI 文案暴露。  
Web 应使用更接近自然语言的标题和说明，例如：

- `build_first` -> `先构建，再验收 / Build First`
- `inspect_first` -> `先巡检，再构建 / Inspect First`
- `benchmark_loop` -> `基准先行 / Benchmark Loop`

## 5. Validation Rules

workflow 保存前必须满足：

- 至少 1 个 role
- 至少 1 个 step
- step 引用的 `role_id` 必须存在
- 至少 1 个启用的 `gatekeeper` step 且 `on_pass=finish_run`

但面向用户的校验提示不应直接暴露内部字段名；  
例如应表达为“至少要有一个可在通过时结束流程的 GateKeeper 步骤”，而不是原样输出 `on_pass=finish_run`。

系统还会给出非阻断 warning，例如：

- `GateKeeper` 出现在后续 `Builder` 之前
- `GateKeeper` 在 `Builder` 之后立刻出现，但中间没有新的 `Inspector` 证据

## 6. Prompt Assets

prompt 文件统一为 Markdown，必须带 YAML front matter。

最小格式：

```md
---
version: 1
archetype: builder
---

Prompt body...
```

要求：

- `version` 必须为 `1`
- `archetype` 必须与 role 的 archetype 一致
- 正文不能为空

## 7. Runtime Assembly

运行时真正发送给底层 agent 的 prompt 由以下部分拼装：

1. 不可覆盖的系统安全前缀
2. 用户 prompt 正文
3. spec / checks / constraints
4. 同轮与上一轮的 workflow evidence
5. archetype 对应的输出契约说明

这意味着 prompt 可以被自定义，但系统安全边界和结构化输出契约不会被完全绕开。

## 8. Runtime Snapshot

每次 run 开始时，系统会冻结以下资产到 run 目录：

- `workflow.json`
- `prompts/*.md`
- `steps/iter_xxx/<step_id>/prompt.md`
- `steps/iter_xxx/<step_id>/output.raw.json`
- `steps/iter_xxx/<step_id>/output.normalized.json`

兼容旧页面与旧测试时，系统仍保留 legacy alias 文件，例如：

- `generator_output.json`
- `tester_output.json`
- `verifier_verdict.json`
- `challenger_seed.json`

## 9. Interface Parity

workflow / prompt 资产必须跨入口同构：

- Web：可视化编辑 preset、roles、steps、prompt
- CLI：通过 `--workflow-preset` 或 `--workflow-file`
- API：通过 `workflow` 与 `prompt_files`

同时，系统必须提供独立的一层 orchestration 管理入口，而不是把 workflow 编辑塞进 loop 创建表单中。

在 Web 中，orchestration 列表页的主交互应该是“进入编辑器”，而不是“直接去创建 loop”。  
loop 创建页只负责从已有 orchestration 中选择一套方案。

内置 orchestration 也必须能进入同一个编辑器，但保存语义是“另存为新的自定义 orchestration”，而不是就地修改内置方案。

不允许长期出现：

- 只有 Web 能改 workflow
- 只有 CLI 能提交 prompt 文件
- 只有 API 能表达 custom archetype instance

## 10. Non-Goals

- 不支持 DAG
- 不支持并发 step
- 不支持用户自定义输出 schema
- 不支持跳过 archetype 校验直接提交任意 prompt
