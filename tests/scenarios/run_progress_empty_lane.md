本用例由 Agent 自行进行模拟

# 场景：用户回到没有中间步骤的运行详情页

**目标**：确认当某次 run 的 workflow snapshot 没有冻结下中间 steps 时，阶段图会诚实退化成 entry / empty lane / exit，而不是继续画出像真实步骤一样的装饰轨道。

**前置**：已经存在一条 run，且它的 workflow snapshot 里只有入口检查和最终完成，没有任何中间 workflow step。

**步骤**：
1. 用当前界面语言打开这次 run 的详情页，先观察顶部“运行进度”面板里的阶段图。
2. 确认中央区域显示的是 empty-state 说明，而不是一个带中间 stage chips 的 workflow lane。
3. 观察空态周围是否还残留 rail、connector 或 loopback arc 一类装饰，确认这些视觉线索已经一并收起，不会误导用户以为还有隐藏步骤。
4. 再看控制台工具条，确认“打开全屏终端”等辅助标签也会直接使用当前界面语言，而不是只有可见文案被翻译。
5. 最后看左右两端的 `Checks` 与 `Done` terminal，确认它们依然保留，能表达“这次 run 只有入口和最终状态”的真实结构。

**预期**：空 workflow snapshot 会呈现清晰的说明型 empty state；标题、说明和控制台工具条辅助标签都会直接使用当前界面语言，不会先掉回英文首屏；中间不会出现误导性的轨道、连接线或弧线残影；terminal nodes 仍然可见，且整体语义与真实 run snapshot 一致。
