# Liminal — 指标驱动自主迭代框架

> **Liminal**：来自拉丁语 *limen*（门槛）。系统始终处于已知解与未知可能之间的门槛地带——既不允许停留在局部最优，也不允许随机退化。每一次 Challenger 介入都是穿越一道门槛。

---

## 一、设计背景

### 核心问题

Ralph Loop 解决了 context 污染，但未解决两个更深层的问题：

1. **自我评估失效**：单一 agent 既执行又评判，Goodhart 定律在 agent 层面的体现——当测试者和优化者共享上下文，指标就不再是质量的代理，而变成被优化的目标本身。
2. **局部最优陷阱**：LLM 的偏差沿训练分布梯度漂移，有方向性而非随机游走，单线程迭代容易在已知解空间内收敛。

### 核心设计原则

> **Context 的范围，而不是功能职责，才是划分角色的核心依据。**
> 每个角色“知道什么”和“不知道什么”同等重要。

---

## 二、角色设计

四个角色，按信息访问范围从窄到宽：

```text
Tester      Verifier     Challenger    Generator
[黑盒执行]  [测试结果]   [指标摘要]    [完整上下文]
[不读代码]  [不看实现]   [不看代码]    [所有文件]
    ↑            ↑            ↑              ↑
  最窄                                     最宽
```

| 角色 | 核心职责 | 最优失败模式 |
|------|---------|------------|
| Tester | 主动寻找破绽 | 测试太浅，未覆盖边界 |
| Verifier | 保守、严格、可重复地裁判 | 对 LLM 产出过度宽容 |
| Challenger | 质疑隐含假设，打破稳定 | 扰动缺乏方向性，成为噪声 |
| Generator | 执行优化，记录决策 | iteration_log 填写流于表面 |

---

## 三、文件系统全结构

```text
liminal/
├── spec/                        # 定义层：人工维护，所有 agent 原则上只读
│   ├── test_cases.json
│   ├── acceptance_criteria.json
│   └── constraints.md
│
├── state/                       # 状态层：追加写入，保留完整历史
│   ├── metrics_history.jsonl
│   ├── iteration_log.jsonl
│   └── stagnation.json
│
├── handoff/                     # 接力层：每轮覆盖写入，单向流动
│   ├── tester_output.json
│   ├── verifier_verdict.json
│   └── challenger_seed.json
│
└── workspace/                   # 工作层：Generator 专属
    ├── src/                     # 实际代码/方案
    └── scratch.md               # Generator 工作草稿
```

---

## 四、文件结构详细设计

### 4.1 `spec/test_cases.json`

测试用例定义。由人工维护，Tester 和 Generator 可读，Verifier 不读（防止 Verifier 对测试用例产生偏见）。

```json
{
  "version": "1.0.0",
  "target_metric": "f1_score",
  "target_threshold": 0.95,
  "cases": [
    {
      "id": "case_001",
      "name": "基本功能验证",
      "category": "core",
      "weight": 1.0,
      "input": {
        "type": "json",
        "data": { "query": "hello world" }
      },
      "expected": {
        "type": "exact_match",
        "value": "HELLO WORLD"
      },
      "timeout_ms": 1000
    },
    {
      "id": "case_002",
      "name": "空输入边界",
      "category": "edge",
      "weight": 0.8,
      "input": {
        "type": "json",
        "data": { "query": "" }
      },
      "expected": {
        "type": "schema",
        "schema": {
          "error": { "type": "string", "required": true }
        }
      },
      "timeout_ms": 500
    }
  ],
  "tester_instructions": "主动构造 cases 中未覆盖的边界情况，额外生成动态测试用例并附加到输出中。你的目标是让系统失败。"
}
```

**字段说明：**
- `target_metric`：主要优化指标名，与 `metrics_history` 中的 key 对应
- `target_threshold`：达到此值视为成功，由编排脚本读取
- `cases[].weight`：加权计算综合得分
- `cases[].expected.type`：支持 `exact_match` / `schema` / `contains` / `numeric_range` / `custom_script`
- `tester_instructions`：直接注入 Tester 的 system prompt

### 4.2 `spec/acceptance_criteria.json`

验收标准。Verifier 的评判依据，不含具体测试用例（防止 Verifier 和 Tester 信息耦合）。

```json
{
  "version": "1.0.0",
  "metrics": {
    "f1_score": {
      "weight": 0.6,
      "pass_threshold": 0.95,
      "description": "综合精确率和召回率"
    },
    "latency_p99_ms": {
      "weight": 0.2,
      "pass_threshold": 200,
      "direction": "lower_is_better",
      "description": "P99 延迟不超过 200ms"
    },
    "edge_case_coverage": {
      "weight": 0.2,
      "pass_threshold": 0.80,
      "description": "边界用例通过率"
    }
  },
  "composite_score": {
    "formula": "weighted_average",
    "pass_threshold": 0.90
  },
  "hard_constraints": [
    "latency_p99_ms 不得超过 500ms（无论其他指标）",
    "core 类别用例全部通过才允许计算 composite_score"
  ],
  "verifier_stance": "保守。当测试结果模糊时，倾向于判定失败而非通过。发现问题后不得自我说服‘这不重要’。"
}
```

### 4.3 `spec/constraints.md`

Generator 必须遵守的不可违反约束。纯自然语言，直接注入 Generator system prompt。

```markdown
# 不可违反的约束

## 技术约束
- 不得修改 `workspace/src/api/` 目录下的接口定义（向后兼容要求）
- 所有新增依赖必须在 `workspace/src/requirements.txt` 中声明
- 不得使用 Python 3.10 以下的语法特性

## 行为约束
- 每次迭代只做一个方向的改动，不允许同时修改多个独立模块
- 修改前必须在 scratch.md 中写出推理过程
- 若 challenger_seed.json 存在且未消费，必须在 iteration_log 中说明是否采纳及原因

## iteration_log 填写规范
每轮必须包含以下三个字段，不得省略或敷衍：
1. **尝试方向**：本轮做了什么，为什么这样做
2. **放弃的方向**：考虑过但没做的方向，以及放弃原因
3. **隐含假设**：当前方案依赖的、尚未被验证的核心假设是什么
```

### 4.4 `state/metrics_history.jsonl`

每行一条记录，追加写入，永不覆盖。Verifier 写，Challenger 读，Generator **禁止读取**。

```jsonl
{"iter": 0, "timestamp": "2025-01-01T00:00:00Z", "scores": {"f1_score": 0.52, "latency_p99_ms": 380, "edge_case_coverage": 0.40}, "composite": 0.48, "passed": false, "challenger_triggered": false}
{"iter": 1, "timestamp": "2025-01-01T00:08:23Z", "scores": {"f1_score": 0.61, "latency_p99_ms": 340, "edge_case_coverage": 0.50}, "composite": 0.57, "passed": false, "challenger_triggered": false}
{"iter": 5, "timestamp": "2025-01-01T00:41:10Z", "scores": {"f1_score": 0.71, "latency_p99_ms": 290, "edge_case_coverage": 0.65}, "composite": 0.69, "passed": false, "challenger_triggered": false}
{"iter": 6, "timestamp": "2025-01-01T00:49:55Z", "scores": {"f1_score": 0.71, "latency_p99_ms": 295, "edge_case_coverage": 0.65}, "composite": 0.69, "passed": false, "challenger_triggered": true}
```

### 4.5 `state/iteration_log.jsonl`

每行一条 Generator 的决策记录，追加写入。Generator 写，Challenger 读，其他角色不读。

```jsonl
{"iter": 0, "timestamp": "2025-01-01T00:00:00Z", "attempted": "建立基础架构，实现核心 pipeline", "abandoned": "无（首轮）", "assumption": "问题的瓶颈在数据预处理阶段", "challenger_seed_consumed": false, "challenger_seed_adopted": null}
{"iter": 1, "timestamp": "2025-01-01T00:08:23Z", "attempted": "优化分词逻辑，增加同义词扩展", "abandoned": "考虑过换用 BM25，但认为当前问题不是检索而是理解，放弃", "assumption": "语义理解比关键词匹配更重要，当前指标瓶颈在理解层", "challenger_seed_consumed": false, "challenger_seed_adopted": null}
{"iter": 6, "timestamp": "2025-01-01T00:49:55Z", "attempted": "增加 ensemble，引入第二个模型投票", "abandoned": "考虑过完全重写特征工程，但改动太大，风险高，放弃", "assumption": "单模型已到天花板，需要集成学习", "challenger_seed_consumed": true, "challenger_seed_adopted": false, "challenger_seed_reason": "Challenger 建议重新审视特征工程，但判断当前 ensemble 路径更有把握，未采纳"}
```

### 4.6 `state/stagnation.json`

停滞状态，由 Verifier 更新，由编排脚本和 Challenger 读取。每轮覆盖写入（不追加）。

```json
{
  "current_iter": 6,
  "consecutive_low_delta": 3,
  "delta_threshold": 0.005,
  "trigger_window": 4,
  "recent_deltas": [0.09, 0.08, 0.02, 0.01, 0.00, 0.00],
  "recent_composites": [0.48, 0.57, 0.64, 0.67, 0.69, 0.69],
  "stagnation_mode": "plateau",
  "challenger_triggered_at_iters": [3],
  "last_challenger_effect": {
    "triggered_at_iter": 3,
    "composite_before": 0.61,
    "composite_after_3_iters": 0.67,
    "delta_improvement": 0.06
  }
}
```

### 4.7 `handoff/tester_output.json`

Tester 写，Verifier 读。每轮完整覆盖。

```json
{
  "iter": 6,
  "timestamp": "2025-01-01T00:47:12Z",
  "execution_summary": {
    "total_cases": 28,
    "passed": 19,
    "failed": 7,
    "errored": 2,
    "total_duration_ms": 4821
  },
  "case_results": [
    {
      "id": "case_001",
      "category": "core",
      "weight": 1.0,
      "status": "passed",
      "duration_ms": 87,
      "actual_output": "HELLO WORLD",
      "expected_output": "HELLO WORLD",
      "diff": null
    },
    {
      "id": "case_002",
      "category": "edge",
      "weight": 0.8,
      "status": "failed",
      "duration_ms": 1203,
      "actual_output": { "result": "" },
      "expected_output": { "error": "input cannot be empty" },
      "diff": "期望返回 error 字段，实际返回空 result",
      "failure_type": "wrong_schema"
    }
  ],
  "dynamic_cases": [
    {
      "id": "dynamic_001",
      "name": "超长输入压力测试（Tester 自行构造）",
      "category": "edge",
      "weight": 0.5,
      "status": "errored",
      "duration_ms": 5000,
      "error": "TimeoutError: exceeded 1000ms",
      "tester_note": "输入长度 10000 字符时触发超时，建议关注"
    }
  ],
  "tester_observations": "发现系统在输入包含特殊字符 '\\n' 时行为不一致，部分情况返回 null，部分情况抛出异常。建议 Verifier 重点关注 case_015 和 case_016。"
}
```

### 4.8 `handoff/verifier_verdict.json`

Verifier 写，Generator 读。每轮完整覆盖。

```json
{
  "iter": 6,
  "timestamp": "2025-01-01T00:48:33Z",
  "passed": false,
  "composite_score": 0.693,
  "metric_scores": {
    "f1_score": {
      "value": 0.71,
      "threshold": 0.95,
      "passed": false,
      "weight": 0.6
    },
    "latency_p99_ms": {
      "value": 295,
      "threshold": 200,
      "passed": false,
      "weight": 0.2,
      "direction": "lower_is_better"
    },
    "edge_case_coverage": {
      "value": 0.65,
      "threshold": 0.80,
      "passed": false,
      "weight": 0.2
    }
  },
  "hard_constraint_violations": [],
  "failed_case_ids": ["case_002", "case_008", "case_012", "case_015", "case_016", "case_019", "case_023"],
  "priority_failures": [
    {
      "case_id": "case_015",
      "severity": "high",
      "description": "特殊字符 '\\n' 导致行为不一致，core 类别，建议优先修复"
    },
    {
      "case_id": "case_002",
      "severity": "medium",
      "description": "空输入未返回正确 error schema"
    }
  ],
  "feedback_to_generator": "本轮 f1_score 未提升（相比上轮持平），延迟也未改善。priority_failures 中 case_015 的特殊字符处理问题是新出现的回退，建议优先修复后再考虑整体提升。",
  "verifier_confidence": "high"
}
```

### 4.9 `handoff/challenger_seed.json`

Challenger 写，Generator 读，消费后由 Generator 标记为已读（在 iteration_log 中记录）。停滞触发时创建，Generator 消费后删除或置空。

```json
{
  "created_at_iter": 6,
  "mode": "plateau",
  "consumed": false,
  "analysis": {
    "stagnation_pattern": "composite_score 在 iter 4-6 持续为 0.69，delta 趋近于零。指标曲线在早期快速上升后出现平台期。",
    "identified_assumptions": [
      {
        "assumption": "问题瓶颈在语义理解层，特征工程已足够好",
        "evidence_from_log": "iter_001 中放弃了'换用 BM25'，iter_003 中放弃了'重写特征工程'，两次均以'改动太大'为由",
        "challenge": "连续两次放弃特征工程方向，但指标恰好在这之后开始停滞。放弃的理由是实施成本，而非验证了假设本身是错的。"
      },
      {
        "assumption": "ensemble 是突破当前天花板的正确方向",
        "evidence_from_log": "iter_006 采用了 ensemble，但指标未提升",
        "challenge": "ensemble 没有带来改善，说明问题可能不是模型容量不足，而是输入特征本身的质量上限。"
      }
    ]
  },
  "seed_question": "如果特征工程是瓶颈而非模型本身，当前的特征表示错过了哪些信号？在不了解当前实现的情况下，你会如何重新定义这个问题的输入空间？",
  "meta_note": "这不是指令。Generator 可以选择不采纳，但必须在 iteration_log 中说明判断理由。"
}
```

### 4.10 `workspace/scratch.md`

Generator 专用工作草稿，每轮迭代开始时清空，迭代过程中随意使用。其他角色不读。

```markdown
# Iter 007 工作草稿

## 读取的输入
- verifier_verdict: composite=0.693, priority failure: case_015 (特殊字符)
- challenger_seed: 存在，mode=plateau，质疑特征工程假设

## 初步分析
case_015 的特殊字符问题是新出现的回退，必须先修复。
challenger_seed 的问题有意思——我们确实从未认真验证特征工程的假设。

## 方案比较
方案A：先修 case_015，再小幅调整现有特征
  - 优点：风险低，可以保住现有进展
  - 缺点：可能继续在平台期打转

方案B：修 case_015 + 重新审视特征工程（部分采纳 challenger_seed）
  - 优点：可能突破平台期
  - 缺点：改动较大，有回退风险

决定：采用方案B，但分两步，先修 case_015 确保不回退，再在特征层做一个
最小可验证的改动——只改一个特征，看指标反应。

## 执行步骤
1. 修复 src/preprocessor.py 中的换行符处理
2. 在 src/features.py 中增加字符级 n-gram 特征（最小改动）
3. 更新 scratch.md 记录结果
4. 写 iteration_log
```

---

## 五、完整工作流循环

```text
初始化：
  人工填写 spec/ 所有文件
  初始化 state/stagnation.json（iter=0, consecutive_low_delta=0）
  创建空 state/metrics_history.jsonl 和 state/iteration_log.jsonl

LOOP (iter = 0, 1, 2, ...):

  [Generator]
    读取: verifier_verdict.json（若存在）+ challenger_seed.json（若存在）
    清空: scratch.md
    执行: 修改 workspace/src/，写 scratch.md
    写入: iteration_log.jsonl（追加一行，三字段必填）
    标记: 若消费了 challenger_seed，在 iteration_log 中记录是否采纳

  [Tester]
    读取: spec/test_cases.json + workspace/src/（运行时）
    执行: 运行所有 cases + 构造动态边界测试
    写入: handoff/tester_output.json（覆盖）

  [Verifier]
    读取: tester_output.json + spec/acceptance_criteria.json
    计算: 各项指标得分和 composite score
    写入: state/metrics_history.jsonl（追加）
           handoff/verifier_verdict.json（覆盖）
           state/stagnation.json（覆盖，更新 delta 统计）

  [编排脚本 — 纯代码逻辑，非 LLM]
    读取: verifier_verdict.json + stagnation.json
    判断:
      if verdict.passed == true → EXIT SUCCESS
      if stagnation.consecutive_low_delta >= trigger_window:
          → 触发 Challenger
          → 强制 context reset（新 session）
      elif context_token_usage > 0.7:
          → 软 reset（保留最近 K 条 iteration_log + 最新 verdict）
      → 回到 Generator

  [Challenger — 仅停滞触发]
    读取: state/metrics_history.jsonl + state/iteration_log.jsonl
           state/stagnation.json
    禁止读取: workspace/src/（最核心的隔离）
    模式选择:
      stagnation_mode == "plateau" → Alien 模式
      stagnation_mode == "regression" → Archaeologist 模式
    写入: handoff/challenger_seed.json（覆盖）
    → 编排脚本触发强制 context reset，回到 Generator
```

---

## 六、停滞检测参数

| 参数 | 建议初始值 | 说明 |
|------|-----------|------|
| `delta_threshold` | 0.005 | composite score 改善低于此值视为无效改善 |
| `trigger_window` | 4 轮 | 连续多少轮无效改善后触发 Challenger |
| `regression_window` | 2 轮 | 连续多少轮 delta 为负视为 regression 模式 |
| 软 reset token 阈值 | 70% | context 使用超过此比例触发软 reset |
| 软 reset 保留轮数 K | 3 轮 | 软 reset 时 iteration_log 保留最近几条完整记录 |

---

## 七、Context Reset 策略

| 场景 | 类型 | Handoff 内容 |
|------|------|-------------|
| Challenger 触发后 | 强制硬 reset | `challenger_seed.json` + `verifier_verdict.json` + `constraints.md` |
| 正常迭代 token > 70% | 软 reset | `verifier_verdict.json` + `iteration_log.jsonl` 最近 K 行 + `constraints.md` |
| 正常迭代 token 充足 | 不 reset | 继续当前 session |

> Challenger 触发时必须硬 reset。目的就是打破连续性，compaction 无法实现这一点。

---

## 八、项目名由来与隐喻

**Liminal** 源自拉丁语 *limen*（门槛、入口）。在人类学中，“liminal” 描述仪式中的过渡状态——既不再是旧的，也尚未成为新的，处于两种状态之间的门槛地带。

这个系统的设计哲学正是如此：

- **Verifier** 守住已知的标准，防止退化
- **Challenger** 推动越过当前认知的门槛
- **Generator** 始终在已知解与未知可能之间探索
- 整个系统不追求收敛到局部最优，而是保持在门槛地带的张力中持续前进

每一次 Challenger 介入，都是穿越一道门槛的尝试。

---

## 九、已知局限

1. **iteration_log 质量依赖**：Challenger 的洞察上限取决于 Generator 填写“放弃的方向”和“隐含假设”的诚实程度。需要在 Generator system prompt 中反复强调，并在 constraints.md 中作为硬性规范。
2. **停滞参数敏感性**：`delta_threshold` 和 `trigger_window` 对系统行为影响显著，没有通用最优值，需针对具体任务调优。
3. **Challenger 效果无保证**：架构提供涌现的条件，但不保证涌现发生。`stagnation.json` 中的 `last_challenger_effect` 字段用于追踪历史效果，若多次触发均无效可考虑调整 Challenger 的 system prompt。
4. **Tester 动态用例的权重**：Tester 自行构造的 `dynamic_cases` 权重较低，但不应为零——它们往往覆盖了最重要的边界情况。
