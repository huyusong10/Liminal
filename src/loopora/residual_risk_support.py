from __future__ import annotations

import re

NO_RESIDUAL_RISK_MARKERS = {
    "none",
    "n/a",
    "na",
    "no residual risk",
    "no blocking residual risk",
    "no blocking residual risk was reported by gatekeeper",
    "no meaningful residual risk",
    "无",
    "无残余风险",
    "无明显残余风险",
    "无重大残余风险",
    "无有意义残余风险",
    "没有残余风险",
    "没有明显残余风险",
    "没有阻断残余风险",
    "没有重大残余风险",
    "没有有意义的残余风险",
}

VAGUE_RESIDUAL_RISK_MARKERS = {
    "some risk remains",
    "some residual risk remains",
    "residual risk remains",
    "risks remain",
    "there is residual risk",
    "remaining risk",
    "some risk is fine",
    "有残余风险",
    "仍有风险",
    "存在风险",
    "存在残余风险",
    "还有风险",
    "有些风险",
}

RESIDUAL_RISK_MANAGEMENT_MARKERS = {
    "accepted",
    "assigned",
    "assignee",
    "block closure",
    "blocks closure",
    "deferred",
    "documented",
    "explicitly name",
    "explicitly named",
    "fail closed",
    "follow-up",
    "followup",
    "handoff",
    "issue",
    "mitigation",
    "monitor",
    "must block",
    "next",
    "owned",
    "owner",
    "planned",
    "review",
    "revisit",
    "ticket",
    "tracked",
    "tracking",
    "人工",
    "具名",
    "后续",
    "复核",
    "审查",
    "工单",
    "已接受",
    "手动",
    "接管",
    "接受",
    "方案",
    "明确命名",
    "监控",
    "计划",
    "记录",
    "负责人",
    "负责",
    "处理",
    "失败关闭",
    "跟踪",
    "跟进",
    "追踪",
    "必须阻断",
    "显式声明",
}

RESIDUAL_RISK_EXCEPTION_MARKERS = {
    " except ",
    " but ",
    " however ",
    " other than ",
    " aside from ",
    " besides ",
    " though ",
    " unless ",
    "，但",
    "，但是",
    "，不过",
    "；但",
    "；但是",
    "；不过",
    " 但",
    " 但是",
    " 不过",
    "除了",
    "除 ",
    "之外",
    "仍有",
    "还有",
}

UNMANAGED_RESIDUAL_RISK_DETAIL_PATTERNS = (
    r"\bownerless\b",
    r"\bunowned\b",
    r"\b(?:no|without|missing)\s+(?:owner|assignee|follow[- ]?up|followup|ticket|tracking|mitigation|acceptance path)\b",
    r"\b(?:owner|assignee|follow[- ]?up|followup|ticket|tracking|mitigation|acceptance path)\s+(?:missing|absent|unknown)\b",
    r"无人(?:接管|负责|跟进)",
    r"没人(?:接管|负责|跟进)",
    r"没有(?:接管|负责人|负责|后续|跟进)",
    r"未(?:接管|分配|跟进)",
    r"无(?:负责人|后续|跟进)",
)

VAGUE_RESIDUAL_RISK_ACCEPTANCE_PATTERNS = (
    r"\b(?:some|any|residual|remaining)\s+(?:residual\s+)?risks?\b.{0,40}\b(?:accepted|acceptable|allowed|fine|ok|okay)\b",
    r"\b(?:accepted|acceptable|allowed|fine|ok|okay)\b.{0,40}\b(?:some|any|residual|remaining)\s+(?:residual\s+)?risks?\b",
    r"(?:有些|一些|部分)?(?:残余|剩余)?风险.{0,16}(?:可以)?(?:接受|可接受|允许)",
    r"(?:接受|可接受|允许).{0,16}(?:有些|一些|部分)?(?:残余|剩余)?风险",
)

RESIDUAL_RISK_HANDOFF_MARKERS = {
    "assigned",
    "assignee",
    "follow-up",
    "followup",
    "handoff",
    "issue",
    "mitigation",
    "monitor",
    "next",
    "owned",
    "owner",
    "planned",
    "revisit",
    "ticket",
    "tracked",
    "tracking",
    "具名",
    "后续",
    "复核",
    "工单",
    "接管",
    "方案",
    "明确命名",
    "监控",
    "计划",
    "记录",
    "负责人",
    "负责",
    "处理",
    "跟踪",
    "跟进",
    "追踪",
    "显式声明",
}


def residual_risk_is_meaningful(value: object) -> bool:
    if not isinstance(value, str):
        return False
    normalized = _normalized_residual_risk_text(value)
    if not normalized:
        return False
    if normalized in NO_RESIDUAL_RISK_MARKERS:
        return False
    if normalized.startswith("no ") and "residual risk" in normalized:
        return _has_residual_risk_exception(normalized)
    return True


def residual_risk_is_managed(value: object) -> bool:
    if not residual_risk_is_meaningful(value):
        return False
    normalized = _normalized_residual_risk_text(value)
    if normalized in VAGUE_RESIDUAL_RISK_MARKERS:
        return False
    if _has_vague_residual_risk_acceptance(normalized) and not _has_residual_risk_handoff_path(normalized):
        return False
    if _has_unmanaged_residual_risk_detail(normalized) and not _has_fail_closed_residual_risk_management(normalized):
        return False
    return any(_management_marker_is_present(marker, normalized) for marker in RESIDUAL_RISK_MANAGEMENT_MARKERS)


def residual_risk_is_unmanaged(value: object) -> bool:
    return residual_risk_is_meaningful(value) and not residual_risk_is_managed(value)


def residual_risk_policy_disallows_acceptance(value: object) -> bool:
    normalized = _normalized_residual_risk_text(value)
    if not normalized:
        return False
    return any(
        _regex_search(pattern, normalized)
        for pattern in (
            r"\b(?:no|none|zero)\b.{0,80}\b(?:accepted|acceptable|allowed|carried)?\s*residual risks?\b",
            r"\b(?:no|none|zero)\b.{0,80}\bresidual risks?\b.{0,80}\b(?:accepted|acceptable|allowed|carried)\b",
            r"\b(?:do not|don't|cannot|can't|must not|never)\b.{0,80}\baccept\b.{0,80}\bresidual risks?\b",
            r"\bresidual risks?\b.{0,80}\b(?:not accepted|not acceptable|cannot be accepted|must not be accepted)\b",
            r"(?:不接受|不能接受|不可接受|不允许).{0,30}残余风险",
            r"残余风险.{0,30}(?:不接受|不能接受|不可接受|不允许)",
        )
    )


def _normalized_residual_risk_text(value: object) -> str:
    return " ".join(str(value or "").split()).lower().strip(" .。")


def _has_residual_risk_exception(normalized: str) -> bool:
    padded = f" {normalized} "
    return any(marker in padded for marker in RESIDUAL_RISK_EXCEPTION_MARKERS)


def _regex_search(pattern: str, value: str) -> bool:
    return bool(re.search(pattern, value, re.I))


def _has_unmanaged_residual_risk_detail(normalized: str) -> bool:
    return any(_regex_search(pattern, normalized) for pattern in UNMANAGED_RESIDUAL_RISK_DETAIL_PATTERNS)


def _has_vague_residual_risk_acceptance(normalized: str) -> bool:
    return any(_regex_search(pattern, normalized) for pattern in VAGUE_RESIDUAL_RISK_ACCEPTANCE_PATTERNS)


def _has_residual_risk_handoff_path(normalized: str) -> bool:
    return _has_fail_closed_residual_risk_management(normalized) or any(
        _management_marker_is_present(marker, normalized) for marker in RESIDUAL_RISK_HANDOFF_MARKERS
    )


def _has_fail_closed_residual_risk_management(normalized: str) -> bool:
    return any(
        _regex_search(pattern, normalized)
        for pattern in (
            r"\bfail(?:s|ed|ing)? closed\b",
            r"\bmust block\b",
            r"\bmust fail\b",
            r"\bblocks? closure\b",
            r"失败关闭",
            r"必须阻断",
            r"必须失败",
        )
    )


def _management_marker_is_present(marker: str, normalized: str) -> bool:
    if marker.isascii() and re.search(r"[a-z]", marker):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", normalized))
    return marker in normalized
