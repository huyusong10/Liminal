本用例由Agent自行进行模拟

# 场景：新用户通过教程页理解 bundle-first 创建路径

**前置**：首次进入 Loopora Web UI，还不了解 collaboration posture、bundle、创建循环三者的关系。

**步骤**：
1. 分别用英文和中文打开“使用教程”页面，确认浏览器页签标题与页内主标题在首帧就和当前界面语言一致。
2. 先阅读顶部核心精神卡片，确认页面说明 Loopora 编译的是 task-scoped collaboration posture，而不是要求用户先写完整 workflow rule。
3. 确认教程说明 posture 由 `spec`、角色定义和 workflow 共同承载，不把姿态误导成单个 prompt。
4. 继续阅读决策树，确认用户先判断“该不该用 Loopora”，再判断哪条流程最能减少下一次人工回场。
5. 滚到行动入口，确认默认路径是安装对齐 Skill、导入 bundle 创建循环；手动编排被明确标为 expert mode。
6. 打开任意流程样例弹窗，确认样例仍帮助用户理解 workflow 如何承载姿态，而不是把流程名当成静态规则。

**预期结果**：
- 教程页的文档标题与正文主标题在首帧就保持 locale 一致，不会先闪回默认英文。
- 新用户不用先理解所有内部资产，也能知道默认应该从外部 Agent + Skill 生成 bundle，再到“创建循环”导入运行。
- 教程不会把 working agreement 描述成运行期资产；最终运行输入仍然落在 bundle 编译出的 `spec / roles / workflow`。
- 手动入口仍然清晰可见，但不会盖过 bundle-first 的推荐路径。
