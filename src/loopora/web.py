from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from loopora.branding import APP_AUTH_COOKIE, APP_NAME
from loopora.diagnostics import get_logger, log_event, log_exception
from loopora.service import LooporaError, create_service
from loopora.system_dialogs import pick_directory, pick_file, pick_save_file, reveal_path
from loopora.web_inputs import (
    _build_access_state,
    _extract_request_token,
    _is_loopback_host,
    _preferred_locale_from_accept_language,
    _preferred_request_locale,
)
from loopora.web_routes import register_web_routes

logger = get_logger(__name__)

AUTH_COOKIE_NAME = APP_AUTH_COOKIE

__all__ = [
    "_is_loopback_host",
    "_preferred_locale_from_accept_language",
    "build_app",
]


def build_app(service=None, *, bind_host: str = "127.0.0.1", bind_port: int = 8742, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title=APP_NAME)
    app.state.service = service or create_service()
    access_state = _build_access_state(bind_host=bind_host, bind_port=bind_port, auth_token=auth_token)
    app.state.access_state = access_state
    package_root = Path(__file__).parent
    static_root = package_root / "static"

    def template_context(request: Request) -> dict[str, str]:
        locale = _preferred_request_locale(request)
        return {
            "page_locale": locale,
            "page_lang": "zh-CN" if locale == "zh" else "en",
        }

    templates = Jinja2Templates(
        directory=str(package_root / "templates"),
        context_processors=[template_context],
    )
    templates.env.auto_reload = True
    app.mount("/static", StaticFiles(directory=str(package_root / "static")), name="static")
    app.mount("/logo", StaticFiles(directory=str(package_root / "assets" / "logo")), name="logo")

    def static_asset_url(path: str) -> str:
        normalized = path.lstrip("/")
        asset_path = static_root / normalized
        try:
            version = asset_path.stat().st_mtime_ns
        except OSError:
            version = time.time_ns()
        return f"/static/{normalized}?v={version}"

    templates.env.globals["static_asset_url"] = static_asset_url
    log_event(
        logger,
        logging.INFO,
        "web.app.built",
        "Built web application instance",
        bind_host=bind_host,
        bind_port=bind_port,
        auth_enabled=bool(auth_token),
    )

    async def read_json_mapping(request: Request) -> Mapping[str, object]:
        try:
            payload = await request.json()
        except json.JSONDecodeError as exc:
            raise LooporaError(f"invalid JSON body: {exc.msg}") from exc
        if not isinstance(payload, Mapping):
            raise LooporaError("request body must be a JSON object")
        return payload

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        start_time = time.perf_counter()
        expected_token = access_state["auth_token"]
        if not expected_token:
            try:
                response = await call_next(request)
            except Exception as exc:
                log_exception(
                    logger,
                    "web.request.failed",
                    "HTTP request failed before authentication was required",
                    error=exc,
                    method=request.method,
                    request_path=request.url.path,
                    client_ip=request.client.host if request.client else "",
                )
                raise
            _log_web_response(request, response.status_code, start_time)
            return response

        provided_token = _extract_request_token(request)
        if provided_token != expected_token:
            response = auth_required_response(request)
            log_event(
                logger,
                logging.WARNING,
                "web.auth.rejected",
                "Rejected request with a missing or invalid auth token",
                method=request.method,
                request_path=request.url.path,
                status_code=response.status_code,
                client_ip=request.client.host if request.client else "",
            )
            _log_web_response(request, response.status_code, start_time)
            return response

        try:
            response = await call_next(request)
        except Exception as exc:
            log_exception(
                logger,
                "web.request.failed",
                "HTTP request failed",
                error=exc,
                method=request.method,
                request_path=request.url.path,
                client_ip=request.client.host if request.client else "",
            )
            raise
        if request.cookies.get(APP_AUTH_COOKIE) != expected_token:
            response.set_cookie(AUTH_COOKIE_NAME, expected_token, httponly=True, samesite="lax")
        _log_web_response(request, response.status_code, start_time)
        return response
    auth_required_response = register_web_routes(
        app,
        templates=templates,
        access_state=access_state,
        logger=logger,
        read_json_mapping=read_json_mapping,
        resolve_stream_after_id=_resolve_stream_after_id,
        pick_directory_dialog=lambda start_path=None: pick_directory(start_path),
        pick_file_dialog=lambda start_path=None: pick_file(start_path),
        pick_save_file_dialog=lambda start_path=None, **kwargs: pick_save_file(start_path, **kwargs),
        reveal_path_callback=lambda target: reveal_path(target),
    )
    return app


def _log_web_response(request: Request, status_code: int, started_at: float) -> None:
    path = request.url.path
    if path.startswith("/static/") or path.startswith("/logo/"):
        return
    level = logging.ERROR if status_code >= 500 else (logging.WARNING if status_code >= 400 else logging.INFO)
    event = "web.request.failed" if status_code >= 500 else ("web.request.rejected" if status_code >= 400 else "web.request.completed")
    log_event(
        logger,
        level,
        event,
        "HTTP request completed",
        method=request.method,
        request_path=path,
        status_code=status_code,
        duration_ms=int((time.perf_counter() - started_at) * 1000),
        client_ip=request.client.host if request.client else "",
    )


def _resolve_stream_after_id(request: Request, *, run_id: str, after_id: int) -> int:
    last_event_header = str(request.headers.get("last-event-id", "")).strip()
    if not last_event_header:
        return after_id
    try:
        return max(after_id, int(last_event_header))
    except ValueError:
        log_event(
            logger,
            logging.WARNING,
            "web.run_stream.resume_cursor_invalid",
            "Ignored invalid SSE resume cursor and kept the request cursor",
            run_id=run_id,
            after_id=after_id,
            invalid_last_event_id=last_event_header,
        )
        return after_id
