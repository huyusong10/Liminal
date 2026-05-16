from __future__ import annotations

import re
from pathlib import Path

import pytest

from loopora.bundles import (
    bundle_to_yaml,
    lint_alignment_bundle_generation_metadata,
    lint_alignment_bundle_generation_text,
    lint_alignment_bundle_semantics,
    load_bundle_text,
)
from loopora.executor_fake_payloads import alignment_bundle_yaml


def test_alignment_semantic_lint_requires_residual_risk(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec must include Residual Risk guidance" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_residual_risk = re.sub(
        r"\n    # Residual Risk\n\n    .+?(?=\n\n    # Role Notes)",
        "\n",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_residual_risk))

    assert "spec must include Residual Risk guidance" in issues


def test_alignment_semantic_lint_rejects_vague_residual_risk(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Residual Risk guidance must name accepted risk handling or fail closed" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_vague_residual_risk = re.sub(
        r"\n    # Residual Risk\n\n    .+?(?=\n\n    # Role Notes)",
        "\n    # Residual Risk\n\n    Some risk is fine.",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_vague_residual_risk))

    assert "spec Residual Risk guidance must name accepted risk handling or fail closed" in issues

    yaml_with_vague_chinese_residual_risk = re.sub(
        r"\n    # Residual Risk\n\n    .+?(?=\n\n    # Role Notes)",
        "\n    # Residual Risk\n\n    有些风险可以接受。",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_vague_chinese_residual_risk))

    assert "spec Residual Risk guidance must name accepted risk handling or fail closed" in issues


def test_alignment_semantic_lint_requires_summary_governance_story(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "collaboration_summary must explain the governance story" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_governance_summary = re.sub(
        r"collaboration_summary: \|\n(?:  .+\n)+loop:",
        'collaboration_summary: "Build the requested task."\nloop:',
        alignment_bundle_yaml(str(sample_workdir.resolve())),
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_governance_summary))

    assert "collaboration_summary must explain the governance story" in issues


def test_alignment_semantic_lint_requires_loop_fit_in_summary(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "collaboration_summary must explain why this task needs multi-round Loopora governance" not in lint_alignment_bundle_semantics(valid_bundle)

    bundle_without_loop_fit = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle_without_loop_fit["collaboration_summary"] = (
        "Project the working agreement into a spec task contract, role handoffs from Builder / Inspectors / GateKeeper, "
        "and a workflow that routes evidence before final judgment. Prefer a smaller proven flow over polished but "
        "unproven breadth, and let GateKeeper reject speed or surface completeness when evidence is weak. GateKeeper "
        "closes only when the spec, role evidence, and workflow handoffs prove the task is truly done."
    )

    issues = lint_alignment_bundle_semantics(bundle_without_loop_fit)

    assert "collaboration_summary must explain why this task needs multi-round Loopora governance" in issues


@pytest.mark.parametrize(
    "generic_task",
    [
        "Do the task.",
        "Ship the focused starter experience described only by the alignment agreement.",
    ],
)
def test_alignment_semantic_lint_requires_specific_task_contract(sample_workdir: Path, generic_task: str) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec Task must describe the concrete user-facing task" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_with_generic_task = re.sub(
        r"\n    # Task\n\n    .+?(?=\n\n    # Done When)",
        f"\n    # Task\n\n    {generic_task}",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_generic_task))

    assert "spec Task must describe the concrete user-facing task" in issues


def test_alignment_semantic_lint_requires_done_when_checks(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert "spec must include at least one Done When bullet" not in lint_alignment_bundle_semantics(valid_bundle)

    yaml_without_done_when = re.sub(
        r"\n    # Done When\n\n    - .+?(?=\n\n    # Guardrails)",
        "",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_done_when))

    assert "spec must include at least one Done When bullet" in issues


@pytest.mark.parametrize(
    ("section", "expected_issue"),
    [
        ("Success Surface", "spec must include at least one Success Surface bullet"),
        ("Fake Done", "spec must include at least one Fake Done bullet"),
        ("Evidence Preferences", "spec must include at least one Evidence Preferences bullet"),
    ],
)
def test_alignment_semantic_lint_requires_judgment_contract_sections(
    sample_workdir: Path,
    section: str,
    expected_issue: str,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert expected_issue not in lint_alignment_bundle_semantics(valid_bundle)

    heading_pattern = rf"\n    # {re.escape(section)}\n\n    - .+?(?=\n\n    # )"
    yaml_without_section = re.sub(
        heading_pattern,
        "",
        alignment_bundle_yaml(str(sample_workdir.resolve())),
        flags=re.DOTALL,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_section))

    assert expected_issue in issues


def test_alignment_semantic_lint_requires_evidence_bucket_projection(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("must project task verdict evidence" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_without_bucket_projection = (
        alignment_bundle_yaml(str(sample_workdir.resolve()))
        .replace(
            " Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, "
            "Unproven promised surfaces, Blocking fake-done findings, and visible Residual risk.",
            "",
        )
        .replace(
            "    - Final evidence should be bucketed as Proven, Weak, Unproven, Blocking, or Residual risk instead of flattened into one summary.\n",
            "",
        )
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_without_bucket_projection))

    assert ("alignment bundle must project task verdict evidence into Proven, Weak, Unproven, Blocking, and Residual risk buckets") in issues


def test_alignment_semantic_lint_does_not_count_metadata_as_evidence_bucket_projection(sample_workdir: Path) -> None:
    yaml_without_bucket_projection = (
        alignment_bundle_yaml(str(sample_workdir.resolve()))
        .replace(
            " Evidence projection must distinguish Proven direct run proof, Weak indirect evidence, "
            "Unproven promised surfaces, Blocking fake-done findings, and visible Residual risk.",
            "",
        )
        .replace(
            "    - Final evidence should be bucketed as Proven, Weak, Unproven, Blocking, or Residual risk instead of flattened into one summary.\n",
            "",
        )
    )
    bundle = load_bundle_text(yaml_without_bucket_projection)
    bucket_words = "Proven Weak Unproven Blocking Residual risk"
    bundle["metadata"]["description"] = bucket_words
    bundle["loop"]["name"] = bucket_words

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("alignment bundle must project task verdict evidence into Proven, Weak, Unproven, Blocking, and Residual risk buckets") in issues


def test_alignment_semantic_lint_requires_gatekeeper_completion_mode(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("must use gatekeeper completion_mode" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["loop"]["completion_mode"] = "rounds"
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Web alignment bundles must use gatekeeper completion_mode so task verdict is evidence-based, not only run lifecycle completion") in issues


def test_alignment_semantic_lint_requires_workflow_intent_to_explain_evidence_governance(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    expected_issue = "workflow.collaboration_intent must explain evidence flow, GateKeeper closure, and weak-evidence or fake-done exposure"
    assert expected_issue not in lint_alignment_bundle_semantics(valid_bundle)

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["collaboration_intent"] = (
        "Builder implements the billing refund path, Inspector reviews the approval journey, "
        "and GateKeeper gives the final decision for this task-specific sequence after each role completes its part."
    )

    issues = lint_alignment_bundle_semantics(bundle)

    assert expected_issue in issues


def test_alignment_generated_metadata_omits_lineage_fields(sample_workdir: Path) -> None:
    valid_yaml = alignment_bundle_yaml(str(sample_workdir.resolve()))
    assert lint_alignment_bundle_generation_text(valid_yaml) == []
    assert lint_alignment_bundle_generation_metadata(valid_yaml) == []

    lineage_yaml = valid_yaml.replace(
        '  description: "Bundle generated by the Web alignment flow."\n',
        '  description: "Bundle generated by the Web alignment flow."\n  source_bundle_id: "source_bundle_old"\n  revision: 2\n',
        1,
    )

    assert lint_alignment_bundle_generation_metadata(lineage_yaml) == [
        "Web alignment generated bundles must omit metadata.source_bundle_id and metadata.revision; "
        "source context is temporary and final bundles are standalone candidates"
    ]
    semantic_issues = lint_alignment_bundle_semantics(load_bundle_text(lineage_yaml))
    assert (
        "Web alignment bundles must not encode metadata.source_bundle_id; source context is temporary and final bundles are standalone candidates"
    ) in semantic_issues


def test_alignment_generated_bundle_text_must_be_raw_yaml(sample_workdir: Path) -> None:
    valid_yaml = alignment_bundle_yaml(str(sample_workdir.resolve()))
    yaml_with_internal_fence = valid_yaml.replace(
        "Leave concrete handoffs and evidence references for downstream review.",
        "Leave concrete handoffs and evidence references for downstream review.\n\n      ```text\n      internal example\n      ```",
        1,
    )

    fenced_issues = lint_alignment_bundle_generation_text(f"```yaml\n{valid_yaml}```")
    prefixed_issues = lint_alignment_bundle_generation_text("Here is the bundle:\n" + valid_yaml)
    comment_prefixed_issues = lint_alignment_bundle_generation_text("# Here is the bundle\n" + valid_yaml)

    assert lint_alignment_bundle_generation_text(yaml_with_internal_fence) == []
    assert "Web alignment generated bundle_yaml must be one raw YAML document, not markdown-fenced output" in fenced_issues
    assert "Web alignment generated bundle_yaml must start with version: 1" in fenced_issues
    assert prefixed_issues == ["Web alignment generated bundle_yaml must start with version: 1"]
    assert comment_prefixed_issues == ["Web alignment generated bundle_yaml must start with version: 1"]
def test_alignment_semantic_lint_rejects_personality_memory_bundle(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("personality memory" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    valid_bundle["collaboration_summary"] = (
        "This bundle maps the user's permanent preference memory into spec, roles, and workflow "
        "so Builder always follows the user's global personality, Inspector gathers browser "
        "and test evidence, and GateKeeper signs off only after that evidence supports the "
        "preferred behavior."
    )
    issues = lint_alignment_bundle_semantics(valid_bundle)

    assert "alignment bundle must stay task-scoped, not personality memory or global preferences" in issues


@pytest.mark.parametrize(
    "antipattern_phrase",
    [
        "prompt pack",
        "role zoo",
        "loop script",
        "benchmark grinder",
        "chat wrapper",
    ],
)
def test_alignment_semantic_lint_rejects_named_loopora_antipatterns(
    sample_workdir: Path,
    antipattern_phrase: str,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("prompt pack" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    valid_bundle["collaboration_summary"] = (
        f"This {antipattern_phrase} maps the user's task into spec, roles, and workflow. "
        "Builder follows the role prose, Inspector gathers browser and test evidence, "
        "and GateKeeper signs off only after proof supports the promised task surface."
    )
    issues = lint_alignment_bundle_semantics(valid_bundle)

    assert ("alignment bundle must not present prompt pack, role zoo, loop script, benchmark grinder, or chat wrapper as Loopora governance") in issues


def test_alignment_semantic_lint_rejects_duplicate_role_responsibilities(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("distinct task evidence responsibilities" in issue for issue in lint_alignment_bundle_semantics(bundle))

    roles_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    roles_by_key["contract-inspector"]["prompt_markdown"] = roles_by_key["evidence-inspector"]["prompt_markdown"]
    roles_by_key["contract-inspector"]["posture_notes"] = roles_by_key["evidence-inspector"]["posture_notes"]
    for step in bundle["workflow"]["steps"]:
        step.pop("parallel_group", None)

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("role_definitions must have distinct task evidence responsibilities: contract-inspector, evidence-inspector") in issues


def test_alignment_semantic_lint_allows_antipatterns_named_as_fake_done_risks(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += (
        " The spec also avoids prompt pack and personality memory failures by keeping the judgment task-scoped and evidence-owned."
    )

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("prompt pack" in issue for issue in issues)
    assert not any("personality memory" in issue for issue in issues)


def test_alignment_semantic_lint_rejects_final_bundle_loop_fit_contradictions(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("single pass" in issue for issue in lint_alignment_bundle_semantics(bundle))

    bundle["collaboration_summary"] += " A single Agent pass is sufficient, and direct chat would be enough for this task."
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " 这个任务跑一遍就行，不需要多轮。"
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " 一次 Agent 执行加人工 review 已经足够，后续不会产生新证据。"
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " One Agent pass plus human review would be sufficient here."
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " A future round would not produce new evidence for this task."
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " 不用 Loopora，直接让 Agent 做完再人工看一眼就行。"
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " This is a one-off task; no Loopora loop is needed."
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " 这是一次性任务，不要长期循环，直接处理完即可。"
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues

    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] += " The stable proof harness already fully captures the judgment."
    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "alignment bundle must not claim a single pass, direct chat / direct answer, one-off task handling, no-new-evidence round, or benchmark/test-harness-only path is sufficient while compiling a Loop"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_read_upstream_handoffs(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review step must name upstream handoffs" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_missing_parallel_handoff_input = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'handoffs_from: ["builder_step"]',
        "handoffs_from: []",
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_missing_parallel_handoff_input))

    assert ("parallel review step must name upstream handoffs in inputs.handoffs_from: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_review_after_builder_to_read_builder_inputs(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    assert not any("review step after Builder" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["contract_inspection_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("review step after Builder must name a Builder handoff in inputs.handoffs_from: contract_inspection_step") in issues
    assert ("review step after Builder must query Builder evidence in inputs.evidence_query: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_custom_after_builder_to_read_builder_inputs(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"].append("custom")
    assert not any("review step after Builder" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["contract_inspection_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("review step after Builder must name a Builder handoff in inputs.handoffs_from: contract_inspection_step") in issues
    assert ("review step after Builder must query Builder evidence in inputs.evidence_query: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_parallel_review_to_read_same_upstream_handoff(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("same upstream handoffs" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["evidence_inspection_step"]["inputs"]["handoffs_from"] = ["contract_inspection_step"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("parallel review steps must read the same upstream handoffs: contract_inspection_step, evidence_inspection_step") in issues


def test_alignment_semantic_lint_requires_parallel_review_to_query_builder_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review step must query Builder evidence" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"]["inputs"].pop("evidence_query")
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("parallel review step must query Builder evidence in inputs.evidence_query: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_parallel_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review step must declare inputs.iteration_memory" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"]["inputs"].pop("iteration_memory")

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("parallel review step must declare inputs.iteration_memory so cross-iteration evidence flow is explicit: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_parallel_review_summary_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"]["inputs"]["iteration_memory"] = "same_step"

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "parallel review step must use inputs.iteration_memory=summary_only so previous GateKeeper verdict stays visible: contract_inspection_step"
    ) in issues


def test_alignment_semantic_lint_requires_parallel_review_to_use_distinct_role_definitions(
    sample_workdir: Path,
) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("distinct role_definition_key" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_shared_parallel_role_definition = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'role_definition_key: "contract-inspector"',
        'role_definition_key: "evidence-inspector"',
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_shared_parallel_role_definition))

    assert ("parallel review steps must use distinct role_definition_key values: contract_inspection_step, evidence_inspection_step") in issues


def test_alignment_semantic_lint_requires_parallel_review_to_have_distinct_posture(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("responsibility-specific prompt and posture" in issue for issue in lint_alignment_bundle_semantics(bundle))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["name"] = role_by_key["evidence-inspector"]["name"]
    role_by_key["contract-inspector"]["description"] = role_by_key["evidence-inspector"]["description"]
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["evidence-inspector"]["prompt_markdown"]
    role_by_key["contract-inspector"]["posture_notes"] = role_by_key["evidence-inspector"]["posture_notes"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("parallel review role_definitions must have responsibility-specific prompt and posture: contract-inspector, evidence-inspector") in issues


def test_alignment_semantic_lint_rejects_generic_role_names(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("task-specific role name" in issue for issue in lint_alignment_bundle_semantics(bundle))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["name"] = "Inspector 1"
    role_by_key["evidence-inspector"]["name"] = "Inspector 2"
    issues = lint_alignment_bundle_semantics(bundle)

    assert "role_definition contract-inspector must use a task-specific role name" in issues
    assert "role_definition evidence-inspector must use a task-specific role name" in issues
def test_alignment_semantic_lint_uses_graph_contract_for_custom_review_roles(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["archetype"] = "custom"
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["contract-inspector"]["prompt_markdown"].replace(
        "archetype: inspector", "archetype: custom"
    )

    issues = lint_alignment_bundle_semantics(bundle)

    assert not any("Custom read-only specialized review" in issue for issue in issues)
    assert "finishing GateKeeper after review must query review evidence in inputs.evidence_query: custom" in issues


def _add_repair_guide_flow(bundle: dict) -> dict:
    bundle["role_definitions"].append(
        {
            "key": "repair-guide",
            "name": "Repair Direction Guide",
            "description": "Turns inspection evidence into a focused repair direction.",
            "archetype": "guide",
            "prompt_ref": "repair-guide.md",
            "prompt_markdown": """---
version: 1
archetype: guide
---

Use the inspection evidence to narrow the next Builder step. Leave a handoff that names the repair direction, the evidence behind it, and the scope that must not expand.""",
            "posture_notes": "Narrow the repair target from review evidence instead of offering broad advice.",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "command_cli": "",
            "command_args_text": "",
            "model": "",
            "reasoning_effort": "",
        }
    )
    bundle["workflow"]["roles"].append({"id": "repair_guide", "role_definition_key": "repair-guide"})
    gatekeeper_step = bundle["workflow"]["steps"][-1]
    bundle["workflow"]["steps"].insert(
        -1,
        {
            "id": "repair_guide_step",
            "role_id": "repair_guide",
            "inputs": {
                "handoffs_from": ["contract_inspection_step", "evidence_inspection_step"],
                "evidence_query": {"archetypes": ["inspector"], "limit": 12},
                "iteration_memory": "summary_only",
            },
            "on_pass": "continue",
        },
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("repair_guide_step")
    gatekeeper_step["inputs"]["evidence_query"]["archetypes"].append("guide")
    return bundle
def test_alignment_semantic_lint_requires_guide_after_review_to_read_review_inputs(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    assert not any("Guide step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["repair_guide_step"]["inputs"]["handoffs_from"] = ["builder_step"]
    steps_by_id["repair_guide_step"]["inputs"].pop("evidence_query")

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Guide step after review must include review handoffs in inputs.handoffs_from: repair_guide_step") in issues
    assert ("Guide step after review must query review evidence in inputs.evidence_query: inspector") in issues


def _make_contract_inspector_custom_review(bundle: dict) -> None:
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    contract_role = role_by_key["contract-inspector"]
    contract_role["archetype"] = "custom"
    contract_role["prompt_markdown"] = contract_role["prompt_markdown"].replace(
        "archetype: inspector",
        "archetype: custom",
    )
    contract_role["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for contract evidence; do not edit files, and leave a focused handoff."
    )
    contract_role["posture_notes"] += " As a low-permission Custom reviewer, provide only specialized contract review signal."


def test_alignment_semantic_lint_treats_custom_as_review_before_builder(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_custom_review_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_custom_review_step"],
        "iteration_memory": "summary_only",
    }
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"].append("custom")
    assert not any("Builder step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["builder_step"]["inputs"] = {"handoffs_from": []}
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after review must include review handoffs in inputs.handoffs_from: builder_step") in issues
    assert ("Builder step after review must declare inputs.iteration_memory so evidence-first repair does not rely on ambient context: builder_step") in issues


def test_alignment_semantic_lint_treats_custom_as_review_before_gatekeeper(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    _make_contract_inspector_custom_review(bundle)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["evidence_inspection_step"]
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder", "inspector"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("finishing GateKeeper after review must include review handoffs in inputs.handoffs_from: contract_inspection_step") in issues
    assert ("finishing GateKeeper after review must query review evidence in inputs.evidence_query: custom") in issues


def test_alignment_semantic_lint_requires_guide_after_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["repair_guide_step"]["inputs"].pop("iteration_memory")

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Guide step after review must declare inputs.iteration_memory so repair guidance can use prior iteration evidence explicitly: repair_guide_step"
    ) in issues


def test_alignment_semantic_lint_requires_guide_after_review_summary_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["repair_guide_step"]["inputs"]["iteration_memory"] = "same_role"

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "Guide step after review must use inputs.iteration_memory=summary_only so previous GateKeeper blockers and residual risks stay visible: repair_guide_step"
    ) in issues


def test_alignment_semantic_lint_requires_builder_after_guide_to_read_guide_handoff(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    gatekeeper_step = bundle["workflow"]["steps"].pop()
    bundle["workflow"]["steps"].append(
        {
            "id": "builder_repair_step",
            "role_id": "builder",
            "inputs": {
                "handoffs_from": ["builder_step"],
                "iteration_memory": "same_step",
            },
            "on_pass": "continue",
        }
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("builder_repair_step")
    bundle["workflow"]["steps"].append(gatekeeper_step)

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after Guide must name a Guide handoff in inputs.handoffs_from: builder_repair_step") in issues


def test_alignment_semantic_lint_requires_builder_after_guide_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    gatekeeper_step = bundle["workflow"]["steps"].pop()
    bundle["workflow"]["steps"].append(
        {
            "id": "builder_repair_step",
            "role_id": "builder",
            "inputs": {
                "handoffs_from": ["repair_guide_step"],
            },
            "on_pass": "continue",
        }
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("builder_repair_step")
    bundle["workflow"]["steps"].append(gatekeeper_step)

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after Guide must declare inputs.iteration_memory so repair pass does not rely on ambient context: builder_repair_step") in issues


def test_alignment_semantic_lint_requires_builder_after_guide_summary_memory(
    sample_workdir: Path,
) -> None:
    bundle = _add_repair_guide_flow(load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve()))))
    gatekeeper_step = bundle["workflow"]["steps"].pop()
    bundle["workflow"]["steps"].append(
        {
            "id": "builder_repair_step",
            "role_id": "builder",
            "inputs": {
                "handoffs_from": ["repair_guide_step"],
                "iteration_memory": "same_step",
            },
            "on_pass": "continue",
        }
    )
    gatekeeper_step["inputs"]["handoffs_from"].append("builder_repair_step")
    bundle["workflow"]["steps"].append(gatekeeper_step)

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after Guide must use inputs.iteration_memory=summary_only so previous GateKeeper verdict stays visible: builder_repair_step") in issues


def test_alignment_semantic_lint_requires_builder_after_review_to_read_review_handoff(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_inspection_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_inspection_step"],
        "iteration_memory": "summary_only",
    }
    assert not any("Builder step after review" in issue for issue in lint_alignment_bundle_semantics(bundle))

    steps_by_id["builder_step"]["inputs"]["handoffs_from"] = []
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after review must include review handoffs in inputs.handoffs_from: builder_step") in issues


def test_alignment_semantic_lint_requires_builder_after_review_iteration_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_inspection_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_inspection_step"],
    }

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after review must declare inputs.iteration_memory so evidence-first repair does not rely on ambient context: builder_step") in issues


def test_alignment_semantic_lint_requires_builder_after_review_summary_memory(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["workflow"]["steps"].insert(
        0,
        {
            "id": "preflight_inspection_step",
            "role_id": "contract_inspector",
            "on_pass": "continue",
        },
    )
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["builder_step"]["inputs"] = {
        "handoffs_from": ["preflight_inspection_step"],
        "iteration_memory": "same_step",
    }

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("Builder step after review must use inputs.iteration_memory=summary_only so previous GateKeeper repair direction stays visible: builder_step") in issues


def test_alignment_semantic_lint_requires_gatekeeper_to_read_parallel_handoffs(sample_workdir: Path) -> None:
    valid_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("parallel review handoff" in issue for issue in lint_alignment_bundle_semantics(valid_bundle))

    yaml_with_missing_parallel_handoff = alignment_bundle_yaml(str(sample_workdir.resolve())).replace(
        'handoffs_from: ["contract_inspection_step", "evidence_inspection_step"]',
        'handoffs_from: ["evidence_inspection_step"]',
        1,
    )
    issues = lint_alignment_bundle_semantics(load_bundle_text(yaml_with_missing_parallel_handoff))

    assert ("GateKeeper step must include every parallel review handoff in inputs.handoffs_from: contract_inspection_step") in issues


def test_alignment_semantic_lint_requires_finishing_gatekeeper_to_read_handoff_and_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("finishing GateKeeper step" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"].pop("inputs")
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("finishing GateKeeper step must name upstream handoffs in inputs.handoffs_from: gatekeeper_step") in issues
    assert ("finishing GateKeeper step must query upstream evidence in inputs.evidence_query: gatekeeper_step") in issues


def test_alignment_semantic_lint_requires_gatekeeper_after_review_to_read_review_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("GateKeeper after review" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["contract_inspection_step"].pop("parallel_group")
    steps_by_id["evidence_inspection_step"].pop("parallel_group")
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["builder_step"]
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert (
        "finishing GateKeeper after review must include review handoffs in inputs.handoffs_from: contract_inspection_step, evidence_inspection_step"
    ) in issues
    assert ("finishing GateKeeper after review must query review evidence in inputs.evidence_query: inspector") in issues


def test_alignment_semantic_lint_requires_gatekeeper_to_query_builder_and_inspector_evidence(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    assert not any("GateKeeper step must query Builder and parallel review evidence" in issue for issue in lint_alignment_bundle_semantics(bundle))
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["inspector"]
    issues = lint_alignment_bundle_semantics(bundle)

    assert ("GateKeeper step must query Builder and parallel review evidence in inputs.evidence_query: builder") in issues


def test_alignment_semantic_lint_gatekeeper_fan_in_counts_parallel_custom_review_steps(
    sample_workdir: Path,
) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["contract-inspector"]["archetype"] = "custom"
    role_by_key["evidence-inspector"]["archetype"] = "custom"
    role_by_key["contract-inspector"]["prompt_markdown"] = role_by_key["contract-inspector"]["prompt_markdown"].replace(
        "archetype: inspector", "archetype: custom"
    )
    role_by_key["evidence-inspector"]["prompt_markdown"] = role_by_key["evidence-inspector"]["prompt_markdown"].replace(
        "archetype: inspector", "archetype: custom"
    )
    role_by_key["contract-inspector"]["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for contract evidence; do not edit files, and leave a focused handoff."
    )
    role_by_key["contract-inspector"]["posture_notes"] += " As a low-permission Custom reviewer, provide only specialized review signal."
    role_by_key["evidence-inspector"]["prompt_markdown"] += (
        "\n\n      Act as a read-only specialized Custom reviewer for evidence quality; do not edit files, and leave a focused handoff."
    )
    role_by_key["evidence-inspector"]["posture_notes"] += " As a low-permission Custom reviewer, provide only specialized evidence signal."
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = []
    steps_by_id["gatekeeper_step"]["inputs"]["evidence_query"]["archetypes"] = ["builder"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("GateKeeper step must include every parallel review handoff in inputs.handoffs_from: contract_inspection_step, evidence_inspection_step") in issues
    assert ("GateKeeper step must query Builder and parallel review evidence in inputs.evidence_query: custom") in issues


def _long_chain_multi_builder_bundle(workdir: Path) -> dict:
    bundle = load_bundle_text(alignment_bundle_yaml(str(workdir.resolve())))
    role_defaults = {
        "executor_kind": "codex",
        "executor_mode": "preset",
        "command_cli": "",
        "command_args_text": "",
        "model": "",
        "reasoning_effort": "",
    }

    def role(
        key: str,
        name: str,
        archetype: str,
        body: str,
        posture: str,
    ) -> dict:
        return {
            "key": key,
            "name": name,
            "description": body,
            "archetype": archetype,
            "prompt_ref": f"{key}.md",
            "prompt_markdown": f"""---
version: 1
archetype: {archetype}
---

{body} Leave a handoff that names Proven, Weak, Unproven, Blocking, and Residual risk evidence for downstream roles.""",
            "posture_notes": posture,
            **role_defaults,
        }

    bundle["metadata"]["name"] = "Search Long-Chain Bundle"
    bundle["loop"]["name"] = "Search Long-Chain Bundle"
    bundle["collaboration_summary"] = (
        "Compile the search refactor into a long-chain workflow because query rewriting, retrieval, "
        "ranking, regression review, and evidence hardening each create distinct artifacts, handoffs, "
        "and proof targets. Future iterations stay anchored to these phase contracts as new evidence "
        "and blockers appear. GateKeeper must judge from phase evidence rather than only the final "
        "Builder story, separating Proven, Weak, Unproven, Blocking, and Residual risk claims."
    )
    bundle["role_definitions"] = [
        role(
            "baseline-inspector",
            "Search Baseline Inspector",
            "inspector",
            "Inspect the current search behavior and pin the first reproducible baseline before implementation.",
            "Treat unsupported baseline claims as Unproven and identify the first proof path the Builders must preserve.",
        ),
        role(
            "query-builder",
            "Query Rewrite Builder",
            "builder",
            "Implement only the query rewrite phase and preserve a narrow evidence handoff for retrieval work.",
            "Move query rewrite behavior toward Proven without changing retrieval or ranking standards silently.",
        ),
        role(
            "retrieval-builder",
            "Retrieval Builder",
            "builder",
            "Implement only the retrieval phase from the query handoff and leave concrete retrieval evidence.",
            "Preserve the query phase contract while producing a distinct retrieval artifact and proof target.",
        ),
        role(
            "ranking-builder",
            "Ranking Builder",
            "builder",
            "Implement only the ranking phase from retrieval evidence and avoid masking recall regressions.",
            "Prefer maintainable ranking progress over metric theater; expose weak proof instead of broad claims.",
        ),
        role(
            "regression-inspector",
            "Search Regression Inspector",
            "inspector",
            "Review query, retrieval, and ranking handoffs against the baseline and search regressions.",
            "Mark regressions as Blocking, thin evidence as Weak, and unsupported phase claims as Unproven.",
        ),
        role(
            "evidence-hardening-builder",
            "Evidence Hardening Builder",
            "builder",
            "Add only missing proof or harness support requested by regression review.",
            "Do not widen product scope; turn review gaps into durable evidence that GateKeeper can inspect.",
        ),
        role(
            "search-gatekeeper",
            "Search Evidence GateKeeper",
            "gatekeeper",
            "Judge the long-chain search refactor from baseline, phase, regression, and evidence-hardening handoffs.",
            "Finish only when critical phase claims are Proven or acceptable Residual risk, and fail closed on Blocking gaps.",
        ),
    ]
    bundle["workflow"] = {
        "version": 1,
        "preset": "",
        "collaboration_intent": (
            "Use a long-chain phase workflow because the search task has distinct query, retrieval, ranking, "
            "regression, and evidence-hardening proof targets. Each Builder owns one phase handoff; "
            "Regression Inspector checks phase evidence before Evidence Hardening Builder repairs proof gaps; "
            "GateKeeper fans in baseline, regression, and final evidence so weak evidence, drift, or fake done "
            "surface before closure."
        ),
        "roles": [
            {"id": "baseline_inspector", "role_definition_key": "baseline-inspector"},
            {"id": "query_builder", "role_definition_key": "query-builder"},
            {"id": "retrieval_builder", "role_definition_key": "retrieval-builder"},
            {"id": "ranking_builder", "role_definition_key": "ranking-builder"},
            {"id": "regression_inspector", "role_definition_key": "regression-inspector"},
            {"id": "evidence_hardening_builder", "role_definition_key": "evidence-hardening-builder"},
            {"id": "gatekeeper", "role_definition_key": "search-gatekeeper"},
        ],
        "steps": [
            {"id": "baseline_inspection_step", "role_id": "baseline_inspector", "on_pass": "continue"},
            {
                "id": "query_builder_step",
                "role_id": "query_builder",
                "inputs": {"handoffs_from": ["baseline_inspection_step"], "iteration_memory": "summary_only"},
                "on_pass": "continue",
            },
            {
                "id": "retrieval_builder_step",
                "role_id": "retrieval_builder",
                "inputs": {"handoffs_from": ["query_builder_step"], "iteration_memory": "same_step"},
                "on_pass": "continue",
            },
            {
                "id": "ranking_builder_step",
                "role_id": "ranking_builder",
                "inputs": {"handoffs_from": ["retrieval_builder_step"], "iteration_memory": "same_step"},
                "on_pass": "continue",
            },
            {
                "id": "regression_inspection_step",
                "role_id": "regression_inspector",
                "inputs": {
                    "handoffs_from": [
                        "query_builder_step",
                        "retrieval_builder_step",
                        "ranking_builder_step",
                    ],
                    "evidence_query": {"archetypes": ["builder"], "limit": 30},
                    "iteration_memory": "summary_only",
                },
                "on_pass": "continue",
            },
            {
                "id": "evidence_hardening_builder_step",
                "role_id": "evidence_hardening_builder",
                "inputs": {"handoffs_from": ["regression_inspection_step"], "iteration_memory": "summary_only"},
                "on_pass": "continue",
            },
            {
                "id": "gatekeeper_step",
                "role_id": "gatekeeper",
                "inputs": {
                    "handoffs_from": [
                        "baseline_inspection_step",
                        "regression_inspection_step",
                        "evidence_hardening_builder_step",
                    ],
                    "evidence_query": {"archetypes": ["builder", "inspector"], "limit": 40},
                },
                "on_pass": "finish_run",
            },
        ],
    }
    return load_bundle_text(bundle_to_yaml(bundle))


def test_alignment_semantic_lint_accepts_long_chain_multi_builder_workflows(
    sample_workdir: Path,
) -> None:
    bundle = _long_chain_multi_builder_bundle(sample_workdir)

    issues = lint_alignment_bundle_semantics(bundle)

    assert issues == []


def test_alignment_semantic_lint_requires_long_chain_gatekeeper_to_read_phase_handoffs(
    sample_workdir: Path,
) -> None:
    bundle = _long_chain_multi_builder_bundle(sample_workdir)
    steps_by_id = {step["id"]: step for step in bundle["workflow"]["steps"]}
    steps_by_id["gatekeeper_step"]["inputs"]["handoffs_from"] = ["evidence_hardening_builder_step"]

    issues = lint_alignment_bundle_semantics(bundle)

    assert ("long-chain GateKeeper must include an earlier phase, review, or Guide handoff in inputs.handoffs_from: gatekeeper_step") in issues
