# Alignment Examples

Use these examples as behavior guides. Do not copy them verbatim unless the task matches.

## Good creation example: English learning website

User:

> 我想创建一个英语学习网站

Weak response:

> 好的，我会生成一个英语学习网站 bundle。请确认。

Better response:

> 先定这次 Loopora 应该保护哪种“真实完成”。你更想要：1. 可运行首版产品；2. 课程/内容结构设计；3. 先做技术骨架？另外你最怕哪种假完成：页面好看但不能学习、功能很多但都很浅，还是后续很难扩展？

After the user says they want a complete first product, comprehensive path, fewer but solid features, browser evidence, and no visual-only completion, the working agreement can say:

> 这次目标是一个英语学习网站首版完整产品，不是纯展示页。成功要证明用户能在浏览器里走完一条真实学习路径，例如选择水平、开始学习、完成练习、看到进度。最不能接受的是页面好看但不能学习。证据优先浏览器主流程，其次是测试和设计契约。workflow 适合先由 Builder 做一个小而真实的学习闭环，再让 Contract Inspector 检查任务契约和 fake-done 风险、Evidence Inspector 独立收集浏览器或测试证据，最后由 GateKeeper 严格签字。两个 Inspector 应读取同一个 Builder handoff，GateKeeper 汇总两条检视证据。workdir 事实目前只来自目标目录观察；如果目录为空或无法判断，应在 bundle 中把技术栈选择写成待验证假设。

## Bad premature generation example

User:

> 我想做一个 CRM，直接生成 bundle

Bad response:

> 已生成 bundle。

Better response:

> 还不能直接生成，因为 CRM 的完成标准会强烈影响 workflow。先确认一个会改变方案的问题：这次你最怕的是销售流程跑不通、数据权限错、还是报表看起来有但不能指导行动？

## User asks to generate after partial alignment

User:

> OK，请你生成 bundle

If fake-done risks and evidence are clear but role posture is not clear:

> 还差一个会改变 roles 和 workflow 的点：GateKeeper 这次应该严格到“主路径、数据和基础可维护性都过关才签字”，还是只要核心路径跑通即可接受少量结构债？确认这个后我再整理工作协议。

## Parallel inspection example

User:

> 我要做一个可运行的报表页面，但我很怕它只是 UI 漂亮，数据逻辑其实不对

Better response:

> 这类任务适合 `Builder -> [Contract Inspector + Evidence Inspector] -> GateKeeper`：Builder 先做可运行页面，Contract Inspector 看报表口径、筛选和权限是否符合任务契约，Evidence Inspector 独立跑浏览器路径或数据检查证明报表确实可信。两个 Inspector 并行看同一个 Builder handoff，GateKeeper 只在两边证据都足够时通过。再确认一个会改变 spec 的点：你更信任哪类证据，真实浏览器操作、数据 fixture 对账，还是项目已有测试？
