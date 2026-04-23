from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from loopora.service import LooporaError
from loopora.specs import SpecError
from loopora.web_inputs import (
    _loop_payload_from_mapping,
    _normalize_loop_form,
    _normalize_orchestration_form,
    _normalize_role_definition_form,
    _orchestration_payload_from_mapping,
    _role_definition_payload_from_mapping,
)
from loopora.web_route_context import WebRouteContext
from loopora.workflows import WorkflowError


def register_form_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/loops/new")
    async def create_loop_from_form(request: Request):
        form = await request.form()
        values = _normalize_loop_form(form)
        try:
            loop_kwargs, start_immediately = _loop_payload_from_mapping(form)
            loop = ctx.svc().create_loop(**loop_kwargs)
            if start_immediately:
                run = ctx.svc().start_run(loop["id"])
                ctx.svc().start_run_async(run["id"])
                return RedirectResponse(url=f"/runs/{run['id']}", status_code=303)
            return RedirectResponse(url=f"/loops/{loop['id']}", status_code=303)
        except (LooporaError, SpecError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_loop(request, values=values, form_error=str(exc))

    @app.post("/orchestrations/new")
    async def create_orchestration_from_form(request: Request):
        form = await request.form()
        values = _normalize_orchestration_form(form)
        try:
            orchestration = ctx.svc().create_orchestration(
                **_orchestration_payload_from_mapping(form, default_to_preset=False)
            )
            return RedirectResponse(url=f"/orchestrations/{orchestration['id']}/edit?saved=1", status_code=303)
        except (LooporaError, WorkflowError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_orchestration(request, values=values, form_error=str(exc))

    @app.post("/orchestrations/{orchestration_id}/edit")
    async def update_orchestration_from_form(request: Request, orchestration_id: str):
        form = await request.form()
        values = _normalize_orchestration_form(form)
        orchestration = ctx.svc().get_orchestration(orchestration_id)
        try:
            if orchestration.get("source") == "builtin":
                raise LooporaError("built-in orchestrations are read-only; create a new orchestration to customize one")
            updated = ctx.svc().update_orchestration(
                orchestration_id,
                **_orchestration_payload_from_mapping(form, default_to_preset=False),
            )
            return RedirectResponse(url=f"/orchestrations/{updated['id']}/edit?saved=1", status_code=303)
        except (LooporaError, WorkflowError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_orchestration(
                request,
                values=values,
                form_error=str(exc),
                orchestration=orchestration,
            )

    @app.post("/roles/new")
    async def create_role_definition_from_form(request: Request):
        form = await request.form()
        values = _normalize_role_definition_form(form)
        try:
            role_definition = ctx.svc().create_role_definition(**_role_definition_payload_from_mapping(form))
            return RedirectResponse(url=f"/roles/{role_definition['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_role_definition(request, values=values, form_error=str(exc))

    @app.post("/roles/{role_definition_id}/edit")
    async def update_role_definition_from_form(request: Request, role_definition_id: str):
        form = await request.form()
        values = _normalize_role_definition_form(form)
        role_definition = ctx.svc().get_role_definition(role_definition_id)
        try:
            if role_definition.get("source") == "builtin":
                created = ctx.svc().create_role_definition(**_role_definition_payload_from_mapping(form))
                return RedirectResponse(url=f"/roles/{created['id']}/edit?saved=1", status_code=303)
            updated = ctx.svc().update_role_definition(role_definition_id, **_role_definition_payload_from_mapping(form))
            return RedirectResponse(url=f"/roles/{updated['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_role_definition(
                request,
                values=values,
                form_error=str(exc),
                role_definition=role_definition,
            )
