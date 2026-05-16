from __future__ import annotations

import re

_LOOP_FIT_GOVERNANCE_PATTERNS = (
    r"\b(?:multi[- ]?round|long[- ]?(?:running|term))\b.{0,120}\b(?:evidence|proof|handoffs?|judg(?:e|ment)|verdict|gatekeeper|blockers?|governance|auditable|run-owned)\b",
    r"\b(?:iterations?|rounds?)\b.{0,80}\b(?:new evidence|evidence|proof|handoffs?|blockers?|repair|anchor|anchored|survive|verdict|gatekeeper|judgment)\b",
    r"\b(?:one|single)\s+(?:agent\s+)?(?:pass|round|review)\b.{0,80}\b(?:not enough|insufficient|isn't enough|is not enough|cannot|can't|as enough)\b",
    r"\b(?:survive(?:s)?\s+(?:this|one)\s+chat|exportable|auditable|run-owned)\b",
    r"(?:多轮|后续轮次|下一轮|长期|持续).{0,80}(?:证据|判断|阻断|交接|修复|收束|裁决|运行)",
    r"(?:一次|单轮).{0,30}(?:不够|不足|不能|不应|不是|当成足够)",
    r"(?:活过本次聊天|可导出|可审计|运行期|运行中持续)",
)


def semantic_antipattern_match_is_negated(value: str, start: int) -> bool:
    context = value[max(0, start - 48) : start]
    return bool(
        re.search(
            r"do not|don't|must not|should not|never|avoid|refuse|reject|rather than|instead of|"
            r"\bnot\s+(?:a|an|as)?\s*$|\bno\s+$|不要|不能|不得|不应|不是|拒绝|避免",
            context,
            re.I,
        )
    )


def text_mentions_multiround_loopora_governance(text: object) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if not value:
        return False
    return any(re.search(pattern, value, re.I) for pattern in _LOOP_FIT_GOVERNANCE_PATTERNS)


def loop_fit_governance_trace(text: object, *, limit: int = 2) -> list[str]:
    traces = [
        unit[:240].rstrip() + ("..." if len(unit) > 240 else "")
        for unit in trace_text_units(str(text or ""))
        if any(re.search(pattern, unit, re.I) for pattern in _LOOP_FIT_GOVERNANCE_PATTERNS)
    ]
    return traces[:limit]


def text_mentions_loop_fit_contradiction(text: object) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not value:
        return False
    patterns = (
        r"\b(?:one|1|single)\s+agent\s+pass\b.{0,64}\b(?:human\s+)?review\b.{0,40}\b(?:is|would\s+be|seems|should\s+be)?\s*(?:enough|sufficient)\b",
        r"\b(?:one|1|single)[-\s]+(?:agent\s+)?(?:pass|review|run|round|attempt|shot)\b.{0,64}\b(?:enough|sufficient)\b",
        r"\b(?:one|single)\s+(?:agent\s+|implementation\s+)?(?:pass|review|run|round|attempt|shot)\s+(?:is\s+|was\s+)?(?:enough|sufficient)\b",
        r"\b(?:one|single)\s+(?:manual\s+|human\s+|code\s+)?review\b.{0,40}\b(?:should\s+)?(?:suffice|be\s+sufficient|be\s+enough)\b",
        r"\bsingle\s+implementation\s+pass\b.{0,64}\b(?:enough|sufficient)\b",
        r"\bdirect\s+(?:chat|conversation)\b.{0,40}\b(?:is|would\s+be|seems|should\s+be|was)?\s*(?:enough|sufficient)\b",
        r"\bdirect\s+(?:answer|response|reply)\b.{0,40}\b(?:is|would\s+be|seems|should\s+be|was)?\s*(?:enough|sufficient)\b",
        r"\bchat[-\s]*only\b.{0,40}\b(?:is|would\s+be|seems|should\s+be)?\s*(?:enough|sufficient)\b",
        r"\b(?:one[-\s]*off|one\s+time)\s+(?:task|request|job|change|fix)\b.{0,64}\b(?:no\s+(?:loop|loopora)|(?:loop|loopora)\s+(?:not\s+needed|isn't\s+needed|not\s+required|unnecessary))\b",
        r"\b(?:no|not\s+any)\s+(?:loop|loopora)\s+(?:needed|required)\b",
        r"\b(?:no\s+need\s+for|do\s+not\s+need|don't\s+need|does\s+not\s+need|doesn't\s+need)\s+(?:a\s+)?(?:loopora\s+)?loop\b",
        r"\bno\s+need\s+for\s+loopora\b",
        r"\b(?:loop|loopora)\s+(?:is\s+)?(?:not\s+needed|not\s+required|unnecessary)\b",
        r"\b(?:just|simply)?\s*(?:fix|do|handle|ship|patch)\s+it\s+once\b.{0,64}\b(?:manual|human)?\s*(?:review|check|confirm|confirmation)?\b.{0,32}\b(?:enough|sufficient|fine|ok|okay|needed|required)?\b",
        r"\bonly\s+need\s+(?:a\s+)?(?:quick\s+)?(?:answer|response|reply)\s+once\b",
        r"\bjudgment\b.{0,48}\b(?:is\s+)?(?:only|just)\s+needed\s+(?:once|one\s+time)\b",
        r"\bno\s+(?:later|future|next|additional)?\s*(?:round|rounds)?\b.{0,48}\b(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observation|verdict)\b",
        r"\b(?:next|later|another|future|additional)\s+(?:round|rounds|iteration|pass|run)\b.{0,48}\b(?:will|would|does|do|can|could)?\s*(?:not|n't|never|no|no longer|not really)\b.{0,32}\b(?:create|produce|add|yield)?\b.{0,32}\b(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observations?|verdict)\b",
        r"\b(?:later|future|next|additional)\s+rounds?\b.{0,48}\b(?:create|produce|add|yield)\b.{0,24}\bno\s+(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observation|verdict)\b",
        r"\b(?:stable|existing)?\s*benchmark\b.{0,48}\b(?:fully|completely|already)\s+(?:captures|covers|expresses)\b",
        r"\b(?:benchmark[- ]only|benchmark only|stable benchmark|existing benchmark|simple benchmark)\b.{0,48}\b(?:is|was)?\s*(?:enough|sufficient)\b",
        r"\bbenchmark\b.{0,40}\b(?:whole|entire|only)\s+(?:acceptance|proof|validation|judgment)\b",
        r"\buse\s+the\s+benchmark\s+first\b.{0,64}\b(?:instead\s+of|rather\s+than|skip|do\s+not|don't)\b.{0,32}\b(?:loopora|loop)\b",
        r"\b(?:stable|existing)?\s*(?:proof\s+harness|test\s+harness|contract\s+tests?|test\s+suite|tests?)\b.{0,48}\b(?:fully|completely|already)\s+(?:captures|covers|expresses|proves)\b",
        r"\b(?:proof[- ]?harness|test[- ]?harness|contract[- ]?tests?|test[- ]?suite|tests?)\b.{0,48}\b(?:is|are|was|were)?\s*(?:enough|sufficient)\b",
        r"\b(?:use|run)\s+the\s+(?:proof\s+harness|test\s+harness|contract\s+tests?|test\s+suite|tests?)\s+first\b.{0,64}\b(?:instead\s+of|rather\s+than|skip|do\s+not|don't)\b.{0,32}\b(?:loopora|loop)\b",
        r"\bjudgment\b.{0,48}\b(?:does\s+not|doesn't|need\s+not|won't)\s+survive\s+(?:one|this)\s+chat\b",
        r"一次\s*agent.{0,16}(?:人工\s*)?(?:review|审查|评审).{0,16}(?:足够|够了|即可|就行)",
        r"(?:一次|单轮|一轮).{0,16}(?:agent)?(?:执行|实现|处理|运行|pass|评审|对话|聊天).{0,16}(?:人工\s*)?(?:review|审查|评审)?.{0,16}(?:足够|够了|就行|即可)",
        r"(?:直接)?(?:聊天|对话).{0,16}(?:足够|够了|就行|即可)",
        r"(?:一次|本次)(?:聊天|对话).{0,16}(?:足够|够了|就行|即可)",
        r"(?:不会|没有|无需|无法|不能).{0,16}(?:产生|带来|增加)?.{0,8}(?:新证据|新证明|新产物|新交接|新裁决|新的证据|新的证明|新的产物|新的交接|新的观察)",
        r"(?:后续|下一轮|之后).{0,16}(?:不会|无法|不能|没有).{0,16}(?:证据|证明|产物|交接|观察)",
        r"(?:稳定|现有)?基准.{0,16}(?:完全覆盖|已经覆盖|足够表达|足够|够了|就行|即可)",
        r"只(?:跑|看)?基准.{0,16}(?:足够|够了|即可|就行)",
        r"(?:稳定|现有)?(?:测试|测试套件|契约测试|证明工具|验证工具|proof harness).{0,16}(?:完全覆盖|已经覆盖|足够表达|足够|够了|就行|即可)",
        r"只(?:跑|看)?(?:测试|测试套件|契约测试|证明工具|验证工具).{0,16}(?:足够|够了|即可|就行)",
        r"(?:一轮|单轮|一次|跑一遍|跑一次|做一遍).{0,12}(?:足够|够了|就够|就行|即可|可以)",
        r"(?:不需要|不用|无需|不必).{0,12}(?:多轮|后续轮次|后续迭代|循环)",
        r"(?:一次性任务|一次性请求|一次性修改|一次性修复).{0,16}(?:不需要|不用|无需|不必|不要(?!把)).{0,12}(?:长期|持续|多轮|循环|loopora|loop)",
        r"(?:不需要|不用|无需|不必|不要(?!把)).{0,12}(?:长期|持续|多轮|循环|loopora|loop)",
        r"(?:直接回答|直接回复|直接处理|直接改完|直接修完).{0,16}(?:足够|够了|就行|即可|可以)",
        r"(?:只要|只需|只需要).{0,16}(?:agent)?.{0,12}(?:做一遍|跑一遍|跑一次|执行一次).{0,16}(?:看一下|人工确认|人工审查|人工评审)?.{0,12}(?:就行|即可|可以)",
        r"(?:一次|一遍|一次性).{0,8}(?:修完|改完|做完|处理完|完成).{0,16}(?:回报|汇报|人工确认|人工看一下|人工审查|人工评审)?.{0,12}(?:就行|即可|可以|足够|够了)",
        r"(?:不需要|不用|无需|不必)\s*(?:开|使用|跑)?\s*(?:loopora|loop|循环)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, value, re.I):
            matched = match.group(0).lower()
            if re.search(r"\bnot\s+(?:enough|sufficient)\b|不(?:够|足够)", matched, re.I):
                continue
            if semantic_antipattern_match_is_negated(value, match.start()):
                continue
            return True
    return False


def trace_text_units(text: str) -> list[str]:
    units: list[str] = []
    for raw_line in str(text or "").splitlines():
        cleaned = re.sub(r"^\s*[-*]\s+", "", raw_line).strip()
        cleaned = re.sub(r"^\s*\d+[.)]\s+", "", cleaned).strip()
        if not cleaned or cleaned.startswith("#") or cleaned in {"---"}:
            continue
        for part in re.split(r"(?<=[.!?。！？；;])\s+", cleaned):
            compact = part.strip()
            if compact:
                units.append(compact)
    return units
