from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from loopora.markdown_tools import render_safe_markdown_html
from loopora.web_overviews import (
    _build_run_summary_snapshot,
    _decorate_loop_overview,
    _decorate_run_overview,
    _progress_stage_seed,
    _workflow_role_executor_summary,
)
from loopora.web_route_context import WebRouteContext
from loopora.web_inputs import _preferred_request_locale
from loopora.web_url_utils import attachment_content_disposition, with_query_params


def register_page_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        loops = [_decorate_loop_overview(loop) for loop in ctx.svc().list_loops()]
        return ctx.templates.TemplateResponse(
            request,
            "index.html",
            {"request": request, "loops": loops, "access_state": ctx.access_state},
        )

    @app.get("/loops/new", response_class=HTMLResponse)
    async def new_loop(request: Request) -> HTMLResponse:
        if _looks_like_bundle_import_query(request):
            return RedirectResponse(url=_forward_create_query(request, "/loops/new/manual", "bundle-import-form"), status_code=303)
        if _looks_like_manual_loop_query(request):
            return RedirectResponse(url=_forward_create_query(request, "/loops/new/manual", "manual-loop-form"), status_code=303)
        return ctx.render_new_loop(
            request,
            page_mode="choice",
        )

    @app.get("/loops/new/bundle", response_class=HTMLResponse)
    async def new_loop_bundle(request: Request) -> HTMLResponse:
        if _looks_like_bundle_import_query(request):
            return RedirectResponse(url=_forward_create_query(request, "/loops/new/manual", "bundle-import-form"), status_code=303)
        return ctx.render_new_loop(
            request,
            page_mode="bundle",
        )

    @app.get("/loops/new/manual", response_class=HTMLResponse)
    async def new_loop_manual(request: Request) -> HTMLResponse:
        return ctx.render_new_loop(
            request,
            page_mode="manual",
            values=request.query_params,
            import_values=request.query_params if request.query_params else None,
        )

    @app.get("/orchestrations", response_class=HTMLResponse)
    async def orchestrations_page(request: Request) -> HTMLResponse:
        return ctx.render_orchestrations(request)

    @app.get("/bundles", response_class=HTMLResponse)
    async def bundles_page(request: Request):
        replace_bundle_id = str(request.query_params.get("replace_bundle_id", "")).strip()
        if replace_bundle_id:
            return RedirectResponse(
                url=with_query_params("/loops/new/manual#bundle-import-form", replace_bundle_id=replace_bundle_id),
                status_code=303,
            )
        return ctx.render_bundles(request, import_values=request.query_params if request.query_params else None)

    @app.get("/bundles/{bundle_id}", response_class=HTMLResponse)
    async def bundle_detail_page(request: Request, bundle_id: str) -> HTMLResponse:
        return ctx.render_bundle_detail(request, bundle_id)

    @app.get("/roles", response_class=HTMLResponse)
    async def role_definitions_page(request: Request) -> HTMLResponse:
        return ctx.render_role_definitions(request)

    @app.get("/orchestrations/new", response_class=HTMLResponse)
    async def new_orchestration(request: Request) -> HTMLResponse:
        preset = str(request.query_params.get("workflow_preset", "")).strip()
        values = request.query_params if preset else None
        return ctx.render_new_orchestration(request, values=values)

    @app.get("/orchestrations/{orchestration_id}/edit", response_class=HTMLResponse)
    async def edit_orchestration(request: Request, orchestration_id: str) -> HTMLResponse:
        return ctx.render_new_orchestration(request, orchestration=ctx.svc().get_orchestration(orchestration_id))

    @app.get("/roles/new", response_class=HTMLResponse)
    async def new_role_definition(request: Request) -> HTMLResponse:
        return ctx.render_new_role_definition(request, values=request.query_params if request.query_params else None)

    @app.get("/roles/{role_definition_id}/edit", response_class=HTMLResponse)
    async def edit_role_definition(request: Request, role_definition_id: str) -> HTMLResponse:
        return ctx.render_new_role_definition(request, role_definition=ctx.svc().get_role_definition(role_definition_id))

    @app.get("/tools", response_class=HTMLResponse)
    async def tools_page(request: Request) -> HTMLResponse:
        return ctx.render_tools(request)

    @app.get("/tutorial", response_class=HTMLResponse)
    async def tutorial_page(request: Request) -> HTMLResponse:
        return ctx.render_tutorial(request)

    @app.get("/loops/{loop_id}", response_class=HTMLResponse)
    async def loop_detail(request: Request, loop_id: str) -> HTMLResponse:
        loop = ctx.svc().get_loop(loop_id)
        runs = [_decorate_run_overview(run) for run in loop["runs"]]
        latest_run = runs[0] if runs else None
        return ctx.templates.TemplateResponse(
            request,
            "loop_detail.html",
            {
                "request": request,
                "loop": {
                    **loop,
                    "runs": runs,
                    "role_executor_summary": _workflow_role_executor_summary(
                        loop.get("workflow_json") or {},
                        fallback_executor_kind=loop.get("executor_kind", "codex"),
                    ),
                    "spec_rendered_html": render_safe_markdown_html(loop.get("spec_markdown", "")),
                },
                "latest_run": latest_run,
                "summary_snapshot": _build_run_summary_snapshot(latest_run) if latest_run else None,
                "access_state": ctx.access_state,
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        locale = _preferred_request_locale(request)
        run = ctx.svc().get_run(run_id)
        return ctx.templates.TemplateResponse(
            request,
            "run_detail.html",
            {
                "request": request,
                "run": run,
                "page_locale": locale,
                "progress_stages": _progress_stage_seed(run),
                "access_state": ctx.access_state,
            },
        )

    @app.get("/runs/{run_id}/console", response_class=HTMLResponse)
    async def run_console(request: Request, run_id: str) -> HTMLResponse:
        run = ctx.svc().get_run(run_id)
        seed_events = ctx.svc().stream_events(run_id, limit=5000)
        latest_event_id = seed_events[-1]["id"] if seed_events else 0
        return ctx.templates.TemplateResponse(
            request,
            "run_console.html",
            {
                "request": request,
                "run": run,
                "console_events": seed_events[-360:],
                "latest_event_id": latest_event_id,
                "access_state": ctx.access_state,
            },
        )

    @app.get("/bundles/derive/export")
    async def derive_bundle_export(
        loop_id: str,
        name: str = "",
        description: str = "",
        collaboration_summary: str = "",
    ) -> Response:
        bundle = ctx.svc().derive_bundle_from_loop(
            loop_id,
            name=name.strip() or None,
            description=description,
            collaboration_summary=collaboration_summary,
        )
        filename = f"{bundle['metadata']['name'] or loop_id}.yml"
        from loopora.bundles import bundle_to_yaml

        return Response(
            content=bundle_to_yaml(bundle),
            media_type="application/yaml; charset=utf-8",
            headers={"Content-Disposition": attachment_content_disposition(filename, default=f"{loop_id}.yml")},
        )


def _forward_create_query(request: Request, path: str, fragment: str) -> str:
    query = str(request.url.query or "")
    return f"{path}{'?' + query if query else ''}#{fragment}"


def _looks_like_bundle_import_query(request: Request) -> bool:
    keys = set(request.query_params.keys())
    return bool(keys & {"replace_bundle_id", "bundle_path", "bundle_yaml"})


def _looks_like_manual_loop_query(request: Request) -> bool:
    keys = set(request.query_params.keys()) - {"token"}
    return bool(
        keys
        & {
            "name",
            "workdir",
            "spec_path",
            "orchestration_id",
            "completion_mode",
            "max_iters",
            "max_role_retries",
            "delta_threshold",
            "trigger_window",
            "regression_window",
            "iteration_interval_seconds",
        }
    )
