from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from loopora.diagnostics import log_event
from loopora.service import LooporaError
from loopora.specs import SpecError
from loopora.system_dialogs import SystemDialogError
from loopora.web_route_context import WebRouteContext
from loopora.workflows import WorkflowError


def register_error_handlers(app: FastAPI, ctx: WebRouteContext) -> None:
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
        return ctx.json_error(str(exc), status_code=400)

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
