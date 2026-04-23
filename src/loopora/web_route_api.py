from __future__ import annotations

from fastapi import FastAPI

from loopora.web_route_context import WebRouteContext
from loopora.web_route_editor_api import register_editor_api_routes
from loopora.web_route_run_api import register_run_api_routes


def register_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    register_run_api_routes(app, ctx)
    register_editor_api_routes(app, ctx)
