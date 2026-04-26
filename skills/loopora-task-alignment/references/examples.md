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

> 这次目标是一个英语学习网站首版完整产品，不是纯展示页。成功要证明用户能在浏览器里走完一条真实学习路径，例如选择水平、开始学习、完成练习、看到进度。最不能接受的是页面好看但不能学习。证据优先浏览器主流程，其次是测试和设计契约。Builder 需要聚焦小而真实的学习闭环；Inspector 先查假进度和浅功能；GateKeeper 严格签字，只在主流程、进度反馈和基础可维护性可信时通过。workdir 事实目前只来自目标目录观察；如果目录为空或无法判断，应在 bundle 中把技术栈选择写成待验证假设。

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

## Revision example

User:

> 这个 bundle 太偷懒了，跑出来只是页面能看

Better response:

> 我会把这当成 bundle-level revision，不只改 GateKeeper 一句话。当前反馈说明成功面和 fake-done 太弱，Inspector/GateKeeper 对视觉-only 完成不够敏感，workflow 也可能太快进入签字。我的修订方向是：强化 `# Fake Done`、提高浏览器或测试证据要求、让 Inspector 明确阻断静态页面，并让 GateKeeper 只有在真实用户路径可复验时 finish。请确认这个方向，或说明你更在意结构债还是证据深度。

