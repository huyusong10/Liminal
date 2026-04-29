本用例由 Agent 自行进行模拟

# 场景：长期任务治理闭环从新建到证据结论

**目标**：确认 Loopora 的主路径不是生成一次 YAML 或跑一次 Agent，而是把任务输入、循环方案、运行证据和 GateKeeper 裁决串成同一个可追踪的任务执行编排闭环。

**前置**：

- 目标 workdir 是服务端可访问的真实项目目录。
- 至少有一个可用执行器配置；若真实 CLI 不可用，可用 fake executor 验证结构化契约。
- 本场景不依赖具体展示语言或静态文案。

**步骤**：

1. 从默认“新建任务”入口进入对话页，描述一个需要多轮推进和证据判断的任务，并选择 workdir。
2. 让 alignment session 先形成 working agreement；在未确认前，确认系统不会把模型自报的 bundle 当成 READY。
3. 明确确认方案后进入 READY，检查预览能展示任务契约、角色姿态、workflow 形状、证据路径和 GateKeeper 收束方式。
4. 创建循环并启动 run，确认运行开始时冻结 spec、workflow、role prompts 和 workspace baseline。
5. 等待 run 产生 step handoff 与 evidence ledger item，确认每条面向用户的角色结论能指回 evidence refs 或对应 artifact。
6. 等待 GateKeeper verdict，确认 `gatekeeper` completion mode 只有在 verdict 通过运行时证据门禁时才结束；缺少 evidence refs 时不能被当成强通过。
7. 从 run 详情查看关键结论、证据覆盖和 GateKeeper verdict，确认原始 prompt、context、output 留在追查材料中。
8. 从方案库导出 bundle，确认用户可以把方案文件带到系统外处理；Loopora 不把 bundle 迭代包装成内置流程。

**预期**：

- 新手主路径保持“任务 / 循环方案 / 运行 / 证据结论”的心智，不要求先理解内部 YAML。
- READY、run、evidence 和 GateKeeper 都能回到同一份 `spec / roles / workflow / evidence` 契约。
- 旧数据或降级路径可以继续查看，但不能伪装成已经满足新证据质量。
