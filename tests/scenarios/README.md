本目录只保留少量人工探索旅程，用来辅助 Agent 或人工回归核心用户路径。能由 deterministic checks、real probes 或 review cases 覆盖的内容不再保留为 scenario。

- 场景描述应锁定稳定行为，不绑定具体中文或英文文案。
- 一个核心旅程最多保留一个场景；相邻 UI 细节合并到同一旅程里。
- 已有自动化契约测试覆盖的分支，不再单独写成场景文件。
- 每个保留场景都必须说明为什么不能完全由 checks / probes / reviews 覆盖。

当前保留：

- `long_running_governance_loop.md`：跨对话编排、READY、运行、证据、裁决和导出，关注端到端产品心智与证据串联。
- `asset_navigation_and_editing.md`：跨 Loop 卡片、方案文件、编辑器与危险动作，关注多入口之间的人工导航判断。
