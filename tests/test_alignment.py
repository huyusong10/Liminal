from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from loopora.bundles import bundle_to_yaml, load_bundle_text
from loopora.executor import FakeCodexExecutor
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.web import build_app
from loopora.web_streaming import MAX_EVENT_CURSOR_ID
import loopora.service_alignment as alignment_module
import loopora.service_cleanup_diagnostics as cleanup_diagnostics


def _wait_for_status(service, session_id: str, *statuses: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    expected = set(statuses)
    while time.time() < deadline:
        session = service.get_alignment_session(session_id)
        if session["status"] in expected:
            return session
        time.sleep(0.05)
    session = service.get_alignment_session(session_id)
    raise AssertionError(f"alignment session stayed in {session['status']}, expected {sorted(expected)}")


def _confirm_alignment_agreement(service, session_id: str, *final_statuses: str) -> dict:
    agreement = _wait_for_status(service, session_id, "waiting_user")
    assert agreement["alignment_stage"] == "agreement_ready"
    assert agreement["working_agreement"]["summary"]
    assert agreement["working_agreement"]["readiness_evidence"]["loop_fit"]
    assert agreement["working_agreement"]["readiness_evidence"]["task_scope"]
    assert agreement["working_agreement"]["readiness_evidence"]["residual_risk_policy"]
    service.append_alignment_message(session_id, "确认")
    confirmed = _wait_for_status(service, session_id, *(final_statuses or ("ready",)))
    assert confirmed["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is True
    return confirmed


def test_alignment_service_writes_validates_previews_imports_and_runs(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    bundle_path = Path(session["bundle_path"])
    artifact_root = sample_workdir / ".loopora" / "alignment_sessions" / session["id"]
    assert bundle_path == artifact_root / "artifacts" / "bundle.yml"
    assert bundle_path.exists()
    assert session["validation"]["ok"] is True
    assert (artifact_root / "manifest.json").exists()
    assert (artifact_root / "conversation" / "transcript.jsonl").exists()
    assert (artifact_root / "agreement" / "current.json").exists()
    assert (artifact_root / "artifacts" / "validation.json").exists()
    assert (artifact_root / "events" / "events.jsonl").exists()
    invocation_dir = artifact_root / "invocations" / "0001"
    assert (invocation_dir / "prompt.md").exists()
    assert (invocation_dir / "schema.json").exists()
    assert (invocation_dir / "output.json").exists()
    assert (invocation_dir / "stdout.log").exists()
    assert (invocation_dir / "stderr.log").exists()
    invocation_output = json.loads((invocation_dir / "output.json").read_text(encoding="utf-8"))
    assert "bundle_yaml" not in invocation_output
    assert invocation_output["bundle_written"] is True
    assert invocation_output["bundle_path"] == str(bundle_path)
    manifest = json.loads((artifact_root / "manifest.json").read_text(encoding="utf-8"))
    assert "transcript" not in manifest
    assert "validation" not in manifest
    assert "working_agreement" not in manifest
    assert "Build a focused starter experience." in (artifact_root / "conversation" / "transcript.jsonl").read_text(encoding="utf-8")
    assert session["alignment_stage"] == "ready"

    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["loop"]["workdir"] == str(sample_workdir.resolve())
    assert preview["workflow_preview"]["roles"][0]["name"] == "Focused Builder"
    assert preview["control_summary"]["gatekeeper"]["requires_evidence_refs"] is True
    assert preview["traceability"] == preview["control_summary"]["traceability"]
    assert preview["traceability"]["mapped_count"] == preview["traceability"]["required_count"]
    assert "Ship the focused starter experience" in preview["spec_rendered_html"]

    imported = service.import_alignment_bundle(session["id"], start_immediately=True)
    assert imported["bundle"]["loop_id"]
    assert imported["run"]["id"]
    final_session = service.get_alignment_session(session["id"])
    assert final_session["status"] == "running_loop"
    assert final_session["linked_bundle_id"] == imported["bundle"]["id"]
    assert final_session["linked_loop_id"] == imported["bundle"]["loop_id"]
    assert final_session["linked_run_id"] == imported["run"]["id"]


def test_alignment_executor_events_redact_sensitive_values_before_persistence(
    service_factory,
    sample_workdir: Path,
) -> None:
    class SensitiveAlignmentExecutor(FakeCodexExecutor):
        def execute(self, request, emit_event, _should_stop, set_child_pid) -> dict:
            set_child_pid(None)
            emit_event(
                "codex_event",
                {
                    "type": "command",
                    "message": ("codex exec --token leak-command-token\nAuthorization: Bearer leak-bearer-token\nCookie: sid=leak-cookie-token"),
                    "auth_token": "leak-field-token",
                    "prompt": "leak-prompt-body",
                    "json_schema": {"secret": "leak-schema-body"},
                },
            )
            payload = self._alignment_agreement_response()
            request.output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return payload

    service = service_factory(scenario="success")
    service.executor_factory = SensitiveAlignmentExecutor
    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Create an alignment session with sensitive executor output.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    event = next(
        event for event in service.list_alignment_events(session["id"]) if event["event_type"] == "codex_event" and event["payload"].get("type") == "command"
    )
    artifact_events = (Path(session["artifact_dir"]) / "events" / "events.jsonl").read_text(encoding="utf-8")
    stdout_text = (Path(session["artifact_dir"]) / "invocations" / "0001" / "stdout.log").read_text(encoding="utf-8")
    persisted_event = json.dumps(event, ensure_ascii=False)

    for text in (persisted_event, artifact_events, stdout_text):
        assert "leak-command-token" not in text
        assert "leak-bearer-token" not in text
        assert "leak-cookie-token" not in text
        assert "leak-field-token" not in text
        assert "leak-prompt-body" not in text
        assert "leak-schema-body" not in text
    assert "<secret omitted>" in event["payload"]["message"]
    assert event["payload"]["command_truncated"] is True
    assert event["payload"]["payload_omitted"] is True
    assert {"auth_token", "json_schema", "prompt"}.issubset(set(event["payload"]["omitted_keys"]))


def test_alignment_repository_redacts_sensitive_values_before_db_and_artifact(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Create a local alignment event sink.",
        start_immediately=False,
    )

    event = service.repository.append_alignment_event(
        session["id"],
        "alignment_failed",
        {
            "message": "OPENAI_API_KEY=leak-env-token",
            "error": "Authorization: Bearer leak-error-token",
            "headers": {"Cookie": "sid=leak-cookie-token"},
            "auth_token": "leak-field-token",
            "prompt": "leak-prompt-body",
            "json_schema": {"secret": "leak-schema-body"},
            "bundle_yaml": "leak-bundle-body",
        },
    )
    listed = service.list_alignment_events(session["id"])[-1]
    artifact_events = (Path(session["artifact_dir"]) / "events" / "events.jsonl").read_text(encoding="utf-8")

    for text in (json.dumps(event, ensure_ascii=False), json.dumps(listed, ensure_ascii=False), artifact_events):
        assert "leak-env-token" not in text
        assert "leak-error-token" not in text
        assert "leak-cookie-token" not in text
        assert "leak-field-token" not in text
        assert "leak-prompt-body" not in text
        assert "leak-schema-body" not in text
        assert "leak-bundle-body" not in text
    assert listed["payload"]["auth_token"] == "<secret omitted>"
    assert listed["payload"]["prompt_omitted"] is True
    assert listed["payload"]["json_schema_omitted"] is True
    assert listed["payload"]["bundle_yaml_omitted"] is True


def test_alignment_service_waits_for_user_question(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="I need help shaping this task.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["transcript"][-1]["role"] == "assistant"
    assert "推荐" in session["transcript"][-1]["content"]
    options = session["transcript"][-1]["decision_options"]
    assert len(options) >= 2
    assert options[0]["recommended"] is True
    assert "优先阻断假完成" in options[0]["label"]
    assert options[0]["user_reply"]
    assert not Path(session["bundle_path"]).exists()
    assert session["native_resume_available"] is True
    assert session["executor_session_ref"]["session_id"]


def test_alignment_service_keeps_not_fit_gate_in_dialogue(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_not_fit")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Just run one obvious one-off edit.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "一次 Agent 执行加一次人工 review" in session["transcript"][-1]["content"]
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    assert "Skip Loop" in session["transcript"][-1]["decision_options"][0]["label"]
    assert session["alignment_stage"] == "clarifying"


def test_alignment_service_keeps_blocked_not_fit_output_in_dialogue(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_not_fit_without_needs_user_input")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Just run one obvious one-off edit.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert session["error_message"] == ""
    assert "反复出现的判断或新证据" in session["transcript"][-1]["content"]
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    assert session["alignment_stage"] == "clarifying"
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_waiting_user" for event in events)
    assert not any(event["event_type"] == "alignment_failed" for event in events)


def test_alignment_service_reframes_mechanical_configuration_questions(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_mechanical_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个长期任务。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")
    assistant_message = session["transcript"][-1]["content"]

    assert "配置两个 Inspector" not in assistant_message
    assert "推荐" in assistant_message
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_question_reframed"
        and {"mechanical_configuration_question", "missing_recommended_decision_options"}.issubset(set(event["payload"].get("issues", [])))
        for event in events
    )


def test_alignment_service_reframes_generic_preference_questions(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_generic_preference_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个长期任务。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")
    assistant_message = session["transcript"][-1]["content"]

    assert "你有什么偏好" not in assistant_message
    assert "推荐" in assistant_message
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_question_reframed"
        and {"generic_alignment_question", "missing_recommended_decision_options"}.issubset(set(event["payload"].get("issues", [])))
        for event in events
    )


def test_alignment_service_reframes_clarifying_questionnaires(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_questionnaire_overload")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个长期任务。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")
    assistant_message = session["transcript"][-1]["content"]

    assert "1. 你想完成什么任务" not in assistant_message
    assert "推荐" in assistant_message
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_question_reframed"
        and {"questionnaire_overload", "missing_recommended_decision_options"}.issubset(set(event["payload"].get("issues", [])))
        for event in events
    )


def test_alignment_service_materializes_visible_working_agreement(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_hidden_agreement_message")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a governed starter experience.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")
    visible_agreement = session["transcript"][-1]["content"]

    assert visible_agreement.startswith("Please confirm this working agreement.")
    assert "Loopora fit:" in visible_agreement
    assert "Task scope:" in visible_agreement
    assert "Success surface:" in visible_agreement
    assert "Residual risk:" in visible_agreement
    assert "Judgment tradeoffs:" in visible_agreement
    assert "Role posture:" in visible_agreement
    assert "Workflow shape:" in visible_agreement
    assert "Proven, Weak, Unproven, Blocking" in visible_agreement
    assert visible_agreement != "Please confirm."
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    assert "Use this direction" in session["transcript"][-1]["decision_options"][0]["label"]


def test_alignment_service_materializes_chinese_working_agreement(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_hidden_agreement_message")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个需要多轮证据判断的 Loop。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")
    visible_agreement = session["transcript"][-1]["content"]

    assert visible_agreement.startswith("请先确认这份工作协议。")
    assert "为什么用 Loopora：" in visible_agreement
    assert "后续轮次需要新证据" in visible_agreement
    assert "判断取舍：" in visible_agreement
    assert "workflow 形状：" in visible_agreement
    assert visible_agreement != "Please confirm."
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    assert "采用这个方向" in session["transcript"][-1]["decision_options"][0]["label"]


def test_alignment_service_treats_confirmation_with_correction_as_adjustment(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个需要证据判断的中文任务。",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "可以，但把证据偏好改成浏览器截图和命令输出。")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert session["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is False
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_agreement_reopened" for event in events)
    assert not any(event["event_type"] == "alignment_agreement_confirmed" for event in events)


def test_alignment_service_accepts_confirmation_that_says_no_changes(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个需要证据判断的中文任务。",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "可以，不需要修改，继续。")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is True
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_agreement_confirmed" for event in events)


def test_alignment_service_accepts_english_confirmation_with_no_change_clause(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a governed starter experience.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "OK, but no changes, proceed.")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is True
    assert session["working_agreement"]["confirmation_message"] == "OK, but no changes, proceed."
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_agreement_confirmed" for event in events)


def test_alignment_service_treats_confirmation_with_addition_as_adjustment(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a governed starter experience.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "OK, add browser screenshot evidence before generating.")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert session["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is False
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_agreement_reopened" for event in events)
    assert not any(event["event_type"] == "alignment_agreement_confirmed" for event in events)


def test_alignment_service_blocks_chinese_agreement_with_english_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_agreement_for_chinese_user")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert not session["working_agreement"]
    assert "需要使用中文" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_language_mismatch" and "agreement_summary" in event["payload"].get("missing", []) for event in events)


def test_alignment_service_rewrites_english_clarifying_message_for_chinese_user(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_clarifying_message_for_chinese_user")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assistant_message = session["transcript"][-1]["content"]
    assert "推荐判断" in assistant_message
    assert "What evidence" not in assistant_message
    events = service.list_alignment_events(created["id"])
    assert session["transcript"][-1]["decision_options"][0]["recommended"] is True
    assert any(
        event["event_type"] == "alignment_question_reframed"
        and "missing_recommended_decision_options" in event["payload"].get("issues", [])
        for event in events
    )


def test_alignment_service_blocks_chinese_bundle_with_english_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_bundle_for_chinese_user")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "需要使用中文" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "agreement_summary" in event["payload"].get("error", "") for event in events)


def test_alignment_service_rewrites_english_bundle_message_for_chinese_user(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_assistant_message_for_chinese_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["validation"]["ok"] is True
    assert session["transcript"][-1]["content"] == "已整理成一个可导入的 Loopora bundle。"
    assert "I prepared" not in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_language_mismatch" and event["payload"].get("missing") == ["assistant_message"] for event in events)


def test_alignment_service_blocks_chinese_bundle_with_english_prose(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_bundle_prose_for_chinese_user")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert not session["validation"]["ok"]
    assert "bundle field collaboration_summary must follow Chinese user language" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_validation_failed" and "bundle field collaboration_summary" in event["payload"].get("error", "") for event in events
    )


def test_alignment_service_blocks_chinese_bundle_with_english_visible_names(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_english_visible_bundle_names_for_chinese_user")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我编排一个中文任务的 Loop。",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert not session["validation"]["ok"]
    assert "bundle field metadata.name must follow Chinese user language" in session["error_message"]
    assert "bundle field loop.name must follow Chinese user language" in session["error_message"]
    assert "bundle role_definition builder.name must follow Chinese user language" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_validation_failed" and "bundle role_definition builder.name" in event["payload"].get("error", "") for event in events
    )


def test_alignment_service_blocks_agreement_with_incomplete_checklist(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_incomplete_agreement_checklist")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without workflow judgment.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert not session["working_agreement"]
    assert "workflow_shape" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_checklist_incomplete" and "workflow_shape" in event["payload"].get("missing", []) for event in events)


def test_alignment_service_blocks_agreement_with_unresolved_open_questions(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_unresolved_open_questions")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience where evidence choice still matters.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert not session["working_agreement"]
    assert "open_questions" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_evidence_incomplete" and "open_questions" in event["payload"].get("missing", []) for event in events)


def test_alignment_service_blocks_agreement_without_evidence_bucket_projection(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_missing_evidence_bucket_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience where final evidence buckets should be visible before confirmation.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert not session["working_agreement"]
    assert "evidence_buckets" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_evidence_incomplete" and "evidence_buckets" in event["payload"].get("missing", []) for event in events)


def test_alignment_prompt_and_source_sync_follow_user_language(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir()
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir()

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请帮我生成一个中文任务的循环方案。",
    )
    session = _confirm_alignment_agreement(service, created["id"])
    artifact_root = Path(session["artifact_dir"])
    prompt_text = (artifact_root / "invocations" / "0001" / "prompt.md").read_text(encoding="utf-8")

    assert prompt_text.index("## Loopora Product Primer") < prompt_text.index("## Agent-Led Compiler Policy")
    assert "## Embedded Skill" not in prompt_text
    for snippet in (
        "User language hint: `Chinese",
        "Assume you know nothing about Loopora except what is embedded below.",
        "internal Web compiler",
        "Agent drives semantic conversation; Loopora backend decides",
        "## Active Compiler Gate",
        "Current compiler gate: confirmed agreement",
        "Allowed candidate phase: bundle, or clarifying if a human-required judgment gap is discovered",
        "The Agent drives the semantic conversation. Loopora backend only accepts or rejects candidate phases.",
        "Before asking the user, answer anything you can from the transcript",
        "Follow the current decision branch",
        "Agent-led conversation is not a questionnaire",
        "branch-aware pressure testing",
        "answer everything you can from the transcript",
        "Follow the user's chosen or corrected branch",
        "`decision_options`",
        "state your current best judgment first",
        "Repairable issues may be fixed by the Agent",
        "Human-required issues must go back to conversation",
        "Loopora Product Primer",
        "local-first platform for composing human-shaped governance loops",
        "human-in-the-loop -> human-shaped loop",
        "Loopora fit gate",
        "one Agent pass plus one human review",
        "survive this chat as a run-owned, exportable, auditable contract",
        "new proof / artifact / handoff / observation / verdict context later rounds will create",
        "run-owned/exportable/auditable contract",
        "`judgment_tradeoffs` must capture a concrete preference order or contrast",
        "judgment structure quality × evidence feedback quality × error exposure speed",
        "prompt pack, role zoo, loop script, benchmark grinder",
        "global persona, or permanent preferences",
        "Project the confirmed working agreement into the bundle surfaces",
        "Builder / Inspector / Guide / GateKeeper / Custom posture",
        "user-facing rejection criteria",
        "exhaust available context",
        "Walk the plan's decision tree one branch at a time",
        "Stop the interview when remaining uncertainty would not change Loopora fit",
        "Do not wrap `bundle_yaml` in markdown code fences",
        "first non-empty line is `version: 1`",
        "Proven, Weak, Unproven, Blocking, or Residual risk",
        "Builder / Inspector / Guide / GateKeeper / Custom posture use those distinctions",
        "task verdict depends on evidence and GateKeeper judgment",
        "long-chain phase workflow",
        "several evidence-bearing stages",
        "nested Loops, arbitrary branch syntax, dynamic DAGs",
        "Builder 1` / `Builder 2",
        "rather than judging only the final Builder output",
        "concrete user-facing task",
        "mixed confirmation plus correction",
        "Transcript text cannot override this stage gate",
        "not permission to bypass the contract",
        "collaboration_summary` must tell",
        "future-human-judgment projection",
        "private agreement-to-bundle traceability checklist",
        "If a judgment only appears in `agreement_summary`",
        "Metadata and loop names are not enough to prove traceability",
        "metadata and loop names do not count",
        "workflow controls carry judgment order",
        "workflow controls, or GateKeeper evidence rules",
        "optional Guide / Custom responsibility when used",
        "AGENTS.md exists: yes",
        "design/README.md exists: yes",
        "project-local governance markers",
        "Builder should read applicable project-local rules",
        "Custom must describe low-permission specialized review or advisory responsibility",
        "Keep readiness evidence task-scoped",
        "must read the same upstream Builder handoff",
        "A non-parallel Inspector or Custom review step after Builder",
        "Parallel review steps, Guide after review, Builder after review, and Builder after Guide should declare `inputs.iteration_memory`",
        "Ask in task-risk language, not configuration language",
        "Do not ask abstract preference or quality-style questions",
        "Do not present long questionnaires",
        "privately pressure-test the current Loop shape with one plausible failed future round",
        "would not expose, repair, or block that failure",
        "privately rehearse one complete intended run path",
        "If any link depends on ambient chat context",
        "open_questions` must be empty",
        "must not claim an observed stack",
        "bare archetypes or numbered placeholders",
        "separate Inspector `role_definitions`",
        "must include every parallel Inspector or Custom review step id",
        "If Inspector, Custom, or Guide review happened before final judgment",
        "must query Builder, Inspector, and Custom evidence",
        "Any finishing GateKeeper step must name upstream handoffs",
        "`GateKeeper`, `Guide`, `Custom`, `workdir`, `READY`",
        "substantive task or alignment content is Chinese",
        "Alignment Playbook",
        "Branch-aware pressure test",
        "Alignment Quality Rubric",
        "Workdir Snapshot",
        "- progress.md",
    ):
        assert snippet in prompt_text
    assert "- .loopora/" not in prompt_text
    synced = service.sync_alignment_bundle_from_file(session["id"])

    assert synced["ok"] is True
    refreshed = service.get_alignment_session(session["id"])
    assert "已重新读取 bundle.yml" in refreshed["transcript"][-1]["content"]


def test_alignment_language_hint_ignores_confirmation_only_chinese(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")
    prompt_text = (Path(session["artifact_dir"]) / "invocations" / "0001" / "prompt.md").read_text(encoding="utf-8")

    assert "I prepared an importable Loopora bundle." in session["transcript"][-1]["content"]
    assert "User language hint: `Follow the user's language from the transcript" in prompt_text
    assert "User language hint: `Chinese" not in prompt_text


def test_alignment_bundle_source_file_rejects_invalid_utf8(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    preview_session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create a previewable Loop.")["id"],
    )
    Path(preview_session["bundle_path"]).write_bytes(b"\xff")

    preview = service.get_alignment_bundle(preview_session["id"])
    assert preview["ok"] is False
    assert preview["yaml"] == ""
    assert "UTF-8 encoded YAML" in preview["validation"]["error"]

    sync_result = service.sync_alignment_bundle_from_file(preview_session["id"])
    assert sync_result["ok"] is False
    assert "UTF-8 encoded YAML" in sync_result["validation"]["error"]
    synced_session = service.get_alignment_session(preview_session["id"])
    assert synced_session["status"] == "failed"
    assert "UTF-8 encoded YAML" in synced_session["error_message"]
    assert any(event["event_type"] == "alignment_bundle_sync_failed" for event in service.list_alignment_events(preview_session["id"]))

    import_session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create an importable Loop.")["id"],
    )
    Path(import_session["bundle_path"]).write_bytes(b"\xff")
    client = TestClient(build_app(service=service))

    import_response = client.post(
        f"/api/alignments/sessions/{import_session['id']}/import",
        json={"start_immediately": False},
    )
    assert import_response.status_code == 400
    assert "UTF-8 encoded YAML" in import_response.json()["error"]
    import_failed_session = service.get_alignment_session(import_session["id"])
    assert import_failed_session["status"] == "ready"
    assert "UTF-8 encoded YAML" in import_failed_session["error_message"]
    assert any(event["event_type"] == "alignment_import_failed" for event in service.list_alignment_events(import_session["id"]))


def test_alignment_message_after_corrupt_ready_bundle_keeps_session_usable(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create a recoverable Loop.")["id"],
    )
    Path(session["bundle_path"]).write_bytes(b"\xff")

    service.append_alignment_message(session["id"], "请根据对话重新整理方案。")

    continued = _wait_for_status(service, session["id"], "waiting_user")
    assert continued["error_message"] == ""
    assert continued["transcript"][-1]["role"] == "assistant"


def test_alignment_service_blocks_premature_bundle_output(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_premature_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience.",
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "finish alignment" in session["transcript"][-1]["content"]
    assert "Loop plan" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" for event in events)


def test_alignment_service_blocks_bundle_without_readiness_evidence(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_missing_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience, but do not explain the posture evidence.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "readiness evidence" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" for event in events)


def test_alignment_service_blocks_bundle_without_loop_fit_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_missing_loop_fit_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a one-pass starter experience without proving Loopora is needed.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "loop_fit" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "loop_fit" in event["payload"].get("error", "") for event in events)


@pytest.mark.parametrize(
    "scenario",
    [
        "alignment_contradictory_loop_fit_readiness_evidence",
        "alignment_single_pass_sufficient_loop_fit_readiness_evidence",
        "alignment_benchmark_only_loop_fit_readiness_evidence",
        "alignment_chinese_direct_chat_loop_fit_readiness_evidence",
    ],
)
def test_alignment_service_blocks_agreement_that_contradicts_loop_fit(
    service_factory,
    sample_workdir: Path,
    scenario: str,
) -> None:
    service = service_factory(scenario=scenario)

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a task that may only need one Agent pass.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "loop_fit" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "loop_fit" in event["payload"].get("error", "") for event in events)


def test_alignment_service_accepts_nonempty_loop_fit_readiness_evidence_without_keyword_gate(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_vague_loop_fit_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a complex but possibly one-pass starter experience.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["validation"]["ok"] is True


def test_alignment_service_accepts_loop_fit_evidence_without_full_keyword_set(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_single_marker_loop_fit_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a task that only says it needs review.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["validation"]["ok"] is True


def test_alignment_service_accepts_loop_fit_evidence_without_new_evidence_keyword(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_loop_fit_without_new_evidence_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a task that mentions GateKeeper but not new evidence.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["validation"]["ok"] is True


def test_alignment_service_blocks_bundle_without_residual_risk_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_missing_residual_risk_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without clarifying what risks can remain.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "residual_risk_policy" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "residual_risk_policy" in event["payload"].get("error", "") for event in events)


def test_alignment_service_accepts_nonempty_residual_risk_readiness_evidence_without_keyword_gate(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_vague_residual_risk_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience with a vague risk policy.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["validation"]["ok"] is True


def test_alignment_service_blocks_invented_workdir_facts_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_invented_workdir_facts_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without grounding workdir facts.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "workdir_facts" in session["transcript"][-1]["content"]


def test_alignment_service_blocks_observed_stack_claims_not_in_workdir_snapshot(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_invented_observed_workdir_facts_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without inventing stack facts.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "workdir_facts" in session["transcript"][-1]["content"]
    prompt_text = (Path(session["artifact_dir"]) / "invocations" / "0001" / "prompt.md").read_text(encoding="utf-8")
    assert "package.json" not in prompt_text
    assert "tests/ exists: no" in prompt_text


def test_alignment_service_blocks_bundle_observed_stack_claims_not_in_workdir_snapshot(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_bundle_unsupported_observed_workdir_claim")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without inventing stack facts in the final bundle.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert not session["validation"]["ok"]
    assert "bundle field spec.markdown must not claim an observed workdir stack" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_validation_failed" and "bundle field spec.markdown" in event["payload"].get("error", "") for event in events)


def test_alignment_service_blocks_governance_markers_without_role_responsibilities(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_governance_markers_listed_without_responsibilities")
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir()
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir()

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience that must respect local project governance markers.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert not session["validation"]["ok"]
    assert "project-local governance markers" in session["error_message"]
    assert "Builder reading" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_validation_failed" and "project-local governance markers" in event["payload"].get("error", "") for event in events
    )


def test_alignment_traceability_checks_governance_markers_across_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(
        alignment_bundle_yaml(str(sample_workdir)).replace(
            "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
            "Workdir Snapshot detected AGENTS.md and tests/. Ship the focused starter experience.",
        )
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "evidence_preferences": "AGENTS.md and tests/ are project-local governance markers that must shape runtime evidence.",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("project-local governance markers" in issue for issue in issues)


def test_alignment_traceability_ignores_metadata_and_loop_names(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["metadata"]["name"] = "browsertrace"
    bundle["metadata"]["description"] = "browsertrace"
    bundle["loop"]["name"] = "browsertrace"
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "evidence_preferences": "browsertrace",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("evidence_preferences missing browsertrace" in issue for issue in issues)


def test_alignment_traceability_counts_workflow_step_inputs_as_runtime_surface(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["workflow"]["steps"][0]["inputs"] = {"evidence_query": {"target_ids": ["browsertrace"]}}
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "evidence_preferences": "browsertrace",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert not any("evidence_preferences" in issue for issue in issues)


def test_alignment_service_blocks_generated_bundle_lineage_metadata(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_generated_lineage_metadata")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a standalone candidate bundle, not a lineage revision.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "must omit metadata.source_bundle_id and metadata.revision" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_validation_failed" and "source context is temporary" in event["payload"].get("error", "") for event in events)


def test_alignment_service_blocks_markdown_fenced_bundle_yaml(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_markdown_fenced_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a raw YAML bundle without wrappers.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "must be one raw YAML document" in session["error_message"]
    assert "must start with version: 1" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_validation_failed" and "markdown-fenced output" in event["payload"].get("error", "") for event in events)


def test_alignment_service_blocks_bundle_that_drops_confirmed_agreement_specifics(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_refund_agreement_generic_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a governed refund self-service flow.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "confirmed working agreement evidence" in session["error_message"]
    assert "refund" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_validation_failed" and "confirmed working agreement evidence" in event["payload"].get("error", "") for event in events
    )


def test_alignment_service_blocks_chinese_bundle_that_drops_confirmed_agreement_specifics(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_chinese_refund_agreement_generic_bundle")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请编排一个受治理的退款自助流程。",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "confirmed working agreement evidence" in session["error_message"]
    assert "退款" in session["error_message"]


@pytest.mark.parametrize(
    ("scenario", "missing_key"),
    [
        ("alignment_vague_task_scope_readiness_evidence", "task_scope"),
        ("alignment_vague_success_surface_readiness_evidence", "success_surface"),
        ("alignment_vague_fake_done_readiness_evidence", "fake_done_risks"),
        ("alignment_vague_judgment_tradeoffs_readiness_evidence", "judgment_tradeoffs"),
        ("alignment_vague_role_posture_readiness_evidence", "role_posture"),
        ("alignment_role_posture_without_gatekeeper_readiness_evidence", "role_posture"),
        ("alignment_vague_workflow_shape_readiness_evidence", "workflow_shape"),
        ("alignment_workflow_shape_without_error_exposure_readiness_evidence", "workflow_shape"),
        ("alignment_workflow_shape_without_gatekeeper_readiness_evidence", "workflow_shape"),
    ],
)
def test_alignment_service_accepts_nonempty_bundle_shaping_readiness_evidence_without_keyword_gate(
    service_factory,
    sample_workdir: Path,
    scenario: str,
    missing_key: str,
) -> None:
    service = service_factory(scenario=scenario)

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message=f"Build a starter experience with weak {missing_key} evidence.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "ready")

    assert Path(session["bundle_path"]).exists()
    assert session["validation"]["ok"] is True
    assert session["working_agreement"]["readiness_evidence"][missing_key]


def test_alignment_service_blocks_global_persona_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_global_persona_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without turning task judgment into memory.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "task_scoped_judgment" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] in {"alignment_evidence_incomplete", "alignment_stage_blocked"}
        and ("task_scoped_judgment" in event["payload"].get("missing", []) or "task_scoped_judgment" in event["payload"].get("error", ""))
        for event in events
    )


def test_alignment_service_accepts_chinese_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_chinese_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="请用中文对齐这个需要多轮证据判断的任务。",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["validation"]["ok"] is True
    assert Path(session["bundle_path"]).exists()
    bundle_text = Path(session["bundle_path"]).read_text(encoding="utf-8")
    assert "将工作协议投影到 spec" in bundle_text
    assert "name: 对齐 Starter Bundle" in bundle_text
    assert "name: 聚焦 Builder" in bundle_text
    assert "中文整理" in session["transcript"][-1]["content"]
    assert not any(event["event_type"] == "alignment_stage_blocked" for event in service.list_alignment_events(created["id"]))


def test_alignment_service_accepts_survive_chat_as_loop_fit_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_survive_chat_loop_fit_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a task whose judgment should survive the current chat.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["validation"]["ok"] is True
    assert Path(session["bundle_path"]).exists()
    assert "survive one chat" in session["working_agreement"]["readiness_evidence"]["loop_fit"]
    assert not any(event["event_type"] == "alignment_stage_blocked" for event in service.list_alignment_events(created["id"]))


def test_alignment_service_reuses_executor_session_ref_between_turns(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_question")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="I need help shaping this task.",
    )
    first = _wait_for_status(service, created["id"], "waiting_user")
    first_session_id = first["executor_session_ref"]["session_id"]

    service.append_alignment_message(created["id"], "更怕做糙。")
    second = _wait_for_status(service, created["id"], "waiting_user")

    assert second["executor_session_ref"]["session_id"] == first_session_id
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_executor_session_ref" for event in events)


def test_alignment_service_falls_back_when_native_resume_fails(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_resume_failure")

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle after resume trouble.",
        start_immediately=False,
    )
    service.repository.update_alignment_session(session["id"], executor_session_ref={"session_id": "stale-session"})
    service.start_alignment_session_async(session["id"])
    _wait_for_status(service, session["id"], "waiting_user")
    service.repository.update_alignment_session(
        session["id"],
        alignment_stage="confirmed",
        working_agreement={"summary": "Confirmed test agreement.", "confirmed_at": "test"},
    )
    service.start_alignment_session_async(session["id"])
    ready = _wait_for_status(service, session["id"], "ready")

    assert ready["validation"]["ok"] is True
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_native_resume_fallback" for event in events)


def test_alignment_service_repairs_invalid_bundle_once(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid_then_valid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle, and recover if the first draft is malformed.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is True
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_repair_started" for event in events)


def test_alignment_service_repairs_semantically_incomplete_bundle_once(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_semantic_invalid_then_valid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a semantically complete bundle.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is True
    failed_events = [event for event in service.list_alignment_events(created["id"]) if event["event_type"] == "alignment_validation_failed"]
    assert failed_events
    assert "semantic lint" in failed_events[0]["payload"]["error"]


def test_alignment_service_fails_after_invalid_repair(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="alignment_invalid")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle that remains invalid.",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert session["repair_attempts"] == 1
    assert session["validation"]["ok"] is False
    assert "collaboration_summary" in session["error_message"]


def test_alignment_service_normalizes_custom_command_settings(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")

    session = service.create_alignment_session(
        workdir=sample_workdir,
        executor_kind="custom",
        executor_mode="preset",
        command_cli="my-aligner",
        command_args_text="{prompt}\n--output\n{output_path}",
        start_immediately=False,
    )

    assert session["executor_kind"] == "custom"
    assert session["executor_mode"] == "command"
    assert session["command_cli"] == "my-aligner"
    assert session["model"] == ""
    assert session["reasoning_effort"] == ""


def test_alignment_service_blocks_custom_executor_bundle_that_drops_session_settings(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Generate a bundle that preserves the selected runtime.",
        executor_kind="custom",
        executor_mode="preset",
        command_cli="my-aligner",
        command_args_text="{prompt}\n--output\n{output_path}",
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "must preserve selected Web executor settings" in session["error_message"]
    assert "loop.executor_kind" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_validation_failed" and "command/custom sessions" in event["payload"].get("error", "") for event in events)


def test_alignment_api_covers_session_events_bundle_and_import(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/alignments/sessions",
        json={"workdir": str(sample_workdir), "message": "Create a runnable bundle."},
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    _wait_for_status(service, session_id, "waiting_user")
    confirm_response = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "确认"})
    assert confirm_response.status_code == 200
    _wait_for_status(service, session_id, "ready")

    session_response = client.get(f"/api/alignments/sessions/{session_id}")
    assert session_response.status_code == 200
    assert session_response.json()["session"]["status"] == "ready"

    events_response = client.get(f"/api/alignments/sessions/{session_id}/events")
    assert events_response.status_code == 200
    assert any(event["event_type"] == "alignment_ready" for event in events_response.json())

    with client.stream("GET", f"/api/alignments/sessions/{session_id}/stream") as stream_response:
        assert stream_response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in stream_response.iter_text())
    assert "alignment_ready" in body

    list_response = client.get("/api/alignments/sessions")
    assert list_response.status_code == 200
    assert list_response.json()["sessions"][0]["id"] == session_id
    assert list_response.json()["sessions"][0]["native_resume_available"] is True

    bundle_response = client.get(f"/api/alignments/sessions/{session_id}/bundle")
    assert bundle_response.status_code == 200
    bundle_payload = bundle_response.json()
    assert bundle_payload["ok"] is True
    assert bundle_payload["workflow_preview"]["roles"][0]["archetype"] == "builder"

    bundle_path = Path(service.get_alignment_session(session_id)["bundle_path"])
    bundle_path.write_text(
        bundle_path.read_text(encoding="utf-8").replace("Aligned Starter Bundle", "Synced Starter Bundle", 1),
        encoding="utf-8",
    )
    sync_response = client.post(f"/api/alignments/sessions/{session_id}/bundle/sync")
    assert sync_response.status_code == 200
    sync_payload = sync_response.json()
    assert sync_payload["ok"] is True
    assert sync_payload["metadata"]["name"] == "Synced Starter Bundle"
    assert sync_payload["session"]["status"] == "ready"
    assert any(event["event_type"] == "alignment_bundle_synced" for event in service.list_alignment_events(session_id))

    import_response = client.post(
        f"/api/alignments/sessions/{session_id}/import",
        json={"start_immediately": False},
    )
    assert import_response.status_code == 201
    assert import_response.json()["bundle"]["id"]
    assert import_response.json()["session"]["status"] == "imported"

    delete_response = client.delete(f"/api/alignments/sessions/{session_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    assert client.get(f"/api/alignments/sessions/{session_id}").status_code == 404
    assert client.get("/api/alignments/sessions").json()["sessions"] == []


def test_alignment_stream_emits_redacted_stream_error_on_backend_failure(caplog) -> None:
    class FlakyService:
        def get_alignment_session(self, session_id: str) -> dict:
            return {"id": session_id, "status": "running"}

        def list_alignment_events(self, session_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            assert session_id == "session_test"
            assert after_id == 9
            assert limit == 200
            raise RuntimeError("alignment database unavailable")

    client = TestClient(build_app(service=FlakyService()))

    with caplog.at_level(logging.ERROR, logger="loopora.web"), client.stream("GET", "/api/alignments/sessions/session_test/stream?after_id=9") as response:
        assert response.status_code == 200
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert "event: stream_error" in body
    assert "alignment database unavailable" not in body
    payload = json.loads(next(line.removeprefix("data: ") for line in body.splitlines() if line.startswith("data: ")))
    assert payload == {
        "session_id": "session_test",
        "after_id": 9,
        "error": "stream_unavailable",
        "retryable": True,
    }
    assert any(
        getattr(record, "event", "") == "web.alignment_stream.failed" and record.exc_info and "alignment database unavailable" in str(record.exc_info[1])
        for record in caplog.records
    )


def test_alignment_event_api_rejects_out_of_range_query_params(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    for path in (
        "/api/alignments/sessions?limit=0",
        "/api/alignments/sessions?limit=101",
        "/api/alignments/sessions/session_test/events?after_id=-1",
        f"/api/alignments/sessions/session_test/events?after_id={MAX_EVENT_CURSOR_ID + 1}",
        "/api/alignments/sessions/session_test/events?limit=0",
        "/api/alignments/sessions/session_test/events?limit=5001",
        "/api/alignments/sessions/session_test/stream?after_id=-1",
        f"/api/alignments/sessions/session_test/stream?after_id={MAX_EVENT_CURSOR_ID + 1}",
    ):
        response = client.get(path)
        assert response.status_code == 400
        assert response.json()["error"] == "request validation failed"


def test_alignment_stream_logs_invalid_resume_cursor_and_keeps_request_cursor(caplog) -> None:
    captured: dict[str, int] = {}

    class CursorAwareService:
        def get_alignment_session(self, session_id: str) -> dict:
            return {"id": session_id, "status": "ready"}

        def list_alignment_events(self, session_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
            assert session_id == "session_test"
            assert limit == 200
            captured["after_id"] = after_id
            return []

    client = TestClient(build_app(service=CursorAwareService()))

    with (
        caplog.at_level(logging.WARNING, logger="loopora.web"),
        client.stream(
            "GET",
            "/api/alignments/sessions/session_test/stream?after_id=7",
            headers={"Last-Event-ID": str(MAX_EVENT_CURSOR_ID + 1)},
        ) as response,
    ):
        assert response.status_code == 200
        assert "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()) == ""

    assert captured["after_id"] == 7
    assert any(
        getattr(record, "event", "") == "web.alignment_stream.resume_cursor_invalid"
        and getattr(record, "context", {}).get("session_id") == "session_test"
        and getattr(record, "context", {}).get("after_id") == 7
        for record in caplog.records
    )


def _create_alignment_improvement_source_bundle(
    service,
    sample_spec_file: Path,
    sample_workdir: Path,
    *,
    completion_mode: str = "gatekeeper",
) -> dict:
    loop = service.create_loop(
        name="Improvement Source Loop",
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
        completion_mode=completion_mode,
    )
    return service.import_bundle_text(
        bundle_to_yaml(
            service.derive_bundle_from_loop(
                loop["id"],
                name="Improvement Source Bundle",
                description="Start from an existing bundle.",
                collaboration_summary="Prefer evidence before changing posture.",
            )
        )
    )


def test_alignment_improvement_session_can_start_from_existing_bundle(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)

    session = service.create_bundle_revision_session(source["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "bundle"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == ""
    assert agreement["source"]["source_completion_mode"] == "gatekeeper"
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == ""
    assert preview["bundle"]["metadata"]["revision"] == 1
    assert "source_bundle_id" not in preview["yaml"]
    assert "revision:" not in preview["yaml"]
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_bundle_improvement_seeded" for event in events)


def test_alignment_improvement_session_materializes_preservation_and_delta(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)

    created = service.create_bundle_revision_session(
        source["id"],
        message="Please improve this Loop while preserving its stable intent.",
        start_immediately=True,
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "agreement_ready"
    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    evidence = agreement["readiness_evidence"]
    assert "Preserve" in evidence["task_scope"]
    assert "change" in evidence["task_scope"]
    assert "evidence" in evidence["workflow_shape"]
    visible_agreement = session["transcript"][-1]["content"]
    assert "Preserve" in visible_agreement
    assert "source bundle" in evidence["task_scope"]


def test_alignment_improvement_session_requires_completion_mode_delta_for_rounds_source(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(
        service,
        sample_spec_file,
        sample_workdir,
        completion_mode="rounds",
    )

    created = service.create_bundle_revision_session(
        source["id"],
        message="Please improve this Loop while preserving its stable intent.",
        start_immediately=True,
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert session["working_agreement"]["source"]["source_completion_mode"] == "rounds"
    assert "improvement_completion_mode_delta" in session["transcript"][-1]["content"]
    prompt_text = (Path(session["artifact_dir"]) / "invocations" / "0001" / "prompt.md").read_text(encoding="utf-8")
    assert "Source completion mode: rounds" in prompt_text
    assert "conversion to evidence-backed GateKeeper task verdicts" in prompt_text
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_improvement_incomplete" and "improvement_completion_mode_delta" in event["payload"].get("missing", [])
        for event in events
    )


def test_alignment_improvement_bundle_requires_completion_mode_delta_for_rounds_source(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["collaboration_summary"] = (
        "Preserve the source Loop stable intent, source workdir, and useful source posture while applying "
        "a feedback-driven governance delta that maps to spec, roles, workflow, evidence expectations, "
        "and GateKeeper strictness."
    )
    session = {
        "working_agreement": {
            "mode": "improvement",
            "source": {
                "source_completion_mode": "rounds",
            },
        },
    }

    issues = service._alignment_improvement_bundle_issues(session, bundle)

    assert "improvement bundle must state the source completion-mode governance delta" in issues


def test_alignment_improvement_bundle_rejects_reusing_source_bundle_id(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source_bundle_id = "bundle_source"
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["metadata"]["bundle_id"] = source_bundle_id
    bundle["collaboration_summary"] = (
        "Preserve the source Loop stable intent, source workdir, and useful source posture while applying "
        "a feedback-driven governance delta that maps to spec, roles, workflow, evidence expectations, "
        "and GateKeeper strictness."
    )
    session = {
        "working_agreement": {
            "mode": "improvement",
            "source": {
                "source_bundle_id": source_bundle_id,
                "source_completion_mode": "gatekeeper",
            },
        },
    }

    issues = service._alignment_improvement_bundle_issues(session, bundle)

    assert (
        "improvement bundle must not reuse the source bundle id as metadata.bundle_id; leave bundle_id empty or choose a new standalone candidate id"
    ) in issues


def test_alignment_improvement_session_validates_feedback_driven_bundle_delta(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)

    created = service.create_bundle_revision_session(
        source["id"],
        message="Please improve this Loop while preserving its stable intent.",
        start_immediately=True,
    )
    session = _confirm_alignment_agreement(service, created["id"])

    assert session["validation"]["ok"] is True
    bundle_text = Path(session["bundle_path"]).read_text(encoding="utf-8")
    assert "Preserve the source Loop" in bundle_text
    assert "feedback-driven governance delta" in bundle_text
    assert "spec" in bundle_text
    assert "roles" in bundle_text
    assert "workflow" in bundle_text


def test_alignment_improvement_session_blocks_generic_final_bundle(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_improvement_generic_bundle")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)

    created = service.create_bundle_revision_session(
        source["id"],
        message="Please improve this Loop while preserving its stable intent.",
        start_immediately=True,
    )
    session = _confirm_alignment_agreement(service, created["id"], "failed")

    assert session["validation"]["ok"] is False
    assert "feedback-driven governance delta" in session["error_message"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_validation_failed"
        and "improvement bundle must state the feedback-driven governance delta" in event["payload"].get("error", "")
        for event in events
    )


def test_alignment_improvement_session_blocks_vague_improvement_agreement(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_improvement_missing_delta")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)

    created = service.create_bundle_revision_session(
        source["id"],
        message="Please improve this Loop.",
        start_immediately=True,
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_improvement_incomplete" and "improvement_delta" in event["payload"].get("missing", []) for event in events)


def test_alignment_improvement_session_can_start_from_run_evidence(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Run Evidence Source Loop",
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
                name="Run Evidence Source Bundle",
                description="Start from run evidence.",
                collaboration_summary="Use GateKeeper evidence to improve the plan.",
            )
        )
    )
    run = service.rerun(source["loop_id"])

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == run["id"]
    assert agreement["source"]["run_status"] == run["status"]
    assert agreement["source"]["artifact_paths"]["task_verdict"] == "evidence/task_verdict.json"
    assert agreement["source"]["artifact_paths"]["evidence_ledger"] == "evidence/ledger.jsonl"
    assert agreement["source"]["artifact_paths"]["evidence_coverage"] == "evidence/coverage.json"
    assert agreement["source"]["artifact_paths"]["evidence_manifest"] == "evidence/manifest.json"
    assert "coverage_summary" in agreement["source"]
    assert any(item["artifact_refs"] for item in agreement["source"]["evidence_summary"])
    assert agreement["source"]["task_verdict"]["status"]
    assert "gatekeeper_verdict" in agreement["source"]
    assert agreement["source"]["gatekeeper_verdict"]["decision_summary"]
    context_text = alignment_module.ServiceAlignmentMixin._alignment_improvement_context_text(session)
    assert f"Source run status: {run['status']}" in context_text
    assert "Artifact paths:" in context_text
    assert "evidence/task_verdict.json" in context_text
    assert "Task verdict:" in context_text
    assert agreement["source"]["task_verdict"]["status"] in context_text
    assert "GateKeeper verdict:" in context_text
    assert "decision_summary" in context_text
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == ""
    assert "source_bundle_id" not in preview["yaml"]


def test_alignment_run_revision_tolerates_corrupt_evidence_ledger(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Corrupt Evidence Revision Loop",
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
    run = service.rerun(loop["id"])
    (Path(run["runs_dir"]) / "evidence" / "ledger.jsonl").write_bytes(b"\xff")

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_run_id"] == run["id"]
    assert agreement["source"]["artifact_paths"]["task_verdict"] == "evidence/task_verdict.json"
    assert agreement["source"]["artifact_paths"]["evidence_ledger"] == "evidence/ledger.jsonl"
    assert agreement["source"]["evidence_summary"] == []
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True


def test_alignment_api_creates_improvement_sessions_from_bundle_and_run(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="API Improvement Source Loop",
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
                name="API Improvement Source Bundle",
                description="API improvement source.",
                collaboration_summary="Keep the source posture visible.",
            )
        )
    )
    run = service.rerun(source["loop_id"])
    client = TestClient(build_app(service=service))

    bundle_response = client.post(f"/api/bundles/{source['id']}/revise", json={"start_immediately": False})
    assert bundle_response.status_code == 201
    bundle_payload = bundle_response.json()
    assert bundle_payload["redirect_url"] == (f"/loops/new/bundle?alignment_session_id={bundle_payload['session']['id']}")
    assert bundle_payload["session"]["working_agreement"]["mode"] == "improvement"
    assert bundle_payload["session"]["working_agreement"]["source"]["source_type"] == "bundle"
    assert bundle_payload["session"]["working_agreement"]["source"]["source_bundle_id"] == source["id"]

    run_response = client.post(f"/api/runs/{run['id']}/revise", json={"start_immediately": False})
    assert run_response.status_code == 201
    run_payload = run_response.json()
    assert run_payload["redirect_url"] == f"/loops/new/bundle?alignment_session_id={run_payload['session']['id']}"
    assert run_payload["session"]["working_agreement"]["mode"] == "improvement"
    assert run_payload["session"]["working_agreement"]["source"]["source_type"] == "run"
    assert run_payload["session"]["working_agreement"]["source"]["source_run_id"] == run["id"]


def test_alignment_workdir_context_discovers_spec_and_requires_explicit_selection(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    state_dir = sample_workdir / ".loopora"
    state_dir.mkdir()
    spec_path = state_dir / "spec.md"
    spec_path.write_text("# Task\n\n编排一个英语学习网站。\n", encoding="utf-8")
    invocation_dir = state_dir / "alignment_sessions" / "align_old" / "invocations" / "0001"
    invocation_dir.mkdir(parents=True)
    (invocation_dir / "stdout.log").write_text("secret execution log\n", encoding="utf-8")

    context = service.get_alignment_workdir_context(sample_workdir)

    assert context["requires_choice"] is True
    spec_option = next(option for option in context["options"] if option["source_type"] == "spec_file")
    assert spec_option["spec_path"] == str(spec_path)
    assert any(option["action"] == "regenerate" for option in context["options"])

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="继续把这个目录编排成 Loop。",
        source_option_id=spec_option["option_id"],
        start_immediately=False,
    )

    agreement = session["working_agreement"]
    assert agreement["mode"] == "selected_source"
    assert agreement["source"]["source_type"] == "spec_file"
    assert "英语学习网站" in agreement["source"]["spec_markdown"]
    prompt = service._build_alignment_prompt(session, mode="normal")
    assert "Selected Loopora Source Context" in prompt
    assert "英语学习网站" in prompt
    assert "secret execution log" not in prompt

    continue_option = {
        "option_id": alignment_module.ServiceAlignmentMixin._alignment_source_option_id("continue_session", session["id"])
    }
    with pytest.raises(alignment_module.LooporaConflictError):
        service.create_alignment_session(
            workdir=sample_workdir,
            message="不要新建，继续旧对话。",
            source_option_id=continue_option["option_id"],
            start_immediately=False,
        )


def test_alignment_workdir_context_seeds_selected_existing_bundle(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)
    context = service.get_alignment_workdir_context(sample_workdir)
    bundle_option = next(option for option in context["options"] if option.get("source_bundle_id") == source["id"])

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="在这个已有方案上继续改进证据路径。",
        source_option_id=bundle_option["option_id"],
        start_immediately=False,
    )

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "bundle"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert session["linked_bundle_id"] == source["id"]
    assert Path(session["bundle_path"]).exists()
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == ""
    prompt = service._build_alignment_prompt(session, mode="normal")
    assert "Selected Loopora Source Context" in prompt
    assert "Current Bundle" in prompt


def test_alignment_workdir_context_api_creates_selected_source_session(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    state_dir = sample_workdir / ".loopora"
    state_dir.mkdir()
    spec_path = state_dir / "spec.md"
    spec_path.write_text("# Task\n\n整理一个可验证的改进 Loop。\n", encoding="utf-8")
    client = TestClient(build_app(service=service))

    context_response = client.post("/api/alignments/workdir-context", json={"workdir": str(sample_workdir)})
    assert context_response.status_code == 200
    context_payload = context_response.json()
    spec_option = next(option for option in context_payload["options"] if option["source_type"] == "spec_file")

    create_response = client.post(
        "/api/alignments/sessions",
        json={
            "workdir": str(sample_workdir),
            "message": "基于已有 spec 继续对齐。",
            "source_option_id": spec_option["option_id"],
        },
    )
    assert create_response.status_code == 201
    session = create_response.json()["session"]
    assert session["working_agreement"]["mode"] == "selected_source"
    assert session["working_agreement"]["source"]["spec_path"] == str(spec_path)


def test_alignment_service_lazily_migrates_legacy_flat_artifacts(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    session_id = "align_legacy"
    legacy_root = sample_workdir / ".loopora" / "alignment_sessions" / session_id
    legacy_root.mkdir(parents=True)
    legacy_bundle = legacy_root / "bundle.yml"
    legacy_bundle.write_text("version: 1\nmetadata:\n  name: Legacy\n  revision: 1\n", encoding="utf-8")
    (legacy_root / "transcript.jsonl").write_text(
        json.dumps({"role": "user", "content": "Legacy prompt"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (legacy_root / "working_agreement.json").write_text('{"summary":"Legacy agreement"}\n', encoding="utf-8")
    (legacy_root / "validation.json").write_text('{"ok":true}\n', encoding="utf-8")
    (legacy_root / "alignment_prompt_0.md").write_text("legacy prompt\n", encoding="utf-8")
    (legacy_root / "alignment_schema.json").write_text("{}\n", encoding="utf-8")
    (legacy_root / "alignment_output_0.json").write_text(
        json.dumps({"assistant_message": "done", "bundle_yaml": "raw yaml"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (legacy_root / "alignment_output_1.json").write_bytes(b"\xff")
    service.repository.create_alignment_session(
        {
            "id": session_id,
            "status": "ready",
            "workdir": str(sample_workdir),
            "bundle_path": str(legacy_bundle),
            "transcript": [{"role": "user", "content": "Legacy prompt", "created_at": "now"}],
            "validation": {"ok": True},
            "alignment_stage": "ready",
            "working_agreement": {"summary": "Legacy agreement"},
            "executor_session_ref": {},
        }
    )

    migrated = service.get_alignment_session(session_id)
    root = Path(migrated["artifact_dir"])

    assert Path(migrated["bundle_path"]) == root / "artifacts" / "bundle.yml"
    assert (root / "artifacts" / "bundle.yml").exists()
    assert (root / "conversation" / "transcript.jsonl").exists()
    assert (root / "agreement" / "current.json").exists()
    assert (root / "artifacts" / "validation.json").exists()
    output = json.loads((root / "invocations" / "0001" / "output.json").read_text(encoding="utf-8"))
    assert "bundle_yaml" not in output
    assert output["bundle_sha256"]
    assert (root / "invocations" / "0002" / "output.json").read_bytes() == b"\xff"
    assert (root / "legacy" / "bundle.yml").exists()


def test_alignment_cancel_signal_failure_writes_structured_diagnostics(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Cancel a running alignment.",
        start_immediately=False,
    )
    service.repository.update_alignment_session(
        session["id"],
        status="running",
        active_child_pid=987654,
    )

    def fail_signal(_pid: int, _signal: int) -> None:
        raise OSError("signal denied")

    monkeypatch.setattr(alignment_module.os, "kill", fail_signal)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        cancelled = service.cancel_alignment_session(session["id"])

    assert cancelled["stop_requested"] is True
    events = service.list_alignment_events(session["id"])
    diagnostic_event = next(event for event in events if event["event_type"] == "alignment_cancel_signal_failed")
    assert diagnostic_event["payload"]["operation"] == "alignment_cancel_signal"
    assert diagnostic_event["payload"]["resource_type"] == "process"
    assert diagnostic_event["payload"]["resource_id"] == "987654"
    assert diagnostic_event["payload"]["owner_id"] == session["id"]
    assert diagnostic_event["payload"]["error_type"] == "OSError"
    assert any(
        getattr(record, "event", "") == "service.cleanup.failed" and (getattr(record, "context", {}) or {}).get("operation") == "alignment_cancel_signal"
        for record in caplog.records
    )


def test_alignment_cancel_signal_diagnostic_event_failure_is_logged_without_masking_cancel(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Cancel a running alignment with a broken event sink.",
        start_immediately=False,
    )
    service.repository.update_alignment_session(
        session["id"],
        status="running",
        active_child_pid=987654,
    )
    original_append_alignment_event = service.repository.append_alignment_event

    def fail_diagnostic_event(session_id: str, event_type: str, payload: dict) -> dict:
        if event_type == "alignment_cancel_signal_failed":
            raise OSError("alignment event sink locked")
        return original_append_alignment_event(session_id, event_type, payload)

    def fail_signal(_pid: int, _signal: int) -> None:
        raise OSError("signal denied")

    monkeypatch.setattr(service.repository, "append_alignment_event", fail_diagnostic_event)
    monkeypatch.setattr(alignment_module.os, "kill", fail_signal)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        cancelled = service.cancel_alignment_session(session["id"])

    assert cancelled["stop_requested"] is True
    assert any(
        getattr(record, "event", "") == "service.cleanup.failed"
        and (getattr(record, "context", {}) or {}).get("operation") == "alignment_cancel_signal_event_write"
        and (getattr(record, "context", {}) or {}).get("resource_type") == "alignment_event"
        for record in caplog.records
    )


def test_alignment_legacy_migration_failure_writes_structured_diagnostics(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session_id = "align_legacy_diag"
    legacy_root = sample_workdir / ".loopora" / "alignment_sessions" / session_id
    legacy_root.mkdir(parents=True)
    legacy_bundle = legacy_root / "bundle.yml"
    legacy_bundle.write_text("version: 1\nmetadata:\n  name: Legacy\n  revision: 1\n", encoding="utf-8")
    stale_file = legacy_root / "stale.tmp"
    stale_file.write_text("left behind\n", encoding="utf-8")
    service.repository.create_alignment_session(
        {
            "id": session_id,
            "status": "ready",
            "workdir": str(sample_workdir),
            "bundle_path": str(legacy_bundle),
            "transcript": [],
            "validation": {"ok": True},
            "alignment_stage": "ready",
            "working_agreement": {},
            "executor_session_ref": {},
        }
    )
    original_move = alignment_module.shutil.move

    def fail_stale_move(source: str, target: str):
        if Path(source).name == "stale.tmp":
            raise OSError("locked legacy file")
        return original_move(source, target)

    monkeypatch.setattr(alignment_module.shutil, "move", fail_stale_move)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        migrated = service.get_alignment_session(session_id)

    assert Path(migrated["bundle_path"]).name == "bundle.yml"
    diagnostic_event = next(event for event in service.list_alignment_events(session_id) if event["event_type"] == "alignment_legacy_artifact_migration_failed")
    assert diagnostic_event["payload"]["operation"] == "alignment_legacy_artifact_migration"
    assert diagnostic_event["payload"]["resource_type"] == "path"
    assert diagnostic_event["payload"]["resource_id"].endswith("stale.tmp")
    assert diagnostic_event["payload"]["owner_id"] == session_id
    assert any(
        getattr(record, "event", "") == "service.cleanup.failed"
        and (getattr(record, "context", {}) or {}).get("operation") == "alignment_legacy_artifact_migration"
        for record in caplog.records
    )


def test_alignment_delete_logs_session_dir_cleanup_failure(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Create a deletable alignment session.",
        start_immediately=False,
    )

    def fail_rmtree(path: Path) -> None:
        if Path(path) == Path(session["artifact_dir"]):
            raise OSError("alignment dir locked")
        raise AssertionError(f"unexpected cleanup target: {path}")

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        deleted = service.delete_alignment_session(session["id"])

    assert deleted is True
    artifact_events = [json.loads(line) for line in (Path(session["artifact_dir"]) / "events" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    diagnostic_event = next(event for event in artifact_events if event["event_type"] == "alignment_session_cleanup_failed")
    assert diagnostic_event["payload"]["operation"] == "alignment_session_delete"
    assert diagnostic_event["payload"]["resource_type"] == "path"
    assert diagnostic_event["payload"]["owner_id"] == session["id"]
    diagnostics = service.local_asset_diagnostics()
    assert any(item["session_id"] == session["id"] for item in diagnostics["orphan_alignment_dirs"])
    assert any(
        getattr(record, "event", "") == "service.cleanup.failed" and (getattr(record, "context", {}) or {}).get("operation") == "alignment_session_delete"
        for record in caplog.records
    )


def test_alignment_delete_logs_cleanup_diagnostic_callback_failure(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Delete with a broken diagnostic callback.",
        start_immediately=False,
    )

    def fail_rmtree(path: Path) -> None:
        if Path(path) == Path(session["artifact_dir"]):
            raise OSError("alignment dir locked")
        raise AssertionError(f"unexpected cleanup target: {path}")

    def fail_diagnostic_callback(_session: dict, _event_type: str, _payload: dict) -> None:
        raise RuntimeError("diagnostic callback down")

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(service, "_append_alignment_local_diagnostic_event", fail_diagnostic_callback)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        deleted = service.delete_alignment_session(session["id"])

    assert deleted is True
    operations = [
        (getattr(record, "context", {}) or {}).get("operation") for record in caplog.records if getattr(record, "event", "") == "service.cleanup.failed"
    ]
    assert "alignment_session_delete" in operations
    assert "alignment_session_delete_diagnostic_callback" in operations


def test_alignment_delete_logs_local_diagnostic_event_write_failure(
    service_factory,
    sample_workdir: Path,
    monkeypatch,
    caplog,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Delete with a broken local event sink.",
        start_immediately=False,
    )
    hydrated_session = service.get_alignment_session(session["id"])

    def fail_rmtree(path: Path) -> None:
        if Path(path) == Path(session["artifact_dir"]):
            raise OSError("alignment dir locked")
        raise AssertionError(f"unexpected cleanup target: {path}")

    def fail_ensure_alignment_artifact_dirs(_root: Path) -> None:
        raise OSError("alignment artifact events locked")

    monkeypatch.setattr(cleanup_diagnostics.shutil, "rmtree", fail_rmtree)
    monkeypatch.setattr(service, "get_alignment_session", lambda _session_id: hydrated_session)
    monkeypatch.setattr(service, "_ensure_alignment_artifact_dirs", fail_ensure_alignment_artifact_dirs)
    with caplog.at_level(logging.WARNING, logger="loopora.service_alignment"):
        deleted = service.delete_alignment_session(session["id"])

    assert deleted is True
    assert any(
        getattr(record, "event", "") == "service.cleanup.failed"
        and (getattr(record, "context", {}) or {}).get("operation") == "alignment_session_delete_event_write"
        and (getattr(record, "context", {}) or {}).get("resource_type") == "alignment_event"
        for record in caplog.records
    )


def test_alignment_api_rejects_busy_messages_and_allows_continue_after_cancel(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success", role_delay=0.4)
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/alignments/sessions",
        json={"workdir": str(sample_workdir), "message": "Start slowly."},
    )
    assert response.status_code == 201
    session_id = response.json()["session"]["id"]

    busy = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "Too soon."})
    assert busy.status_code == 409
    assert "already running" in busy.json()["error"]

    cancelled = client.post(f"/api/alignments/sessions/{session_id}/cancel")
    assert cancelled.status_code == 200
    _wait_for_status(service, session_id, "failed")

    continued = client.post(f"/api/alignments/sessions/{session_id}/messages", json={"message": "Continue after cancel."})
    assert continued.status_code == 200
    assert continued.json()["session"]["status"] == "running"
