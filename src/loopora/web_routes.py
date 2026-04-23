from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from loopora.web_route_api import register_api_routes
from loopora.web_route_context import WebRouteContext
from loopora.web_route_errors import register_error_handlers
from loopora.web_route_forms import register_form_routes
from loopora.web_route_pages import register_page_routes


def register_web_routes(
    app: FastAPI,
    *,
    templates: Jinja2Templates,
    access_state: Mapping[str, object],
    logger: logging.Logger,
    read_json_mapping: Callable[[Request], Awaitable[Mapping[str, object]]],
    resolve_stream_after_id: Callable[[Request], int] | Callable[..., int],
    pick_directory_dialog: Callable[[str | None], str | None],
    pick_file_dialog: Callable[[str | None], str | None],
    pick_save_file_dialog: Callable[[str | None], str | None] | Callable[..., str | None],
    reveal_path_callback: Callable[[str], str],
) -> Callable[[Request], Response]:
    ctx = WebRouteContext(
        app=app,
        templates=templates,
        access_state=access_state,
        logger=logger,
        read_json_mapping=read_json_mapping,
        resolve_stream_after_id=resolve_stream_after_id,
        pick_directory_dialog=pick_directory_dialog,
        pick_file_dialog=pick_file_dialog,
        pick_save_file_dialog=pick_save_file_dialog,
        reveal_path_callback=reveal_path_callback,
    )
    register_error_handlers(app, ctx)
    register_page_routes(app, ctx)
    register_api_routes(app, ctx)
    register_form_routes(app, ctx)
    return ctx.auth_required_response
