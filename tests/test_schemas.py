from __future__ import annotations

from pathlib import Path

from loopora.context_flow import (
    EVIDENCE_ITEM_SCHEMA,
    ITERATION_SUMMARY_SCHEMA,
    LATEST_STATE_SCHEMA,
    STEP_CONTEXT_PACKET_SCHEMA,
    STEP_HANDOFF_SCHEMA,
    output_contract_prompt,
)
from loopora.service import (
    CHALLENGER_SCHEMA,
    CHECK_PLANNER_SCHEMA,
    GENERATOR_SCHEMA,
    ServiceRunPromptMixin,
    TESTER_SCHEMA,
    VERIFIER_SCHEMA,
)
from loopora.service_prompts import CUSTOM_SCHEMA


class PromptHarness(ServiceRunPromptMixin):
    def _is_bootstrap_workspace(self, _workdir: Path) -> bool:
        return False


def test_object_schemas_with_properties_are_strict_and_exhaustive() -> None:
    schemas = {
        "GENERATOR_SCHEMA": GENERATOR_SCHEMA,
        "CHECK_PLANNER_SCHEMA": CHECK_PLANNER_SCHEMA,
        "TESTER_SCHEMA": TESTER_SCHEMA,
        "VERIFIER_SCHEMA": VERIFIER_SCHEMA,
        "CHALLENGER_SCHEMA": CHALLENGER_SCHEMA,
        "CUSTOM_SCHEMA": CUSTOM_SCHEMA,
        "EVIDENCE_ITEM_SCHEMA": EVIDENCE_ITEM_SCHEMA,
        "STEP_CONTEXT_PACKET_SCHEMA": STEP_CONTEXT_PACKET_SCHEMA,
        "STEP_HANDOFF_SCHEMA": STEP_HANDOFF_SCHEMA,
        "ITERATION_SUMMARY_SCHEMA": ITERATION_SUMMARY_SCHEMA,
        "LATEST_STATE_SCHEMA": LATEST_STATE_SCHEMA,
    }

    for schema_name, schema in schemas.items():
        for path, issue in _find_schema_issues(schema):
            raise AssertionError(f"{schema_name} at {path}: {issue}")


def test_builder_schema_and_prompt_expose_proof_artifact_fields() -> None:
    proof_fields = {"proof_files", "proof_artifacts", "artifact_paths"}

    assert proof_fields <= set(GENERATOR_SCHEMA["required"])
    assert proof_fields <= set(GENERATOR_SCHEMA["properties"])
    assert all(field in output_contract_prompt("builder") for field in proof_fields)


def test_runtime_output_contracts_name_top_level_schema_required_fields() -> None:
    contracts_and_schemas = [
        (output_contract_prompt("builder"), GENERATOR_SCHEMA),
        (output_contract_prompt("inspector"), TESTER_SCHEMA),
        (output_contract_prompt("gatekeeper"), VERIFIER_SCHEMA),
        (output_contract_prompt("guide"), CHALLENGER_SCHEMA),
        (output_contract_prompt("custom"), CUSTOM_SCHEMA),
    ]

    for prompt, schema in contracts_and_schemas:
        missing = [field for field in schema["required"] if field not in prompt]
        assert not missing


def test_tester_prompts_name_execution_summary_shape() -> None:
    mixin = PromptHarness()
    compiled_spec = _prompt_contract_spec()
    prompts = [
        mixin._tester_prompt(compiled_spec, 0, "default"),
        output_contract_prompt("inspector"),
    ]

    for prompt in prompts:
        for field in ("total_checks", "passed", "failed", "errored", "total_duration_ms"):
            assert field in prompt


def test_gatekeeper_prompts_name_metric_and_priority_failure_shapes() -> None:
    mixin = PromptHarness()
    compiled_spec = _prompt_contract_spec()
    tester_output = _prompt_contract_tester_output()
    prompts = [
        mixin._verifier_prompt(compiled_spec, tester_output, 0, "default"),
        output_contract_prompt("gatekeeper"),
    ]

    for prompt in prompts:
        for field in (
            "metrics",
            "name",
            "value",
            "threshold",
            "passed",
            "metric_scores",
            "check_pass_rate",
            "quality_score",
            "priority_failures",
            "error_code",
            "summary",
            "coverage_results",
            "target_id",
            "status",
            "evidence_refs",
            "note",
        ):
            assert field in prompt


def test_legacy_role_prompts_name_top_level_schema_required_fields(tmp_path) -> None:
    mixin = PromptHarness()
    compiled_spec = _prompt_contract_spec()
    tester_output = _prompt_contract_tester_output()

    prompts_and_schemas = [
        (mixin._check_planner_prompt(compiled_spec), CHECK_PLANNER_SCHEMA),
        (mixin._generator_prompt(compiled_spec, tmp_path, 0, "default"), GENERATOR_SCHEMA),
        (mixin._tester_prompt(compiled_spec, 0, "default"), TESTER_SCHEMA),
        (mixin._verifier_prompt(compiled_spec, tester_output, 0, "default"), VERIFIER_SCHEMA),
        (mixin._challenger_prompt(compiled_spec, {"stagnation_mode": "plateau"}, 1), CHALLENGER_SCHEMA),
    ]

    for prompt, schema in prompts_and_schemas:
        missing = [field for field in schema["required"] if field not in prompt]
        assert not missing


def _prompt_contract_spec() -> dict:
    return {
        "goal": "Verify the main flow.",
        "checks": [
            {
                "id": "check_001",
                "title": "Main flow works",
                "details": "The main flow is usable.",
                "when": "When the user follows the main path.",
                "expect": "The main path succeeds.",
                "fail_if": "The path breaks.",
            }
        ],
        "constraints": "- Keep changes focused.",
    }


def _prompt_contract_tester_output() -> dict:
    return {
        "execution_summary": {
            "total_checks": 1,
            "passed": 0,
            "failed": 1,
            "errored": 0,
            "total_duration_ms": 10,
        },
        "check_results": [],
        "dynamic_checks": [],
        "tester_observations": "No passing proof.",
        "coverage_results": [],
    }


def _find_schema_issues(schema: object, path: str = "root") -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            if schema.get("additionalProperties") is not False:
                failures.append((path, "objects with properties must declare additionalProperties: false"))
            property_names = list(schema["properties"].keys())
            required = schema.get("required", [])
            missing = [key for key in property_names if key not in required]
            if missing:
                failures.append((path, f"missing required keys: {missing}"))
        for key, value in schema.items():
            failures.extend(_find_schema_issues(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            failures.extend(_find_schema_issues(item, f"{path}[{index}]"))
    return failures
