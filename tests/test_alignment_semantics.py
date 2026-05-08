from __future__ import annotations

from loopora.alignment_semantics import text_mentions_loop_fit_contradiction


def test_loop_fit_contradiction_detector_covers_shared_readiness_and_bundle_cases() -> None:
    contradictory = [
        "One Agent pass plus human review would be sufficient here.",
        "Direct chat would be enough because the judgment is only needed once.",
        "A future round would not produce new evidence for this task.",
        "The existing benchmark already fully captures the judgment.",
        "一次 Agent 加人工 review 就足够了。",
    ]

    for text in contradictory:
        assert text_mentions_loop_fit_contradiction(text)


def test_loop_fit_contradiction_detector_respects_negated_antipatterns() -> None:
    assert not text_mentions_loop_fit_contradiction("One Agent pass plus human review is not enough because later rounds create new proof artifacts.")
    assert not text_mentions_loop_fit_contradiction("Do not treat direct chat as sufficient; the judgment needs to survive the run.")
