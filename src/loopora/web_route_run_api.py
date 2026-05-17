from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from loopora.branding import FILE_ROOT_QUERY_PATTERN
from loopora.diagnostics import log_exception
from loopora.run_artifacts import list_run_artifacts as _list_run_artifacts
from loopora.run_takeaways import build_run_key_takeaways
from loopora.web_overviews import (
    _artifact_record_or_404,
    _format_timeline_event,
)
from loopora.web_inputs import _loop_payload_from_mapping
from loopora.web_route_context import WebRouteContext
from loopora.web_streaming import MAX_EVENT_CURSOR_ID, stream_error_payload
from loopora.web_url_utils import attachment_content_disposition


def register_run_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    _register_loop_api_routes(app, ctx)
    _register_run_observation_api_routes(app, ctx)
    _register_run_artifact_api_routes(app, ctx)
    _register_run_stream_api_route(app, ctx)
    _register_file_api_routes(app, ctx)


def _register_loop_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/loops")
    async def api_create_loop(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        loop_kwargs, start_immediately = _loop_payload_from_mapping(payload)
        loop = ctx.svc().create_loop(**loop_kwargs)
        if start_immediately:
            run = ctx.svc().start_run(loop["id"])
            ctx.svc().start_run_async(run["id"])
            return JSONResponse({"loop": loop, "run": run, "redirect_url": f"/runs/{run['id']}"}, status_code=201)
        return JSONResponse({"loop": loop, "redirect_url": f"/loops/{loop['id']}"}, status_code=201)

    @app.get("/api/loops")
    async def api_list_loops() -> JSONResponse:
        return JSONResponse(ctx.svc().list_loops())

    @app.get("/api/runtime/activity")
    async def api_runtime_activity() -> JSONResponse:
        return JSONResponse(ctx.svc().get_runtime_activity())

    @app.get("/api/loops/{loop_id}")
    async def api_get_loop(loop_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_loop(loop_id))

    @app.delete("/api/loops/{loop_id}")
    async def api_delete_loop(loop_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().delete_loop(loop_id))

    @app.post("/api/loops/{loop_id}/runs")
    async def api_start_run(loop_id: str) -> JSONResponse:
        agent_entry_start = ctx.svc().agent_entry_loop_start_projection(loop_id)
        if agent_entry_start:
            return JSONResponse(
                {
                    "error": "agent-first Loop runs must be started or continued with /loopora-loop in the host Agent",
                    "agent_entry_start": agent_entry_start,
                },
                status_code=409,
            )
        run = ctx.svc().start_run(loop_id)
        ctx.svc().start_run_async(run["id"])
        return JSONResponse(run, status_code=201)


def _register_run_observation_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/runs/{run_id}")
    async def api_get_run(run_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_run(run_id))

    @app.get("/api/runs/{run_id}/observation-snapshot")
    async def api_run_observation_snapshot(run_id: str) -> JSONResponse:
        snapshot = ctx.svc().run_observation_snapshot(run_id)
        return JSONResponse(
            {
                **snapshot,
                "timeline_events": [_format_timeline_event(event) for event in snapshot["timeline_events"]],
            }
        )

    @app.post("/api/runs/{run_id}/stop")
    async def api_stop_run(run_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().stop_run(run_id))

    @app.get("/api/runs/{run_id}/events")
    async def api_run_events(
        run_id: str,
        after_id: int = Query(default=0, ge=0, le=MAX_EVENT_CURSOR_ID),
        limit: int = Query(default=200, ge=1, le=5000),
    ) -> JSONResponse:
        latest_event_id = _latest_run_event_id(ctx, run_id)
        if after_id > latest_event_id:
            return ctx.json_error("event cursor is out of range")
        return JSONResponse(ctx.svc().stream_events(run_id, after_id=after_id, limit=limit))


def _register_run_artifact_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/runs/{run_id}/artifacts")
    async def api_run_artifacts(run_id: str) -> JSONResponse:
        run = ctx.svc().get_run(run_id)
        return JSONResponse(_list_run_artifacts(run))

    @app.get("/api/runs/{run_id}/key-takeaways")
    async def api_run_key_takeaways(run_id: str) -> JSONResponse:
        run = ctx.svc().get_run(run_id)
        return JSONResponse(build_run_key_takeaways(run))

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}")
    async def api_run_artifact_preview(run_id: str, artifact_id: str) -> JSONResponse:
        run = ctx.svc().get_run(run_id)
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
        preview = ctx.svc().preview_file(run_id, root="loopora", relative_path=relative_path)
        preview["artifact"] = {
            **artifact,
            "path": relative_path,
        }
        return JSONResponse(preview)

    @app.get("/api/runs/{run_id}/artifacts/{artifact_id}/download")
    async def api_run_artifact_download(run_id: str, artifact_id: str) -> FileResponse:
        run = ctx.svc().get_run(run_id)
        artifact = _artifact_record_or_404(run, artifact_id)
        artifact_path = Path(run["runs_dir"]) / artifact["relative_path"]
        if not artifact_path.exists():
            raise HTTPException(status_code=404, detail="artifact not found")
        relative_path = f"runs/{run_id}/{artifact['relative_path']}"
        return _attachment_file_response(ctx.svc().download_file_path(run_id, root="loopora", relative_path=relative_path))


def _register_run_stream_api_route(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/runs/{run_id}/stream")
    async def api_run_stream(
        request: Request,
        run_id: str,
        after_id: int = Query(default=0, ge=0, le=MAX_EVENT_CURSOR_ID),
    ) -> Response:
        latest_event_id = _latest_run_event_id(ctx, run_id)
        if after_id > latest_event_id:
            return ctx.json_error("event cursor is out of range")
        after_id = ctx.resolve_stream_after_id(
            request,
            run_id=run_id,
            after_id=after_id,
            latest_event_id=latest_event_id,
        )
        return StreamingResponse(_run_event_stream(ctx, run_id=run_id, after_id=after_id), media_type="text/event-stream")


def _register_file_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/files")
    async def api_preview_file(
        run_id: str,
        root: str = Query(default="workdir", pattern=FILE_ROOT_QUERY_PATTERN),
        path: str = "",
    ) -> JSONResponse:
        return JSONResponse(ctx.svc().preview_file(run_id, root=root, relative_path=path))

    @app.get("/api/files/download")
    async def api_download_file(
        run_id: str,
        root: str = Query(default="workdir", pattern=FILE_ROOT_QUERY_PATTERN),
        path: str = "",
    ) -> FileResponse:
        return _attachment_file_response(ctx.svc().download_file_path(run_id, root=root, relative_path=path))


def _attachment_file_response(path: Path) -> FileResponse:
    return FileResponse(
        path,
        media_type="application/octet-stream",
        headers={"Content-Disposition": attachment_content_disposition(path.name, default="download")},
    )


def _latest_run_event_id(ctx: WebRouteContext, run_id: str) -> int:
    return max(0, int(ctx.svc().latest_run_event_id(run_id) or 0))


def _run_event_stream(ctx: WebRouteContext, *, run_id: str, after_id: int) -> Iterator[str]:
    last_id = after_id
    while True:
        try:
            events = ctx.svc().stream_events(run_id, after_id=last_id)
            for event in events:
                last_id = event["id"]
                yield f"id: {event['id']}\n"
                yield f"event: {event['event_type']}\n"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            run = ctx.svc().get_run(run_id)
        except Exception as exc:  # noqa: BLE001 - SSE streams must surface failures as stream_error events.
            log_exception(
                ctx.logger,
                "web.run_stream.failed",
                "Run event stream failed",
                error=exc,
                run_id=run_id,
                after_id=last_id,
            )
            payload = stream_error_payload(owner_key="run_id", owner_id=run_id, after_id=last_id)
            yield "event: stream_error\n"
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            break
        if run["status"] in {"succeeded", "failed", "stopped"} and not events:
            break
        yield ": keep-alive\n\n"
        time.sleep(1)
