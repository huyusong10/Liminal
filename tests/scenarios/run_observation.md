本用例由 Agent 自行进行模拟

# 场景：用户回到运行详情页观察证据、阶段和终端输出

**目标**：确认 run 详情页能从真实 run snapshot 投影阶段、证据摘要和终端输出，而不是用装饰性 UI 伪造进度。

**前置**：

- 至少存在一条已进入终态的 run。
- 最好再准备一条 workflow snapshot 没有中间 steps 的 legacy 或降级 run。

**步骤**：

1. 打开普通 run 详情页，确认入口检查、workflow steps、GateKeeper / finished 终态按 run contract 的顺序出现。
2. 查看 Key takeaways 与 evidence coverage，确认角色结论能追溯到 evidence refs 或 artifact。
3. 打开全屏终端视图，确认它仍指向同一 run，并只承担观察输出的职责。
4. 打开没有中间 steps 的 run，确认页面诚实退化成入口、空 workflow lane 和最终状态。
5. 检查空态不会残留像真实步骤一样的连接线、轨道或假节点。

**预期**：

- 阶段图只表达 run snapshot 中真实存在的阶段。
- 证据和 GateKeeper 结论是主判断入口，原始 artifact 与终端输出是追查入口。
- legacy 或降级 run 可以查看，但不会被展示成同等质量的新证据闭环。
