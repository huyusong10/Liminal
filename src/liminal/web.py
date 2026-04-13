from __future__ import annotations

import json
import time
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from liminal.skills import install_spec_skill, list_spec_skill_targets
from liminal.service import LiminalError, create_service
from liminal.specs import SpecError, init_spec_file, read_and_compile
from liminal.system_dialogs import SystemDialogError, pick_directory, pick_file, pick_save_file

DEFAULT_LOOP_FORM = {
    "name": "",
    "workdir": "",
    "spec_path": "",
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
    "stop_requested",
    "run_aborted",
    "run_finished",
}

RUN_ARTIFACT_SPECS = (
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


def build_app(service=None) -> FastAPI:
    app = FastAPI(title="Liminal")
    app.state.service = service or create_service()
    package_root = Path(__file__).parent
    templates = Jinja2Templates(directory=str(package_root / "templates"))
    app.mount("/static", StaticFiles(directory=str(package_root / "static")), name="static")
    app.mount("/logo", StaticFiles(directory=str(package_root / "assets" / "logo")), name="logo")

    def svc():
        return app.state.service

    def json_error(message: str, status_code: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

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
            },
        )

    def render_tools(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "tools.html",
            {
                "request": request,
                "skill_targets": list_spec_skill_targets(),
            },
        )

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
        loops = svc().list_loops()
        return templates.TemplateResponse(request, "index.html", {"request": request, "loops": loops})

    @app.get("/loops/new", response_class=HTMLResponse)
    async def new_loop(request: Request) -> HTMLResponse:
        return render_new_loop(request)

    @app.get("/tools", response_class=HTMLResponse)
    async def tools_page(request: Request) -> HTMLResponse:
        return render_tools(request)

    @app.get("/loops/{loop_id}", response_class=HTMLResponse)
    async def loop_detail(request: Request, loop_id: str) -> HTMLResponse:
        loop = svc().get_loop(loop_id)
        latest_run = loop["runs"][0] if loop["runs"] else None
        return templates.TemplateResponse(
            request,
            "loop_detail.html",
            {"request": request, "loop": loop, "latest_run": latest_run},
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
    async def api_run_stream(run_id: str, after_id: int = 0) -> StreamingResponse:
        def event_stream():
            last_id = after_id
            while True:
                events = svc().stream_events(run_id, after_id=last_id)
                for event in events:
                    last_id = event["id"]
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
        selected = pick_directory(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-file")
    async def api_pick_spec_file(start_path: str = "") -> JSONResponse:
        selected = pick_file(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-save-path")
    async def api_pick_spec_save_path(start_path: str = "") -> JSONResponse:
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
    if not name:
        raise LiminalError("name is required")
    if not workdir:
        raise LiminalError("workdir is required")
    if not spec_path:
        raise LiminalError("spec path is required")

    loop_kwargs = {
        "name": name,
        "spec_path": Path(spec_path),
        "workdir": Path(workdir),
        "model": str(payload.get("model", "gpt-5.4")).strip() or "gpt-5.4",
        "reasoning_effort": str(payload.get("reasoning_effort", "medium")).strip() or "medium",
        "max_iters": int(payload.get("max_iters", 8)),
        "max_role_retries": int(payload.get("max_role_retries", 2)),
        "delta_threshold": float(payload.get("delta_threshold", 0.005)),
        "trigger_window": int(payload.get("trigger_window", 4)),
        "regression_window": int(payload.get("regression_window", 2)),
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
    elif event["event_type"] == "run_finished":
        title = f"Run {payload.get('status', 'finished')}"
        reason = str(payload.get("reason", "")).strip()
        iter_id = payload.get("iter")
        if reason:
            detail = reason
        elif iter_id is not None:
            detail = f"iter={iter_id}"

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
