from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from loopora.service import LooporaError
from loopora.specs import SpecError
from loopora.web_inputs import (
    _coerce_bool,
    _loop_payload_from_mapping,
    _normalize_bundle_derive_form,
    _normalize_bundle_import_form,
    _normalize_loop_form,
    _normalize_orchestration_form,
    _normalize_role_definition_form,
    _orchestration_payload_from_mapping,
    _role_definition_payload_from_mapping,
)
from loopora.web_route_context import WebRouteContext
from loopora.web_url_utils import safe_local_return_path, with_query_params
from loopora.workflows import WorkflowError


def register_form_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/bundles/{bundle_id}/revise")
    async def create_bundle_improvement_from_form(request: Request, bundle_id: str):
        form = await request.form()
        message = str(form.get("message", "") or "")
        session = ctx.svc().create_bundle_revision_session(
            bundle_id,
            message=message,
            start_immediately=True,
        )
        return RedirectResponse(url=f"/loops/new/bundle?alignment_session_id={session['id']}", status_code=303)

    @app.post("/runs/{run_id}/revise")
    async def create_run_improvement_from_form(request: Request, run_id: str):
        form = await request.form()
        message = str(form.get("message", "") or "")
        session = ctx.svc().create_run_revision_session(
            run_id,
            message=message,
            start_immediately=True,
        )
        return RedirectResponse(url=f"/loops/new/bundle?alignment_session_id={session['id']}", status_code=303)

    @app.post("/runs/{run_id}/rerun")
    async def rerun_from_run_detail(run_id: str):
        run = ctx.svc().get_run(run_id)
        if run.get("status") not in {"succeeded", "failed", "stopped"}:
            raise LooporaError(f"cannot rerun from active run in status {run.get('status')}")
        new_run = ctx.svc().rerun(run["loop_id"], background=True)
        return RedirectResponse(url=f"/runs/{new_run['id']}", status_code=303)

    @app.post("/loops/new/manual")
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
            return ctx.render_new_loop(request, page_mode="manual", values=values, form_error=str(exc))

    @app.post("/loops/new/manual/import-bundle")
    @app.post("/loops/new/bundle/import-bundle")
    @app.post("/loops/new/import-bundle")
    async def import_bundle_from_create_loop_form(request: Request):
        form = await request.form()
        import_values = _normalize_bundle_import_form(form)
        try:
            bundle_path = str(form.get("bundle_path", "")).strip()
            bundle_yaml = str(form.get("bundle_yaml", ""))
            replace_bundle_id = str(form.get("replace_bundle_id", "")).strip() or None
            if bundle_yaml.strip():
                bundle = ctx.svc().import_bundle_text(bundle_yaml, replace_bundle_id=replace_bundle_id)
            elif bundle_path:
                bundle = ctx.svc().import_bundle_file(Path(bundle_path), replace_bundle_id=replace_bundle_id)
            else:
                raise LooporaError("bundle path or bundle YAML is required")
            loop_id = str(bundle.get("loop_id", "") or "").strip()
            if not loop_id:
                return RedirectResponse(url=f"/bundles/{bundle['id']}", status_code=303)
            if _coerce_bool(form.get("start_immediately")):
                run = ctx.svc().start_run(loop_id)
                ctx.svc().start_run_async(run["id"])
                return RedirectResponse(url=f"/runs/{run['id']}", status_code=303)
            return RedirectResponse(url=f"/loops/{loop_id}", status_code=303)
        except (LooporaError, SpecError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_loop(request, page_mode="manual", import_values=import_values, import_error=str(exc))

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
        return_to = safe_local_return_path(request.query_params.get("return_to", ""))
        try:
            if orchestration.get("source") == "builtin":
                raise LooporaError("built-in orchestrations are read-only; create a new orchestration to customize one")
            updated = ctx.svc().update_orchestration(
                orchestration_id,
                **_orchestration_payload_from_mapping(form, default_to_preset=False),
            )
            if return_to:
                return RedirectResponse(url=with_query_params(return_to, surface_updated="workflow"), status_code=303)
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
        return_to = safe_local_return_path(request.query_params.get("return_to", ""))
        try:
            if role_definition.get("source") == "builtin":
                created = ctx.svc().create_role_definition(**_role_definition_payload_from_mapping(form))
                return RedirectResponse(url=f"/roles/{created['id']}/edit?saved=1", status_code=303)
            updated = ctx.svc().update_role_definition(role_definition_id, **_role_definition_payload_from_mapping(form))
            if return_to:
                return RedirectResponse(
                    url=with_query_params(return_to, surface_updated=f"role:{updated['id']}"),
                    status_code=303,
                )
            return RedirectResponse(url=f"/roles/{updated['id']}/edit?saved=1", status_code=303)
        except (LooporaError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_role_definition(
                request,
                values=values,
                form_error=str(exc),
                role_definition=role_definition,
            )

    @app.post("/bundles/import")
    async def import_bundle_from_form(request: Request):
        form = await request.form()
        import_values = _normalize_bundle_import_form(form)
        try:
            bundle_path = str(form.get("bundle_path", "")).strip()
            bundle_yaml = str(form.get("bundle_yaml", ""))
            replace_bundle_id = str(form.get("replace_bundle_id", "")).strip() or None
            if bundle_yaml.strip():
                bundle = ctx.svc().import_bundle_text(bundle_yaml, replace_bundle_id=replace_bundle_id)
            elif bundle_path:
                bundle = ctx.svc().import_bundle_file(Path(bundle_path), replace_bundle_id=replace_bundle_id)
            else:
                raise LooporaError("bundle path or bundle YAML is required")
            return RedirectResponse(url=f"/bundles/{bundle['id']}", status_code=303)
        except (LooporaError, SpecError, FileExistsError, OSError, ValueError) as exc:
            return ctx.render_new_loop(request, page_mode="manual", import_values=import_values, import_error=str(exc))

    @app.post("/bundles/{bundle_id}/edit")
    async def update_bundle_from_form(request: Request, bundle_id: str):
        form = await request.form()
        values = {
            "description": str(form.get("description", "")),
            "collaboration_summary": str(form.get("collaboration_summary", "")),
            "spec_markdown": str(form.get("spec_markdown", "")),
        }
        try:
            ctx.svc().update_bundle(
                bundle_id,
                description=str(form.get("description", "")),
                collaboration_summary=str(form.get("collaboration_summary", "")),
                spec_markdown=str(form.get("spec_markdown", "")),
            )
            return RedirectResponse(url=f"/bundles/{bundle_id}?saved=1", status_code=303)
        except (LooporaError, SpecError, OSError, ValueError) as exc:
            return ctx.render_bundle_detail(request, bundle_id, values=values, form_error=str(exc))

    @app.post("/bundles/derive")
    async def derive_bundle_from_form(request: Request):
        form = await request.form()
        derive_values = _normalize_bundle_derive_form(form)
        loop_id = str(form.get("loop_id", "")).strip()
        if not loop_id:
            return ctx.render_bundles(request, derive_values=derive_values, derive_error="loop id is required")
        query_params = {"loop_id": loop_id}
        for key in ("name", "description", "collaboration_summary"):
            value = str(form.get(key, "")).strip()
            if value:
                query_params[key] = value
        return RedirectResponse(url=f"/bundles/derive/export?{urlencode(query_params)}", status_code=303)
