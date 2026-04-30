from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from loopora.diagnostics import log_event
from loopora.service_types import LooporaError
from loopora.specs import SpecError
from loopora.system_dialogs import SystemDialogError
from loopora.web_route_context import WebRouteContext
from loopora.workflows import WorkflowError


def register_error_handlers(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.exception_handler(HTTPException)
    async def http_exception_error_handler(request: Request, exc: HTTPException) -> Response:
        if not request.url.path.startswith("/api/"):
            return await http_exception_handler(request, exc)
        detail = exc.detail if isinstance(exc.detail, str) else "request failed"
        return ctx.json_error(detail, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> Response:
        if not request.url.path.startswith("/api/"):
            return await request_validation_exception_handler(request, exc)
        return ctx.json_error("request validation failed", status_code=400)

    @app.exception_handler(LooporaError)
    async def loopora_error_handler(request: Request, exc: LooporaError) -> JSONResponse:
        log_event(
            ctx.logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a Loopora domain error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return ctx.json_error(str(exc), status_code=getattr(exc, "status_code", 400))

    @app.exception_handler(SpecError)
    async def spec_error_handler(request: Request, exc: SpecError) -> JSONResponse:
        log_event(
            ctx.logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a spec validation error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return ctx.json_error(str(exc), status_code=400)

    @app.exception_handler(WorkflowError)
    async def workflow_error_handler(request: Request, exc: WorkflowError) -> JSONResponse:
        log_event(
            ctx.logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed with a workflow validation error",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return ctx.json_error(str(exc), status_code=400)

    @app.exception_handler(SystemDialogError)
    async def system_dialog_error_handler(request: Request, exc: SystemDialogError) -> JSONResponse:
        log_event(
            ctx.logger,
            logging.WARNING,
            "web.request.domain_error",
            "Request failed while opening a system dialog",
            method=request.method,
            request_path=request.url.path,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        return ctx.json_error(str(exc), status_code=400)
