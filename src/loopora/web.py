from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from loopora.branding import (
    APP_AUTH_COOKIE,
    APP_AUTH_HEADER,
    APP_NAME,
    FILE_ROOT_QUERY_PATTERN,
    LEGACY_APP_AUTH_COOKIE,
    LEGACY_APP_AUTH_HEADER,
    LEGACY_SPEC_SKILL_SLUG,
    SPEC_SKILL_SLUG,
    normalize_file_root,
    strip_run_summary_title,
)
from loopora.providers import executor_profile, list_executor_profiles
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.markdown_tools import decode_text_bytes, looks_binary, normalize_markdown_text, render_safe_markdown_html
from loopora.run_artifacts import list_run_artifacts as _list_run_artifacts
from loopora.settings import load_recent_workdirs
from loopora.skills import build_spec_skill_bundle_archive, install_spec_skill, list_spec_skill_targets, load_spec_skill_bundle
from loopora.service import LooporaError, create_service, normalize_role_models
from loopora.specs import SpecError, compile_markdown_spec, init_spec_file, read_and_compile
from loopora.system_dialogs import SystemDialogError, pick_directory, pick_file, pick_save_file, reveal_path
from loopora.workflows import (
    ARCHETYPES,
    WorkflowError,
    available_prompt_templates,
    build_preset_workflow,
    builtin_prompt_markdown,
    builtin_prompt_markdown_by_locale,
    default_role_execution_settings,
    display_name_for_archetype,
    normalize_role_display_name,
    normalize_prompt_locale,
    normalize_workflow,
    preset_names,
    resolve_prompt_files,
    workflow_preset_copy,
    workflow_preset_options,
)

logger = get_logger(__name__)

AUTH_COOKIE_NAME = APP_AUTH_COOKIE

DEFAULT_LOOP_FORM = {
    "name": "",
    "workdir": "",
    "spec_path": "",
    "orchestration_id": "builtin:build_first",
    "completion_mode": "gatekeeper",
    "iteration_interval_seconds": 0,
    "max_iters": 8,
    "max_role_retries": 2,
    "delta_threshold": 0.005,
    "trigger_window": 4,
    "regression_window": 2,
    "start_immediately": True,
}

DEFAULT_ORCHESTRATION_FORM = {
    "name": "",
    "description": "",
    "workflow_preset": "",
    "workflow_json": "",
    "prompt_files_json": "",
}

DEFAULT_ROLE_DEFINITION_FORM = {
    "name": "",
    "description": "",
    "archetype": "builder",
    "prompt_ref": "builder.md",
    "prompt_markdown": builtin_prompt_markdown("builder.md", locale="en"),
    **default_role_execution_settings(),
}

TIMELINE_EVENT_TYPES = {
    "run_started",
    "checks_resolved",
    "step_context_prepared",
    "role_execution_summary",
    "step_handoff_written",
    "iteration_summary_written",
    "role_degraded",
    "challenger_done",
    "iteration_wait_started",
    "iteration_wait_finished",
    "workspace_guard_triggered",
    "stop_requested",
    "run_aborted",
    "run_finished",
}

PROGRESS_EVENT_TYPES = {
    "checks_resolved",
    "role_started",
    "role_request_prepared",
    "step_context_prepared",
    "role_execution_summary",
    "step_handoff_written",
    "run_aborted",
    "run_finished",
}


def build_app(service=None, *, bind_host: str = "127.0.0.1", bind_port: int = 8742, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title=APP_NAME)
    app.state.service = service or create_service()
    access_state = _build_access_state(bind_host=bind_host, bind_port=bind_port, auth_token=auth_token)
    app.state.access_state = access_state
    package_root = Path(__file__).parent
    static_root = package_root / "static"

    def template_context(request: Request) -> dict[str, str]:
        locale = _preferred_request_locale(request)
        return {
            "page_locale": locale,
            "page_lang": "zh-CN" if locale == "zh" else "en",
        }

    templates = Jinja2Templates(
        directory=str(package_root / "templates"),
        context_processors=[template_context],
    )
    templates.env.auto_reload = True
    app.mount("/static", StaticFiles(directory=str(package_root / "static")), name="static")
    app.mount("/logo", StaticFiles(directory=str(package_root / "assets" / "logo")), name="logo")

    def static_asset_url(path: str) -> str:
        normalized = path.lstrip("/")
        asset_path = static_root / normalized
        try:
            version = asset_path.stat().st_mtime_ns
        except OSError:
            version = time.time_ns()
        return f"/static/{normalized}?v={version}"

    templates.env.globals["static_asset_url"] = static_asset_url
    log_event(
        logger,
        logging.INFO,
        "web.app.built",
        "Built web application instance",
        bind_host=bind_host,
        bind_port=bind_port,
        auth_enabled=bool(auth_token),
    )

    def svc():
        return app.state.service

    def json_error(message: str, status_code: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        start_time = time.perf_counter()
        expected_token = access_state["auth_token"]
        if not expected_token:
            try:
                response = await call_next(request)
            except Exception as exc:
                log_exception(
                    logger,
                    "web.request.failed",
                    "HTTP request failed before authentication was required",
                    error=exc,
                    method=request.method,
                    request_path=request.url.path,
                    client_ip=request.client.host if request.client else "",
                )
                raise
            _log_web_response(request, response.status_code, start_time)
            return response

        provided_token = _extract_request_token(request)
        if provided_token != expected_token:
            response = _auth_required_response(request)
            log_event(
                logger,
                logging.WARNING,
                "web.auth.rejected",
                "Rejected request with a missing or invalid auth token",
                method=request.method,
                request_path=request.url.path,
                status_code=response.status_code,
                client_ip=request.client.host if request.client else "",
            )
            _log_web_response(request, response.status_code, start_time)
            return response

        try:
            response = await call_next(request)
        except Exception as exc:
            log_exception(
                logger,
                "web.request.failed",
                "HTTP request failed",
                error=exc,
                method=request.method,
                request_path=request.url.path,
                client_ip=request.client.host if request.client else "",
            )
            raise
        if request.cookies.get(APP_AUTH_COOKIE) != expected_token:
            response.set_cookie(AUTH_COOKIE_NAME, expected_token, httponly=True, samesite="lax")
        _log_web_response(request, response.status_code, start_time)
        return response

    def render_new_loop(
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
    ) -> HTMLResponse:
        form_values = _normalize_loop_form(values)
        return templates.TemplateResponse(
            request,
            "new_loop.html",
            {
                "request": request,
                "form_values": form_values,
                "pristine_loop_form": _normalize_loop_form(None),
                "form_error": form_error,
                "executor_profiles": list_executor_profiles(),
                "orchestrations": svc().list_orchestrations(),
                "recent_workdirs": load_recent_workdirs(),
                "allow_draft_restore": form_error is None and _loop_form_is_pristine(form_values),
                "access_state": access_state,
            },
        )

    def render_orchestrations(request: Request) -> HTMLResponse:
        orchestrations = svc().list_orchestrations()
        custom_orchestrations = [item for item in orchestrations if item.get("source") == "custom"]
        builtin_orchestrations = [item for item in orchestrations if item.get("source") == "builtin"]
        return templates.TemplateResponse(
            request,
            "orchestrations.html",
            {
                "request": request,
                "orchestrations": orchestrations,
                "custom_orchestrations": custom_orchestrations,
                "builtin_orchestrations": builtin_orchestrations,
                "access_state": access_state,
            },
        )

    def render_new_orchestration(
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
        orchestration: Mapping[str, object] | None = None,
    ) -> HTMLResponse:
        current_orchestration = dict(orchestration) if orchestration else None
        if values is None and current_orchestration is not None:
            values = _orchestration_form_values_from_record(current_orchestration)
        is_builtin_template = bool(current_orchestration and current_orchestration.get("source") == "builtin")
        is_editing_custom = bool(current_orchestration and current_orchestration.get("source") == "custom")
        if is_builtin_template and current_orchestration is not None:
            form_values = _normalize_orchestration_form(_orchestration_form_values_from_record(current_orchestration))
        else:
            form_values = _normalize_orchestration_form(values)
        if is_editing_custom:
            page_copy = {
                "title_zh": "修改编排，让后续 loop 继续沿着新的流程走。",
                "title_en": "Refine this orchestration before future loops use the new flow.",
                "body_zh": "这里改的是已经保存的流程编排。你可以调整角色定义的引用关系、步骤顺序和收束规则；角色 prompt 和执行方式请回到“角色定义”页修改。",
                "body_en": "You are editing a saved orchestration. Adjust role-definition snapshots, step order, and completion rules here; return to Role Definitions to change prompts or execution settings.",
                "submit_zh": "保存修改",
                "submit_en": "Save changes",
                "action": f"/orchestrations/{current_orchestration['id']}/edit",
            }
        elif is_builtin_template:
            page_copy = {
                "title_zh": "查看默认编排，先理解 Loopora 推荐的循环结构。",
                "title_en": "Inspect the built-in orchestration to understand Loopora's recommended loop shape.",
                "body_zh": "默认编排是固定的，只用于查看和直接复用，不能在这里修改。若要做自己的版本，请新建一条自定义编排，再按需要调整角色快照、步骤顺序和收束规则。",
                "body_en": "Built-in orchestrations are fixed. You can inspect and reuse them directly here, but not modify them. To make your own version, create a custom orchestration and then adjust role snapshots, step order, and completion rules there.",
                "submit_zh": "新建自定义编排",
                "submit_en": "Create custom orchestration",
                "action": "/orchestrations/new",
            }
        else:
            page_copy = {
                "title_zh": "先把步骤工作台搭起来，再让 loop 去执行。",
                "title_en": "Shape the step workbench first, then let loops execute it.",
                "body_zh": "这里默认从空白编排开始。你可以在步骤工具条里载入起手模板、按角色定义添加步骤、重排步骤和检查循环实例图；角色 prompt 与执行配置继续在“角色定义”页维护。",
                "body_en": "This editor starts blank by default. Use the step toolbar to load a starter template, add steps from role definitions, reorder steps, and inspect the loop map. Prompts and execution settings still live in Role Definitions.",
                "submit_zh": "保存编排",
                "submit_en": "Save orchestration",
                "action": "/orchestrations/new",
            }
        return templates.TemplateResponse(
            request,
            "new_orchestration.html",
            {
                "request": request,
                "form_values": form_values,
                "form_error": form_error,
                "workflow_preset_options": workflow_preset_options(),
                "workflow_preset_bundles": {
                    preset_name: {
                        "copy": workflow_preset_copy(preset_name),
                        "workflow": build_preset_workflow(preset_name),
                        "prompt_files": resolve_prompt_files(build_preset_workflow(preset_name)),
                    }
                    for preset_name in preset_names()
                },
                "prompt_templates": available_prompt_templates(),
                "role_definitions": svc().list_role_definitions(),
                "page_copy": page_copy,
                "current_orchestration": current_orchestration,
                "orchestration_locked": is_builtin_template,
                "orchestration_create_from_preset_href": (
                    f"/orchestrations/new?workflow_preset={form_values.get('workflow_preset', 'build_first')}"
                    if is_builtin_template
                    else ""
                ),
                "access_state": access_state,
            },
        )

    def render_role_definitions(request: Request) -> HTMLResponse:
        role_definitions = [_decorate_role_definition_overview(role_definition) for role_definition in svc().list_role_definitions()]
        builtin_role_templates = [item for item in role_definitions if item["source"] == "builtin"]
        custom_role_definitions = [item for item in role_definitions if item["source"] == "custom"]
        return templates.TemplateResponse(
            request,
            "role_definitions.html",
            {
                "request": request,
                "role_definitions": role_definitions,
                "builtin_role_templates": builtin_role_templates,
                "custom_role_definitions": custom_role_definitions,
                "access_state": access_state,
            },
        )

    def render_new_role_definition(
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
        role_definition: Mapping[str, object] | None = None,
    ) -> HTMLResponse:
        locale = _preferred_request_locale(request)
        incoming_values = values
        current_role_definition = dict(role_definition) if role_definition else None
        if values is None and current_role_definition is not None:
            values = _role_definition_form_values_from_record(current_role_definition, locale=locale)
        is_builtin_template = bool(current_role_definition and current_role_definition.get("source") == "builtin")
        is_editing_custom = bool(current_role_definition and current_role_definition.get("source") == "custom")
        role_template_locked = current_role_definition is not None
        if is_editing_custom:
            page_copy = {
                "title_zh": "修改这条角色定义，让后续编排都能复用新的版本。",
                "title_en": "Refine this role definition so future orchestrations can reuse it.",
                "body_zh": "这里改的是已经保存的角色定义。保存后，新的编排会继续引用它；已有编排里的角色快照不会被回写。",
                "body_en": "You are editing a saved role definition. Future orchestrations keep reusing it, while existing orchestrations keep their frozen role snapshots.",
                "submit_zh": "保存修改",
                "submit_en": "Save changes",
                "action": f"/roles/{current_role_definition['id']}/edit",
            }
        elif is_builtin_template:
            page_copy = {
                "title_zh": "从内置模板出发，打磨成你团队自己的角色版本。",
                "title_en": "Start from the built-in template, then tailor it into your team’s own role.",
                "body_zh": "这里保留的是模板的核心角色身份，你可以修改名字、执行工具、模型和 prompt；保存时会派生出一条新的自定义角色定义。",
                "body_en": "The core role identity stays fixed here. Adjust the name, executor, model, and prompt, then save a new custom role definition derived from this template.",
                "submit_zh": "保存为新角色",
                "submit_en": "Save as new role",
                "action": "/roles/new",
            }
        else:
            page_copy = {
                "title_zh": "先把角色定义好，后面的编排就能直接拿来用。",
                "title_en": "Define the role once, then let orchestrations reuse it directly.",
                "body_zh": "角色定义保存的是角色名、角色模板、权限边界、默认执行工具、模型和 prompt 模版。编排里选中后，会把这些字段带进去作为角色快照。",
                "body_en": "A role definition stores the role name, role template, permission boundary, default executor, model, and prompt template. When an orchestration selects it, those values are copied in as a role snapshot.",
                "submit_zh": "保存角色",
                "submit_en": "Save role",
                "action": "/roles/new",
            }
        form_values = _normalize_role_definition_form(values, locale=locale)
        archetype_options = _archetype_options()
        selected_archetype_option = next(
            (option for option in archetype_options if option["id"] == str(form_values.get("archetype", "builder"))),
            archetype_options[0],
        )
        builtin_prompt_sync_enabled = not is_editing_custom and (
            incoming_values is None or "prompt_markdown" not in incoming_values
        )
        return templates.TemplateResponse(
            request,
            "new_role_definition.html",
            {
                "request": request,
                "form_values": form_values,
                "form_error": form_error,
                "page_copy": page_copy,
                "current_role_definition": current_role_definition,
                "archetype_options": archetype_options,
                "selected_archetype_option": selected_archetype_option,
                "page_locale": locale,
                "role_template_locked": role_template_locked,
                "role_template_lock_reason": "builtin" if is_builtin_template else ("existing" if is_editing_custom else "new"),
                "executor_profiles": list_executor_profiles(),
                "builtin_role_templates": _builtin_role_templates(locale=locale),
                "builtin_prompt_sync_enabled": builtin_prompt_sync_enabled,
                "initial_prompt_preview_html": render_safe_markdown_html(
                    str(form_values.get("prompt_markdown", "")),
                    strip_front_matter=True,
                ),
                "access_state": access_state,
            },
        )

    def render_tutorial(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "tutorial.html",
            {
                "request": request,
                "access_state": access_state,
            },
        )

    def render_tools(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "tools.html",
            {
                "request": request,
                "skill_bundle": load_spec_skill_bundle(),
                "skill_targets": list_spec_skill_targets(),
                "access_state": access_state,
            },
        )

    def render_auth_required(request: Request) -> HTMLResponse:
        return HTMLResponse(
            templates.TemplateResponse(
                request,
                "auth.html",
                {"request": request, "url_path": html.escape(request.url.path)},
            ).body.decode(),
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _auth_required_response(request: Request):
        accept_header = request.headers.get("accept", "")
        if request.url.path.startswith("/api/") or "application/json" in accept_header:
            return JSONResponse(
                {
                    "error": "auth token required",
                    "hint": "append ?token=<your-token> once or send Authorization: Bearer <your-token>",
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return render_auth_required(request)

    @app.exception_handler(LooporaError)
    async def loopora_error_handler(request: Request, exc: LooporaError) -> JSONResponse:
        log_event(
            logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a Loopora domain error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return json_error(str(exc), status_code=400)

    @app.exception_handler(SpecError)
    async def spec_error_handler(request: Request, exc: SpecError) -> JSONResponse:
        log_event(
            logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a spec validation error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return json_error(str(exc), status_code=400)

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
        log_event(
            logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a workflow validation error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return json_error(str(exc), status_code=400)

    @app.exception_handler(SystemDialogError)
    async def system_dialog_error_handler(request: Request, exc: SystemDialogError) -> JSONResponse:
        log_event(
            logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed while opening a system dialog",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return json_error(str(exc), status_code=400)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        loops = [_decorate_loop_overview(loop) for loop in svc().list_loops()]
        return templates.TemplateResponse(request, "index.html", {"request": request, "loops": loops, "access_state": access_state})

    @app.get("/loops/new", response_class=HTMLResponse)
    async def new_loop(request: Request) -> HTMLResponse:
        return render_new_loop(request, values=request.query_params)

    @app.get("/orchestrations", response_class=HTMLResponse)
    async def orchestrations_page(request: Request) -> HTMLResponse:
        return render_orchestrations(request)

    @app.get("/roles", response_class=HTMLResponse)
    async def role_definitions_page(request: Request) -> HTMLResponse:
        return render_role_definitions(request)

    @app.get("/orchestrations/new", response_class=HTMLResponse)
    async def new_orchestration(request: Request) -> HTMLResponse:
        preset = str(request.query_params.get("workflow_preset", "")).strip()
        values = request.query_params if preset else None
        return render_new_orchestration(request, values=values)

    @app.get("/orchestrations/{orchestration_id}/edit", response_class=HTMLResponse)
    async def edit_orchestration(request: Request, orchestration_id: str) -> HTMLResponse:
        return render_new_orchestration(request, orchestration=svc().get_orchestration(orchestration_id))

    @app.get("/roles/new", response_class=HTMLResponse)
    async def new_role_definition(request: Request) -> HTMLResponse:
        return render_new_role_definition(request, values=request.query_params if request.query_params else None)

    @app.get("/roles/{role_definition_id}/edit", response_class=HTMLResponse)
    async def edit_role_definition(request: Request, role_definition_id: str) -> HTMLResponse:
        return render_new_role_definition(request, role_definition=svc().get_role_definition(role_definition_id))

    @app.get("/tools", response_class=HTMLResponse)
    async def tools_page(request: Request) -> HTMLResponse:
        return render_tools(request)

    @app.get("/tutorial", response_class=HTMLResponse)
    async def tutorial_page(request: Request) -> HTMLResponse:
        return render_tutorial(request)

    @app.get("/loops/{loop_id}", response_class=HTMLResponse)
    async def loop_detail(request: Request, loop_id: str) -> HTMLResponse:
        loop = svc().get_loop(loop_id)
        runs = [_decorate_run_overview(run) for run in loop["runs"]]
        latest_run = runs[0] if runs else None
        return templates.TemplateResponse(
            request,
            "loop_detail.html",
            {
                "request": request,
                "loop": {
                    **loop,
                    "runs": runs,
                    "role_executor_summary": _workflow_role_executor_summary(
                        loop.get("workflow_json") or {},
                        fallback_executor_kind=loop.get("executor_kind", "codex"),
                    ),
                    "spec_rendered_html": render_safe_markdown_html(loop.get("spec_markdown", "")),
                },
                "latest_run": latest_run,
                "summary_snapshot": _build_run_summary_snapshot(latest_run) if latest_run else None,
                "access_state": access_state,
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        locale = _preferred_request_locale(request)
        run = svc().get_run(run_id)
        seed_events = svc().stream_events(run_id, limit=5000)
        latest_event_id = seed_events[-1]["id"] if seed_events else 0
        events = [_format_timeline_event(event) for event in seed_events if event["event_type"] in TIMELINE_EVENT_TYPES]
        return templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "request": request,
                "run": run,
                "page_locale": locale,
                "progress_stages": _progress_stage_seed(run),
                "timeline_events": events[-40:],
                "console_events": seed_events[-160:],
                "progress_events": [event for event in seed_events if event["event_type"] in PROGRESS_EVENT_TYPES][-2000:],
                "latest_event_id": latest_event_id,
                "key_takeaways": _build_run_key_takeaways(run),
                "access_state": access_state,
            },
        )

    @app.get("/runs/{run_id}/console", response_class=HTMLResponse)
    async def run_console(request: Request, run_id: str) -> HTMLResponse:
        run = svc().get_run(run_id)
        seed_events = svc().stream_events(run_id, limit=5000)
        latest_event_id = seed_events[-1]["id"] if seed_events else 0
        return templates.TemplateResponse(
            request,
            "run_console.html",
            {
                "request": request,
                "run": run,
                "console_events": seed_events[-360:],
                "latest_event_id": latest_event_id,
                "access_state": access_state,
            },
        )

    @app.post("/api/loops")
    async def api_create_loop(request: Request) -> JSONResponse:
        payload = await request.json()
        loop_kwargs, start_immediately = _loop_payload_from_mapping(payload)
        loop = svc().create_loop(**loop_kwargs)
        if start_immediately:
            run = svc().start_run(loop["id"])
            svc().start_run_async(run["id"])
            return JSONResponse(
                {"loop": loop, "run": run, "redirect_url": f"/runs/{run['id']}"},
                status_code=201,
            )
        return JSONResponse({"loop": loop, "redirect_url": f"/loops/{loop['id']}"}, status_code=201)

    @app.get("/api/loops")
    async def api_list_loops() -> JSONResponse:
        return JSONResponse(svc().list_loops())

    @app.get("/api/orchestrations")
    async def api_list_orchestrations() -> JSONResponse:
        return JSONResponse(svc().list_orchestrations())

    @app.get("/api/orchestrations/{orchestration_id}")
    async def api_get_orchestration(orchestration_id: str) -> JSONResponse:
        return JSONResponse(svc().get_orchestration(orchestration_id))

    @app.get("/api/role-definitions")
    async def api_list_role_definitions() -> JSONResponse:
        return JSONResponse(svc().list_role_definitions())

    @app.get("/api/role-definitions/{role_definition_id}")
    async def api_get_role_definition(role_definition_id: str) -> JSONResponse:
        return JSONResponse(svc().get_role_definition(role_definition_id))

    @app.post("/api/orchestrations")
    async def api_create_orchestration(request: Request) -> JSONResponse:
        payload = await request.json()
        orchestration = svc().create_orchestration(**_orchestration_payload_from_mapping(payload))
        return JSONResponse({"orchestration": orchestration, "redirect_url": f"/orchestrations/{orchestration['id']}/edit"}, status_code=201)

    @app.put("/api/orchestrations/{orchestration_id}")
    async def api_update_orchestration(orchestration_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        orchestration = svc().update_orchestration(orchestration_id, **_orchestration_payload_from_mapping(payload))
        return JSONResponse({"orchestration": orchestration, "redirect_url": f"/orchestrations/{orchestration['id']}/edit"})

    @app.delete("/api/orchestrations/{orchestration_id}")
    async def api_delete_orchestration(orchestration_id: str) -> JSONResponse:
        return JSONResponse(svc().delete_orchestration(orchestration_id))

    @app.post("/api/role-definitions")
    async def api_create_role_definition(request: Request) -> JSONResponse:
        payload = await request.json()
        role_definition = svc().create_role_definition(**_role_definition_payload_from_mapping(payload))
        return JSONResponse(
            {"role_definition": role_definition, "redirect_url": f"/roles/{role_definition['id']}/edit"},
            status_code=201,
        )

    @app.put("/api/role-definitions/{role_definition_id}")
    async def api_update_role_definition(role_definition_id: str, request: Request) -> JSONResponse:
        payload = await request.json()
        role_definition = svc().update_role_definition(role_definition_id, **_role_definition_payload_from_mapping(payload))
        return JSONResponse(
            {"role_definition": role_definition, "redirect_url": f"/roles/{role_definition['id']}/edit"}
        )

    @app.delete("/api/role-definitions/{role_definition_id}")
    async def api_delete_role_definition(role_definition_id: str) -> JSONResponse:
        return JSONResponse(svc().delete_role_definition(role_definition_id))

    @app.get("/api/runtime/activity")
    async def api_runtime_activity() -> JSONResponse:
        return JSONResponse(svc().get_runtime_activity())

    @app.get("/api/loops/{loop_id}")
    async def api_get_loop(loop_id: str) -> JSONResponse:
        return JSONResponse(svc().get_loop(loop_id))

    @app.delete("/api/loops/{loop_id}")
    async def api_delete_loop(loop_id: str) -> JSONResponse:
        return JSONResponse(svc().delete_loop(loop_id))

    @app.post("/api/loops/{loop_id}/runs")
    async def api_start_run(loop_id: str) -> JSONResponse:
        run = svc().start_run(loop_id)
        svc().start_run_async(run["id"])
        return JSONResponse(run, status_code=201)

    @app.get("/api/runs/{run_id}")
    async def api_get_run(run_id: str) -> JSONResponse:
        return JSONResponse(svc().get_run(run_id))

    @app.post("/api/runs/{run_id}/stop")
    async def api_stop_run(run_id: str) -> JSONResponse:
        return JSONResponse(svc().stop_run(run_id))

    @app.get("/api/runs/{run_id}/events")
    async def api_run_events(run_id: str, after_id: int = 0, limit: int = 200) -> JSONResponse:
        svc().get_run(run_id)
        return JSONResponse(svc().repository.list_events(run_id, after_id=after_id, limit=limit))

    @app.get("/api/runs/{run_id}/artifacts")
    async def api_run_artifacts(run_id: str) -> JSONResponse:
        run = svc().get_run(run_id)
        return JSONResponse(_list_run_artifacts(run))

    @app.get("/api/runs/{run_id}/key-takeaways")
    async def api_run_key_takeaways(run_id: str) -> JSONResponse:
        run = svc().get_run(run_id)
        return JSONResponse(_build_run_key_takeaways(run))

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    async def api_run_artifact_preview(run_id: str, artifact_id: str) -> JSONResponse:
        run = svc().get_run(run_id)
        artifact = _artifact_record_or_404(run, artifact_id)
        artifact_path = Path(run["runs_dir"]) / artifact["relative_path"]
        relative_path = f"runs/{run_id}/{artifact['relative_path']}"
        if not artifact_path.exists():
            return JSONResponse(
                {
                    "kind": "missing",
                    "artifact": {
                        **artifact,
                        "path": relative_path,
                    },
                    "message": "missing",
                }
            )
        preview = svc().preview_file(run_id, root="loopora", relative_path=relative_path)
        preview["artifact"] = {
            **artifact,
            "path": relative_path,
        }
        return JSONResponse(preview)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}/download")
    async def api_run_artifact_download(run_id: str, artifact_id: str) -> FileResponse:
        run = svc().get_run(run_id)
        artifact = _artifact_record_or_404(run, artifact_id)
        artifact_path = Path(run["runs_dir"]) / artifact["relative_path"]
        if not artifact_path.exists():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(artifact_path.resolve())

    @app.get("/api/runs/{run_id}/stream")
    async def api_run_stream(request: Request, run_id: str, after_id: int = 0) -> StreamingResponse:
        svc().get_run(run_id)
        after_id = _resolve_stream_after_id(request, run_id=run_id, after_id=after_id)

        def event_stream():
            last_id = after_id
            while True:
                try:
                    events = svc().stream_events(run_id, after_id=last_id)
                    for event in events:
                        last_id = event["id"]
                        yield f"id: {event['id']}\n"
                        yield f"event: {event['event_type']}\n"
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    run = svc().get_run(run_id)
                except Exception as exc:
                    log_exception(
                        logger,
                        "web.run_stream.failed",
                        "Run event stream failed",
                        error=exc,
                        run_id=run_id,
                        after_id=last_id,
                    )
                    payload = {"run_id": run_id, "after_id": last_id, "error": str(exc)}
                    yield "event: stream_error\n"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                if run["status"] in {"succeeded", "failed", "stopped"} and not events:
                    break
                yield ": keep-alive\n\n"
                time.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/files")
    async def api_preview_file(
        run_id: str,
        root: str = Query(default="workdir", pattern=FILE_ROOT_QUERY_PATTERN),
        path: str = "",
    ) -> JSONResponse:
        return JSONResponse(svc().preview_file(run_id, root=normalize_file_root(root), relative_path=path))

    @app.get("/api/files/download")
    async def api_download_file(
        run_id: str,
        root: str = Query(default="workdir", pattern=FILE_ROOT_QUERY_PATTERN),
        path: str = "",
    ) -> FileResponse:
        preview = svc().preview_file(run_id, root=normalize_file_root(root), relative_path=path)
        if preview["kind"] != "file":
            raise HTTPException(status_code=400, detail="path is not a file")
        base = Path(preview["base"])
        resolved = (base / path).resolve()
        return FileResponse(resolved)

    @app.get("/api/specs/validate")
    async def api_validate_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            _, compiled = read_and_compile(spec_path)
        except (FileNotFoundError, OSError, SpecError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(
            {
                "ok": True,
                "path": str(spec_path.resolve()),
                "check_count": len(compiled["checks"]),
                "check_mode": compiled["check_mode"],
            }
        )

    @app.get("/api/specs/preview")
    async def api_preview_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            raw_bytes = spec_path.read_bytes()
        except (FileNotFoundError, OSError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        if looks_binary(raw_bytes):
            return JSONResponse({"ok": False, "error": "spec preview only supports text markdown files"})
        return JSONResponse(_spec_document_payload(spec_path, decode_text_bytes(raw_bytes)))

    @app.get("/api/specs/document")
    async def api_get_spec_document(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            raw_bytes = spec_path.read_bytes()
        except (FileNotFoundError, OSError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        if looks_binary(raw_bytes):
            return JSONResponse({"ok": False, "error": "spec editor only supports text markdown files"})
        return JSONResponse(_spec_document_payload(spec_path, decode_text_bytes(raw_bytes)))

    @app.put("/api/specs/document")
    async def api_save_spec_document(request: Request) -> JSONResponse:
        payload = await request.json()
        path_text = str(payload.get("path", "")).strip()
        markdown_text = normalize_markdown_text(str(payload.get("content", "")))
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        if not spec_path.parent.exists():
            return JSONResponse({"ok": False, "error": f"spec parent directory does not exist: {spec_path.parent}"})
        try:
            spec_path.write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(_spec_document_payload(spec_path, markdown_text))

    @app.post("/api/markdown/render")
    async def api_render_markdown(request: Request) -> JSONResponse:
        payload = await request.json()
        markdown_text = str(payload.get("markdown", ""))
        strip_front_matter = _coerce_bool(payload.get("strip_front_matter", False))
        return JSONResponse(
            {
                "ok": True,
                "rendered_html": render_safe_markdown_html(
                    markdown_text,
                    strip_front_matter=strip_front_matter,
                ),
            }
        )

    @app.post("/api/prompts/validate")
    async def api_validate_prompt(request: Request) -> JSONResponse:
        payload = await request.json()
        markdown_text = str(payload.get("markdown", ""))
        expected_archetype = str(payload.get("archetype", "")).strip() or None
        try:
            from loopora.workflows import validate_prompt_markdown

            metadata, body = validate_prompt_markdown(markdown_text, expected_archetype=expected_archetype)
        except WorkflowError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse({"ok": True, "metadata": metadata, "body": body})

    @app.get("/api/prompts/templates/{prompt_ref}")
    async def api_prompt_template(prompt_ref: str, locale: str | None = Query(default=None)) -> Response:
        try:
            markdown_text = builtin_prompt_markdown(prompt_ref, locale=locale)
        except WorkflowError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=markdown_text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{prompt_ref}"'},
        )

    @app.post("/api/specs/init")
    async def api_init_spec(request: Request) -> JSONResponse:
        payload = await request.json()
        path_text = str(payload.get("path", "")).strip()
        if not path_text:
            return json_error("spec path is required")
        locale = str(payload.get("locale", "zh"))
        try:
            created = init_spec_file(Path(path_text).expanduser(), locale=locale)
        except (FileExistsError, OSError) as exc:
            return json_error(str(exc))
        return JSONResponse({"path": str(created.resolve())}, status_code=201)

    @app.get(f"/api/skills/{SPEC_SKILL_SLUG}")
    @app.get(f"/api/skills/{LEGACY_SPEC_SKILL_SLUG}")
    async def api_spec_skill_targets() -> JSONResponse:
        return JSONResponse({"skill_name": SPEC_SKILL_SLUG, "targets": list_spec_skill_targets()})

    @app.post(f"/api/skills/{SPEC_SKILL_SLUG}/install")
    @app.post(f"/api/skills/{LEGACY_SPEC_SKILL_SLUG}/install")
    async def api_install_spec_skill(request: Request) -> JSONResponse:
        payload = await request.json()
        target = str(payload.get("target", "")).strip().lower()
        try:
            result = install_spec_skill(target)
        except ValueError as exc:
            return json_error(str(exc))
        return JSONResponse({"result": result, "targets": list_spec_skill_targets()}, status_code=201)

    @app.get(f"/api/skills/{SPEC_SKILL_SLUG}/download")
    @app.get(f"/api/skills/{LEGACY_SPEC_SKILL_SLUG}/download")
    async def api_download_spec_skill_bundle() -> Response:
        filename, archive_bytes = build_spec_skill_bundle_archive()
        return Response(
            content=archive_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/system/pick-directory")
    async def api_pick_directory(start_path: str = "") -> JSONResponse:
        if not access_state["native_dialogs_enabled"]:
            return json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = pick_directory(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-file")
    async def api_pick_spec_file(start_path: str = "") -> JSONResponse:
        if not access_state["native_dialogs_enabled"]:
            return json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = pick_file(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-save-path")
    async def api_pick_spec_save_path(start_path: str = "") -> JSONResponse:
        if not access_state["native_dialogs_enabled"]:
            return json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = pick_save_file(start_path or None, default_name="spec.md")
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.post("/api/system/reveal-path")
    async def api_reveal_path(request: Request) -> JSONResponse:
        if not access_state["native_dialogs_enabled"]:
            return json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        payload = await request.json()
        target = str(payload.get("path") or "").strip()
        if not target:
            return json_error("path is required")
        return JSONResponse({"path": reveal_path(target), "ok": True})

    @app.post("/loops/new")
    async def create_loop_from_form(request: Request):
        form = await request.form()
        values = _normalize_loop_form(form)
        try:
            loop_kwargs, start_immediately = _loop_payload_from_mapping(form)
            loop = svc().create_loop(**loop_kwargs)
            if start_immediately:
                run = svc().start_run(loop["id"])
                svc().start_run_async(run["id"])
                return RedirectResponse(url=f"/runs/{run['id']}", status_code=303)
            return RedirectResponse(url=f"/loops/{loop['id']}", status_code=303)
        except (LooporaError, SpecError, FileExistsError, OSError, ValueError) as exc:
            return render_new_loop(request, values=values, form_error=str(exc))

    @app.post("/orchestrations/new")
    async def create_orchestration_from_form(request: Request):
        form = await request.form()
        values = _normalize_orchestration_form(form)
        try:
            orchestration = svc().create_orchestration(**_orchestration_payload_from_mapping(form, default_to_preset=False))
            return RedirectResponse(url=f"/orchestrations/{orchestration['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return render_new_orchestration(request, values=values, form_error=str(exc))

    @app.post("/orchestrations/{orchestration_id}/edit")
    async def update_orchestration_from_form(request: Request, orchestration_id: str):
        form = await request.form()
        values = _normalize_orchestration_form(form)
        orchestration = svc().get_orchestration(orchestration_id)
        try:
            if orchestration.get("source") == "builtin":
                raise LooporaError("built-in orchestrations are read-only; create a new orchestration to customize one")
            updated = svc().update_orchestration(orchestration_id, **_orchestration_payload_from_mapping(form, default_to_preset=False))
            return RedirectResponse(url=f"/orchestrations/{updated['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return render_new_orchestration(request, values=values, form_error=str(exc), orchestration=orchestration)

    @app.post("/roles/new")
    async def create_role_definition_from_form(request: Request):
        form = await request.form()
        values = _normalize_role_definition_form(form)
        try:
            role_definition = svc().create_role_definition(**_role_definition_payload_from_mapping(form))
            return RedirectResponse(url=f"/roles/{role_definition['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return render_new_role_definition(request, values=values, form_error=str(exc))

    @app.post("/roles/{role_definition_id}/edit")
    async def update_role_definition_from_form(request: Request, role_definition_id: str):
        form = await request.form()
        values = _normalize_role_definition_form(form)
        role_definition = svc().get_role_definition(role_definition_id)
        try:
            if role_definition.get("source") == "builtin":
                created = svc().create_role_definition(**_role_definition_payload_from_mapping(form))
                return RedirectResponse(url=f"/roles/{created['id']}/edit?saved=1", status_code=303)
            updated = svc().update_role_definition(role_definition_id, **_role_definition_payload_from_mapping(form))
            return RedirectResponse(url=f"/roles/{updated['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return render_new_role_definition(
                request,
                values=values,
                form_error=str(exc),
                role_definition=role_definition,
            )

    return app


def _log_web_response(request: Request, status_code: int, started_at: float) -> None:
    path = request.url.path
    if path.startswith("/static/") or path.startswith("/logo/"):
        return
    level = logging.ERROR if status_code >= 500 else (logging.WARNING if status_code >= 400 else logging.INFO)
    event = "web.request.failed" if status_code >= 500 else ("web.request.rejected" if status_code >= 400 else "web.request.completed")
    log_event(
        logger,
        level,
        event,
        "HTTP request completed",
        method=request.method,
        request_path=path,
        status_code=status_code,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        client_ip=request.client.host if request.client else "",
    )


def _resolve_stream_after_id(request: Request, *, run_id: str, after_id: int) -> int:
    last_event_header = str(request.headers.get("last-event-id", "")).strip()
    if not last_event_header:
        return after_id
    try:
        return max(after_id, int(last_event_header))
    except ValueError:
        log_event(
            logger,
            logging.WARNING,
            "web.run_stream.resume_cursor_invalid",
            "Ignored invalid SSE resume cursor and kept the request cursor",
            run_id=run_id,
            after_id=after_id,
            invalid_last_event_id=last_event_header,
        )
        return after_id


def _loop_payload_from_mapping(payload: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    name = str(payload.get("name", "")).strip()
    workdir = str(payload.get("workdir", "")).strip()
    spec_path = str(payload.get("spec_path", "")).strip()
    executor_kind = str(payload.get("executor_kind", "codex")).strip() or "codex"
    executor_mode = str(payload.get("executor_mode", "preset")).strip() or "preset"
    try:
        profile = executor_profile(executor_kind)
    except ValueError as exc:
        raise LooporaError(str(exc)) from exc
    model = str(payload.get("model", "")).strip()
    reasoning_effort = str(payload.get("reasoning_effort", "")).strip()
    command_cli = str(payload.get("command_cli", "")).strip()
    command_args_text = str(payload.get("command_args_text", ""))
    if not name:
        raise LooporaError("name is required")
    if not workdir:
        raise LooporaError("workdir is required")
    if not spec_path:
        raise LooporaError("spec path is required")

    try:
        iteration_interval_seconds = float(payload.get("iteration_interval_seconds", 0))
        max_iters = int(payload.get("max_iters", 8))
        max_role_retries = int(payload.get("max_role_retries", 2))
        delta_threshold = float(payload.get("delta_threshold", 0.005))
        trigger_window = int(payload.get("trigger_window", 4))
        regression_window = int(payload.get("regression_window", 2))
    except (TypeError, ValueError) as exc:
        raise LooporaError("numeric loop settings must use valid numbers") from exc

    loop_kwargs = {
        "name": name,
        "spec_path": Path(spec_path),
        "workdir": Path(workdir),
        "orchestration_id": str(payload.get("orchestration_id", "")).strip() or None,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli if command_cli else profile.cli_name,
        "command_args_text": command_args_text,
        "model": model if model or profile.default_model == "" else profile.default_model,
        "reasoning_effort": reasoning_effort if reasoning_effort or profile.effort_default == "" else profile.effort_default,
        "completion_mode": str(payload.get("completion_mode", "gatekeeper")).strip() or "gatekeeper",
        "iteration_interval_seconds": iteration_interval_seconds,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "workflow": _workflow_from_mapping(payload, default_to_preset=False),
        "prompt_files": _prompt_files_from_mapping(payload),
        "role_models": _role_models_from_mapping(payload),
    }
    return loop_kwargs, _coerce_bool(payload.get("start_immediately"))


def _orchestration_payload_from_mapping(
    payload: Mapping[str, object],
    *,
    default_to_preset: bool = True,
) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    if not name:
        raise LooporaError("name is required")
    return {
        "name": name,
        "description": description,
        "workflow": _workflow_from_mapping(payload, default_to_preset=default_to_preset),
        "prompt_files": _prompt_files_from_mapping(payload),
        "role_models": _role_models_from_mapping(payload),
    }


def _role_definition_payload_from_mapping(payload: Mapping[str, object]) -> dict[str, object]:
    name = str(payload.get("name", "")).strip()
    description = str(payload.get("description", "")).strip()
    archetype = str(payload.get("archetype", "builder")).strip() or "builder"
    prompt_ref = str(payload.get("prompt_ref", "")).strip()
    prompt_markdown = str(payload.get("prompt_markdown", ""))
    executor_kind = str(payload.get("executor_kind", "codex")).strip() or "codex"
    executor_mode = str(payload.get("executor_mode", "preset")).strip() or "preset"
    command_cli = str(payload.get("command_cli", "")).strip()
    command_args_text = str(payload.get("command_args_text", ""))
    model = str(payload.get("model", "")).strip()
    reasoning_effort = str(payload.get("reasoning_effort", "")).strip()
    if not name:
        raise LooporaError("name is required")
    if not prompt_markdown.strip():
        raise LooporaError("prompt_markdown is required")
    return {
        "name": name,
        "description": description,
        "archetype": archetype,
        "prompt_ref": prompt_ref,
        "prompt_markdown": prompt_markdown,
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli,
        "command_args_text": command_args_text,
        "model": model,
        "reasoning_effort": reasoning_effort,
    }


def _mapping_from_json_field(value: object, *, field_name: str) -> dict[str, object]:
    if isinstance(value, Mapping):
        return dict(value)
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LooporaError(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, Mapping):
        raise LooporaError(f"{field_name} must decode to an object")
    return dict(parsed)


def _workflow_from_mapping(payload: Mapping[str, object], *, default_to_preset: bool = True) -> dict | None:
    workflow = payload.get("workflow")
    if isinstance(workflow, Mapping):
        return dict(workflow)
    workflow_json = _mapping_from_json_field(payload.get("workflow_json"), field_name="workflow_json")
    if workflow_json:
        return workflow_json
    if not default_to_preset:
        return None
    preset = str(payload.get("workflow_preset", "build_first")).strip() or "build_first"
    return build_preset_workflow(preset)


def _prompt_files_from_mapping(payload: Mapping[str, object]) -> dict[str, str]:
    prompt_files = payload.get("prompt_files")
    if isinstance(prompt_files, Mapping):
        return {str(key): str(value) for key, value in dict(prompt_files).items()}
    prompt_files_json = _mapping_from_json_field(payload.get("prompt_files_json"), field_name="prompt_files_json")
    return {str(key): str(value) for key, value in prompt_files_json.items()}


def _role_models_from_mapping(payload: Mapping[str, object]) -> dict[str, str]:
    role_models = payload.get("role_models")
    if isinstance(role_models, Mapping):
        return normalize_role_models(dict(role_models))
    extracted = {}
    for role in ("builder", "inspector", "gatekeeper", "guide", "generator", "tester", "verifier", "challenger"):
        value = str(payload.get(f"role_model_{role}", "")).strip()
        if value:
            extracted[role] = value
    return normalize_role_models(extracted)


def _format_timeline_event(event: dict) -> dict:
    payload = event.get("payload", {})
    role = payload.get("role") or event.get("role")
    title = event["event_type"]
    detail = ""
    duration_ms = payload.get("duration_ms")

    if event["event_type"] == "run_started":
        title = "Run started"
    elif event["event_type"] == "checks_resolved":
        source = "auto-generated" if payload.get("source") == "auto_generated" else "specified"
        title = "Checks resolved"
        detail = f"{payload.get('count', 0)} checks, {source}"
    elif event["event_type"] == "role_request_prepared":
        title = "Role request prepared"
        detail = str(payload.get("role_name") or role or "").strip()
    elif event["event_type"] == "step_context_prepared":
        title = "Step context prepared"
        detail = str(payload.get("step_id") or "").strip()
    elif event["event_type"] == "role_execution_summary":
        if payload.get("ok"):
            title = f"{role or 'role'} completed"
            parts = []
            if payload.get("attempts", 1) > 1:
                parts.append(f"attempts={payload['attempts']}")
            if payload.get("degraded"):
                parts.append("degraded")
            if duration_ms is not None:
                parts.append(f"{int(duration_ms)}ms")
            detail = ", ".join(parts) if parts else "ok"
        else:
            title = f"{role or 'role'} failed"
            parts = [str(payload.get("error", "")).strip()]
            if duration_ms is not None:
                parts.append(f"{int(duration_ms)}ms")
            detail = ", ".join(part for part in parts if part)
    elif event["event_type"] == "role_degraded":
        title = f"{role or 'role'} degraded"
        detail = str(payload.get("mode", "")).strip()
    elif event["event_type"] == "step_handoff_written":
        title = "Step handoff written"
        detail = str(payload.get("summary") or payload.get("step_id") or "").strip()
    elif event["event_type"] == "iteration_summary_written":
        title = "Iteration summary written"
        detail = str(payload.get("composite_score", "")).strip()
    elif event["event_type"] == "challenger_done":
        title = "Challenger suggested a new direction"
        detail = str(payload.get("mode", "")).strip()
    elif event["event_type"] == "iteration_wait_started":
        title = "Waiting for the next iteration"
        detail = f"{payload.get('duration_seconds', 0)}s"
    elif event["event_type"] == "iteration_wait_finished":
        title = "Iteration wait finished"
        detail = f"{payload.get('duration_seconds', 0)}s"
    elif event["event_type"] == "stop_requested":
        title = "Stop requested"
    elif event["event_type"] == "run_aborted":
        title = f"Run aborted in {payload.get('role', 'role')}"
        detail = str(payload.get("attempts", "")).strip()
    elif event["event_type"] == "workspace_guard_triggered":
        title = "Workspace safety guard triggered"
        detail = f"deleted={payload.get('deleted_original_count', 0)}"
    elif event["event_type"] == "run_finished":
        title = f"Run {payload.get('status', 'finished')}"
        reason = str(payload.get("reason", "")).strip()
        iter_id = payload.get("iter")
        if reason:
            detail = {
                "max_iters_exhausted": "max iterations exhausted",
                "rounds_completed": "planned rounds completed",
            }.get(reason, reason)
        elif iter_id is not None:
            display_iter = _display_iter(iter_id)
            detail = f"iter={display_iter}" if display_iter is not None else ""

    return {
        "id": event["id"],
        "event_type": event["event_type"],
        "created_at": event["created_at"],
        "title": title,
        "detail": detail,
        "role": event.get("role"),
        "payload": payload,
    }


def _normalize_loop_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_LOOP_FORM)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    normalized["start_immediately"] = _coerce_bool(normalized.get("start_immediately", True))
    return normalized


def _loop_form_is_pristine(values: Mapping[str, object] | None) -> bool:
    return _canonicalize_loop_form_for_comparison(values) == _canonicalize_loop_form_for_comparison(None)


def _canonicalize_loop_form_for_comparison(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = _normalize_loop_form(values)
    canonical = dict(normalized)
    for key in canonical:
        value = canonical[key]
        if key == "start_immediately":
            canonical[key] = _coerce_bool(value)
            continue
        if key in {"max_iters", "max_role_retries", "trigger_window", "regression_window"}:
            canonical[key] = _coerce_loop_form_number(value, integer_only=True)
            continue
        if key in {"delta_threshold", "iteration_interval_seconds"}:
            canonical[key] = _coerce_loop_form_number(value, integer_only=False)
            continue
        if isinstance(value, str):
            canonical[key] = value.strip()
    return canonical


def _coerce_loop_form_number(value: object, *, integer_only: bool) -> object:
    if isinstance(value, str) and not value.strip():
        return ""
    try:
        return int(value) if integer_only else float(value)
    except (TypeError, ValueError):
        return value


def _normalize_orchestration_form(values: Mapping[str, object] | None) -> dict[str, object]:
    normalized = dict(DEFAULT_ORCHESTRATION_FORM)
    if not values:
        normalized["workflow_json"] = json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False, indent=2)
        normalized["prompt_files_json"] = json.dumps({}, ensure_ascii=False, indent=2)
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    if isinstance(normalized.get("workflow_json"), Mapping):
        normalized["workflow_json"] = json.dumps(normalized["workflow_json"], ensure_ascii=False, indent=2)
    if isinstance(normalized.get("prompt_files_json"), Mapping):
        normalized["prompt_files_json"] = json.dumps(normalized["prompt_files_json"], ensure_ascii=False, indent=2)
    if not str(normalized.get("workflow_json", "")).strip():
        preset_name = str(normalized.get("workflow_preset", "")).strip()
        if preset_name:
            workflow = build_preset_workflow(preset_name)
            normalized["workflow_json"] = json.dumps(workflow, ensure_ascii=False, indent=2)
            normalized["prompt_files_json"] = json.dumps(resolve_prompt_files(workflow), ensure_ascii=False, indent=2)
        else:
            normalized["workflow_json"] = json.dumps({"version": 1, "preset": "", "roles": [], "steps": []}, ensure_ascii=False, indent=2)
            normalized["prompt_files_json"] = json.dumps({}, ensure_ascii=False, indent=2)
    return normalized


def _normalize_role_definition_form(values: Mapping[str, object] | None, *, locale: str = "en") -> dict[str, object]:
    normalized = dict(DEFAULT_ROLE_DEFINITION_FORM)
    normalized["prompt_markdown"] = builtin_prompt_markdown("builder.md", locale=locale)
    if not values:
        return normalized
    for key in normalized:
        if key in values:
            normalized[key] = values[key]
    if "prompt_markdown" not in values:
        archetype = str(normalized.get("archetype", "builder") or "builder")
        normalized["prompt_markdown"] = builtin_prompt_markdown(_builtin_prompt_ref_for_archetype(archetype), locale=locale)
    try:
        profile = executor_profile(str(normalized.get("executor_kind", "codex")))
    except ValueError:
        profile = executor_profile("codex")
    if profile.command_only:
        normalized["executor_mode"] = "command"
    if not str(normalized.get("command_cli", "")).strip():
        normalized["command_cli"] = profile.cli_name
    return normalized


def _archetype_ui_copy() -> dict[str, dict[str, str]]:
    return {
        "builder": {
            "summary_zh": "直接推进实现，适合把 spec 和 handoff 落成真实代码与文件改动。",
            "summary_en": "Pushes the implementation forward and turns specs plus handoffs into real code changes.",
            "recommendation_zh": "建议把它放在需要实际修改工作区的位置，并给它明确的主线目标。",
            "recommendation_en": "Use it where the workflow needs actual workspace edits, with a crisp main-path goal.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "inspector": {
            "summary_zh": "收集证据、跑检查、整理事实，适合验证当前产出到底到了什么程度。",
            "summary_en": "Collects evidence, runs checks, and summarizes facts so the workflow knows what is truly working.",
            "recommendation_zh": "建议接在 Builder 之后，优先覆盖最关键、最可复现的用户路径。",
            "recommendation_en": "Usually works best after the Builder, starting with the most critical reproducible user paths.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "gatekeeper": {
            "summary_zh": "负责做放行判断，只根据 checks、证据和风险决定是否通过。",
            "summary_en": "Owns the pass/fail decision and judges readiness strictly from checks, evidence, and risk.",
            "recommendation_zh": "建议只放一个在流程收束位，避免多个最终裁决角色相互打架。",
            "recommendation_en": "Keep one of these near the end of the workflow so there is a single clear final verdict.",
            "warning_zh": "不建议把它当成实现角色使用，它的职责是裁决，不是补做工作。",
            "warning_en": "Do not use it as an implementation role. Its job is to decide, not to compensate for missing work.",
            "card_tip_zh": "Inspector 负责收集证据和跑检查，只回答“现在发生了什么”；GateKeeper 负责基于这些证据做最终放行判断，回答“现在能不能过”。没有 GateKeeper 时，流程里就少了一个专门做通过/不通过裁决的角色。",
            "card_tip_en": "The Inspector gathers evidence and runs checks, answering “what is happening now.” The GateKeeper uses that evidence to make the final pass/fail call, answering “is this ready to pass.” Without a GateKeeper, the workflow loses its dedicated final judge.",
        },
        "guide": {
            "summary_zh": "在停滞、回退或噪音过多时提供新的方向，帮流程恢复有效推进。",
            "summary_en": "Intervenes when progress stalls or gets noisy, then suggests a tighter next direction.",
            "recommendation_zh": "建议放在流程末尾或条件分支里，用来给下一轮提供更高杠杆的突破口。",
            "recommendation_en": "Use it near the end or in recovery branches to generate the next high-leverage move.",
            "warning_zh": "",
            "warning_en": "",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
        "custom": {
            "summary_zh": "最低权限的补充角色，适合做只读分析、专门观察和窄范围建议。",
            "summary_en": "A restricted support role for read-only analysis, specialized observations, and narrow recommendations.",
            "recommendation_zh": "适合安全审计、文案评审、风险盘点这类辅助任务；通常不要让它承担最终放行。",
            "recommendation_en": "Great for sidecar tasks like security review, copy critique, or risk scans; usually not for the final verdict.",
            "warning_zh": "它不能充当最终放行角色；如果选择 custom 执行工具，也只能使用直接命令模式。",
            "warning_en": "It cannot be the final pass/fail role. If you pair it with the custom executor, direct-command mode is required.",
            "card_tip_zh": "",
            "card_tip_en": "",
        },
    }


def _archetype_options() -> list[dict[str, str]]:
    labels = []
    copy = _archetype_ui_copy()
    for archetype in ARCHETYPES:
        item = copy[archetype]
        english_label = "Custom (Restricted)" if archetype == "custom" else display_name_for_archetype(archetype, locale="en")
        if archetype == "custom":
            labels.append(
                {
                    "id": archetype,
                    "label_zh": english_label,
                    "label_en": english_label,
                    **item,
                }
            )
            continue
        labels.append(
            {
                "id": archetype,
                "label_zh": english_label,
                "label_en": english_label,
                **item,
            }
        )
    return labels


def _orchestration_form_values_from_record(orchestration: Mapping[str, object]) -> dict[str, object]:
    workflow = dict(orchestration.get("workflow_json") or {})
    return {
        "name": str(orchestration.get("name", "")),
        "description": str(orchestration.get("description", "")),
        "workflow_preset": str(workflow.get("preset", "")).strip(),
        "workflow_json": json.dumps(workflow, ensure_ascii=False, indent=2),
        "prompt_files_json": json.dumps(orchestration.get("prompt_files_json") or {}, ensure_ascii=False, indent=2),
    }


def _role_definition_form_values_from_record(role_definition: Mapping[str, object], *, locale: str = "en") -> dict[str, object]:
    prompt_ref = str(role_definition.get("prompt_ref", ""))
    prompt_markdown = str(role_definition.get("prompt_markdown", ""))
    if str(role_definition.get("source", "")).strip() == "builtin" and prompt_ref:
        prompt_markdown = builtin_prompt_markdown(prompt_ref, locale=locale)
    return {
        "name": str(role_definition.get("name", "")),
        "description": str(role_definition.get("description", "")),
        "archetype": str(role_definition.get("archetype", "builder") or "builder"),
        "prompt_ref": prompt_ref,
        "prompt_markdown": prompt_markdown,
        "executor_kind": str(role_definition.get("executor_kind", "codex") or "codex"),
        "executor_mode": str(role_definition.get("executor_mode", "preset") or "preset"),
        "command_cli": str(role_definition.get("command_cli", "")),
        "command_args_text": str(role_definition.get("command_args_text", "")),
        "model": str(role_definition.get("model", "")),
        "reasoning_effort": str(role_definition.get("reasoning_effort", "")),
    }


def _builtin_prompt_ref_for_archetype(archetype: str) -> str:
    return "gatekeeper.md" if archetype == "gatekeeper" else f"{archetype}.md"


def _builtin_role_templates(*, locale: str = "en") -> dict[str, dict[str, object]]:
    templates: dict[str, dict[str, object]] = {}
    for archetype in ARCHETYPES:
        prompt_ref = _builtin_prompt_ref_for_archetype(archetype)
        prompt_markdown_by_locale = builtin_prompt_markdown_by_locale(prompt_ref)
        templates[archetype] = {
            "prompt_ref": prompt_ref,
            "prompt_markdown": prompt_markdown_by_locale[normalize_prompt_locale(locale)],
            "prompt_markdown_by_locale": prompt_markdown_by_locale,
        }
    return templates


def _preferred_request_locale(request: Request) -> str:
    return _preferred_locale_from_accept_language(request.headers.get("accept-language"))


def _preferred_locale_from_accept_language(accept_language: str | None) -> str:
    header = str(accept_language or "").strip()
    if not header:
        return "en"

    candidates: list[tuple[float, int, str]] = []
    for position, raw_item in enumerate(header.split(",")):
        item = raw_item.strip()
        if not item:
            continue
        language_tag, *params = [segment.strip() for segment in item.split(";")]
        normalized_tag = str(language_tag or "").strip().lower().replace("_", "-")
        if not normalized_tag:
            continue
        if normalized_tag.startswith("zh"):
            locale = "zh"
        elif normalized_tag.startswith("en"):
            locale = "en"
        else:
            continue

        q_value = 1.0
        for param in params:
            key, sep, value = param.partition("=")
            if sep and key.strip().lower() == "q":
                try:
                    q_value = float(value.strip())
                except ValueError:
                    q_value = 0.0
                break
        if q_value <= 0:
            continue
        candidates.append((-q_value, position, locale))

    if not candidates:
        return "en"

    candidates.sort()
    return candidates[0][2]


def _spec_validation_from_markdown(markdown_text: str) -> dict[str, object]:
    try:
        compiled = compile_markdown_spec(markdown_text)
    except SpecError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "check_count": 0,
            "check_mode": "",
        }
    return {
        "ok": True,
        "error": "",
        "check_count": len(compiled["checks"]),
        "check_mode": compiled["check_mode"],
    }


def _spec_document_payload(spec_path: Path, markdown_text: str) -> dict[str, object]:
    return {
        "ok": True,
        "path": str(spec_path.resolve()),
        "content": markdown_text,
        "rendered_html": render_safe_markdown_html(markdown_text),
        "validation": _spec_validation_from_markdown(markdown_text),
    }


def _decorate_role_definition_overview(role_definition: Mapping[str, object]) -> dict[str, object]:
    executor_kind = str(role_definition.get("executor_kind", "codex") or "codex")
    archetype = str(role_definition.get("archetype", "builder") or "builder")
    template_name = "Custom (Restricted)" if archetype.strip() == "custom" else display_name_for_archetype(
        archetype,
        locale="en",
    )
    archetype_copy = _archetype_ui_copy()[archetype]
    name = str(role_definition.get("name", "")).strip()
    normalized_name = re.sub(r"[^a-z0-9]+", "", name.lower())
    normalized_template = re.sub(r"[^a-z0-9]+", "", template_name.lower())
    return {
        **role_definition,
        "executor_label": executor_profile(executor_kind).label,
        "template_display_name": template_name,
        "show_template_meta": str(role_definition.get("source", "")).strip() == "custom" and normalized_name != normalized_template,
        "summary_zh": archetype_copy["summary_zh"],
        "summary_en": archetype_copy["summary_en"],
        "card_tip_zh": archetype_copy["card_tip_zh"],
        "card_tip_en": archetype_copy["card_tip_en"],
    }


def _build_access_state(*, bind_host: str, bind_port: int, auth_token: str | None) -> dict[str, object]:
    normalized_auth = (auth_token or "").strip() or None
    remote_access_enabled = not _is_loopback_host(bind_host)
    return {
        "bind_host": bind_host,
        "bind_port": bind_port,
        "auth_token": normalized_auth,
        "auth_enabled": bool(normalized_auth),
        "remote_access_enabled": remote_access_enabled,
        "native_dialogs_enabled": not remote_access_enabled,
    }


def _extract_request_token(request: Request) -> str | None:
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        token = bearer.split(" ", 1)[1].strip()
        if token:
            return token

    header_token = request.headers.get(APP_AUTH_HEADER, "").strip() or request.headers.get(LEGACY_APP_AUTH_HEADER, "").strip()
    if header_token:
        return header_token

    query_token = request.query_params.get("token", "").strip()
    if query_token:
        return query_token

    cookie_token = request.cookies.get(APP_AUTH_COOKIE, "").strip() or request.cookies.get(LEGACY_APP_AUTH_COOKIE, "").strip()
    if cookie_token:
        return cookie_token
    return None


def _is_loopback_host(host: str) -> bool:
    normalized = (host or "").strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _artifact_record_or_404(run: dict, artifact_id: str) -> dict:
    for artifact in _list_run_artifacts(run):
        if artifact["id"] == artifact_id:
            return artifact
    raise HTTPException(status_code=404, detail="unknown artifact")


LEGACY_RUNTIME_ROLE_TO_ARCHETYPE = {
    "generator": "builder",
    "tester": "inspector",
    "verifier": "gatekeeper",
    "challenger": "guide",
}


def _display_iter(iter_value: object | None) -> int | None:
    if iter_value is None:
        return None
    try:
        return max(int(iter_value), 0) + 1
    except (TypeError, ValueError):
        return None


def _strip_markdown(value: str | None) -> str:
    text = str(value or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+\.\s*", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _truncate_text(value: str, max_length: int = 140) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def _summary_excerpt(summary_md: str | None) -> str:
    text = _strip_markdown(summary_md)
    text = strip_run_summary_title(text)
    return _truncate_text(text, max_length=170) if text else ""


def _safe_read_json_file(path: Path) -> dict | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _clean_takeaway_text(value: object, *, max_length: int = 240) -> str:
    text = _truncate_text(_strip_markdown(str(value or "").strip()), max_length=max_length)
    return text.strip()


def _display_role_name(name: object, *, archetype: object = "", runtime_role: object = "") -> str:
    cleaned_name = str(name or "").strip()
    cleaned_runtime = str(runtime_role or "").strip().lower()
    cleaned_archetype = str(archetype or "").strip().lower() or LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(cleaned_runtime, "")
    normalized_name = normalize_role_display_name(cleaned_name, cleaned_archetype)
    if normalized_name:
        return normalized_name
    if cleaned_archetype in ARCHETYPES:
        return display_name_for_archetype(cleaned_archetype, locale="en")
    return cleaned_name or cleaned_runtime or "-"


def _normalize_takeaway_status(status: object) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"passed", "completed", "blocked", "failed", "running", "advisory", "pending"}:
        return normalized
    if normalized in {"complete", "succeeded", "success"}:
        return "completed"
    if normalized in {"queued", "waiting", "idle"}:
        return "pending"
    return "pending"


def _build_role_takeaway_from_handoff(handoff: Mapping[str, object], *, composite_score: object = None) -> dict:
    source = handoff.get("source") if isinstance(handoff.get("source"), Mapping) else {}
    try:
        iter_id = int(source.get("iter", 0))
    except (TypeError, ValueError):
        iter_id = 0
    try:
        step_order = int(source.get("step_order") or 0)
    except (TypeError, ValueError):
        step_order = 0
    role_name = _display_role_name(
        source.get("role_name"),
        archetype=source.get("archetype"),
        runtime_role=source.get("runtime_role"),
    )
    blocking_items = [
        _clean_takeaway_text(item, max_length=520)
        for item in list(handoff.get("blocking_items") or [])
        if _clean_takeaway_text(item, max_length=520)
    ]
    next_action = _clean_takeaway_text(handoff.get("recommended_next_action"), max_length=520)
    return {
        "id": f"iter-{iter_id}-{str(source.get('step_id') or role_name).strip() or role_name}",
        "step_id": str(source.get("step_id") or "").strip(),
        "step_order": step_order,
        "role_name": role_name,
        "archetype": str(source.get("archetype") or "").strip().lower(),
        "status": _normalize_takeaway_status(handoff.get("status")),
        "summary": _clean_takeaway_text(handoff.get("summary"), max_length=1200),
        "blocking_item": " · ".join(blocking_items),
        "next_action": next_action,
        "composite_score": composite_score,
    }


def _build_structured_iteration_takeaways(run: dict) -> list[dict]:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    if not runs_dir_value:
        return []
    runs_dir = Path(runs_dir_value)
    if not runs_dir.exists():
        return []

    summaries_by_iter: dict[int, dict] = {}
    for summary_path in sorted(runs_dir.glob("iterations/iter_*/summary.json")):
        summary_payload = _safe_read_json_file(summary_path)
        if not summary_payload:
            continue
        try:
            iter_id = int(summary_payload.get("iter", -1))
        except (TypeError, ValueError):
            continue
        summaries_by_iter[iter_id] = summary_payload

    handoffs_by_iter: dict[int, list[dict]] = defaultdict(list)
    for handoff_path in sorted(runs_dir.glob("iterations/iter_*/steps/*/handoff.json")):
        handoff_payload = _safe_read_json_file(handoff_path)
        if not handoff_payload:
            continue
        source = handoff_payload.get("source") if isinstance(handoff_payload.get("source"), Mapping) else {}
        try:
            iter_id = int(source.get("iter", -1))
        except (TypeError, ValueError):
            continue
        if iter_id < 0:
            continue
        handoffs_by_iter[iter_id].append(handoff_payload)

    iter_ids = sorted(set(summaries_by_iter) | set(handoffs_by_iter))
    current_iter = run.get("current_iter")
    try:
        current_iter_id = int(current_iter) if current_iter is not None else None
    except (TypeError, ValueError):
        current_iter_id = None

    iterations: list[dict] = []
    for iter_id in iter_ids:
        summary_payload = summaries_by_iter.get(iter_id) or {}
        score_payload = summary_payload.get("score") if isinstance(summary_payload.get("score"), Mapping) else {}
        composite_score = score_payload.get("composite")
        handoffs = sorted(
            handoffs_by_iter.get(iter_id, []),
            key=lambda item: int(((item.get("source") if isinstance(item.get("source"), Mapping) else {}) or {}).get("step_order") or 0),
        )
        roles = [_build_role_takeaway_from_handoff(handoff, composite_score=composite_score) for handoff in handoffs]
        primary_role = next((item for item in roles if item.get("archetype") == "gatekeeper"), roles[-1] if roles else None)
        summary_text = (
            primary_role.get("summary")
            if isinstance(primary_role, Mapping)
            else ""
        ) or _clean_takeaway_text(run.get("summary_md"), max_length=220)
        passed = score_payload.get("passed")
        if passed is True:
            iteration_status = "passed"
        elif passed is False:
            iteration_status = "blocked"
        elif current_iter_id == iter_id and str(run.get("status") or "").strip() == "running":
            iteration_status = "running"
        elif roles:
            iteration_status = _normalize_takeaway_status(roles[-1].get("status"))
        else:
            iteration_status = "pending"
        iterations.append(
            {
                "iter": iter_id,
                "display_iter": _display_iter(iter_id),
                "status": iteration_status,
                "phase": str(summary_payload.get("phase") or "").strip(),
                "summary": summary_text,
                "timestamp": str(summary_payload.get("timestamp") or "").strip(),
                "composite_score": composite_score,
                "role_count": len(roles),
                "roles": roles,
            }
        )
    return iterations


def _build_legacy_iteration_takeaway(run: dict) -> dict | None:
    runs_dir_value = str(run.get("runs_dir") or "").strip()
    runs_dir = Path(runs_dir_value) if runs_dir_value else None
    verdict = run.get("last_verdict_json") or {}
    if not verdict and runs_dir is not None:
        verdict = _safe_read_json_file(runs_dir / "verifier_verdict.json") or _safe_read_json_file(runs_dir / "gatekeeper_verdict.json") or {}

    summary_excerpt = _summary_excerpt(run.get("summary_md"))
    roles: list[dict] = []
    priority_failures = verdict.get("priority_failures") if isinstance(verdict, Mapping) else []
    if isinstance(priority_failures, list):
        for index, failure in enumerate(priority_failures, start=1):
            if not isinstance(failure, Mapping):
                continue
            runtime_role = str(failure.get("role") or "").strip().lower()
            role_name = _display_role_name("", runtime_role=runtime_role)
            error_code = _clean_takeaway_text(failure.get("error_code"), max_length=80)
            attempts = failure.get("attempts")
            degraded = bool(failure.get("degraded"))
            support_bits = []
            if error_code:
                support_bits.append(error_code)
            if attempts not in {None, ""}:
                support_bits.append(f"attempts={attempts}")
            if degraded:
                support_bits.append("degraded")
            roles.append(
                {
                    "id": f"legacy-failure-{index}",
                    "step_id": "",
                    "step_order": index - 1,
                    "role_name": role_name,
                    "archetype": LEGACY_RUNTIME_ROLE_TO_ARCHETYPE.get(runtime_role, ""),
                    "status": "failed",
                    "summary": "Execution aborted before this role could produce a stable handoff.",
                    "blocking_item": " · ".join(support_bits),
                    "next_action": _clean_takeaway_text(
                        verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                        max_length=520,
                    ),
                    "composite_score": None,
                }
            )

    if verdict:
        blocking_note = (
            _clean_takeaway_text((verdict.get("blocking_issues") or [""])[0], max_length=140)
            or _clean_takeaway_text((verdict.get("hard_constraint_violations") or [""])[0], max_length=140)
        )
        roles.append(
            {
                "id": "legacy-gatekeeper",
                "step_id": "",
                "step_order": len(roles),
                "role_name": "GateKeeper",
                "archetype": "gatekeeper",
                "status": "passed" if verdict.get("passed") is True else "blocked",
                "summary": _clean_takeaway_text(verdict.get("decision_summary"), max_length=220) or summary_excerpt,
                "blocking_item": blocking_note,
                "next_action": _clean_takeaway_text(
                    verdict.get("feedback_to_builder") or verdict.get("feedback_to_generator"),
                    max_length=520,
                ),
                "composite_score": verdict.get("composite_score"),
            }
        )

    if not roles and not summary_excerpt:
        return None

    run_status = str(run.get("status") or "").strip().lower()
    if verdict.get("passed") is True:
        status = "passed"
    elif run_status == "running":
        status = "running"
    elif roles and roles[0].get("status") == "failed":
        status = "failed"
    elif verdict:
        status = "blocked"
    else:
        status = _normalize_takeaway_status(run_status)
    return {
        "iter": int(run.get("current_iter") or 0),
        "display_iter": _display_iter(run.get("current_iter")) or 1,
        "status": status,
        "phase": run_status,
        "summary": summary_excerpt or _clean_takeaway_text(verdict.get("decision_summary"), max_length=220),
        "timestamp": "",
        "composite_score": verdict.get("composite_score"),
        "role_count": len(roles),
        "roles": roles,
    }


def _build_run_key_takeaways(run: dict) -> dict:
    iterations = _build_structured_iteration_takeaways(run)
    if not iterations:
        legacy_iteration = _build_legacy_iteration_takeaway(run)
        if legacy_iteration:
            iterations = [legacy_iteration]
    iterations = sorted(iterations, key=lambda item: int(item.get("iter") or -1), reverse=True)
    latest = iterations[0] if iterations else None
    return {
        "build_dir": str(Path(str(run.get("workdir") or "")).expanduser().resolve()) if run.get("workdir") else "",
        "log_dir": str(Path(str(run.get("runs_dir") or "")).expanduser().resolve()) if run.get("runs_dir") else "",
        "iteration_count": len(iterations),
        "role_conclusion_count": sum(len(list(iteration.get("roles") or [])) for iteration in iterations),
        "latest_display_iter": latest.get("display_iter") if latest else None,
        "latest_status": latest.get("status") if latest else _normalize_takeaway_status(run.get("status")),
        "latest_summary": latest.get("summary") if latest else _summary_excerpt(run.get("summary_md")),
        "iterations": iterations,
    }


def _workflow_role_executor_summary(workflow: Mapping[str, object] | None, *, fallback_executor_kind: str = "codex") -> str:
    roles = workflow.get("roles", []) if isinstance(workflow, Mapping) else []
    if not isinstance(roles, list) or not roles:
        return "-"
    counts: dict[str, int] = {}
    for role in roles:
        if not isinstance(role, Mapping):
            continue
        raw_kind = str(role.get("executor_kind", "")).strip() or fallback_executor_kind
        try:
            label = executor_profile(raw_kind).label
        except ValueError:
            label = raw_kind or "-"
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return "-"
    return " · ".join(
        f"{label} x{count}" if count > 1 else label
        for label, count in counts.items()
    )


def _decorate_loop_overview(loop: dict) -> dict:
    latest_run_id = loop.get("latest_run_id")
    latest_status = loop.get("latest_status") or "draft"
    summary_excerpt = _summary_excerpt(loop.get("latest_summary_md"))
    workflow = loop.get("workflow_json") or {}
    hints = {
        "draft": ("还没有运行，先检查 spec 和工作目录。", "No run yet. Start by checking the spec and workdir."),
        "queued": ("已经进入队列，点进去看最新状态。", "Queued up. Open it to see the current state."),
        "running": ("正在推进中，点进去看实时进展。", "Actively progressing. Open it for live updates."),
        "succeeded": ("最近一次运行已经通过。", "The latest run passed."),
        "failed": ("最近一次运行失败，建议先看验证结论。", "The latest run failed. Start with the verdict."),
        "stopped": ("最近一次运行已停止。", "The latest run was stopped."),
    }
    hint_zh, hint_en = hints.get(latest_status, hints["draft"])
    return {
        **loop,
        "role_executor_summary": _workflow_role_executor_summary(workflow, fallback_executor_kind=loop.get("executor_kind", "codex")),
        "role_count": len(workflow.get("roles", []) if isinstance(workflow, Mapping) else []),
        "step_count": len(workflow.get("steps", []) if isinstance(workflow, Mapping) else []),
        "display_iter": _display_iter(loop.get("latest_current_iter")),
        "card_href": f"/runs/{latest_run_id}" if latest_run_id else f"/loops/{loop['id']}",
        "card_hint_zh": hint_zh,
        "card_hint_en": hint_en,
        "card_excerpt": summary_excerpt,
    }


def _decorate_run_overview(run: dict) -> dict:
    workflow = run.get("workflow_json") or {}
    return {
        **run,
        "role_executor_summary": _workflow_role_executor_summary(workflow, fallback_executor_kind=run.get("executor_kind", "codex")),
        "display_iter": _display_iter(run.get("current_iter")),
        "summary_excerpt": _summary_excerpt(run.get("summary_md")),
    }


def _progress_stage_seed(run: Mapping[str, object] | None) -> list[dict[str, str]]:
    workflow = run.get("workflow_json") if isinstance(run, Mapping) else {}
    roles = workflow.get("roles", []) if isinstance(workflow, Mapping) else []
    steps = workflow.get("steps", []) if isinstance(workflow, Mapping) else []
    role_by_id = {
        str(role.get("id") or "").strip(): role
        for role in roles
        if isinstance(role, Mapping) and str(role.get("id") or "").strip()
    }

    stages = [
        {
            "key": "checks",
            "label": "Checks",
            "kind": "checks",
        }
    ]
    for step in steps:
        if not isinstance(step, Mapping):
            continue
        step_id = str(step.get("id") or "").strip()
        if not step_id:
            continue
        role = role_by_id.get(str(step.get("role_id") or "").strip(), {})
        archetype = str(role.get("archetype") or "").strip()
        fallback_name = display_name_for_archetype(archetype, locale="en") if archetype else step_id
        label = normalize_role_display_name(str(role.get("name") or "").strip(), archetype) or fallback_name
        stages.append(
            {
                "key": f"step:{step_id}",
                "label": label,
                "kind": "workflow_step",
            }
        )
    stages.append(
        {
            "key": "finished",
            "label": "Done",
            "kind": "finished",
        }
    )
    return [
        {
            **stage,
            "sequence": index + 1,
        }
        for index, stage in enumerate(stages)
    ]


def _build_run_summary_snapshot(run: dict) -> dict:
    verdict = run.get("last_verdict_json") or {}
    failed_count = len(verdict.get("failed_check_ids") or [])
    composite_score = verdict.get("composite_score")
    passed = verdict.get("passed")
    if passed is True:
        verdict_title = ("最新结论：已通过", "Latest verdict: passed")
        verdict_note = ("关键 checks 都已通过，可以继续扩展目标。", "All key checks are passing. You can safely expand the target.")
    elif passed is False:
        verdict_title = ("最新结论：未通过", "Latest verdict: not passed")
        verdict_note = (
            f"还有 {failed_count} 条 checks 没过，优先看失败点。",
            f"{failed_count} check(s) are still failing. Start with the misses.",
        )
    else:
        verdict_title = ("还没有结论", "No verdict yet")
        verdict_note = ("GateKeeper 产出后这里会更新。", "This updates once the GateKeeper produces a verdict.")

    status_notes = {
        "queued": ("运行已创建，正在等待执行。", "The run is created and waiting to start."),
        "running": ("当前 run 正在推进，下面的摘要会持续更新。", "This run is in progress and the summary will keep updating."),
        "succeeded": ("这次 run 已顺利结束。", "This run finished successfully."),
        "failed": ("这次 run 已失败结束。", "This run finished with a failure."),
        "stopped": ("这次 run 已被手动停止。", "This run was stopped manually."),
        "draft": ("运行还没有真正开始。", "The run has not started yet."),
    }
    status = run.get("status") or "draft"
    status_note = status_notes.get(status, status_notes["draft"])

    return {
        "display_iter": _display_iter(run.get("current_iter")),
        "summary_excerpt": _summary_excerpt(run.get("summary_md")),
        "summary_empty_zh": "还没有稳定输出。",
        "summary_empty_en": "No substantial output yet.",
        "status_note_zh": status_note[0],
        "status_note_en": status_note[1],
        "verdict_title_zh": verdict_title[0],
        "verdict_title_en": verdict_title[1],
        "verdict_note_zh": verdict_note[0],
        "verdict_note_en": verdict_note[1],
        "failed_count": failed_count,
        "composite_score": composite_score,
    }
