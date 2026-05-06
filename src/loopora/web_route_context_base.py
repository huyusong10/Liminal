from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates


StreamAfterResolver = Callable[[Request], int] | Callable[..., int]
SaveFilePicker = Callable[[str | None], str | None] | Callable[..., str | None]


@dataclass(frozen=True, kw_only=True)
class WebRouteDependencies:
    templates: Jinja2Templates
    access_state: Mapping[str, object]
    logger: logging.Logger
    read_json_mapping: Callable[[Request], Awaitable[Mapping[str, object]]]
    resolve_stream_after_id: StreamAfterResolver
    pick_directory_dialog: Callable[[str | None], str | None]
    pick_file_dialog: Callable[[str | None], str | None]
    pick_save_file_dialog: SaveFilePicker
    reveal_path_callback: Callable[[str], str]


def _required_web_route_dependency(fields: dict[str, object], field: str) -> object:
    try:
        return fields.pop(field)
    except KeyError as exc:
        raise TypeError(f"missing web route dependency: {field}") from exc


def web_route_dependencies_from_args(
    dependencies: WebRouteDependencies | None,
    raw_dependencies: dict[str, object],
) -> WebRouteDependencies:
    if dependencies is not None:
        if raw_dependencies:
            raise TypeError("web route dependencies object cannot be combined with keyword fields")
        return dependencies

    fields = dict(raw_dependencies)
    dependency_set = WebRouteDependencies(
        templates=_required_web_route_dependency(fields, "templates"),
        access_state=_required_web_route_dependency(fields, "access_state"),
        logger=_required_web_route_dependency(fields, "logger"),
        read_json_mapping=_required_web_route_dependency(fields, "read_json_mapping"),
        resolve_stream_after_id=_required_web_route_dependency(fields, "resolve_stream_after_id"),
        pick_directory_dialog=_required_web_route_dependency(fields, "pick_directory_dialog"),
        pick_file_dialog=_required_web_route_dependency(fields, "pick_file_dialog"),
        pick_save_file_dialog=_required_web_route_dependency(fields, "pick_save_file_dialog"),
        reveal_path_callback=_required_web_route_dependency(fields, "reveal_path_callback"),
    )
    if fields:
        unexpected_fields = ", ".join(sorted(fields))
        raise TypeError(f"unexpected web route dependencies: {unexpected_fields}")
    return dependency_set


class WebRouteContextBase:
    def __init__(
        self,
        app: FastAPI,
        dependencies: WebRouteDependencies | None = None,
        **raw_dependencies: object,
    ) -> None:
        dependencies = web_route_dependencies_from_args(dependencies, raw_dependencies)
        self.app = app
        self.templates = dependencies.templates
        self.access_state = dependencies.access_state
        self.logger = dependencies.logger
        self.read_json_mapping = dependencies.read_json_mapping
        self.resolve_stream_after_id = dependencies.resolve_stream_after_id
        self.pick_directory_dialog = dependencies.pick_directory_dialog
        self.pick_file_dialog = dependencies.pick_file_dialog
        self.pick_save_file_dialog = dependencies.pick_save_file_dialog
        self.reveal_path_callback = dependencies.reveal_path_callback

    def svc(self):
        return self.app.state.service

    @staticmethod
    def json_error(message: str, status_code: int = 400) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    def render_auth_required(self, request: Request) -> HTMLResponse:
        return HTMLResponse(
            self.templates.TemplateResponse(
                request,
                "auth.html",
                {"request": request, "url_path": html.escape(request.url.path)},
            ).body.decode(),
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )

    def auth_required_response(self, request: Request) -> Response:
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
        return self.render_auth_required(request)
