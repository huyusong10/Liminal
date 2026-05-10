from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from loopora.service import LooporaError
from loopora.web_route_context import WebRouteContext


def register_agent_adapter_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/agent-adapters")
    async def api_list_agent_adapters(workdir: str = "") -> JSONResponse:
        root = _adapter_workdir(workdir)
        try:
            result = {"workdir": str(root), "adapters": ctx.svc().list_agent_adapters(workdir=root)}
        except LooporaError as exc:
            return ctx.json_error_from_exception(exc)
        return JSONResponse(result)

    @app.get("/api/agent-adapters/{adapter}")
    async def api_get_agent_adapter(adapter: str, workdir: str = "") -> JSONResponse:
        root = _adapter_workdir(workdir)
        try:
            result = ctx.svc().get_agent_adapter(adapter, workdir=root)
        except LooporaError as exc:
            return ctx.json_error_from_exception(exc)
        return JSONResponse(result)

    @app.post("/api/agent-adapters/{adapter}/install")
    async def api_install_agent_adapter(adapter: str, request: Request) -> JSONResponse:
        try:
            payload = await ctx.read_json_mapping(request)
            root = _adapter_workdir(str(payload.get("workdir", "") or ""))
            result = ctx.svc().install_agent_adapter(adapter, workdir=root)
        except LooporaError as exc:
            return ctx.json_error_from_exception(exc)
        return JSONResponse(result)

    @app.post("/api/agent-adapters/{adapter}/uninstall")
    async def api_uninstall_agent_adapter(adapter: str, request: Request) -> JSONResponse:
        try:
            payload = await ctx.read_json_mapping(request)
            root = _adapter_workdir(str(payload.get("workdir", "") or ""))
            result = ctx.svc().uninstall_agent_adapter(adapter, workdir=root)
        except LooporaError as exc:
            return ctx.json_error_from_exception(exc)
        return JSONResponse(result)


def _adapter_workdir(value: str) -> Path:
    raw = str(value or "").strip()
    return Path(raw).expanduser().resolve() if raw else Path.cwd().resolve()
