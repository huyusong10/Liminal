from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from loopora.bundles import bundle_to_yaml
from loopora.executor_fake_payloads import alignment_bundle_yaml
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.web import build_app


def _assert_ok(response) -> None:
    assert response.status_code == 200, response.text[:500]


def _assert_testids(html: str, *testids: str) -> None:
    for testid in testids:
        assert f'data-testid="{testid}"' in html


def _create_loop(service, spec_path: Path, workdir: Path, *, name: str = "Web Journey Loop") -> dict:
    return service.create_loop(
        name=name,
        spec_path=spec_path,
        workdir=workdir,
        model="",
        reasoning_effort="",
        max_iters=2,
        max_role_retries=1,
        delta_threshold=0.005,
        trigger_window=2,
        regression_window=2,
        role_models={},
    )


def _import_web_bundle(service, spec_path: Path, workdir: Path) -> dict:
    loop = _create_loop(service, spec_path, workdir, name="Plan File Source")
    bundle = service.derive_bundle_from_loop(
        loop["id"],
        name="Web Plan File",
        description="Plan file page smoke test.",
        collaboration_summary="Prefer evidence and visible proof.",
    )
    return service.import_bundle_text(bundle_to_yaml(bundle))


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
            entry_source="codex_project_skill",
        )
    )
    return service.start_agent_loop("codex", workdir=workdir, entry_source="codex_project_skill", execute_async=False)


def test_web_full_function_surfaces_are_reachable(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir)
    run = service.rerun(loop["id"])
    imported = _import_web_bundle(service, sample_spec_file, sample_workdir)
    client = TestClient(build_app(service=service))

    surfaces = {
        "/": ("top-nav", "nav-compose-link", "home-workbench"),
        "/loops/new": ("loop-create-page", "loop-create-choice-page"),
        "/loops/new/bundle": ("loop-create-page", "alignment-start-form", "alignment-history-panel"),
        "/loops/new/manual": ("loop-create-page", "manual-compose-section", "loop-create-form"),
        "/tools": ("agent-adapters-panel", "agent-adapter-grid", "wake-lock-panel-section"),
        "/tutorial": ("tutorial-page", "tutorial-hero-actions", "tutorial-actions-panel"),
        "/roles": ("role-definitions-page", "builtin-role-templates-list"),
        "/orchestrations": ("orchestrations-page", "builtin-orchestrations-list"),
        "/bundles": ("bundles-page", "bundle-list"),
        f"/bundles/{imported['id']}": ("bundle-detail-page", "bundle-spec-preview", "bundle-yaml-preview"),
        f"/loops/{loop['id']}": ("loop-detail-page", "loop-detail-history-panel"),
        f"/runs/{run['id']}": ("run-detail-page", "run-console-panel", "run-timeline-panel"),
    }

    for path, testids in surfaces.items():
        response = client.get(path)
        _assert_ok(response)
        _assert_testids(response.text, *testids)


def test_run_pages_prioritize_loop_verdict_over_process_success(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Verdict Journey")
    run = service.rerun(loop["id"])
    service.repository.update_run(
        run["id"],
        status="succeeded",
        task_verdict={
            "status": "insufficient_evidence",
            "source": "gatekeeper",
            "summary": "Missing audit proof.",
            "buckets": {"unproven": [{"label": "audit proof missing"}]},
        },
        summary_md="# Loopora Run Summary\n\nAll done according to the Agent summary.",
    )
    client = TestClient(build_app(service=service))

    home = client.get("/")
    loop_page = client.get(f"/loops/{loop['id']}")
    run_page = client.get(f"/runs/{run['id']}")
    for response in (home, loop_page, run_page):
        _assert_ok(response)

    assert "Missing audit proof." in home.text + loop_page.text + run_page.text
    assert "All done according to the Agent summary." not in home.text + loop_page.text
    _assert_testids(home.text, "home-recent-loop-verdict")
    _assert_testids(loop_page.text, "loop-latest-verdict-pill", "loop-run-history-verdict")
    _assert_testids(run_page.text, "run-improve-chat-button", "run-rerun-button", "run-accept-result-button")

    accept_response = client.post(f"/runs/{run['id']}/accept", follow_redirects=False)
    assert accept_response.status_code == 303
    accepted_event = service.recent_run_events(run["id"], event_types={"run_result_accepted"})[-1]
    assert accepted_event["payload"]["task_verdict_status"] == "insufficient_evidence"
    assert accepted_event["payload"]["recorded_verdict_kind"] == "unproven_verdict_recorded"


def test_agent_native_loop_pages_keep_command_handoff_instead_of_web_start(
    service_factory,
    sample_workdir: Path,
    tmp_path: Path,
) -> None:
    service = service_factory(scenario="success")
    started = _start_agent_first_loop(service, tmp_path=tmp_path, workdir=sample_workdir)
    client = TestClient(build_app(service=service))

    loop_page = client.get(f"/loops/{started['run']['loop_id']}")
    run_page = client.get(f"/runs/{started['run']['id']}")
    for response in (loop_page, run_page):
        _assert_ok(response)
        assert "/loopora-loop" in response.text
        assert "codex_project_skill" in response.text
        assert 'action="/api/loops/' not in response.text

    _assert_testids(loop_page.text, "loop-agent-entry-start-guide", "loop-agent-entry-copy-command")
    _assert_testids(run_page.text, "run-agent-handoff-card", "agent-handoff-copy-submit")


def test_plan_file_surfaces_cover_preview_replace_export_and_diagnostics(
    service_factory,
    sample_spec_file: Path,
    sample_workdir: Path,
) -> None:
    service = service_factory(scenario="success")
    imported = _import_web_bundle(service, sample_spec_file, sample_workdir)
    service._bundle_spec_path(imported["id"]).write_bytes(b"\xff")

    loop = _create_loop(service, sample_spec_file, sample_workdir, name="Diagnostic Source")
    weak_bundle = service.derive_bundle_from_loop(
        loop["id"],
        name="Weak Plan File",
        description="Projection test.",
        collaboration_summary="Prefer evidence and visible proof.",
    )
    for step in weak_bundle["workflow"]["steps"]:
        if step["id"] == "gatekeeper_step":
            step.pop("inputs", None)
    weak_import = service.import_bundle_text(bundle_to_yaml(weak_bundle))
    client = TestClient(build_app(service=service))

    list_page = client.get("/bundles")
    unreadable_detail = client.get(f"/bundles/{imported['id']}")
    diagnostic_detail = client.get(f"/bundles/{weak_import['id']}")
    export_response = client.get(f"/api/bundles/{weak_import['id']}/export")
    replace_redirect = client.get(f"/loops/new?replace_bundle_id={weak_import['id']}", follow_redirects=False)
    replace_page = client.get(f"/loops/new/manual?replace_bundle_id={weak_import['id']}")

    for response in (list_page, unreadable_detail, diagnostic_detail, export_response, replace_page):
        _assert_ok(response)
    assert replace_redirect.status_code == 303
    assert replace_redirect.headers["location"] == f"/loops/new/manual?replace_bundle_id={weak_import['id']}#bundle-import-form"

    _assert_testids(list_page.text, "bundles-page", "bundle-list")
    _assert_testids(unreadable_detail.text, "bundle-detail-page")
    assert "bundle spec file could not be read" in unreadable_detail.text
    _assert_testids(diagnostic_detail.text, "bundle-diagnostic-projection", "bundle-diagnostic-row")
    assert "gatekeeper_missing_handoff_fan_in" in diagnostic_detail.text
    _assert_testids(replace_page.text, "bundle-replace-target-note")
    assert "workflow:" in export_response.text


def test_web_entry_redirects_keep_auth_out_of_urls_and_remote_paths_explicit(service_factory) -> None:
    service = service_factory(scenario="success")
    client = TestClient(build_app(service=service, bind_host="0.0.0.0", auth_token="secret-token"))

    redirect = client.get("/loops/new?token=secret-token&workdir=/tmp/demo", follow_redirects=False)
    remote_manual = client.get("/loops/new/manual?token=secret-token")

    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/loops/new/manual?workdir=%2Ftmp%2Fdemo#manual-loop-form"
    assert "secret-token" not in redirect.headers["location"]
    assert client.cookies.get("loopora_auth") == "secret-token"
    _assert_ok(remote_manual)
    _assert_testids(remote_manual.text, "remote-path-callout")
    assert 'aria-disabled="true"' in remote_manual.text
