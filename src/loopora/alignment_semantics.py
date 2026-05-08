from __future__ import annotations

import re


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


def text_mentions_loop_fit_contradiction(text: object) -> bool:
    value = re.sub(r"\s+", " ", str(text or "")).strip().lower()
    if not value:
        return False
    patterns = (
        r"\b(?:one|1|single)\s+agent\s+pass\b.{0,64}\b(?:human\s+)?review\b.{0,40}\b(?:is|would\s+be|seems|should\s+be)?\s*(?:enough|sufficient)\b",
        r"\b(?:one|1|single)[-\s]+(?:agent\s+)?(?:pass|review|run|round|attempt|shot)\b.{0,64}\b(?:enough|sufficient)\b",
        r"\b(?:one|single)\s+(?:agent\s+|implementation\s+)?(?:pass|review|run|round|attempt|shot)\s+(?:is\s+|was\s+)?(?:enough|sufficient)\b",
        r"\bsingle\s+implementation\s+pass\b.{0,64}\b(?:enough|sufficient)\b",
        r"\bdirect\s+(?:chat|conversation)\b.{0,40}\b(?:is|would\s+be|seems|should\s+be|was)?\s*(?:enough|sufficient)\b",
        r"\bchat[-\s]*only\b.{0,40}\b(?:is|would\s+be|seems|should\s+be)?\s*(?:enough|sufficient)\b",
        r"\bjudgment\b.{0,48}\b(?:is\s+)?(?:only|just)\s+needed\s+(?:once|one\s+time)\b",
        r"\bno\s+(?:later|future|next|additional)?\s*(?:round|rounds)?\b.{0,48}\b(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observation|verdict)\b",
        r"\b(?:next|later|another|future|additional)\s+(?:round|rounds|iteration|pass|run)\b.{0,48}\b(?:will|would|does|do|can|could)?\s*(?:not|n't|never|no|no longer|not really)\b.{0,32}\b(?:create|produce|add|yield)?\b.{0,32}\b(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observations?|verdict)\b",
        r"\b(?:later|future|next|additional)\s+rounds?\b.{0,48}\b(?:create|produce|add|yield)\b.{0,24}\bno\s+(?:new|additional)\s+(?:evidence|proof|artifact|handoff|observation|verdict)\b",
        r"\b(?:stable|existing)?\s*benchmark\b.{0,48}\b(?:fully|completely|already)\s+(?:captures|covers|expresses)\b",
        r"\b(?:benchmark[- ]only|benchmark only|stable benchmark|existing benchmark|simple benchmark)\b.{0,48}\b(?:is|was)?\s*(?:enough|sufficient)\b",
        r"\bbenchmark\b.{0,40}\b(?:whole|entire|only)\s+(?:acceptance|proof|validation|judgment)\b",
        r"\buse\s+the\s+benchmark\s+first\b.{0,64}\b(?:instead\s+of|rather\s+than|skip|do\s+not|don't)\b.{0,32}\b(?:loopora|loop)\b",
        r"\bjudgment\b.{0,48}\b(?:does\s+not|doesn't|need\s+not|won't)\s+survive\s+(?:one|this)\s+chat\b",
        r"一次\s*agent.{0,16}(?:人工\s*)?(?:review|审查|评审).{0,16}(?:足够|够了|即可|就行)",
        r"(?:一次|单轮|一轮).{0,16}(?:agent)?(?:执行|实现|处理|运行|pass|评审|对话|聊天).{0,16}(?:人工\s*)?(?:review|审查|评审)?.{0,16}(?:足够|够了|就行|即可)",
        r"(?:直接)?(?:聊天|对话).{0,16}(?:足够|够了|就行|即可)",
        r"(?:一次|本次)(?:聊天|对话).{0,16}(?:足够|够了|就行|即可)",
        r"(?:不会|没有|无需|无法|不能).{0,16}(?:产生|带来|增加)?.{0,8}(?:新证据|新证明|新产物|新交接|新裁决|新的证据|新的证明|新的产物|新的交接|新的观察)",
        r"(?:后续|下一轮|之后).{0,16}(?:不会|无法|不能|没有).{0,16}(?:证据|证明|产物|交接|观察)",
        r"(?:稳定|现有)?基准.{0,16}(?:完全覆盖|已经覆盖|足够表达|足够|够了|就行|即可)",
        r"只(?:跑|看)?基准.{0,16}(?:足够|够了|即可|就行)",
        r"不需要\s*loopora",
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
