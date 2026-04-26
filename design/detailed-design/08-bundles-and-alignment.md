# Bundles And Alignment

## 1. 模块职责

本文档定义两条稳定边界：

- Loopora 如何把外部对齐结果消费成可运行资产
- bundle 如何作为单文件交换单元承载这次任务的协作结果

它回答的是：

- 什么是 bundle
- bundle 和手动资产是什么关系
- Web 内置对齐、外部 Agent + Skill 与 Loopora 本体如何分工

它不回答：

- 对话 prompt 的具体写法
- Agent 的内部实现细节

## 2. 核心边界

Loopora 本体仍然只是本地编排与执行引擎。

稳定分工如下：

| 边界 | 负责方 | 稳定职责 |
|------|--------|----------|
| 任务访谈与对齐 | Web 内置 alignment session，或外部 Agent + repo-local Skill | 围绕当前任务与用户沟通，形成 transient working agreement |
| bundle 产物生成 | Web 内置 alignment session，或外部 Agent + repo-local Skill | 输出单文件 YAML bundle |
| bundle 导入 / 导出 / 派生 / 删除 | Loopora 本体 | 管理 bundle 生命周期，并把 bundle 物化为本地资产 |
| run 执行 | Loopora 本体 | 从导入后的 `spec / role definitions / workflow` 运行 loop |

补充规则：

- `working agreement` 是编译期中间产物，不是运行期资产。
- Loopora 不执行独立的 agreement 文件。
- 最终运行输入仍然是 `spec / role definitions / workflow`。

## 3. Bundle 契约

bundle 是新的稳定交换单元。

它必须同时满足两件事：

- 人可读：用户能看懂这次 bundle 为什么这样编排
- 可运行：Loopora 能直接导入并物化为本地资产

bundle 至少包含：

| 区域 | 作用 |
|------|------|
| metadata | bundle 名称、描述、revision 等生命周期信息 |
| collaboration summary | 这次任务协作姿态的可读摘要 |
| loop | 运行参数与 workdir 绑定 |
| spec | task contract |
| role definitions | 角色模板与 task-scoped posture |
| workflow | 角色顺序、步骤结构与 `collaboration_intent` |

## 4. Posture 承载规则

`collaboration posture` 不是单个字段，也不是单个 prompt。

它必须共同承载在三种运行面上：

| 运行面 | 负责表达什么 |
|--------|--------------|
| `spec` | 成功面、假完成、证据偏好、残余风险等 task contract |
| `role definitions` | 每个角色在本次任务中的 posture，如更重视证据、重构、风险或推进速度 |
| `workflow` | 执行顺序、是否先取证、何时介入、如何收束 |

稳定规则：

- 三者缺一不可。
- bundle revision 默认按整包重编译，而不是只改某一个 surface。
- 手动微调时允许用户分别修改三种 surface，但导出后的 bundle 仍必须重新表达同一份协作结果。

## 5. 生命周期

bundle 生命周期按整包表达：

`导入 → 查看 → 局部编辑 / 派生 → 导出 → 删除`

补充规则：

- 导入后的资源默认属于同一 bundle。
- 删除 bundle 时，默认删除它导入的 loop、orchestration 与 role definitions。
- 被 bundle 拥有的 loop、orchestration 与 role definitions 不应再被当作可独立拆删对象；若用户想整体移除，应回到 bundle 生命周期入口。
- 删除 bundle 不应影响无关的手动资产。
- 从现有 loop 派生 bundle 时，派生结果必须回到单文件 YAML。
- 当用户修改 bundle 拥有的 spec、role definition 或 orchestration 时，bundle revision 也应前进，并重新导出同一份单文件 YAML。

## 6. 入口语义

推荐入口：

`创建循环选择页 → Bundle 对话页 → Web 内置对齐 / 既有 YAML 导入 → READY 预览 → 物化 loop → 运行`

手动入口继续保留：

`创建循环选择页 → 手动创建页 → spec / role definitions / orchestration / loop 手动编排`

稳定承诺：

- “创建循环”先分流到 Bundle-first 和手动专家模式，两者最终都创建 loop，但使用心智不同。
- Bundle-first 是默认推荐路径，承载 Web 内置对齐、已有 YAML 预览导入和 READY 后运行。
- 手动编排仍然是 expert mode，适合用户已经明确 spec、角色与 workflow 规则。
- 两条路径必须能互相转换：bundle 可以导入成手动资产，手动 loop 也可以派生回 bundle
- bundle 列表 / 详情页承担管理、导出、派生、整包删除和 revision 入口，不应再成为用户首次创建 loop 时必须理解的额外主流程

## 7. 变更触发

以下变化需要更新本文档：

- bundle 不再是单文件 YAML
- working agreement 的运行期地位变化
- bundle 生命周期语义变化
- Web 内置对齐、外部 Agent + Skill 与 Loopora 本体的边界变化
- posture 不再由 `spec / role definitions / workflow` 共同承载

以下变化通常不需要更新本文档：

- bundle 字段的小幅扩展
- 对齐话术调整
- Web / CLI 页面布局调整
