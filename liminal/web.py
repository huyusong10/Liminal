from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from liminal.service import LiminalError, create_service


def build_app(service=None) -> FastAPI:
    app = FastAPI(title="Liminal")
    app.state.service = service or create_service()
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

    def svc():
        return app.state.service

    def json_error(message: str, status_code: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    @app.exception_handler(LiminalError)
    async def liminal_error_handler(_: Request, exc: LiminalError) -> JSONResponse:
        return json_error(str(exc), status_code=400)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        loops = svc().list_loops()
        return templates.TemplateResponse("index.html", {"request": request, "loops": loops})

    @app.get("/loops/new", response_class=HTMLResponse)
    async def new_loop(request: Request) -> HTMLResponse:
        return templates.TemplateResponse("new_loop.html", {"request": request})

    @app.get("/loops/{loop_id}", response_class=HTMLResponse)
    async def loop_detail(request: Request, loop_id: str) -> HTMLResponse:
        loop = svc().get_loop(loop_id)
        latest_run = loop["runs"][0] if loop["runs"] else None
        return templates.TemplateResponse(
            "loop_detail.html",
            {"request": request, "loop": loop, "latest_run": latest_run},
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        run = svc().get_run(run_id)
        events = svc().stream_events(run_id)
        return templates.TemplateResponse(
            "run_detail.html",
            {"request": request, "run": run, "events": events[-20:]},
        )

    @app.post("/api/loops")
    async def api_create_loop(request: Request) -> JSONResponse:
        payload = await request.json()
        loop = svc().create_loop(
            name=payload["name"],
            spec_path=Path(payload["spec_path"]),
            workdir=Path(payload["workdir"]),
            model=payload.get("model", "gpt-5.4"),
            reasoning_effort=payload.get("reasoning_effort", "medium"),
            max_iters=int(payload.get("max_iters", 8)),
            max_role_retries=int(payload.get("max_role_retries", 2)),
            delta_threshold=float(payload.get("delta_threshold", 0.005)),
            trigger_window=int(payload.get("trigger_window", 4)),
            regression_window=int(payload.get("regression_window", 2)),
            role_models=payload.get("role_models"),
        )
        if payload.get("start_immediately"):
            run = svc().start_run(loop["id"])
            svc().start_run_async(run["id"])
            return JSONResponse({"loop": loop, "run": run}, status_code=201)
        return JSONResponse(loop, status_code=201)

    @app.get("/api/loops")
    async def api_list_loops() -> JSONResponse:
        return JSONResponse(svc().list_loops())

    @app.get("/api/loops/{loop_id}")
    async def api_get_loop(loop_id: str) -> JSONResponse:
        return JSONResponse(svc().get_loop(loop_id))

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

    @app.get("/api/runs/{run_id}/stream")
    async def api_run_stream(run_id: str) -> StreamingResponse:
        def event_stream():
            last_id = 0
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

    @app.post("/loops/new")
    async def create_loop_from_form(request: Request) -> RedirectResponse:
        form = await request.form()
        loop = svc().create_loop(
            name=str(form["name"]),
            spec_path=Path(str(form["spec_path"])),
            workdir=Path(str(form["workdir"])),
            model=str(form.get("model", "gpt-5.4")),
            reasoning_effort=str(form.get("reasoning_effort", "medium")),
            max_iters=int(form.get("max_iters", 8)),
            max_role_retries=int(form.get("max_role_retries", 2)),
            delta_threshold=float(form.get("delta_threshold", 0.005)),
            trigger_window=int(form.get("trigger_window", 4)),
            regression_window=int(form.get("regression_window", 2)),
            role_models={},
        )
        if form.get("start_immediately"):
            run = svc().start_run(loop["id"])
            svc().start_run_async(run["id"])
            return RedirectResponse(url=f"/runs/{run['id']}", status_code=303)
        return RedirectResponse(url=f"/loops/{loop['id']}", status_code=303)

    return app
