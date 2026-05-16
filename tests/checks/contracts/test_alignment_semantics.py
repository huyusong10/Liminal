from __future__ import annotations

from loopora.alignment_semantics import (
    loop_fit_governance_trace,
    text_mentions_loop_fit_contradiction,
    text_mentions_multiround_loopora_governance,
)


def test_loop_fit_contradiction_detector_covers_shared_readiness_and_bundle_cases() -> None:
    contradictory = [
        "One Agent pass plus human review would be sufficient here.",
        "Direct chat would be enough because the judgment is only needed once.",
        "A future round would not produce new evidence for this task.",
        "The existing benchmark already fully captures the judgment.",
        "The stable proof harness already fully captures the judgment.",
        "The contract tests are enough for this task.",
        "This is a one-off task; no Loopora loop is needed.",
        "There is no need for a Loopora loop here; just answer directly.",
        "We do not need a loop for this task.",
        "A single code review should suffice.",
        "One manual review should be sufficient.",
        "I only need a quick answer once.",
        "A direct answer is enough; no future iteration will add proof.",
        "Just fix it once and I will review it manually.",
        "一次 Agent 加人工 review 就足够了。",
        "这是一次性任务，不要长期循环。",
        "直接回答就够了。",
        "现有基准已经完全覆盖这次判断，直接跑基准就够了。",
        "现有契约测试已经完全覆盖这次判断，直接跑测试就够了。",
        "单次人工审查即可，不必开 Loop。",
        "不用 Loopora，直接让 Agent 做完再人工看一眼就行。",
        "这个任务跑一遍就行，不需要多轮。",
        "一轮就够了，不需要后续迭代。",
        "只要 Agent 做一遍，然后我看一下就可以。",
    ]

    for text in contradictory:
        assert text_mentions_loop_fit_contradiction(text)


def test_loop_fit_contradiction_detector_respects_negated_antipatterns() -> None:
    assert not text_mentions_loop_fit_contradiction(
        "One Agent pass plus human review is not enough because later rounds create new proof artifacts."
    )
    assert not text_mentions_loop_fit_contradiction(
        "Do not treat direct chat as sufficient; the judgment needs to survive the run."
    )
    assert not text_mentions_loop_fit_contradiction("Do not treat one-off handling as enough; later proof still matters.")
    assert not text_mentions_loop_fit_contradiction("The proof harness is not enough; GateKeeper must inspect later evidence.")
    assert not text_mentions_loop_fit_contradiction("不要把 no loop needed 当作可接受方案。")
    assert not text_mentions_loop_fit_contradiction("现有测试不够，后续轮次仍要补证据。")
    assert not text_mentions_loop_fit_contradiction("不是不用 Loopora，而是要先证明后续轮次会产生新证据。")
    assert not text_mentions_loop_fit_contradiction("不是一轮就够了；后续轮次必须继续补新证据。")


def test_loop_fit_governance_detector_supports_shared_lint_and_projection() -> None:
    text = (
        "One Agent pass must not be treated as enough. "
        "Future iterations keep new proof artifacts and GateKeeper judgment alive across the run."
    )

    assert text_mentions_multiround_loopora_governance(text)
    assert loop_fit_governance_trace(text) == [
        "One Agent pass must not be treated as enough.",
        "Future iterations keep new proof artifacts and GateKeeper judgment alive across the run.",
    ]


def test_loop_fit_governance_detector_rejects_generic_multiround_complexity() -> None:
    text = "This is a complex long-running project, so future rounds and iterations will continue the work."

    assert not text_mentions_multiround_loopora_governance(text)
    assert loop_fit_governance_trace(text) == []
