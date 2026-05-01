from __future__ import annotations

import typer

from loopora.branding import APP_NAME
from loopora.cli_bundle_commands import register_bundle_commands
from loopora.cli_diagnose_commands import register_diagnose_commands
from loopora.cli_shared import spawn_background_worker as _spawn_background_worker
from loopora.cli_loop_commands import register_loop_commands
from loopora.cli_orchestration_commands import register_orchestration_commands
from loopora.cli_prompt_commands import register_prompt_commands
from loopora.cli_role_commands import register_role_commands
from loopora.cli_root_commands import register_root_commands
from loopora.cli_spec_commands import register_spec_commands
from loopora.service import create_service

app = typer.Typer(help=f"{APP_NAME} CLI")
loops_app = typer.Typer(help="Inspect and control saved loops")
orchestrations_app = typer.Typer(help="Create and inspect orchestrations")
roles_app = typer.Typer(help="Create and inspect role definitions")
bundles_app = typer.Typer(help="Import and manage YAML bundles")
spec_app = typer.Typer(help="Work with Markdown loop specs")
prompts_app = typer.Typer(help="Validate and inspect prompt templates")
diagnose_app = typer.Typer(help="Inspect local diagnostics and repair safe historical issues")

app.add_typer(loops_app, name="loops")
app.add_typer(orchestrations_app, name="orchestrations")
app.add_typer(roles_app, name="roles")
app.add_typer(bundles_app, name="bundles")
app.add_typer(spec_app, name="spec")
app.add_typer(prompts_app, name="prompts")
app.add_typer(diagnose_app, name="diagnose")

register_root_commands(app)
register_loop_commands(loops_app)
register_orchestration_commands(orchestrations_app)
register_role_commands(roles_app)
register_bundle_commands(bundles_app)
register_spec_commands(spec_app)
register_prompt_commands(prompts_app)
register_diagnose_commands(diagnose_app)

__all__ = ["_spawn_background_worker", "app", "create_service"]
