from __future__ import annotations

import html
import ipaddress
import json
import re
import time
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from liminal.providers import executor_profile, list_executor_profiles
from liminal.skills import install_spec_skill, list_spec_skill_targets
from liminal.service import LiminalError, create_service
from liminal.specs import SpecError, init_spec_file, read_and_compile
from liminal.system_dialogs import SystemDialogError, pick_directory, pick_file, pick_save_file

AUTH_COOKIE_NAME = "liminal_auth"

DEFAULT_LOOP_FORM = {
    "name": "",
    "workdir": "",
    "spec_path": "",
    "executor_kind": "codex",
    "executor_mode": "preset",
    "command_cli": "codex",
    "command_args_text": "",
    "model": "gpt-5.4",
    "reasoning_effort": "medium",
    "max_iters": 8,
    "max_role_retries": 2,
    "delta_threshold": 0.005,
    "trigger_window": 4,
    "regression_window": 2,
    "start_immediately": True,
}

TIMELINE_EVENT_TYPES = {
    "run_started",
    "checks_resolved",
    "role_execution_summary",
    "role_degraded",
    "challenger_done",
    "workspace_guard_triggered",
    "stop_requested",
    "run_aborted",
    "run_finished",
}

RUN_ARTIFACT_SPECS = (
    {
        "id": "original-spec",
        "filename": "spec.md",
        "label_zh": "原始 Spec",
        "label_en": "Original spec",
        "description_zh": "这次 run 开始时冻结保存的原始 Markdown spec。",
        "description_en": "The original Markdown spec snapshot frozen at the start of this run.",
    },
    {
        "id": "summary",
        "filename": "summary.md",
        "label_zh": "运行摘要",
        "label_en": "Summary",
        "description_zh": "当前 run 的摘要结论。",
        "description_en": "The current run summary.",
    },
    {
        "id": "compiled-spec",
        "filename": "compiled_spec.json",
        "label_zh": "编译后 Spec",
        "label_en": "Compiled spec",
        "description_zh": "本次 run 实际使用的 Goal、Checks 和 Constraints。",
        "description_en": "The Goal, Checks, and Constraints used by this run.",
    },
    {
        "id": "generator-output",
        "filename": "generator_output.json",
        "label_zh": "生成输出",
        "label_en": "Generator output",
        "description_zh": "Generator 这轮改了什么、没改什么、做了哪些假设。",
        "description_en": "What the Generator changed, skipped, and assumed.",
    },
    {
        "id": "tester-output",
        "filename": "tester_output.json",
        "label_zh": "测试输出",
        "label_en": "Tester output",
        "description_zh": "Tester 的检查结果、证据和观察。",
        "description_en": "The Tester's results, evidence, and observations.",
    },
    {
        "id": "verifier-verdict",
        "filename": "verifier_verdict.json",
        "label_zh": "验证结论",
        "label_en": "Verifier verdict",
        "description_zh": "Verifier 对是否通过的最终裁决。",
        "description_en": "The Verifier's final pass/fail judgement.",
    },
    {
        "id": "challenger-seed",
        "filename": "challenger_seed.json",
        "label_zh": "挑战输出",
        "label_en": "Challenger output",
        "description_zh": "只有进入停滞或回退时才会生成的新方向建议。",
        "description_en": "A direction shift that only appears on plateau or regression.",
    },
)


def build_app(service=None, *, bind_host: str = "127.0.0.1", bind_port: int = 8742, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="Liminal")
    app.state.service = service or create_service()
    access_state = _build_access_state(bind_host=bind_host, bind_port=bind_port, auth_token=auth_token)
    app.state.access_state = access_state
    package_root = Path(__file__).parent
    templates = Jinja2Templates(directory=str(package_root / "templates"))
    app.mount("/static", StaticFiles(directory=str(package_root / "static")), name="static")
    app.mount("/logo", StaticFiles(directory=str(package_root / "assets" / "logo")), name="logo")

    def svc():
        return app.state.service

    def json_error(message: str, status_code: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        expected_token = access_state["auth_token"]
        if not expected_token:
            return await call_next(request)

        provided_token = _extract_request_token(request)
        if provided_token != expected_token:
            return _auth_required_response(request)

        response = await call_next(request)
        if request.cookies.get(AUTH_COOKIE_NAME) != expected_token:
            response.set_cookie(AUTH_COOKIE_NAME, expected_token, httponly=True, samesite="lax")
        return response

    def render_new_loop(
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "new_loop.html",
            {
                "request": request,
                "form_values": _normalize_loop_form(values),
                "form_error": form_error,
                "executor_profiles": list_executor_profiles(),
                "access_state": access_state,
            },
        )

    def render_tools(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "tools.html",
            {
                "request": request,
                "skill_targets": list_spec_skill_targets(),
                "access_state": access_state,
            },
        )

    def render_auth_required(request: Request) -> HTMLResponse:
        url_path = html.escape(request.url.path)
        return HTMLResponse(
            f"""
            <!doctype html>
            <html lang="zh-CN">
            <head>
              <meta charset="utf-8" />
              <meta name="viewport" content="width=device-width, initial-scale=1" />
              <title>Liminal · Auth required</title>
              <style>
                body {{
                  margin: 0;
                  min-height: 100vh;
                  display: grid;
                  place-items: center;
                  padding: 24px;
                  background: linear-gradient(180deg, #fffaf2 0%, #fff4e8 100%);
                  color: #2d2215;
                  font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                }}
                main {{
                  width: min(640px, 100%);
                  padding: 28px;
                  border-radius: 24px;
                  background: rgba(255, 255, 255, 0.82);
                  border: 1px solid rgba(93, 76, 62, 0.12);
                  box-shadow: 0 18px 45px rgba(45, 34, 21, 0.12);
                }}
                h1 {{ margin: 0 0 12px; font-size: 2rem; }}
                p {{ margin: 0 0 10px; line-height: 1.7; }}
                code {{
                  display: inline-block;
                  padding: 2px 8px;
                  border-radius: 999px;
                  background: rgba(214, 106, 54, 0.12);
                }}
              </style>
            </head>
            <body>
              <main>
                <h1>需要访问令牌 / Auth token required</h1>
                <p>这个 Liminal 实例正在网络模式下运行，所以先带上令牌再进来比较稳妥。</p>
                <p>This Liminal instance is exposed over the network, so it expects an auth token before letting requests through.</p>
                <p>把令牌加到地址后面访问一次即可，例如：<code>{url_path}?token=&lt;your-token&gt;</code></p>
                <p>You can also send it as <code>Authorization: Bearer &lt;your-token&gt;</code> or <code>X-Liminal-Token</code>.</p>
              </main>
            </body>
            </html>
            """,
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

    @app.exception_handler(LiminalError)
    async def liminal_error_handler(_: Request, exc: LiminalError) -> JSONResponse:
        return json_error(str(exc), status_code=400)

    @app.exception_handler(SpecError)
    async def spec_error_handler(_: Request, exc: SpecError) -> JSONResponse:
        return json_error(str(exc), status_code=400)

    @app.exception_handler(SystemDialogError)
    async def system_dialog_error_handler(_: Request, exc: SystemDialogError) -> JSONResponse:
        return json_error(str(exc), status_code=400)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        loops = [_decorate_loop_overview(loop) for loop in svc().list_loops()]
        return templates.TemplateResponse(request, "index.html", {"request": request, "loops": loops, "access_state": access_state})

    @app.get("/loops/new", response_class=HTMLResponse)
    async def new_loop(request: Request) -> HTMLResponse:
        return render_new_loop(request)

    @app.get("/tools", response_class=HTMLResponse)
    async def tools_page(request: Request) -> HTMLResponse:
        return render_tools(request)

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
                "loop": {**loop, "runs": runs, "executor_label": executor_profile(loop.get("executor_kind", "codex")).label},
                "latest_run": latest_run,
                "summary_snapshot": _build_run_summary_snapshot(latest_run) if latest_run else None,
                "access_state": access_state,
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
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
                "timeline_events": events[-40:],
                "console_events": seed_events[-160:],
                "latest_event_id": latest_event_id,
                "run_artifacts": _list_run_artifacts(run),
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

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    async def api_run_artifact_preview(run_id: str, artifact_id: str) -> JSONResponse:
        run = svc().get_run(run_id)
        artifact = _artifact_spec_or_404(artifact_id)
        artifact_path = Path(run["runs_dir"]) / artifact["filename"]
        relative_path = f"runs/{run_id}/{artifact['filename']}"
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
        preview = svc().preview_file(run_id, root="liminal", relative_path=relative_path)
        preview["artifact"] = {
            **artifact,
            "path": relative_path,
        }
        return JSONResponse(preview)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}/download")
    async def api_run_artifact_download(run_id: str, artifact_id: str) -> FileResponse:
        run = svc().get_run(run_id)
        artifact = _artifact_spec_or_404(artifact_id)
        artifact_path = Path(run["runs_dir"]) / artifact["filename"]
        if not artifact_path.exists():
            raise HTTPException(status_code=404, detail="artifact not found")
        return FileResponse(artifact_path.resolve())

    @app.get("/api/runs/{run_id}/stream")
    async def api_run_stream(request: Request, run_id: str, after_id: int = 0) -> StreamingResponse:
        svc().get_run(run_id)
        last_event_header = str(request.headers.get("last-event-id", "")).strip()
        if last_event_header:
            try:
                after_id = max(after_id, int(last_event_header))
            except ValueError:
                pass

        def event_stream():
            last_id = after_id
            while True:
                events = svc().stream_events(run_id, after_id=last_id)
                for event in events:
                    last_id = event["id"]
                    yield f"id: {event['id']}\n"
                    yield f"event: {event['event_type']}\n"
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                run = svc().get_run(run_id)
                if run["status"] in {"succeeded", "failed", "stopped"} and not events:
                    break
                yield ": keep-alive\n\n"
                time.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/files")
    async def api_preview_file(
        run_id: str,
        root: str = Query(default="workdir", pattern="^(workdir|liminal)$"),
        path: str = "",
    ) -> JSONResponse:
        return JSONResponse(svc().preview_file(run_id, root=root, relative_path=path))

    @app.get("/api/files/download")
    async def api_download_file(
        run_id: str,
        root: str = Query(default="workdir", pattern="^(workdir|liminal)$"),
        path: str = "",
    ) -> FileResponse:
        preview = svc().preview_file(run_id, root=root, relative_path=path)
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

    @app.get("/api/skills/liminal-spec")
    async def api_spec_skill_targets() -> JSONResponse:
        return JSONResponse({"skill_name": "liminal-spec", "targets": list_spec_skill_targets()})

    @app.post("/api/skills/liminal-spec/install")
    async def api_install_spec_skill(request: Request) -> JSONResponse:
        payload = await request.json()
        target = str(payload.get("target", "")).strip().lower()
        try:
            result = install_spec_skill(target)
        except ValueError as exc:
            return json_error(str(exc))
        return JSONResponse({"result": result, "targets": list_spec_skill_targets()}, status_code=201)

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
        except (LiminalError, SpecError, FileExistsError, OSError, ValueError) as exc:
            return render_new_loop(request, values=values, form_error=str(exc))

    return app


def _loop_payload_from_mapping(payload: Mapping[str, object]) -> tuple[dict[str, object], bool]:
    name = str(payload.get("name", "")).strip()
    workdir = str(payload.get("workdir", "")).strip()
    spec_path = str(payload.get("spec_path", "")).strip()
    executor_kind = str(payload.get("executor_kind", "codex")).strip() or "codex"
    executor_mode = str(payload.get("executor_mode", "preset")).strip() or "preset"
    try:
        profile = executor_profile(executor_kind)
    except ValueError as exc:
        raise LiminalError(str(exc)) from exc
    model = str(payload.get("model", "")).strip()
    reasoning_effort = str(payload.get("reasoning_effort", "")).strip()
    command_cli = str(payload.get("command_cli", "")).strip()
    command_args_text = str(payload.get("command_args_text", ""))
    if not name:
        raise LiminalError("name is required")
    if not workdir:
        raise LiminalError("workdir is required")
    if not spec_path:
        raise LiminalError("spec path is required")

    try:
        max_iters = int(payload.get("max_iters", 8))
        max_role_retries = int(payload.get("max_role_retries", 2))
        delta_threshold = float(payload.get("delta_threshold", 0.005))
        trigger_window = int(payload.get("trigger_window", 4))
        regression_window = int(payload.get("regression_window", 2))
    except (TypeError, ValueError) as exc:
        raise LiminalError("numeric loop settings must use valid numbers") from exc

    loop_kwargs = {
        "name": name,
        "spec_path": Path(spec_path),
        "workdir": Path(workdir),
        "executor_kind": executor_kind,
        "executor_mode": executor_mode,
        "command_cli": command_cli if command_cli else profile.cli_name,
        "command_args_text": command_args_text,
        "model": model if model or profile.default_model == "" else profile.default_model,
        "reasoning_effort": reasoning_effort if reasoning_effort or profile.effort_default == "" else profile.effort_default,
        "max_iters": max_iters,
        "max_role_retries": max_role_retries,
        "delta_threshold": delta_threshold,
        "trigger_window": trigger_window,
        "regression_window": regression_window,
        "role_models": payload.get("role_models") or {},
    }
    return loop_kwargs, _coerce_bool(payload.get("start_immediately"))


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
    elif event["event_type"] == "challenger_done":
        title = "Challenger suggested a new direction"
        detail = str(payload.get("mode", "")).strip()
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
            detail = reason
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
    if not str(normalized.get("command_cli", "")).strip():
        try:
            normalized["command_cli"] = executor_profile(str(normalized.get("executor_kind", "codex"))).cli_name
        except ValueError:
            normalized["command_cli"] = "codex"
    normalized["start_immediately"] = _coerce_bool(normalized.get("start_immediately", True))
    return normalized


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

    header_token = request.headers.get("x-liminal-token", "").strip()
    if header_token:
        return header_token

    query_token = request.query_params.get("token", "").strip()
    if query_token:
        return query_token

    cookie_token = request.cookies.get(AUTH_COOKIE_NAME, "").strip()
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


def _list_run_artifacts(run: dict) -> list[dict]:
    run_dir = Path(run["runs_dir"])
    artifacts = []
    for artifact in RUN_ARTIFACT_SPECS:
        path = run_dir / artifact["filename"]
        artifacts.append(
            {
                **artifact,
                "path": str(path),
                "available": path.exists(),
            }
        )
    return artifacts


def _artifact_spec_or_404(artifact_id: str) -> dict:
    for artifact in RUN_ARTIFACT_SPECS:
        if artifact["id"] == artifact_id:
            return artifact
    raise HTTPException(status_code=404, detail="unknown artifact")


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
    text = text.removeprefix("Liminal Run Summary").strip()
    return _truncate_text(text, max_length=170) if text else ""


def _decorate_loop_overview(loop: dict) -> dict:
    latest_run_id = loop.get("latest_run_id")
    latest_status = loop.get("latest_status") or "draft"
    summary_excerpt = _summary_excerpt(loop.get("latest_summary_md"))
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
        "executor_label": executor_profile(loop.get("executor_kind", "codex")).label,
        "executor_mode": loop.get("executor_mode", "preset"),
        "display_iter": _display_iter(loop.get("latest_current_iter")),
        "card_href": f"/runs/{latest_run_id}" if latest_run_id else f"/loops/{loop['id']}",
        "card_hint_zh": hint_zh,
        "card_hint_en": hint_en,
        "card_excerpt": summary_excerpt,
    }


def _decorate_run_overview(run: dict) -> dict:
    return {
        **run,
        "executor_label": executor_profile(run.get("executor_kind", "codex")).label,
        "executor_mode": run.get("executor_mode", "preset"),
        "display_iter": _display_iter(run.get("current_iter")),
        "summary_excerpt": _summary_excerpt(run.get("summary_md")),
    }


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
        verdict_note = ("Verifier 产出后这里会更新。", "This updates once the Verifier produces a verdict.")

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
