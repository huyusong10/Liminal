# Loopora Design

## 1. 目的

本目录记录 Loopora 的设计约束与实现分解。

最高产品原则见 `core-ideas/product-principle.md`：

> Loopora 是面向长期 AI Agent 任务的外部任务治理层。所有设计都必须服务于 `任务输入 -> 对齐治理方案 -> 运行并收集证据 -> 基于证据修订 harness` 的闭环，而不是退化成 role zoo、prompt pack、loop script、通用聊天界面或内部资产 CRUD console。

同一原则还包含“5 分钟上手”硬约束：高级治理能力只能服务于误差控制，并且必须默认隐藏在循环方案、专家编辑或修订路径中，不能让第一次使用变成配置 workflow 平台。

文档分成两个子模块：

- `core-ideas/`：只保留抽象规则、反例、非目标；作为项目级约束。
- `detailed-design/`：按高内聚模块拆分实现设计；作为实现和演进的参考面。

## 2. 使用规则

- `core-ideas/` 优先回答“什么绝不能变形”。
- `detailed-design/` 优先回答“模块边界如何切、职责如何分、依赖如何流动”。
- 本目录不是 README 扩写版；不重复安装、使用教程、营销性描述。
- 本目录默认以当前代码为准；如果文档与实现冲突，应同时修正文档和实现，不允许长期漂移。
- 细节设计不追踪易变细节；字段枚举、提示词文案、常量阈值、临时 UI copy 不是这里的重点。

## 3. 文档稳定性原则

以下变化通常不要求更新 `detailed-design/`：

- 小范围字段增删
- 文案调整
- 默认值调整
- provider 参数细节调整
- 日志结构小幅扩展

以下变化必须更新 `detailed-design/`：

- 模块职责迁移
- 依赖方向改变
- 生命周期或状态机改变
- 新增或删除一层核心边界
- 原有不变量失效

## 4. 文档地图

| 子模块 | 文档 | 主题 | 主要代码边界 |
| --- | --- | --- | --- |
| 演进路线 | `evolution.md` | 从当前实现走向外部任务治理层的能力路线 | 全局 |
| 核心思想 | `core-ideas/README.md` | 项目公理、反例、非目标 | 全局 |
| 核心思想 | `core-ideas/product-principle.md` | 最高产品原则、外部任务治理与默认用户心智 | 全局 |
| 核心思想 | `core-ideas/collaboration-posture.md` | 用户判断姿态如何成为治理输入 | 全局 |
| 核心思想 | `core-ideas/task-scoped-alignment.md` | 任务驱动对齐、working agreement 与循环方案演进 | 全局 |
| 细节设计 | `detailed-design/01-spec-subsystem.md` | `spec.md` 编译与 checks 冻结 | `src/loopora/specs.py`, `src/loopora/service.py` |
| 细节设计 | `detailed-design/02-orchestration-service.md` | loop/run 编排与角色循环 | `src/loopora/service.py` |
| 细节设计 | `detailed-design/03-executor-subsystem.md` | 执行器、provider 适配、命令模式 | `src/loopora/executor.py`, `src/loopora/providers.py` |
| 细节设计 | `detailed-design/04-persistence-and-reliability.md` | 存储、事件、锁、恢复、安全守卫 | `src/loopora/db.py`, `src/loopora/settings.py`, `src/loopora/recovery.py`, `src/loopora/stagnation.py`, `src/loopora/service.py` |
| 细节设计 | `detailed-design/05-interfaces.md` | Web / CLI / API 交互面 | `src/loopora/cli.py`, `src/loopora/web.py`, `src/loopora/templates/`, `src/loopora/static/` |
| 细节设计 | `detailed-design/06-workflow-and-prompts.md` | workflow、prompt 与角色快照契约 | `src/loopora/workflows.py`, `src/loopora/context_flow.py` |
| 细节设计 | `detailed-design/07-observability-and-diagnostics.md` | 统一日志契约、事件命名与分级规则 | `src/loopora/diagnostics.py`, `src/loopora/settings.py`, `src/loopora/db.py`, `src/loopora/service.py`, `src/loopora/web.py`, `src/loopora/cli.py` |
| 细节设计 | `detailed-design/08-bundles-and-alignment.md` | bundle 生命周期、外部 skill 边界与 task-scoped alignment 落点 | `src/loopora/bundles.py`, `src/loopora/service_bundle_assets.py`, `skills/loopora-task-alignment/` |
| 细节设计 | `detailed-design/09-web-bundle-alignment.md` | Web 内置任务对齐入口、alignment session、READY 预览与创建运行 | `src/loopora/web_route_*.py`, `src/loopora/templates/`, `src/loopora/static/`, `src/loopora/executor.py`, `src/loopora/bundles.py` |

## 5. 读者约定

- 产品与架构讨论先读 `core-ideas/README.md`。
- 改某个模块前先读对应的 `detailed-design/*.md`。
- 涉及跨模块变更时，至少同时检查：
  - `02-orchestration-service.md`
  - `04-persistence-and-reliability.md`
  - `05-interfaces.md`
  - `06-workflow-and-prompts.md`
  - `08-bundles-and-alignment.md`
  - `09-web-bundle-alignment.md`
  - `07-observability-and-diagnostics.md`
