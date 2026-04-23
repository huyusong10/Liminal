from __future__ import annotations

import html
import logging
from collections.abc import Awaitable, Callable, Mapping

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates


class WebRouteContextBase:
    def __init__(
        self,
        *,
        app: FastAPI,
        templates: Jinja2Templates,
        access_state: Mapping[str, object],
        logger: logging.Logger,
        read_json_mapping: Callable[[Request], Awaitable[Mapping[str, object]]],
        resolve_stream_after_id: Callable[[Request], int] | Callable[..., int],
        pick_directory_dialog: Callable[[str | None], str | None],
        pick_file_dialog: Callable[[str | None], str | None],
        pick_save_file_dialog: Callable[[str | None], str | None] | Callable[..., str | None],
        reveal_path_callback: Callable[[str], str],
    ) -> None:
        self.app = app
        self.templates = templates
        self.access_state = access_state
        self.logger = logger
        self.read_json_mapping = read_json_mapping
        self.resolve_stream_after_id = resolve_stream_after_id
        self.pick_directory_dialog = pick_directory_dialog
        self.pick_file_dialog = pick_file_dialog
        self.pick_save_file_dialog = pick_save_file_dialog
        self.reveal_path_callback = reveal_path_callback

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
