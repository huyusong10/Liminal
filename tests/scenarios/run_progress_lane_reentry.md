本用例由 Agent 自行进行模拟

# 场景：用户回到运行详情页重新理解阶段图

**目标**：确认运行详情页的阶段图能清楚区分入口检查、workflow loop 和最终收束，并让用户一眼看出 loop lane 与两端 terminal 的关系。

**前置**：已经存在一条至少包含 checks、若干 workflow steps 和 finished terminal 的 run。

**步骤**：
1. 打开这次 run 的详情页，先观察顶部“运行进度”面板里的阶段图。
2. 确认左侧 `Checks` terminal、中央 workflow loop、右侧 `Done` terminal 在版面上分区明确，而不是挤成一条难以分辨的直线。
3. 观察 workflow loop 周围的连接线和 loopback 弧线，确认它们只是帮助理解循环结构，不会让人误以为多了额外步骤。
4. 依次把视线从左 terminal 移到中间 workflow steps，再移到右 terminal，确认 entry / exit 的方向感稳定，且每个 stage chip 仍然可独立扫读。

**预期**：阶段图会把 terminal nodes 与中间 loop lane 的关系讲清楚；连接线和弧线只承担结构辅助作用，不改变真实阶段数量、顺序或 run 语义。
