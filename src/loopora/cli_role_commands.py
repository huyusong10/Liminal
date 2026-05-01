from __future__ import annotations


import typer

from loopora.cli_shared import (
    ArchetypeOption,
    CommandArgOption,
    CommandCliOption,
    ExecutorModeOption,
    ExecutorOption,
    get_service,
    LocaleOption,
    ModelOption,
    PromptFileOption,
    PromptTemplateOption,
    ReasoningOption,
    build_role_definition_kwargs,
    echo_json,
    handle_error,
)
from loopora.service import LooporaError
from loopora.workflows import WorkflowError


def register_role_commands(roles_app: typer.Typer) -> None:
    @roles_app.command("list")
    def list_roles() -> None:
        """List built-in and custom role definitions."""
        try:
            definitions = get_service().list_role_definitions()
            for item in definitions:
                typer.echo(
                    f"{item['id']}  {item['name']}  source={item.get('source', 'custom')}  "
                    f"archetype={item.get('archetype', 'builder')}  executor={item.get('executor_kind', 'codex')}"
                )
        except LooporaError as exc:
            handle_error(exc)

    @roles_app.command("get")
    def get_role(role_definition_id: str = typer.Argument(..., help="Built-in or custom role definition id.")) -> None:
        """Show one role definition as JSON."""
        try:
            echo_json(get_service().get_role_definition(role_definition_id))
        except LooporaError as exc:
            handle_error(exc)

    @roles_app.command("create")
    def create_role(
        name: str = typer.Option(..., help="Role definition name."),
        archetype: ArchetypeOption = "builder",
        description: str = typer.Option("", help="Optional role description."),
        posture_notes: str = typer.Option("", help="Optional task-scoped posture notes for this role."),
        prompt_file: PromptFileOption = None,
        prompt_template: PromptTemplateOption = "",
        locale: LocaleOption = "zh",
        executor_kind: ExecutorOption = "codex",
        executor_mode: ExecutorModeOption = "preset",
        command_cli: CommandCliOption = "",
        command_arg: CommandArgOption = None,
        model: ModelOption = "",
        reasoning_effort: ReasoningOption = "",
    ) -> None:
        """Create a saved role definition."""
        try:
            payload = build_role_definition_kwargs(
                archetype=archetype,
                prompt_file=prompt_file,
                prompt_template=prompt_template,
                locale=locale,
                posture_notes=posture_notes,
                executor_kind=executor_kind,
                executor_mode=executor_mode,
                command_cli=command_cli,
                command_arg=command_arg,
                model=model,
                reasoning_effort=reasoning_effort,
            )
            role_definition = get_service().create_role_definition(
                name=name,
                description=description,
                **payload,
            )
            echo_json(role_definition)
        except (LooporaError, WorkflowError, OSError, ValueError) as exc:
            handle_error(exc)

    @roles_app.command("derive")
    def derive_role(
        source_id: str = typer.Argument(..., help="Built-in or custom role definition id to derive from."),
        name: str | None = typer.Option(None, help="Name for the new role definition."),
        description: str | None = typer.Option(None, help="Description for the new role definition."),
        posture_notes: str = typer.Option("", help="Optional task-scoped posture notes for this role."),
        prompt_file: PromptFileOption = None,
        prompt_template: PromptTemplateOption = "",
        locale: LocaleOption = "zh",
        executor_kind: ExecutorOption = "",
        executor_mode: ExecutorModeOption = "",
        command_cli: CommandCliOption = "",
        command_arg: CommandArgOption = None,
        model: ModelOption = "",
        reasoning_effort: ReasoningOption = "",
    ) -> None:
        """Create a new role definition derived from an existing one."""
        try:
            service = get_service()
            source = service.get_role_definition(source_id)
            payload = build_role_definition_kwargs(
                archetype=str(source.get("archetype", "builder") or "builder"),
                prompt_file=prompt_file,
                prompt_template=prompt_template,
                locale=locale,
                posture_notes=posture_notes,
                executor_kind=executor_kind,
                executor_mode=executor_mode,
                command_cli=command_cli,
                command_arg=command_arg,
                model=model,
                reasoning_effort=reasoning_effort,
                fallback=source,
            )
            role_definition = service.create_role_definition(
                name=name or f"{source['name']} Copy",
                description=description if description is not None else str(source.get("description", "")),
                **payload,
            )
            echo_json(role_definition)
        except (LooporaError, WorkflowError, OSError, ValueError) as exc:
            handle_error(exc)

    @roles_app.command("update")
    def update_role(
        role_definition_id: str = typer.Argument(..., help="Custom role definition id."),
        name: str | None = typer.Option(None, help="Override the role name."),
        description: str | None = typer.Option(None, help="Override the role description."),
        posture_notes: str = typer.Option("", help="Optional task-scoped posture notes for this role."),
        prompt_file: PromptFileOption = None,
        prompt_template: PromptTemplateOption = "",
        locale: LocaleOption = "zh",
        executor_kind: ExecutorOption = "",
        executor_mode: ExecutorModeOption = "",
        command_cli: CommandCliOption = "",
        command_arg: CommandArgOption = None,
        model: ModelOption = "",
        reasoning_effort: ReasoningOption = "",
    ) -> None:
        """Update a saved custom role definition."""
        try:
            service = get_service()
            current = service.get_role_definition(role_definition_id)
            payload = build_role_definition_kwargs(
                archetype=str(current.get("archetype", "builder") or "builder"),
                prompt_file=prompt_file,
                prompt_template=prompt_template,
                locale=locale,
                posture_notes=posture_notes,
                executor_kind=executor_kind,
                executor_mode=executor_mode,
                command_cli=command_cli,
                command_arg=command_arg,
                model=model,
                reasoning_effort=reasoning_effort,
                fallback=current,
            )
            role_definition = service.update_role_definition(
                role_definition_id,
                name=name if name is not None else current["name"],
                description=description if description is not None else str(current.get("description", "")),
                prompt_ref=str(current.get("prompt_ref", "")),
                **payload,
            )
            echo_json(role_definition)
        except (LooporaError, WorkflowError, OSError, ValueError) as exc:
            handle_error(exc)

    @roles_app.command("delete")
    def delete_role(role_definition_id: str = typer.Argument(..., help="Custom role definition id.")) -> None:
        """Delete a saved custom role definition."""
        try:
            echo_json(get_service().delete_role_definition(role_definition_id))
        except LooporaError as exc:
            handle_error(exc)
