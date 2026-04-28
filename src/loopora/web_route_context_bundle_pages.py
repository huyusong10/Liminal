from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse

from loopora.markdown_tools import render_safe_markdown_html
from loopora.web_inputs import (
    _normalize_bundle_derive_form,
    _normalize_bundle_import_form,
)


class WebRouteBundlePagesMixin:
    def render_bundles(
        self,
        request: Request,
        *,
        import_values: Mapping[str, object] | None = None,
        import_error: str | None = None,
        derive_values: Mapping[str, object] | None = None,
        derive_error: str | None = None,
    ) -> HTMLResponse:
        loops = self.svc().list_loops()
        bundles = self.svc().list_bundles()
        return self.templates.TemplateResponse(
            request,
            "bundles.html",
            {
                "request": request,
                "bundles": bundles,
                "loops": loops,
                "import_values": _normalize_bundle_import_form(import_values),
                "derive_values": _normalize_bundle_derive_form(derive_values),
                "import_error": import_error,
                "derive_error": derive_error,
                "access_state": self.access_state,
            },
        )

    def render_bundle_detail(
        self,
        request: Request,
        bundle_id: str,
        *,
        values: Mapping[str, object] | None = None,
        form_error: str | None = None,
    ) -> HTMLResponse:
        bundle = self.svc().get_bundle(bundle_id)
        spec_path = Path(self.svc()._bundle_spec_path(bundle_id))
        spec_markdown = spec_path.read_text(encoding="utf-8") if spec_path.exists() else ""
        bundle_yaml = self.svc().export_bundle_yaml(bundle_id)
        exported_bundle = self.svc().export_bundle(bundle_id)
        form_values = {
            "description": str(bundle.get("description", "")),
            "collaboration_summary": str(bundle.get("collaboration_summary", "")),
            "spec_markdown": spec_markdown,
        }
        if values:
            for key in form_values:
                if key in values:
                    form_values[key] = values[key]
        return self.templates.TemplateResponse(
            request,
            "bundle_detail.html",
            {
                "request": request,
                "bundle": bundle,
                "form_values": form_values,
                "form_error": form_error,
                "bundle_yaml": bundle_yaml,
                "control_summary": self.svc()._bundle_control_summary(exported_bundle),
                "spec_rendered_html": render_safe_markdown_html(str(form_values.get("spec_markdown", ""))),
                "access_state": self.access_state,
            },
        )
