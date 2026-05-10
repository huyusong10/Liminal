本用例由 Agent 或发布负责人在真实环境中主动执行

# 场景：Coding Agent 中通过 Loopora Agent entry 生成并启动 Loop

**目标**：确认用户以 Codex、Claude Code 或 OpenCode 为主入口工作时，Loopora 只承担 Loop 治理事实源：先生成 READY 候选 Loop，再启动或复用 Loopora-managed run。

**前置**：

- 目标项目目录可由目标 Coding Agent 和 Loopora 访问。
- `loopora` CLI 在目标 Coding Agent 运行环境的 `PATH` 中可用。
- 已在项目中安装目标 Agent adapter，或准备通过 Web / CLI 安装。

**步骤**：

1. 在项目目录运行 Codex、Claude Code 或 OpenCode，并确认项目级 Loopora entry 可被发现。
2. 触发 `/loopora-gen`，让目标 Coding Agent 基于当前任务、约束、风险、证据偏好和用户判断生成候选 bundle。
3. 确认 `/loopora-gen` 只返回候选 Loop / READY 预览 URL，不启动 run。
4. 打开返回的 Web URL，确认 READY 状态来自 Loopora Core 校验后的 bundle，而不是 Codex 的自然语言自报。
5. 触发 `/loopora-loop`，确认它复用当前 session / workdir 关联的 READY bundle，启动或复用 Loopora-managed run，并返回 run URL。
6. 在 Web run 详情页观察 run 状态、证据与裁决入口，确认 Coding Agent 仍是执行主体，Loopora 是状态、证据和裁决事实源。
7. 新开一个没有 READY binding 的 Agent session 或临时项目目录，直接触发 `/loopora-loop`，确认系统提示先运行 `/loopora-gen`。
8. 在 Web Tools 页选择同一目标项目，执行安装、状态刷新、卸载，再确认用户自己的 `AGENTS.md`、`CLAUDE.md`、`.codex/config.toml`、`.claude/settings.json` 或其他配置没有被覆盖。

**预期**：

- `/loopora-gen -> READY preview -> /loopora-loop` 顺序不可被绕过。
- 安装与卸载只影响 Loopora-managed Agent entry 文件和 manifest。
- Web 与 CLI 的状态、ownership 和错误语义一致。
