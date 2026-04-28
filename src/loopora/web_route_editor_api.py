from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from loopora.markdown_tools import decode_text_bytes, looks_binary, normalize_markdown_text, render_safe_markdown_html
from loopora.service import LooporaError
from loopora.skills import (
    build_task_alignment_skill_archive,
    install_task_alignment_skill,
    list_task_alignment_skill_targets,
)
from loopora.specs import SpecError, init_spec_file_for_workflow, read_and_compile, render_spec_template
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


def register_editor_api_routes(app: FastAPI, ctx: WebRouteContext) -> None:
    @app.get("/api/bundles")
    async def api_list_bundles() -> JSONResponse:
        return JSONResponse(ctx.svc().list_bundle_governance_cards())

    @app.get("/api/bundles/{bundle_id}")
    async def api_get_bundle(bundle_id: str) -> JSONResponse:
        bundle = ctx.svc().get_bundle(bundle_id)
        return JSONResponse({**bundle, "revision_summary": ctx.svc().get_bundle_revision_summary(bundle_id)})

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

    @app.get("/api/skills/loopora-task-alignment")
    async def api_task_alignment_skill_targets() -> JSONResponse:
        return JSONResponse(
            {
                "skill_name": "loopora-task-alignment",
                "targets": list_task_alignment_skill_targets(),
            }
        )

    @app.post("/api/skills/loopora-task-alignment/install")
    async def api_install_task_alignment_skill(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        target = str(payload.get("target", "")).strip().lower()
        try:
            result = install_task_alignment_skill(target)
        except ValueError as exc:
            return ctx.json_error(str(exc))
        return JSONResponse(
            {"result": result, "targets": list_task_alignment_skill_targets()},
            status_code=201,
        )

    @app.get("/api/skills/loopora-task-alignment/download")
    async def api_download_task_alignment_skill_bundle() -> Response:
        filename, archive_bytes = build_task_alignment_skill_archive()
        return Response(
            content=archive_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": attachment_content_disposition(filename, default="loopora-task-alignment.zip")},
        )

    @app.get("/api/orchestrations")
    async def api_list_orchestrations() -> JSONResponse:
        return JSONResponse(ctx.svc().list_orchestrations())

    @app.get("/api/orchestrations/{orchestration_id}")
    async def api_get_orchestration(orchestration_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_orchestration(orchestration_id))

    @app.get("/api/role-definitions")
    async def api_list_role_definitions() -> JSONResponse:
        return JSONResponse(ctx.svc().list_role_definitions())

    @app.get("/api/role-definitions/{role_definition_id}")
    async def api_get_role_definition(role_definition_id: str) -> JSONResponse:
        return JSONResponse(ctx.svc().get_role_definition(role_definition_id))

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

    @app.get("/api/specs/validate")
    async def api_validate_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            _, compiled = read_and_compile(spec_path)
        except (FileNotFoundError, OSError, SpecError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(
            {
                "ok": True,
                "path": str(spec_path.resolve()),
                "check_count": len(compiled["checks"]),
                "check_mode": compiled["check_mode"],
            }
        )

    @app.get("/api/specs/preview")
    async def api_preview_spec(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            raw_bytes = spec_path.read_bytes()
        except (FileNotFoundError, OSError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        if looks_binary(raw_bytes):
            return JSONResponse({"ok": False, "error": "spec preview only supports text markdown files"})
        return JSONResponse(_spec_document_payload(spec_path, decode_text_bytes(raw_bytes)))

    @app.get("/api/specs/document")
    async def api_get_spec_document(path: str = "") -> JSONResponse:
        path_text = path.strip()
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        try:
            raw_bytes = spec_path.read_bytes()
        except (FileNotFoundError, OSError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        if looks_binary(raw_bytes):
            return JSONResponse({"ok": False, "error": "spec editor only supports text markdown files"})
        return JSONResponse(_spec_document_payload(spec_path, decode_text_bytes(raw_bytes)))

    @app.put("/api/specs/document")
    async def api_save_spec_document(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        path_text = str(payload.get("path", "")).strip()
        markdown_text = normalize_markdown_text(str(payload.get("content", "")))
        if not path_text:
            return JSONResponse({"ok": False, "error": "spec path is required"})
        spec_path = Path(path_text).expanduser()
        if not spec_path.parent.exists():
            return JSONResponse({"ok": False, "error": f"spec parent directory does not exist: {spec_path.parent}"})
        try:
            spec_path.write_text(markdown_text, encoding="utf-8")
        except OSError as exc:
            return JSONResponse({"ok": False, "error": str(exc)})
        return JSONResponse(_spec_document_payload(spec_path, markdown_text))

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

    @app.post("/api/specs/init")
    async def api_init_spec(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        path_text = str(payload.get("path", "")).strip()
        if not path_text:
            return ctx.json_error("spec path is required")
        locale = str(payload.get("locale", "zh"))
        try:
            workflow = _workflow_for_spec_template(payload)
        except LooporaError as exc:
            return ctx.json_error(str(exc))
        try:
            created = init_spec_file_for_workflow(Path(path_text).expanduser(), locale=locale, workflow=workflow)
        except (FileExistsError, OSError) as exc:
            return ctx.json_error(str(exc))
        return JSONResponse({"path": str(created.resolve())}, status_code=201)

    @app.post("/api/specs/template")
    async def api_spec_template(request: Request) -> JSONResponse:
        payload = await ctx.read_json_mapping(request)
        try:
            workflow = _workflow_for_spec_template(payload)
        except LooporaError as exc:
            return ctx.json_error(str(exc))
        locale = str(payload.get("locale", "zh"))
        markdown_text = render_spec_template(locale=locale, workflow=workflow)
        role_note_sections = []
        if workflow:
            seen: set[str] = set()
            for role in workflow.get("roles", []):
                if not isinstance(role, dict):
                    continue
                label = normalize_role_display_name(role.get("name"), archetype=role.get("archetype")) or str(role.get("name", "")).strip()
                normalized = label.lower()
                if not label or normalized in seen:
                    continue
                seen.add(normalized)
                role_note_sections.append(
                    {
                        "heading": f"{label} Notes",
                        "role_name": label,
                        "archetype": str(role.get("archetype", "")).strip(),
                    }
                )
        return JSONResponse(
            {
                "ok": True,
                "content": markdown_text,
                "rendered_html": render_safe_markdown_html(markdown_text),
                "role_note_sections": role_note_sections,
            }
        )

    @app.get("/api/system/pick-directory")
    async def api_pick_directory(start_path: str = "") -> JSONResponse:
        if not ctx.access_state["native_dialogs_enabled"]:
            return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = ctx.pick_directory_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-file")
    async def api_pick_spec_file(start_path: str = "") -> JSONResponse:
        if not ctx.access_state["native_dialogs_enabled"]:
            return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = ctx.pick_file_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-bundle-file")
    async def api_pick_bundle_file(start_path: str = "") -> JSONResponse:
        if not ctx.access_state["native_dialogs_enabled"]:
            return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = ctx.pick_file_dialog(start_path or None)
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.get("/api/system/pick-spec-save-path")
    async def api_pick_spec_save_path(start_path: str = "") -> JSONResponse:
        if not ctx.access_state["native_dialogs_enabled"]:
            return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        selected = ctx.pick_save_file_dialog(start_path or None, default_name="spec.md")
        return JSONResponse({"path": selected or "", "cancelled": not selected})

    @app.post("/api/system/reveal-path")
    async def api_reveal_path(request: Request) -> JSONResponse:
        if not ctx.access_state["native_dialogs_enabled"]:
            return ctx.json_error("native dialogs are disabled in network mode; paste a server-side absolute path instead")
        payload = await ctx.read_json_mapping(request)
        target = str(payload.get("path") or "").strip()
        if not target:
            return ctx.json_error("path is required")
        return JSONResponse({"path": ctx.reveal_path_callback(target), "ok": True})
