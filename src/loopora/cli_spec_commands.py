from __future__ import annotations

from pathlib import Path

import typer

from loopora.cli_shared import (
    FromFileOption,
    JsonOutputOption,
    LocaleOption,
    OrchestrationIdOption,
    WorkflowFileOption,
    WorkflowPresetOption,
    echo_json,
    handle_error,
    role_note_sections_for_workflow,
    resolve_spec_template_workflow,
    spec_document_payload,
)
from loopora.markdown_tools import normalize_markdown_text
from loopora.service import LooporaError
from loopora.specs import SpecError, init_spec_file_for_workflow, read_and_compile, render_spec_template
from loopora.workflows import WorkflowError


def register_spec_commands(spec_app: typer.Typer) -> None:
    @spec_app.command("init")
    def spec_init(
        path: Path = typer.Argument(..., help="Where to create the Markdown template."),
        locale: LocaleOption = "zh",
        workflow_preset: WorkflowPresetOption = "",
    ) -> None:
        """Create a starter Markdown spec."""
        try:
            workflow = {"preset": workflow_preset} if workflow_preset else None
            created = init_spec_file_for_workflow(path, locale=locale, workflow=workflow)
            typer.echo(f"created: {created}")
        except (FileExistsError, OSError) as exc:
            handle_error(exc)

    @spec_app.command("validate")
    def spec_validate(path: Path = typer.Argument(..., exists=True, help="Path to the Markdown spec to validate.")) -> None:
        """Validate a Markdown spec and print the resolved check mode."""
        try:
            _, compiled = read_and_compile(path)
            echo_json(
                {
                    "ok": True,
                    "path": str(path.resolve()),
                    "check_count": len(compiled["checks"]),
                    "check_mode": compiled["check_mode"],
                }
            )
        except (SpecError, FileNotFoundError, OSError) as exc:
            handle_error(exc)

    @spec_app.command("template")
    def spec_template(
        locale: LocaleOption = "zh",
        orchestration_id: OrchestrationIdOption = "",
        workflow_preset: WorkflowPresetOption = "",
        workflow_file: WorkflowFileOption = None,
        json_output: JsonOutputOption = False,
    ) -> None:
        """Render a spec template without writing it to disk."""
        try:
            workflow = resolve_spec_template_workflow(
                orchestration_id=orchestration_id,
                workflow_preset=workflow_preset,
                workflow_file=workflow_file,
            )
            markdown_text = render_spec_template(locale=locale, workflow=workflow)
            if json_output:
                echo_json(
                    {
                        "ok": True,
                        "locale": locale,
                        "markdown": markdown_text,
                        "role_note_sections": role_note_sections_for_workflow(workflow),
                    }
                )
                return
            typer.echo(markdown_text)
        except (LooporaError, WorkflowError, OSError) as exc:
            handle_error(exc)

    @spec_app.command("read")
    def spec_read(path: Path = typer.Argument(..., exists=True, help="Path to the Markdown spec to read.")) -> None:
        """Read a spec document together with rendered HTML and validation status."""
        try:
            markdown_text = path.read_text(encoding="utf-8")
            echo_json(spec_document_payload(path, markdown_text))
        except (FileNotFoundError, OSError) as exc:
            handle_error(exc)

    @spec_app.command("write")
    def spec_write(
        path: Path = typer.Argument(..., help="Spec path to overwrite."),
        from_file: FromFileOption = None,
    ) -> None:
        """Overwrite a spec document from another Markdown file."""
        try:
            if from_file is None:
                raise LooporaError("--from-file is required")
            markdown_text = normalize_markdown_text(from_file.read_text(encoding="utf-8"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(markdown_text, encoding="utf-8")
            echo_json(spec_document_payload(path, markdown_text))
        except (LooporaError, OSError) as exc:
            handle_error(exc)
