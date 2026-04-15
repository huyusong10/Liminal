# Interfaces

## 1. Purpose

本模块定义用户如何进入系统，以及不同入口之间如何保持同一语义模型。

重点不是列出所有页面和命令，而是回答：

- 哪些差异属于交互差异
- 哪些差异不能上升为能力差异

## 2. Owned Boundary

接口层拥有以下边界：

1. 用户输入与服务层输入之间的边界
2. 不同入口形态之间的一致性边界
3. 本地访问与网络访问之间的安全边界
4. 文件预览与文件执行之间的边界

## 3. Responsibilities

接口层负责：

1. 收集用户输入
2. 做边缘层校验与规范化
3. 把输入映射到统一服务语义
4. 把运行状态投影成 CLI 输出、Web 页面和 API 响应

接口层不负责：

- 编排角色生命周期
- 直接操作数据库语义
- 承载 provider 私有协议

## 4. Interface Model

三类入口：

- CLI：面向脚本与终端用户
- Web UI：面向可视化操作与观测
- HTTP API：面向 Web UI 与程序化集成

一级功能还必须区分两类对象：

- `orchestration`：保存线性 workflow 与 prompt 资产
- `loop`：绑定 workdir / spec / executor，并引用一个 orchestration

设计原则：

- 三者共享同一个 loop 定义模型
- 差异只体现在交互方式，不体现在核心能力上

## 5. Consistency Rules

### 5.1 Required Parity

以下能力属于“核心能力”，必须跨入口同构：

- 创建 loop
- 选择 workflow preset 或提交自定义 workflow
- 编辑 / 上传 / 下载 prompt 文件
- 创建、列出、选择、编辑 orchestration
- 选择执行模式
- 指定运行边界参数
- 启动、重跑、停止、删除
- 校验 spec
- 校验 prompt 文件

### 5.2 Allowed Differences

以下差异属于“表现层差异”，允许存在：

- Web 提供 workflow 编辑器、实时流和页面导航
- CLI 提供同步等待或后台返回
- Web 在网络模式下禁用本地文件弹窗
- CLI 用 `--workflow-preset` / `--workflow-file` 替代表单式编辑
- Web 的 orchestration 列表默认进入编辑器；loop 创建页只负责“选择已有 orchestration”

### 5.3 Forbidden Differences

以下差异不可接受：

- 只有某一入口能表达核心 loop 配置
- 只有某一入口能表达 workflow 或 prompt 资产
- 同名配置项在不同入口语义不同
- 预览行为与实际提交行为不一致
- 把存储层 slug（例如 `build_first`、`finish_run`）直接暴露成主要用户文案

## 6. Dependency Direction

依赖方向必须保持为：

`user interaction -> interface layer -> orchestration service`

禁止：

- Web 直接实现业务编排
- CLI 直接维护独立状态模型
- API 直接暴露底层存储细节

## 7. Security Boundary

接口层负责把“可用性”与“暴露面”隔开。

核心原则：

- 本地默认安全优先
- 网络暴露必须显式进入
- 文件系统访问必须受根路径约束
- 预览接口必须按不可信内容处理

## 8. Documentation Scope

本文档只记录稳定边界：

- 入口职责
- 一致性规则
- 安全边界

本文档刻意不记录：

- 每一条路由
- 每一个页面元素
- 每一个 CLI flag

这些内容应以代码和测试为准。

## 9. Change Triggers

以下变化需要更新本文档：

- 新增一种顶层入口
- 跨入口能力模型变化
- workflow / prompt 编辑能力只落在单一入口
- 安全边界变化
- 输入规范化责任迁移

以下变化通常不需要更新本文档：

- 页面布局改版
- 命令帮助文本调整
- API 字段的局部扩展

## 10. Non-Goals

- 不把 Web 做成通用 IDE
- 不让 CLI 承担视觉观测职责
- 不把 API 扩张成平台化公网接口
