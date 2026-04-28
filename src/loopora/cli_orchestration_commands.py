from __future__ import annotations

import typer

from loopora.cli_shared import (
    RoleModelOption,
    WorkflowFileOption,
    WorkflowPresetOption,
    echo_json,
    get_service,
    handle_error,
    parse_role_models,
    resolve_workflow_bundle,
    workflow_bundle_from_entity,
)
from loopora.service import LooporaError
from loopora.workflows import DEFAULT_WORKFLOW_PRESET, WorkflowError


def register_orchestration_commands(orchestrations_app: typer.Typer) -> None:
    @orchestrations_app.command("list")
    def list_orchestrations() -> None:
        """List saved orchestrations."""
        try:
            service = get_service()
            orchestrations = service.list_orchestrations()
            for item in orchestrations:
                typer.echo(
                    f"{item['id']}  {item['name']}  "
                    f"source={item.get('source', 'custom')}  "
                    f"roles={len(item.get('workflow_json', {}).get('roles', []))}  "
                    f"steps={len(item.get('workflow_json', {}).get('steps', []))}"
                )
        except LooporaError as exc:
            handle_error(exc)

    @orchestrations_app.command("get")
    def get_orchestration(orchestration_id: str = typer.Argument(..., help="Saved orchestration id.")) -> None:
        """Show one orchestration as JSON."""
        try:
            echo_json(get_service().get_orchestration(orchestration_id))
        except LooporaError as exc:
            handle_error(exc)

    @orchestrations_app.command("create")
    def create_orchestration(
        name: str = typer.Option(..., help="Orchestration name."),
        description: str = typer.Option("", help="Optional orchestration description."),
        workflow_preset: WorkflowPresetOption = DEFAULT_WORKFLOW_PRESET,
        workflow_file: WorkflowFileOption = None,
        role_model: RoleModelOption = None,
    ) -> None:
        """Create a saved orchestration."""
        try:
            service = get_service()
            workflow, prompt_files = resolve_workflow_bundle(
                workflow_file=workflow_file,
                workflow_preset=workflow_preset,
            )
            orchestration = service.create_orchestration(
                name=name,
                description=description,
                workflow=workflow,
                prompt_files=prompt_files,
                role_models=parse_role_models(role_model),
            )
            echo_json(orchestration)
        except LooporaError as exc:
            handle_error(exc)

    @orchestrations_app.command("update")
    def update_orchestration(
        orchestration_id: str = typer.Argument(..., help="Custom orchestration id."),
        name: str | None = typer.Option(None, help="Override the orchestration name."),
        description: str | None = typer.Option(None, help="Override the orchestration description."),
        workflow_preset: WorkflowPresetOption = "",
        workflow_file: WorkflowFileOption = None,
        role_model: RoleModelOption = None,
    ) -> None:
        """Update a saved custom orchestration."""
        try:
            service = get_service()
            current = service.get_orchestration(orchestration_id)
            current_workflow, current_prompt_files = workflow_bundle_from_entity(current)
            workflow, prompt_files = resolve_workflow_bundle(
                workflow_file=workflow_file,
                workflow_preset=workflow_preset,
                fallback_workflow=current_workflow,
                fallback_prompt_files=current_prompt_files,
            )
            orchestration = service.update_orchestration(
                orchestration_id,
                name=name if name is not None else current["name"],
                description=description if description is not None else str(current.get("description", "")),
                workflow=workflow,
                prompt_files=prompt_files,
                role_models=parse_role_models(role_model) or current.get("role_models_json") or current.get("role_models") or {},
            )
            echo_json(orchestration)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @orchestrations_app.command("derive")
    def derive_orchestration(
        source_id: str = typer.Argument(..., help="Built-in or custom orchestration id to derive from."),
        name: str | None = typer.Option(None, help="Name for the new derived orchestration."),
        description: str | None = typer.Option(None, help="Description for the new derived orchestration."),
        workflow_preset: WorkflowPresetOption = "",
        workflow_file: WorkflowFileOption = None,
        role_model: RoleModelOption = None,
    ) -> None:
        """Create a new orchestration derived from an existing one."""
        try:
            service = get_service()
            source = service.get_orchestration(source_id)
            source_workflow, source_prompt_files = workflow_bundle_from_entity(source)
            workflow, prompt_files = resolve_workflow_bundle(
                workflow_file=workflow_file,
                workflow_preset=workflow_preset,
                fallback_workflow=source_workflow,
                fallback_prompt_files=source_prompt_files,
            )
            orchestration = service.create_orchestration(
                name=name or f"{source['name']} Copy",
                description=description if description is not None else str(source.get("description", "")),
                workflow=workflow,
                prompt_files=prompt_files,
                role_models=parse_role_models(role_model) or source.get("role_models_json") or source.get("role_models") or {},
            )
            echo_json(orchestration)
        except (LooporaError, WorkflowError) as exc:
            handle_error(exc)

    @orchestrations_app.command("delete")
    def delete_orchestration(orchestration_id: str = typer.Argument(..., help="Custom orchestration id.")) -> None:
        """Delete a saved custom orchestration."""
        try:
            echo_json(get_service().delete_orchestration(orchestration_id))
        except LooporaError as exc:
            handle_error(exc)
