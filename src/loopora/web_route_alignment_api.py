from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from loopora.diagnostics import log_exception
from loopora.service_alignment import ALIGNMENT_ACTIVE_STATUSES
from loopora.web_route_context import WebRouteContext


def register_alignment_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/alignments/sessions")
    async def api_create_alignment_session(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        message = str(payload.get("message", "") or payload.get("user_message", "") or "")
        workdir_text = str(payload.get("workdir", "")).strip()
        if not workdir_text:
            return ctx.json_error("workdir is required")
        session = ctx.svc().create_alignment_session(
            workdir=Path(workdir_text),
            message=message,
            executor_kind=str(payload.get("executor_kind", "codex")).strip() or "codex",
            executor_mode=str(payload.get("executor_mode", "preset")).strip() or "preset",
            command_cli=str(payload.get("command_cli", "")).strip(),
            command_args_text=str(payload.get("command_args_text", "")),
            model=str(payload.get("model", "")).strip(),
            reasoning_effort=str(payload.get("reasoning_effort", "")).strip(),
            start_immediately=True,
        )
        return JSONResponse({"session": session}, status_code=201)

    @app.get("/api/alignments/sessions")
    async def api_list_alignment_sessions(limit: int = 30) -> JSONResponse:
        return JSONResponse({"sessions": ctx.svc().list_alignment_sessions(limit=limit)})

    @app.get("/api/alignments/sessions/{session_id}")
    async def api_get_alignment_session(session_id: str) -> JSONResponse:
        return JSONResponse({"session": ctx.svc().get_alignment_session(session_id)})

    @app.delete("/api/alignments/sessions/{session_id}")
    async def api_delete_alignment_session(session_id: str) -> JSONResponse:
        return JSONResponse({"deleted": ctx.svc().delete_alignment_session(session_id)})

    @app.post("/api/alignments/sessions/{session_id}/messages")
    async def api_append_alignment_message(session_id: str, request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        session = ctx.svc().append_alignment_message(session_id, str(payload.get("message", "")))
        return JSONResponse({"session": session})

    @app.post("/api/alignments/sessions/{session_id}/cancel")
    async def api_cancel_alignment_session(session_id: str) -> JSONResponse:
        return JSONResponse({"session": ctx.svc().cancel_alignment_session(session_id)})

    @app.get("/api/alignments/sessions/{session_id}/events")
    async def api_alignment_events(session_id: str, after_id: int = 0, limit: int = 200) -> JSONResponse:
        return JSONResponse(ctx.svc().list_alignment_events(session_id, after_id=after_id, limit=limit))

    @app.get("/api/alignments/sessions/{session_id}/stream")
    async def api_alignment_stream(request: Request, session_id: str, after_id: int = 0) -> StreamingResponse:
        ctx.svc().get_alignment_session(session_id)
        after_id = _resolve_alignment_stream_after_id(request, after_id=after_id)

        def event_stream():
            last_id = after_id
            while True:
                try:
                    events = ctx.svc().list_alignment_events(session_id, after_id=last_id)
                    for event in events:
                        last_id = event["id"]
                        yield f"id: {event['id']}\n"
                        yield f"event: {event['event_type']}\n"
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    session = ctx.svc().get_alignment_session(session_id)
                except Exception as exc:
                    log_exception(
                        ctx.logger,
                        "web.alignment_stream.failed",
                        "Alignment event stream failed",
                        error=exc,
                        session_id=session_id,
                        after_id=last_id,
                    )
                    payload = {"session_id": session_id, "after_id": last_id, "error": str(exc)}
                    yield "event: stream_error\n"
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                if session["status"] not in ALIGNMENT_ACTIVE_STATUSES and not events:
                    break
                yield ": keep-alive\n\n"
                time.sleep(1)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/api/alignments/sessions/{session_id}/bundle")
    async def api_alignment_bundle(session_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_alignment_bundle(session_id))

    @app.post("/api/alignments/sessions/{session_id}/bundle/sync")
    async def api_sync_alignment_bundle(session_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().sync_alignment_bundle_from_file(session_id))

    @app.post("/api/alignments/sessions/{session_id}/import")
    async def api_import_alignment_bundle(session_id: str, request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        start_immediately = _coerce_bool(payload.get("start_immediately", True))
        result = ctx.svc().import_alignment_bundle(session_id, start_immediately=start_immediately)
        return JSONResponse(result, status_code=201)


def _resolve_alignment_stream_after_id(request: Request, *, after_id: int) -> int:
    last_event_header = str(request.headers.get("last-event-id", "")).strip()
    if not last_event_header:
        return after_id
    try:
        return max(after_id, int(last_event_header))
    except ValueError:
        return after_id


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
