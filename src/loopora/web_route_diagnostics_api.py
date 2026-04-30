from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from loopora.web_route_context import WebRouteContext


def register_diagnostics_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/diagnostics/local-assets")
    async def api_local_asset_diagnostics() -> JSONResponse:
        return JSONResponse(ctx.svc().local_asset_diagnostics())
