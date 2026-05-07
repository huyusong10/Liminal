from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from loopora.markdown_tools import looks_binary, normalize_markdown_text, render_safe_markdown_html
from loopora.service import LooporaError
from loopora.specs import SpecError, compile_markdown_spec, init_spec_file_for_workflow, render_spec_template
from loopora.web_inputs import (
    _coerce_bool,
    _orchestration_payload_from_mapping,
    _role_definition_payload_from_mapping,
    _spec_document_payload,
    _workflow_for_spec_template,
)
from loopora.web_route_context import WebRouteContext
from loopora.web_url_utils import attachment_content_disposition
from loopora.workflows import (
    WorkflowError,
    builtin_prompt_markdown,
    normalize_role_display_name,
    validate_prompt_markdown,
)

SPEC_MARKDOWN_SUFFIXES = {".md", ".markdown"}
SPEC_DOCUMENT_MAX_BYTES = 1_000_000


def register_editor_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    _register_bundle_record_api_routes(app, ctx)
    _register_bundle_import_api_routes(app, ctx)
    _register_bundle_export_api_routes(app, ctx)
    _register_orchestration_api_routes(app, ctx)
    _register_role_definition_api_routes(app, ctx)
    _register_spec_validation_api_routes(app)
    _register_spec_document_api_routes(app)
    _register_spec_save_api_route(app, ctx)
    _register_markdown_prompt_api_routes(app, ctx)
    _register_spec_template_api_routes(app, ctx)
    _register_system_picker_api_routes(app, ctx)
    _register_system_reveal_api_route(app, ctx)


def _register_bundle_record_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/bundles")
    async def api_list_bundles() -> JSONResponse:
        return JSONResponse(ctx.svc().list_bundle_governance_cards())

    @app.get("/api/bundles/{bundle_id}")
    async def api_get_bundle(bundle_id: str) -> JSONResponse:
        bundle = ctx.svc().get_bundle(bundle_id)
        return JSONResponse(bundle)

    @app.put("/api/bundles/{bundle_id}")
    async def api_update_bundle(bundle_id: str, request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        bundle = ctx.svc().update_bundle(
            bundle_id,
            description=payload.get("description"),
            collaboration_summary=payload.get("collaboration_summary"),
            spec_markdown=payload.get("spec_markdown"),
        )
        return JSONResponse({"bundle": bundle, "redirect_url": f"/bundles/{bundle['id']}"})


def _register_bundle_import_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/bundles/import")
    async def api_import_bundle(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        bundle_yaml = str(payload.get("bundle_yaml", ""))
        bundle_path = str(payload.get("bundle_path", "")).strip()
        replace_bundle_id = str(payload.get("replace_bundle_id", "")).strip() or None
        if bundle_yaml.strip():
            bundle = ctx.svc().import_bundle_text(bundle_yaml, replace_bundle_id=replace_bundle_id)
        elif bundle_path:
            bundle = ctx.svc().import_bundle_file(Path(bundle_path), replace_bundle_id=replace_bundle_id)
        else:
            return ctx.json_error("bundle path or bundle YAML is required")
        return JSONResponse({"bundle": bundle, "redirect_url": f"/bundles/{bundle['id']}"}, status_code=201)

    @app.post("/api/bundles/preview")
    async def api_preview_bundle(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        bundle_yaml = str(payload.get("bundle_yaml", ""))
        bundle_path = str(payload.get("bundle_path", "")).strip()
        try:
            if bundle_yaml.strip():
                preview = ctx.svc().preview_bundle_text(bundle_yaml)
            elif bundle_path:
                preview = ctx.svc().preview_bundle_file(Path(bundle_path))
            else:
                return JSONResponse({"ok": False, "error": "bundle path or bundle YAML is required"})
        except LooporaError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(preview)

    @app.post("/api/bundles/derive")
    async def api_derive_bundle(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        loop_id = str(payload.get("loop_id", "")).strip()
        if not loop_id:
            return ctx.json_error("loop id is required")
        bundle = ctx.svc().derive_bundle_from_loop(
            loop_id,
            name=str(payload.get("name", "")).strip() or None,
            description=str(payload.get("description", "")),
            collaboration_summary=str(payload.get("collaboration_summary", "")),
        )
        return JSONResponse({"bundle": bundle})


def _register_bundle_export_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/bundles/{bundle_id}/export")
    async def api_export_bundle(bundle_id: str) -> Response:
        bundle = ctx.svc().export_bundle(bundle_id)
        from loopora.bundles import bundle_to_yaml

        return Response(
            content=bundle_to_yaml(bundle),
            media_type="application/yaml; charset=utf-8",
            headers={
                "Content-Disposition": attachment_content_disposition(
                    f"{bundle['metadata']['name'] or bundle_id}.yml",
                    default=f"{bundle_id}.yml",
                )
            },
        )

    @app.delete("/api/bundles/{bundle_id}")
    async def api_delete_bundle(bundle_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().delete_bundle(bundle_id))


def _register_orchestration_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/orchestrations")
    async def api_list_orchestrations() -> JSONResponse:
        return JSONResponse(ctx.svc().list_orchestrations())

    @app.get("/api/orchestrations/{orchestration_id}")
    async def api_get_orchestration(orchestration_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_orchestration(orchestration_id))

    @app.post("/api/orchestrations")
    async def api_create_orchestration(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        orchestration = ctx.svc().create_orchestration(**_orchestration_payload_from_mapping(payload))
        return JSONResponse(
            {"orchestration": orchestration, "redirect_url": f"/orchestrations/{orchestration['id']}/edit"},
            status_code=201,
        )

    @app.put("/api/orchestrations/{orchestration_id}")
    async def api_update_orchestration(orchestration_id: str, request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        orchestration = ctx.svc().update_orchestration(orchestration_id, **_orchestration_payload_from_mapping(payload))
        return JSONResponse({"orchestration": orchestration, "redirect_url": f"/orchestrations/{orchestration['id']}/edit"})

    @app.delete("/api/orchestrations/{orchestration_id}")
    async def api_delete_orchestration(orchestration_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().delete_orchestration(orchestration_id))


def _register_role_definition_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/role-definitions")
    async def api_list_role_definitions() -> JSONResponse:
        return JSONResponse(ctx.svc().list_role_definitions())

    @app.get("/api/role-definitions/{role_definition_id}")
    async def api_get_role_definition(role_definition_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_role_definition(role_definition_id))

    @app.post("/api/role-definitions")
    async def api_create_role_definition(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        role_definition = ctx.svc().create_role_definition(**_role_definition_payload_from_mapping(payload))
        return JSONResponse(
            {"role_definition": role_definition, "redirect_url": f"/roles/{role_definition['id']}/edit"},
            status_code=201,
        )

    @app.put("/api/role-definitions/{role_definition_id}")
    async def api_update_role_definition(role_definition_id: str, request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        role_definition = ctx.svc().update_role_definition(role_definition_id, **_role_definition_payload_from_mapping(payload))
        return JSONResponse({"role_definition": role_definition, "redirect_url": f"/roles/{role_definition['id']}/edit"})

    @app.delete("/api/role-definitions/{role_definition_id}")
    async def api_delete_role_definition(role_definition_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().delete_role_definition(role_definition_id))


def _register_spec_validation_api_routes(app: FastAPI) -> None:
    @app.get("/api/specs/validate")
    async def api_validate_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        try:
            spec_path, markdown_text = _load_spec_markdown_document(path_text, binary_error="spec validation only supports text markdown files")
            compiled = compile_markdown_spec(markdown_text)
        except (FileNotFoundError, OSError, LooporaError, SpecError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(
            {
                "ok": True,
                "path": str(spec_path),
                "check_count": len(compiled["checks"]),
                "check_mode": compiled["check_mode"],
            }
        )


def _register_spec_document_api_routes(app: FastAPI) -> None:
    @app.get("/api/specs/preview")
    async def api_preview_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        try:
            spec_path, markdown_text = _load_spec_markdown_document(path_text, binary_error="spec preview only supports text markdown files")
        except (FileNotFoundError, OSError, LooporaError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(_spec_document_payload(spec_path, markdown_text))

    @app.get("/api/specs/document")
    async def api_get_spec_document(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        try:
            spec_path, markdown_text = _load_spec_markdown_document(path_text, binary_error="spec editor only supports text markdown files")
        except (FileNotFoundError, OSError, LooporaError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(_spec_document_payload(spec_path, markdown_text))


def _register_spec_save_api_route(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.put("/api/specs/document")
    async def api_save_spec_document(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        path_text = str(payload.get("path", "")).strip()
        markdown_text = normalize_markdown_text(str(payload.get("content", "")))
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        try:
            spec_path = _resolve_spec_markdown_path(path_text)
            _assert_spec_markdown_content(
                markdown_text.encode("utf-8"),
                binary_error="spec editor only supports text markdown files",
            )
        except LooporaError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        if not spec_path.parent.exists():
            return JSONResponse({"ok": False, "error": f"spec parent directory does not exist: {spec_path.parent}"})
        try:
            spec_path.write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(_spec_document_payload(spec_path, markdown_text))


def _register_markdown_prompt_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/markdown/render")
    async def api_render_markdown(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        markdown_text = str(payload.get("markdown", ""))
        strip_front_matter = _coerce_bool(payload.get("strip_front_matter", False))
        return JSONResponse(
            {
                "ok": True,
                "rendered_html": render_safe_markdown_html(markdown_text, strip_front_matter=strip_front_matter),
            }
        )

    @app.post("/api/prompts/validate")
    async def api_validate_prompt(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        markdown_text = str(payload.get("markdown", ""))
        expected_archetype = str(payload.get("archetype", "")).strip() or None
        try:
            metadata, body = validate_prompt_markdown(markdown_text, expected_archetype=expected_archetype)
        except WorkflowError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse({"ok": True, "metadata": metadata, "body": body})

    @app.get("/api/prompts/templates/{prompt_ref}")
    async def api_prompt_template(prompt_ref: str, locale: str | None = Query(default=None)) -> Response:
        try:
            markdown_text = builtin_prompt_markdown(prompt_ref, locale=locale)
        except WorkflowError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=markdown_text,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": attachment_content_disposition(prompt_ref, default="prompt.md")},
        )


def _register_spec_template_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/specs/init")
    async def api_init_spec(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        path_text = str(payload.get("path", "")).strip()
        if not path_text:
            return ctx.json_error("spec path is required")
        locale = str(payload.get("locale", "zh"))
        try:
            workflow = _workflow_for_spec_template(payload)
        except (LooporaError, WorkflowError) as exc:
            return ctx.json_error_from_exception(exc)
        try:
            spec_path = _resolve_spec_markdown_path(path_text)
            created = init_spec_file_for_workflow(spec_path, locale=locale, workflow=workflow)
        except (FileExistsError, OSError, LooporaError) as exc:
            return ctx.json_error_from_exception(exc)
        return JSONResponse({"path": str(created.resolve())}, status_code=201)

    @app.post("/api/specs/template")
    async def api_spec_template(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        try:
            workflow = _workflow_for_spec_template(payload)
        except (LooporaError, WorkflowError) as exc:
            return ctx.json_error_from_exception(exc)
        locale = str(payload.get("locale", "zh"))
        markdown_text = render_spec_template(locale=locale, workflow=workflow)
        return JSONResponse(
            {
                "ok": True,
                "content": markdown_text,
                "rendered_html": render_safe_markdown_html(markdown_text),
                "role_note_sections": _role_note_sections_from_workflow(workflow),
            }
        )


def _role_note_sections_from_workflow(workflow: dict | None) -> list[dict[str, str]]:
    if not workflow:
        return []
    sections: list[dict[str, str]] = []
    seen: set[str] = set()
    for role in workflow.get("roles", []):
        if not isinstance(role, dict):
            continue
        label = normalize_role_display_name(role.get("name"), archetype=role.get("archetype")) or str(
            role.get("name", "")
        ).strip()
        normalized = label.lower()
        if not label or normalized in seen:
            continue
        seen.add(normalized)
        sections.append(
            {
                "heading": f"{label} Notes",
                "role_name": label,
                "archetype": str(role.get("archetype", "")).strip(),
            }
        )
    return sections


def _load_spec_markdown_document(path_text: str, *, binary_error: str) -> tuple[Path, str]:
    spec_path = _resolve_spec_markdown_path(path_text)
    raw_bytes = spec_path.read_bytes()
    _assert_spec_markdown_content(raw_bytes, binary_error=binary_error)
    try:
        markdown_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LooporaError("spec file must be UTF-8 encoded Markdown") from exc
    return spec_path, markdown_text


def _resolve_spec_markdown_path(path_text: str) -> Path:
    spec_path = Path(path_text).expanduser().resolve()
    if spec_path.suffix.lower() not in SPEC_MARKDOWN_SUFFIXES:
        raise LooporaError("spec path must point to a Markdown file (.md or .markdown)")
    return spec_path


def _assert_spec_markdown_size(raw_bytes: bytes) -> None:
    if len(raw_bytes) > SPEC_DOCUMENT_MAX_BYTES:
        raise LooporaError(f"spec file is too large; maximum size is {SPEC_DOCUMENT_MAX_BYTES} bytes")


def _assert_spec_markdown_content(raw_bytes: bytes, *, binary_error: str) -> None:
    _assert_spec_markdown_size(raw_bytes)
    if looks_binary(raw_bytes):
        raise LooporaError(binary_error)


def _register_system_picker_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/system/pick-directory")
    async def api_pick_directory(request: Request) -> JSONResponse:
        guard = _guard_system_api_request(request, ctx)
        if guard is not None:
            return guard
        payload = await ctx.read_json_mapping(request)
        start_path = str(payload.get("start_path", "")).strip()
        selected = ctx.pick_directory_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.post("/api/system/pick-spec-file")
    async def api_pick_spec_file(request: Request) -> JSONResponse:
        guard = _guard_system_api_request(request, ctx)
        if guard is not None:
            return guard
        payload = await ctx.read_json_mapping(request)
        start_path = str(payload.get("start_path", "")).strip()
        selected = ctx.pick_file_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.post("/api/system/pick-bundle-file")
    async def api_pick_bundle_file(request: Request) -> JSONResponse:
        guard = _guard_system_api_request(request, ctx)
        if guard is not None:
            return guard
        payload = await ctx.read_json_mapping(request)
        start_path = str(payload.get("start_path", "")).strip()
        selected = ctx.pick_file_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.post("/api/system/pick-spec-save-path")
    async def api_pick_spec_save_path(request: Request) -> JSONResponse:
        guard = _guard_system_api_request(request, ctx)
        if guard is not None:
            return guard
        payload = await ctx.read_json_mapping(request)
        start_path = str(payload.get("start_path", "")).strip()
        selected = ctx.pick_save_file_dialog(start_path or None, default_name="spec.md")
        return JSONResponse({"path": selected or "", "cancelled": not selected})


def _register_system_reveal_api_route(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.post("/api/system/reveal-path")
    async def api_reveal_path(request: Request) -> JSONResponse:
        guard = _guard_system_api_request(request, ctx)
        if guard is not None:
            return guard
        payload = await ctx.read_json_mapping(request)
        target = str(payload.get("path") or "").strip()
        if not target:
            return ctx.json_error("path is required")
        return JSONResponse({"path": ctx.reveal_path_callback(target), "ok": True})


def _guard_system_api_request(request: Request, ctx: WebRouteContext) -> JSONResponse | None:
    if not _system_request_is_same_origin(request):
        return ctx.json_error("system API requests must come from the same origin", status_code=403)
    if not ctx.access_state["native_dialogs_enabled"]:
        return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
    return None


def _system_request_is_same_origin(request: Request) -> bool:
    references = [
        value.strip()
        for value in (
            request.headers.get("origin", ""),
            request.headers.get("referer", ""),
        )
        if value and value.strip()
    ]
    if not references:
        return True

    expected = _origin_tuple(
        scheme=request.url.scheme,
        hostname=request.url.hostname,
        port=request.url.port,
    )
    if expected is None:
        return False
    return all(_header_origin_tuple(value) == expected for value in references)


def _header_origin_tuple(value: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        return None
    return _origin_tuple(scheme=parsed.scheme, hostname=parsed.hostname, port=port)


def _origin_tuple(*, scheme: str | None, hostname: str | None, port: int | None) -> tuple[str, str, int] | None:
    normalized_scheme = str(scheme or "").lower()
    normalized_host = str(hostname or "").lower()
    if not normalized_scheme or not normalized_host:
        return None
    if port is None:
        if normalized_scheme == "http":
            port = 80
        elif normalized_scheme == "https":
            port = 443
    return normalized_scheme, normalized_host, int(port or 0)
