from __future__ import annotations

from pathlib import Path

import typer

from loopora.cli_shared import ArchetypeOption, LocaleOption, echo_json, handle_error
from loopora.workflows import WorkflowError, available_prompt_templates, builtin_prompt_markdown, validate_prompt_markdown


def register_prompt_commands(prompts_app: typer.Typer) -> None:
    @prompts_app.command("list")
    def list_prompts() -> None:
        """List built-in prompt templates."""
        try:
            echo_json(available_prompt_templates())
        except WorkflowError as exc:
            handle_error(exc)

    @prompts_app.command("template")
    def prompt_template(prompt_ref: str = typer.Argument(..., help="Built-in prompt template ref."), locale: LocaleOption = "zh") -> None:
        """Print one built-in prompt template."""
        try:
            typer.echo(builtin_prompt_markdown(prompt_ref, locale=locale))
        except WorkflowError as exc:
            handle_error(exc)

    @prompts_app.command("validate")
    def prompt_validate(
        path: Path = typer.Argument(..., exists=True, help="Path to the prompt Markdown file to validate."),
        archetype: ArchetypeOption = "",
    ) -> None:
        """Validate prompt Markdown and print parsed metadata."""
        try:
            markdown_text = path.read_text(encoding="utf-8")
            metadata, body = validate_prompt_markdown(markdown_text, expected_archetype=archetype or None)
            echo_json({"ok": True, "metadata": metadata, "body": body})
        except (WorkflowError, OSError) as exc:
            handle_error(exc)
