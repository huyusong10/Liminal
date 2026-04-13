# 不可违反的约束

## 技术约束
- 不得修改 `workspace/src/api/` 目录下的接口定义
- 所有新增依赖必须在 `workspace/src/requirements.txt` 中声明
- 不得使用 Python 3.10 以下语法

## 行为约束
- 每次迭代只做一个方向改动
- 修改前必须在 scratch.md 中写推理过程
- 若存在 `handoff/challenger_seed.json` 未消费，必须在 iteration_log 解释采纳与否

## iteration_log 必填
1. 尝试方向
2. 放弃方向
3. 隐含假设
