from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from loopora.markdown_tools import render_safe_markdown_html
from loopora.providers import list_executor_profiles
from loopora.web_inputs import (
    _archetype_options,
    _builtin_role_templates,
    _decorate_role_definition_overview,
    _normalize_role_definition_form,
    _preferred_request_locale,
    _role_definition_form_values_from_record,
)
from loopora.web_url_utils import safe_local_return_path


class WebRouteRolePagesMixin:
    def render_role_definitions(self, request: Request) -> HTMLResponse:
        role_definitions = [_decorate_role_definition_overview(role_definition) for role_definition in self.svc().list_role_definitions()]
        builtin_role_templates = [item for item in role_definitions if item["source"] == "builtin"]
        custom_role_definitions = [item for item in role_definitions if item["source"] == "custom"]
        return self.templates.TemplateResponse(
            request,
            "role_definitions.html",
            {
                "request": request,
                "role_definitions": role_definitions,
                "builtin_role_templates": builtin_role_templates,
                "custom_role_definitions": custom_role_definitions,
                "access_state": self.access_state,
            },
        )

    def render_new_role_definition(
        self,
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
        role_definition: Mapping[str, object] | None = None,
    ) -> HTMLResponse:
        locale = _preferred_request_locale(request)
        return_to = safe_local_return_path(request.query_params.get("return_to", ""))
        incoming_values = values
        current_role_definition = dict(role_definition) if role_definition else None
        if values is None and current_role_definition is not None:
            values = _role_definition_form_values_from_record(current_role_definition, locale=locale)
        is_builtin_template = bool(current_role_definition and current_role_definition.get("source") == "builtin")
        is_editing_custom = bool(current_role_definition and current_role_definition.get("source") == "custom")
        role_template_locked = current_role_definition is not None
        if is_editing_custom:
            page_copy = {
                "title_zh": "修改这条角色定义，让后续编排都能复用新的版本。",
                "title_en": "Refine this role definition so future orchestrations can reuse it.",
                "body_zh": "这里改的是已经保存的角色定义。保存后，新的编排会继续引用它；已有编排里的角色快照不会被回写。",
                "body_en": "You are editing a saved role definition. Future orchestrations keep reusing it, while existing orchestrations keep their frozen role snapshots.",
                "submit_zh": "保存修改",
                "submit_en": "Save changes",
                "action": f"/roles/{current_role_definition['id']}/edit",
            }
        elif is_builtin_template:
            page_copy = {
                "title_zh": "从内置模板出发，打磨成你团队自己的角色版本。",
                "title_en": "Start from the built-in template, then tailor it into your team’s own role.",
                "body_zh": "这里保留的是模板的核心角色身份，你可以修改名字、执行工具、模型和 prompt；保存时会派生出一条新的自定义角色定义。",
                "body_en": "The core role identity stays fixed here. Adjust the name, executor, model, and prompt, then save a new custom role definition derived from this template.",
                "submit_zh": "保存为新角色",
                "submit_en": "Save as new role",
                "action": "/roles/new",
            }
        else:
            page_copy = {
                "title_zh": "先把角色定义好，后面的编排就能直接拿来用。",
                "title_en": "Define the role once, then let orchestrations reuse it directly.",
                "body_zh": "角色定义保存的是角色名、角色模板、权限边界、默认执行工具、模型和 prompt 模板。编排里选中后，会把这些字段带进去作为角色快照。",
                "body_en": "A role definition stores the role name, role template, permission boundary, default executor, model, and prompt template. When an orchestration selects it, those values are copied in as a role snapshot.",
                "submit_zh": "保存角色",
                "submit_en": "Save role",
                "action": "/roles/new",
            }
        if return_to:
            page_copy["action"] = f"{page_copy['action']}?{urlencode({'return_to': return_to})}"
        form_values = _normalize_role_definition_form(values, locale=locale)
        archetype_options = _archetype_options()
        selected_archetype_option = next(
            (option for option in archetype_options if option["id"] == str(form_values.get("archetype", "builder"))),
            archetype_options[0],
        )
        builtin_prompt_sync_enabled = not is_editing_custom and (
            incoming_values is None or "prompt_markdown" not in incoming_values
        )
        return self.templates.TemplateResponse(
            request,
            "new_role_definition.html",
            {
                "request": request,
                "form_values": form_values,
                "form_error": form_error,
                "page_copy": page_copy,
                "current_role_definition": current_role_definition,
                "archetype_options": archetype_options,
                "selected_archetype_option": selected_archetype_option,
                "page_locale": locale,
                "role_template_locked": role_template_locked,
                "role_template_lock_reason": "builtin" if is_builtin_template else ("existing" if is_editing_custom else "new"),
                "executor_profiles": list_executor_profiles(),
                "builtin_role_templates": _builtin_role_templates(locale=locale),
                "builtin_prompt_sync_enabled": builtin_prompt_sync_enabled,
                "initial_prompt_preview_html": render_safe_markdown_html(
                    str(form_values.get("prompt_markdown", "")),
                    strip_front_matter=True,
                ),
                "access_state": self.access_state,
            },
        )
