from __future__ import annotations

from fastapi import Request
from fastapi.responses import HTMLResponse

from loopora.markdown_tools import render_safe_markdown_html
from loopora.skills import list_task_alignment_skill_targets, load_task_alignment_skill_bundle


class WebRouteHelpPagesMixin:
    def render_tutorial(self, request: Request) -> HTMLResponse:
        orchestrations = self.svc().list_orchestrations()
        builtin_orchestrations = [dict(item) for item in orchestrations if item.get("source") == "builtin"]
        tutorial_order = {
            "build_first": 0,
            "inspect_first": 1,
            "triage_first": 2,
            "repair_loop": 3,
            "benchmark_loop": 4,
        }
        builtin_orchestrations.sort(key=lambda item: tutorial_order.get(str(item.get("preset", "")), 99))
        tutorial_spec_practices: dict[str, dict[str, str]] = {}

        def tutorial_teaser(summary: str, *, locale: str) -> str:
            text = str(summary or "").strip()
            if locale == "zh" and text.startswith("场景："):
                return text.removeprefix("场景：").strip()
            if locale == "en" and text.lower().startswith("scenario:"):
                _, _, remainder = text.partition(":")
                return remainder.strip()
            return text

        for orchestration in builtin_orchestrations:
            summary_zh = str(orchestration.get("spec_practice_summary_zh", "")).strip()
            summary_en = str(orchestration.get("spec_practice_summary_en", "")).strip()
            markdown_zh = str(orchestration.get("spec_practice_markdown_zh", "")).strip()
            markdown_en = str(orchestration.get("spec_practice_markdown_en", "")).strip()
            orchestration["tutorial_teaser_zh"] = tutorial_teaser(summary_zh, locale="zh")
            orchestration["tutorial_teaser_en"] = tutorial_teaser(summary_en, locale="en")
            tutorial_spec_practices[str(orchestration.get("id", ""))] = {
                "name": str(orchestration.get("name", "")).strip(),
                "summary_zh": summary_zh,
                "summary_en": summary_en,
                "rendered_html_zh": render_safe_markdown_html(markdown_zh) if markdown_zh else "",
                "rendered_html_en": render_safe_markdown_html(markdown_en) if markdown_en else "",
            }
        return self.templates.TemplateResponse(
            request,
            "tutorial.html",
            {
                "request": request,
                "builtin_orchestrations": builtin_orchestrations,
                "tutorial_spec_practices": tutorial_spec_practices,
                "access_state": self.access_state,
            },
        )

    def render_tools(self, request: Request) -> HTMLResponse:
        return self.templates.TemplateResponse(
            request,
            "tools.html",
            {
                "request": request,
                "skill_bundle": load_task_alignment_skill_bundle(),
                "skill_targets": list_task_alignment_skill_targets(),
                "access_state": self.access_state,
            },
        )
