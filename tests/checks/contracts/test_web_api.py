from __future__ import annotations

import json
import re
import shutil
import time
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from loopora.bundles import bundle_to_yaml
from loopora.branding import state_dir_for_workdir
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.file_previews import preview_existing_path
from loopora.run_observation_events import PROGRESS_EVENT_TYPES, TIMELINE_EVENT_TYPES
from loopora.run_artifacts import RunArtifactLayout
from loopora.run_takeaways import (
    build_evidence_manifest,
    build_legacy_iteration_takeaway,
    build_minimal_run_takeaway_projection,
    build_role_takeaway_from_handoff,
    display_iter,
    empty_judgment_contract,
    normalize_run_takeaway_projection_shape,
)
from loopora.providers import CLAUDE_DEFAULT_MODEL, OPENCODE_DEFAULT_MODEL
from loopora.settings import app_home, configure_logging
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.web_streaming import MAX_EVENT_CURSOR_ID, parse_sse_last_event_id, stream_error_payload
from loopora.web_url_utils import safe_attachment_filename, safe_local_return_path, with_query_params
import loopora.service_run_lifecycle as service_run_lifecycle
import loopora.web as web_module
from loopora.web import build_app
from loopora.web_overviews import _build_run_summary_snapshot, _decorate_loop_overview, _format_timeline_event, _progress_stage_seed


def _read_service_log_records() -> list[dict]:
    return [json.loads(line) for line in (app_home() / "logs" / "service.log").read_text(encoding="utf-8").splitlines() if line.strip()]


def _start_agent_first_loop(service, *, tmp_path: Path, workdir: Path) -> dict:
    bundle_file = tmp_path / "agent-first-bundle.yml"
    bundle_file.write_text(alignment_bundle_yaml(str(workdir.resolve())), encoding="utf-8")
    service.create_agent_bundle_candidate(
        AgentBundleCandidateRequest(
            adapter="codex",
            workdir=workdir,
            message=(
                "Ship the focused starter experience. The primary user flow must work end to end, "
                "use project-owned evidence, avoid happy-path claim only, keep a clear handoff, "
                "and let GateKeeper reject weak proof."
            ),
            bundle_file=bundle_file,
            context_id="web-api-agent-first",
            entry_source="codex_project_skill",
        )
    )
    return service.start_agent_loop(
        "codex",
        workdir=workdir,
        context_id="web-api-agent-first",
        entry_source="codex_project_skill",
        execute_async=False,
    )


def test_streaming_cursor_helpers_require_strict_integer_boundaries() -> None:
    assert parse_sse_last_event_id("42") == 42
    assert parse_sse_last_event_id(" 42 ") == 42
    assert parse_sse_last_event_id("+42") is None
    assert parse_sse_last_event_id("42.0") is None
    assert parse_sse_last_event_id(str(MAX_EVENT_CURSOR_ID + 1)) is None

    assert stream_error_payload(owner_key="run_id", owner_id="run_test", after_id=42)["after_id"] == 42
    assert stream_error_payload(owner_key="run_id", owner_id="run_test", after_id="42")["after_id"] == 0
    assert stream_error_payload(owner_key="run_id", owner_id="run_test", after_id=True)["after_id"] == 0
    assert stream_error_payload(owner_key="run_id", owner_id="run_test", after_id=MAX_EVENT_CURSOR_ID + 1)["after_id"] == 0


def test_progress_stage_seed_keeps_run_closure_language_neutral() -> None:
    stages = _progress_stage_seed({"workflow_json": {"roles": [], "steps": []}})

    assert stages[-1] == {"key": "finished", "label": "Run closed", "kind": "finished", "sequence": 2}
    assert all(stage["label"] != "Done" for stage in stages)


def test_timeline_event_formatter_keeps_stable_observation_titles() -> None:
    role_summary = _format_timeline_event(
        {
            "id": 1,
            "event_type": "role_execution_summary",
            "created_at": "2026-05-05T00:00:00Z",
            "role": "Builder",
            "payload": {"ok": True, "attempts": 2, "degraded": True, "duration_ms": 12},
        }
    )
    string_ok_role_summary = _format_timeline_event(
        {
            "id": 6,
            "event_type": "role_execution_summary",
            "created_at": "2026-05-05T00:00:00Z",
            "role": "Builder",
            "payload": {"ok": "false", "error": "failed as string", "duration_ms": 12},
        }
    )
    control_event = _format_timeline_event(
        {
            "id": 2,
            "event_type": "control_triggered",
            "created_at": "2026-05-05T00:00:01Z",
            "payload": {"signal": "no_evidence_progress", "role_id": "inspector"},
        }
    )
    parallel_event = _format_timeline_event(
        {
            "id": 5,
            "event_type": "parallel_group_started",
            "created_at": "2026-05-05T00:00:01Z",
            "payload": {"parallel_group": "inspection_pack", "step_ids": ["review_a", "review_b"]},
        }
    )
    run_finished = _format_timeline_event(
        {
            "id": 3,
            "event_type": "run_finished",
            "created_at": "2026-05-05T00:00:02Z",
            "payload": {
                "status": "succeeded",
                "reason": "rounds_completed",
                "task_verdict_status": "insufficient_evidence",
                "task_verdict_summary": "Required coverage still lacks direct evidence.",
            },
        }
    )
    accepted = _format_timeline_event(
        {
            "id": 4,
            "event_type": "run_result_accepted",
            "created_at": "2026-05-05T00:00:03Z",
            "payload": {"status": "succeeded", "task_verdict_status": "passed"},
        }
    )
    accepted_with_judgment = _format_timeline_event(
        {
            "id": 5,
            "event_type": "run_result_accepted",
            "created_at": "2026-05-05T00:00:04Z",
            "payload": {
                "status": "succeeded",
                "task_verdict_status": "passed",
                "run_contract_path": "contract/run_contract.json",
                "judgment_contract_summary": "Prefer proof before closure.",
                "loop_fit_reasons": ["Future rounds keep proof alive."],
                "execution_strategy": ["Prove the contract before polish."],
                "local_governance": ["GateKeeper treats skipped AGENTS.md obligations as Blocking."],
                "role_postures": ["GateKeeper: Fail closed when evidence is weak."],
                "judgment_tradeoffs": ["Proof beats polish."],
                "success_surface": ["Support admin can approve a refund."],
                "fake_done_states": ["CSV export without permission audit is fake done."],
                "evidence_preferences": ["Use browser journey and audit log evidence."],
                "residual_risk": "No residual risk is acceptable.",
            },
        }
    )
    malformed_role_summary = _format_timeline_event(
        {
            "id": 7,
            "event_type": "role_execution_summary",
            "created_at": "2026-05-05T00:00:04Z",
            "role": "Builder",
            "payload": {"ok": True, "attempts": "2", "degraded": "false", "duration_ms": "not-a-duration"},
        }
    )
    malformed_checks = _format_timeline_event(
        {
            "id": 11,
            "event_type": "checks_resolved",
            "created_at": "2026-05-05T00:00:04Z",
            "payload": {"count": "7", "source": "auto_generated"},
        }
    )
    malformed_wait = _format_timeline_event(
        {
            "id": 12,
            "event_type": "iteration_wait_started",
            "created_at": "2026-05-05T00:00:04Z",
            "payload": {"duration_seconds": "30"},
        }
    )
    malformed_abort = _format_timeline_event(
        {
            "id": 13,
            "event_type": "run_aborted",
            "created_at": "2026-05-05T00:00:04Z",
            "payload": {"role": "Builder", "attempts": "2"},
        }
    )
    malformed_guard = _format_timeline_event(
        {
            "id": 14,
            "event_type": "workspace_guard_triggered",
            "created_at": "2026-05-05T00:00:04Z",
            "payload": {"deleted_original_count": "3"},
        }
    )
    malformed_failure_summary = _format_timeline_event(
        {
            "id": 8,
            "event_type": "role_execution_summary",
            "created_at": "2026-05-05T00:00:05Z",
            "role": "Builder",
            "payload": {"ok": "false", "error": "failed as string", "duration_ms": "not-a-duration"},
        }
    )
    list_payload_summary = _format_timeline_event(
        {
            "id": 9,
            "event_type": "role_execution_summary",
            "created_at": "2026-05-05T00:00:06Z",
            "role": "Builder",
            "payload": ["not", "a", "mapping"],
        }
    )
    overflow_iter_finished = _format_timeline_event(
        {
            "id": 10,
            "event_type": "run_finished",
            "created_at": "2026-05-05T00:00:07Z",
            "payload": {"status": "succeeded", "iter": float("inf")},
        }
    )
    legacy_missing_verdict_finished = _format_timeline_event(
        {
            "id": 11,
            "event_type": "run_finished",
            "created_at": "2026-05-05T00:00:08Z",
            "payload": {"status": "succeeded", "reason": "legacy_terminal_event"},
        }
    )

    assert role_summary["title"] == "Builder completed"
    assert role_summary["detail"] == "attempts=2, degraded, 12ms"
    assert string_ok_role_summary["title"] == "Builder failed"
    assert string_ok_role_summary["detail"] == "failed as string, 12ms"
    assert malformed_role_summary["title"] == "Builder completed"
    assert malformed_role_summary["detail"] == "ok"
    assert malformed_checks["detail"] == "0 checks, auto-generated"
    assert malformed_wait["detail"] == "0s"
    assert malformed_abort["detail"] == ""
    assert malformed_guard["detail"] == "deleted=0"
    assert malformed_failure_summary["title"] == "Builder failed"
    assert malformed_failure_summary["detail"] == "failed as string"
    assert list_payload_summary["title"] == "Builder failed"
    assert list_payload_summary["detail"] == ""
    assert overflow_iter_finished["title"] == "Run finished"
    assert overflow_iter_finished["detail"] == "task_verdict_status=not_evaluated"
    assert legacy_missing_verdict_finished["title"] == "Run finished"
    assert legacy_missing_verdict_finished["detail"] == "legacy_terminal_event, task_verdict_status=not_evaluated"
    assert control_event["title"] == "Control triggered"
    assert control_event["detail"] == "no_evidence_progress -> inspector"
    assert parallel_event["title"] == "Parallel review started"
    assert parallel_event["detail"] == "inspection_pack, steps=2"
    assert run_finished["title"] == "Run finished"
    assert (
        run_finished["detail"]
        == "planned rounds completed, task_verdict_status=insufficient_evidence, task_verdict_summary=Required coverage still lacks direct evidence."
    )
    assert accepted["title"] == "Passing evidence verdict recorded"
    assert accepted["detail"] == "status=succeeded, task_verdict_status=passed"
    assert accepted_with_judgment["detail"] == (
        "status=succeeded, task_verdict_status=passed, judgment=Prefer proof before closure., "
        "loop_fit=Future rounds keep proof alive., strategy=Prove the contract before polish., "
        "local_governance=GateKeeper treats skipped AGENTS.md obligations as Blocking., "
        "role_posture=GateKeeper: Fail closed when evidence is weak., "
        "tradeoff=Proof beats polish., success=Support admin can approve a refund., "
        "fake_done=CSV export without permission audit is fake done., "
        "evidence=Use browser journey and audit log evidence., residual_risk=No residual risk is acceptable."
    )


def test_loop_overview_preserves_residual_risk_task_verdict() -> None:
    decorated = _decorate_loop_overview(
        {
            "id": "loop_1",
            "latest_run_id": "run_1",
            "latest_status": "succeeded",
            "latest_task_verdict_json": {
                "status": "passed_with_residual_risk",
                "source": "gatekeeper",
                "summary": "Accepted a visible follow-up risk.",
                "buckets": {"residual_risk": [{"label": "follow-up"}]},
            },
            "workflow_json": {},
        }
    )

    assert decorated["card_hint_en"] == "The latest task verdict passed with residual risk."
    assert decorated["card_hint_zh"] == "最近一次 Loop 裁决带残余风险通过。"

    summary = _build_run_summary_snapshot(
        {
            "status": "succeeded",
            "current_iter": 0,
            "summary_md": "",
            "last_verdict_json": {},
            "task_verdict": {
                "status": "passed_with_residual_risk",
                "source": "gatekeeper",
                "summary": "",
                "buckets": {"residual_risk": [{"label": "follow-up"}]},
            },
        }
    )

    assert summary["verdict_title_en"] == "Task verdict: passed with residual risk"
    assert summary["verdict_title_zh"] == "Loop 裁决：有残余风险地通过"
    assert summary["verdict_note_en"] == "follow-up"
    assert "Loop verdict" in summary["status_note_en"]
    assert "任务是否通过" in summary["status_note_zh"]


def test_loop_overview_surfaces_unproven_terminal_task_verdicts() -> None:
    insufficient = _decorate_loop_overview(
        {
            "id": "loop_1",
            "latest_run_id": "run_1",
            "latest_status": "succeeded",
            "latest_task_verdict_json": {
                "status": "insufficient_evidence",
                "source": "gatekeeper",
                "summary": "Missing proof.",
            },
            "latest_summary_md": "# Loopora Run Summary\n\nAll done according to the Agent summary.",
            "workflow_json": {},
        }
    )
    failed = _decorate_loop_overview(
        {
            "id": "loop_2",
            "latest_run_id": "run_2",
            "latest_status": "failed",
            "latest_task_verdict_json": {
                "status": "failed",
                "source": "run_status",
                "summary": "Blocked.",
            },
            "workflow_json": {},
        }
    )

    assert insufficient["card_hint_en"] == "The latest task verdict has insufficient evidence."
    assert insufficient["card_hint_zh"] == "最近一次 Loop 裁决证据不足。"
    assert insufficient["card_excerpt_en"] == "Task verdict still insufficient: Missing proof."
    assert insufficient["card_excerpt_zh"] == "Loop 裁决证据不足：Missing proof."
    assert "All done" not in insufficient["card_excerpt_en"]
    assert failed["card_hint_en"] == "The latest task verdict failed."
    assert failed["card_hint_zh"] == "最近一次 Loop 裁决未通过。"

    summary = _build_run_summary_snapshot(
        {
            "status": "succeeded",
            "current_iter": 0,
            "summary_md": "# Loopora Run Summary\n\nAll done according to the Agent summary.",
            "last_verdict_json": {},
            "task_verdict": {
                "status": "insufficient_evidence",
                "source": "gatekeeper",
                "summary": "Missing proof.",
            },
        }
    )
    assert summary["summary_excerpt_en"] == "Task verdict still insufficient: Missing proof."
    assert summary["summary_excerpt_zh"] == "Loop 裁决证据不足：Missing proof."
    assert "All done" not in summary["summary_excerpt_en"]


def test_web_url_helpers_keep_redirects_and_filenames_local() -> None:
    assert safe_local_return_path("/bundles/bundle-1?tab=roles#surface") == "/bundles/bundle-1?tab=roles#surface"
    assert safe_local_return_path("/bundles/bundle-1?token=secret&tab=roles#surface") == "/bundles/bundle-1?tab=roles#surface"
    assert safe_local_return_path("https://example.test/bundles/1") is None
    assert safe_local_return_path("//example.test/bundles/1") is None
    assert safe_local_return_path("bundles/1") is None
    assert safe_local_return_path("/bundles\\example.test") is None
    assert safe_local_return_path("/bundles/1\r\nLocation: https://example.test") is None
    assert with_query_params("/bundles/bundle-1?tab=roles#surface", surface_updated="workflow") == (
        "/bundles/bundle-1?tab=roles&surface_updated=workflow#surface"
    )
    assert with_query_params("/bundles/bundle-1?token=secret&tab=roles", surface_updated="workflow") == (
        "/bundles/bundle-1?tab=roles&surface_updated=workflow"
    )
    assert safe_attachment_filename('Bad/Name" \r\n injected.yml') == "Bad-Name-injected.yml"


def _create_api_loop_run(client: TestClient, sample_spec_file: Path, sample_workdir: Path) -> str:
    response = client.post(
        "/api/loops",
        json={
            "name": "API Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": True,
        },
    )
    assert response.status_code == 201
    return response.json()["run"]["id"]


def _wait_for_run_success(client: TestClient, run_id: str) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        run_response = client.get(f"/api/runs/{run_id}")
        assert run_response.status_code == 200
        if run_response.json()["status"] == "succeeded":
            return
        time.sleep(0.05)
    raise AssertionError(f"run did not succeed before timeout: {run_id}")


def _assert_file_explorer_contract(client: TestClient, run_id: str) -> None:
    explorer = client.get(f"/api/files?run_id={run_id}&root=workdir")
    assert explorer.status_code == 200
    assert explorer.json()["kind"] == "directory"
    assert explorer.json()["entries_truncated"] is False

    loopora_dir = client.get(f"/api/files?run_id={run_id}&root=loopora")
    assert loopora_dir.status_code == 200
    assert loopora_dir.json()["kind"] == "directory"
    assert loopora_dir.json()["entries_truncated"] is False

    invalid_root = client.get(f"/api/files?run_id={run_id}&root=archive")
    assert invalid_root.status_code == 400
    assert "error" in invalid_root.json()


def _assert_run_artifact_catalog(client: TestClient, run_id: str) -> None:
    artifacts = client.get(f"/api/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    artifact_payload = artifacts.json()
    assert any(item["id"] == "original-spec" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "summary" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "evidence-ledger" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "evidence-coverage" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "evidence-manifest" and item["available"] for item in artifact_payload)
    assert any(item["id"] == "task-verdict" and item["available"] for item in artifact_payload)

    artifacts_by_id = {item["id"]: item for item in artifact_payload}
    assert artifacts_by_id["original-spec"]["label_zh"] == "原始 Loop 契约"
    assert artifacts_by_id["compiled-spec"]["label_zh"] == "编译后契约"
    assert "假完成风险" in artifacts_by_id["compiled-spec"]["description_zh"]
    assert "执行策略" in artifacts_by_id["compiled-spec"]["description_zh"]
    assert "Evidence Preferences" in artifacts_by_id["compiled-spec"]["description_en"]
    assert "Execution Strategy" in artifacts_by_id["compiled-spec"]["description_en"]
    assert "Residual Risk" in artifacts_by_id["compiled-spec"]["description_en"]
    assert artifacts_by_id["workflow-manifest"]["label_zh"] == "流程清单"
    assert "规范证据账本" in artifacts_by_id["evidence-ledger"]["description_zh"]
    assert artifacts_by_id["task-verdict"]["label_zh"] == "Loop 裁决"
    assert "终态 Loop 裁决" in artifacts_by_id["task-verdict"]["description_zh"]
    for artifact_id in (
        "summary",
        "original-spec",
        "compiled-spec",
        "workflow-manifest",
        "run-contract",
        "latest-state",
        "timeline-events",
        "timeline-iterations",
        "timeline-metrics",
        "evidence-ledger",
        "evidence-coverage",
        "evidence-manifest",
        "task-verdict",
    ):
        zh_metadata = f"{artifacts_by_id[artifact_id]['label_zh']} {artifacts_by_id[artifact_id]['description_zh']}"
        assert "Spec" not in zh_metadata
        assert "workflow" not in zh_metadata
        assert "canonical" not in zh_metadata
        assert " run " not in f" {zh_metadata} "
        assert "任务裁决" not in zh_metadata


def _assert_artifact_file(
    client: TestClient,
    run_id: str,
    artifact_id: str,
    *,
    expected_content: str | None = None,
    content_fragment: str | None = None,
) -> None:
    artifact = client.get(f"/api/runs/{run_id}/artifacts/{artifact_id}")
    assert artifact.status_code == 200
    payload = artifact.json()
    assert payload["kind"] == "file"
    if expected_content is not None:
        assert payload["content"] == expected_content
    if content_fragment is not None:
        assert content_fragment in payload["content"]


def _assert_attachment_download(response, *, filename: str) -> None:
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert filename in response.headers["content-disposition"]


def _assert_acceptance_evidence_payload(payload: dict) -> None:
    assert payload["evidence_source_event_id"] > 0
    assert payload["evidence_available"] is True
    assert payload["task_verdict_summary"]
    _assert_key_takeaway_judgment_contract(payload["judgment_contract"])
    assert payload["run_contract_path"] == "contract/run_contract.json"
    assert payload["judgment_contract_summary"] == "Ship the requested behavior."
    assert payload["check_mode"] == "specified"
    assert payload["check_count"] == 2
    assert payload["completion_mode"] == "gatekeeper"
    assert payload["workflow_preset"]
    assert any(target["id"] == "done_when.check_001" for target in payload["coverage_targets"])
    assert any(target["id"] == "gatekeeper.finish" for target in payload["coverage_targets"])
    assert isinstance(payload["loop_fit_reasons"], list)
    assert isinstance(payload["execution_strategy"], list)
    assert payload["execution_strategy"]
    assert isinstance(payload["local_governance"], list)
    assert isinstance(payload["role_postures"], list)
    assert any("Prefer structured run artifacts" in item for item in payload["judgment_tradeoffs"])
    assert payload["success_surface"] == [
        "The result remains easy for the next role to verify.",
        "The surrounding contract stays clear enough to revise safely.",
    ]
    assert payload["fake_done_states"] == ["A happy-path-only result that leaves the edge path unverifiable."]
    assert payload["evidence_preferences"] == [
        "Prefer structured run artifacts and reproducible checks over role self-report."
    ]
    assert payload["residual_risk"] == "Minor copy polish can wait, but unverifiable completion should fail closed."
    assert payload["task_verdict_path"] == "evidence/task_verdict.json"
    assert payload["coverage_path"] == "evidence/coverage.json"
    assert payload["manifest_path"] == "evidence/manifest.json"
    assert payload["coverage_status"] in {"covered", "weak", "partial", "blocked", "pending"}
    assert payload["evidence_count"] > 0
    assert set(payload["evidence_bucket_counts"]) >= {"proven", "weak", "unproven", "blocking", "residual_risk"}


def _accept_run_result_and_assert_observation_event(client: TestClient, service, run: dict, loop: dict) -> list[dict]:
    run_before_accept = service.get_run(run["id"])
    loop_before_accept = service.get_loop(loop["id"])
    task_verdict_status = str((run_before_accept.get("task_verdict") or {}).get("status") or "")

    accept_response = client.post(f"/runs/{run['id']}/accept", follow_redirects=False)

    assert accept_response.status_code == 303
    assert accept_response.headers["location"] == f"/runs/{run['id']}"
    run_after_accept = service.get_run(run["id"])
    loop_after_accept = service.get_loop(loop["id"])
    assert run_after_accept["status"] == run_before_accept["status"]
    assert run_after_accept["task_verdict"] == run_before_accept["task_verdict"]
    assert loop_after_accept["workflow_json"] == loop_before_accept["workflow_json"]
    accepted_events = service.recent_run_events(run["id"], event_types={"run_result_accepted"})
    assert accepted_events
    assert accepted_events[-1]["payload"]["status"] == run["status"]
    assert accepted_events[-1]["payload"]["task_verdict_status"]
    assert accepted_events[-1]["payload"]["recorded_verdict_kind"] == _expected_recorded_verdict_kind(task_verdict_status)
    assert accepted_events[-1]["payload"]["evidence_source_event_id"] < accepted_events[-1]["id"]
    _assert_acceptance_evidence_payload(accepted_events[-1]["payload"])
    return accepted_events


def _expected_recorded_verdict_kind(task_verdict_status: str) -> str:
    return {
        "passed": "passed_verdict_recorded",
        "passed_with_residual_risk": "passed_with_residual_risk_recorded",
        "insufficient_evidence": "unproven_verdict_recorded",
        "failed": "failed_verdict_recorded",
        "not_evaluated": "not_evaluated_verdict_recorded",
    }.get(task_verdict_status, "evidence_verdict_recorded")


def _expected_recorded_verdict_title(task_verdict_status: str) -> str:
    return {
        "passed": "Passing evidence verdict recorded",
        "passed_with_residual_risk": "Pass-with-risk verdict recorded",
        "insufficient_evidence": "Unproven evidence verdict recorded",
        "failed": "Failed evidence verdict recorded",
        "not_evaluated": "Unevaluated evidence verdict recorded",
    }.get(task_verdict_status, "Evidence verdict recorded")


def _expected_recorded_verdict_page_text(task_verdict_status: str) -> str:
    return {
        "passed": "Passing verdict recorded",
        "passed_with_residual_risk": "Pass-with-risk verdict recorded",
        "insufficient_evidence": "Unproven verdict recorded",
        "failed": "Failed verdict recorded",
        "not_evaluated": "Unevaluated verdict recorded",
    }.get(task_verdict_status, "Evidence verdict recorded")


def _assert_run_artifact_previews(client: TestClient, run_id: str, sample_spec_text: str) -> None:
    missing_artifact = client.get(f"/api/runs/{run_id}/artifacts/missing-artifact/download")
    assert missing_artifact.status_code == 404
    assert missing_artifact.json()["error"] == "unknown artifact"
    summary_download = client.get(f"/api/runs/{run_id}/artifacts/summary/download")
    _assert_attachment_download(summary_download, filename="summary.md")
    _assert_artifact_file(client, run_id, "original-spec", expected_content=sample_spec_text)
    _assert_artifact_file(client, run_id, "summary", content_fragment="Loopora Run Summary")
    _assert_artifact_file(client, run_id, "latest-state", content_fragment='"latest_iteration"')
    _assert_artifact_file(client, run_id, "evidence-ledger", content_fragment="gatekeeper")
    _assert_artifact_file(client, run_id, "evidence-coverage", content_fragment='"targets"')
    _assert_artifact_file(client, run_id, "evidence-manifest", content_fragment='"verification_status"')
    _assert_artifact_file(client, run_id, "task-verdict", content_fragment='"status"')


def test_run_artifact_download_rejects_symlink_escaping_loopora_root(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    run_id = _create_api_loop_run(client, sample_spec_file, sample_workdir)
    _wait_for_run_success(client, run_id)
    run = client.get(f"/api/runs/{run_id}").json()

    outside_artifact = sample_workdir.parent / "outside-summary.md"
    outside_artifact.write_text("outside secret", encoding="utf-8")
    summary_path = Path(run["runs_dir"]) / "summary.md"
    summary_path.unlink()
    try:
        summary_path.symlink_to(outside_artifact)
    except OSError as exc:
        pytest.skip(f"symlinks are not available in this environment: {exc}")

    artifacts = client.get(f"/api/runs/{run_id}/artifacts")
    assert artifacts.status_code == 200
    summary_artifact = next(item for item in artifacts.json() if item["id"] == "summary")
    assert summary_artifact["available"] is False

    preview = client.get(f"/api/runs/{run_id}/artifacts/summary")
    assert preview.status_code == 400

    download = client.get(f"/api/runs/{run_id}/artifacts/summary/download")
    assert download.status_code == 400
    assert "outside secret" not in download.text


def _assert_file_preview_safety(client: TestClient, run_id: str, sample_workdir: Path) -> None:
    binary_path = sample_workdir / ".DS_Store"
    binary_path.write_bytes(b"\x00\x01\x02binary-data")
    binary_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=.DS_Store")
    assert binary_preview.status_code == 200
    assert binary_preview.json()["kind"] == "file"
    assert binary_preview.json()["is_binary"] is True

    bad_path = client.get(f"/api/files?run_id={run_id}&root=workdir&path=../secret.txt")
    assert bad_path.status_code == 400

    sibling_dir = sample_workdir.parent / "workdir-shadow"
    sibling_dir.mkdir()
    (sibling_dir / "secret.txt").write_text("nope", encoding="utf-8")
    sneaky_path = client.get(f"/api/files?run_id={run_id}&root=workdir&path=../workdir-shadow/secret.txt")
    assert sneaky_path.status_code == 400

    unsafe_md = sample_workdir / "unsafe.md"
    unsafe_md.write_text("# Title\n\n<script>alert('xss')</script>\n", encoding="utf-8")
    unsafe_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=unsafe.md")
    assert unsafe_preview.status_code == 200
    assert "<script>" not in unsafe_preview.json()["rendered_html"]
    assert "&lt;script&gt;alert" in unsafe_preview.json()["rendered_html"]

    large_path = sample_workdir / "large.txt"
    large_body = "x" * 1_000_001
    large_path.write_text(large_body, encoding="utf-8")
    large_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=large.txt")
    assert large_preview.status_code == 200
    large_payload = large_preview.json()
    assert large_payload["kind"] == "file"
    assert large_payload["preview_omitted"] is True
    assert large_payload["content"] == ""
    assert large_payload["size_bytes"] == len(large_body)
    assert "too large" in large_payload["preview_error"]

    large_download = client.get(f"/api/files/download?run_id={run_id}&root=workdir&path=large.txt")
    _assert_attachment_download(large_download, filename="large.txt")
    assert large_download.content == large_body.encode()

    html_download_path = sample_workdir / "untrusted.html"
    html_download_path.write_text("<script>alert('xss')</script>", encoding="utf-8")
    html_download = client.get(f"/api/files/download?run_id={run_id}&root=workdir&path=untrusted.html")
    _assert_attachment_download(html_download, filename="untrusted.html")

    crowded_dir = sample_workdir / "crowded"
    crowded_dir.mkdir()
    for index in range(1001):
        (crowded_dir / f"entry-{index:04d}.txt").write_text("", encoding="utf-8")
    crowded_preview = client.get(f"/api/files?run_id={run_id}&root=workdir&path=crowded")
    assert crowded_preview.status_code == 200
    crowded_payload = crowded_preview.json()
    assert crowded_payload["kind"] == "directory"
    assert crowded_payload["entries_truncated"] is True
    assert len(crowded_payload["entries"]) == 1000


def test_api_file_preview_reports_unreadable_file_without_500(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Unreadable File Preview Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    unreadable_path = sample_workdir / "unreadable.txt"
    unreadable_path.write_text("hidden", encoding="utf-8")
    unreadable_resolved = unreadable_path.resolve()
    original_read_bytes = Path.read_bytes

    def fail_target_read(path: Path) -> bytes:
        if path == unreadable_resolved:
            raise OSError("forced unreadable file")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_target_read)
    client = TestClient(build_app(service=service))
    response = client.get(f"/api/files?run_id={run['id']}&root=workdir&path=unreadable.txt")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["content"] == ""
    assert payload["preview_error"] == "file could not be read"


def test_file_preview_reports_unreadable_directory(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / "blocked"
    directory.mkdir()
    original_iterdir = Path.iterdir

    def fail_target_iterdir(path: Path):
        if path == directory:
            raise OSError("forced unreadable directory")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", fail_target_iterdir)
    payload = preview_existing_path(base=tmp_path, relative_path="blocked", resolved=directory)

    assert payload["kind"] == "directory"
    assert payload["entries"] == []
    assert payload["preview_error"] == "directory could not be read"


def _stream_body(stream_response) -> str:
    return "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())


def _assert_run_event_streaming(client: TestClient, run_id: str) -> None:
    events = client.get(f"/api/runs/{run_id}/events")
    assert events.status_code == 200
    event_payload = events.json()
    assert event_payload

    with client.stream("GET", f"/api/runs/{run_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        body = _stream_body(stream_response)
    assert "run_finished" in body or "keep-alive" in body

    latest_event_id = event_payload[-1]["id"]
    with client.stream("GET", f"/api/runs/{run_id}/stream?after_id={latest_event_id}") as stream_response:
        assert stream_response.status_code == 200
        delta_body = _stream_body(stream_response)
    assert "run_started" not in delta_body

    reconnect_from = event_payload[0]["id"]
    with client.stream(
        "GET",
        f"/api/runs/{run_id}/stream",
        headers={"Last-Event-ID": str(reconnect_from)},
    ) as stream_response:
        assert stream_response.status_code == 200
        reconnect_body = _stream_body(stream_response)
    assert f"id: {reconnect_from}\n" not in reconnect_body


def test_run_event_api_rejects_out_of_range_query_params(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    for path in (
        "/api/runs/run_test/events?after_id=-1",
        f"/api/runs/run_test/events?after_id={MAX_EVENT_CURSOR_ID + 1}",
        "/api/runs/run_test/events?limit=0",
        "/api/runs/run_test/events?limit=5001",
        "/api/runs/run_test/stream?after_id=-1",
        f"/api/runs/run_test/stream?after_id={MAX_EVENT_CURSOR_ID + 1}",
    ):
        response = client.get(path)
        assert response.status_code == 400
        assert response.json()["error"] == "request validation failed"


def test_run_event_api_rejects_cursor_beyond_current_run_events(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Cursor Boundary Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    latest_event = service.repository.append_event(run["id"], "run_started", {"status": "running"})
    future_cursor = latest_event["id"] + 1
    client = TestClient(build_app(service=service))

    for path in (
        f"/api/runs/{run['id']}/events?after_id={future_cursor}",
        f"/api/runs/{run['id']}/stream?after_id={future_cursor}",
    ):
        response = client.get(path)
        assert response.status_code == 400
        assert response.json()["error"] == "event cursor is out of range"


def test_api_loop_creation_run_preview_and_stream(
    service_factory,
    sample_spec_file: Path,
    sample_spec_text: str,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    run_id = _create_api_loop_run(client, sample_spec_file, sample_workdir)
    _wait_for_run_success(client, run_id)
    _assert_file_explorer_contract(client, run_id)
    _assert_run_artifact_catalog(client, run_id)
    _assert_run_artifact_previews(client, run_id, sample_spec_text)
    _assert_file_preview_safety(client, run_id, sample_workdir)
    _assert_run_event_streaming(client, run_id)


def _assert_key_takeaway_judgment_contract(judgment_contract: dict) -> None:
    assert judgment_contract["contract_path"] == "contract/run_contract.json"
    assert judgment_contract["goal"] == "Ship the requested behavior."
    assert judgment_contract["check_mode"] == "specified"
    assert judgment_contract["check_count"] == 2
    assert judgment_contract["completion_mode"] == "gatekeeper"
    assert judgment_contract["workflow_preset"]
    assert any(target["id"] == "done_when.check_001" for target in judgment_contract["coverage_targets"])
    assert any(target["id"] == "gatekeeper.finish" for target in judgment_contract["coverage_targets"])
    assert judgment_contract["success_surface"] == [
        "The result remains easy for the next role to verify.",
        "The surrounding contract stays clear enough to revise safely.",
    ]
    assert judgment_contract["fake_done_states"] == ["A happy-path-only result that leaves the edge path unverifiable."]
    assert judgment_contract["evidence_preferences"] == [
        "Prefer structured run artifacts and reproducible checks over role self-report."
    ]
    assert judgment_contract["execution_strategy"]
    assert isinstance(judgment_contract["local_governance"], list)
    assert "Prefer structured run artifacts and reproducible checks over role self-report." in judgment_contract["judgment_tradeoffs"]
    assert any("one coherent attempt that improves the main path" in item for item in judgment_contract["judgment_tradeoffs"])
    assert judgment_contract["residual_risk"] == "Minor copy polish can wait, but unverifiable completion should fail closed."


def test_api_run_key_takeaways_returns_iteration_role_conclusions(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Takeaway Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/key-takeaways")

    assert response.status_code == 200
    payload = response.json()
    assert payload["build_dir"] == str(sample_workdir.resolve())
    assert payload["log_dir"].endswith(f"/.loopora/runs/{run['id']}")
    assert payload["run_status"] == "succeeded"
    assert payload["task_verdict"]["status"] == "passed"
    assert payload["task_verdict"]["source"] == "gatekeeper"
    assert payload["task_verdict_path"] == "evidence/task_verdict.json"
    _assert_key_takeaway_judgment_contract(payload["judgment_contract"])
    assert set(payload["evidence_buckets"]) == {"proven", "weak", "unproven", "blocking", "residual_risk"}
    assert payload["iteration_count"] >= 1
    assert payload["role_conclusion_count"] >= 2
    latest_iteration = payload["iterations"][0]
    assert latest_iteration["display_iter"] >= 1
    assert latest_iteration["summary"]
    role_names = {item["role_name"] for item in latest_iteration["roles"]}
    assert "Builder" in role_names
    assert "GateKeeper" in role_names
    gatekeeper = next(item for item in latest_iteration["roles"] if item["role_name"] == "GateKeeper")
    assert gatekeeper["composite_score"] is not None
    coverage = payload["evidence_coverage"]
    assert coverage["ledger_path"] == "evidence/ledger.jsonl"
    assert coverage["coverage_path"] == "evidence/coverage.json"
    assert coverage["evidence_count"] == payload["evidence_count"]
    assert coverage["status"] == "weak"
    assert coverage["summary"]["reason"]
    assert coverage["check_count"] == 2
    assert coverage["covered_check_count"] == 2
    assert coverage["missing_check_count"] == 0
    assert set(coverage["covered_check_ids"]) == {"check_001", "check_002"}
    assert coverage["target_count"] >= 5
    assert coverage["missing_target_count"] >= 1
    assert coverage["top_gaps"]
    assert coverage["latest_gatekeeper"]["evidence_refs"]
    assert coverage["evidence_kind_counts"]["inspection"] >= 1
    assert coverage["evidence_kind_counts"]["verdict"] >= 1
    manifest = payload["evidence_manifest"]
    assert manifest["manifest_path"] == "evidence/manifest.json"
    assert manifest["claim_count"] == payload["evidence_count"]
    assert manifest["artifact_backed_claim_count"] == manifest["claim_count"]
    assert manifest["run_artifact_claim_count"] >= 1
    assert set(manifest) >= {
        "direct_proof_claim_count",
        "workspace_artifact_claim_count",
        "ledger_only_claim_count",
        "unverified_claim_count",
        "problem_count",
    }


def test_api_run_key_takeaways_tolerates_invalid_utf8_json_artifacts(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Corrupt Artifact Takeaway Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    run_dir = Path(run["runs_dir"])
    (run_dir / "contract" / "compiled_spec.json").write_bytes(b"\xff")
    (run_dir / "contract" / "run_contract.json").write_bytes(b"\xff")
    (run_dir / "evidence" / "ledger.jsonl").write_bytes(b"\xff")
    for handoff_path in run_dir.glob("iterations/iter_*/steps/*/handoff.json"):
        handoff_path.write_bytes(b"\xff")
        break

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/key-takeaways")

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_count"] == 0
    assert payload["run_status"] == "succeeded"
    assert payload["judgment_contract"] == empty_judgment_contract()


def test_minimal_run_takeaway_projection_keeps_status_verdict_and_empty_evidence_shape(tmp_path: Path) -> None:
    workdir = tmp_path / "project"
    runs_dir = workdir / ".loopora" / "runs" / "run_minimal"
    task_verdict = {
        "status": "insufficient_evidence",
        "source": "rounds_completion",
        "summary": "Evidence did not cross the bar.",
        "buckets": {
            "proven": [],
            "weak": [],
            "unproven": [{"label": "manual review"}],
            "blocking": [],
            "residual_risk": [],
        },
    }

    projection = build_minimal_run_takeaway_projection(
        {
            "id": "run_minimal",
            "status": "succeeded",
            "run_status": "succeeded",
            "task_verdict": task_verdict,
            "workdir": str(workdir),
            "runs_dir": str(runs_dir),
            "summary_md": "# Loopora Run Summary\n\nEvidence did not cross the bar.",
        },
        source_event_id=42,
    )

    assert projection["run_status"] == "succeeded"
    assert projection["task_verdict"]["status"] == "insufficient_evidence"
    assert projection["task_verdict_path"] == ""
    assert projection["evidence_buckets"]["unproven"] == [{"label": "manual review"}]
    assert projection["build_dir"] == str(workdir.resolve())
    assert projection["log_dir"] == str(runs_dir.resolve())
    assert projection["evidence_coverage"]["status"] == "pending"
    assert projection["evidence_manifest"]["claim_count"] == 0
    assert projection["evidence_manifest"]["manifest_path"] == ""
    assert projection["evidence_count"] == 0
    assert projection["iteration_count"] == 0
    assert projection["source_event_id"] == 42


def test_takeaway_evidence_manifest_does_not_promote_boolean_manifest_counts(tmp_path: Path) -> None:
    runs_dir = tmp_path / "run"
    layout = RunArtifactLayout(runs_dir)
    layout.initialize()
    layout.evidence_manifest_path.write_text(
        json.dumps(
            {
                "manifest_path": True,
                "claim_count": True,
                "artifact_backed_claim_count": "1",
                "direct_proof_claim_count": 2,
                "problems": [
                    {"code": True, "claim_id": 7, "severity": False, "message": 3},
                    {"code": "missing_artifact", "claim_id": "ev_001", "severity": "warning", "message": "Proof file is missing."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = build_evidence_manifest({"runs_dir": str(runs_dir)})

    assert manifest["claim_count"] == 0
    assert manifest["artifact_backed_claim_count"] == 0
    assert manifest["direct_proof_claim_count"] == 2
    assert manifest["manifest_path"] == "evidence/manifest.json"
    assert manifest["problem_count"] == 2
    assert manifest["problems"][0] == {"code": "", "claim_id": "", "severity": "", "message": ""}
    assert manifest["problems"][1] == {
        "code": "missing_artifact",
        "claim_id": "ev_001",
        "severity": "warning",
        "message": "Proof file is missing.",
    }


def test_takeaway_projection_normalization_does_not_promote_boolean_counts() -> None:
    projection = normalize_run_takeaway_projection_shape(
        {"id": "run_projection_counts", "status": "succeeded", "run_status": "succeeded"},
        {
            "source_event_id": True,
            "evidence_count": True,
            "evidence_coverage": {
                "ledger_path": True,
                "coverage_path": True,
                "status": True,
                "evidence_count": True,
                "covered_check_count": "1",
                "missing_check_count": 2,
                "covered_check_ids": "check_001",
                "missing_check_ids": ["check_002", True],
                "risk_signals": [False, "manual review"],
            },
            "evidence_manifest": {
                "claim_count": True,
                "artifact_backed_claim_count": "1",
                "direct_proof_claim_count": 2,
                "problem_count": True,
            },
            "judgment_contract": {
                "contract_path": True,
                "source_bundle": {
                    "id": "bundle_projection",
                    "name": "Projection Bundle",
                    "bundle_sha256": "abc123",
                    "bundle_bytes": 42,
                    "bundle_yaml_path": "/tmp/loopora/bundle_projection.yml",
                },
                "collaboration_summary": True,
                "loop_fit_reasons": [False, "Future rounds keep proof alive."],
                "goal": "  Keep the frozen task visible.  ",
                "workflow_collaboration_intent": 8,
                "execution_strategy": [False, "Prove the focused path first."],
                "local_governance": [False, "GateKeeper treats skipped AGENTS.md evidence as Blocking."],
                "role_postures": [
                    {
                        "role_name": "Builder",
                        "archetype": "builder",
                        "posture_notes": "Keep the change narrow and verifiable.",
                    },
                    False,
                ],
                "judgment_tradeoffs": [False, "Prefer proof before polish."],
                "success_surface": ["Stable surface", True],
                "fake_done_states": [False, "Only the happy path"],
                "evidence_preferences": ["Proof artifact", 3],
                "residual_risk": "  Minor copy polish.  ",
            },
            "iteration_count": True,
            "role_conclusion_count": "1",
            "latest_display_iter": True,
        },
    )

    assert projection["source_event_id"] == 0
    assert projection["evidence_count"] == 0
    assert projection["evidence_coverage"]["ledger_path"] == ""
    assert projection["evidence_coverage"]["coverage_path"] == ""
    assert projection["evidence_coverage"]["status"] == "pending"
    assert projection["evidence_coverage"]["evidence_count"] == 0
    assert projection["evidence_coverage"]["covered_check_count"] == 0
    assert projection["evidence_coverage"]["missing_check_count"] == 2
    assert projection["evidence_coverage"]["covered_check_ids"] == []
    assert projection["evidence_coverage"]["missing_check_ids"] == ["check_002"]
    assert projection["evidence_coverage"]["risk_signals"] == ["manual review"]
    assert projection["evidence_manifest"]["claim_count"] == 0
    assert projection["evidence_manifest"]["artifact_backed_claim_count"] == 0
    assert projection["evidence_manifest"]["direct_proof_claim_count"] == 2
    assert projection["evidence_manifest"]["problem_count"] == 0
    assert projection["judgment_contract"]["contract_path"] == ""
    assert projection["judgment_contract"]["source_bundle"]["id"] == "bundle_projection"
    assert projection["judgment_contract"]["source_bundle"]["bundle_sha256"] == "abc123"
    assert projection["judgment_contract"]["source_bundle"]["bundle_bytes"] == 42
    assert projection["judgment_contract"]["source_bundle"]["bundle_yaml_path"] == "/tmp/loopora/bundle_projection.yml"
    assert projection["judgment_contract"]["collaboration_summary"] == ""
    assert projection["judgment_contract"]["loop_fit_reasons"] == ["Future rounds keep proof alive."]
    assert projection["judgment_contract"]["goal"] == "Keep the frozen task visible."
    assert projection["judgment_contract"]["check_mode"] == ""
    assert projection["judgment_contract"]["check_count"] == 0
    assert projection["judgment_contract"]["completion_mode"] == ""
    assert projection["judgment_contract"]["workflow_preset"] == ""
    assert projection["judgment_contract"]["workflow_collaboration_intent"] == ""
    assert projection["judgment_contract"]["execution_strategy"] == ["Prove the focused path first."]
    assert projection["judgment_contract"]["local_governance"] == ["GateKeeper treats skipped AGENTS.md evidence as Blocking."]
    assert projection["judgment_contract"]["role_postures"] == ["Builder: Keep the change narrow and verifiable."]
    assert projection["judgment_contract"]["judgment_tradeoffs"] == ["Prefer proof before polish."]
    assert projection["judgment_contract"]["coverage_targets"] == []
    assert projection["judgment_contract"]["success_surface"] == ["Stable surface"]
    assert projection["judgment_contract"]["fake_done_states"] == ["Only the happy path"]
    assert projection["judgment_contract"]["evidence_preferences"] == ["Proof artifact"]
    assert projection["judgment_contract"]["residual_risk"] == "Minor copy polish."
    assert projection["iteration_count"] == 0
    assert projection["role_conclusion_count"] == 0
    assert projection["latest_display_iter"] is None


def test_takeaway_projection_normalizes_task_verdict_bucket_shapes() -> None:
    projection = normalize_run_takeaway_projection_shape(
        {"id": "run_projection_buckets", "status": "failed", "run_status": "failed"},
        {
            "task_verdict": {
                "status": "failed",
                "source": "gatekeeper",
                "summary": "Stored projection should keep stable bucket entries.",
                "buckets": {
                    "blocking": [True, "real blocker", {"label": "structured blocker"}],
                    "residual_risk": [False],
                },
            },
            "evidence_buckets": {
                "residual_risk": [False, "manual risk"],
                "unknown": ["not a stable bucket"],
            },
        },
    )

    assert projection["task_verdict"]["buckets"]["blocking"] == [
        {"label": "real blocker"},
        {"label": "structured blocker"},
    ]
    assert projection["task_verdict"]["buckets"]["residual_risk"] == []
    assert projection["evidence_buckets"] == {"residual_risk": [{"label": "manual risk"}]}


@pytest.mark.parametrize("iter_value", [True, "2", 1.5])
def test_takeaway_display_iter_requires_integer_sequence(iter_value) -> None:
    assert display_iter(iter_value) is None

    iteration = build_legacy_iteration_takeaway(
        {
            "id": "legacy_run",
            "status": "succeeded",
            "current_iter": iter_value,
            "summary_md": "# Loopora Run Summary\n\nLegacy run completed.",
        }
    )

    assert iteration is not None
    assert iteration["iter"] == 0
    assert iteration["display_iter"] == 1


def test_takeaway_role_source_and_legacy_failure_fields_require_literal_values() -> None:
    role = build_role_takeaway_from_handoff(
        {
            "source": {
                "iter": "4",
                "step_order": "8",
                "step_id": "builder_step",
                "runtime_role": "generator",
            },
            "status": "passed",
            "summary": "done",
            "blocking_items": ["real blocker", True],
            "evidence_refs": ["ev_001", False],
        }
    )

    assert role["id"].startswith("iter-0-")
    assert role["step_order"] == 0
    assert role["blocking_item"] == "real blocker"
    assert role["evidence_refs"] == ["ev_001"]

    malformed_role = build_role_takeaway_from_handoff(
        {
            "source": {"iter": 0, "step_order": 1, "step_id": "bad_shape"},
            "status": "blocked",
            "summary": True,
            "recommended_next_action": 7,
            "blocking_items": "string blocker",
            "evidence_refs": "ev_bad",
        }
    )

    assert malformed_role["summary"] == ""
    assert malformed_role["next_action"] == ""
    assert malformed_role["blocking_item"] == ""
    assert malformed_role["evidence_refs"] == []

    malformed_identity_role = build_role_takeaway_from_handoff(
        {
            "source": {
                "iter": 0,
                "step_order": 0,
                "step_id": True,
                "role_name": True,
                "runtime_role": True,
                "archetype": True,
            },
            "status": "passed",
            "summary": "done",
        }
    )

    assert malformed_identity_role["role_name"] == "-"
    assert malformed_identity_role["step_id"] == ""
    assert malformed_identity_role["archetype"] == ""
    assert "True" not in malformed_identity_role["id"]

    legacy_gatekeeper_iteration = build_legacy_iteration_takeaway(
        {
            "id": "legacy_blocker",
            "status": "failed",
            "current_iter": 0,
            "summary_md": "",
            "last_verdict_json": {
                "passed": False,
                "blocking_issues": "full blocker",
                "hard_constraint_violations": [True, "hard blocker"],
            },
        }
    )

    assert legacy_gatekeeper_iteration is not None
    assert legacy_gatekeeper_iteration["roles"][0]["blocking_item"] == "full blocker"

    iteration = build_legacy_iteration_takeaway(
        {
            "id": "legacy_run",
            "status": "failed",
            "current_iter": 0,
            "summary_md": "",
            "last_verdict_json": {
                "passed": False,
                "priority_failures": [
                    {
                        "role": "generator",
                        "error_code": "provider_failed",
                        "attempts": "2",
                        "degraded": "false",
                    }
                ],
            },
        }
    )

    assert iteration is not None
    blocking_item = iteration["roles"][0]["blocking_item"]
    assert "provider_failed" in blocking_item
    assert "attempts=2" not in blocking_item
    assert "degraded" not in blocking_item


def test_api_run_observation_snapshot_is_bounded_and_redacted(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Snapshot Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])

    for index in range(45):
        service.repository.append_event(
            run["id"],
            "run_finished",
            {"status": "succeeded", "reason": f"snapshot timeline {index}", "iter": index},
        )
    for index in range(2050):
        service.repository.append_event(
            run["id"],
            "role_started",
            {"role": "generator", "step_id": "builder_step", "iter": index},
            role="generator",
        )
    marker = "UNIQUE-SNAPSHOT-SECRET-MARKER"
    redacted_event = service.repository.append_event(
        run["id"],
        "codex_event",
        {
            "type": "command",
            "message": "uv run pytest -q",
            "prompt": marker,
            "json_schema": {"marker": marker},
        },
        role="generator",
    )

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/observation-snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["run"]["id"] == run["id"]
    assert payload["latest_event_id"] == redacted_event["id"]
    assert len(payload["timeline_events"]) == 40
    assert len(payload["console_events"]) == 160
    assert len(payload["progress_events"]) == 2000
    assert payload["key_takeaways"]["run_status"] == "succeeded"
    assert 0 < payload["key_takeaways"]["source_event_id"] <= payload["latest_event_id"]
    assert marker not in json.dumps(payload, ensure_ascii=False)

    html_response = client.get(f"/runs/{run['id']}")
    assert html_response.status_code == 200
    assert marker not in html_response.text
    timeline_text = (Path(run["runs_dir"]) / "timeline" / "events.jsonl").read_text(encoding="utf-8")
    assert marker not in timeline_text
    assert "uv run pytest -q" in json.dumps(payload["console_events"], ensure_ascii=False)


def test_api_run_observation_snapshot_projects_stable_timeline_events(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Parallel Snapshot Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.repository.append_event(
        run["id"],
        "role_request_prepared",
        {"role_name": "Builder", "role": "builder", "step_id": "build", "iter": 0},
        role="builder",
    )
    payload = {
        "iter": 0,
        "parallel_group": "inspection_pack",
        "step_orders": [1, 2],
        "step_ids": ["inspect_a", "inspect_b"],
    }
    service.repository.append_event(run["id"], "parallel_group_started", payload)
    service.repository.append_event(run["id"], "parallel_group_finished", payload)
    service.repository.append_event(
        run["id"],
        "control_triggered",
        {"signal": "gatekeeper_rejected", "role_id": "guide", "reason": "needs repair"},
    )
    service.repository.append_event(
        run["id"],
        "run_finished",
        {"status": "succeeded", "reason": "legacy_terminal_event_without_verdict"},
    )

    assert "role_request_prepared" in TIMELINE_EVENT_TYPES
    assert "control_triggered" in TIMELINE_EVENT_TYPES
    assert "parallel_group_started" in TIMELINE_EVENT_TYPES
    assert "run_finished" in TIMELINE_EVENT_TYPES
    assert "parallel_group_started" in PROGRESS_EVENT_TYPES
    assert "run_finished" in PROGRESS_EVENT_TYPES
    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/observation-snapshot")

    assert response.status_code == 200
    snapshot = response.json()
    timeline_events = [event for event in snapshot["timeline_events"] if event["event_type"].startswith("parallel_group_")]
    timeline_event_by_type = {event["event_type"]: event for event in snapshot["timeline_events"]}
    progress_types = [event["event_type"] for event in snapshot["progress_events"]]
    assert timeline_event_by_type["role_request_prepared"]["title"] == "Role request prepared"
    assert timeline_event_by_type["control_triggered"]["title"] == "Control triggered"
    assert [event["event_type"] for event in timeline_events] == ["parallel_group_started", "parallel_group_finished"]
    assert timeline_events[0]["title"] == "Parallel review started"
    assert timeline_events[0]["detail"] == "inspection_pack, steps=2"
    assert timeline_event_by_type["run_finished"]["detail"] == (
        "legacy_terminal_event_without_verdict, task_verdict_status=not_evaluated"
    )
    assert "parallel_group_started" in progress_types
    assert "parallel_group_finished" in progress_types
    assert "run_finished" in progress_types


def test_api_run_observation_snapshot_uses_persisted_takeaway_projection(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Snapshot Projection Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    marker = "LIVE-ARTIFACT-UPDATE-AFTER-PROJECTION"
    handoff_path = next(Path(run["runs_dir"]).glob("iterations/iter_*/steps/*/handoff.json"))
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff["summary"] = marker
    handoff_path.write_text(json.dumps(handoff, ensure_ascii=False), encoding="utf-8")
    late_event = service.repository.append_event(
        run["id"],
        "codex_event",
        {"type": "stdout", "message": "late non-projection event"},
        role="generator",
    )

    client = TestClient(build_app(service=service))
    snapshot_response = client.get(f"/api/runs/{run['id']}/observation-snapshot")
    live_response = client.get(f"/api/runs/{run['id']}/key-takeaways")

    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    assert snapshot_payload["latest_event_id"] == late_event["id"]
    assert snapshot_payload["key_takeaways"]["source_event_id"] < snapshot_payload["latest_event_id"]
    assert marker not in json.dumps(snapshot_payload["key_takeaways"], ensure_ascii=False)
    assert live_response.status_code == 200
    assert marker in json.dumps(live_response.json(), ensure_ascii=False)


def test_api_run_observation_snapshot_normalizes_legacy_takeaway_projection_shape(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Legacy Snapshot Projection Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    legacy_event = service.repository.append_event(
        run["id"],
        "codex_event",
        {"type": "stdout", "message": "legacy projection cutoff"},
        role="generator",
    )
    service.repository.record_run_takeaway_projection(
        run["id"],
        legacy_event["id"],
        {
            "run_status": "succeeded",
            "task_verdict": {"status": "passed", "source": "gatekeeper", "summary": "legacy shape", "buckets": {}},
            "iterations": [],
        },
    )

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/observation-snapshot")

    assert response.status_code == 200
    key_takeaways = response.json()["key_takeaways"]
    assert key_takeaways["source_event_id"] == legacy_event["id"]
    assert key_takeaways["task_verdict_path"] == ""
    assert key_takeaways["evidence_buckets"] == {}
    assert key_takeaways["evidence_coverage"]["status"] == "pending"
    assert key_takeaways["evidence_coverage"]["coverage_path"] == ""
    assert key_takeaways["evidence_manifest"]["manifest_path"] == ""
    assert key_takeaways["evidence_manifest"]["claim_count"] == 0
    assert key_takeaways["evidence_count"] == 0


@pytest.mark.parametrize("event_type", ("control_completed", "control_failed"))
def test_control_events_refresh_persisted_takeaway_projection(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    event_type: str,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Control Projection Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    handoff_path = next(Path(run["runs_dir"]).glob("iterations/iter_*/steps/*/handoff.json"))
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    control_marker = f"{event_type}-snapshot-marker"
    later_marker = f"{event_type}-later-marker"
    handoff["summary"] = control_marker
    handoff_path.write_text(json.dumps(handoff, ensure_ascii=False), encoding="utf-8")
    control_event = service.append_run_event(
        run["id"],
        event_type,
        {"control_id": "audit_control", "signal": "no_evidence_progress", "evidence_refs": []},
    )
    handoff["summary"] = later_marker
    handoff_path.write_text(json.dumps(handoff, ensure_ascii=False), encoding="utf-8")
    late_event = service.repository.append_event(
        run["id"],
        "codex_event",
        {"type": "stdout", "message": "late non-projection event"},
        role="generator",
    )

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/observation-snapshot")

    assert response.status_code == 200
    payload = response.json()
    key_takeaways_text = json.dumps(payload["key_takeaways"], ensure_ascii=False)
    assert payload["latest_event_id"] == late_event["id"]
    assert payload["key_takeaways"]["source_event_id"] == control_event["id"]
    assert control_marker in key_takeaways_text
    assert later_marker not in key_takeaways_text


def test_run_takeaway_projection_backfills_existing_terminal_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Snapshot Backfill Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    with service.repository.transaction() as connection:
        connection.execute("DELETE FROM run_takeaway_projections WHERE run_id = ?", (run["id"],))

    restarted = service.__class__(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )
    snapshot = restarted.run_observation_snapshot(run["id"])

    assert 0 < snapshot["key_takeaways"]["source_event_id"] <= snapshot["latest_event_id"]
    assert snapshot["key_takeaways"]["iteration_count"] >= 1


def test_run_takeaway_projection_backfills_terminal_runs_with_only_generic_events(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Minimal Snapshot Backfill Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    latest_event_id = service.repository.latest_event_id(run["id"])
    service.repository.update_run(
        run["id"],
        status="succeeded",
        summary_md="# Loopora Run Summary\n\nLifecycle closed before any role takeaway event was written.\n",
    )
    with service.repository.transaction() as connection:
        connection.execute("DELETE FROM workdir_locks WHERE run_id = ?", (run["id"],))
        connection.execute("DELETE FROM run_takeaway_projections WHERE run_id = ?", (run["id"],))

    restarted = service.__class__(
        repository=service.repository,
        settings=service.settings,
        executor_factory=service.executor_factory,
    )
    snapshot = restarted.run_observation_snapshot(run["id"])

    assert snapshot["latest_event_id"] == latest_event_id
    assert snapshot["key_takeaways"]["source_event_id"] == latest_event_id
    assert snapshot["key_takeaways"]["run_status"] == "succeeded"
    assert snapshot["key_takeaways"]["iteration_count"] == 0
    assert "Lifecycle closed before any role takeaway event" in snapshot["key_takeaways"]["latest_summary"]


def test_api_run_observation_snapshot_uses_consistent_event_cutoff(
    monkeypatch,
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Snapshot Cutoff Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.repository.append_event(run["id"], "run_started", {"status": "running"})
    service.repository.append_event(
        run["id"],
        "role_started",
        {"role": "generator", "step_id": "initial_step", "iter": 0},
        role="generator",
    )
    service.repository.append_event(
        run["id"],
        "codex_event",
        {"type": "stdout", "message": "visible before cutoff"},
        role="generator",
    )

    original_recent_rows = service.repository._recent_event_rows_for_connection
    captured: dict[str, int] = {}

    def recent_rows_with_concurrent_append(connection, run_id: str, **kwargs):
        captured.setdefault("cutoff", int(kwargs.get("max_event_id") or 0))
        if "late_id" not in captured:
            late_event = service.repository.append_event(
                run_id,
                "role_started",
                {"role": "generator", "step_id": "late_step", "iter": 1},
                role="generator",
            )
            captured["late_id"] = late_event["id"]
        return original_recent_rows(connection, run_id, **kwargs)

    monkeypatch.setattr(service.repository, "_recent_event_rows_for_connection", recent_rows_with_concurrent_append)
    client = TestClient(build_app(service=service))
    response = client.get(f"/api/runs/{run['id']}/observation-snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["latest_event_id"] == captured["cutoff"]
    assert payload["key_takeaways"]["source_event_id"] == captured["cutoff"]
    for event in payload["timeline_events"] + payload["console_events"] + payload["progress_events"]:
        assert event["id"] <= payload["latest_event_id"]
        assert event["id"] != captured["late_id"]

    events_response = client.get(f"/api/runs/{run['id']}/events?after_id={payload['latest_event_id']}")
    assert events_response.status_code == 200
    assert any(event["id"] == captured["late_id"] for event in events_response.json())


def test_api_reveal_path_uses_native_host_shortcut(monkeypatch, service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    called: list[str] = []

    def fake_reveal(path: str) -> str:
        called.append(path)
        return path

    monkeypatch.setattr(web_module, "reveal_path", fake_reveal)
    response = client.post("/api/system/reveal-path", json={"path": str(sample_workdir)})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert called == [str(sample_workdir)]


def test_system_picker_requires_post_and_same_origin(monkeypatch, service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    called: list[str] = []

    def fake_pick_directory(start_path: str | None = None) -> str:
        called.append(start_path or "")
        return str(sample_workdir)

    monkeypatch.setattr(web_module, "pick_directory", fake_pick_directory)

    old_get = client.get(f"/api/system/pick-directory?start_path={sample_workdir}")
    assert old_get.status_code == 405
    assert called == []

    cross_origin = client.post(
        "/api/system/pick-directory",
        json={"start_path": str(sample_workdir)},
        headers={"Origin": "http://evil.example"},
    )
    assert cross_origin.status_code == 403
    assert "same origin" in cross_origin.json()["error"]
    assert called == []

    malformed_origin = client.post(
        "/api/system/pick-directory",
        json={"start_path": str(sample_workdir)},
        headers={"Origin": "http://testserver:bad"},
    )
    assert malformed_origin.status_code == 403
    assert "same origin" in malformed_origin.json()["error"]
    assert called == []

    same_origin = client.post(
        "/api/system/pick-directory",
        json={"start_path": str(sample_workdir)},
        headers={"Origin": "http://testserver"},
    )
    assert same_origin.status_code == 200
    assert same_origin.json()["path"] == str(sample_workdir)
    assert called == [str(sample_workdir)]


def test_system_reveal_rejects_cross_origin_before_callback(monkeypatch, service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    called: list[str] = []

    def fake_reveal(path: str) -> str:
        called.append(path)
        return path

    monkeypatch.setattr(web_module, "reveal_path", fake_reveal)
    response = client.post(
        "/api/system/reveal-path",
        json={"path": str(sample_workdir)},
        headers={"Referer": "http://evil.example/page"},
    )

    assert response.status_code == 403
    assert "same origin" in response.json()["error"]
    assert called == []


def test_api_json_endpoints_reject_invalid_json_body(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/markdown/render",
        content="{",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400
    assert "invalid JSON body" in response.json()["error"]

    invalid_utf8_response = client.post(
        "/api/markdown/render",
        content=b'{"markdown":"\xff"}',
        headers={"content-type": "application/json"},
    )

    assert invalid_utf8_response.status_code == 400
    assert "invalid JSON body" in invalid_utf8_response.json()["error"]
    assert "UTF-8" in invalid_utf8_response.json()["error"]


def test_api_json_endpoints_require_object_bodies(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post("/api/markdown/render", json=["not", "an", "object"])

    assert response.status_code == 400
    assert response.json()["error"] == "request body must be a JSON object"


def test_api_file_preview_reports_json_parse_errors(service_factory, sample_spec_file: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="JSON Preview Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    broken_json_path = sample_workdir / "broken.json"
    broken_json_path.write_text("{\n", encoding="utf-8")

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/files?run_id={run['id']}&root=workdir&path=broken.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert payload["content"] == "{\n"
    assert payload["parse_error"]


def test_api_file_preview_keeps_valid_jsonl_lines_when_some_are_broken(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="JSONL Preview Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    log_path = sample_workdir / "events.jsonl"
    log_path.write_text('{"event":"good"}\n{\n{"event":"also-good"}\n', encoding="utf-8")

    client = TestClient(build_app(service=service))
    response = client.get(f"/api/files?run_id={run['id']}&root=workdir&path=events.jsonl")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "file"
    assert '"event": "good"' in payload["content"]
    assert '"event": "also-good"' in payload["content"]
    assert payload["jsonl_parse_errors"] == [{"line": 2, "error": "Expecting property name enclosed in double quotes"}]


def test_api_run_events_and_stream_require_a_real_run(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    events_response = client.get("/api/runs/missing-run/events")
    assert events_response.status_code == 404
    assert "unknown run" in events_response.json()["error"]

    snapshot_response = client.get("/api/runs/missing-run/observation-snapshot")
    assert snapshot_response.status_code == 404
    assert "unknown run" in snapshot_response.json()["error"]

    stream_response = client.get("/api/runs/missing-run/stream")
    assert stream_response.status_code == 404
    assert "unknown run" in stream_response.json()["error"]


def test_api_run_lifecycle_reports_not_found_and_conflict_status_codes(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    missing_loop_response = client.post("/api/loops/missing-loop/runs")
    assert missing_loop_response.status_code == 404
    assert "unknown loop" in missing_loop_response.json()["error"]

    loop = service.create_loop(
        name="Conflict Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    service.start_run(loop["id"])

    conflict_response = client.post(f"/api/loops/{loop['id']}/runs")
    assert conflict_response.status_code == 409
    assert "active run" in conflict_response.json()["error"]


def test_api_run_lifecycle_rejects_web_headless_start_for_agent_first_loop(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    started = _start_agent_first_loop(service, tmp_path=tmp_path, workdir=sample_workdir)
    client = TestClient(build_app(service=service))

    response = client.post(f"/api/loops/{started['run']['loop_id']}/runs")

    assert response.status_code == 409
    payload = response.json()
    assert "agent-first Loop runs" in payload["error"]
    assert payload["agent_entry_start"]["slash_command"] == "/loopora-loop"
    assert payload["agent_entry_start"]["execution_plane"] == "agent_native"
    assert payload["agent_entry_start"]["linked_run_id"] == started["run"]["id"]
    assert payload["agent_entry_start"]["host_context_id"] == "web-api-agent-first"
    assert "loopora agent codex loop" in payload["agent_entry_start"]["loop_command"]
    assert "--context-id web-api-agent-first" in payload["agent_entry_start"]["loop_command"]
    assert len(service.get_loop(started["run"]["loop_id"])["runs"]) == 1


def test_api_runtime_activity_reports_running_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    loop = service.create_loop(
        name="Runtime Activity Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    service.start_run_async(run["id"])

    deadline = time.time() + 5
    while time.time() < deadline:
        current = service.get_run(run["id"])
        if current["status"] == "running":
            break
        time.sleep(0.05)

    client = TestClient(build_app(service=service))
    response = client.get("/api/runtime/activity")

    assert response.status_code == 200
    payload = response.json()
    assert payload["running_count"] >= 1
    assert payload["has_running_runs"] is True
    assert any(item["id"] == run["id"] and item["loop_name"] == "Runtime Activity Loop" for item in payload["runs"])

    service.stop_run(run["id"])


def test_api_local_asset_diagnostics_reports_orphans_and_missing_dirs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Diagnostics Workdir Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=1,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    assert loop["id"]
    run = service.start_run(loop["id"])
    run_dir = Path(run["runs_dir"])
    if run_dir.exists():
        shutil.rmtree(run_dir)
    orphan_run_dir = state_dir_for_workdir(sample_workdir) / "runs" / "run_orphan"
    orphan_run_dir.mkdir(parents=True)
    orphan_alignment_dir = state_dir_for_workdir(sample_workdir) / "alignment_sessions" / "align_orphan"
    orphan_alignment_dir.mkdir(parents=True)
    orphan_bundle_dir = app_home() / "bundles" / "bundle_orphan"
    orphan_bundle_dir.mkdir(parents=True)
    service.repository.create_bundle(
        {
            "id": "bundle_missing_dir",
            "name": "Missing Dir Bundle",
            "description": "",
            "collaboration_summary": "",
            "workdir": str(sample_workdir),
            "loop_id": "",
            "orchestration_id": "",
            "role_definition_ids": [],
            "source_bundle_id": "",
            "revision": 1,
            "imported_from_path": "",
        }
    )
    missing_bundle_dir = service._bundle_dir("bundle_missing_dir")
    if missing_bundle_dir.exists():
        shutil.rmtree(missing_bundle_dir)
    missing_registry_run_dir = state_dir_for_workdir(sample_workdir) / "runs" / "run_registry_missing"
    service.repository.upsert_local_asset_root(
        resource_type="run",
        resource_id="run_registry_missing",
        path=missing_registry_run_dir,
        workdir=str(sample_workdir),
        state="active",
    )

    client = TestClient(build_app(service=service))
    response = client.get("/api/diagnostics/local-assets")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"orphan_alignment_dirs", "orphan_bundle_dirs", "orphan_run_dirs", "record_without_dir"}
    assert any(item["session_id"] == "align_orphan" for item in payload["orphan_alignment_dirs"])
    assert any(item["bundle_id"] == "bundle_orphan" for item in payload["orphan_bundle_dirs"])
    assert any(item["run_id"] == "run_orphan" and item["source"] == "recent_workdir" for item in payload["orphan_run_dirs"])
    assert any(item["resource_type"] == "bundle" and item["resource_id"] == "bundle_missing_dir" for item in payload["record_without_dir"])
    assert any(item["resource_type"] == "run" and item["resource_id"] == run["id"] for item in payload["record_without_dir"])
    assert any(item["resource_type"] == "run" and item["resource_id"] == "run_registry_missing" for item in payload["record_without_dir"])


def test_api_run_stream_emits_redacted_stream_error_on_backend_failure() -> None:
    configure_logging()

    class FlakyService:
        def get_run(self, run_id: str) -> dict:
            return {"id": run_id, "status": "running", "loop_id": "loop_test"}

        def latest_run_event_id(self, run_id: str) -> int:
            assert run_id == "run_test"
            return 42

        def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            assert run_id == "run_test"
            assert after_id == 42
            assert limit == 200
            raise RuntimeError("database unavailable")

    client = TestClient(build_app(service=FlakyService()))

    with client.stream("GET", "/api/runs/run_test/stream?after_id=42") as response:
        assert response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert "event: stream_error" in body
    assert "database unavailable" not in body
    payload = json.loads(next(line.removeprefix("data: ") for line in body.splitlines() if line.startswith("data: ")))
    assert payload == {
        "run_id": "run_test",
        "after_id": 42,
        "error": "stream_unavailable",
        "retryable": True,
    }
    assert any(
        record.get("event") == "web.run_stream.failed" and (record.get("error") or {}).get("message") == "database unavailable"
        for record in _read_service_log_records()
    )


def test_api_unhandled_error_returns_stable_json_and_logs_exception() -> None:
    configure_logging()
    raw_error = "database unavailable for api-internal-error-test"

    class FlakyService:
        def latest_run_event_id(self, run_id: str) -> int:
            assert run_id == "run_test"
            raise RuntimeError(raw_error)

    client = TestClient(build_app(service=FlakyService()), raise_server_exceptions=False)

    response = client.get("/api/runs/run_test/events")

    assert response.status_code == 500
    assert response.json() == {"error": "internal server error"}
    assert raw_error not in response.text
    assert any(
        record.get("event") == "web.request.failed"
        and (record.get("error") or {}).get("message") == raw_error
        and (record.get("context") or {}).get("request_path") == "/api/runs/run_test/events"
        and (record.get("context") or {}).get("status_code") == 500
        for record in _read_service_log_records()
    )


def test_api_run_stream_logs_invalid_resume_cursor_and_keeps_request_cursor() -> None:
    configure_logging()
    captured: dict[str, int] = {}

    class CursorAwareService:
        def get_run(self, run_id: str) -> dict:
            return {"id": run_id, "status": "succeeded", "loop_id": "loop_test"}

        def latest_run_event_id(self, run_id: str) -> int:
            assert run_id == "run_test"
            return 10

        def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            assert run_id == "run_test"
            assert limit == 200
            captured["after_id"] = after_id
            return []

    client = TestClient(build_app(service=CursorAwareService()))

    with client.stream(
        "GET",
        "/api/runs/run_test/stream?after_id=7",
        headers={"Last-Event-ID": "not-a-number"},
    ) as response:
        assert response.status_code == 200
        assert "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()) == ""

    assert captured["after_id"] == 7
    record = next(item for item in _read_service_log_records() if item["event"] == "web.run_stream.resume_cursor_invalid")
    assert record["run_id"] == "run_test"
    assert record["context"]["after_id"] == 7
    assert record["context"]["latest_event_id"] == 10
    assert record["context"]["invalid_last_event_id"] == "not-a-number"


def test_api_run_stream_ignores_resume_cursor_beyond_current_run_events() -> None:
    configure_logging()
    captured: dict[str, int] = {}

    class CursorAwareService:
        def get_run(self, run_id: str) -> dict:
            return {"id": run_id, "status": "succeeded", "loop_id": "loop_test"}

        def latest_run_event_id(self, run_id: str) -> int:
            assert run_id == "run_test"
            return 10

        def stream_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            assert run_id == "run_test"
            assert limit == 200
            captured["after_id"] = after_id
            return []

    client = TestClient(build_app(service=CursorAwareService()))

    with client.stream(
        "GET",
        "/api/runs/run_test/stream?after_id=7",
        headers={"Last-Event-ID": "11"},
    ) as response:
        assert response.status_code == 200
        assert "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()) == ""

    assert captured["after_id"] == 7
    record = next(item for item in _read_service_log_records() if item["event"] == "web.run_stream.resume_cursor_invalid")
    assert record["run_id"] == "run_test"
    assert record["context"]["after_id"] == 7
    assert record["context"]["latest_event_id"] == 10
    assert record["context"]["invalid_last_event_id"] == "11"


def test_web_logs_completed_requests(service_factory) -> None:
    configure_logging()
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.get("/tutorial")

    assert response.status_code == 200
    records = _read_service_log_records()
    record = next(item for item in records if item["event"] == "web.request.completed" and item["context"]["request_path"] == "/tutorial")
    assert record["context"]["status_code"] == 200
    assert record["context"]["duration_ms"] >= 0


def test_api_stop_run_rejects_finished_runs(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Finished Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    client = TestClient(build_app(service=service))

    response = client.post(f"/api/runs/{run['id']}/stop")

    assert response.status_code == 409
    assert "cannot stop run in status" in response.json()["error"]


def test_run_detail_separates_status_verdict_and_reruns_terminal_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Rerun From Detail Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    client = TestClient(build_app(service=service))

    _assert_run_detail_terminal_actions_page(client, run, loop)

    _accept_run_result_and_assert_observation_event(client, service, run, loop)
    accepted_events_after_first_post = service.recent_run_events(run["id"], event_types={"run_result_accepted"})
    first_accept_event_id = accepted_events_after_first_post[-1]["id"]
    accepted_task_verdict_status = accepted_events_after_first_post[-1]["payload"]["task_verdict_status"]
    page_after_accept = client.get(f"/runs/{run['id']}")
    assert page_after_accept.status_code == 200
    assert 'data-testid="run-accepted-result-state"' in page_after_accept.text
    assert _expected_recorded_verdict_page_text(accepted_task_verdict_status) in page_after_accept.text
    assert 'data-testid="run-accept-result-button"' not in page_after_accept.text
    duplicate_accept_response = client.post(f"/runs/{run['id']}/accept", follow_redirects=False)
    assert duplicate_accept_response.status_code == 303
    accepted_events_after_duplicate_post = service.recent_run_events(run["id"], event_types={"run_result_accepted"})
    assert [event["id"] for event in accepted_events_after_duplicate_post] == [first_accept_event_id]
    acceptance_state = service.run_result_acceptance_state(run["id"])
    assert acceptance_state["accepted"] is True
    assert acceptance_state["event_id"] == first_accept_event_id
    snapshot_response = client.get(f"/api/runs/{run['id']}/observation-snapshot")
    assert snapshot_response.status_code == 200
    snapshot_payload = snapshot_response.json()
    accepted_timeline_events = [event for event in snapshot_payload["timeline_events"] if event["event_type"] == "run_result_accepted"]
    assert accepted_timeline_events
    assert accepted_timeline_events[-1]["title"] == _expected_recorded_verdict_title(accepted_task_verdict_status)
    assert snapshot_payload["key_takeaways"]["source_event_id"] <= snapshot_payload["latest_event_id"]

    rerun_response = client.post(f"/runs/{run['id']}/rerun", follow_redirects=False)

    assert rerun_response.status_code == 303
    new_run_id = rerun_response.headers["location"].removeprefix("/runs/")
    assert new_run_id
    assert new_run_id != run["id"]
    assert service.get_run(new_run_id)["loop_id"] == loop["id"]
    _wait_for_run_terminal_status(service, new_run_id)


def _assert_run_detail_terminal_actions_page(client: TestClient, run: dict, loop: dict) -> None:
    page_response = client.get(f"/runs/{run['id']}")
    assert page_response.status_code == 200
    assert "Run status" in page_response.text
    assert "Task verdict" in page_response.text
    assert 'data-testid="run-status-card"' in page_response.text
    assert 'data-testid="run-task-verdict-card"' in page_response.text
    assert 'data-testid="run-latest-event-card"' in page_response.text
    assert 'data-testid="run-agent-handoff-card"' in page_response.text
    assert 'data-testid="run-export-loop-button"' in page_response.text
    assert f"/bundles/derive/export?loop_id={loop['id']}" in page_response.text
    assert 'data-testid="run-accept-result-button"' in page_response.text
    assert 'data-testid="run-rerun-button"' in page_response.text
    assert "Run next evidence pass" in page_response.text
    assert '<span data-lang="en">Rerun</span>' not in page_response.text
    assert 'id="stop-run"' not in page_response.text

    export_response = client.get(f"/bundles/derive/export?loop_id={loop['id']}")
    assert export_response.status_code == 200
    assert export_response.headers["content-type"].startswith("application/yaml")
    assert "Rerun From Detail Loop" in export_response.text


def _wait_for_run_terminal_status(service, run_id: str) -> None:
    deadline = time.time() + 5
    while time.time() < deadline:
        new_run = service.get_run(run_id)
        if new_run["status"] in {"succeeded", "failed", "stopped"}:
            break
        time.sleep(0.05)
    assert service.get_run(run_id)["status"] in {"succeeded", "failed", "stopped"}


def test_run_detail_keeps_generic_rerun_for_passing_terminal_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Passing Detail Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.rerun(loop["id"])
    service.repository.update_run(
        run["id"],
        task_verdict={
            "status": "passed",
            "source": "gatekeeper",
            "summary": "Required proof is complete.",
            "buckets": {"proven": [{"label": "all required checks"}]},
        },
    )
    client = TestClient(build_app(service=service))

    page_response = client.get(f"/runs/{run['id']}")

    assert page_response.status_code == 200
    assert 'data-testid="run-rerun-button"' in page_response.text
    assert '<span data-lang="en">Rerun</span>' in page_response.text
    assert "Run next evidence pass" not in page_response.text
    assert "Record passing verdict" in page_response.text


def test_run_detail_rerun_routes_agent_first_terminal_run_back_to_slash_command(
    service_factory,
    tmp_path: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    started = _start_agent_first_loop(service, tmp_path=tmp_path, workdir=sample_workdir)
    service.repository.update_run(
        started["run"]["id"],
        status="succeeded",
        task_verdict={
            "status": "insufficient_evidence",
            "source": "gatekeeper",
            "summary": "Required coverage still lacks direct evidence.",
            "buckets": {
                "proven": [],
                "weak": [],
                "unproven": [{"id": "coverage.required", "summary": "Required coverage is still missing."}],
                "blocking": [],
                "residual_risk": [],
            },
        },
        summary_md="# Loopora Run Summary\n\nLifecycle closed; task evidence still belongs to the Agent-first lane.\n",
    )
    client = TestClient(build_app(service=service))

    page_response = client.get(f"/runs/{started['run']['id']}")

    assert page_response.status_code == 200
    assert 'data-testid="run-agent-entry-start-guide"' in page_response.text
    assert 'data-testid="run-agent-entry-copy-command-hero"' in page_response.text
    assert 'data-testid="run-agent-entry-copy-command"' in page_response.text
    assert "/loopora-loop" in page_response.text
    assert "loopora agent codex loop" in page_response.text
    assert "--context-id web-api-agent-first" in page_response.text
    assert "开启下一轮" in page_response.text
    assert "复制续跑命令" in page_response.text
    assert 'data-agent-entry-command-copy' in page_response.text
    assert 'data-copy-value="LOOPORA_AGENT_ENTRY_SOURCE=codex_project_skill loopora agent codex loop' in page_response.text
    assert 'data-testid="run-rerun-button"' not in page_response.text

    rerun_response = client.post(f"/runs/{started['run']['id']}/rerun")

    assert rerun_response.status_code == 409
    rerun_payload = rerun_response.json()
    assert "agent-first Loop runs" in rerun_payload["error"]
    assert rerun_payload["agent_entry_start"]["next_loop_action"] == "start_next_run_for_unproven_verdict"
    assert rerun_payload["agent_entry_start"]["linked_task_verdict_status"] == "insufficient_evidence"
    assert len(service.get_loop(started["run"]["loop_id"])["runs"]) == 1


def test_run_accept_result_rejects_active_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Active Accept Loop",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    run = service.start_run(loop["id"])
    client = TestClient(build_app(service=service))

    response = client.post(f"/runs/{run['id']}/accept")

    assert response.status_code == 409
    assert "cannot accept run result in status" in response.json()["error"]


def test_run_accept_result_keeps_audit_shape_when_evidence_summary_is_unavailable(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    monkeypatch,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    run_id = _create_api_loop_run(client, sample_spec_file, sample_workdir)
    _wait_for_run_success(client, run_id)

    def fail_takeaways(_run: dict) -> dict:
        raise RuntimeError("raw artifact read failed")

    monkeypatch.setattr(service_run_lifecycle, "build_run_key_takeaways", fail_takeaways)

    response = client.post(f"/runs/{run_id}/accept", follow_redirects=False)

    assert response.status_code == 303
    accepted_event = service.recent_run_events(run_id, event_types={"run_result_accepted"})[-1]
    payload = accepted_event["payload"]
    assert payload["evidence_source_event_id"] < accepted_event["id"]
    assert payload["evidence_available"] is False
    assert payload["evidence_error"] == "acceptance_evidence_unavailable"
    assert payload["judgment_contract"] == empty_judgment_contract()
    assert payload["run_contract_path"] == ""
    assert payload["judgment_contract_summary"] == ""
    assert payload["check_mode"] == ""
    assert payload["check_count"] == 0
    assert payload["completion_mode"] == ""
    assert payload["workflow_preset"] == ""
    assert payload["coverage_targets"] == []
    assert payload["loop_fit_reasons"] == []
    assert payload["execution_strategy"] == []
    assert payload["local_governance"] == []
    assert payload["role_postures"] == []
    assert payload["judgment_tradeoffs"] == []
    assert payload["success_surface"] == []
    assert payload["fake_done_states"] == []
    assert payload["evidence_preferences"] == []
    assert payload["residual_risk"] == ""
    assert payload["task_verdict_path"] == ""
    assert payload["coverage_path"] == ""
    assert payload["manifest_path"] == ""
    assert payload["evidence_count"] == 0
    assert payload["evidence_bucket_counts"] == {
        "proven": 0,
        "weak": 0,
        "unproven": 0,
        "blocking": 0,
        "residual_risk": 0,
    }


def test_api_loop_creation_supports_provider_specific_defaults(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    claude_response = client.post(
        "/api/loops",
        json={
            "name": "Claude Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "claude",
            "model": "",
            "reasoning_effort": "xhigh",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert claude_response.status_code == 201
    claude_loop = claude_response.json()["loop"]
    assert claude_loop["executor_kind"] == "claude"
    assert claude_loop["model"] == CLAUDE_DEFAULT_MODEL
    assert claude_loop["reasoning_effort"] == "max"

    codex_response = client.post(
        "/api/loops",
        json={
            "name": "Codex Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "reasoning_effort": "",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert codex_response.status_code == 201
    codex_loop = codex_response.json()["loop"]
    assert codex_loop["executor_kind"] == "codex"
    assert codex_loop["model"] == ""
    assert codex_loop["reasoning_effort"] == "medium"

    opencode_response = client.post(
        "/api/loops",
        json={
            "name": "OpenCode Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "opencode",
            "model": "",
            "reasoning_effort": "default",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert opencode_response.status_code == 201
    opencode_loop = opencode_response.json()["loop"]
    assert opencode_loop["executor_kind"] == "opencode"
    assert opencode_loop["model"] == OPENCODE_DEFAULT_MODEL
    assert opencode_loop["reasoning_effort"] == ""


def test_api_loop_creation_rejects_invalid_numeric_settings(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Broken Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "max_iters": "abc",
        },
    )

    assert response.status_code == 400
    assert "numeric loop settings" in response.json()["error"]

    bool_response = client.post(
        "/api/loops",
        json={
            "name": "Broken Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "max_iters": False,
        },
    )

    assert bool_response.status_code == 400
    assert "numeric loop settings" in bool_response.json()["error"]

    fractional_response = client.post(
        "/api/loops",
        json={
            "name": "Broken Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "max_iters": 1.5,
        },
    )

    assert fractional_response.status_code == 400
    assert "numeric loop settings" in fractional_response.json()["error"]

    non_finite_response = client.post(
        "/api/loops",
        json={
            "name": "Broken Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "delta_threshold": "nan",
        },
    )

    assert non_finite_response.status_code == 400
    assert "finite" in non_finite_response.json()["error"]


def test_api_loop_creation_supports_command_mode(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Command Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "executor_mode": "command",
            "command_cli": "codex",
            "command_args_text": "\n".join(
                [
                    "exec",
                    "--json",
                    "--cd",
                    "{workdir}",
                    "--sandbox",
                    "{sandbox}",
                    "--output-schema",
                    "{schema_path}",
                    "--output-last-message",
                    "{output_path}",
                    "{prompt}",
                ]
            ),
            "model": "",
            "reasoning_effort": "",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["executor_mode"] == "command"
    assert loop["command_cli"] == "codex"
    assert "{schema_path}" in loop["command_args_text"]


def test_api_loop_creation_accepts_role_model_overrides(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Role Models Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "role_models": {
                "generator": "gpt-5.4-mini",
                "verifier": "gpt-5.4",
            },
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["role_models_json"] == {
        "builder": "gpt-5.4-mini",
        "gatekeeper": "gpt-5.4",
    }


def test_prompt_template_download_and_validation_endpoints(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    template_response = client.get("/api/prompts/templates/builder.md")
    assert template_response.status_code == 200
    markdown_text = template_response.text
    assert "archetype: builder" in markdown_text

    localized_template_response = client.get("/api/prompts/templates/builder.md?locale=zh")
    assert localized_template_response.status_code == 200
    assert "# Builder Prompt" in localized_template_response.text
    assert "archetype: builder" in localized_template_response.text

    validation_response = client.post(
        "/api/prompts/validate",
        json={
            "markdown": markdown_text,
            "archetype": "builder",
        },
    )
    assert validation_response.status_code == 200
    assert validation_response.json()["ok"] is True

    mismatch_response = client.post(
        "/api/prompts/validate",
        json={
            "markdown": markdown_text,
            "archetype": "gatekeeper",
        },
    )
    assert mismatch_response.status_code == 200
    assert mismatch_response.json()["ok"] is False


def test_api_can_create_orchestration_and_use_it_for_loop(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    orchestration_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Inspect First",
            "description": "Inspector before Builder.",
            "workflow": {"preset": "inspect_first"},
        },
    )
    assert orchestration_response.status_code == 201
    orchestration = orchestration_response.json()["orchestration"]
    assert orchestration["name"] == "Custom Inspect First"
    assert orchestration["workflow_json"]["preset"] == "inspect_first"

    list_response = client.get("/api/orchestrations")
    assert list_response.status_code == 200
    assert any(item["id"] == orchestration["id"] for item in list_response.json())

    update_response = client.put(
        f"/api/orchestrations/{orchestration['id']}",
        json={
            "name": "Custom Build First",
            "description": "Updated description.",
            "workflow": {"preset": "build_first"},
        },
    )
    assert update_response.status_code == 200
    updated_orchestration = update_response.json()["orchestration"]
    assert updated_orchestration["name"] == "Custom Build First"
    assert updated_orchestration["workflow_json"]["preset"] == "build_first"

    loop_response = client.post(
        "/api/loops",
        json={
            "name": "Uses Custom Orchestration",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "orchestration_id": updated_orchestration["id"],
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "max_iters": 3,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "start_immediately": False,
        },
    )
    assert loop_response.status_code == 201
    loop = loop_response.json()["loop"]
    assert loop["orchestration"]["id"] == updated_orchestration["id"]
    assert loop["orchestration"]["name"] == "Custom Build First"
    assert loop["workflow_json"]["preset"] == "build_first"


def test_api_orchestration_hydrates_role_snapshots_from_role_definition_id(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Uses Role Definition Snapshot",
            "description": "Hydrates missing role fields from a role definition.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "role_definition_id": role_definition["id"]},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 201
    orchestration = response.json()["orchestration"]
    builder_role = orchestration["workflow_json"]["roles"][0]
    assert builder_role["name"] == "Release Builder"
    assert builder_role["prompt_ref"] == "release-builder.md"
    assert builder_role["executor_kind"] == "claude"
    assert builder_role["model"] == "gpt-5.4-mini"
    assert orchestration["prompt_files_json"]["release-builder.md"].startswith("---\nversion: 1")


def test_api_orchestration_rejects_unknown_role_definition_ids(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Broken Role Definition Reference",
            "description": "Should fail fast.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "role_definition_id": "role_missing"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 404
    assert "unknown role definition: role_missing" in response.json()["error"]


def test_api_orchestration_rejects_conflicting_role_definition_snapshot_fields(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Conflicting Role Snapshot",
            "description": "Should fail when snapshot fields conflict with the role definition.",
            "workflow": {
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                        "model": "gpt-5.4",
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert response.status_code == 400
    assert f"conflicts with role_definition_id {role_definition['id']} on model" in response.json()["error"]


def test_api_orchestration_rejects_conflicting_prompt_files_for_role_definition_id(service_factory) -> None:
    service = service_factory(scenario="success")
    role_definition = service.create_role_definition(
        name="Release Builder",
        description="Ships focused release work.",
        archetype="builder",
        prompt_ref="release-builder.md",
        prompt_markdown="""---
version: 1
archetype: builder
---

Focus on safe release work.
""",
        executor_kind="claude",
        executor_mode="preset",
        model="gpt-5.4-mini",
        reasoning_effort="high",
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Conflicting Role Prompt Snapshot",
            "description": "Should fail when prompt_files override a role definition prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {
                        "id": "builder",
                        "role_definition_id": role_definition["id"],
                    },
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "release-builder.md": """---
version: 1
archetype: builder
---

Focus on risky release work.
""",
            },
        },
    )

    assert response.status_code == 400
    assert f"conflicts with role_definition_id {role_definition['id']} on prompt_markdown" in response.json()["error"]


def test_api_orchestration_update_preserves_existing_prompt_files_when_omitted(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Builder Flow",
            "description": "Uses a custom builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )
    assert create_response.status_code == 201
    orchestration_id = create_response.json()["orchestration"]["id"]

    update_response = client.put(
        f"/api/orchestrations/{orchestration_id}",
        json={
            "name": "Custom Builder Flow v2",
            "description": "Workflow changed, prompt payload omitted.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_retry_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert update_response.status_code == 200
    orchestration = update_response.json()["orchestration"]
    assert orchestration["name"] == "Custom Builder Flow v2"
    assert orchestration["workflow_json"]["steps"][0]["id"] == "builder_retry_step"
    assert orchestration["prompt_files_json"]["custom-builder.md"].startswith("---\nversion: 1")


def test_api_orchestration_update_prunes_unused_prompt_files(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/orchestrations",
        json={
            "name": "Custom Builder Flow",
            "description": "Uses a custom builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "custom-builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "custom-builder.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )
    assert create_response.status_code == 201
    orchestration_id = create_response.json()["orchestration"]["id"]

    update_response = client.put(
        f"/api/orchestrations/{orchestration_id}",
        json={
            "name": "Builtin Builder Flow",
            "description": "Now uses the built-in builder prompt.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
        },
    )

    assert update_response.status_code == 200
    orchestration = update_response.json()["orchestration"]
    assert orchestration["workflow_json"]["roles"][0]["prompt_ref"] == "builder.md"
    assert list(orchestration["prompt_files_json"].keys()) == ["builder.md"]
    assert "custom-builder.md" not in orchestration["prompt_files_json"]


def test_api_orchestration_rejects_shared_prompt_ref_with_mismatched_archetype(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Shared Prompt Ref Mismatch",
            "description": "Should fail when one prompt ref is reused across incompatible archetypes.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "shared.md"},
                    {"id": "inspector", "archetype": "inspector", "prompt_ref": "shared.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                    {"id": "inspector_step", "role_id": "inspector"},
                ],
            },
            "prompt_files": {
                "shared.md": """---
version: 1
archetype: builder
---

Keep the builder prompt stable.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt archetype builder does not match expected archetype inspector" in response.json()["error"]


def test_api_orchestration_rejects_unsafe_prompt_ref_paths(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Unsafe Prompt Ref",
            "description": "Should fail when a prompt ref escapes the asset root.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "../escape.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

This should never be written outside prompts/.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_orchestration_rejects_invalid_prompt_file_keys(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/orchestrations",
        json={
            "name": "Unsafe Prompt Files",
            "description": "Should reject invalid prompt_files keys instead of ignoring them.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

This key should be rejected instead of silently dropped.
""",
            },
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_get_orchestration_sanitizes_invalid_persisted_prompt_file_keys(service_factory) -> None:
    service = service_factory(scenario="success")
    service.repository.create_orchestration(
        {
            "id": "orch_legacy",
            "name": "Legacy Builder Flow",
            "description": "Contains stale invalid prompt file keys.",
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "prompt_files": {
                "../escape.md": """---
version: 1
archetype: builder
---

Legacy invalid key.
""",
                "builder.md": """---
version: 1
archetype: builder
---

Legit builder prompt.
""",
            },
        }
    )
    client = TestClient(build_app(service=service))

    response = client.get("/api/orchestrations/orch_legacy")

    assert response.status_code == 200
    orchestration = response.json()
    assert list(orchestration["prompt_files_json"].keys()) == ["builder.md"]


def test_builtin_orchestration_form_route_is_read_only(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    builtin = service.get_orchestration("builtin:build_first")
    custom_before = [item for item in service.list_orchestrations() if item["source"] == "custom"]

    response = client.post(
        "/orchestrations/builtin:build_first/edit",
        data={
            "name": "Attempted Custom Copy",
            "description": "Should not be created from the built-in edit route.",
            "workflow_preset": "build_first",
            "workflow_json": json.dumps(builtin["workflow_json"], ensure_ascii=False),
            "prompt_files_json": json.dumps(builtin["prompt_files_json"], ensure_ascii=False),
        },
    )

    assert response.status_code == 200
    assert "built-in orchestrations are read-only" in response.text
    custom_after = [item for item in service.list_orchestrations() if item["source"] == "custom"]
    assert custom_after == custom_before


def test_blank_orchestration_form_does_not_fall_back_to_build_first(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/orchestrations/new",
        data={
            "name": "Blank Starter",
            "description": "Should stay blank until steps are added.",
            "workflow_json": json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False),
            "prompt_files_json": json.dumps({}, ensure_ascii=False),
        },
    )

    assert response.status_code == 200
    assert "workflow requires at least one role" in response.text
    custom_records = [item for item in service.list_orchestrations() if item["source"] == "custom"]
    assert custom_records == []


def test_api_can_create_round_based_loop_without_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Round Builder Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "iteration_interval_seconds": 0.1,
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    loop = response.json()["loop"]
    assert loop["completion_mode"] == "rounds"
    assert loop["iteration_interval_seconds"] == 0.1
    assert loop["workflow_json"]["steps"][0]["role_id"] == "builder"


def test_api_rejects_gatekeeper_mode_without_finish_gatekeeper(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid Gate Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "gatekeeper",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "gatekeeper completion mode" in response.json()["error"]


def test_api_rejects_duplicate_workflow_step_ids(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Duplicate Step Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "shared_step", "role_id": "builder"},
                    {"id": "shared_step", "role_id": "inspector"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "duplicate workflow step id" in response.json()["error"]


def test_api_normalizes_boolean_like_workflow_step_session_flags(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Session Flag Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "inspector", "name": "Inspector", "archetype": "inspector", "prompt_ref": "inspector.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "inherit_session": "false"},
                    {"id": "inspector_step", "role_id": "inspector", "inherit_session": "true"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 201
    steps = response.json()["loop"]["workflow_json"]["steps"]
    assert steps[0]["inherit_session"] is False
    assert steps[1]["inherit_session"] is True


def test_api_rejects_invalid_workflow_step_session_flag(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid Session Flag Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "inherit_session": "sometimes"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "inherit_session must be a boolean" in response.json()["error"]


def test_api_rejects_finish_run_for_non_gatekeeper_steps(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/loops",
        json={
            "name": "Invalid On Pass Loop",
            "spec_path": str(sample_spec_file),
            "workdir": str(sample_workdir),
            "executor_kind": "codex",
            "model": "gpt-5.4",
            "reasoning_effort": "medium",
            "completion_mode": "rounds",
            "max_iters": 2,
            "max_role_retries": 1,
            "delta_threshold": 0.005,
            "trigger_window": 2,
            "regression_window": 2,
            "workflow": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                ],
                "steps": [
                    {"id": "builder_step", "role_id": "builder", "on_pass": "finish_run"},
                ],
            },
            "start_immediately": False,
        },
    )

    assert response.status_code == 400
    assert "non-gatekeeper steps only support on_pass=continue" in response.json()["error"]


def test_api_role_definition_crud(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    create_response = client.post(
        "/api/role-definitions",
        json={
            "name": "Release Builder",
            "description": "Ship focused release changes.",
            "posture_notes": "Prefer maintainability evidence before calling this ready.",
            "archetype": "builder",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Focus on scoped release work.
""",
            "executor_kind": "claude",
            "executor_mode": "preset",
            "model": "",
            "reasoning_effort": "high",
        },
    )
    assert create_response.status_code == 201
    role_definition = create_response.json()["role_definition"]
    assert role_definition["name"] == "Release Builder"
    assert role_definition["archetype"] == "builder"
    assert role_definition["executor_kind"] == "claude"
    assert role_definition["reasoning_effort"] == "high"
    assert role_definition["posture_notes"] == "Prefer maintainability evidence before calling this ready."
    assert role_definition["prompt_ref"].endswith(".md")
    generated_prompt_ref = role_definition["prompt_ref"]

    list_response = client.get("/api/role-definitions")
    assert list_response.status_code == 200
    assert any(item["id"] == role_definition["id"] for item in list_response.json())

    update_response = client.put(
        f"/api/role-definitions/{role_definition['id']}",
        json={
            "name": "Release Builder v2",
            "description": "Updated role definition.",
            "posture_notes": "Tighten the evidence bar for refactors.",
            "archetype": "builder",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Focus on scoped release work with tighter release constraints.
""",
            "executor_kind": "codex",
            "executor_mode": "command",
            "command_cli": "codex",
            "command_args_text": "\n".join(
                [
                    "exec",
                    "--json",
                    "--cd",
                    "{workdir}",
                    "--output-schema",
                    "{schema_path}",
                    "--output-last-message",
                    "{output_path}",
                    "{prompt}",
                ]
            ),
            "model": "gpt-5.4",
            "reasoning_effort": "",
        },
    )
    assert update_response.status_code == 200
    updated_role_definition = update_response.json()["role_definition"]
    assert updated_role_definition["name"] == "Release Builder v2"
    assert updated_role_definition["executor_mode"] == "command"
    assert updated_role_definition["model"] == "gpt-5.4"
    assert updated_role_definition["posture_notes"] == "Tighten the evidence bar for refactors."
    assert updated_role_definition["prompt_ref"] == generated_prompt_ref

    invalid_update_response = client.put(
        f"/api/role-definitions/{role_definition['id']}",
        json={
            "name": "Release Inspector",
            "description": "Should fail.",
            "archetype": "inspector",
            "prompt_markdown": """---
version: 1
archetype: inspector
---

Inspect release work instead.
""",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "model": "",
            "reasoning_effort": "medium",
        },
    )
    assert invalid_update_response.status_code == 400
    assert "saved role definitions cannot change archetype" in invalid_update_response.json()["error"]

    delete_response = client.delete(f"/api/role-definitions/{role_definition['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True


def _assert_bundle_preview_control_summary(preview: dict) -> None:
    preview_control_summary = preview["control_summary"]
    assert preview_control_summary["gatekeeper"]["requires_evidence_refs"] is True
    assert preview_control_summary["coverage"]["check_count"] >= 1
    assert preview_control_summary["coverage"]["target_count"] >= preview_control_summary["coverage"]["check_count"]
    assert isinstance(preview_control_summary["loop_fit_reasons"], list)
    assert preview_control_summary["residual_risk_policy"] and preview_control_summary["role_postures"]
    assert "traceability" in preview_control_summary
    assert preview["traceability"] == preview_control_summary["traceability"]
    assert isinstance(preview["traceability"]["items"], list)
    assert preview["traceability"]["required_count"] >= preview["traceability"]["mapped_count"] >= 0
    assert preview["diagnostics"] == preview_control_summary["diagnostics"]
    assert isinstance(preview["diagnostics"], list)


def _assert_bundle_governance_summary(governance_summary: dict) -> None:
    assert governance_summary["workflow_step_count"] >= 1
    assert (
        governance_summary["residual_risk_policy"]
        and governance_summary["execution_strategy"]
        and governance_summary["role_postures"]
    )
    assert governance_summary["coverage_summary"]
    assert governance_summary["coverage_targets"]
    assert isinstance(governance_summary["loop_fit_reasons"], list)
    assert governance_summary["gatekeeper"]["strictness"] == "evidence_refs_required"


def test_api_bundles_import_export_and_delete(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Export Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Imported Bundle",
            description="Bundle import from API.",
            collaboration_summary="Prefer evidence before declaring done.",
        )
    )

    client = TestClient(build_app(service=service))
    preview_response = client.post("/api/bundles/preview", json={"bundle_yaml": bundle_yaml})
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["ok"] is True
    assert preview["metadata"]["name"] == "Imported Bundle"
    assert preview["bundle"]["loop"]["workdir"] == str(sample_workdir.resolve())
    assert preview["roles"]
    assert preview["workflow_preview"]["steps"]
    assert preview["spec_rendered_html"].strip()
    _assert_bundle_preview_control_summary(preview)

    import_response = client.post("/api/bundles/import", json={"bundle_yaml": bundle_yaml})

    assert import_response.status_code == 201
    bundle = import_response.json()["bundle"]
    assert bundle["name"] == "Imported Bundle"
    assert bundle["collaboration_summary"] == "Prefer evidence before declaring done."

    list_response = client.get("/api/bundles")
    assert list_response.status_code == 200
    listed_bundle = next(item for item in list_response.json() if item["id"] == bundle["id"])
    _assert_bundle_governance_summary(listed_bundle["governance_summary"])

    get_response = client.get(f"/api/bundles/{bundle['id']}")
    assert get_response.status_code == 200
    assert get_response.json()["id"] == bundle["id"]

    export_response = client.get(f"/api/bundles/{bundle['id']}/export")
    assert export_response.status_code == 200
    assert "Imported Bundle" in export_response.text
    assert "Prefer evidence before declaring done." in export_response.text
    assert export_response.headers["content-type"].startswith("application/yaml")

    delete_response = client.delete(f"/api/bundles/{bundle['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    missing_response = client.get(f"/api/bundles/{bundle['id']}")
    assert missing_response.status_code == 404
    assert "unknown bundle" in missing_response.json()["error"]


def test_api_bundle_file_inputs_reject_invalid_utf8(service_factory, tmp_path: Path) -> None:
    service = service_factory(scenario="success")
    bundle_path = tmp_path / "broken-bundle.yaml"
    bundle_path.write_bytes(b"\xff")
    client = TestClient(build_app(service=service))

    preview_response = client.post("/api/bundles/preview", json={"bundle_path": str(bundle_path)})
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["ok"] is False
    assert "UTF-8 encoded YAML" in preview_payload["error"]

    import_response = client.post("/api/bundles/import", json={"bundle_path": str(bundle_path)})
    assert import_response.status_code == 400
    assert "UTF-8 encoded YAML" in import_response.json()["error"]


def test_api_bundle_preview_and_import_report_invalid_version_without_500(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    invalid_yaml = "version: not-a-number\nmetadata:\n  name: Broken Bundle\n"

    preview_response = client.post("/api/bundles/preview", json={"bundle_yaml": invalid_yaml})
    assert preview_response.status_code == 200
    assert preview_response.json() == {"ok": False, "error": "bundle version must be an integer"}

    import_response = client.post("/api/bundles/import", json={"bundle_yaml": invalid_yaml})
    assert import_response.status_code == 400
    assert import_response.json()["error"] == "bundle version must be an integer"


@pytest.mark.parametrize(
    ("replace_bundle_id", "expected_error"),
    [
        (False, "bundle replace_bundle_id must be a string"),
        ("../escape", "bundle replace_bundle_id must use letters, numbers, dot, underscore, or dash"),
    ],
)
def test_api_bundle_import_rejects_invalid_replace_bundle_id(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
    replace_bundle_id: object,
    expected_error: str,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Replace Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Replacement Bundle",
            description="Bundle import with invalid replace id.",
            collaboration_summary="Keep replace targets explicit.",
        )
    )
    client = TestClient(build_app(service=service))

    import_response = client.post(
        "/api/bundles/import",
        json={"bundle_yaml": bundle_yaml, "replace_bundle_id": replace_bundle_id},
    )

    assert import_response.status_code == 400
    assert import_response.json()["error"] == expected_error


def test_api_bundles_derive_returns_bundle_payload(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Derive Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/bundles/derive",
        json={
            "loop_id": loop["id"],
            "name": "Derived Bundle",
            "description": "Derived from existing assets.",
            "collaboration_summary": "Treat fake done states as blockers.",
        },
    )

    assert response.status_code == 200
    bundle = response.json()["bundle"]
    assert bundle["metadata"]["name"] == "Derived Bundle"
    assert bundle["collaboration_summary"] == "Treat fake done states as blockers."
    assert bundle["workflow"]["roles"]
    assert bundle["role_definitions"]


def test_task_alignment_skill_api_is_not_registered() -> None:
    client = TestClient(build_app())

    assert client.get("/api/skills/loopora-task-alignment").status_code == 404
    assert client.post("/api/skills/loopora-task-alignment/install", json={"target": "codex"}).status_code == 404
    assert client.get("/api/skills/loopora-task-alignment/download").status_code == 404


def test_bundle_form_import_and_edit_flow(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Form Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Form Bundle",
            description="Imported through the HTML form.",
            collaboration_summary="Prefer compact but convincing evidence.",
        )
    )

    client = TestClient(build_app(service=service))
    import_response = client.post("/bundles/import", data={"bundle_yaml": bundle_yaml}, follow_redirects=False)

    assert import_response.status_code == 303
    bundle_location = import_response.headers["location"]
    bundle_id = bundle_location.rsplit("/", 1)[-1]
    bundle = service.get_bundle(bundle_id)
    assert bundle["name"] == "Form Bundle"

    edit_response = client.post(
        f"/bundles/{bundle_id}/edit",
        data={
            "description": "Updated bundle description.",
            "collaboration_summary": "Take fake done seriously.",
            "spec_markdown": "# Task\n\nShip the update.\n\n# Done When\n- It works.\n",
        },
        follow_redirects=False,
    )

    assert edit_response.status_code == 303
    updated_bundle = service.get_bundle(bundle_id)
    assert updated_bundle["description"] == "Updated bundle description."
    assert updated_bundle["collaboration_summary"] == "Take fake done seriously."
    spec_path = app_home() / "bundles" / bundle_id / "spec.md"
    assert spec_path.read_text(encoding="utf-8").startswith("# Task")


def test_bundle_detail_stays_open_when_managed_spec_is_unreadable(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Broken Spec Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Broken Spec Bundle",
                description="The managed spec file can be repaired from the detail page.",
                collaboration_summary="Keep the plan detail page usable.",
            )
        )
    )
    (app_home() / "bundles" / imported["id"] / "spec.md").write_bytes(b"\xff")

    response = TestClient(build_app(service=service)).get(f"/bundles/{imported['id']}")

    assert response.status_code == 200
    assert 'data-testid="bundle-detail-page"' in response.text
    assert 'data-testid="bundle-detail-form"' in response.text
    assert "bundle spec file could not be read" in response.text


def test_bundle_derive_form_encodes_query_values(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/bundles/derive",
        data={
            "loop_id": "loop&id=shadow",
            "name": "Bundle & Review",
            "description": "Use A&B evidence.",
            "collaboration_summary": "No query leakage.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == (
        "/bundles/derive/export?loop_id=loop%26id%3Dshadow&name=Bundle+%26+Review&description=Use+A%26B+evidence.&collaboration_summary=No+query+leakage."
    )


def test_create_loop_page_imports_bundle_as_loop_creation_flow(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source_loop = service.create_loop(
        name="Create Page Bundle Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    bundle_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            source_loop["id"],
            name="Create Page Bundle",
            description="Imported from the unified create loop page.",
            collaboration_summary="Create loop and bundle import share one entry.",
        )
    )

    client = TestClient(build_app(service=service))
    import_response = client.post(
        "/loops/new/import-bundle",
        data={"bundle_yaml": bundle_yaml, "start_immediately": ""},
        follow_redirects=False,
    )

    assert import_response.status_code == 303
    assert import_response.headers["location"].startswith("/loops/")
    imported_bundle = next(bundle for bundle in service.list_bundles() if bundle["name"] == "Create Page Bundle")
    assert import_response.headers["location"] == f"/loops/{imported_bundle['loop_id']}"
    assert service.get_loop(imported_bundle["loop_id"])["name"] == "Create Page Bundle Source"


def test_api_bundle_update_updates_plan_without_bumping_revision(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Update Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="API Update Bundle",
                description="Before API update.",
                collaboration_summary="Original collaboration summary.",
            )
        )
    )

    client = TestClient(build_app(service=service))
    response = client.put(
        f"/api/bundles/{imported['id']}",
        json={
            "description": "After API update.",
            "collaboration_summary": "Updated collaboration summary.",
            "spec_markdown": "# Task\n\nUpdated.\n\n# Done When\n- Ready.\n",
        },
    )

    assert response.status_code == 200
    bundle = response.json()["bundle"]
    assert bundle["description"] == "After API update."
    assert bundle["collaboration_summary"] == "Updated collaboration summary."
    assert bundle["revision"] == imported["revision"]
    assert bundle["source_bundle_id"] == ""


def test_bundle_api_and_detail_hide_legacy_lineage_surfaces(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Lineage Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    source = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Lineage Source Bundle",
                description="Original lineage source.",
                collaboration_summary="Original governance posture.",
            )
        )
    )
    legacy_yaml = bundle_to_yaml(
        service.derive_bundle_from_loop(
            loop["id"],
            name="Lineage Revision Bundle",
            description="Revision source should remain hidden.",
            collaboration_summary="Updated governance posture.",
        )
    ).replace(
        "metadata:\n  name: Lineage Revision Bundle\n  description: Revision source should remain hidden.",
        "metadata:\n"
        "  name: Lineage Revision Bundle\n"
        "  description: Revision source should remain hidden.\n"
        f"  source_bundle_id: {source['id']}\n"
        f"  revision: {source['revision'] + 1}",
    )
    imported = service.import_bundle_text(legacy_yaml)
    client = TestClient(build_app(service=service))

    api_response = client.get(f"/api/bundles/{imported['id']}")
    list_response = client.get("/bundles")
    page_response = client.get(f"/bundles/{imported['id']}")

    assert api_response.status_code == 200
    assert "revision_summary" not in api_response.json()
    assert api_response.json()["source_bundle_id"] == ""
    assert page_response.status_code == 200
    assert 'data-testid="bundle-revision-lineage"' not in page_response.text
    assert "Plan version" not in page_response.text
    assert 'data-testid="bundle-surface-diff"' not in page_response.text
    assert f'value="{source["id"]}"' not in page_response.text
    assert 'data-testid="bundle-revision-delta-summary"' not in page_response.text
    assert list_response.status_code == 200
    assert f'data-testid="bundle-governance-card-{imported["id"]}"' in list_response.text
    assert 'data-testid="bundle-governance-failure"' in list_response.text
    assert 'data-testid="bundle-governance-evidence"' in list_response.text
    assert 'data-testid="bundle-governance-coverage"' in list_response.text
    assert 'data-testid="bundle-governance-residual-risk"' in list_response.text
    assert 'data-testid="bundle-governance-execution-strategy"' in list_response.text
    assert 'data-testid="bundle-governance-local"' in list_response.text
    assert 'data-testid="bundle-governance-workflow"' in list_response.text
    assert 'data-testid="bundle-governance-gatekeeper"' in list_response.text
    assert 'data-testid="bundle-governance-changed-surfaces"' not in list_response.text


def test_bundle_owned_surface_edit_redirects_back_to_bundle_detail(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Bundle Redirect Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Redirect Bundle",
                description="Bundle redirect test.",
                collaboration_summary="Return to the bundle detail after local surface edits.",
            )
        )
    )
    orchestration = imported["orchestration"]
    role_definition = imported["role_definitions"][0]
    client = TestClient(build_app(service=service))

    return_to = quote(f"/bundles/{imported['id']}?token=secret-token&tab=workflow#surface", safe="")
    orchestration_response = client.post(
        f"/orchestrations/{orchestration['id']}/edit?return_to={return_to}",
        data={
            "name": orchestration["name"],
            "description": "Workflow tuned from bundle detail.",
            "workflow_json": json.dumps(orchestration["workflow_json"], ensure_ascii=False, indent=2),
            "prompt_files_json": json.dumps(orchestration["prompt_files_json"], ensure_ascii=False, indent=2),
        },
        follow_redirects=False,
    )
    assert orchestration_response.status_code == 303
    assert orchestration_response.headers["location"] == f"/bundles/{imported['id']}?tab=workflow&surface_updated=workflow#surface"

    role_response = client.post(
        f"/roles/{role_definition['id']}/edit?return_to=/bundles/{imported['id']}",
        data={
            "name": role_definition["name"],
            "description": role_definition["description"],
            "archetype": role_definition["archetype"],
            "prompt_ref": role_definition["prompt_ref"],
            "prompt_markdown": role_definition["prompt_markdown"],
            "posture_notes": "Tighten this role from the bundle detail flow.",
            "executor_kind": role_definition["executor_kind"],
            "executor_mode": role_definition["executor_mode"],
            "command_cli": role_definition["command_cli"],
            "command_args_text": role_definition["command_args_text"],
            "model": role_definition["model"],
            "reasoning_effort": role_definition["reasoning_effort"],
        },
        follow_redirects=False,
    )
    assert role_response.status_code == 303
    assert role_response.headers["location"] == f"/bundles/{imported['id']}?surface_updated=role%3A{role_definition['id']}"


def test_bundle_surface_return_to_rejects_external_redirects(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Unsafe Return Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Unsafe Return Bundle",
                description="Return target safety.",
                collaboration_summary="Do not redirect outside the local console.",
            )
        )
    )
    orchestration = imported["orchestration"]
    role_definition = imported["role_definitions"][0]
    client = TestClient(build_app(service=service))

    orchestration_page = client.get(f"/orchestrations/{orchestration['id']}/edit?return_to=https://evil.example/phish")
    assert orchestration_page.status_code == 200
    assert "https://evil.example" not in orchestration_page.text

    orchestration_response = client.post(
        f"/orchestrations/{orchestration['id']}/edit?return_to=https://evil.example/phish",
        data={
            "name": orchestration["name"],
            "description": "Workflow tuned from an unsafe return target.",
            "workflow_json": json.dumps(orchestration["workflow_json"], ensure_ascii=False, indent=2),
            "prompt_files_json": json.dumps(orchestration["prompt_files_json"], ensure_ascii=False, indent=2),
        },
        follow_redirects=False,
    )
    assert orchestration_response.status_code == 303
    assert orchestration_response.headers["location"] == f"/orchestrations/{orchestration['id']}/edit?saved=1"

    role_page = client.get(f"/roles/{role_definition['id']}/edit?return_to=//evil.example/phish")
    assert role_page.status_code == 200
    assert "evil.example" not in role_page.text

    role_response = client.post(
        f"/roles/{role_definition['id']}/edit?return_to=//evil.example/phish",
        data={
            "name": role_definition["name"],
            "description": role_definition["description"],
            "archetype": role_definition["archetype"],
            "prompt_ref": role_definition["prompt_ref"],
            "prompt_markdown": role_definition["prompt_markdown"],
            "posture_notes": "Ignore the external return target.",
            "executor_kind": role_definition["executor_kind"],
            "executor_mode": role_definition["executor_mode"],
            "command_cli": role_definition["command_cli"],
            "command_args_text": role_definition["command_args_text"],
            "model": role_definition["model"],
            "reasoning_effort": role_definition["reasoning_effort"],
        },
        follow_redirects=False,
    )
    assert role_response.status_code == 303
    assert role_response.headers["location"] == f"/roles/{role_definition['id']}/edit?saved=1"


def test_bundle_export_sanitizes_download_filename(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Filename Source",
        spec_path=sample_spec_file,
        workdir=sample_workdir,
        model="gpt-5.4-mini",
        reasoning_effort="medium",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )
    imported = service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name='Bad/Name" \r\n injected',
                description="Filename safety.",
                collaboration_summary="Export headers stay parseable.",
            )
        )
    )
    client = TestClient(build_app(service=service))

    response = client.get(f"/api/bundles/{imported['id']}/export")

    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert disposition == 'attachment; filename="Bad-Name-injected.yml"'
    assert "\n" not in disposition
    assert "\r" not in disposition
    assert "/" not in disposition


def test_api_role_definition_rejects_custom_executor_preset_mode(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/role-definitions",
        json={
            "name": "Custom Wrapper",
            "description": "Wrapper role.",
            "archetype": "custom",
            "prompt_markdown": """---
version: 1
archetype: custom
---

Observe and summarize.
""",
            "executor_kind": "custom",
            "executor_mode": "preset",
            "command_cli": "wrapper",
            "command_args_text": "--output\n{output_path}\n{prompt}\n",
            "model": "",
            "reasoning_effort": "",
        },
    )

    assert response.status_code == 400
    assert "only supports command mode" in response.json()["error"]


def test_api_role_definition_rejects_unsafe_prompt_ref(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/role-definitions",
        json={
            "name": "Escaping Builder",
            "description": "Should fail when prompt_ref escapes the asset root.",
            "archetype": "builder",
            "prompt_ref": "../escape.md",
            "prompt_markdown": """---
version: 1
archetype: builder
---

Keep prompt refs inside prompts/.
""",
            "executor_kind": "codex",
            "executor_mode": "preset",
            "model": "gpt-5.4-mini",
            "reasoning_effort": "medium",
        },
    )

    assert response.status_code == 400
    assert "prompt_ref must be a safe relative path" in response.json()["error"]


def test_api_spec_init_validate_and_delete_loop(service_factory, tmp_path: Path, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "created-spec.md"
    init_response = client.post(
        "/api/specs/init",
        json={"path": str(spec_path), "locale": "en", "workflow_preset": "build_first"},
    )
    assert init_response.status_code == 201
    assert spec_path.exists()
    created_text = spec_path.read_text(encoding="utf-8")
    assert "delete `# Done When`" in created_text
    assert "preserve existing user files" in created_text
    assert "# Task" in created_text
    assert "# Done When" in created_text
    assert "# Guardrails" in created_text
    assert "# Role Notes" in created_text
    assert "## Builder Notes" in created_text
    assert "## Inspector Notes" in created_text
    assert "## GateKeeper Notes" in created_text
    assert "## Guide Notes" in created_text

    duplicate_init_response = client.post(
        "/api/specs/init",
        json={"path": str(spec_path), "locale": "en", "workflow_preset": "build_first"},
    )
    assert duplicate_init_response.status_code == 409
    assert "already exists" in duplicate_init_response.json()["error"]

    validate_response = client.get("/api/specs/validate", params={"path": str(spec_path)})
    assert validate_response.status_code == 200
    assert validate_response.json()["ok"] is True
    assert validate_response.json()["check_mode"] == "specified"

    loop = service.create_loop(
        name="Delete Me",
        spec_path=spec_path,
        workdir=sample_workdir,
        model="gpt-5.4",
        reasoning_effort="xhigh",
        max_iters=3,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )

    delete_response = client.delete(f"/api/loops/{loop['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json()["id"] == loop["id"]
    assert service.list_loops() == []


def test_api_spec_template_accepts_workflow_json_mapping(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/specs/template",
        json={
            "locale": "en",
            "workflow_json": {
                "version": 1,
                "roles": [
                    {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
                    {"id": "gatekeeper", "name": "GateKeeper", "archetype": "gatekeeper", "prompt_ref": "gatekeeper.md"},
                ],
                "steps": [
                    {"id": "build", "role_id": "builder"},
                    {"id": "gate", "role_id": "gatekeeper", "on_pass": "finish_run"},
                ],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "# Task" in payload["content"]
    assert "## Builder Notes" in payload["content"]
    assert "## GateKeeper Notes" in payload["content"]
    assert [item["role_name"] for item in payload["role_note_sections"]] == ["Builder", "GateKeeper"]
    assert "<h1>Task</h1>" in payload["rendered_html"]


def test_api_spec_template_and_init_reject_invalid_workflow_json(
    tmp_path: Path,
    service_factory,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))
    invalid_workflow = {
        "version": 1,
        "roles": [
            {"id": "builder", "name": "Builder", "archetype": "builder", "prompt_ref": "builder.md"},
        ],
        "steps": [
            {"id": "builder_step", "role_id": "builder"},
        ],
        "controls": [
            {
                "id": "bad_repair",
                "when": {"signal": "step_failed", "after": "0s"},
                "call": {"role_id": "builder"},
            }
        ],
    }

    template_response = client.post("/api/specs/template", json={"workflow_json": invalid_workflow})
    assert template_response.status_code == 400
    assert "controls may only call Inspector" in template_response.json()["error"]

    spec_path = tmp_path / "invalid-workflow-template.md"
    init_response = client.post(
        "/api/specs/init",
        json={"path": str(spec_path), "locale": "en", "workflow_json": invalid_workflow},
    )
    assert init_response.status_code == 400
    assert "controls may only call Inspector" in init_response.json()["error"]
    assert not spec_path.exists()


def test_api_spec_validate_reports_auto_generated_check_mode(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "exploratory-spec.md"
    spec_path.write_text(
        "# Task\n\nExplore a promising prototype direction.\n\n# Guardrails\n\n- Stay focused.\n",
        encoding="utf-8",
    )

    validate_response = client.get("/api/specs/validate", params={"path": str(spec_path)})
    assert validate_response.status_code == 200
    payload = validate_response.json()
    assert payload["ok"] is True
    assert payload["check_mode"] == "auto_generated"
    assert payload["check_count"] == 0


def test_api_spec_validate_rejects_legacy_headings(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "legacy-spec.md"
    spec_path.write_text("# Goal\n\nLegacy format.\n", encoding="utf-8")

    response = client.get("/api/specs/validate", params={"path": str(spec_path)})

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert "legacy spec headings" in response.json()["error"]


def test_api_spec_preview_returns_rendered_read_only_markdown(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "preview-spec.md"
    spec_path.write_text(
        "# Task\n\nShip a preview.\n\n# Done When\n\n- Render headings\n- Escape <script>alert('xss')</script>\n\n```js\nconsole.log('ok')\n```\n",
        encoding="utf-8",
    )

    preview_response = client.get("/api/specs/preview", params={"path": str(spec_path)})

    assert preview_response.status_code == 200
    payload = preview_response.json()
    assert payload["ok"] is True
    assert payload["path"] == str(spec_path.resolve())
    assert "# Task" in payload["content"]
    assert "<h1>Task</h1>" in payload["rendered_html"]
    assert "<script>" not in payload["rendered_html"]
    assert "&lt;script&gt;alert" in payload["rendered_html"]
    assert 'class="language-js"' in payload["rendered_html"]
    assert "console.log" in payload["rendered_html"]


def test_api_spec_document_returns_content_rendering_and_validation(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "editable-spec.md"
    spec_path.write_text(
        "# Task\n\nKeep editing local.\n\n# Done When\n\n- The disk file updates after save.\n- The rendered preview updates too.\n",
        encoding="utf-8",
    )

    response = client.get("/api/specs/document", params={"path": str(spec_path)})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["path"] == str(spec_path.resolve())
    assert payload["content"].startswith("# Task")
    assert "<h1>Task</h1>" in payload["rendered_html"]
    assert payload["validation"]["ok"] is True
    assert payload["validation"]["check_count"] == 2
    assert payload["validation"]["check_mode"] == "specified"


def test_api_spec_document_save_writes_file_and_returns_validation(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    spec_path = tmp_path / "editable-spec.md"
    spec_path.write_text("# Task\n\nInitial\n", encoding="utf-8")

    response = client.put(
        "/api/specs/document",
        json={
            "path": str(spec_path),
            "content": "# Task\r\n\r\nSaved copy.\r\n\r\n# Done When\r\n\r\n- The file matches the editor after save.\r\n",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["content"] == "# Task\n\nSaved copy.\n\n# Done When\n\n- The file matches the editor after save.\n"
    assert spec_path.read_text(encoding="utf-8") == payload["content"]
    assert payload["validation"]["ok"] is True
    assert payload["validation"]["check_count"] == 1
    assert "<h1>Done When</h1>" in payload["rendered_html"]


def test_api_spec_document_endpoints_reject_non_markdown_paths(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    non_spec_path = tmp_path / "not-a-spec.txt"
    non_spec_path.write_text("# Task\n\nSensitive but parseable local text.\n", encoding="utf-8")

    for endpoint in ("/api/specs/validate", "/api/specs/preview", "/api/specs/document"):
        response = client.get(endpoint, params={"path": str(non_spec_path)})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "Markdown file" in payload["error"]
        assert "Sensitive but parseable" not in json.dumps(payload, ensure_ascii=False)

    save_response = client.put(
        "/api/specs/document",
        json={"path": str(non_spec_path), "content": "# Task\n\nOverwritten\n"},
    )
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is False
    assert "Markdown file" in save_response.json()["error"]
    assert "Sensitive but parseable" in non_spec_path.read_text(encoding="utf-8")

    init_response = client.post("/api/specs/init", json={"path": str(tmp_path / "created.txt"), "locale": "en"})
    assert init_response.status_code == 400
    assert "Markdown file" in init_response.json()["error"]


def test_api_spec_document_endpoints_reject_oversized_markdown(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    oversized_path = tmp_path / "oversized-spec.md"
    oversized_path.write_text("# Task\n\n" + ("x" * 1_000_001), encoding="utf-8")

    for endpoint in ("/api/specs/validate", "/api/specs/preview", "/api/specs/document"):
        response = client.get(endpoint, params={"path": str(oversized_path)})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "too large" in response.json()["error"]

    save_response = client.put(
        "/api/specs/document",
        json={"path": str(tmp_path / "new-spec.md"), "content": "# Task\n\n" + ("x" * 1_000_001)},
    )
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is False
    assert "too large" in save_response.json()["error"]
    assert not (tmp_path / "new-spec.md").exists()


def test_api_spec_document_endpoints_reject_binary_markdown(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    binary_path = tmp_path / "binary-spec.md"
    binary_path.write_bytes(b"# Task\n\n\x00binary-like content\n")

    for endpoint in ("/api/specs/validate", "/api/specs/preview", "/api/specs/document"):
        response = client.get(endpoint, params={"path": str(binary_path)})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "text markdown" in payload["error"]
        assert "binary-like content" not in json.dumps(payload, ensure_ascii=False)

    save_path = tmp_path / "save-target.md"
    save_path.write_text("# Task\n\nKeep this text.\n", encoding="utf-8")

    save_response = client.put(
        "/api/specs/document",
        json={"path": str(save_path), "content": "# Task\n\n\u0000binary-like content\n"},
    )
    assert save_response.status_code == 200
    assert save_response.json()["ok"] is False
    assert "text markdown" in save_response.json()["error"]
    assert save_path.read_text(encoding="utf-8") == "# Task\n\nKeep this text.\n"


def test_api_spec_document_endpoints_reject_non_utf8_markdown(tmp_path: Path, service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    invalid_path = tmp_path / "invalid-spec.md"
    invalid_path.write_bytes(b"# Task\n\n\xff\n")

    for endpoint in ("/api/specs/validate", "/api/specs/preview", "/api/specs/document"):
        response = client.get(endpoint, params={"path": str(invalid_path)})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is False
        assert "UTF-8 encoded Markdown" in payload["error"]


def test_api_markdown_render_can_strip_prompt_front_matter(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/markdown/render",
        json={
            "markdown": "---\nversion: 1\narchetype: builder\n---\n\n# Prompt Body\n\nShip the change.\n",
            "strip_front_matter": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert "<h1>Prompt Body</h1>" in payload["rendered_html"]
    assert "version: 1" not in payload["rendered_html"]
    assert "archetype: builder" not in payload["rendered_html"]
    assert "Ship the change." in payload["rendered_html"]


def test_logo_assets_are_served(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.get("/logo/logo.svg")
    assert response.status_code == 200
    assert "image/svg+xml" in response.headers["content-type"]


def test_network_mode_requires_auth_token_and_sets_cookie(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    unauthorized = client.get("/")
    assert unauthorized.status_code == 401
    assert "Auth token required" in unauthorized.text

    unsupported_header = client.get("/", headers={"X-Other-Token": "secret-token"})
    assert unsupported_header.status_code == 401

    bearer_authorized = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token")).get(
        "/api/loops",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert bearer_authorized.status_code == 200

    custom_header_authorized = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token")).get(
        "/api/loops",
        headers={"X-Loopora-Token": "secret-token"},
    )
    assert custom_header_authorized.status_code == 200

    authorized = client.get("/?token=secret-token")
    assert authorized.status_code == 200
    assert client.cookies.get("loopora_auth") == "secret-token"

    api_response = client.get("/api/loops")
    assert api_response.status_code == 200


def test_network_mode_auth_page_uses_request_locale_and_shared_styles(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    unauthorized = client.get("/", headers={"Accept-Language": "zh-CN;q=0.1,en-US;q=0.9"})

    assert unauthorized.status_code == 401
    assert re.search(r'<html\s+lang="en"\s+data-locale="en"\s+data-theme="light"\s*>', unauthorized.text)
    assert "loopora:theme" in unauthorized.text
    assert "loopora:locale" in unauthorized.text
    assert "/static/app.css?v=" in unauthorized.text
    assert "<style>" not in unauthorized.text
    assert 'data-testid="auth-card"' in unauthorized.text
    assert 'data-testid="auth-copy-stack"' in unauthorized.text
    assert "Loopora · Auth token required" in unauthorized.text
    assert "Auth token required" in unauthorized.text
    assert "需要访问令牌" in unauthorized.text
    assert "X-Loopora-Token" in unauthorized.text
    assert "X-Other-Token" not in unauthorized.text
    assert 'class="auth-logo" src="/logo/logo-with-text-horizontal.svg" alt="" aria-hidden="true"' in unauthorized.text

    unauthenticated_css = client.get("/static/app.css")
    assert unauthenticated_css.status_code == 200
    assert "text/css" in unauthenticated_css.headers["content-type"]
    assert ".auth-shell {" in unauthenticated_css.text
    unauthenticated_logo = client.get("/logo/logo.svg")
    assert unauthenticated_logo.status_code == 200
    assert "image/svg+xml" in unauthenticated_logo.headers["content-type"]

    css = client.get("/static/app.css?token=secret-token")
    assert css.status_code == 200
    assert ".auth-shell {" in css.text
    assert ".auth-card {" in css.text
    assert ".auth-copy-stack {" in css.text
    assert '[data-theme="dark"] .auth-card {' in css.text
    assert 'html[data-theme="dark"] .auth-logo {' in css.text


def test_preferred_locale_from_accept_language_respects_q_values_and_supported_locales() -> None:
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=0.1,en-US;q=0.9") == "en"
    assert web_module._preferred_locale_from_accept_language("en-US;q=0.1,zh-CN;q=0.9") == "zh"
    assert web_module._preferred_locale_from_accept_language("fr-FR,zh-CN;q=0.8,en-US;q=0.6") == "zh"
    assert web_module._preferred_locale_from_accept_language("fr-FR,de-DE;q=0.8") == "en"
    assert web_module._preferred_locale_from_accept_language("en-US;q=0,zh-CN;q=0.6") == "zh"
    assert web_module._preferred_locale_from_accept_language("zh_CN;q=0.7,en-US;q=0.4") == "zh"
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=bad,en-US;q=0.4") == "en"
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=nan,en-US;q=0.4") == "en"
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=inf,en-US;q=0.4") == "en"
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=1.5,en-US;q=0.4") == "en"
    assert web_module._preferred_locale_from_accept_language("zh-CN;q=-0.1,en-US;q=0.4") == "en"


def test_network_mode_disables_native_dialog_endpoints(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    response = client.get("/api/system/pick-directory?token=secret-token")
    assert response.status_code == 405

    post_response = client.post(
        "/api/system/pick-directory?token=secret-token",
        json={"start_path": "/tmp"},
    )
    assert post_response.status_code == 400
    assert "native dialogs are disabled in network mode" in post_response.json()["error"]

    reveal = client.post("/api/system/reveal-path?token=secret-token", json={"path": "/tmp"})
    assert reveal.status_code == 400
    assert "native dialogs are disabled in network mode" in reveal.json()["error"]
