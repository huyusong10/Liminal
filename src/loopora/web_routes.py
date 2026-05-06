from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI, Request
from fastapi.responses import Response

from loopora.web_route_api import register_api_routes
from loopora.web_route_context import WebRouteContext
from loopora.web_route_context_base import WebRouteDependencies, web_route_dependencies_from_args
from loopora.web_route_errors import register_error_handlers
from loopora.web_route_forms import register_form_routes
from loopora.web_route_pages import register_page_routes


def register_web_routes(
    app: FastAPI,
    dependencies: WebRouteDependencies | None = None,
    **raw_dependencies: object,
) -> Callable[[Request], Response]:
    dependencies = web_route_dependencies_from_args(dependencies, raw_dependencies)
    ctx = WebRouteContext(
        app=app,
        dependencies=dependencies,
    )
    register_error_handlers(app, ctx)
    register_page_routes(app, ctx)
    register_api_routes(app, ctx)
    register_form_routes(app, ctx)
    return ctx.auth_required_response
