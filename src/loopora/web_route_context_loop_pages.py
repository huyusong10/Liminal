from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse

from loopora.markdown_tools import render_safe_markdown_html
from loopora.providers import list_executor_profiles
from loopora.settings import load_recent_workdirs
from loopora.specs import render_spec_template
from loopora.web_inputs import (
    _loop_form_is_pristine,
    _normalize_bundle_import_form,
    _normalize_loop_form,
    _normalize_orchestration_form,
    _orchestration_form_values_from_record,
    _preferred_request_locale,
    _workflow_for_spec_template,
)
from loopora.web_url_utils import safe_local_return_path
from loopora.workflows import (
    available_prompt_templates,
    build_preset_workflow,
    preset_names,
    resolve_prompt_files,
    workflow_preset_copy,
)


class WebRouteLoopPagesMixin:
    def render_new_loop(
        self,
        request: Request,
        *,
        page_mode: str = "choice",
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
        import_values: Mapping[str, object] | None = None,
        import_error: str | None = None,
    ) -> HTMLResponse:
        form_values = _normalize_loop_form(values)
        return self.templates.TemplateResponse(
            request,
            "new_loop.html",
            {
                "request": request,
                "create_page_mode": page_mode,
                "form_values": form_values,
                "pristine_loop_form": _normalize_loop_form(None),
                "form_error": form_error,
                "import_values": _normalize_bundle_import_form(import_values),
                "import_error": import_error,
                "executor_profiles": list_executor_profiles(),
                "orchestrations": self.svc().list_orchestrations(),
                "recent_workdirs": load_recent_workdirs(),
                "allow_draft_restore": form_error is None and _loop_form_is_pristine(form_values),
                "access_state": self.access_state,
            },
        )

    def render_orchestrations(self, request: Request) -> HTMLResponse:
        orchestrations = self.svc().list_orchestrations()
        custom_orchestrations = [item for item in orchestrations if item.get("source") == "custom"]
        builtin_orchestrations = [item for item in orchestrations if item.get("source") == "builtin"]
        return self.templates.TemplateResponse(
            request,
            "orchestrations.html",
            {
                "request": request,
                "orchestrations": orchestrations,
                "custom_orchestrations": custom_orchestrations,
                "builtin_orchestrations": builtin_orchestrations,
                "access_state": self.access_state,
            },
        )

    def render_new_orchestration(
        self,
        request: Request,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
        orchestration: Mapping[str, object] | None = None,
    ) -> HTMLResponse:
        page_locale = _preferred_request_locale(request)
        return_to = safe_local_return_path(request.query_params.get("return_to", ""))
        current_orchestration = dict(orchestration) if orchestration else None
        if values is None and current_orchestration is not None:
            values = _orchestration_form_values_from_record(current_orchestration)
        is_builtin_template = bool(current_orchestration and current_orchestration.get("source") == "builtin")
        is_editing_custom = bool(current_orchestration and current_orchestration.get("source") == "custom")
        if is_builtin_template and current_orchestration is not None:
            form_values = _normalize_orchestration_form(_orchestration_form_values_from_record(current_orchestration))
        else:
            form_values = _normalize_orchestration_form(values)
        if is_editing_custom:
            page_copy = {
                "title_zh": "修改编排，让后续 loop 继续沿着新的流程走。",
                "title_en": "Refine this orchestration before future loops use the new flow.",
                "body_zh": "这里改的是已经保存的流程编排。你可以调整角色定义的引用关系、步骤顺序和收束规则；角色 prompt 和执行方式请回到“角色定义”页修改。",
                "body_en": "You are editing a saved orchestration. Adjust role-definition snapshots, step order, and completion rules here; return to Role Definitions to change prompts or execution settings.",
                "submit_zh": "保存修改",
                "submit_en": "Save changes",
                "action": f"/orchestrations/{current_orchestration['id']}/edit",
            }
        elif is_builtin_template:
            page_copy = {
                "title_zh": "查看默认编排，先理解 Loopora 推荐的循环结构。",
                "title_en": "Inspect the built-in orchestration to understand Loopora's recommended loop shape.",
                "body_zh": "默认编排是固定的，只用于查看和直接复用，不能在这里修改。若要做自己的版本，请新建一条自定义编排，再按需要调整角色快照、步骤顺序和收束规则。",
                "body_en": "Built-in orchestrations are fixed. You can inspect and reuse them directly here, but not modify them. To make your own version, create a custom orchestration and then adjust role snapshots, step order, and completion rules there.",
                "submit_zh": "新建自定义编排",
                "submit_en": "Create custom orchestration",
                "action": "/orchestrations/new",
            }
        else:
            page_copy = {
                "title_zh": "先把步骤工作台搭起来，再让 loop 去执行。",
                "title_en": "Shape the step workbench first, then let loops execute it.",
                "body_zh": "这里默认从空白编排开始。你可以在步骤工具条里载入起手模板、按角色定义添加步骤、重排步骤和检查循环实例图；角色 prompt 与执行配置继续在“角色定义”页维护。",
                "body_en": "This editor starts blank by default. Use the step toolbar to load a starter template, add steps from role definitions, reorder steps, and inspect the loop map. Prompts and execution settings still live in Role Definitions.",
                "submit_zh": "保存编排",
                "submit_en": "Save orchestration",
                "action": "/orchestrations/new",
            }
        if return_to:
            page_copy["action"] = f"{page_copy['action']}?{urlencode({'return_to': return_to})}"
        try:
            spec_template_workflow = _workflow_for_spec_template(form_values)
        except Exception:
            spec_template_workflow = None
        generated_spec_template = render_spec_template(locale=page_locale, workflow=spec_template_workflow)
        spec_practice_markdown = ""
        spec_practice_summary = ""
        spec_practice_markdown_zh = ""
        spec_practice_markdown_en = ""
        spec_practice_summary_zh = ""
        spec_practice_summary_en = ""
        if current_orchestration and current_orchestration.get("source") == "builtin":
            spec_practice_markdown_zh = str(current_orchestration.get("spec_practice_markdown_zh", ""))
            spec_practice_markdown_en = str(current_orchestration.get("spec_practice_markdown_en", ""))
            spec_practice_summary_zh = str(current_orchestration.get("spec_practice_summary_zh", ""))
            spec_practice_summary_en = str(current_orchestration.get("spec_practice_summary_en", ""))
            spec_practice_markdown = spec_practice_markdown_zh if page_locale == "zh" else spec_practice_markdown_en
            spec_practice_summary = spec_practice_summary_zh if page_locale == "zh" else spec_practice_summary_en
        workflow_preset_option_names = list(preset_names())
        selected_workflow_preset = str(form_values.get("workflow_preset", "")).strip()
        if (
            selected_workflow_preset
            and selected_workflow_preset not in workflow_preset_option_names
            and selected_workflow_preset in preset_names(include_hidden=True)
        ):
            workflow_preset_option_names.append(selected_workflow_preset)
        workflow_preset_option_values = [workflow_preset_copy(preset_name) for preset_name in workflow_preset_option_names]
        return self.templates.TemplateResponse(
            request,
            "new_orchestration.html",
            {
                "request": request,
                "form_values": form_values,
                "form_error": form_error,
                "workflow_preset_options": [
                    {
                        "id": preset_name,
                        **copy,
                    }
                    for preset_name, copy in zip(workflow_preset_option_names, workflow_preset_option_values, strict=False)
                ],
                "workflow_preset_bundles": {
                    preset_name: {
                        "copy": copy,
                        "workflow": build_preset_workflow(preset_name),
                        "prompt_files": resolve_prompt_files(build_preset_workflow(preset_name)),
                    }
                    for preset_name, copy in zip(workflow_preset_option_names, workflow_preset_option_values, strict=False)
                },
                "prompt_templates": available_prompt_templates(),
                "role_definitions": self.svc().list_role_definitions(),
                "page_copy": page_copy,
                "current_orchestration": current_orchestration,
                "generated_spec_template_rendered_html": render_safe_markdown_html(generated_spec_template),
                "spec_practice_summary": spec_practice_summary,
                "spec_practice_markdown": spec_practice_markdown,
                "spec_practice_summary_zh": spec_practice_summary_zh,
                "spec_practice_summary_en": spec_practice_summary_en,
                "spec_practice_markdown_zh": spec_practice_markdown_zh,
                "spec_practice_markdown_en": spec_practice_markdown_en,
                "spec_practice_rendered_html": render_safe_markdown_html(spec_practice_markdown) if spec_practice_markdown else "",
                "spec_practice_rendered_html_zh": render_safe_markdown_html(spec_practice_markdown_zh) if spec_practice_markdown_zh else "",
                "spec_practice_rendered_html_en": render_safe_markdown_html(spec_practice_markdown_en) if spec_practice_markdown_en else "",
                "orchestration_locked": is_builtin_template,
                "orchestration_create_from_preset_href": (
                    f"/orchestrations/new?workflow_preset={form_values.get('workflow_preset', 'build_first')}"
                    if is_builtin_template
                    else ""
                ),
                "access_state": self.access_state,
            },
        )
