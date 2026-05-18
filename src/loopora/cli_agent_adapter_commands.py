from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Annotated

import typer

from loopora.agent_web import ensure_local_web_service, web_url_for_path
from loopora.agent_adapters import read_agent_binding, resolve_adapter_project_root
from loopora.cli_shared import JsonOutputOption, call_spawn_background_worker, echo_json, get_service, handle_error
from loopora.cli_run_support import print_run_contract_summary, print_task_verdict
from loopora.service import LooporaError
from loopora.service_agent_native import AgentNativeStepClaimRequest, AgentNativeStepSubmitRequest
from loopora.service_agent_adapters import AgentBundleCandidateRequest
from loopora.service_types import LooporaConflictError
from loopora.workflows import WorkflowError

PASSING_TASK_VERDICT_STATUSES = frozenset({"passed", "passed_with_residual_risk"})

AdapterWorkdirOption = Annotated[
    Path,
    typer.Option(
        "--workdir",
        exists=True,
        file_okay=False,
        dir_okay=True,
        help="Project directory where the Coding Agent will work.",
    ),
]
ContextIdOption = Annotated[
    str,
    typer.Option("--context-id", help="Optional host session/thread identity. Defaults to Loopora, Codex, Claude Code, or OpenCode session env vars, then workdir."),
]
EntrySourceOption = Annotated[
    str,
    typer.Option("--entry-source", hidden=True, help="Internal marker for Loopora-managed Agent entry provenance."),
]
BundleFileOption = Annotated[
    Path | None,
    typer.Option(
        "--bundle-file",
        "--plan-file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Candidate Loop plan file produced by the Coding Agent.",
    ),
]
ResultFileOption = Annotated[
    Path,
    typer.Option("--result-file", exists=True, file_okay=True, dir_okay=False, help="JSON result produced by the host Agent for the claimed Loopora step."),
]
RunIdOption = Annotated[str, typer.Option("--run-id", help="Optional Loopora run id. Defaults to the run bound to the current host session/workdir.")]
StepIdOption = Annotated[str, typer.Option("--step-id", help="Loopora step id being submitted.")]
AdapterMessageOption = Annotated[
    str,
    typer.Option("--message", help="Short task summary for the Loop preview; required for Agent-first traceability."),
]
NoWebOption = Annotated[bool, typer.Option("--no-web", hidden=True, help="Skip local Web service startup.")]


def register_agent_adapter_commands(
    init_app: typer.Typer,
    uninstall_app: typer.Typer,
    agent_app: typer.Typer,
) -> None:
    _register_init_commands(init_app)
    _register_uninstall_commands(uninstall_app)
    _register_agent_runtime_commands(agent_app)


def _register_init_commands(init_app: typer.Typer) -> None:
    @init_app.command("codex")
    def init_codex(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the Codex project entry for task-judgment first use.

        Then return to Codex with the task goal, fake-done risk, and required evidence.
        Run /loopora-gen, review the READY Loop preview, and run /loopora-loop in the same Agent session.
        """
        _install_adapter("codex", workdir=workdir, json_output=json_output)

    @init_app.command("claude")
    def init_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the Claude Code project entry for task-judgment first use.

        Then return to Claude Code with the task goal, fake-done risk, and required evidence.
        Run /loopora-gen, review the READY Loop preview, and run /loopora-loop in the same Agent session.
        """
        _install_adapter("claude", workdir=workdir, json_output=json_output)

    @init_app.command("opencode")
    def init_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Install or update the OpenCode project entry for task-judgment first use.

        Then return to OpenCode with the task goal, fake-done risk, and required evidence.
        Run /loopora-gen, review the READY Loop preview, and run /loopora-loop in the same Agent session.
        """
        _install_adapter("opencode", workdir=workdir, json_output=json_output)


def _install_adapter(adapter: str, *, workdir: Path, json_output: bool) -> None:
    try:
        result = get_service().install_agent_adapter(adapter, workdir=workdir)
        _print_adapter_mutation_result(result, action="installed", json_output=json_output)
    except LooporaConflictError as exc:
        _handle_adapter_install_conflict(adapter, workdir=workdir, exc=exc)
    except LooporaError as exc:
        handle_error(exc)


def _register_uninstall_commands(uninstall_app: typer.Typer) -> None:
    @uninstall_app.command("codex")
    def uninstall_codex(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove the Loopora-managed Codex project entry."""
        _uninstall_adapter("codex", workdir=workdir, json_output=json_output)

    @uninstall_app.command("claude")
    def uninstall_claude(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove the Loopora-managed Claude Code project entry."""
        _uninstall_adapter("claude", workdir=workdir, json_output=json_output)

    @uninstall_app.command("opencode")
    def uninstall_opencode(workdir: AdapterWorkdirOption = Path("."), json_output: JsonOutputOption = False) -> None:
        """Remove the Loopora-managed OpenCode project entry."""
        _uninstall_adapter("opencode", workdir=workdir, json_output=json_output)


def _uninstall_adapter(adapter: str, *, workdir: Path, json_output: bool) -> None:
    try:
        result = get_service().uninstall_agent_adapter(adapter, workdir=workdir)
        _print_adapter_mutation_result(result, action="uninstalled", json_output=json_output)
    except LooporaError as exc:
        handle_error(exc)


def _register_agent_runtime_commands(agent_app: typer.Typer) -> None:
    _register_agent_runtime_for(agent_app, adapter="codex", help_text="Internal Codex runtime used by Loopora project entries")
    _register_agent_runtime_for(agent_app, adapter="claude", help_text="Internal Claude Code runtime used by Loopora project entries")
    _register_agent_runtime_for(agent_app, adapter="opencode", help_text="Internal OpenCode runtime used by Loopora project entries")


def _register_agent_runtime_for(agent_app: typer.Typer, *, adapter: str, help_text: str) -> None:
    adapter_app = typer.Typer(help=help_text)
    agent_app.add_typer(adapter_app, name=adapter)

    @adapter_app.command("gen")
    def agent_gen(
        workdir: AdapterWorkdirOption = Path("."),
        message: AdapterMessageOption = "",
        bundle_file: BundleFileOption = None,
        context_id: ContextIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Validate a generated Loop plan and return the Loop preview URL."""
        try:
            request = AgentBundleCandidateRequest(
                adapter=adapter,
                workdir=workdir,
                message=message,
                bundle_file=bundle_file,
                context_id=context_id,
                entry_source=_resolved_entry_source(entry_source),
            )
            result = get_service().create_agent_bundle_candidate(request)
            _attach_web_url(result, path_key="preview_path", url_key="preview_url", no_web=no_web)
            _print_agent_gen_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @adapter_app.command("loop")
    def agent_loop(
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Start or reuse the Loopora run associated with the current ready Loop preview."""
        service = None
        try:
            service = get_service()
            result = service.start_agent_loop(
                adapter,
                workdir=workdir,
                context_id=context_id,
                entry_source=_resolved_entry_source(entry_source),
                execute_async=False,
            )
            _spawn_agent_loop_worker_if_needed(service, result)
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_loop_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            if _print_agent_loop_unready_guidance(
                exc,
                service=service,
                adapter=adapter,
                workdir=workdir,
                context_id=context_id,
                no_web=no_web,
                json_output=json_output,
            ):
                raise typer.Exit(code=1) from exc
            handle_error(exc)

    @adapter_app.command("next")
    def agent_next(
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        run_id: RunIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Claim the next Loopora step capsule for the host Agent to execute natively."""
        try:
            result = get_service().claim_agent_native_step(
                AgentNativeStepClaimRequest(
                    adapter=adapter,
                    workdir=workdir,
                    context_id=context_id,
                    run_id=run_id,
                    entry_source=_resolved_entry_source(entry_source),
                )
            )
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_step_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @adapter_app.command("submit")
    def agent_submit(
        result_file: ResultFileOption,
        workdir: AdapterWorkdirOption = Path("."),
        context_id: ContextIdOption = "",
        run_id: RunIdOption = "",
        step_id: StepIdOption = "",
        entry_source: EntrySourceOption = "",
        json_output: JsonOutputOption = False,
        no_web: NoWebOption = False,
    ) -> None:
        """Submit a host Agent's structured step result back to Loopora Core."""
        service = get_service()
        resolved_entry_source = _resolved_entry_source(entry_source)
        result_payload: dict = {}
        host_dispatch: dict = {}
        try:
            result_payload, host_dispatch = _read_result_json(result_file)
            result = service.submit_agent_native_step(
                AgentNativeStepSubmitRequest(
                    adapter=adapter,
                    workdir=workdir,
                    context_id=context_id,
                    run_id=run_id,
                    step_id=step_id,
                    output=result_payload,
                    host_dispatch=host_dispatch,
                    entry_source=resolved_entry_source,
                )
            )
            _attach_web_url(result, path_key="run_path", url_key="run_url", no_web=no_web)
            _print_agent_step_result(result, json_output=json_output)
        except (LooporaError, WorkflowError) as exc:
            _print_agent_submit_repair_guidance(
                exc,
                service=service,
                adapter=adapter,
                context_id=context_id,
                run_id=run_id or str(host_dispatch.get("run_id") or ""),
                entry_source=resolved_entry_source,
                result_file=result_file,
            )
            handle_error(exc)


def _attach_web_url(result: dict, *, path_key: str, url_key: str, no_web: bool) -> None:
    path = str(result.get(path_key) or "")
    if not path:
        return
    if no_web:
        result[url_key] = path
        return
    web = ensure_local_web_service()
    result["web"] = web
    result[url_key] = web_url_for_path(path, web=web)


def _resolved_entry_source(entry_source: str) -> str:
    return str(entry_source or "").strip() or os.environ.get("LOOPORA_AGENT_ENTRY_SOURCE", "").strip()


def _spawn_agent_loop_worker_if_needed(service, result: dict) -> None:
    if result.get("execution_plane") == "agent_native":
        return
    if not result.get("started_new_run"):
        return
    run = result.get("run")
    if not isinstance(run, dict):
        return
    spawned_run = call_spawn_background_worker(service, run)
    result["run"] = spawned_run


def _print_adapter_mutation_result(result: dict, *, action: str, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    label = str(result.get("label") or _adapter_label(str(result.get("adapter") or "")))
    if action == "installed":
        typer.echo(f"{label} Loopora entry is installed")
        typer.echo(f"target project: {result['workdir']}")
        _print_adapter_next_steps(label)
    else:
        typer.echo(f"{label} Loopora entry {action}: {result['status']}")
        typer.echo(f"target project: {result['workdir']}")
    _print_adapter_file_details(result)


def _handle_adapter_install_conflict(adapter: str, *, workdir: Path, exc: LooporaConflictError) -> None:
    label = _adapter_label(adapter)
    root = resolve_adapter_project_root(workdir)
    conflicts = _adapter_conflict_paths(str(exc))
    typer.secho(f"{label} Loopora entry was not installed.", fg=typer.colors.RED, err=True)
    typer.echo(f"target project: {root}", err=True)
    typer.echo(
        "Loopora found existing Agent entry files or host config that it does not own, so it left the project unchanged.",
        err=True,
    )
    if conflicts:
        typer.echo("conflicting files:", err=True)
        for path in conflicts:
            typer.echo(f"- {path}", err=True)
    else:
        typer.echo(f"details: {exc}", err=True)
    typer.echo("recovery:", err=True)
    typer.echo("- Inspect the listed file or config before changing it.", err=True)
    typer.echo("- If it is yours, move or rename it, or choose another target project directory.", err=True)
    typer.echo(f"- Then rerun: loopora init {adapter} --workdir {shlex.quote(str(root))}", err=True)
    raise typer.Exit(code=1)


def _adapter_conflict_paths(message: str) -> list[str]:
    marker = "adapter files:"
    if marker not in message:
        return []
    return [part.strip() for part in message.split(marker, 1)[1].split(",") if part.strip()]


def _print_adapter_file_details(result: dict) -> None:
    managed_files = result.get("managed_files")
    if isinstance(managed_files, list):
        typer.echo("managed files:")
        for item in managed_files:
            if isinstance(item, dict):
                typer.echo(f"- {item.get('path')}: {item.get('state', 'managed')}")
    removed_files = result.get("removed_files")
    if isinstance(removed_files, list) and removed_files:
        typer.echo("removed:")
        for item in removed_files:
            typer.echo(f"- {item}")
    kept_files = result.get("kept_files")
    if isinstance(kept_files, list) and kept_files:
        typer.echo("kept:")
        for item in kept_files:
            if isinstance(item, dict):
                typer.echo(f"- {item.get('path')}: {item.get('reason')}")


def _print_adapter_next_steps(label: str) -> None:
    typer.echo("next:")
    typer.echo(
        f"- Return to {label} in this project with the task goal, fake-done risk, and required evidence."
    )
    typer.echo("- Run /loopora-gen to prepare the Loop preview before starting work.")
    typer.echo("- Review the READY Loop preview, then run /loopora-loop in the same Agent session.")
    typer.echo("- Use Web to observe evidence, gaps, and verdicts while execution stays in the Agent.")


def _print_agent_gen_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    if result.get("ready"):
        typer.echo("Loopora Loop preview is ready")
        typer.echo("next_agent_step: review the preview URL, then run /loopora-loop in this same Agent session")
        _print_agent_ready_review_projection(result.get("ready_review_projection"))
    elif result.get("requires_candidate_repair"):
        typer.echo("Loopora Loop preview needs plan file repair before /loopora-loop")
        if result.get("loopora_fit_contradiction"):
            typer.echo(
                "not_fit: task summary says this looks like one-off, direct-answer, no-new-evidence, "
                "or benchmark/test-harness-only work; "
                "reframe the task with later evidence, handoff, or GateKeeper value before trying a runnable Loop"
            )
        error = _agent_gen_error_summary(result)
        if error:
            typer.echo(f"validation_error: {error}")
        _print_agent_repair_guidance(result)
    elif result.get("requires_web_alignment"):
        typer.echo("Loopora Loop preview needs Web review before /loopora-loop")
        if result.get("loopora_fit_contradiction"):
            typer.echo(
                "not_fit: task summary says this looks like one-off, direct-answer, no-new-evidence, "
                "or benchmark/test-harness-only work; "
                "define later evidence, handoff, or GateKeeper value before generating a runnable Loop"
            )
        _print_agent_web_review_guidance(result)
    else:
        typer.echo(f"Loopora Loop preview status: {result.get('status')}")
    typer.echo(f"session_id: {result['session']['id']}")
    typer.echo(f"preview_url: {result.get('preview_url') or result.get('preview_path')}")
    _print_web_status(result)


def _print_agent_ready_review_projection(projection: object) -> None:
    review = projection if isinstance(projection, dict) else {}
    if not review:
        return
    typer.echo("ready_review:")
    _print_ready_review_items("loopora_fit", review.get("loopora_fit_reasons"))
    _print_ready_review_items("success_surface", review.get("success_surface"))
    _print_ready_review_items("fake_done_risks", review.get("fake_done_risks"))
    _print_ready_review_items("evidence_preferences", review.get("evidence_preferences"))
    _print_ready_review_items("execution_strategy", review.get("execution_strategy"))
    _print_ready_review_items("judgment_tradeoffs", review.get("judgment_tradeoffs"))
    _print_ready_review_items("residual_risk", review.get("residual_risk_policy"))
    _print_ready_review_items("local_governance", review.get("local_governance"))
    coverage = review.get("coverage") if isinstance(review.get("coverage"), dict) else {}
    if coverage:
        typer.echo(
            "coverage_targets: "
            f"{coverage.get('check_count', 0)} checks / "
            f"{coverage.get('target_count', 0)} targets / "
            f"{coverage.get('required_target_count', 0)} required"
        )
    traceability = review.get("traceability") if isinstance(review.get("traceability"), dict) else {}
    if traceability:
        typer.echo(f"judgment_projection: {traceability.get('mapped_count', 0)}/{traceability.get('required_count', 0)} mapped")
    gatekeeper = review.get("gatekeeper") if isinstance(review.get("gatekeeper"), dict) else {}
    if gatekeeper:
        gatekeeper_text = "evidence_refs_required" if gatekeeper.get("requires_evidence_refs") else "configured"
        typer.echo(f"closure_gate: {'GateKeeper' if gatekeeper.get('enabled') else 'run budget'} ({gatekeeper_text})")
    diagnostic_count = _non_bool_int(review.get("diagnostic_count"))
    if diagnostic_count:
        typer.echo(f"review_warnings: {diagnostic_count}")
    typer.echo("review_before_loop: confirm the preview carries these judgments before running /loopora-loop")


def _print_ready_review_items(label: str, values: object) -> None:
    items = [str(item).strip() for item in list(values or []) if str(item).strip()] if isinstance(values, list) else []
    if not items:
        return
    typer.echo(f"{label}:")
    for item in items:
        typer.echo(f"- {_clip(item, 220)}")


def _print_agent_web_review_guidance(result: dict) -> None:
    if result.get("loopora_fit_contradiction"):
        typer.echo("review_status: not runnable; Loopora fit needs to be redefined")
    else:
        typer.echo("review_status: not runnable; no candidate plan file was submitted")
    typer.echo("review_focus:")
    for item in _agent_web_review_focus(result):
        typer.echo(f"- {item}")
    typer.echo(
        "next_review_step: open the preview URL, complete the Web review checklist, "
        "then use /loopora-loop only after the preview is ready"
    )


def _agent_web_review_focus(result: dict) -> list[str]:
    focus = [
        "Loopora fit: explain what future rounds add beyond one Agent pass",
        "Success surface: name the user-visible outcome that must be proven",
        "Fake-done risks: name shallow states that must block closure",
        "Evidence expectations: name the checks, logs, browser paths, audits, or artifacts to trust",
        "Execution strategy and tradeoffs: say what to prove, repair, narrow, expand, or defer first",
        "Residual risk and local governance: name what may remain, who owns it, and which project rules must be read or gated",
    ]
    if result.get("loopora_fit_contradiction"):
        focus[0] = "Loopora fit: define later evidence, handoffs, or GateKeeper value before creating a runnable Loop"
    return focus


def _print_agent_repair_guidance(result: dict) -> None:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    binding = result.get("binding") if isinstance(result.get("binding"), dict) else {}
    source_path = str(binding.get("source_path") or session.get("bundle_path") or "").strip()
    session_bundle_path = str(session.get("bundle_path") or "").strip()
    error = _agent_gen_error_summary(result)
    hints = _validation_repair_hints(error)
    if result.get("loopora_fit_contradiction"):
        typer.echo(
            "not_fit: task summary says this looks like one-off, direct-answer, no-new-evidence, "
            "or benchmark/test-harness-only work; reframe the task with later evidence, handoff, "
            "or GateKeeper value before trying a runnable Loop"
        )
    if source_path:
        typer.echo(f"plan_file_to_repair: {source_path}")
    if session_bundle_path and session_bundle_path != source_path:
        typer.echo(f"preview_plan_copy: {session_bundle_path}")
    if hints:
        typer.echo("repair_focus:")
        for hint in hints:
            typer.echo(f"- {hint}")
    typer.echo("next_repair_step: repair the candidate plan file, rerun /loopora-gen, then use /loopora-loop only after the preview is ready")


def _print_agent_loop_unready_guidance(
    exc: Exception,
    *,
    service,
    adapter: str,
    workdir: Path,
    context_id: str,
    no_web: bool,
    json_output: bool,
) -> bool:
    if service is None:
        return False
    message = str(exc)
    if "/loopora-loop" not in message:
        return False
    try:
        root = resolve_adapter_project_root(workdir)
        binding = read_agent_binding(adapter, root, context_id=context_id)
        session_id = str(binding.get("alignment_session_id") or "").strip()
        session = service.get_alignment_session(session_id) if session_id else {}
    except Exception:  # noqa: BLE001 - error recovery must never replace the primary domain error.
        return False
    if not binding or not session:
        return False
    result = {
        "adapter": adapter,
        "workdir": str(root),
        "ready": False,
        "status": session.get("status"),
        "requires_web_alignment": binding.get("requires_web_alignment") is True,
        "requires_candidate_repair": binding.get("requires_candidate_repair") is True,
        "loopora_fit_contradiction": binding.get("loopora_fit_contradiction") is True,
        "session": session,
        "binding": binding,
        "preview_path": str(binding.get("preview_path") or f"/loops/new/bundle?alignment_session_id={session_id}"),
    }
    _attach_web_url(result, path_key="preview_path", url_key="preview_url", no_web=no_web)
    if result["requires_candidate_repair"]:
        result["loop_recovery"] = "repair_candidate_plan_file"
    elif result["requires_web_alignment"]:
        result["loop_recovery"] = "finish_web_review"
    else:
        result["loop_recovery"] = "preview_not_ready"
    if json_output:
        echo_json(result)
        return True
    if result["requires_candidate_repair"]:
        typer.echo("loop_recovery: repair the current plan file before /loopora-loop can start")
        _print_agent_repair_guidance(result)
    elif result["requires_web_alignment"]:
        typer.echo("loop_recovery: finish the current Web review before /loopora-loop can start")
        _print_agent_web_review_guidance(result)
    else:
        typer.echo("loop_recovery: the current preview is not ready; return to /loopora-gen or Web review before /loopora-loop")
    typer.echo(f"session_id: {session_id}")
    typer.echo(f"preview_url: {result.get('preview_url') or result.get('preview_path')}")
    _print_web_status(result)
    return True


def _validation_repair_hints(error: str) -> list[str]:
    text = str(error or "")
    hints: list[str] = []
    if "spec Task must describe the concrete user-facing task" in text:
        hints.append("make # Task name the concrete user-facing outcome, not only internal governance language")
    if "must follow Chinese user language" in text:
        hints.append("keep user-facing plan names, spec prose, role names, and posture notes in the user's language")
    if "host Agent task summary" in text or "project the host Agent task summary" in text:
        hints.append("project the task objects from --message into spec, roles, workflow intent, and evidence rules")
    if "evidence preferences" in text or "explicit host Agent evidence" in text:
        hints.append("compile required evidence modes into runnable surfaces, not only the CLI summary")
    if "Loopora fit" in text or "one-off" in text or "no-new-evidence" in text:
        hints.append("explain what later rounds add: new evidence, handoffs, GateKeeper judgment, or residual-risk tracking")
    deduped: list[str] = []
    for hint in hints:
        if hint not in deduped:
            deduped.append(hint)
    return deduped[:5]


def _agent_gen_error_summary(result: dict) -> str:
    session = result.get("session") if isinstance(result.get("session"), dict) else {}
    validation = session.get("validation") if isinstance(session.get("validation"), dict) else {}
    return str(session.get("error_message") or validation.get("error") or "").strip()


def _print_agent_loop_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('run_status') or run.get('status')}")
    print_run_contract_summary(run)
    task_verdict = run.get("task_verdict") or run.get("task_verdict_json")
    if result.get("complete"):
        print_task_verdict(task_verdict)
        _print_terminal_task_next_action(task_verdict, result.get("task_next_action"))
        _print_agent_native_terminal_state(task_verdict)
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    _print_web_status(result)
    next_step = result.get("next_step") if isinstance(result.get("next_step"), dict) else {}
    if next_step:
        _print_agent_current_step(next_step)


def _print_agent_step_result(result: dict, *, json_output: bool) -> None:
    if json_output:
        echo_json(result)
        return
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    typer.echo(f"Loopora run: {run.get('id')}")
    typer.echo(f"run_status: {run.get('run_status') or run.get('status')}")
    print_run_contract_summary(run)
    task_verdict = run.get("task_verdict") or run.get("task_verdict_json")
    if result.get("complete"):
        print_task_verdict(task_verdict)
        _print_terminal_task_next_action(task_verdict, result.get("task_next_action"))
    typer.echo(f"run_url: {result.get('run_url') or result.get('run_path')}")
    _print_web_status(result)
    next_step = result.get("next_step") if isinstance(result.get("next_step"), dict) else {}
    if result.get("complete"):
        _print_agent_native_terminal_state(task_verdict)
    elif next_step:
        _print_agent_current_step(next_step)


def _task_verdict_status(task_verdict: object) -> str:
    if isinstance(task_verdict, dict):
        return str(task_verdict.get("status") or "").strip()
    return ""


def _print_agent_native_terminal_state(task_verdict: object) -> None:
    status = _task_verdict_status(task_verdict)
    if status in PASSING_TASK_VERDICT_STATUSES:
        typer.echo("agent_native: complete")
        return
    if not status:
        status = "not_evaluated"
    typer.echo("agent_native: lifecycle_closed_task_unproven")
    typer.echo(f"agent_native_task_verdict: {status}")


def _print_terminal_task_next_action(task_verdict: object, task_next_action: object = None) -> None:
    action = task_next_action if isinstance(task_next_action, dict) else {}
    status = _task_verdict_status(task_verdict)
    summary = ""
    if isinstance(task_verdict, dict):
        summary = str(task_verdict.get("summary") or "").strip()
    if status in PASSING_TASK_VERDICT_STATUSES:
        return
    if not status:
        status = "not_evaluated"
    guidance = str(action.get("guidance") or "").strip() if action else ""
    typer.echo(
        "task_next_action: "
        + (
            guidance
            if guidance
            else "run lifecycle is complete but the task is not proven; run /loopora-loop again in this Agent session to start the next evidence pass"
        )
    )
    typer.echo(f"next_loop_command: {(action.get('next_loop_command') or '/loopora-loop')!s}")
    plan_action = str(action.get("plan_action") or "").strip()
    if plan_action == "open_run_url_improve_with_evidence_if_loop_needs_adjustment":
        typer.echo("next_plan_action: open run_url and use Improve plan with evidence if the Loop itself needs adjustment")
    elif plan_action:
        typer.echo(f"next_plan_action: {plan_action}")
    else:
        typer.echo("next_plan_action: open run_url and use Improve plan with evidence if the Loop itself needs adjustment")
    action_summary = str(action.get("task_verdict_summary") or "").strip()
    if action_summary:
        summary = action_summary
    if summary:
        typer.echo(f"next_evidence_focus: {_clip(summary, 220)}")


def _print_agent_current_step(next_step: dict) -> None:
    role = next_step.get("role") if isinstance(next_step.get("role"), dict) else {}
    role_dispatch = next_step.get("role_dispatch") if isinstance(next_step.get("role_dispatch"), dict) else {}
    action_policy = next_step.get("action_policy") if isinstance(next_step.get("action_policy"), dict) else {}
    submit_hint = next_step.get("submit_hint") if isinstance(next_step.get("submit_hint"), dict) else {}
    target_agent = str(role_dispatch.get("target_agent") or "").strip()
    typer.echo(f"next_step_id: {next_step.get('step_id')}")
    typer.echo(f"next_role: {role.get('name') or role.get('id')}")
    if target_agent:
        typer.echo(f"next_target_agent: {target_agent}")
    _print_agent_continuation(next_step.get("continuation"))
    action_summary = _action_policy_summary(action_policy)
    if action_summary:
        typer.echo(f"next_action_policy: {action_summary}")
    coverage_summary = _required_coverage_summary(next_step.get("required_coverage"))
    if coverage_summary:
        typer.echo(f"required_coverage: {coverage_summary}")
    _print_top_coverage_gaps(next_step.get("required_coverage"))
    _print_agent_current_step_paths(next_step, submit_hint)
    _print_agent_current_step_submit_hint(submit_hint)


def _print_agent_current_step_paths(next_step: dict, submit_hint: dict) -> None:
    context_path = str(next_step.get("context_absolute_path") or next_step.get("context_path") or "").strip()
    if context_path:
        typer.echo(f"next_context_path: {context_path}")
    capsule_path = str(next_step.get("capsule_absolute_path") or next_step.get("capsule_path") or "").strip()
    if capsule_path:
        typer.echo(f"next_capsule_path: {capsule_path}")
    known_evidence_count = _non_bool_int(next_step.get("known_evidence_count"))
    if known_evidence_count is not None:
        typer.echo(f"known_evidence_count: {known_evidence_count}")
    result_template_path = str(submit_hint.get("result_template_absolute_path") or submit_hint.get("result_template_path") or "").strip()
    if result_template_path:
        typer.echo(f"result_template_path: {result_template_path}")


def _print_agent_current_step_submit_hint(submit_hint: dict) -> None:
    result_template_path = str(submit_hint.get("result_template_absolute_path") or submit_hint.get("result_template_path") or "").strip()
    result_contract = str(submit_hint.get("result_file_contract") or "").strip()
    if result_contract:
        typer.echo(f"result_template_contract: {result_contract}")
    if result_template_path or result_contract:
        typer.echo("result_template_fill: open the template, replace null placeholders in result, keep loopora_host_dispatch, then submit the filled copy")
    result_outbox_dir = str(submit_hint.get("result_outbox_absolute_dir") or submit_hint.get("result_outbox_dir") or "").strip()
    if result_outbox_dir:
        typer.echo(f"result_outbox_dir: {result_outbox_dir}")
    submit_command = str(submit_hint.get("command") or "").strip()
    if submit_command:
        typer.echo(f"submit_hint: {submit_command}")


def _print_agent_continuation(continuation: object) -> None:
    if not isinstance(continuation, dict) or continuation.get("active") is not True:
        return
    verdict = continuation.get("previous_task_verdict") if isinstance(continuation.get("previous_task_verdict"), dict) else {}
    coverage = continuation.get("coverage") if isinstance(continuation.get("coverage"), dict) else {}
    previous_run_id = str(continuation.get("previous_run_id") or "").strip()
    if previous_run_id:
        typer.echo(f"continuation_previous_run: {previous_run_id}")
    status = str(verdict.get("status") or "").strip()
    if status:
        typer.echo(f"continuation_task_verdict: {status}")
    summary = str(verdict.get("summary") or "").strip()
    if summary:
        typer.echo(f"continuation_task_verdict_summary: {_clip(summary, 200)}")
    _print_continuation_coverage(coverage)
    _print_continuation_focus_items("blocking", continuation.get("focus_blocking"))
    _print_continuation_focus_items("unproven", continuation.get("focus_unproven"))
    _print_continuation_focus_items("weak", continuation.get("focus_weak"))
    _print_continuation_next_focus(continuation.get("next_focus"))


def _print_continuation_coverage(coverage: dict) -> None:
    missing = coverage.get("missing_check_count")
    covered = coverage.get("covered_check_count")
    if covered is not None or missing is not None:
        typer.echo(f"continuation_required_coverage: {covered or 0} covered / {missing or 0} missing")
    target_count = coverage.get("target_count")
    covered_targets = coverage.get("covered_target_count")
    weak_targets = coverage.get("weak_target_count")
    missing_targets = coverage.get("missing_target_count")
    blocked_targets = coverage.get("blocked_target_count")
    if target_count:
        target_bits = [f"{covered_targets or 0} covered"]
        if weak_targets:
            target_bits.append(f"{weak_targets} weak")
        if missing_targets:
            target_bits.append(f"{missing_targets} missing")
        if blocked_targets:
            target_bits.append(f"{blocked_targets} blocked")
        typer.echo(f"continuation_coverage_targets: {target_count} total ({' / '.join(target_bits)})")


def _print_continuation_next_focus(items: object) -> None:
    next_focus = [str(item).strip() for item in list(items or []) if str(item).strip()]
    if next_focus:
        typer.echo("continuation_next_focus:")
        for item in next_focus[:5]:
            typer.echo(f"- {item}")


def _print_continuation_focus_items(label: str, items: object) -> None:
    focus_items = [str(item).strip() for item in list(items or []) if str(item).strip()]
    if not focus_items:
        return
    typer.echo(f"continuation_{label}:")
    for item in focus_items[:4]:
        typer.echo(f"- {_clip(item, 180)}")


def _action_policy_summary(action_policy: dict) -> str:
    workspace = str(action_policy.get("workspace") or "").strip()
    bits = [workspace] if workspace else []
    if action_policy.get("can_block") is True:
        bits.append("can_block")
    if action_policy.get("can_finish_run") is True:
        bits.append("can_finish_run")
    return ", ".join(bits)


def _required_coverage_summary(required_coverage: object) -> str:
    if not isinstance(required_coverage, dict):
        return ""
    status = str(required_coverage.get("status") or "pending").strip()
    covered = _non_bool_int(required_coverage.get("covered_check_count"))
    missing = _non_bool_int(required_coverage.get("missing_check_count"))
    target_count = _non_bool_int(required_coverage.get("target_count"))
    covered_targets = _non_bool_int(required_coverage.get("covered_target_count"))
    weak_targets = _non_bool_int(required_coverage.get("weak_target_count"))
    missing_targets = _non_bool_int(required_coverage.get("missing_target_count"))
    blocked_targets = _non_bool_int(required_coverage.get("blocked_target_count"))
    bits = []
    if covered is not None or missing is not None:
        bits.append(f"required checks {covered or 0} covered / {missing or 0} missing")
    if target_count:
        target_bits = [f"{covered_targets or 0}/{target_count} targets"]
        if weak_targets:
            target_bits.append(f"{weak_targets} weak")
        if missing_targets:
            target_bits.append(f"{missing_targets} missing")
        if blocked_targets:
            target_bits.append(f"{blocked_targets} blocked")
        bits.append(" / ".join(target_bits))
    if not bits:
        return status
    return f"{status}; {', '.join(bits)}"


def _print_top_coverage_gaps(required_coverage: object) -> None:
    if not isinstance(required_coverage, dict):
        return
    gaps = required_coverage.get("top_gaps")
    if not isinstance(gaps, list):
        return
    visible_gaps = [gap for gap in gaps if isinstance(gap, dict)][:3]
    if not visible_gaps:
        return
    typer.echo("top_coverage_gaps:")
    for gap in visible_gaps:
        target_id = str(gap.get("target_id") or gap.get("id") or "").strip()
        source_section = str(gap.get("source_section") or "").strip()
        text = _clip(str(gap.get("text") or gap.get("reason") or "").strip(), 180)
        source_prefix = f"[{source_section}] " if source_section else ""
        if target_id and text:
            typer.echo(f"- {target_id}: {source_prefix}{text}")
        elif target_id:
            typer.echo(f"- {target_id}: {source_prefix}")
        elif text:
            typer.echo(f"- {source_prefix}{text}")


def _non_bool_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1].rstrip()}…"


def _print_agent_submit_repair_guidance(
    exc: Exception,
    *,
    service,
    adapter: str,
    context_id: str,
    run_id: str,
    entry_source: str,
    result_file: Path,
) -> None:
    error = str(exc)
    if not _agent_submit_error_is_repairable(error):
        return
    active_step = _active_agent_native_step(service, run_id=run_id)
    typer.echo("submit_repair: result JSON needs repair before this Loopora step can advance", err=True)
    typer.echo(f"result_file_to_repair: {result_file}", err=True)
    if active_step:
        role = active_step.get("role") if isinstance(active_step.get("role"), dict) else {}
        dispatch = active_step.get("role_dispatch") if isinstance(active_step.get("role_dispatch"), dict) else {}
        target_agent = str(dispatch.get("target_agent") or active_step.get("target_agent") or "").strip()
        typer.echo(f"active_step_id: {active_step.get('step_id')}", err=True)
        typer.echo(f"active_role: {role.get('name') or role.get('id')}", err=True)
        if target_agent:
            typer.echo(f"active_target_agent: {target_agent}", err=True)
        context_path = str(active_step.get("context_absolute_path") or active_step.get("context_path") or "").strip()
        if context_path:
            typer.echo(f"active_context_path: {context_path}", err=True)
    focus = _agent_submit_repair_focus(error, active_step)
    if focus:
        typer.echo("repair_focus:", err=True)
        for item in focus:
            typer.echo(f"- {item}", err=True)
    typer.echo(
        "next_repair_step: edit the result JSON, preserve loopora_host_dispatch, rerun agent next --json if you need the active output_schema, then submit again",
        err=True,
    )
    rerun = _agent_next_command_hint(adapter=adapter, context_id=context_id, run_id=run_id, entry_source=entry_source)
    if rerun:
        typer.echo(f"schema_lookup: {rerun}", err=True)


def _agent_submit_error_is_repairable(error: str) -> bool:
    markers = (
        "result file is not valid JSON",
        "result file must contain one JSON object",
        "agent-native result does not match output_schema",
        "result wrapper must contain",
        "loopora_host_dispatch",
        "evidence_refs_unknown",
        "coverage_results_unknown_target_id",
        "read-only step cannot claim workspace artifact fields",
        "submitted step_id does not match",
    )
    return any(marker in error for marker in markers)


def _active_agent_native_step(service, *, run_id: str) -> dict:
    if not run_id:
        return {}
    try:
        run = service.get_run(run_id)
    except LooporaError:
        return {}
    runs_dir = str(run.get("runs_dir") or "").strip() if isinstance(run, dict) else ""
    if not runs_dir:
        return {}
    try:
        state = json.loads((Path(runs_dir) / "agent_native" / "state.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    active = state.get("active_step") if isinstance(state.get("active_step"), dict) else {}
    capsule = active.get("capsule") if isinstance(active.get("capsule"), dict) else {}
    return capsule if isinstance(capsule, dict) else {}


def _agent_submit_repair_focus(error: str, active_step: dict) -> list[str]:
    focus: list[str] = []
    if "result file is not valid JSON" in error:
        focus.append("fix JSON syntax; the file must be one wrapper object with loopora_host_dispatch and result")
    if "result file must contain one JSON object" in error:
        focus.append("replace the file with one JSON object; do not submit an array, string, or multiple documents")
    schema = active_step.get("output_schema") if isinstance(active_step.get("output_schema"), dict) else {}
    schema_hint = _output_schema_error_hint(error, schema)
    if schema_hint:
        focus.append(schema_hint)
    if "result wrapper must contain" in error:
        focus.append("use one wrapper JSON object with loopora_host_dispatch and result")
    focus.extend(_host_dispatch_repair_focus(error, active_step))
    focus.extend(_evidence_ref_repair_focus(error, active_step))
    focus.extend(_coverage_target_repair_focus(error, active_step))
    if "read-only step cannot claim workspace artifact fields" in error:
        focus.append("remove workspace artifact fields such as changed_files/proof_files from this read_only role result")
    if "submitted step_id does not match" in error:
        focus.append("submit the active step_id exactly; rerun agent next --json if the run advanced or the result file is stale")
    if not focus and "output_schema" in error:
        focus.append("make result match next_step.output_schema exactly; do not add fields outside the schema")
    return list(dict.fromkeys(focus))[:6]


def _host_dispatch_repair_focus(error: str, active_step: dict) -> list[str]:
    if "loopora_host_dispatch" not in error:
        return []
    role_dispatch = active_step.get("role_dispatch") if isinstance(active_step.get("role_dispatch"), dict) else {}
    target_agent = str(role_dispatch.get("target_agent") or "").strip()
    if target_agent:
        return [f"set loopora_host_dispatch.target_agent and actual_agent to {target_agent}, inline to false, and keep run_id/step_id exact"]
    return ["preserve loopora_host_dispatch with exact adapter, run_id, step_id, target_agent, actual_agent, dispatch_mode, and inline=false"]


def _evidence_ref_repair_focus(error: str, active_step: dict) -> list[str]:
    if "evidence_refs_unknown" not in error:
        return []
    known = [str(item) for item in list(active_step.get("known_evidence_ids") or []) if str(item).strip()]
    if known:
        return ["use only known_evidence_ids in evidence_refs: " + ", ".join(known[:6])]
    return ["remove invented evidence_refs; evidence_refs must be exact IDs from the active capsule"]


def _coverage_target_repair_focus(error: str, active_step: dict) -> list[str]:
    if "coverage_results_unknown_target_id" not in error:
        return []
    target_ids = _active_step_coverage_target_ids(active_step)
    if target_ids:
        return ["use only frozen coverage target IDs: " + ", ".join(target_ids[:8])]
    return ["coverage_results.target_id must come from the active judgment_contract coverage targets"]


_SCHEMA_TYPE_ERROR_RE = re.compile(r"(?P<path>\$(?:\.[A-Za-z0-9_-]+|\[\d+\])*) expected (?P<expected>[A-Za-z_]+), got (?P<actual>[A-Za-z_]+)")
_SCHEMA_REQUIRED_ERROR_RE = re.compile(r"(?P<path>\$(?:\.[A-Za-z0-9_-]+|\[\d+\])*) is required")
_SCHEMA_EXTRA_ERROR_RE = re.compile(r"(?P<path>\$(?:\.[A-Za-z0-9_-]+|\[\d+\])*) is not allowed by output_schema")
_SCHEMA_ENUM_ERROR_RE = re.compile(r"(?P<path>\$(?:\.[A-Za-z0-9_-]+|\[\d+\])*) must be one of (?P<values>\[[^\]]+\])")


def _output_schema_error_hint(error: str, schema: dict) -> str:
    if match := _SCHEMA_TYPE_ERROR_RE.search(error):
        path = match.group("path")
        expected = match.group("expected")
        node = _schema_node_at_path(schema, path)
        shape = _schema_shape_hint(node)
        if shape:
            return f"{path} must be {shape}"
        return f"{path} must be {expected}; rewrite that value inside result"
    if match := _SCHEMA_REQUIRED_ERROR_RE.search(error):
        return f"add missing result field {match.group('path').removeprefix('$.')}"
    if match := _SCHEMA_EXTRA_ERROR_RE.search(error):
        return f"remove non-schema result field {match.group('path').removeprefix('$.')}"
    if match := _SCHEMA_ENUM_ERROR_RE.search(error):
        return f"{match.group('path')} must use one allowed value: {match.group('values')}"
    return ""


def _schema_node_at_path(schema: dict, path: str) -> dict:
    node: object = schema
    for segment in _schema_path_segments(path):
        if not isinstance(node, dict):
            return {}
        if isinstance(segment, int):
            node = node.get("items")
        else:
            properties = node.get("properties") if isinstance(node.get("properties"), dict) else {}
            node = properties.get(segment)
    return node if isinstance(node, dict) else {}


def _schema_path_segments(path: str) -> list[str | int]:
    segments: list[str | int] = []
    for match in re.finditer(r"\.([A-Za-z0-9_-]+)|\[(\d+)\]", path):
        if match.group(1) is not None:
            segments.append(match.group(1))
        else:
            segments.append(int(match.group(2)))
    return segments


def _schema_shape_hint(node: dict) -> str:
    schema_type = str(node.get("type") or "").strip()
    if schema_type == "object":
        required = [str(item) for item in list(node.get("required") or []) if str(item).strip()]
        if required:
            return "an object with required fields: " + ", ".join(required)
        return "an object"
    if schema_type == "array":
        item_shape = _schema_shape_hint(node.get("items") if isinstance(node.get("items"), dict) else {})
        return f"an array of {item_shape}" if item_shape else "an array"
    if schema_type:
        return schema_type
    return ""


def _active_step_coverage_target_ids(active_step: dict) -> list[str]:
    judgment_contract = active_step.get("judgment_contract") if isinstance(active_step.get("judgment_contract"), dict) else {}
    ids: list[str] = []
    for item in list(judgment_contract.get("coverage_targets") or []):
        if isinstance(item, dict):
            target_id = str(item.get("id") or item.get("target_id") or "").strip()
            if target_id:
                ids.append(target_id)
    return list(dict.fromkeys(ids))


def _agent_next_command_hint(*, adapter: str, context_id: str, run_id: str, entry_source: str = "") -> str:
    bits = [f"loopora agent {adapter} next", '--workdir "$PWD"']
    if run_id:
        bits.append(f"--run-id {run_id}")
    elif context_id:
        bits.append(f"--context-id {context_id}")
    bits.append("--json")
    normalized_entry_source = str(entry_source or "").strip()
    if normalized_entry_source:
        bits.extend(["--entry-source", shlex.quote(normalized_entry_source)])
    command = " ".join(bits)
    if normalized_entry_source:
        command = f"LOOPORA_AGENT_ENTRY_SOURCE={shlex.quote(normalized_entry_source)} {command}"
    return command


def _print_web_status(result: dict) -> None:
    web = result.get("web")
    if not isinstance(web, dict):
        return
    base_url = str(web.get("base_url") or "").strip()
    if not base_url:
        return
    if web.get("started"):
        typer.echo(f"web: started {base_url}")
    elif web.get("reused"):
        typer.echo(f"web: reused {base_url}")
    else:
        typer.echo(f"web: {base_url}")
    warning = str(web.get("warning") or "").strip()
    if warning:
        typer.echo(f"web_warning: {warning}")


def _read_result_json(path: Path) -> tuple[dict, dict]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LooporaError(f"result file is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise LooporaError("result file must contain one JSON object")
    if "loopora_host_dispatch" in payload or "result" in payload:
        host_dispatch = payload.get("loopora_host_dispatch")
        result = payload.get("result")
        if not isinstance(host_dispatch, dict):
            raise LooporaError("result wrapper must contain loopora_host_dispatch object")
        if not isinstance(result, dict):
            raise LooporaError("result wrapper must contain result object")
        return result, host_dispatch
    return payload, {}


def _adapter_label(adapter: str) -> str:
    return {
        "codex": "Codex",
        "claude": "Claude Code",
        "opencode": "OpenCode",
    }.get(adapter, adapter or "Agent")
