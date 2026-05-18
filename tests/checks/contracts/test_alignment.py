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
from loopora.service_bundle_control_summary import build_bundle_control_summary
from loopora.web import build_app
from loopora.web_streaming import MAX_EVENT_CURSOR_ID
import loopora.service_alignment as alignment_module
import loopora.service_alignment_legacy as alignment_legacy_module
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
    assert agreement["working_agreement"]["readiness_evidence"]["local_governance"]
    service.append_alignment_message(session_id, "确认")
    confirmed = _wait_for_status(service, session_id, *(final_statuses or ("ready",)))
    assert confirmed["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is True
    return confirmed


def _bundle_invocation_dir(artifact_root: Path) -> Path:
    bundle_invocations: list[Path] = []
    for invocation_dir in sorted((artifact_root / "invocations").iterdir()):
        output_path = invocation_dir / "output.json"
        if not output_path.is_file():
            continue
        try:
            output = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if output.get("bundle_written") is True:
            bundle_invocations.append(invocation_dir)
    if not bundle_invocations:
        raise AssertionError("no bundle-writing alignment invocation was recorded")
    return bundle_invocations[-1]


def _assert_run_succeeds_and_joins(service, run_id: str, *, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    run = service.get_run(run_id)
    while time.time() < deadline:
        run = service.get_run(run_id)
        if run["status"] in {"succeeded", "failed", "stopped"}:
            break
        time.sleep(0.05)
    thread = service._threads.get(run_id)
    if thread is not None:
        thread.join(timeout=max(0.0, deadline - time.time()))
    run = service.get_run(run_id)
    assert run["status"] == "succeeded"


def test_alignment_prompt_assets_separate_run_status_from_task_verdict() -> None:
    root = Path(__file__).resolve().parents[3]
    asset_dir = root / "src" / "loopora" / "assets" / "alignment"
    playbook = (asset_dir / "alignment-playbook.md").read_text(encoding="utf-8")
    primer = (asset_dir / "product-primer.md").read_text(encoding="utf-8")

    main_workflow = "`compose Loop -> run Loop -> automatic iteration with evidence -> run status, task verdict, and result`"
    assert main_workflow in playbook
    assert main_workflow in primer
    assert "`Loop -> run -> automatic iteration -> evidence -> run status + task verdict + result`" in primer
    assert "The task verdict projection should be easy to map into stable buckets" in primer

    for path in sorted(asset_dir.glob("*.md")):
        source = path.read_text(encoding="utf-8")
        assert "evidence verdict and result" not in source, path.name
        assert "The evidence verdict should" not in source, path.name


def test_alignment_fake_bundle_keeps_runtime_judgment_surfaces_visible(sample_workdir: Path) -> None:
    bundle_text = alignment_bundle_yaml(str(sample_workdir.resolve()))

    assert "Execution Strategy, Judgment Tradeoffs, Local Governance, and Residual Risk" in bundle_text
    assert "sequencing drift, lowered tradeoffs, local-governance gaps" in bundle_text
    assert "prove the task contract, execution strategy, judgment tradeoffs, local governance when present" in bundle_text


def _assert_alignment_preview_control_summary(preview: dict) -> None:
    control_summary = preview["control_summary"]
    assert control_summary["gatekeeper"]["requires_evidence_refs"] is True
    assert control_summary["coverage"]["check_count"] >= 1
    assert control_summary["coverage"]["target_count"] >= control_summary["coverage"]["check_count"]
    assert any(target["id"].startswith("done_when.") for target in control_summary["coverage"]["targets"])
    assert (
        any("fail closed" in item for item in control_summary["residual_risk_policy"])
        and any("smaller proven flow" in item for item in control_summary["judgment_tradeoffs"])
        and any("Focused Builder (builder): Keep implementation narrow" in item for item in control_summary["role_postures"])
        and any("Future iterations stay anchored" in item for item in control_summary["loop_fit_reasons"])
    )
    assert preview["traceability"] == control_summary["traceability"]
    assert any(item["key"] == "loop_fit" and item["mapped"] for item in preview["traceability"]["items"])
    assert any(item["key"] == "coverage_targets" and item["mapped"] for item in preview["traceability"]["items"])
    assert any(item["key"] == "judgment_tradeoffs" and item["mapped"] for item in preview["traceability"]["items"])
    assert preview["traceability"]["mapped_count"] == preview["traceability"]["required_count"]


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
    bundle_invocation_dir = _bundle_invocation_dir(artifact_root)
    assert bundle_invocation_dir != invocation_dir
    invocation_output = json.loads((invocation_dir / "output.json").read_text(encoding="utf-8"))
    assert "bundle_yaml" not in invocation_output
    assert invocation_output["bundle_written"] is False
    invocation_output = json.loads((bundle_invocation_dir / "output.json").read_text(encoding="utf-8"))
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
    _assert_alignment_preview_control_summary(preview)
    assert "Ship the focused starter experience" in preview["spec_rendered_html"]

    imported = service.import_alignment_bundle(session["id"], start_immediately=True)
    assert imported["bundle"]["loop_id"]
    assert imported["run"]["id"]
    final_session = service.get_alignment_session(session["id"])
    assert final_session["status"] == "running_loop"
    assert final_session["linked_bundle_id"] == imported["bundle"]["id"]
    assert final_session["linked_loop_id"] == imported["bundle"]["loop_id"]
    assert final_session["linked_run_id"] == imported["run"]["id"]
    _assert_run_succeeds_and_joins(service, imported["run"]["id"])


def test_alignment_manifest_and_session_summary_redact_transcript_preview_secrets(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Start from --token MANIFEST_TOKEN_SECRET_MARKER and Cookie: sid=MANIFEST_COOKIE_SECRET_MARKER.",
        start_immediately=False,
    )
    artifact_root = Path(session["artifact_dir"])
    manifest = json.loads((artifact_root / "manifest.json").read_text(encoding="utf-8"))
    listed = service.list_alignment_sessions()[0]
    transcript_text = (artifact_root / "conversation" / "transcript.jsonl").read_text(encoding="utf-8")

    for payload in (json.dumps(manifest, ensure_ascii=False), json.dumps(listed, ensure_ascii=False)):
        assert "MANIFEST_TOKEN_SECRET_MARKER" not in payload
        assert "MANIFEST_COOKIE_SECRET_MARKER" not in payload
        assert "<secret omitted>" in payload

    assert "MANIFEST_TOKEN_SECRET_MARKER" in transcript_text
    assert "MANIFEST_COOKIE_SECRET_MARKER" in transcript_text


def test_alignment_manifest_redacts_error_message_preview_secrets(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a Loop later.",
        start_immediately=False,
    )

    service.repository.update_alignment_session(
        session["id"],
        status="failed",
        error_message="provider failed with Authorization: Bearer MANIFEST_ERROR_SECRET_MARKER",
    )
    service._write_alignment_manifest(service.get_alignment_session(session["id"]))

    manifest = json.loads((Path(session["artifact_dir"]) / "manifest.json").read_text(encoding="utf-8"))
    assert "MANIFEST_ERROR_SECRET_MARKER" not in json.dumps(manifest, ensure_ascii=False)
    assert manifest["error_message"] == "provider failed with Authorization: <secret omitted>"


def test_alignment_invocation_output_debug_artifact_redacts_sensitive_values(tmp_path: Path) -> None:
    invocation_dir = tmp_path / "invocations" / "0001"
    invocation_dir.mkdir(parents=True)
    bundle_path = tmp_path / "artifacts" / "bundle.yml"
    bundle_yaml = "version: 1\nmetadata:\n  name: OUTPUT_BUNDLE_SECRET_MARKER\n"

    alignment_module.ServiceAlignmentMixin._finalize_alignment_invocation_files(
        invocation_dir,
        {
            "assistant_message": "Use --x-loopora-token OUTPUT_ARG_SECRET_MARKER",
            "diagnostics": {
                "error": "Authorization: Bearer OUTPUT_AUTH_SECRET_MARKER",
                "headers": {"Cookie": "sid=OUTPUT_COOKIE_SECRET_MARKER"},
                "auth_token": "OUTPUT_FIELD_SECRET_MARKER",
            },
            "prompt": "OUTPUT_PROMPT_SECRET_MARKER",
            "bundle_yaml": bundle_yaml,
        },
        bundle_path,
    )

    output = json.loads((invocation_dir / "output.json").read_text(encoding="utf-8"))
    output_text = json.dumps(output, ensure_ascii=False)

    assert "bundle_yaml" not in output
    assert output["bundle_written"] is True
    assert output["bundle_path"] == str(bundle_path)
    assert output["bundle_bytes"] == len(bundle_yaml.encode("utf-8"))
    assert output["bundle_sha256"]
    assert output["diagnostics"]["headers"]["Cookie"] == "<secret omitted>"
    assert output["diagnostics"]["auth_token"] == "<secret omitted>"
    assert output["prompt"] == "<prompt omitted>"
    for secret in (
        "OUTPUT_ARG_SECRET_MARKER",
        "OUTPUT_AUTH_SECRET_MARKER",
        "OUTPUT_COOKIE_SECRET_MARKER",
        "OUTPUT_FIELD_SECRET_MARKER",
        "OUTPUT_PROMPT_SECRET_MARKER",
        "OUTPUT_BUNDLE_SECRET_MARKER",
    ):
        assert secret not in output_text


def test_alignment_workdir_context_redacts_user_controlled_option_labels(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))
    bundle["metadata"]["name"] = "Imported --token CONTEXT_LABEL_TOKEN_SECRET_MARKER"
    bundle["metadata"]["description"] = "Authorization: Bearer CONTEXT_LABEL_AUTH_SECRET_MARKER"
    bundle["loop"]["name"] = "Cookie: sid=CONTEXT_LABEL_COOKIE_SECRET_MARKER"

    service.import_bundle_text(bundle_to_yaml(bundle))

    context = service.get_alignment_workdir_context(sample_workdir)
    context_text = json.dumps(context, ensure_ascii=False)

    assert "CONTEXT_LABEL_TOKEN_SECRET_MARKER" not in context_text
    assert "CONTEXT_LABEL_AUTH_SECRET_MARKER" not in context_text
    assert "CONTEXT_LABEL_COOKIE_SECRET_MARKER" not in context_text
    assert "<secret omitted>" in context_text


def test_alignment_import_string_false_does_not_start_run(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    session = _confirm_alignment_agreement(service, created["id"])

    imported = service.import_alignment_bundle(session["id"], start_immediately="false")

    assert imported["run"] is None
    assert imported["session"]["status"] == "imported"
    assert imported["session"]["linked_run_id"] == ""
    events = service.list_alignment_events(session["id"])
    assert any(event["event_type"] == "alignment_imported" for event in events)
    assert not any(event["event_type"] == "alignment_run_started" for event in events)


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


def test_alignment_event_cursor_requires_integer_sequence(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )
    service.repository.append_alignment_event(session["id"], "alignment_status_checked", {"status": "idle"})

    events = service.list_alignment_events(session["id"])
    assert len(events) >= 2
    first_id = events[0]["id"]

    assert [event["id"] for event in service.list_alignment_events(session["id"], after_id=True, limit=2)] == [
        event["id"] for event in events[:2]
    ]
    assert [event["id"] for event in service.list_alignment_events(session["id"], after_id=str(first_id), limit=2)] == [
        event["id"] for event in events[:2]
    ]
    assert service.list_alignment_events(session["id"], limit=True) == []


def test_alignment_repair_attempts_require_integer_sequence(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a focused starter experience.",
    )

    updated = service.repository.update_alignment_session(session["id"], repair_attempts="2")

    assert updated["repair_attempts"] == 0
    assert alignment_module.ServiceAlignmentMixin._alignment_repair_attempts({"repair_attempts": None}) == 0
    assert alignment_module.ServiceAlignmentMixin._alignment_repair_attempts({"repair_attempts": "1"}, invalid_default=1) == 1
    assert alignment_module.ServiceAlignmentMixin._alignment_invocation_dir(sample_workdir, "2", repair=False).name == "0001"


def test_alignment_session_start_immediately_string_false_does_not_start(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_question")

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="I need help shaping this task.",
        start_immediately="false",
    )

    assert session["status"] == "idle"
    assert session["transcript"][-1]["role"] == "user"
    assert not Path(session["bundle_path"]).exists()
    events = service.list_alignment_events(session["id"])
    assert not any(event["event_type"] == "alignment_waiting_user" for event in events)


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


def test_alignment_visible_decision_options_require_choice_set_and_recommendation() -> None:
    session = {"transcript": [{"role": "user", "content": "Build a governed starter experience."}]}
    non_boolean_needs_user_input = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": "false",
            "alignment_phase": "clarifying",
            "decision_options": [
                {
                    "id": "evidence_path",
                    "label": "Evidence path",
                    "description": "Prefer proof.",
                    "recommended": True,
                    "user_reply": "Use the evidence path.",
                },
                {
                    "id": "speed_path",
                    "label": "Speed path",
                    "description": "Prefer speed.",
                    "recommended": False,
                    "user_reply": "Use the speed path.",
                },
            ],
        },
        has_bundle=False,
    )
    single_option = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": True,
            "alignment_phase": "clarifying",
            "decision_options": [
                {
                    "id": "only_choice",
                    "label": "Only one path",
                    "description": "This should not be displayed as a real choice.",
                    "recommended": True,
                    "user_reply": "Use the only path.",
                }
            ],
        },
        has_bundle=False,
    )
    no_recommendation = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": True,
            "alignment_phase": "clarifying",
            "decision_options": [
                {"id": "slow", "label": "Go slow", "description": "More evidence.", "user_reply": "Go slow."},
                {"id": "fast", "label": "Go fast", "description": "More speed.", "user_reply": "Go fast."},
            ],
        },
        has_bundle=False,
    )
    missing_description = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": True,
            "alignment_phase": "clarifying",
            "decision_options": [
                {
                    "id": "evidence_path",
                    "label": "Evidence path",
                    "recommended": True,
                    "user_reply": "Use the evidence path.",
                },
                {
                    "id": "speed_path",
                    "label": "Speed path",
                    "description": "Prefer speed.",
                    "recommended": False,
                    "user_reply": "Use the speed path.",
                },
            ],
        },
        has_bundle=False,
    )
    string_recommendation = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": True,
            "alignment_phase": "clarifying",
            "decision_options": [
                {
                    "id": "evidence_path",
                    "label": "Evidence path",
                    "description": "Prefer proof.",
                    "recommended": "true",
                    "user_reply": "Use the evidence path.",
                },
                {
                    "id": "speed_path",
                    "label": "Speed path",
                    "description": "Prefer speed.",
                    "recommended": "false",
                    "user_reply": "Use the speed path.",
                },
            ],
        },
        has_bundle=False,
    )
    valid_options = alignment_module.ServiceAlignmentMixin._visible_alignment_decision_options(
        session,
        {
            "needs_user_input": True,
            "alignment_phase": "clarifying",
            "decision_options": [
                {
                    "id": "evidence_path",
                    "label": "Evidence path",
                    "description": "Prefer proof.",
                    "recommended": True,
                    "user_reply": "Use the evidence path.",
                },
                {
                    "id": "speed_path",
                    "label": "Speed path",
                    "description": "Prefer speed.",
                    "recommended": False,
                    "user_reply": "Use the speed path.",
                },
            ],
        },
        has_bundle=False,
    )

    assert non_boolean_needs_user_input == []
    assert [option["id"] for option in single_option] == ["evidence_first", "speed_first", "add_judgment"]
    assert [option["id"] for option in no_recommendation] == ["evidence_first", "speed_first", "add_judgment"]
    assert [option["id"] for option in missing_description] == ["evidence_first", "speed_first", "add_judgment"]
    assert [option["id"] for option in string_recommendation] == ["evidence_first", "speed_first", "add_judgment"]
    assert [option["id"] for option in valid_options] == ["evidence_path", "speed_path"]


def test_alignment_missing_items_are_stable_ids_only() -> None:
    missing = alignment_module.ServiceAlignmentMixin._normalize_alignment_missing_items(
        [
            "success_surface",
            "success_surface",
            "role_posture",
            "raw model prose should not become a chip",
            {"bad": "shape"},
        ]
    )

    assert missing == ["success_surface", "role_posture"]


def test_alignment_clarifying_question_rewrite_requires_boolean_need() -> None:
    non_boolean_issues = alignment_module.ServiceAlignmentMixin._alignment_clarifying_question_issues(
        {
            "needs_user_input": "true",
            "assistant_message": "What roles do you want?",
            "decision_options": [],
        }
    )
    boolean_issues = alignment_module.ServiceAlignmentMixin._alignment_clarifying_question_issues(
        {
            "needs_user_input": True,
            "assistant_message": "What roles do you want?",
            "decision_options": [],
        }
    )

    assert non_boolean_issues == []
    assert "generic_alignment_question" in boolean_issues


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
    assert "Fake-done risks:" in visible_agreement
    assert "Evidence preferences:" in visible_agreement
    assert "Execution strategy:" in visible_agreement
    assert "Residual risk:" in visible_agreement
    assert "Judgment tradeoffs:" in visible_agreement
    assert "Local governance:" in visible_agreement
    assert "Role posture:" in visible_agreement
    assert "Run-flow shape:" in visible_agreement
    assert "Workflow shape:" not in visible_agreement
    assert "Project facts:" in visible_agreement
    assert "Workdir facts:" not in visible_agreement
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
    assert "成功面：" in visible_agreement
    assert "假完成风险：" in visible_agreement
    assert "证据偏好：" in visible_agreement
    assert "执行策略：" in visible_agreement
    assert "残余风险：" in visible_agreement
    assert "判断取舍：" in visible_agreement
    assert "本地治理：" in visible_agreement
    assert "运行流程形状：" in visible_agreement
    assert "workflow 形状：" not in visible_agreement
    assert "项目事实：" in visible_agreement
    assert "workdir 事实：" not in visible_agreement
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


@pytest.mark.parametrize(
    ("scenario", "missing_key", "message"),
    [
        ("alignment_incomplete_agreement_checklist", "workflow_shape", "Build a starter experience without workflow judgment."),
        ("alignment_incomplete_tradeoff_checklist", "judgment_tradeoffs", "Build a starter experience without tradeoff judgment."),
    ],
)
def test_alignment_service_blocks_agreement_with_incomplete_checklist(
    service_factory,
    sample_workdir: Path,
    scenario: str,
    missing_key: str,
    message: str,
) -> None:
    service = service_factory(scenario=scenario)

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message=message,
    )
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert session["alignment_stage"] == "clarifying"
    assert not session["working_agreement"]
    assert missing_key in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_checklist_incomplete" and missing_key in event["payload"].get("missing", []) for event in events)


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
    prompt_text = (_bundle_invocation_dir(artifact_root) / "prompt.md").read_text(encoding="utf-8")

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
        "execution strategy, residual-risk policy, judgment tradeoff, local-governance responsibility",
        "execution priorities, residual-risk policy, local-governance responsibility",
        "Loopora Product Primer",
        "local-first platform for composing human-shaped governance loops",
        "human-in-the-loop -> human-shaped loop",
        "Loopora fit gate",
        "one Agent pass plus one human review",
        "direct answer or one-off task handling",
        "survive this chat as a run-owned, exportable, auditable contract",
        "new proof / artifact / handoff / observation / verdict context later rounds will create",
        "run-owned/exportable/auditable contract",
        "`readiness_checklist`: booleans for `loop_fit`, `task_scope`, `success_surface`, `fake_done_risks`, `evidence_preferences`, `execution_strategy`, `residual_risk_policy`, `judgment_tradeoffs`, `local_governance`",
        "`residual_risk_policy` must explain which remaining risks may be accepted and who or what follow-up / acceptance path owns them",
        "`judgment_tradeoffs` must capture a concrete preference order or contrast",
        "`local_governance` must explain whether project-local governance markers affect this Loop",
        "judgment structure quality × evidence feedback quality × error exposure speed",
        "prompt pack, role zoo, loop script, benchmark grinder",
        "global persona, or permanent preferences",
        "Project the confirmed working agreement into the bundle surfaces",
        "execution priorities",
        "project-local governance responsibilities",
        "local-governance checkpoints",
        "build/prove/repair/narrow/expand/defer priorities",
        "execution strategy",
        "judgment tradeoffs",
        "local-governance responsibility when project markers matter",
        "what should be built, proved, narrowed, repaired, expanded, or deliberately deferred first",
        "which imperfect result should be rejected, when proof beats speed, or when blocking beats pragmatic progress",
        "including any project-local governance reading or verification duties",
        "`spec.markdown` `# Role Notes` or `role_definitions` must carry",
        "`spec.markdown` / `# Role Notes`",
        "execution priorities or deliberate deferrals",
        "task-level judgment tradeoffs",
        "project-local governance obligations when they affect the task contract",
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
        "step `inputs` carry judgment order",
        "step `inputs`, or GateKeeper evidence rules",
        "optional Guide / Custom responsibility when used",
        "AGENTS.md exists: yes",
        "design/README.md exists: yes",
        "project-local governance markers",
        "Builder should read applicable project-local rules",
        "Custom must describe low-permission specialized review or advisory responsibility",
        "Keep readiness evidence task-scoped",
        "multiple reviewers or repair passes",
        "An Inspector or Custom review step after Builder",
        "Review steps, Guide after review, Builder after review, and Builder after Guide should declare `inputs.iteration_memory`",
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
        "advanced workflow fields",
        "If Inspector, Custom, or Guide review happened before final judgment",
        "query relevant upstream evidence",
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

    Path(preview_session["bundle_path"]).write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    recovered = service.sync_alignment_bundle_from_file(preview_session["id"])
    recovered_session = service.get_alignment_session(preview_session["id"])
    assert recovered["ok"] is True
    assert recovered_session["status"] == "ready"
    assert recovered_session["error_message"] == ""
    assert recovered_session["finished_at"] is None


def test_alignment_bundle_preview_revalidates_current_file_without_mutating_session(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create a previewable Loop.")["id"],
    )
    bundle_path = Path(session["bundle_path"])
    ready_bundle = load_bundle_text(bundle_path.read_text(encoding="utf-8"))
    ready_bundle["spec"]["markdown"] = ready_bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Some risk is fine.",
    )
    bundle_path.write_text(bundle_to_yaml(ready_bundle), encoding="utf-8")

    preview = service.get_alignment_bundle(session["id"])

    assert preview["ok"] is False
    assert preview["validation"]["ok"] is False
    assert "Residual Risk guidance" in preview["validation"]["error"]
    assert service.get_alignment_session(session["id"])["status"] == "ready"


def test_alignment_bundle_source_file_recovers_after_invalid_utf8(service_factory, sample_workdir: Path) -> None:
    service = service_factory(scenario="success")
    preview_session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create a previewable Loop.")["id"],
    )
    Path(preview_session["bundle_path"]).write_bytes(b"\xff")
    sync_result = service.sync_alignment_bundle_from_file(preview_session["id"])
    assert sync_result["ok"] is False

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

    continued = _wait_for_status(service, session["id"], "ready")
    assert continued["error_message"] == ""
    assert continued["validation"]["ok"] is True
    assert continued["transcript"][-1]["role"] == "assistant"
    prompt_text = (_bundle_invocation_dir(Path(continued["artifact_dir"])) / "prompt.md").read_text(encoding="utf-8")
    assert "Current bundle file could not be read" in prompt_text


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


def test_alignment_service_blocks_bundle_without_execution_strategy_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_missing_execution_strategy_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without deciding what the next rounds should prioritize.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "execution_strategy" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "execution_strategy" in event["payload"].get("error", "") for event in events)


def test_alignment_service_blocks_bundle_without_local_governance_readiness_evidence(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="alignment_missing_local_governance_readiness_evidence")

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message="Build a starter experience without clarifying local governance responsibilities.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert "local_governance" in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(event["event_type"] == "alignment_stage_blocked" and "local_governance" in event["payload"].get("error", "") for event in events)


@pytest.mark.parametrize(
    ("scenario", "missing_key"),
    [
        ("alignment_vague_success_surface_readiness_evidence", "success_surface"),
        ("alignment_vague_fake_done_readiness_evidence", "fake_done_risks"),
        ("alignment_vague_evidence_preferences_readiness_evidence", "evidence_preferences"),
        ("alignment_vague_role_posture_readiness_evidence", "role_posture"),
        ("alignment_role_posture_without_gatekeeper_readiness_evidence", "role_posture"),
    ],
)
def test_alignment_service_blocks_placeholder_judgment_readiness_evidence(
    service_factory,
    sample_workdir: Path,
    scenario: str,
    missing_key: str,
) -> None:
    service = service_factory(scenario=scenario)

    created = service.create_alignment_session(
        workdir=sample_workdir,
        message=f"Build a starter experience with placeholder {missing_key} evidence.",
    )
    _wait_for_status(service, created["id"], "waiting_user")
    service.append_alignment_message(created["id"], "确认")
    session = _wait_for_status(service, created["id"], "waiting_user")

    assert not Path(session["bundle_path"]).exists()
    assert missing_key in session["transcript"][-1]["content"]
    events = service.list_alignment_events(created["id"])
    assert any(
        event["event_type"] == "alignment_stage_blocked" and missing_key in event["payload"].get("error", "")
        for event in events
    )


def test_alignment_readiness_evidence_rejects_placeholder_judgment_surfaces() -> None:
    service = alignment_module.ServiceAlignmentMixin
    readiness_evidence = {
        "loop_fit": "Loopora is needed because roles must gather proof, compare findings, and keep judgment alive across iterations.",
        "task_scope": "The task scope is the requested starter workflow and its evidence-bearing bundle surfaces.",
        "success_surface": "The success surface is the user-visible primary path plus the runnable checks that prove it works.",
        "fake_done_risks": "Blocking fake-done findings include screenshots without checks and claims without direct artifacts.",
        "evidence_preferences": "Evidence must project Proven, Weak, Unproven, Blocking, and Residual risk before closure.",
        "execution_strategy": "Build the focused flow first, then repair evidence gaps before expanding or polishing.",
        "residual_risk_policy": "Minor polish risk may remain visible as a tracked follow-up owned by product; ownerless primary-flow risk fails closed.",
        "judgment_tradeoffs": "Prefer proof over speed when the primary flow or evidence boundary is uncertain.",
        "local_governance": "No extra repository-rule content is claimed; roles follow the task contract and evidence rules.",
        "role_posture": "Builder implements, Inspector verifies direct evidence, and GateKeeper decides from the evidence buckets.",
        "workflow_shape": "Builder, Inspector, and GateKeeper exchange explicit handoffs before any finish decision.",
        "workdir_facts": "Snapshot assumptions remain unknown until observed in the workdir.",
    }
    valid_issues = service._readiness_evidence_issues({"readiness_evidence": readiness_evidence})
    assert not {
        "success_surface",
        "fake_done_risks",
        "evidence_preferences",
        "role_posture",
    }.intersection(valid_issues)

    placeholders = {
        "success_surface": "The final result should be good and useful for the user.",
        "fake_done_risks": "The result should avoid bugs and should be high quality.",
        "evidence_preferences": "The user needs enough proof to feel confident before the result is accepted.",
        "role_posture": "Use three roles to complete the task well.",
    }
    for key, value in placeholders.items():
        candidate = dict(readiness_evidence)
        candidate[key] = value
        issues = service._readiness_evidence_issues({"readiness_evidence": candidate})
        assert key in issues

    no_gatekeeper = dict(readiness_evidence)
    no_gatekeeper["role_posture"] = "Builder leaves evidence and Inspector reviews the handoff carefully."
    assert "role_posture" in service._readiness_evidence_issues({"readiness_evidence": no_gatekeeper})
    chinese_no_gatekeeper = dict(readiness_evidence)
    chinese_no_gatekeeper["role_posture"] = "Builder 负责构建，Inspector 验证证据。"
    assert "role_posture" in service._readiness_evidence_issues({"readiness_evidence": chinese_no_gatekeeper})


def test_alignment_readiness_evidence_rejects_unmanaged_residual_risk_policy() -> None:
    readiness_evidence = {
        "loop_fit": "Loopora is needed because roles must gather proof, compare findings, and keep judgment alive across iterations.",
        "task_scope": "The task scope is the requested starter workflow and its evidence-bearing bundle surfaces.",
        "success_surface": "The success surface is the user-visible primary path plus the runnable checks that prove it works.",
        "fake_done_risks": "Blocking fake-done findings include screenshots without checks and claims without direct artifacts.",
        "evidence_preferences": (
            "Evidence must project Proven direct checks, Weak indirect signals, Unproven claims, "
            "Blocking findings, and Residual risk."
        ),
        "execution_strategy": "Build the focused flow first, then repair evidence gaps before expanding or polishing.",
        "residual_risk_policy": "Minor polish risk may remain visible as a tracked follow-up owned by product; ownerless primary-flow risk fails closed.",
        "judgment_tradeoffs": "Prefer proof over speed when the primary flow or evidence boundary is uncertain.",
        "local_governance": "No extra repository-rule content is claimed; roles follow the task contract and evidence rules.",
        "role_posture": "Builder implements, Inspector verifies direct evidence, and GateKeeper decides from the evidence buckets.",
        "workflow_shape": "Builder, Inspector, and GateKeeper exchange explicit handoffs before any finish decision.",
        "workdir_facts": "Snapshot assumptions remain unknown until observed in the workdir.",
    }
    valid_issues = alignment_module.ServiceAlignmentMixin._readiness_evidence_issues({"readiness_evidence": readiness_evidence})
    assert "residual_risk_policy" not in valid_issues

    readiness_evidence["residual_risk_policy"] = "Some risk is fine."
    issues = alignment_module.ServiceAlignmentMixin._readiness_evidence_issues({"readiness_evidence": readiness_evidence})

    assert "residual_risk_policy" in issues

    readiness_evidence["residual_risk_policy"] = "有些风险可以接受。"
    issues = alignment_module.ServiceAlignmentMixin._readiness_evidence_issues({"readiness_evidence": readiness_evidence})

    assert "residual_risk_policy" in issues

    readiness_evidence["residual_risk_policy"] = "有些风险可以接受，但必须由客服负责人跟进工单。"
    issues = alignment_module.ServiceAlignmentMixin._readiness_evidence_issues({"readiness_evidence": readiness_evidence})

    assert "residual_risk_policy" not in issues


def test_alignment_readiness_evidence_rejects_local_governance_marker_lists_without_responsibility() -> None:
    service = alignment_module.ServiceAlignmentMixin
    readiness_evidence = {
        "loop_fit": "Loopora is needed because roles must gather proof, compare findings, and keep judgment alive across iterations.",
        "task_scope": "The task scope is the requested starter workflow and its evidence-bearing bundle surfaces.",
        "success_surface": "The success surface is the user-visible primary path plus the runnable checks that prove it works.",
        "fake_done_risks": "Blocking fake-done findings include screenshots without checks and claims without direct artifacts.",
        "evidence_preferences": "Evidence must project Proven, Weak, Unproven, Blocking, and Residual risk before closure.",
        "execution_strategy": "Build the focused flow first, then repair evidence gaps before expanding or polishing.",
        "residual_risk_policy": "Minor polish risk may remain visible as a tracked follow-up owned by product; ownerless primary-flow risk fails closed.",
        "judgment_tradeoffs": "Prefer proof over speed when the primary flow or evidence boundary is uncertain.",
        "local_governance": "AGENTS.md, design/README.md, design/, and tests/ are visible governance markers.",
        "role_posture": "Builder implements, Inspector verifies direct evidence, and GateKeeper decides from the evidence buckets.",
        "workflow_shape": "Builder, Inspector, and GateKeeper exchange explicit handoffs before any finish decision.",
        "workdir_facts": "Snapshot assumptions remain unknown until observed in the workdir.",
    }

    issues = service._readiness_evidence_issues({"readiness_evidence": readiness_evidence})
    assert "local_governance" in issues

    readiness_evidence["local_governance"] = (
        "Builder reads AGENTS.md and design/README.md before editing; Inspector verifies design/ and tests/ "
        "obligations against the result; GateKeeper treats skipped AGENTS.md or tests/ validation as Weak, "
        "Unproven, or Blocking."
    )
    issues = service._readiness_evidence_issues({"readiness_evidence": readiness_evidence})
    assert "local_governance" not in issues


def test_alignment_readiness_evidence_uses_workdir_snapshot_for_local_governance() -> None:
    service = alignment_module.ServiceAlignmentMixin
    readiness_evidence = {
        "loop_fit": "Loopora is needed because roles must gather proof, compare findings, and keep judgment alive across iterations.",
        "task_scope": "The task scope is the requested starter workflow and its evidence-bearing bundle surfaces.",
        "success_surface": "The success surface is the user-visible primary path plus the runnable checks that prove it works.",
        "fake_done_risks": "Blocking fake-done findings include screenshots without checks and claims without direct artifacts.",
        "evidence_preferences": "Evidence must project Proven, Weak, Unproven, Blocking, and Residual risk before closure.",
        "execution_strategy": "Build the focused flow first, then repair evidence gaps before expanding or polishing.",
        "residual_risk_policy": "Minor polish risk may remain visible as a tracked follow-up owned by product; ownerless primary-flow risk fails closed.",
        "judgment_tradeoffs": "Prefer proof over speed when the primary flow or evidence boundary is uncertain.",
        "local_governance": "No extra repository-rule content is claimed.",
        "role_posture": "Builder implements, Inspector verifies direct evidence, and GateKeeper decides from the evidence buckets.",
        "workflow_shape": "Builder, Inspector, and GateKeeper exchange explicit handoffs before any finish decision.",
        "workdir_facts": "Snapshot observed project markers.",
    }
    snapshot = "\n".join(
        [
            "AGENTS.md exists: yes",
            "design/ exists: yes",
            "design/README.md exists: yes",
            "tests/ exists: yes",
        ]
    )

    issues = service._readiness_evidence_issues({"readiness_evidence": readiness_evidence}, workdir_snapshot=snapshot)
    assert "local_governance" in issues

    readiness_evidence["local_governance"] = (
        "Builder reads AGENTS.md and design/README.md before editing; Inspector verifies design/ and tests/ "
        "obligations against the result; GateKeeper treats skipped AGENTS.md or tests/ validation as Weak, "
        "Unproven, or Blocking."
    )
    issues = service._readiness_evidence_issues({"readiness_evidence": readiness_evidence}, workdir_snapshot=snapshot)
    assert "local_governance" not in issues


def test_alignment_traceability_uses_workdir_snapshot_for_local_governance(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    (sample_workdir / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    (sample_workdir / "design").mkdir()
    (sample_workdir / "design" / "README.md").write_text("# Design\n", encoding="utf-8")
    (sample_workdir / "tests").mkdir()
    session = {
        "workdir": str(sample_workdir),
        "working_agreement": {
            "readiness_evidence": {
                "local_governance": (
                    "If project-local governance markers are present, Builder reads applicable rules, "
                    "Inspector verifies related obligations, and GateKeeper blocks skipped governance."
                ),
            }
        },
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("project-local governance markers" in issue for issue in issues)


def test_alignment_workdir_snapshot_detects_applicable_parent_agents_file(tmp_path: Path) -> None:
    service = alignment_module.ServiceAlignmentMixin
    project = tmp_path / "project"
    workdir = project / "packages" / "app"
    workdir.mkdir(parents=True)
    (project / ".git").mkdir()
    (project / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")

    snapshot = service._alignment_workdir_snapshot(workdir)

    assert "AGENTS.md exists: no" in snapshot
    assert "Applicable AGENTS.md exists: yes" in snapshot
    assert "Applicable AGENTS.md paths: ../../AGENTS.md" in snapshot
    assert service._workdir_snapshot_has_governance_markers(snapshot)


def test_alignment_traceability_uses_parent_agents_snapshot_for_local_governance(
    service_factory,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    project = tmp_path / "project"
    workdir = project / "packages" / "app"
    workdir.mkdir(parents=True)
    (project / ".git").mkdir()
    (project / "AGENTS.md").write_text("Project rules.\n", encoding="utf-8")
    bundle = load_bundle_text(alignment_bundle_yaml(str(workdir)))
    session = {
        "workdir": str(workdir),
        "working_agreement": {
            "readiness_evidence": {
                "local_governance": "No direct AGENTS.md file is visible in the selected workdir.",
            }
        },
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("project-local governance markers" in issue for issue in issues)


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


def test_alignment_service_blocks_governance_markers_without_bundle_responsibilities(
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


def test_alignment_traceability_checks_loop_fit_task_terms(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "loop_fit": (
                    "Browsertrace needs Loopora because later rounds must create new browsertrace proof "
                    "before GateKeeper can close."
                ),
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("loop_fit missing browsertrace" in issue for issue in issues)


def test_alignment_traceability_checks_agreement_success_categories(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Ship the focused starter experience in the target workdir with small, maintainable changes that preserve the primary user flow.",
        "Ship the refund approval path so Support admin can approve a refund and audit log records the actor.",
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "success_surface": (
                    "Success means Support admin can approve a refund, audit log records the actor, "
                    "and customer receives an email notification."
                ),
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("success surface" in issue and "notification/message" in issue for issue in issues)


def test_alignment_traceability_checks_agreement_evidence_preference_categories(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["spec"]["markdown"] = bundle["spec"]["markdown"].replace(
        "Prefer project-owned checks, direct run output, and concrete artifacts before screenshots or claims.",
        "Prefer browser journey proof before screenshots or claims.",
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "evidence_preferences": (
                    "Evidence must include a browser journey and audit log command output before GateKeeper can pass."
                ),
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("evidence preferences" in issue and "audit/log" in issue for issue in issues)


def test_alignment_traceability_checks_agreement_accessibility_and_locale_categories(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "success_surface": (
                    "Success means keyboard users can complete checkout, screen reader labels are available, "
                    "and Chinese and English variants preserve the same action."
                ),
                "evidence_preferences": (
                    "Evidence must include keyboard navigation proof and Chinese and English locale verification."
                ),
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("success surface" in issue and "accessibility/a11y" in issue for issue in issues)
    assert any("success surface" in issue and "locale/i18n" in issue for issue in issues)
    assert any("evidence preferences" in issue and "accessibility/a11y" in issue for issue in issues)
    assert any("evidence preferences" in issue and "locale/i18n" in issue for issue in issues)


def test_alignment_traceability_rejects_disconnected_governance_marker_responsibilities(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["spec"]["markdown"] += (
        "\nWorkdir Snapshot detected AGENTS.md, design/README.md, design/, and tests/.\n"
        + ("Neutral context keeps the marker list separate from generic role responsibilities. " * 10)
    )
    bundle["collaboration_summary"] += (
        "\nBuilder reads task notes. Inspector checks the result. GateKeeper blocks weak proof."
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "workdir_facts": "AGENTS.md, design/README.md, design/, and tests/ must shape runtime governance.",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert any("project-local governance markers" in issue for issue in issues)


def test_alignment_traceability_accepts_marker_specific_role_responsibilities(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    role_by_key = {role["key"]: role for role in bundle["role_definitions"]}
    role_by_key["builder"]["prompt_markdown"] += (
        "\n\nBuilder reads AGENTS.md, design/README.md, design/, and tests/ before editing."
    )
    role_by_key["contract-inspector"]["prompt_markdown"] += (
        "\n\nInspector verifies AGENTS.md, design/README.md, design/, and tests/ obligations against the result."
    )
    role_by_key["gatekeeper"]["prompt_markdown"] += (
        "\n\nGateKeeper treats skipped AGENTS.md, design/README.md, design/, or tests/ evidence as Weak, Unproven, or Blocking."
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "workdir_facts": "AGENTS.md, design/README.md, design/, and tests/ must shape runtime governance.",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert not any("project-local governance markers" in issue for issue in issues)


def test_alignment_traceability_accepts_role_notes_governance_responsibilities(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    spec_without_role_notes = bundle["spec"]["markdown"].split("\n# Role Notes\n", 1)[0]
    bundle["spec"]["markdown"] = (
        spec_without_role_notes
        + "\n\n# Role Notes\n\n"
        + "## Builder Notes\n\nBuilder reads AGENTS.md, design/README.md, design/, and tests/ before editing.\n\n"
        + "## Inspector Notes\n\nInspector verifies AGENTS.md, design/README.md, design/, and tests/ obligations against the result.\n\n"
        + "## GateKeeper Notes\n\nGateKeeper treats skipped AGENTS.md, design/README.md, design/, or tests/ evidence as Weak, Unproven, or Blocking.\n"
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "workdir_facts": "AGENTS.md, design/README.md, design/, and tests/ must shape runtime governance.",
            }
        }
    }

    issues = service._alignment_bundle_agreement_traceability_issues(session, bundle)

    assert not any("project-local governance markers" in issue for issue in issues)


def test_alignment_traceability_rejects_summary_only_governance_responsibilities(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))
    bundle["collaboration_summary"] += (
        "\nBuilder reads AGENTS.md, design/README.md, design/, and tests/ before editing. "
        "Inspector verifies AGENTS.md, design/README.md, design/, and tests/ obligations against the result. "
        "GateKeeper treats skipped AGENTS.md, design/README.md, design/, or tests/ evidence as Weak, Unproven, or Blocking."
    )
    session = {
        "working_agreement": {
            "readiness_evidence": {
                "workdir_facts": "AGENTS.md, design/README.md, design/, and tests/ must shape runtime governance.",
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


def test_bundle_control_summary_projects_execution_strategy(sample_workdir: Path) -> None:
    bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir)))

    summary = build_bundle_control_summary(bundle)

    assert any("Build one focused starter slice" in item for item in summary["execution_strategy"])
    assert any(item["key"] == "execution_strategy" and item["mapped"] for item in summary["traceability"]["items"])


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
        ("alignment_vague_judgment_tradeoffs_readiness_evidence", "judgment_tradeoffs"),
        ("alignment_vague_execution_strategy_readiness_evidence", "execution_strategy"),
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


def test_alignment_ready_preview_feedback_recompiles_from_current_bundle(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    created = service.create_alignment_session(
        workdir=sample_workdir,
        message=(
            "Create a focused starter Loop with project-owned evidence, fake-done protection, "
            "and conservative GateKeeper closure."
        ),
    )
    ready = _confirm_alignment_agreement(service, created["id"])
    bundle_before = Path(ready["bundle_path"]).read_text(encoding="utf-8")
    agreement_before = dict(ready["working_agreement"])
    feedback = (
        "审查后请调整这份 Loop 预览：primary user flow、project-owned evidence、"
        "happy-path claim 和 GateKeeper weak proof 必须继续作为阻断判断。"
    )

    service.append_alignment_message(ready["id"], feedback)
    reviewed = _wait_for_status(service, ready["id"], "ready")

    assert reviewed["alignment_stage"] == "ready"
    assert reviewed["working_agreement"]["summary"] == agreement_before["summary"]
    assert reviewed["working_agreement"]["readiness_checklist"]["explicit_confirmation"] is True
    assert reviewed["working_agreement"]["ready_review"]["feedback"] == feedback
    assert Path(reviewed["bundle_path"]).read_text(encoding="utf-8").strip()
    transcript_log = Path(reviewed["artifact_dir"]) / "conversation" / "transcript.jsonl"
    assert feedback in transcript_log.read_text(encoding="utf-8")
    events = service.list_alignment_events(ready["id"])
    assert any(event["event_type"] == "alignment_ready_review_started" for event in events)
    assert any(event["event_type"] == "alignment_bundle_written" for event in events)
    prompt_paths = sorted((Path(reviewed["artifact_dir"]) / "invocations").glob("*/prompt.md"))
    assert len(prompt_paths) >= 2
    prompt_text = prompt_paths[-1].read_text(encoding="utf-8")
    assert "Current compiler gate: ready preview review" in prompt_text
    assert "The session already has a READY candidate bundle" in prompt_text
    assert "## Current Bundle" in prompt_text
    assert bundle_before.splitlines()[0] in prompt_text
    assert feedback in prompt_text


def test_alignment_api_start_immediately_false_keeps_new_session_idle(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service))

    response = client.post(
        "/api/alignments/sessions",
        json={
            "workdir": str(sample_workdir),
            "message": "Create a bundle later.",
            "start_immediately": "false",
        },
    )

    assert response.status_code == 201
    session_id = response.json()["session"]["id"]
    session = service.get_alignment_session(session_id)
    assert session["status"] == "idle"
    assert session["transcript"][-1]["content"] == "Create a bundle later."
    assert not any(event["event_type"] == "alignment_started" for event in service.list_alignment_events(session_id))


def test_alignment_stream_emits_redacted_stream_error_on_backend_failure(caplog) -> None:
    class FlakyService:
        def get_alignment_session(self, session_id: str) -> dict:
            return {"id": session_id, "status": "running"}

        def latest_alignment_event_id(self, session_id: str) -> int:
            assert session_id == "session_test"
            return 9

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


def test_alignment_event_api_rejects_cursor_beyond_current_events() -> None:
    class CursorAwareService:
        def get_alignment_session(self, session_id: str) -> dict:
            return {"id": session_id, "status": "ready"}

        def latest_alignment_event_id(self, session_id: str) -> int:
            assert session_id == "session_test"
            return 10

    client = TestClient(build_app(service=CursorAwareService()))

    response = client.get("/api/alignments/sessions/session_test/events?after_id=11")

    assert response.status_code == 400
    assert response.json()["error"] == "event cursor is out of range"


def test_alignment_stream_logs_invalid_resume_cursor_and_keeps_request_cursor(caplog) -> None:
    captured: dict[str, int] = {}

    class CursorAwareService:
        def get_alignment_session(self, session_id: str) -> dict:
            return {"id": session_id, "status": "ready"}

        def latest_alignment_event_id(self, session_id: str) -> int:
            assert session_id == "session_test"
            return 10

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
            headers={"Last-Event-ID": "11"},
        ) as response,
    ):
        assert response.status_code == 200
        assert "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text()) == ""

    assert captured["after_id"] == 7
    assert any(
        getattr(record, "event", "") == "web.alignment_stream.resume_cursor_invalid"
        and getattr(record, "context", {}).get("session_id") == "session_test"
        and getattr(record, "context", {}).get("after_id") == 7
        and getattr(record, "context", {}).get("latest_event_id") == 10
        and getattr(record, "context", {}).get("invalid_last_event_id") == "11"
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


def test_alignment_improvement_bundle_accepts_loop_verdict_marker_for_completion_mode_delta(
    service_factory,
) -> None:
    service = service_factory(scenario="success")
    bundle = {
        "metadata": {},
        "collaboration_summary": (
            "保留来源 Loop 的稳定意图；基于反馈变化，新的方案把 rounds completion mode 的"
            "运行生命周期与 Loop 裁决分开，并把证据放回治理面。"
        ),
        "loop": {},
        "spec": {},
        "workflow": {},
        "role_definitions": [],
    }
    session = {
        "working_agreement": {
            "mode": "improvement",
            "source": {
                "source_completion_mode": "rounds",
            },
        },
    }

    issues = service._alignment_improvement_bundle_issues(session, bundle)

    assert "improvement bundle must state the source completion-mode governance delta" not in issues


def test_alignment_improvement_readiness_accepts_loop_verdict_marker_for_completion_mode_delta(
    service_factory,
) -> None:
    service = service_factory(scenario="success")
    session = {
        "working_agreement": {
            "mode": "improvement",
            "source": {
                "source_completion_mode": "rounds",
            },
        },
    }
    output = {
        "agreement_summary": (
            "保留既有意图，基于反馈调整治理面；原完成模式是 rounds，新的运行生命周期"
            "与 Loop 裁决分开。"
        ),
        "readiness_evidence": {},
    }

    issues = service._alignment_improvement_readiness_issues(session, output)

    assert "improvement_completion_mode_delta" not in issues


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
    run_contract_path = Path(run["runs_dir"]) / "contract" / "run_contract.json"
    run_contract_payload = json.loads(run_contract_path.read_text(encoding="utf-8"))
    run_contract_payload["execution_strategy"] = ["Repair evidence gaps before broad polishing."]
    run_contract_payload["local_governance"] = ["GateKeeper treats skipped AGENTS.md evidence as Blocking."]
    run_contract_path.write_text(json.dumps(run_contract_payload, ensure_ascii=False), encoding="utf-8")
    _write_run_revision_coverage(Path(run["runs_dir"]) / "evidence" / "coverage.json")

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == run["id"]
    assert agreement["source"]["run_status"] == run["status"]
    assert agreement["source"]["artifact_paths"] == {
        "run_contract": "contract/run_contract.json",
        "task_verdict": "evidence/task_verdict.json",
        "evidence_ledger": "evidence/ledger.jsonl",
        "evidence_coverage": "evidence/coverage.json",
        "evidence_manifest": "evidence/manifest.json",
    }
    assert agreement["source"]["judgment_contract"]["contract_path"] == "contract/run_contract.json"
    assert agreement["source"]["judgment_contract"]["collaboration_summary"] == "Use GateKeeper evidence to improve the plan."
    assert agreement["source"]["judgment_contract"]["execution_strategy"] == ["Repair evidence gaps before broad polishing."]
    assert agreement["source"]["judgment_contract"]["local_governance"] == ["GateKeeper treats skipped AGENTS.md evidence as Blocking."]
    _assert_run_revision_coverage_agreement(agreement)
    context_text = alignment_module.ServiceAlignmentMixin._alignment_improvement_context_text(session)
    _assert_run_revision_context_text(context_text, run, agreement)
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True
    assert preview["bundle"]["metadata"]["source_bundle_id"] == ""
    assert "source_bundle_id" not in preview["yaml"]


def _write_run_revision_coverage(coverage_path: Path) -> None:
    coverage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ledger_path": "evidence/ledger.jsonl",
                "coverage_path": "evidence/coverage.json",
                "status": "partial",
                "summary": {"reason": "Required refund audit and payment failure checks still lack direct proof."},
                "evidence_count": 4,
                "check_count": 3,
                "covered_check_count": 1,
                "missing_check_count": 2,
                "covered_check_ids": ["check_permission"],
                "missing_check_ids": ["check_payment_failure", "check_audit_trail"],
                "target_count": 6,
                "covered_target_count": 2,
                "weak_target_count": 1,
                "missing_target_count": 2,
                "blocked_target_count": 1,
                "top_gaps": [
                    {
                        "target_id": "done_when.check_payment_failure",
                        "text": "Payment failure handoff has no direct proof.",
                    },
                    {
                        "target_id": "done_when.check_audit_trail",
                        "text": "Audit trail cannot yet reconstruct a refund.",
                    },
                ],
                "evidence_kind_counts": {"artifact": 2, "summary": 2},
                "artifact_ref_count": 2,
                "residual_risk_count": 1,
                "risk_signals": ["Payment provider retry path remains visible."],
                "latest_gatekeeper": {"id": "ev_gatekeeper", "result": "blocked"},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _assert_run_revision_coverage_agreement(agreement: dict) -> None:
    coverage_summary = agreement["source"]["coverage_summary"]
    assert coverage_summary["ledger_path"] == "evidence/ledger.jsonl"
    assert coverage_summary["coverage_path"] == "evidence/coverage.json"
    assert coverage_summary["covered_check_count"] == 1
    assert coverage_summary["missing_check_count"] == 2
    assert coverage_summary["covered_check_ids"] == ["check_permission"]
    assert coverage_summary["missing_check_ids"] == ["check_payment_failure", "check_audit_trail"]
    assert coverage_summary["weak_target_count"] == 1
    assert coverage_summary["blocked_target_count"] == 1
    assert coverage_summary["risk_signals"] == ["Payment provider retry path remains visible."]
    assert any(item["artifact_refs"] for item in agreement["source"]["evidence_summary"])
    assert agreement["source"]["task_verdict"]["status"]
    assert "gatekeeper_verdict" in agreement["source"]
    assert agreement["source"]["gatekeeper_verdict"]["decision_summary"]


def _assert_run_revision_context_text(context_text: str, run: dict, agreement: dict) -> None:
    assert f"Source run status: {run['status']}" in context_text
    assert "Artifact paths:" in context_text
    assert "evidence/task_verdict.json" in context_text
    assert "Frozen judgment contract:" in context_text
    assert "Use GateKeeper evidence to improve the plan." in context_text
    assert "Repair evidence gaps before broad polishing." in context_text
    assert "GateKeeper treats skipped AGENTS.md evidence as Blocking." in context_text
    assert "`execution_strategy` should say what the next version should build" in context_text
    assert "`local_governance` should preserve or revise project-local governance responsibilities" in context_text
    assert '"missing_check_count": 2' in context_text
    assert "check_payment_failure" in context_text
    assert "Payment failure handoff has no direct proof." in context_text
    assert "Payment provider retry path remains visible." in context_text
    assert "Task verdict:" in context_text
    assert agreement["source"]["task_verdict"]["status"] in context_text
    assert "GateKeeper verdict:" in context_text
    assert "decision_summary" in context_text


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
    (Path(run["runs_dir"]) / "evidence" / "task_verdict.json").unlink()

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_run_id"] == run["id"]
    assert agreement["source"]["artifact_paths"] == {
        "run_contract": "contract/run_contract.json",
        "task_verdict": "evidence/task_verdict.json",
        "evidence_ledger": "evidence/ledger.jsonl",
        "evidence_coverage": "evidence/coverage.json",
        "evidence_manifest": "evidence/manifest.json",
    }
    assert agreement["source"]["judgment_contract"]["contract_path"] == "contract/run_contract.json"
    assert agreement["source"]["evidence_summary"] == []
    preview = service.get_alignment_bundle(session["id"])
    assert preview["ok"] is True


def test_alignment_run_evidence_summary_drops_malformed_trace_shapes(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = service.create_loop(
        name="Malformed Evidence Summary Loop",
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
    proof_path = sample_workdir / "proof.md"
    ledger_path = Path(run["runs_dir"]) / "evidence" / "ledger.jsonl"
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "id": "ev_bad_shape",
                        "claim": "Bad trace shapes should not become prompt structure.",
                        "verifies": "target:done_when.check_001:covered",
                        "artifact_refs": {"kind": "workspace", "relative_path": "proof.md"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "id": "ev_good_shape",
                        "claim": "Good trace shapes should keep only stable fields.",
                        "verifies": ["target:done_when.check_001:covered", 7, True],
                        "artifact_refs": [
                            {
                                "kind": "workspace",
                                "label": "proof",
                                "relative_path": "proof.md",
                                "workspace_path": "proof.md",
                                "absolute_path": str(proof_path),
                                "raw_payload": "uncommitted payload",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    session = service.create_run_revision_session(run["id"], start_immediately=False)

    summary = session["working_agreement"]["source"]["evidence_summary"]
    assert summary[0]["id"] == "ev_bad_shape"
    assert summary[0]["verifies"] == []
    assert summary[0]["artifact_refs"] == []
    assert summary[1]["id"] == "ev_good_shape"
    assert summary[1]["verifies"] == ["target:done_when.check_001:covered"]
    assert summary[1]["artifact_refs"] == [
        {
            "kind": "workspace",
            "label": "proof",
            "relative_path": "proof.md",
            "workspace_path": "proof.md",
            "absolute_path": str(proof_path),
        }
    ]
    assert "raw_payload" not in json.dumps(summary, ensure_ascii=False)


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
    empty_context = service.get_alignment_workdir_context(sample_workdir)
    assert empty_context["requires_choice"] is False
    assert empty_context["recommended_option_id"] == "regenerate"
    assert empty_context["resolution"]["action"] == "create_new"
    assert empty_context["resolution"]["confidence"] == "no_existing_context"
    assert empty_context["resolution"]["fresh"] is True

    state_dir = sample_workdir / ".loopora"
    state_dir.mkdir()
    spec_path = state_dir / "spec.md"
    spec_path.write_text("# Task\n\n编排一个英语学习网站。\n", encoding="utf-8")
    invocation_dir = state_dir / "alignment_sessions" / "align_old" / "invocations" / "0001"
    invocation_dir.mkdir(parents=True)
    (invocation_dir / "stdout.log").write_text("secret execution log\n", encoding="utf-8")

    context = service.get_alignment_workdir_context(sample_workdir)

    assert context["requires_choice"] is True
    assert context["resolution"]["action"] == "choose_source"
    assert context["resolution"]["requires_user_choice"] is True
    spec_option = next(option for option in context["options"] if option["source_type"] == "spec_file")
    assert spec_option["spec_path"] == str(spec_path)
    assert spec_option["label_zh"].startswith("从已有任务契约开始")
    assert "角色责任" in spec_option["description_zh"]
    assert "roles" not in spec_option["description_zh"]
    assert "workflow" not in spec_option["description_zh"]
    assert any(option["action"] == "regenerate" for option in context["options"])
    fresh_resolution = service.resolve_loopora_context(
        sample_workdir,
        intent="plan",
        source_option_id="regenerate",
    )
    assert fresh_resolution["action"] == "create_new"
    assert fresh_resolution["fresh"] is True
    assert fresh_resolution["confidence"] == "explicit_fresh"
    fresh_session = service.create_alignment_session(
        workdir=sample_workdir,
        message="重新创建一份 Loop，不复用旧 spec。",
        source_option_id="regenerate",
        start_immediately=False,
    )
    assert fresh_session["working_agreement"] == {}
    assert not fresh_session.get("linked_bundle_id")
    assert not fresh_session.get("linked_run_id")
    fresh_prompt = service._build_alignment_prompt(fresh_session, mode="normal")
    assert "Selected Loopora Source Context" not in fresh_prompt
    assert "secret execution log" not in fresh_prompt

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


def test_alignment_workdir_context_only_lists_validated_local_ready_bundles(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    state_dir = sample_workdir / ".loopora"
    valid_bundle = state_dir / "alignment_sessions" / "align_valid" / "artifacts" / "bundle.yml"
    stale_ready_bundle = state_dir / "alignment_sessions" / "align_stale_ready" / "artifacts" / "bundle.yml"
    wrong_workdir_bundle = state_dir / "alignment_sessions" / "align_wrong_workdir" / "artifacts" / "bundle.yml"
    failed_bundle = state_dir / "alignment_sessions" / "align_failed" / "artifacts" / "bundle.yml"
    unknown_bundle = state_dir / "alignment_sessions" / "align_unknown" / "artifacts" / "bundle.yml"
    for bundle_path in (valid_bundle, stale_ready_bundle, wrong_workdir_bundle, failed_bundle, unknown_bundle):
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_path.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    (valid_bundle.parent / "validation.json").write_text('{"ok": true}\n', encoding="utf-8")
    stale_ready_bundle.write_text(
        stale_ready_bundle.read_text(encoding="utf-8").replace(
            "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
            "Some risk is fine.",
        ),
        encoding="utf-8",
    )
    (stale_ready_bundle.parent / "validation.json").write_text('{"ok": true}\n', encoding="utf-8")
    wrong_workdir = sample_workdir.parent / "other-workdir"
    wrong_workdir_bundle.write_text(alignment_bundle_yaml(str(wrong_workdir.resolve())), encoding="utf-8")
    (wrong_workdir_bundle.parent / "validation.json").write_text('{"ok": true}\n', encoding="utf-8")
    (failed_bundle.parent / "validation.json").write_text('{"ok": false, "error": "semantic lint failed"}\n', encoding="utf-8")

    context = service.get_alignment_workdir_context(sample_workdir)
    local_options = [
        option
        for option in context["options"]
        if option.get("source_type") == "alignment_session_file"
    ]

    assert [option["source_alignment_session_id"] for option in local_options] == ["align_valid"]
    assert local_options[0]["bundle_path"] == str(valid_bundle)
    assert "方案文件" in local_options[0]["description_zh"]
    assert "bundle" not in local_options[0]["description_zh"]


def test_alignment_workdir_context_does_not_seed_from_stale_ready_session_bundle(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create a reusable READY Loop.")["id"],
    )
    bundle_path = Path(session["bundle_path"])
    stale_bundle = load_bundle_text(bundle_path.read_text(encoding="utf-8"))
    stale_bundle["spec"]["markdown"] = stale_bundle["spec"]["markdown"].replace(
        "Accept minor polish gaps only when they are explicitly named and tracked as an owned follow-up; fail closed on unproven primary-flow behavior or weak verification evidence.",
        "Some risk is fine.",
    )
    bundle_path.write_text(bundle_to_yaml(stale_bundle), encoding="utf-8")
    wrong_workdir_session = _confirm_alignment_agreement(
        service,
        service.create_alignment_session(workdir=sample_workdir, message="Create another reusable READY Loop.")["id"],
    )
    wrong_workdir_bundle_path = Path(wrong_workdir_session["bundle_path"])
    wrong_workdir_bundle = load_bundle_text(wrong_workdir_bundle_path.read_text(encoding="utf-8"))
    wrong_workdir_bundle["loop"]["workdir"] = str((sample_workdir.parent / "other-workdir").resolve())
    wrong_workdir_bundle_path.write_text(bundle_to_yaml(wrong_workdir_bundle), encoding="utf-8")

    context = service.get_alignment_workdir_context(sample_workdir)

    assert any(
        option.get("action") == "continue_session" and option.get("session_id") == session["id"]
        for option in context["options"]
    )
    assert not any(
        option.get("action") == "improve"
        and option.get("source_type") == "alignment_session"
        and option.get("source_alignment_session_id") == session["id"]
        for option in context["options"]
    )
    assert not any(
        option.get("action") == "improve"
        and option.get("source_type") == "alignment_session"
        and option.get("source_alignment_session_id") == wrong_workdir_session["id"]
        for option in context["options"]
    )


def test_alignment_workdir_context_preserves_regenerate_option_when_source_list_is_bounded(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    for index in range(25):
        service.create_alignment_session(
            workdir=sample_workdir,
            message=f"Existing alignment source {index}",
            start_immediately=False,
        )

    context = service.get_alignment_workdir_context(sample_workdir)
    option_ids = [option["option_id"] for option in context["options"]]

    assert len(context["options"]) == 20
    assert context["requires_choice"] is True
    assert context["recommended_option_id"] == ""
    assert option_ids[-1] == "regenerate"
    assert sum(option_id == "regenerate" for option_id in option_ids) == 1


def test_alignment_source_context_redacts_sensitive_transcript_and_spec_material(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    state_dir = sample_workdir / ".loopora"
    state_dir.mkdir()
    spec_path = state_dir / "spec.md"
    spec_path.write_text("# Task\n\nCall the API with Authorization: Bearer SPEC_SECRET_MARKER.\n", encoding="utf-8")
    source_session_id = "align_secret_source"
    bundle_path = state_dir / "alignment_sessions" / source_session_id / "artifacts" / "bundle.yml"
    bundle_path.parent.mkdir(parents=True)
    bundle_path.write_text(alignment_bundle_yaml(str(sample_workdir.resolve())), encoding="utf-8")
    service.repository.create_alignment_session(
        {
            "id": source_session_id,
            "status": "ready",
            "workdir": str(sample_workdir),
            "bundle_path": str(bundle_path),
            "transcript": [
                {
                    "role": "user",
                    "content": "Improve this Loop with --token TRANSCRIPT_TOKEN_SECRET_MARKER and Cookie: sid=TRANSCRIPT_COOKIE_SECRET_MARKER",
                    "created_at": "now",
                }
            ],
            "validation": {"ok": True},
            "alignment_stage": "ready",
            "working_agreement": {},
            "executor_session_ref": {},
        }
    )

    context = service.get_alignment_workdir_context(sample_workdir)
    context_text = json.dumps(context, ensure_ascii=False)

    assert "TRANSCRIPT_TOKEN_SECRET_MARKER" not in context_text
    assert "TRANSCRIPT_COOKIE_SECRET_MARKER" not in context_text

    session_option = next(option for option in context["options"] if option.get("source_alignment_session_id") == source_session_id)
    assert "方案文件" in session_option["description_zh"]
    assert "bundle" not in session_option["description_zh"]
    assert "session" not in session_option["description_zh"]
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Use the old alignment as source context.",
        source_option_id=session_option["option_id"],
        start_immediately=False,
    )
    prompt = service._build_alignment_prompt(session, mode="normal")
    source_text = json.dumps(session["working_agreement"], ensure_ascii=False)

    assert "TRANSCRIPT_TOKEN_SECRET_MARKER" not in source_text
    assert "TRANSCRIPT_COOKIE_SECRET_MARKER" not in source_text
    assert "TRANSCRIPT_TOKEN_SECRET_MARKER" not in prompt
    assert "TRANSCRIPT_COOKIE_SECRET_MARKER" not in prompt
    assert "<secret omitted>" in prompt

    spec_option = next(option for option in context["options"] if option["source_type"] == "spec_file")
    spec_session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Use the spec as source context.",
        source_option_id=spec_option["option_id"],
        start_immediately=False,
    )

    assert "SPEC_SECRET_MARKER" not in spec_session["working_agreement"]["source"]["spec_markdown"]
    assert "<secret omitted>" in service._build_alignment_prompt(spec_session, mode="normal")


def test_alignment_improvement_context_redacts_sensitive_run_source_values(service_factory) -> None:
    service = service_factory(scenario="success")
    session = {
        "working_agreement": {
            "mode": "improvement",
            "source": {
                "source_type": "run",
                "source_run_id": "run_secret",
                "evidence_summary": [{"claim": "Observed Authorization: Bearer RUN_EVIDENCE_SECRET_MARKER"}],
                "coverage_summary": {"reason": "Header x-api-key: RUN_API_KEY_SECRET_MARKER"},
                "task_verdict": {"summary": "Cookie: sid=RUN_COOKIE_SECRET_MARKER"},
                "gatekeeper_verdict": {"decision_summary": "tool --token RUN_TOKEN_SECRET_MARKER"},
            },
        }
    }

    context = service._alignment_improvement_context_text(session)

    assert "RUN_EVIDENCE_SECRET_MARKER" not in context
    assert "RUN_API_KEY_SECRET_MARKER" not in context
    assert "RUN_COOKIE_SECRET_MARKER" not in context
    assert "RUN_TOKEN_SECRET_MARKER" not in context
    assert "<secret omitted>" in context


def test_alignment_improvement_session_redacts_persisted_source_context(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    seed_bundle = load_bundle_text(alignment_bundle_yaml(str(sample_workdir.resolve())))

    session = service._create_revision_alignment_session(
        alignment_module.RevisionAlignmentSessionRequest(
            seed_bundle=seed_bundle,
            message="Use sensitive source context.",
            start_immediately=False,
            source_context={
                "mode": "improvement",
                "source_type": "run",
                "source_run_id": "run_secret",
                "evidence_summary": [{"claim": "Authorization: Bearer PERSISTED_EVIDENCE_SECRET"}],
                "coverage_summary": {"reason": "x-api-key: PERSISTED_API_KEY_SECRET"},
                "task_verdict": {"summary": "Cookie: sid=PERSISTED_COOKIE_SECRET"},
                "gatekeeper_verdict": {"decision_summary": "tool --token PERSISTED_TOKEN_SECRET"},
            },
            linked_bundle_id="",
            linked_run_id="run_secret",
            executor_settings=alignment_module._default_alignment_executor_settings(),
        )
    )

    source_text = json.dumps(session["working_agreement"], ensure_ascii=False)

    assert "PERSISTED_EVIDENCE_SECRET" not in source_text
    assert "PERSISTED_API_KEY_SECRET" not in source_text
    assert "PERSISTED_COOKIE_SECRET" not in source_text
    assert "PERSISTED_TOKEN_SECRET" not in source_text
    assert "<secret omitted>" in source_text


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


def test_alignment_workdir_context_run_option_exposes_artifact_refs_and_rehydrates_source(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    source = _create_alignment_improvement_source_bundle(service, sample_spec_file, sample_workdir)
    run = service.rerun(source["loop_id"])

    context = service.get_alignment_workdir_context(sample_workdir)
    run_option = next(option for option in context["options"] if option.get("source_run_id") == run["id"])

    assert run_option["source_type"] == "run"
    assert "Loop 裁决" in run_option["description_zh"]
    assert "守门裁决" in run_option["description_zh"]
    for option in context["options"]:
        description_zh = option.get("description_zh", "")
        assert "task verdict" not in description_zh
        assert "最近一次 run" not in description_zh
        assert "GateKeeper" not in description_zh
        assert "bundle" not in description_zh
        assert "spec、roles" not in description_zh
        assert "workflow" not in description_zh
    assert run_option["artifact_paths"] == {
        "run_contract": "contract/run_contract.json",
        "task_verdict": "evidence/task_verdict.json",
        "evidence_ledger": "evidence/ledger.jsonl",
        "evidence_coverage": "evidence/coverage.json",
        "evidence_manifest": "evidence/manifest.json",
    }
    assert "evidence_summary" not in run_option
    assert "task_verdict" not in run_option
    assert "gatekeeper_verdict" not in run_option

    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="基于这次 run 的证据继续改进方案。",
        source_option_id=run_option["option_id"],
        start_immediately=False,
    )

    agreement = session["working_agreement"]
    assert agreement["mode"] == "improvement"
    assert agreement["source"]["source_type"] == "run"
    assert agreement["source"]["source_bundle_id"] == source["id"]
    assert agreement["source"]["source_run_id"] == run["id"]
    assert agreement["source"]["artifact_paths"] == {
        "run_contract": "contract/run_contract.json",
        "task_verdict": "evidence/task_verdict.json",
        "evidence_ledger": "evidence/ledger.jsonl",
        "evidence_coverage": "evidence/coverage.json",
        "evidence_manifest": "evidence/manifest.json",
    }
    assert agreement["source"]["judgment_contract"]["contract_path"] == "contract/run_contract.json"
    assert agreement["source"]["task_verdict"]["status"]
    assert agreement["source"]["gatekeeper_verdict"]["decision_summary"]
    assert any(item["artifact_refs"] for item in agreement["source"]["evidence_summary"])
    prompt = service._build_alignment_prompt(session, mode="normal")
    assert "Recent evidence summary:" in prompt
    assert "Frozen judgment contract:" in prompt
    assert "artifact_refs" in prompt


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


def test_alignment_selected_spec_source_degrades_invalid_utf8(
    service_factory,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    state_dir = sample_workdir / ".loopora"
    state_dir.mkdir()
    spec_path = state_dir / "spec.md"
    spec_path.write_bytes(b"\xff")

    context = service.get_alignment_workdir_context(sample_workdir)
    spec_option = next(option for option in context["options"] if option["source_type"] == "spec_file")
    session = service.create_alignment_session(
        workdir=sample_workdir,
        message="Use this spec as source context.",
        source_option_id=spec_option["option_id"],
        start_immediately=False,
    )

    source = session["working_agreement"]["source"]
    assert source["spec_path"] == str(spec_path)
    assert source["artifact_paths"] == {"spec": str(spec_path)}
    assert source["spec_markdown"] == "Source file could not be read as UTF-8 text."


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
    original_move = alignment_legacy_module.shutil.move

    def fail_stale_move(source: str, target: str):
        if Path(source).name == "stale.tmp":
            raise OSError("locked legacy file")
        return original_move(source, target)

    monkeypatch.setattr(alignment_legacy_module.shutil, "move", fail_stale_move)
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
